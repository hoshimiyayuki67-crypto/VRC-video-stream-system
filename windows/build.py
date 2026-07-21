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
    print("❌ ffmpeg.exe 未找到"); sys.exit(1)
if not mediamtx_exe.exists():
    print("❌ mediamtx.exe 未找到"); sys.exit(1)

# 写入启动入口
launcher = '''\
import os, sys, threading, time, subprocess

# 修正导入路径 (PyInstaller 打包后)
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from app.app import app as flask_app
import app.app as app_module

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "VRCStream")
os.makedirs(DATA_DIR, exist_ok=True)
app_module.BASE_DIR = DATA_DIR

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
'''

launcher_path = ROOT / "pywebview_app.py"
with open(launcher_path, "w", encoding="utf-8") as f:
    f.write(launcher)

print(f"✅ 启动入口已生成: {launcher_path}")

# 复制 mediamtx 配置到 windows 目录 (供 PyInstaller 打包)
mtx_cfg_src = ROOT / "config" / "mediamtx.yml"
mtx_cfg_dst = ROOT / "windows" / "mediamtx.yml"
shutil.copy2(mtx_cfg_src, mtx_cfg_dst)
print(f"✅ MediaMTX 配置已复制")

# PyInstaller 打包
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

print(f"📦 开始 PyInstaller 打包...")
subprocess.run([
    sys.executable, "-m", "PyInstaller",
    "--distpath", str(DIST),
    "--workpath", str(ROOT / "build_temp"),
    "--specpath", str(ROOT),
    "--clean", "--noconfirm",
    str(spec_path)
], check=True, cwd=str(ROOT))

exe_path = DIST / "VRCStream.exe"
if exe_path.exists():
    print(f"✅ 构建完成: {exe_path}")
else:
    print("❌ 构建失败: EXE 未生成")
    sys.exit(1)
