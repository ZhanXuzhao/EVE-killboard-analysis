"""从 CCP 官方 SDE 下载并导入中文翻译到 SQLite。

用法：
    python scripts/fetch_translations.py

首次运行会自动下载 SDE zip（约 200MB），然后从 fsd/types.yaml 中提取
所有类型（舰船/物品等）的 typeID、中文名、英文名，存入数据库。

SDE 数据格式：types.yaml 中每个条目直接包含 name.en 和 name.zh。
"""

import logging
import sqlite3
import zipfile
import shutil
import sys
import time
from pathlib import Path

# ── 项目路径 ──────────────────────────────────────────

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from src.config import DATA_DIR, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SDE_ZIP_URL = (
    "https://eve-static-data-export.s3-eu-west-1.amazonaws.com/tranquility/sde.zip"
)
SDE_ZIP_PATH = DATA_DIR / "sde.zip"


# ── 下载 SDE ──────────────────────────────────────────

def download_sde():
    """下载 SDE zip（仅当本地不存在时）。"""
    if SDE_ZIP_PATH.exists():
        size_mb = SDE_ZIP_PATH.stat().st_size // 1024 // 1024
        logger.info(f"📦 SDE 已存在 ({size_mb}MB)")
        return True

    logger.info("⬇️  正在下载 SDE（约 200MB）...")
    import requests

    try:
        resp = requests.get(SDE_ZIP_URL, stream=True, timeout=300)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(SDE_ZIP_PATH, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    if pct % 10 == 0:
                        logger.info(f"   ... {pct}% ({downloaded // 1024 // 1024}MB)")
        logger.info("✅ 下载完成")
        return True
    except Exception as e:
        logger.error(f"❌ 下载失败: {e}")
        return False


# ── 解析 types.yaml（直接从 zip 流式读取）─────────────

def import_translations():
    """从 SDE zip 中的 fsd/types.yaml 解析中英文名并写入数据库。"""
    import yaml

    logger.info("")
    logger.info("🔍 解析 types.yaml（直接从 zip 读取）...")

    zf = zipfile.ZipFile(str(SDE_ZIP_PATH), "r")
    raw = yaml.safe_load(zf.open("fsd/types.yaml"))
    zf.close()

    if not isinstance(raw, dict):
        logger.error("❌ types.yaml 格式异常")
        return False

    logger.info(f"   ✅ 读取到 {len(raw)} 个类型条目")

    # 收集有中文名的条目
    rows = []
    zh_count = 0
    t0 = time.time()
    for tid, info in raw.items():
        name = info.get("name", {}) or {}
        name_zh = name.get("zh", "").strip()
        name_en = name.get("en", "").strip()
        if name_zh:
            zh_count += 1
            rows.append((int(tid), name_zh, name_en))

    elapsed = time.time() - t0
    logger.info(f"   ✅ 有中文名的条目: {zh_count} / {len(raw)}（解析耗时 {elapsed:.1f}s）")

    # 写入数据库
    logger.info("")
    logger.info("💾 写入数据库...")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    # 分批写入，避免事务过大
    BATCH_SIZE = 5000
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        conn.executemany(
            "INSERT OR REPLACE INTO type_translations (type_id, name_zh, name_en) VALUES (?, ?, ?)",
            batch,
        )
        conn.commit()
        total += len(batch)
        logger.info(f"   ... {total}/{zh_count}")

    conn.close()
    logger.info(f"✅ 导入完成: {total} 条中文名")
    return True


# ── 清理 ──────────────────────────────────────────────

def cleanup():
    """删除 SDE zip 临时文件。"""
    if SDE_ZIP_PATH.exists():
        SDE_ZIP_PATH.unlink()
        logger.info(f"🧹 已删除: {SDE_ZIP_PATH.name}")

    # 也清理旧的解压目录
    old_dir = DATA_DIR / "sde_bsd"
    if old_dir.exists():
        shutil.rmtree(old_dir, ignore_errors=True)


# ── 主流程 ────────────────────────────────────────────

def main():
    t0 = time.time()

    # 1. 确保数据库表存在
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS type_translations (
            type_id   INTEGER PRIMARY KEY,
            name_zh   TEXT NOT NULL,
            name_en   TEXT
        );
    """)
    conn.commit()
    conn.close()

    # 2. 下载 SDE
    if not download_sde():
        sys.exit(1)

    # 3. 解析并导入
    if not import_translations():
        sys.exit(1)

    elapsed = time.time() - t0
    logger.info(f"⏱  总耗时: {elapsed:.1f}s")

    # 询问清理
    print()
    ans = input("🧹 是否删除 SDE zip 临时文件？（y/N）: ").strip().lower()
    if ans == "y":
        cleanup()

    logger.info("💡 重启 Streamlit 后舰船名将默认显示中文。")


if __name__ == "__main__":
    main()
