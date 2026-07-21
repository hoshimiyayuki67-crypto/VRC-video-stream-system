"""
Windows GUI 构建脚本
使用 PyInstaller 将 Flask 应用 + 启动器打包为 EXE
运行方式: cd windows && python build.py
"""
import os, sys, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = Path(__file__).resolve().parent / "dist"
BIN = Path(__file__).resolve().parent / "bin"
LAUNCHER = Path(__file__).resolve().parent / "launcher.py"

DIST.mkdir(parents=True, exist_ok=True)

# 检查二进制依赖
if not (BIN / "ffmpeg.exe").exists():
    print("[ERROR] ffmpeg.exe not found"); sys.exit(1)
if not (BIN / "mediamtx.exe").exists():
    print("[ERROR] mediamtx.exe not found"); sys.exit(1)

# 复制 launcher 到项目根（PyInstaller 需要从此处解析 app 模块）
launcher_dst = ROOT / "launcher.py"
with open(LAUNCHER, "r", encoding="utf-8") as src:
    with open(launcher_dst, "w", encoding="utf-8") as dst:
        dst.write(src.read())
print(f"[OK] Launcher: {launcher_dst}")

# 复制 mediamtx 配置（已存在于 windows/）
mtx_cfg = ROOT / "windows" / "mediamtx.yml"

# PyInstaller spec
templates_dir = ROOT / "windows" / "app" / "templates"
spec = f"""# -*- mode: python -*-
a = Analysis(
    [{repr(str(launcher_dst))}],
    pathex=[{repr(str(ROOT))}],
    binaries=[
        ({repr(str(BIN / 'mediamtx.exe'))}, 'bin'),
        ({repr(str(BIN / 'ffmpeg.exe'))}, 'bin'),
    ],
    datas=[
        ({repr(str(templates_dir / 'index.html'))}, 'app/templates'),
        ({repr(str(templates_dir / 'admin.html'))}, 'app/templates'),
        ({repr(str(templates_dir / 'setup.html'))}, 'app/templates'),
        ({repr(str(mtx_cfg))}, 'config'),
    ],
    hiddenimports=['windows.app', 'windows.app.app', 'flask', 'flask_cors', 'webview', 'sqlite3', 'html'],
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
