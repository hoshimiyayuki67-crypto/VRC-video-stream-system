import os, time, json, secrets, string, sqlite3, hashlib, subprocess, threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from werkzeug.utils import secure_filename
from functools import wraps
import html

app = Flask(__name__)

# 持久化 secret_key，避免重启后 session 失效
SECRET_KEY_FILE = os.path.join(os.environ.get("VRC_DATA_DIR", "/opt/video_data"), "secret_key")
def load_or_create_secret_key():
    try:
        with open(SECRET_KEY_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        key = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(64))
        os.makedirs(os.path.dirname(SECRET_KEY_FILE), exist_ok=True)
        with open(SECRET_KEY_FILE, "w") as f:
            f.write(key)
        return key

app.secret_key = load_or_create_secret_key()
CORS(app, supports_credentials=True)

BASE_DIR = os.environ.get("VRC_DATA_DIR", "/opt/video_data")
ALLOWED_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "flv", "wmv", "webm", "m4v"}
MEDIAMTX_RTMP = "rtmp://127.0.0.1:1935/vrcstream"
HLS_BASE = f"http://{os.environ.get('DOMAIN', 'localhost')}:{os.environ.get('HLS_PORT', '8888')}/vrcstream"
os.makedirs(BASE_DIR, exist_ok=True)

streams = {}
streams_lock = threading.Lock()

# 非管理员限制
NONADMIN_MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
NONADMIN_MAX_TOTAL_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
NONADMIN_STREAM_MAX_HOURS = 4

def check_expired_streams():
    """后台线程：每分钟检查过期推流"""
    while True:
        try:
            now = time.time()
            to_stop = []
            # 批量获取所有非管理员 UID
            db = get_db()
            admin_uid = None
            cur = db.execute("SELECT uid FROM users WHERE role='admin'")
            admins = {r["uid"] for r in cur.fetchall()}
            db.close()

            with streams_lock:
                for uid, info in list(streams.items()):
                    if info["process"].poll() is not None:
                        to_stop.append(uid)
                        continue
                    if uid not in admins:
                        started = datetime.strptime(info["started_at"], "%Y-%m-%d %H:%M:%S")
                        elapsed = (datetime.now() - started).total_seconds()
                        if elapsed > NONADMIN_STREAM_MAX_HOURS * 3600:
                            to_stop.append(uid)
            for uid in to_stop:
                stop_user(uid)
        except Exception:
            pass  # 异常不退出线程
        time.sleep(60)

t = threading.Thread(target=check_expired_streams, daemon=True)
t.start()

def get_db():
    db = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, salt TEXT, role TEXT DEFAULT 'user', created_at TEXT DEFAULT (datetime('now','localtime')))")
    db.execute("CREATE TABLE IF NOT EXISTS invite_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, created_by TEXT NOT NULL, expires_at TEXT NOT NULL, used_by TEXT, used_at TEXT)")
    # 兼容旧表：如果缺少 salt 列则添加
    try:
        db.execute("SELECT salt FROM users LIMIT 0")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE users ADD COLUMN salt TEXT")
    db.commit()
    db.close()

init_db()

# === 密码哈希（加盐 PBKDF2，兼容旧 SHA256） ===
def hash_pw(pw, salt=None):
    """生成加盐哈希，返回 (hash, salt)"""
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100000)
    return h.hex(), salt

def hash_pw_legacy(pw):
    """旧版 SHA256（向后兼容）"""
    return hashlib.sha256(pw.encode()).hexdigest()

def verify_pw(pw, stored_hash, salt):
    """验证密码，兼容旧格式"""
    if salt:
        h, _ = hash_pw(pw, salt)
        return h == stored_hash
    else:
        return hash_pw_legacy(pw) == stored_hash

# === 装饰器 ===
def login_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if "uid" not in session:
            return jsonify({"error": "Not logged in"}), 401
        return f(*a, **kw)
    return wrap

def admin_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if "uid" not in session:
            return jsonify({"error": "Not logged in"}), 401
        if session.get("role") != "admin":
            return jsonify({"error": "Admin required"}), 403
        return f(*a, **kw)
    return wrap

def user_dir(uid):
    p = os.path.join(BASE_DIR, uid)
    os.makedirs(p, exist_ok=True)
    return p

