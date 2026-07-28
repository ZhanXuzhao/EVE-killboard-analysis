"""SQLite 数据库初始化与连接管理。"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from src.config import DATA_DIR, DB_PATH

logger = logging.getLogger(__name__)


def get_write_connection() -> sqlite3.Connection:
    """获取读写数据库连接（适用于 INSERT/UPDATE/DELETE）。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_read_connection() -> sqlite3.Connection:
    """获取只读数据库连接（适用于 SELECT 查询，不阻塞写入）。"""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db_write():
    """获取读写数据库连接的上下文管理器（用于写入，自动提交/回滚）。"""
    conn = get_write_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_db_read():
    """获取只读数据库连接的上下文管理器（用于查询，不提交，不阻塞写入）。"""
    conn = get_read_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """初始化数据库表结构。"""
    with get_db_write() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS killmails (
                killmail_id          INTEGER PRIMARY KEY,
                killmail_time        TEXT NOT NULL,
                solar_system_id      INTEGER,
                solar_system_name    TEXT,
                solar_system_region_name TEXT,
                war_id               INTEGER,

                victim_character_id   INTEGER,
                victim_character_name TEXT,
                victim_corporation_id  INTEGER,
                victim_corporation_name TEXT,
                victim_alliance_id     INTEGER,
                victim_alliance_name   TEXT,
                victim_ship_type_id    INTEGER,
                victim_ship_name       TEXT,
                victim_damage_taken    INTEGER,

                isk_destroyed        REAL,
                total_attackers      INTEGER,
                npc_kill             INTEGER DEFAULT 0,

                fetched_at           TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS attackers (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                killmail_id      INTEGER NOT NULL REFERENCES killmails(killmail_id),
                character_id     INTEGER,
                character_name   TEXT,
                corporation_id   INTEGER,
                corporation_name TEXT,
                alliance_id      INTEGER,
                alliance_name    TEXT,
                ship_type_id     INTEGER,
                ship_name        TEXT,
                weapon_type_id   INTEGER,
                weapon_name      TEXT,
                damage_done      INTEGER,
                final_blow       INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS items (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                killmail_id        INTEGER NOT NULL REFERENCES killmails(killmail_id),
                item_type_id       INTEGER,
                item_name          TEXT,
                quantity_dropped   INTEGER DEFAULT 0,
                quantity_destroyed INTEGER DEFAULT 0,
                flag               INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_killmail_time ON killmails(killmail_time);
            CREATE INDEX IF NOT EXISTS idx_victim_corp ON killmails(victim_corporation_id);
            CREATE INDEX IF NOT EXISTS idx_attacker_corp ON attackers(corporation_id);
            CREATE INDEX IF NOT EXISTS idx_attacker_km   ON attackers(killmail_id);
            CREATE INDEX IF NOT EXISTS idx_items_km      ON items(killmail_id);

            CREATE TABLE IF NOT EXISTS fetch_log (
                entity_id      INTEGER NOT NULL,
                entity_type    TEXT NOT NULL,
                date_from      TEXT NOT NULL,
                date_to        TEXT NOT NULL,
                fetched_at     TEXT NOT NULL DEFAULT (datetime('now')),
                killmail_count INTEGER DEFAULT 0,
                complete       INTEGER DEFAULT 0,
                PRIMARY KEY (entity_id, entity_type, date_from, date_to)
            );

            -- ID→名称缓存表（含类别）
            CREATE TABLE IF NOT EXISTS id_name_cache (
                entity_id INTEGER PRIMARY KEY,
                name      TEXT NOT NULL,
                category  TEXT
            );

            -- 星系→星域缓存表
            CREATE TABLE IF NOT EXISTS system_region_cache (
                system_id        INTEGER PRIMARY KEY,
                region_name      TEXT NOT NULL,
                security_status  REAL
            );

            -- 中英文翻译对照表（舰船/物品/星域等）
            CREATE TABLE IF NOT EXISTS type_translations (
                type_id   INTEGER PRIMARY KEY,
                name_zh   TEXT NOT NULL,
                name_en   TEXT
            );
        """)

        # 兼容旧数据库：新增列
        for col in ["solar_system_region_name"]:
            try:
                conn.execute(f"ALTER TABLE killmails ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # 列已存在
        try:
            conn.execute("ALTER TABLE system_region_cache ADD COLUMN security_status REAL")
        except sqlite3.OperationalError:
            pass
            try:
                conn.execute(f"ALTER TABLE killmails ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # 列已存在

        # 兼容旧数据库：id_name_cache 新增 category 列
        try:
            conn.execute("ALTER TABLE id_name_cache ADD COLUMN category TEXT")
        except sqlite3.OperationalError:
            pass

    # 迁移旧 JSON 缓存到数据库
    _migrate_json_cache()

    # 从种子文件初始化 type_translations（空表时自动加载）
    _load_type_translations_seed()

    # 从种子文件初始化 system_region_cache（空表时自动加载）
    _load_system_region_seed()

    # 从种子文件初始化 id_name_cache（空表时自动加载）
    _load_id_name_cache_seed()


def _load_type_translations_seed():
    """如果 type_translations 为空，从种子 JSON 文件初始化。"""
    seed_path = DATA_DIR / "type_translations_seed.json"
    if not seed_path.exists():
        return
    try:
        with get_db_read() as conn:
            count = conn.execute("SELECT COUNT(*) FROM type_translations").fetchone()[0]
        if count > 0:
            return  # 已有数据，跳过
        logger.info("📦 从种子文件初始化 type_translations ...")
        with open(seed_path, encoding="utf-8") as f:
            data = json.load(f)
        rows = []
        for tid, vals in data.items():
            if isinstance(vals, dict):
                rows.append((int(tid), vals.get("zh", ""), vals.get("en", "")))
            elif isinstance(vals, list) and len(vals) >= 2:
                rows.append((int(tid), vals[0], vals[1]))
        with get_db_write() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO type_translations (type_id, name_zh, name_en) VALUES (?, ?, ?)",
                rows,
            )
        logger.info(f"   ✅ 加载 {len(rows)} 条翻译数据")
    except Exception as e:
        logger.warning(f"加载翻译种子文件失败: {e}")


def _load_system_region_seed():
    """如果 system_region_cache 为空，从种子 JSON 文件初始化（星系→星域映射及安全等级）。"""
    seed_path = DATA_DIR / "system_region_seed.json"
    if not seed_path.exists():
        return
    try:
        with get_db_read() as conn:
            count = conn.execute("SELECT COUNT(*) FROM system_region_cache").fetchone()[0]
        if count > 0:
            return  # 已有数据，跳过
        logger.info("📦 从种子文件初始化 system_region_cache ...")
        with open(seed_path, encoding="utf-8") as f:
            data = json.load(f)
        rows = []
        for sid, vals in data.items():
            region_name = vals["region_name"] if isinstance(vals, dict) else vals
            security_status = vals.get("security_status") if isinstance(vals, dict) else None
            rows.append((int(sid), region_name, security_status))
        with get_db_write() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO system_region_cache (system_id, region_name, security_status) VALUES (?, ?, ?)",
                rows,
            )
        logger.info(f"   ✅ 加载 {len(rows)} 条星系星域数据")
    except Exception as e:
        logger.warning(f"加载星系星域种子文件失败: {e}")


def _load_id_name_cache_seed():
    """如果 id_name_cache 为空，从种子 JSON 文件初始化（ID→名称映射）。"""
    seed_path = DATA_DIR / "id_name_seed.json"
    if not seed_path.exists():
        return
    try:
        with get_db_read() as conn:
            count = conn.execute("SELECT COUNT(*) FROM id_name_cache").fetchone()[0]
        if count > 0:
            return  # 已有数据，跳过
        logger.info("📦 从种子文件初始化 id_name_cache ...")
        with open(seed_path, encoding="utf-8") as f:
            data = json.load(f)
        rows = []
        for eid, vals in data.items():
            if isinstance(vals, dict):
                rows.append((int(eid), vals["name"], vals.get("category")))
            else:
                rows.append((int(eid), vals, None))
        with get_db_write() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO id_name_cache (entity_id, name, category) VALUES (?, ?, ?)",
                rows,
            )
        logger.info(f"   ✅ 加载 {len(rows)} 条 ID 名称数据")
    except Exception as e:
        logger.warning(f"加载 ID 名称种子文件失败: {e}")


def _migrate_json_cache():
    """将旧的 JSON 缓存文件导入到数据库表中。"""
    _migrate_single_cache(
        table="system_region_cache",
        json_file=DATA_DIR / "system_region_cache.json",
        key_col="system_id",
        val_col="region_name",
    )
    _migrate_single_cache(
        table="id_name_cache",
        json_file=DATA_DIR / "id_name_cache.json",
        key_col="entity_id",
        val_col="name",
    )


def _migrate_single_cache(table: str, json_file: Path, key_col: str, val_col: str):
    """将单个 JSON 缓存文件导入到数据库表中，已存在的记录跳过。"""
    if not json_file.exists():
        return
    try:
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return
        with get_db_write() as conn:
            count = 0
            for k, v in data.items():
                try:
                    conn.execute(
                        f"INSERT OR IGNORE INTO {table} ({key_col}, {val_col}) VALUES (?, ?)",
                        (int(k), v),
                    )
                    if conn.total_changes:
                        count += 1
                except (ValueError, sqlite3.OperationalError):
                    continue
            logger.info(
                "迁移 %s: %d 条记录（总 %d）",
                json_file.name, count, len(data),
            )
        # 迁移成功后重命名 JSON 文件（保留备份）
        backup = json_file.with_suffix(".json.bak")
        json_file.rename(backup)
        logger.info("旧缓存 %s → %s", json_file.name, backup.name)
    except Exception as e:
        logger.warning("迁移 %s 失败: %s", json_file.name, e)


# ── ID→名称 缓存操作 ────────────────────────────────────


def get_id_name(entity_id: int) -> Optional[str]:
    """从缓存中查询单个 ID 的名称。"""
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT name FROM id_name_cache WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        return row["name"] if row else None


def has_id_name(entity_id: int) -> bool:
    """检查 ID 是否在缓存中。"""
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT 1 FROM id_name_cache WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        return row is not None


def batch_get_id_names(entity_ids: list[int]) -> dict[int, str]:
    """批量查询缓存中的 ID→名称。"""
    if not entity_ids:
        return {}
    placeholders = ",".join("?" * len(entity_ids))
    with get_db_read() as conn:
        rows = conn.execute(
            f"SELECT entity_id, name FROM id_name_cache WHERE entity_id IN ({placeholders})",
            entity_ids,
        ).fetchall()
        return {row["entity_id"]: row["name"] for row in rows}


def batch_set_id_names(name_map: dict[int, str]):
    """批量写入 ID→名称到缓存（兼容旧调用，category 留 NULL）。"""
    if not name_map:
        return
    with get_db_write() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO id_name_cache (entity_id, name) VALUES (?, ?)",
            list(name_map.items()),
        )


def batch_upsert_id_names(name_map: dict[int, tuple[str, str]]):
    """批量写入 ID→(名称, 类别) 到缓存。

    Args:
        name_map: {entity_id: (name, category)}
    """
    if not name_map:
        return
    with get_db_write() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO id_name_cache (entity_id, name, category) VALUES (?, ?, ?)",
            [(eid, name, cat) for eid, (name, cat) in name_map.items()],
        )


def batch_fill_category(category_map: dict[int, str]):
    """增量更新已有记录的 category（仅更新 category 为 NULL 的记录）。"""
    if not category_map:
        return
    with get_db_write() as conn:
        conn.executemany(
            "UPDATE id_name_cache SET category = ? WHERE entity_id = ? AND category IS NULL",
            [(cat, eid) for eid, cat in category_map.items()],
        )


def batch_get_ids_missing_category(entity_ids: list[int]) -> list[int]:
    """返回缓存中 category 为 NULL 的 ID 子集。"""
    if not entity_ids:
        return []
    placeholders = ",".join("?" * len(entity_ids))
    with get_db_read() as conn:
        rows = conn.execute(
            f"SELECT entity_id FROM id_name_cache WHERE entity_id IN ({placeholders}) AND category IS NULL",
            entity_ids,
        ).fetchall()
        return [r["entity_id"] for r in rows]


# ── 星系→星域 缓存操作 ──────────────────────────────────


def get_system_region(system_id: int) -> Optional[str]:
    """从缓存中查询星系对应的星域名称。"""
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT region_name FROM system_region_cache WHERE system_id = ?",
            (system_id,),
        ).fetchone()
        return row["region_name"] if row else None


def has_system_region(system_id: int) -> bool:
    """检查星系是否在缓存中。"""
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT 1 FROM system_region_cache WHERE system_id = ?",
            (system_id,),
        ).fetchone()
        return row is not None


def batch_get_system_regions(system_ids: list[int]) -> dict[int, str]:
    """批量查询缓存中的星系→星域。"""
    if not system_ids:
        return {}
    placeholders = ",".join("?" * len(system_ids))
    with get_db_read() as conn:
        rows = conn.execute(
            f"SELECT system_id, region_name FROM system_region_cache WHERE system_id IN ({placeholders})",
            system_ids,
        ).fetchall()
        return {row["system_id"]: row["region_name"] for row in rows}


def batch_get_system_data(system_ids: list[int]) -> dict[int, dict]:
    """批量查询缓存中的星系数据（星域名 + 安全等级）。"""
    if not system_ids:
        return {}
    placeholders = ",".join("?" * len(system_ids))
    with get_db_read() as conn:
        rows = conn.execute(
            f"SELECT system_id, region_name, security_status FROM system_region_cache WHERE system_id IN ({placeholders})",
            system_ids,
        ).fetchall()
        return {row["system_id"]: {"region_name": row["region_name"], "security_status": row["security_status"]} for row in rows}


def set_system_region(system_id: int, region_name: str, security_status: float = None):
    """写入星系→星域到缓存。"""
    with get_db_write() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_region_cache (system_id, region_name, security_status) VALUES (?, ?, ?)",
            (system_id, region_name, security_status),
        )


# ── 中英文翻译查询 ─────────────────────────────────────


def get_name_zh(type_id: int) -> Optional[str]:
    """查询 type_id 对应的中文名称，无则返回 None。"""
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT name_zh FROM type_translations WHERE type_id = ?",
            (type_id,),
        ).fetchone()
        return row["name_zh"] if row else None


def batch_get_names_zh(type_ids: list[int]) -> dict[int, str]:
    """批量查询多个 type_id 的中文名称。"""
    if not type_ids:
        return {}
    placeholders = ",".join("?" * len(type_ids))
    with get_db_read() as conn:
        rows = conn.execute(
            f"SELECT type_id, name_zh FROM type_translations WHERE type_id IN ({placeholders})",
            type_ids,
        ).fetchall()
        return {row["type_id"]: row["name_zh"] for row in rows}
