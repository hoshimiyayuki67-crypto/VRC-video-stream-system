"""
Windows GUI 启动器 — 使用 PyWebView 嵌入 Flask
PyInstaller 打包入口: pyinstaller VRCStream.spec
"""
import os, sys, threading, time, subprocess

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 必须在 import app 之前设置，确保数据库创建在正确位置
os.environ["VRC_DATA_DIR"] = DATA_DIR

if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
    os.chdir(os.path.dirname(sys.executable))
    # 将 bin 目录加入 PATH，让 flask 能找到 ffmpeg
    bin_dir = os.path.join(bundle_dir, "bin")
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
else:
    bundle_dir = os.path.dirname(os.path.abspath(__file__))

from windows.app.app import app as flask_app

# PyInstaller 打包后修正模板路径
if getattr(sys, 'frozen', False):
    flask_app.template_folder = os.path.join(bundle_dir, "app", "templates")

# 启动 MediaMTX（路径基于 bundle_dir，即 _MEIPASS）
MTX = os.path.join(bundle_dir, "bin", "mediamtx.exe")
MTX_CFG = os.path.join(bundle_dir, "config", "mediamtx.yml")
mtx_proc = None

if os.path.exists(MTX) and os.path.exists(MTX_CFG):
    mtx_proc = subprocess.Popen(
        [MTX, MTX_CFG],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=DATA_DIR
    )
    print(f"[OK] MediaMTX started")
else:
    print(f"[WARN] MediaMTX not found: MTX={os.path.exists(MTX)} CFG={os.path.exists(MTX_CFG)}")

def start_flask():
    flask_app.run(host="127.0.0.1", port=13333, debug=False)

flask_thread = threading.Thread(target=start_flask, daemon=True)
flask_thread.start()
time.sleep(1.5)

import webview
window = webview.create_window(
    "VRCStream - Video Stream System",
    "http://127.0.0.1:13333",
    width=1000, height=750,
    resizable=True, min_size=(800, 600)
)

def on_closed():
    if mtx_proc:
        mtx_proc.terminate()

window.events.closed += on_closed
webview.start()
