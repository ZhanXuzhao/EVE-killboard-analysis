"""EVE Killboard Analysis - Configuration."""

import os
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent

# 数据目录
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# SQLite 数据库路径
DB_PATH = DATA_DIR / "killboard.db"

# zKillboard API 基础 URL
ZKILLBOARD_BASE_URL = "https://zkillboard.com/api"

# 请求间隔（秒）- 避免被限流
REQUEST_INTERVAL = 0.5

# HTTP 请求超时（秒）
REQUEST_TIMEOUT = 30

# 用户代理，zKillboard 要求设置
USER_AGENT = "EVE-Killboard-Analysis/1.0 (contact@example.com)"
