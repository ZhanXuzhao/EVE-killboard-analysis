"""
PyInstaller 打包脚本 — 将 Streamlit App 打包为单目录 exe。

用法：
    python build_exe.py

输出目录： dist/EVE-killboard-analysis/
"""
import sys
import subprocess
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_SCRIPT = ROOT / "run_app.py"
OUT_DIR = ROOT / "dist"
APP_NAME = "EVE-Killboard-Analysis"

# ── 确保 PyInstaller 已安装 ───────────────────────────
try:
    import PyInstaller  # noqa
except ImportError:
    print("正在安装 PyInstaller ...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "pyinstaller", "-q"]
    )

# ── 额外数据文件 ──────────────────────────────────────
# 需要随 exe 分发的文件（data 下的缓存文件）
data_files = []
data_dir = ROOT / "data"
for f in data_dir.iterdir():
    if f.is_file():
        data_files.append(f"--add-data")
        data_files.append(f"{f}{os.pathsep}data/")

# ── PyInstaller 命令 ──────────────────────────────────
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--clean",
    "--noconfirm",
    "--onedir",                              # 单目录模式（比 --onefile 更稳定）
    f"--name={APP_NAME}",
    f"--distpath={OUT_DIR}",
    f"--workpath={ROOT / 'build'}",
    f"--specpath={ROOT / 'build'}",
    "--add-data", f"{ROOT / 'src'}{os.pathsep}src",
    # Streamlit 及其依赖的完整收集
    "--collect-all", "streamlit",
    "--collect-all", "plotly",
    "--collect-all", "altair",
    "--collect-all", "markdown",
    "--collect-all", "pandas",
    "--collect-all", "requests",
    "--collect-all", "pillow",
    "--collect-all", "protobuf",
    "--collect-all", "tornado",
    "--collect-all", "watchdog",
    # 常见隐藏导入
    "--hidden-import", "streamlit",
    "--hidden-import", "streamlit.web.cli",
    "--hidden-import", "streamlit.runtime.scriptrunner",
    "--hidden-import", "streamlit.runtime.caching",
    "--hidden-import", "streamlit.elements.lib",
    "--hidden-import", "plotly.express",
    "--hidden-import", "plotly.graph_objects",
    "--hidden-import", "pandas",
    "--hidden-import", "requests",
    "--hidden-import", "sqlite3",
    "--hidden-import", "json",
    "--hidden-import", "pathlib",
    "--hidden-import", "altair",
    "--hidden-import", "pkg_resources",
    "--hidden-import", "pkgutil",
    "--hidden-import", "importlib.metadata",
    "--hidden-import", "importlib.resources",
    # 添加数据文件
] + data_files + [
    str(APP_SCRIPT),
]

print("=" * 60)
print(f"  🚀 正在打包 {APP_NAME} ...")
print(f"  入口脚本: {APP_SCRIPT}")
print(f"  输出目录: {OUT_DIR / APP_NAME}")
print("=" * 60)
print()

subprocess.check_call(cmd)

print()
print("=" * 60)
print(f"  ✅ 打包完成！")
print(f"  输出路径: {OUT_DIR / APP_NAME}")
print(f"  运行方式: 双击 {OUT_DIR / APP_NAME / f'{APP_NAME}.exe'}")
print("=" * 60)
