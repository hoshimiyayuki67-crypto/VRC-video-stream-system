import os, time, json, secrets, string, sqlite3, hashlib, subprocess
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from werkzeug.utils import secure_filename
from functools import wraps
import threading

app = Flask(__name__)
app.secret_key = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(64))
CORS(app, supports_credentials=True)

BASE_DIR = "/home/yuki/vd"
ALLOWED_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "flv", "wmv", "webm", "m4v"}
MEDIAMTX_RTMP = "rtmp://127.0.0.1:1935/vrcstream"
HLS_BASE = f"http://{os.environ.get('DOMAIN', 'localhost')}:{os.environ.get('HLS_PORT', '8888')}/vrcstream"
os.makedirs(BASE_DIR, exist_ok=True)

streams = {}

# 非管理员限制
NONADMIN_MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
NONADMIN_MAX_TOTAL_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
NONADMIN_STREAM_MAX_HOURS = 4  # 4小时自动停止

def check_expired_streams():
    while True:
        now = time.time()
        to_stop = []
        for uid, info in list(streams.items()):
            if info["process"].poll() is not None:
                to_stop.append(uid)
                continue
            # Check if non-admin and expired
            db = get_db()
            cur = db.execute("SELECT role FROM users WHERE uid=?", (uid,))
            u = cur.fetchone()
            db.close()
            if u and u["role"] != "admin":
                started = datetime.strptime(info["started_at"], "%Y-%m-%d %H:%M:%S")
                elapsed = (datetime.now() - started).total_seconds()
                if elapsed > NONADMIN_STREAM_MAX_HOURS * 3600:
                    to_stop.append(uid)
        for uid in to_stop:
            stop_user(uid)
        time.sleep(60)  # 每分钟检查一次

# 启动后台检查线程
t = threading.Thread(target=check_expired_streams, daemon=True)
t.start()

def get_db():
    db = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT DEFAULT 'user', created_at TEXT DEFAULT (datetime('now','localtime')))")
    db.execute("CREATE TABLE IF NOT EXISTS invite_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, created_by TEXT NOT NULL, expires_at TEXT NOT NULL, used_by TEXT, used_at TEXT)")
    # 管理员账号由安装脚本创建
    db.commit()
    db.close()

init_db()

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

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
    db.execute("INSERT INTO users (uid, password_hash) VALUES (?, ?)", (uid, hash_pw(pw)))
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
    db.close()
    if not u or u["password_hash"] != hash_pw(pw):
        return jsonify({"error":"Wrong ID or password"}), 401
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

# ===== Admin Invite Codes =====
@app.route("/api/admin/invite/generate", methods=["POST"])
@admin_required
def gen_invite():
    d = request.get_json()
    hours = int(d.get("hours", 24))
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
                videos.append({"name":f,"size":f"{os.path.getsize(fp)/1024/1024:.1f} MB","modified":time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(os.path.getmtime(fp)))})
    return videos

@app.route("/api/videos")
@login_required
def api_videos():
    uid = session["uid"]
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
        # Check admin status
        db = get_db()
        cur = db.execute("SELECT role FROM users WHERE uid=?", (uid,))
        u = cur.fetchone()
        db.close()
        is_admin = u and u["role"] == "admin"
        
        if not is_admin:
            # 检查单文件大小上限
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            f.seek(0)
            if file_size > NONADMIN_MAX_FILE_SIZE:
                return jsonify({"error":"单文件不能超过2GB"}), 400
            
            # 检查总容量上限
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
        if uid in streams and streams[uid]["filename"] == fn:
            stop_user(uid)
        os.remove(fp)
        return jsonify({"success":True})
    return jsonify({"error":"Not found"}), 404

# ===== Stream =====
def stop_user(uid):
    if uid in streams:
        p = streams[uid]["process"]
        if p and p.poll() is None:
            p.terminate()
            try: p.wait(timeout=5)
            except: p.kill()
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
    proc = subprocess.Popen(["ffmpeg","-re","-stream_loop","-1","-i",fp,"-c","copy","-f","flv",rtmp],
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
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
    us = streams.get(uid)
    on = us and us["process"].poll() is None
    return jsonify({"is_streaming":on,"current_stream":us["filename"] if on else None,"stream_url":f"{HLS_BASE}/{uid}/index.m3u8" if on else None,"stream_path":f"vrcstream/{uid}"})

# ===== Pages =====
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=13333, debug=False)
