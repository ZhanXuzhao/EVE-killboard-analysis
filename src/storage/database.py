"""SQLite 数据库初始化与连接管理。"""

import sqlite3
from contextlib import contextmanager
from src.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """获取数据库连接（自动提交模式）。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    """获取数据库连接的上下文管理器。"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化数据库表结构。"""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS killmails (
                killmail_id          INTEGER PRIMARY KEY,
                killmail_time        TEXT NOT NULL,
                solar_system_id      INTEGER,
                solar_system_name    TEXT,
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
        """)
