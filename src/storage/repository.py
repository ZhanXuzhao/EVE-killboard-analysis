"""数据访问层 — 击杀数据的写入与查询。"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from src.storage.database import get_db


# ── 写入 ─────────────────────────────────────────────────


def save_killmail(killmail: dict, attackers: list[dict], items: list[dict]):
    """保存一条击杀邮件及其攻击者、物品到数据库。"""
    zkb = killmail.get("zkb", {})
    victim = killmail.get("victim", {})

    with get_db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO killmails (
                killmail_id, killmail_time,
                solar_system_id, solar_system_name, solar_system_region_name, war_id,
                victim_character_id, victim_character_name,
                victim_corporation_id, victim_corporation_name,
                victim_alliance_id, victim_alliance_name,
                victim_ship_type_id, victim_ship_name,
                victim_damage_taken,
                isk_destroyed, total_attackers, npc_kill
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                killmail["killmail_id"],
                killmail["killmail_time"],
                killmail.get("solar_system_id"),
                killmail.get("solar_system_name"),
                killmail.get("solar_system_region_name"),
                killmail.get("war_id"),
                victim.get("character_id"),
                victim.get("character_name"),
                victim.get("corporation_id"),
                victim.get("corporation_name"),
                victim.get("alliance_id"),
                victim.get("alliance_name"),
                victim.get("ship_type_id"),
                victim.get("ship_name"),
                victim.get("damage_taken"),
                zkb.get("totalValue", 0),
                len(attackers),
                1 if zkb.get("npc") else 0,
            ),
        )

        for a in attackers:
            conn.execute(
                """
                INSERT INTO attackers (
                    killmail_id, character_id, character_name,
                    corporation_id, corporation_name,
                    alliance_id, alliance_name,
                    ship_type_id, ship_name,
                    weapon_type_id, weapon_name,
                    damage_done, final_blow
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    killmail["killmail_id"],
                    a.get("character_id"),
                    a.get("character_name"),
                    a.get("corporation_id"),
                    a.get("corporation_name"),
                    a.get("alliance_id"),
                    a.get("alliance_name"),
                    a.get("ship_type_id"),
                    a.get("ship_name"),
                    a.get("weapon_type_id"),
                    a.get("weapon_name"),
                    a.get("damage_done", 0),
                    1 if a.get("final_blow") else 0,
                ),
            )

        for it in items:
            conn.execute(
                """
                INSERT INTO items (
                    killmail_id, item_type_id, item_name,
                    quantity_dropped, quantity_destroyed, flag
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    killmail["killmail_id"],
                    it.get("item_type_id"),
                    it.get("item_name"),
                    it.get("quantity_dropped", 0),
                    it.get("quantity_destroyed", 0),
                    it.get("flag"),
                ),
            )


def has_killmail(killmail_id: int) -> bool:
    """检查击杀邮件是否已存在。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM killmails WHERE killmail_id = ?", (killmail_id,)
        ).fetchone()
        return row is not None


def get_corporation_killmail_ids(corp_id: int, date_from: str, date_to: str) -> list[int]:
    """获取指定军团在时间范围内的击杀 ID 列表（含本方击杀和本方损失）。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT k.killmail_id FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND (
                  k.victim_corporation_id = ?
                  OR EXISTS (
                      SELECT 1 FROM attackers a
                      WHERE a.killmail_id = k.killmail_id AND a.corporation_id = ?
                  )
              )
            ORDER BY k.killmail_time DESC
            """,
            (date_from, date_to, corp_id, corp_id),
        ).fetchall()
        return [r["killmail_id"] for r in rows]


# ── 分析查询 ────────────────────────────────────────────


def query_corp_daily_stats(corp_id: int, date_from: str, date_to: str) -> dict:
    """军团昨日击杀/损失汇总统计。"""
    with get_db() as conn:
        # 本方击杀（攻击者中包含本军团成员）
        kills = conn.execute(
            """
            SELECT COUNT(DISTINCT k.killmail_id) AS count,
                   COALESCE(SUM(k.isk_destroyed), 0) AS isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.corporation_id = ?
              )
              AND k.npc_kill = 0
            """,
            (date_from, date_to, corp_id),
        ).fetchone()

        # 本方损失（受害者是本军团成员）
        losses = conn.execute(
            """
            SELECT COUNT(*) AS count,
                   COALESCE(SUM(isk_destroyed), 0) AS isk
            FROM killmails
            WHERE killmail_time >= ? AND killmail_time < ?
              AND victim_corporation_id = ?
            """,
            (date_from, date_to, corp_id),
        ).fetchone()

        return {
            "kills": {"count": kills["count"], "isk": kills["isk"]},
            "losses": {"count": losses["count"], "isk": losses["isk"]},
        }