def get_user_total_size(uid):
    total = 0
    d = user_dir(uid)
    if os.path.exists(d):
        for f in os.listdir(d):
            fp = os.path.join(d, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total

def e(text):
    """HTML 转义"""
    return html.escape(str(text), quote=True)

# ===== Auth =====
@app.route("/api/auth/register", methods=["POST"])
def register():
    d = request.get_json()
    uid = d.get("uid","").strip()
    pw = d.get("password","")
    code = d.get("invite_code","").strip()
    if not uid or not pw or not code:
        return jsonify({"error":"Fill all fields"}), 400
    if len(uid) < 2 or len(uid) > 20:
        return jsonify({"error":"ID 2-20 chars"}), 400
    if len(pw) < 6:
        return jsonify({"error":"Password min 6 chars"}), 400
    db = get_db()
    cur = db.execute("SELECT * FROM invite_codes WHERE code=? AND used_by IS NULL", (code,))
    inv = cur.fetchone()
    if not inv:
        db.close()
        return jsonify({"error":"Invalid invite code"}), 400
    exp = datetime.strptime(inv["expires_at"], "%Y-%m-%d %H:%M:%S")
    if datetime.now() > exp:
        db.close()
        return jsonify({"error":"Invite code expired"}), 400
    cur = db.execute("SELECT id FROM users WHERE uid=?", (uid,))
    if cur.fetchone():
        db.close()
        return jsonify({"error":"ID already taken"}), 400
    pw_hash, pw_salt = hash_pw(pw)
    db.execute("INSERT INTO users (uid, password_hash, salt) VALUES (?, ?, ?)", (uid, pw_hash, pw_salt))
    db.execute("UPDATE invite_codes SET used_by=?, used_at=datetime('now','localtime') WHERE code=?", (uid, code))
    db.commit()
    db.close()
    user_dir(uid)
    return jsonify({"success":True,"message":"Registered!"})

@app.route("/api/auth/login", methods=["POST"])
def login():
    d = request.get_json()
    uid = d.get("uid","").strip()
    pw = d.get("password","")
    db = get_db()
    cur = db.execute("SELECT * FROM users WHERE uid=?", (uid,))
    u = cur.fetchone()
    if not u or not verify_pw(pw, u["password_hash"], u["salt"]):
        db.close()
        return jsonify({"error":"Wrong ID or password"}), 401
    # 自动升级旧密码格式
    if not u["salt"]:
        new_hash, new_salt = hash_pw(pw)
        db.execute("UPDATE users SET password_hash=?, salt=? WHERE uid=?", (new_hash, new_salt, uid))
        db.commit()
    db.close()
    session["uid"] = u["uid"]
    session["role"] = u["role"]
    return jsonify({"success":True, "uid":u["uid"], "role":u["role"]})

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success":True})

@app.route("/api/auth/me")
def auth_me():
    if "uid" in session:
        return jsonify({"uid":session["uid"],"role":session["role"]})
    return jsonify({"uid":None}), 401

# ===== Config API（前端获取动态配置） =====
@app.route("/api/config")
def api_config():
    return jsonify({"hls_base": HLS_BASE, "hls_port": os.environ.get("HLS_PORT", "8888")})

# ===== Admin Invite Codes =====
@app.route("/api/admin/invite/generate", methods=["POST"])
@admin_required
def gen_invite():
    d = request.get_json()
    try:
        hours = int(d.get("hours", 24))
    except (ValueError, TypeError):
        return jsonify({"error":"Hours must be a number"}), 400
    if hours < 1 or hours > 720:
        return jsonify({"error":"1-720 hours"}), 400
    code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    exp = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    db.execute("INSERT INTO invite_codes (code, created_by, expires_at) VALUES (?,?,?)", (code, session["uid"], exp))
    db.commit()
    db.close()
    return jsonify({"success":True,"code":code,"expires_at":exp})

@app.route("/api/admin/invite/list")
@admin_required
def list_invites():
    db = get_db()
    rows = db.execute("SELECT * FROM invite_codes ORDER BY id DESC").fetchall()
    db.close()
    now = datetime.now()
    return jsonify({"invites":[{
        "id":r["id"],"code":r["code"],"created_by":r["created_by"],
        "expires_at":r["expires_at"],"expired":now>datetime.strptime(r["expires_at"],"%Y-%m-%d %H:%M:%S"),
        "used_by":r["used_by"],"used_at":r["used_at"]
    } for r in rows]})

@app.route("/api/admin/invite/delete", methods=["POST"])
@admin_required
def del_invite():
    d = request.get_json()
    db = get_db()
    db.execute("DELETE FROM invite_codes WHERE id=?", (d.get("id"),))
    db.commit()
    db.close()
    return jsonify({"success":True})

@app.route("/api/admin/users")
@admin_required
def list_users():
    db = get_db()
    rows = db.execute("SELECT id, uid, role, created_at FROM users ORDER BY id").fetchall()
    db.close()
    return jsonify({"users":[dict(r) for r in rows]})

@app.route("/api/admin/streams")
@admin_required
def admin_streams():
    active = {}
    with streams_lock:
        for uid, info in streams.items():
            if info["process"].poll() is None:
                active[uid] = {"filename":info["filename"],"started_at":info["started_at"],"stream_url":f"{HLS_BASE}/{uid}/index.m3u8"}
    return jsonify({"active_streams":active})

# ===== Videos =====
def allowed_file(fn):
    return "." in fn and fn.rsplit(".",1)[1].lower() in ALLOWED_EXTENSIONS

def user_videos(uid):
    videos = []
    d = user_dir(uid)
    if os.path.exists(d):
        for f in sorted(os.listdir(d), reverse=True):
            fp = os.path.join(d, f)
            if os.path.isfile(fp) and allowed_file(f):
                videos.append({
                    "name": f,
                    "name_escaped": e(f),  # 前端安全渲染
                    "size": f"{os.path.getsize(fp)/1024/1024:.1f} MB",
                    "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(fp)))
                })
    return videos

@app.route("/api/videos")
@login_required
def api_videos():
    uid = session["uid"]
    with streams_lock:
        us = streams.get(uid)
        cur = us["filename"] if us and us["process"].poll() is None else None
    return jsonify({"videos":user_videos(uid),"current_stream":cur,"stream_path":f"vrcstream/{uid}"})

@app.route("/api/upload", methods=["POST"])
@login_required
def upload_file():
    uid = session["uid"]
    if "file" not in request.files:
        return jsonify({"error":"No file"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error":"No file selected"}), 400
    if f and allowed_file(f.filename):
        db = get_db()
        cur = db.execute("SELECT role FROM users WHERE uid=?", (uid,))
        u = cur.fetchone()
        db.close()
        is_admin = u and u["role"] == "admin"

        if not is_admin:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            f.seek(0)
            if file_size > NONADMIN_MAX_FILE_SIZE:
                return jsonify({"error":"单文件不能超过2GB"}), 400
            total = get_user_total_size(uid)
            if total + file_size > NONADMIN_MAX_TOTAL_SIZE:
                return jsonify({"error":"总容量已超过5GB上限，无法上传"}), 400

        fn = secure_filename(f.filename)
        base, ext = os.path.splitext(fn)
        c = 1
        d = user_dir(uid)
        while os.path.exists(os.path.join(d, fn)):
            fn = f"{base}_{c}{ext}"
            c += 1
        f.save(os.path.join(d, fn))
        return jsonify({"success":True,"filename":fn})
    return jsonify({"error":"Unsupported format"}), 400

@app.route("/api/delete", methods=["POST"])
@login_required
def delete_video():
    uid = session["uid"]
    d = request.get_json()
    fn = d.get("filename","")
    fp = os.path.join(user_dir(uid), fn)
    if os.path.exists(fp):
        with streams_lock:
            if uid in streams and streams[uid]["filename"] == fn:
                stop_user(uid)
        os.remove(fp)
        return jsonify({"success":True})
    return jsonify({"error":"Not found"}), 404

# ===== Stream =====
def stop_user(uid):
    """停止指定用户的推流（线程安全）"""
    with streams_lock:
        if uid in streams:
            p = streams[uid]["process"]
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
            del streams[uid]

@app.route("/api/stream/start", methods=["POST"])
@login_required
def start_stream():
    uid = session["uid"]
    d = request.get_json()
    fn = d.get("filename","")
    if not fn:
        return jsonify({"error":"No file"}), 400
    fp = os.path.join(user_dir(uid), fn)
    if not os.path.exists(fp):
        return jsonify({"error":"File not found"}), 404
    stop_user(uid)
    rtmp = f"{MEDIAMTX_RTMP}/{uid}"
    proc = subprocess.Popen(
        ["ffmpeg","-re","-stream_loop","-1","-i",fp,"-c","copy","-f","flv",rtmp],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    with streams_lock:
        streams[uid] = {"process":proc,"filename":fn,"started_at":time.strftime("%Y-%m-%d %H:%M:%S")}
    return jsonify({"success":True,"message":f"Streaming: {fn}","stream_url":f"{HLS_BASE}/{uid}/index.m3u8"})

@app.route("/api/stream/stop", methods=["POST"])
@login_required
def stop_stream():
    stop_user(session["uid"])
    return jsonify({"success":True,"message":"Stopped"})

@app.route("/api/stream/status")
@login_required
def stream_status():
    uid = session["uid"]
    with streams_lock:
        us = streams.get(uid)
        on = us and us["process"].poll() is None
    return jsonify({
        "is_streaming": on,
        "current_stream": us["filename"] if on else None,
        "stream_url": f"{HLS_BASE}/{uid}/index.m3u8" if on else None,
        "stream_path": f"vrcstream/{uid}"
    })

# ===== Pages =====
@app.route("/")
def index():
    return render_template("index.html", hls_base=HLS_BASE)

@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html", hls_base=HLS_BASE)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=13333, debug=False)
