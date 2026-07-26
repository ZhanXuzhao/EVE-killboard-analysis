"""Streamlit 应用启动器 — 用于 PyInstaller 打包。

直接运行：  python run_app.py
打包后 exe 会自动启动 Streamlit 服务器并打开浏览器。
"""
import sys
import os
import webbrowser
from pathlib import Path
from threading import Timer

# ── 确保项目根目录在 sys.path 中 ──────────────────────
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# ── 端口 ──────────────────────────────────────────────
PORT = 8501


def _open_browser():
    """延迟打开浏览器。"""
    webbrowser.open_new(f"http://localhost:{PORT}/")


if __name__ == "__main__":
    # 切换到项目根目录，确保 data/ 等相对路径正确
    os.chdir(str(_root))

    # 延迟 2 秒打开浏览器（等 Streamlit 启动）
    Timer(2.0, _open_browser).start()

    # 启动 Streamlit
    from streamlit.web import cli as st_cli

    sys.argv = ["streamlit", "run", str(_root / "src" / "app.py"),
                "--server.port", str(PORT),
                "--server.headless", "true",
                "--browser.serverAddress", "localhost",
                "--browser.gatherUsageStats", "false"]
    sys.exit(st_cli.main())