def query_top_killers(corp_id: int, date_from: str, date_to: str, limit: int = 10) -> list[dict]:
    """击杀排行 — 本方成员击杀数排行。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT a.character_id, a.character_name,
                   a.ship_name,
                   COUNT(DISTINCT a.killmail_id) AS kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM attackers a
            JOIN killmails k ON k.killmail_id = a.killmail_id
            WHERE a.corporation_id = ?
              AND k.killmail_time >= ? AND k.killmail_time < ?
              AND a.final_blow = 1
              AND k.npc_kill = 0
            GROUP BY a.character_id
            ORDER BY kills DESC
            LIMIT ?
            """,
            (corp_id, date_from, date_to, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_top_loss_ships(corp_id: int, date_from: str, date_to: str, limit: int = 10) -> list[dict]:
    """被击毁舰船排行 — 本方损失最多的船型。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT victim_ship_name, victim_ship_type_id,
                   COUNT(*) AS count,
                   COALESCE(SUM(isk_destroyed), 0) AS total_isk
            FROM killmails
            WHERE victim_corporation_id = ?
              AND killmail_time >= ? AND killmail_time < ?
            GROUP BY victim_ship_type_id
            ORDER BY count DESC
            LIMIT ?
            """,
            (corp_id, date_from, date_to, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_top_kill_ships(corp_id: int, date_from: str, date_to: str, limit: int = 10) -> list[dict]:
    """击杀使用舰船排行 — 本方击杀时使用的船型。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT a.ship_name, a.ship_type_id,
                   COUNT(DISTINCT a.killmail_id) AS count,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM attackers a
            JOIN killmails k ON k.killmail_id = a.killmail_id
            WHERE a.corporation_id = ?
              AND k.killmail_time >= ? AND k.killmail_time < ?
              AND a.final_blow = 1
              AND k.npc_kill = 0
            GROUP BY a.ship_type_id
            ORDER BY count DESC
            LIMIT ?
            """,
            (corp_id, date_from, date_to, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_hourly_timeline(corp_id: int, date_from: str, date_to: str) -> list[dict]:
    """24 小时击杀时间分布。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT CAST(STRFTIME('%H', k.killmail_time) AS INTEGER) AS hour,
                   COUNT(DISTINCT k.killmail_id) AS kills
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.corporation_id = ?
              )
              AND k.npc_kill = 0
            GROUP BY hour
            ORDER BY hour
            """,
            (date_from, date_to, corp_id),
        ).fetchall()
        return [dict(r) for r in rows]


def query_system_hotspots(corp_id: int, date_from: str, date_to: str, limit: int = 10) -> list[dict]:
    """星系热区 — 击杀发生最多的星系。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT k.solar_system_id, k.solar_system_name,
                   COUNT(DISTINCT k.killmail_id) AS kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.corporation_id = ?
              )
              AND k.npc_kill = 0
            GROUP BY k.solar_system_id
            ORDER BY kills DESC
            LIMIT ?
            """,
            (date_from, date_to, corp_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_active_members(corp_id: int, date_from: str, date_to: str) -> int:
    """活跃成员数（有击杀或损失记录的成员）。"""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT entity_id) AS count FROM (
                SELECT a.character_id AS entity_id
                FROM attackers a
                JOIN killmails k ON k.killmail_id = a.killmail_id
                WHERE a.corporation_id = ?
                  AND k.killmail_time >= ? AND k.killmail_time < ?
                UNION
                SELECT k.victim_character_id
                FROM killmails k
                WHERE k.victim_corporation_id = ?
                  AND k.killmail_time >= ? AND k.killmail_time < ?
            )
            """,
            (corp_id, date_from, date_to, corp_id, date_from, date_to),
        ).fetchone()
        return row["count"] if row else 0


def query_top_victims(corp_id: int, date_from: str, date_to: str, limit: int = 10) -> list[dict]:
    """受害者排行 — 被本方击杀最多的角色。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT k.victim_character_id, k.victim_character_name,
                   k.victim_corporation_name, k.victim_alliance_name,
                   COUNT(*) AS count,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.corporation_id = ?
              )
              AND k.npc_kill = 0
            GROUP BY k.victim_character_id
            ORDER BY count DESC
            LIMIT ?
            """,
            (date_from, date_to, corp_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_region_hotspots(corp_id: int, date_from: str, date_to: str, limit: int = 10) -> list[dict]:
    """星域热区 — 击杀发生最多的星域。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT k.solar_system_region_name,
                   COUNT(DISTINCT k.killmail_id) AS kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.corporation_id = ?
              )
              AND k.npc_kill = 0
              AND k.solar_system_region_name IS NOT NULL
            GROUP BY k.solar_system_region_name
            ORDER BY kills DESC
            LIMIT ?
            """,
            (date_from, date_to, corp_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_top_killed_alliances(corp_id: int, date_from: str, date_to: str, limit: int = 10) -> list[dict]:
    """杀的最多的联盟 — 本方击杀的受害者所属联盟排行。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT k.victim_alliance_name,
                   COUNT(DISTINCT k.killmail_id) AS kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.corporation_id = ?
              )
              AND k.npc_kill = 0
              AND k.victim_alliance_name IS NOT NULL
              AND k.victim_alliance_name != ''
            GROUP BY k.victim_alliance_name
            ORDER BY kills DESC
            LIMIT ?
            """,
            (date_from, date_to, corp_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_top_attacker_alliances(corp_id: int, date_from: str, date_to: str, limit: int = 10) -> list[dict]:
    """杀我们最多的联盟 — 击杀本方成员的攻击者所属联盟排行。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT a.alliance_name,
                   COUNT(DISTINCT a.killmail_id) AS kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM attackers a
            JOIN killmails k ON k.killmail_id = a.killmail_id
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND k.victim_corporation_id = ?
              AND a.alliance_name IS NOT NULL
              AND a.alliance_name != ''
              AND (a.character_id IS NOT NULL)
            GROUP BY a.alliance_name
            ORDER BY kills DESC
            LIMIT ?
            """,
            (date_from, date_to, corp_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── 联盟分析查询 ────────────────────────────────────────


def query_alliance_daily_stats(alliance_id: int, date_from: str, date_to: str) -> dict:
    """联盟昨日击杀/损失汇总统计。"""
    with get_db() as conn:
        kills = conn.execute(
            """
            SELECT COUNT(DISTINCT k.killmail_id) AS count,
                   COALESCE(SUM(k.isk_destroyed), 0) AS isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.alliance_id = ?
              )
              AND k.npc_kill = 0
            """,
            (date_from, date_to, alliance_id),
        ).fetchone()

        losses = conn.execute(
            """
            SELECT COUNT(*) AS count,
                   COALESCE(SUM(isk_destroyed), 0) AS isk
            FROM killmails
            WHERE killmail_time >= ? AND killmail_time < ?
              AND victim_alliance_id = ?
            """,
            (date_from, date_to, alliance_id),
        ).fetchone()

        return {
            "kills": {"count": kills["count"], "isk": kills["isk"]},
            "losses": {"count": losses["count"], "isk": losses["isk"]},
        }


def query_alliance_active_members(alliance_id: int, date_from: str, date_to: str) -> int:
    """联盟活跃成员数。"""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT entity_id) AS count FROM (
                SELECT a.character_id AS entity_id
                FROM attackers a
                JOIN killmails k ON k.killmail_id = a.killmail_id
                WHERE a.alliance_id = ?
                  AND k.killmail_time >= ? AND k.killmail_time < ?
                UNION
                SELECT k.victim_character_id
                FROM killmails k
                WHERE k.victim_alliance_id = ?
                  AND k.killmail_time >= ? AND k.killmail_time < ?
            )
            """,
            (alliance_id, date_from, date_to, alliance_id, date_from, date_to),
        ).fetchone()
        return row["count"] if row else 0
