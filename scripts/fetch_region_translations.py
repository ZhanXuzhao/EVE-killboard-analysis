"""从 ESI 拉取星域中英文翻译，存入 type_translations 表。

用法：
    python scripts/fetch_region_translations.py

从 ESI 获取全部 114 个星域的 (region_id, name_zh, name_en)，
写入 type_translations 表。仅首次需要，之后永久缓存。
"""

import logging
import sqlite3
import sys
import time
from pathlib import Path

import requests

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from src.config import DB_PATH, USER_AGENT, REQUEST_TIMEOUT

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT})


def main():
    t0 = time.time()

    # 1. 获取所有星域 ID
    logger.info("📡 获取星域列表...")
    resp = _SESSION.get(
        "https://esi.evetech.net/latest/universe/regions/?datasource=tranquility",
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    region_ids = sorted(resp.json())
    logger.info(f"   ✅ 共 {len(region_ids)} 个星域")

    # 2. 逐个获取中英文名
    rows = []
    for i, rid in enumerate(region_ids, 1):
        try:
            # 中文名
            r_zh = _SESSION.get(
                f"https://esi.evetech.net/latest/universe/regions/{rid}/?language=zh",
                timeout=REQUEST_TIMEOUT,
            )
            r_zh.raise_for_status()
            name_zh = r_zh.json().get("name", "")

            # 英文名
            r_en = _SESSION.get(
                f"https://esi.evetech.net/latest/universe/regions/{rid}/",
                timeout=REQUEST_TIMEOUT,
            )
            r_en.raise_for_status()
            name_en = r_en.json().get("name", "")

            rows.append((rid, name_zh, name_en))
            if i % 20 == 0:
                logger.info(f"   ... {i}/{len(region_ids)}")
        except Exception as e:
            logger.warning(f"   ⚠️  星域 {rid} 获取失败: {e}")

        time.sleep(0.3)  # ESI 限速保护

    # 3. 写入 type_translations
    logger.info(f"\n💾 写入 {len(rows)} 条到 type_translations...")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executemany(
        "INSERT OR REPLACE INTO type_translations (type_id, name_zh, name_en) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

    elapsed = time.time() - t0
    logger.info(f"✅ 完成！耗时 {elapsed:.1f}s")
    logger.info("💡 重启 Streamlit 后星域将默认显示中文。")


if __name__ == "__main__":
    main()
