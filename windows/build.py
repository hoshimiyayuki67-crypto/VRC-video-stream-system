"""
Windows GUI 构建脚本
使用 PyWebView + PyInstaller 将 Flask Web 应用打包为 Windows EXE
运行方式: cd windows && python build.py
"""
import os, sys, subprocess, shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
DIST = Path(__file__).parent / "dist"
BIN = Path(__file__).parent / "bin"

DIST.mkdir(parents=True, exist_ok=True)

# 检查二进制依赖
ffmpeg_exe = BIN / "ffmpeg.exe"
mediamtx_exe = BIN / "mediamtx.exe"
if not ffmpeg_exe.exists():
    print("[ERROR] ffmpeg.exe not found"); sys.exit(1)
if not mediamtx_exe.exists():
    print("[ERROR] mediamtx.exe not found"); sys.exit(1)

# 写入启动入口
launcher = '''\
import os, sys, threading, time, subprocess

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "VRCStream")
os.makedirs(DATA_DIR, exist_ok=True)

# 必须在 import app 之前设置，确保数据库和所有文件创建在正确位置
os.environ["VRC_DATA_DIR"] = DATA_DIR

if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
    os.chdir(os.path.dirname(sys.executable))
else:
    bundle_dir = os.path.dirname(os.path.abspath(__file__))

from app.app import app as flask_app

# PyInstaller 打包后修正模板路径
if getattr(sys, 'frozen', False):
    flask_app.template_folder = os.path.join(bundle_dir, 'app', 'templates')

BASE = os.path.dirname(os.path.abspath(sys.argv[0]))
MTX = os.path.join(BASE, "bin", "mediamtx.exe")
MTX_CFG = os.path.join(BASE, "config", "mediamtx.yml")
mtx_proc = None

if os.path.exists(MTX):
    mtx_proc = subprocess.Popen(
        [MTX, MTX_CFG],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=DATA_DIR
    )

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
'''

launcher_path = ROOT / "pywebview_app.py"
with open(launcher_path, "w", encoding="utf-8") as f:
    f.write(launcher)

print(f"[OK] Launcher written: {launcher_path}")

# 复制 mediamtx 配置
mtx_cfg_src = ROOT / "config" / "mediamtx.yml"
mtx_cfg_dst = ROOT / "windows" / "mediamtx.yml"
shutil.copy2(mtx_cfg_src, mtx_cfg_dst)
print(f"[OK] MediaMTX config copied")

# PyInstaller spec
spec = f"""# -*- mode: python -*-
a = Analysis(
    [{repr(str(launcher_path))}],
    pathex=[{repr(str(ROOT))}],
    binaries=[
        ({repr(str(BIN / 'mediamtx.exe'))}, 'bin'),
        ({repr(str(BIN / 'ffmpeg.exe'))}, 'bin'),
    ],
    datas=[
        ({repr(str(ROOT / 'app' / 'templates' / 'index.html'))}, 'app/templates'),
        ({repr(str(ROOT / 'app' / 'templates' / 'admin.html'))}, 'app/templates'),
        ({repr(str(ROOT / 'app' / 'templates' / 'setup.html'))}, 'app/templates'),
        ({repr(str(mtx_cfg_dst))}, 'config'),
    ],
    hiddenimports=['app', 'app.app', 'flask', 'flask_cors', 'webview', 'sqlite3', 'html'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VRCStream',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)
"""

spec_path = ROOT / "VRCStream.spec"
with open(spec_path, "w", encoding="utf-8") as f:
    f.write(spec)

print("[BUILD] Running PyInstaller...")
subprocess.run([
    sys.executable, "-m", "PyInstaller",
    "--distpath", str(DIST),
    "--workpath", str(ROOT / "build_temp"),
    "--clean", "--noconfirm",
    str(spec_path)
], check=True, cwd=str(ROOT))

exe_path = DIST / "VRCStream.exe"
if exe_path.exists():
    print(f"[OK] Build complete: {exe_path}")
else:
    print("[ERROR] EXE not found")
    sys.exit(1)
