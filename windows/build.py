"""
Windows GUI 构建脚本
使用 PyWebView 将 Flask Web 应用打包为 Windows EXE
依赖：pyinstaller, pywebview
"""
import os, sys, subprocess, shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
DIST = Path(__file__).parent / "dist"
BIN = Path(__file__).parent / "bin"
APP_DIR = ROOT / "app"

# 确保 bin 目录存在
DIST.mkdir(parents=True, exist_ok=True)

# 检查二进制依赖
ffmpeg_exe = BIN / "ffmpeg.exe"
mediamtx_exe = BIN / "mediamtx.exe"

if not ffmpeg_exe.exists():
    print("❌ ffmpeg.exe 未找到，请先运行 CI 下载步骤")
    sys.exit(1)
if not mediamtx_exe.exists():
    print("❌ mediamtx.exe 未找到，请先运行 CI 下载步骤")
    sys.exit(1)

# 创建桌面启动入口 pywebview_app.py
launcher = """\
import os, sys, threading, time, subprocess, signal
import webview
from app import app as flask_app

BASE = os.path.dirname(os.path.abspath(sys.argv[0]))
DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "VRCStream")
os.makedirs(DATA, exist_ok=True)

# 修改 Flask 的数据目录到用户 AppData
import app as app_module
app_module.BASE_DIR = DATA

# 启动 MediaMTX 和 FFmpeg 检查
MTX = os.path.join(BASE, "bin", "mediamtx.exe")
FFMPEG = os.path.join(BASE, "bin", "ffmpeg.exe")
MTX_CFG = os.path.join(BASE, "config", "mediamtx.yml")

mtx_proc = None

def start_mtx():
    global mtx_proc
    if os.path.exists(MTX):
        mtx_proc = subprocess.Popen(
            [MTX, MTX_CFG],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=DATA
        )

def start_flask():
    flask_app.run(host="127.0.0.1", port=13333, debug=False)

mtx_thread = threading.Thread(target=start_mtx, daemon=True)
mtx_thread.start()
time.sleep(1)

flask_thread = threading.Thread(target=start_flask, daemon=True)
flask_thread.start()
time.sleep(1)

# 创建 WebView 窗口
window = webview.create_window(
    "VRCStream - 视频推流系统",
    "http://127.0.0.1:13333",
    width=1000, height=750,
    resizable=True, min_size=(800, 600)
)

def on_closed():
    if mtx_proc:
        mtx_proc.terminate()

window.events.closed += on_closed
webview.start()
"""

with open(ROOT / "pywebview_app.py", "w", encoding="utf-8") as f:
    f.write(launcher)

# 复制必要文件
shutil.copy2(ROOT / "config" / "mediamtx.yml", ROOT / "config" / "mediamtx.yml")

# PyInstaller 打包
spec_content = f"""\
# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['pywebview_app.py'],
    pathex=[{repr(str(ROOT))}],
    binaries=[],
    datas=[
        ('app/templates/*.html', 'app/templates'),
        ('config/mediamtx.yml', 'config'),
        ('bin/*.exe', 'bin'),
    ],
    hiddenimports=['app', 'flask', 'flask_cors', 'webview', 'sqlite3'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
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
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"""

with open(ROOT / "VRCStream.spec", "w", encoding="utf-8") as f:
    f.write(spec_content)

# 运行 PyInstaller
subprocess.run([
    sys.executable, "-m", "PyInstaller",
    "--distpath", str(DIST),
    "--workpath", str(ROOT / "build_temp"),
    "--specpath", str(ROOT),
    "--clean", "--noconfirm",
    str(ROOT / "VRCStream.spec")
], check=True)

print(f"✅ 构建完成: {DIST / 'VRCStream.exe'}")
