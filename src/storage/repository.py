"""数据访问层 — 击杀数据的写入与查询。"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from src.storage.database import get_db_read, get_db_write


# ── 写入 ─────────────────────────────────────────────────


def save_killmail(killmail: dict, attackers: list[dict], items: list[dict]):
    """保存一条击杀邮件及其攻击者、物品到数据库。"""
    zkb = killmail.get("zkb", {})
    victim = killmail.get("victim", {})

    with get_db_write() as conn:
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
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT 1 FROM killmails WHERE killmail_id = ?", (killmail_id,)
        ).fetchone()
        return row is not None


def get_corporation_killmail_ids(corp_id: int, date_from: str, date_to: str) -> list[int]:
    """获取指定军团在时间范围内的击杀 ID 列表（含本方击杀和本方损失）。"""
    with get_db_read() as conn:
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


def get_alliance_killmail_ids(alliance_id: int, date_from: str, date_to: str) -> list[int]:
    """获取指定联盟在时间范围内的击杀 ID 列表。"""
    with get_db_read() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT k.killmail_id FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND (
                  k.victim_alliance_id = ?
                  OR EXISTS (
                      SELECT 1 FROM attackers a
                      WHERE a.killmail_id = k.killmail_id AND a.alliance_id = ?
                  )
              )
            ORDER BY k.killmail_time DESC
            """,
            (date_from, date_to, alliance_id, alliance_id),
        ).fetchall()
        return [r["killmail_id"] for r in rows]


def _id_col(entity_type: str) -> str:
    """根据实体类型返回 SQL 中的攻击者 ID 列名。"""
    return "alliance_id" if entity_type == "alliance" else "corporation_id"


def _victim_col(entity_type: str) -> str:
    """根据实体类型返回 SQL 中的受害者 ID 列名。"""
    return "victim_alliance_id" if entity_type == "alliance" else "victim_corporation_id"


# ── 分析查询 ────────────────────────────────────────────


def query_corp_daily_stats(corp_id: int, date_from: str, date_to: str) -> dict:
    """军团昨日击杀/损失汇总统计。"""
    with get_db_read() as conn:
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


def query_top_killers(entity_id: int, date_from: str, date_to: str, limit: int = 10, entity_type: str = "corporation") -> list[dict]:
    """击杀排行 — 本方成员击杀数排行。"""
    id_col = _id_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            SELECT a.character_id,
                   COALESCE(NULLIF(a.character_name, ''), 'Unknown') AS character_name,
                   a.ship_name,
                   COUNT(DISTINCT a.killmail_id) AS kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM attackers a
            JOIN killmails k ON k.killmail_id = a.killmail_id
            WHERE a.{id_col} = ?
              AND k.killmail_time >= ? AND k.killmail_time < ?
              AND a.final_blow = 1
              AND k.npc_kill = 0
            GROUP BY a.character_id
            ORDER BY kills DESC
            LIMIT ?
            """,
            (entity_id, date_from, date_to, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_top_loss_ships(entity_id: int, date_from: str, date_to: str, limit: int = 10, entity_type: str = "corporation", sort_by: str = "count") -> list[dict]:
    """被击毁舰船排行 — 本方损失最多的船型。

    Args:
        sort_by: "count"（按击毁数降序）或 "isk"（按总 ISK 降序）
    """
    order_clause = "total_isk DESC" if sort_by == "isk" else "count DESC"
    victim_col = _victim_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            SELECT victim_ship_name, victim_ship_type_id,
                   COUNT(*) AS count,
                   COALESCE(SUM(isk_destroyed), 0) AS total_isk
            FROM killmails
            WHERE {victim_col} = ?
              AND killmail_time >= ? AND killmail_time < ?
            GROUP BY victim_ship_type_id
            ORDER BY {order_clause}
            LIMIT ?
            """,
            (entity_id, date_from, date_to, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_top_kill_ships(entity_id: int, date_from: str, date_to: str, limit: int = 10, entity_type: str = "corporation", sort_by: str = "count") -> list[dict]:
    """击杀使用舰船排行 — 本方击杀时使用的船型。

    Args:
        sort_by: "count"（按击杀数降序）或 "isk"（按总 ISK 降序）
    """
    order_clause = "total_isk DESC" if sort_by == "isk" else "count DESC"
    id_col = _id_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            SELECT a.ship_name, a.ship_type_id,
                   COUNT(DISTINCT a.killmail_id) AS count,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM attackers a
            JOIN killmails k ON k.killmail_id = a.killmail_id
            WHERE a.{id_col} = ?
              AND k.killmail_time >= ? AND k.killmail_time < ?
              AND a.final_blow = 1
              AND k.npc_kill = 0
            GROUP BY a.ship_type_id
            ORDER BY {order_clause}
            LIMIT ?
            """,
            (entity_id, date_from, date_to, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_daily_timeline(entity_id: int, date_from: str, date_to: str, entity_type: str = "corporation") -> list[dict]:
    """每天击杀+损失分布（用于周报）。"""
    id_col = _id_col(entity_type)
    victim_col = _victim_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            SELECT DATE(k.killmail_time) AS day,
                   COUNT(DISTINCT CASE WHEN EXISTS (
                       SELECT 1 FROM attackers a
                       WHERE a.killmail_id = k.killmail_id AND a.{id_col} = ?
                   ) AND k.npc_kill = 0 THEN k.killmail_id END) AS kills,
                   COALESCE(SUM(CASE WHEN EXISTS (
                       SELECT 1 FROM attackers a
                       WHERE a.killmail_id = k.killmail_id AND a.{id_col} = ?
                   ) AND k.npc_kill = 0 THEN k.isk_destroyed ELSE 0 END), 0) AS kill_isk,
                   COUNT(DISTINCT CASE WHEN k.{victim_col} = ? THEN k.killmail_id END) AS losses,
                   COALESCE(SUM(CASE WHEN k.{victim_col} = ? THEN k.isk_destroyed ELSE 0 END), 0) AS loss_isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
            GROUP BY DATE(k.killmail_time)
            ORDER BY day
            """,
            (entity_id, entity_id, entity_id, entity_id, date_from, date_to),
        ).fetchall()
        return [dict(r) for r in rows]


def query_hourly_timeline(entity_id: int, date_from: str, date_to: str, entity_type: str = "corporation") -> list[dict]:
    """24 小时击杀+损失时间分布。"""
    id_col = _id_col(entity_type)
    victim_col = _victim_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            WITH RECURSIVE hours(h) AS (
                SELECT 0 UNION ALL SELECT h+1 FROM hours WHERE h < 23
            ),
            kills AS (
                SELECT CAST(STRFTIME('%H', k.killmail_time) AS INTEGER) AS hour,
                       COUNT(DISTINCT k.killmail_id) AS kills,
                       COALESCE(SUM(k.isk_destroyed), 0) AS kill_isk
                FROM killmails k
                WHERE k.killmail_time >= ? AND k.killmail_time < ?
                  AND EXISTS (
                      SELECT 1 FROM attackers a
                      WHERE a.killmail_id = k.killmail_id AND a.{id_col} = ?
                  )
                  AND k.npc_kill = 0
                GROUP BY hour
            ),
            losses AS (
                SELECT CAST(STRFTIME('%H', k.killmail_time) AS INTEGER) AS hour,
                       COUNT(*) AS losses,
                       COALESCE(SUM(k.isk_destroyed), 0) AS loss_isk
                FROM killmails k
                WHERE k.killmail_time >= ? AND k.killmail_time < ?
                  AND k.{victim_col} = ?
                GROUP BY hour
            )
            SELECT h.h AS hour,
                   COALESCE(k.kills, 0) AS kills,
                   COALESCE(k.kill_isk, 0) AS kill_isk,
                   COALESCE(l.losses, 0) AS losses,
                   COALESCE(l.loss_isk, 0) AS loss_isk
            FROM hours h
            LEFT JOIN kills k ON h.h = k.hour
            LEFT JOIN losses l ON h.h = l.hour
            ORDER BY h.h
            """,
            (date_from, date_to, entity_id, date_from, date_to, entity_id),
        ).fetchall()
        return [dict(r) for r in rows]


def query_system_hotspots(entity_id: int, date_from: str, date_to: str, limit: int = 10, entity_type: str = "corporation") -> list[dict]:
    """星系热区 — 击杀发生最多的星系。"""
    id_col = _id_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            SELECT k.solar_system_id, k.solar_system_name,
                   COUNT(DISTINCT k.killmail_id) AS kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.{id_col} = ?
              )
              AND k.npc_kill = 0
            GROUP BY k.solar_system_id
            ORDER BY kills DESC
            LIMIT ?
            """,
            (date_from, date_to, entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_active_members(entity_id: int, date_from: str, date_to: str, entity_type: str = "corporation") -> int:
    """活跃成员数（有击杀或损失记录的成员）。"""
    id_col = _id_col(entity_type)
    victim_col = _victim_col(entity_type)
    with get_db_read() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(DISTINCT entity_id) AS count FROM (
                SELECT a.character_id AS entity_id
                FROM attackers a
                JOIN killmails k ON k.killmail_id = a.killmail_id
                WHERE a.{id_col} = ?
                  AND k.killmail_time >= ? AND k.killmail_time < ?
                UNION
                SELECT k.victim_character_id
                FROM killmails k
                WHERE k.{victim_col} = ?
                  AND k.killmail_time >= ? AND k.killmail_time < ?
            )
            """,
            (entity_id, date_from, date_to, entity_id, date_from, date_to),
        ).fetchone()
        return row["count"] if row else 0


def query_top_victims(entity_id: int, date_from: str, date_to: str, limit: int = 10, entity_type: str = "corporation") -> list[dict]:
    """受害者排行 — 被本方击杀最多的角色。"""
    id_col = _id_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            SELECT k.victim_character_id,
                   COALESCE(NULLIF(k.victim_character_name, ''), 'Unknown') AS victim_character_name,
                   k.victim_corporation_name, k.victim_alliance_name,
                   COUNT(*) AS count,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.{id_col} = ?
              )
              AND k.npc_kill = 0
            GROUP BY k.victim_character_id
            ORDER BY count DESC
            LIMIT ?
            """,
            (date_from, date_to, entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_region_hotspots(entity_id: int, date_from: str, date_to: str, limit: int = 10, entity_type: str = "corporation") -> list[dict]:
    """星域热区 — 击杀发生最多的星域。"""
    id_col = _id_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            SELECT k.solar_system_region_name,
                   COUNT(DISTINCT k.killmail_id) AS kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.{id_col} = ?
              )
              AND k.npc_kill = 0
              AND k.solar_system_region_name IS NOT NULL
            GROUP BY k.solar_system_region_name
            ORDER BY kills DESC
            LIMIT ?
            """,
            (date_from, date_to, entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_top_killed_alliances(entity_id: int, date_from: str, date_to: str, limit: int = 10, entity_type: str = "corporation") -> list[dict]:
    """杀的最多的联盟 — 本方击杀的受害者所属联盟排行。"""
    id_col = _id_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            SELECT k.victim_alliance_name,
                   COUNT(DISTINCT k.killmail_id) AS kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
            FROM killmails k
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND EXISTS (
                  SELECT 1 FROM attackers a
                  WHERE a.killmail_id = k.killmail_id AND a.{id_col} = ?
              )
              AND k.npc_kill = 0
              AND k.victim_alliance_name IS NOT NULL
              AND k.victim_alliance_name != ''
            GROUP BY k.victim_alliance_name
            ORDER BY kills DESC
            LIMIT ?
            """,
            (date_from, date_to, entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_top_attacker_alliances(entity_id: int, date_from: str, date_to: str, limit: int = 10, entity_type: str = "corporation") -> list[dict]:
    """杀我们最多的联盟 — 击杀本方成员的攻击者所属联盟排行。
    
    人数 = 所有参与的击杀人头（不限 final_blow）
    ISK = 仅统计 final_blow 拿人头的击杀价值（避免重复计数）
    """
    victim_col = _victim_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            WITH kills_by_alliance AS (
                SELECT a.alliance_name,
                       COUNT(DISTINCT a.killmail_id) AS kills
                FROM attackers a
                JOIN killmails k ON k.killmail_id = a.killmail_id
                WHERE k.killmail_time >= ? AND k.killmail_time < ?
                  AND k.{victim_col} = ?
                  AND a.alliance_name IS NOT NULL AND a.alliance_name != ''
                  AND a.character_id IS NOT NULL
                GROUP BY a.alliance_name
            ),
            isk_by_alliance AS (
                SELECT a.alliance_name,
                       COALESCE(SUM(k.isk_destroyed), 0) AS total_isk
                FROM attackers a
                JOIN killmails k ON k.killmail_id = a.killmail_id
                WHERE k.killmail_time >= ? AND k.killmail_time < ?
                  AND k.{victim_col} = ?
                  AND a.final_blow = 1
                  AND a.alliance_name IS NOT NULL AND a.alliance_name != ''
                GROUP BY a.alliance_name
            )
            SELECT k.alliance_name,
                   k.kills,
                   COALESCE(i.total_isk, 0) AS total_isk
            FROM kills_by_alliance k
            LEFT JOIN isk_by_alliance i ON k.alliance_name = i.alliance_name
            ORDER BY k.kills DESC
            LIMIT ?
            """,
            (date_from, date_to, entity_id, date_from, date_to, entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── 联盟分析查询 ────────────────────────────────────────


def retry_null_names():
    """对数据库中角色名为空的记录重试 ESI 名称解析。

    收集所有有 ID 但无名称的角色/军团/联盟，调用 ESI 批量查询，
    将解析到的名称回填到数据库。
    """
    import requests as _req
    from src.config import USER_AGENT

    _headers = {"User-Agent": USER_AGENT}
    _updated = 0

    with get_db_write() as conn:
        # -- 收集 attacker 中缺名的 character_id --
        rows = conn.execute(
            "SELECT DISTINCT character_id FROM attackers "
            "WHERE character_id IS NOT NULL "
            "AND (character_name IS NULL OR character_name='')"
        ).fetchall()
        char_ids = [r["character_id"] for r in rows if r["character_id"]]

        # -- 收集 killmails 中缺名的 victim_character_id --
        rows = conn.execute(
            "SELECT DISTINCT victim_character_id FROM killmails "
            "WHERE victim_character_id IS NOT NULL "
            "AND (victim_character_name IS NULL OR victim_character_name='')"
        ).fetchall()
        victim_ids = [r["victim_character_id"] for r in rows if r["victim_character_id"]]

        # 合并所有 ID，也加入常用的 corporation/alliance ID
        all_ids = set(char_ids + victim_ids)
        rows = conn.execute(
            "SELECT DISTINCT victim_corporation_id FROM killmails "
            "WHERE victim_corporation_id IS NOT NULL "
            "AND (victim_corporation_name IS NULL OR victim_corporation_name='')"
        ).fetchall()
        all_ids.update(r["victim_corporation_id"] for r in rows if r["victim_corporation_id"])
        rows = conn.execute(
            "SELECT DISTINCT victim_alliance_id FROM killmails "
            "WHERE victim_alliance_id IS NOT NULL "
            "AND (victim_alliance_name IS NULL OR victim_alliance_name='')"
        ).fetchall()
        all_ids.update(r["victim_alliance_id"] for r in rows if r["victim_alliance_id"])
        rows = conn.execute(
            "SELECT DISTINCT corporation_id FROM attackers "
            "WHERE corporation_id IS NOT NULL "
            "AND (corporation_name IS NULL OR corporation_name='')"
        ).fetchall()
        all_ids.update(r["corporation_id"] for r in rows if r["corporation_id"])
        rows = conn.execute(
            "SELECT DISTINCT alliance_id FROM attackers "
            "WHERE alliance_id IS NOT NULL "
            "AND (alliance_name IS NULL OR alliance_name='')"
        ).fetchall()
        all_ids.update(r["alliance_id"] for r in rows if r["alliance_id"])

        if not all_ids:
            return 0

        id_list = sorted(all_ids)
        # ESI /universe/names/ 一次最多 1000 个
        for i in range(0, len(id_list), 1000):
            batch = id_list[i:i + 1000]
            try:
                resp = _req.post(
                    "https://esi.evetech.net/latest/universe/names/",
                    json=batch,
                    headers=_headers,
                    timeout=30,
                )
                if resp.status_code != 200:
                    continue
                for item in resp.json():
                    _id = item.get("id")
                    _name = item.get("name")
                    _cat = item.get("category")
                    if not _id or not _name:
                        continue
                    # 根据 category 更新对应表
                    if _cat == "character":
                        conn.execute(
                            "UPDATE attackers SET character_name=? WHERE character_id=? "
                            "AND (character_name IS NULL OR character_name='')",
                            (_name, _id),
                        )
                        conn.execute(
                            "UPDATE killmails SET victim_character_name=? WHERE victim_character_id=? "
                            "AND (victim_character_name IS NULL OR victim_character_name='')",
                            (_name, _id),
                        )
                        _updated += conn.total_changes
                    elif _cat == "corporation":
                        conn.execute(
                            "UPDATE attackers SET corporation_name=? WHERE corporation_id=? "
                            "AND (corporation_name IS NULL OR corporation_name='')",
                            (_name, _id),
                        )
                        conn.execute(
                            "UPDATE killmails SET victim_corporation_name=? WHERE victim_corporation_id=? "
                            "AND (victim_corporation_name IS NULL OR victim_corporation_name='')",
                            (_name, _id),
                        )
                        _updated += conn.total_changes
                    elif _cat == "alliance":
                        conn.execute(
                            "UPDATE attackers SET alliance_name=? WHERE alliance_id=? "
                            "AND (alliance_name IS NULL OR alliance_name='')",
                            (_name, _id),
                        )
                        conn.execute(
                            "UPDATE killmails SET victim_alliance_name=? WHERE victim_alliance_id=? "
                            "AND (victim_alliance_name IS NULL OR victim_alliance_name='')",
                            (_name, _id),
                        )
                        _updated += conn.total_changes
            except Exception:
                continue

    return _updated


# ── Fetch log（API 拉取记录） ──────────────────────────


def get_fetch_log(entity_id: int, entity_type: str, date_from: str, date_to: str) -> Optional[dict]:
    """查询指定范围的数据拉取记录，没有则返回 None。"""
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT * FROM fetch_log WHERE entity_id=? AND entity_type=? AND date_from=? AND date_to=?",
            (entity_id, entity_type, date_from, date_to),
        ).fetchone()
        return dict(row) if row else None


def upsert_fetch_log(entity_id: int, entity_type: str, date_from: str, date_to: str,
                     killmail_count: int, complete: bool):
    """写入/更新拉取记录。"""
    with get_db_write() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO fetch_log
               (entity_id, entity_type, date_from, date_to, fetched_at, killmail_count, complete)
               VALUES (?, ?, ?, ?, datetime('now'), ?, ?)""",
            (entity_id, entity_type, date_from, date_to, killmail_count, 1 if complete else 0),
        )


def is_cache_valid(entity_id: int, entity_type: str, date_from: str, date_to: str) -> bool:
    """判断数据库中的缓存数据是否仍然有效。

    规则：
      - 不完整 → 无效
      - 数据为空（0 条） → 最多缓存 1 小时（防网络波动）
      - 完整且有数据：
        - 今天 → 5 分钟
        - 昨天 → 12 小时
        - 前天及更早 → 永久
    """
    from datetime import datetime, timezone

    log = get_fetch_log(entity_id, entity_type, date_from, date_to)
    if not log or not log["complete"]:
        return False

    now = datetime.now(timezone.utc)
    fetched = datetime.fromisoformat(log["fetched_at"])
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)

    # 空数据：最多缓存 1 小时，避免网络波动导致永久缺数据
    if log["killmail_count"] == 0:
        return (now - fetched).total_seconds() < 3600

    date_from_dt = datetime.fromisoformat(date_from)
    if date_from_dt.tzinfo is None:
        date_from_dt = date_from_dt.replace(tzinfo=timezone.utc)
    days_ago = (now.date() - date_from_dt.date()).days

    if days_ago <= 0:
        return (now - fetched).total_seconds() < 300  # 今天: 5 分钟
    if days_ago == 1:
        return (now - fetched).total_seconds() < 43200  # 昨天: 12 小时
    return True  # 前天及更早: 永久


def query_joint_kills_alliances(entity_id: int, date_from: str, date_to: str, limit: int = 10, entity_type: str = "corporation") -> list[dict]:
    """联合击杀 — 统计哪些联盟与本方合作击杀了目标。

    对于本方参与的击杀，查找同一击杀邮件中的其他联盟攻击者，
    按合作击杀数和总 ISK 排序，同时返回各联盟参战人数。
    """
    id_col = _id_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            SELECT a2.alliance_id,
                   a2.alliance_name,
                   COUNT(DISTINCT k.killmail_id) AS joint_kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk,
                   COUNT(DISTINCT a2.character_id) AS participant_count
            FROM killmails k
            JOIN attackers a1 ON a1.killmail_id = k.killmail_id
            JOIN attackers a2 ON a2.killmail_id = k.killmail_id
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND a1.{id_col} = ?
              AND a2.alliance_id IS NOT NULL AND a2.alliance_id != 0
              AND (a2.alliance_id != a1.alliance_id OR a1.alliance_id IS NULL)
              AND k.npc_kill = 0
            GROUP BY a2.alliance_id
            ORDER BY joint_kills DESC
            LIMIT ?
            """,
            (date_from, date_to, entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_joint_kills_participants(entity_id: int, date_from: str, date_to: str, limit: int = 10, entity_type: str = "corporation") -> list[dict]:
    """联合参战人数 — 统计参与联合击杀的其他联盟的参战人数。

    对于本方参与的击杀，统计其他参战联盟的击杀数、总 ISK、参与角色数，
    按参战人数排序（不含本方）。
    """
    id_col = _id_col(entity_type)
    with get_db_read() as conn:
        rows = conn.execute(
            f"""
            SELECT a2.alliance_id,
                   a2.alliance_name,
                   COUNT(DISTINCT k.killmail_id) AS joint_kills,
                   COALESCE(SUM(k.isk_destroyed), 0) AS total_isk,
                   COUNT(DISTINCT a2.character_id) AS participant_count
            FROM killmails k
            JOIN attackers a1 ON a1.killmail_id = k.killmail_id
            JOIN attackers a2 ON a2.killmail_id = k.killmail_id
            WHERE k.killmail_time >= ? AND k.killmail_time < ?
              AND a1.{id_col} = ?
              AND a2.alliance_id IS NOT NULL AND a2.alliance_id != 0
              AND (a2.alliance_id != a1.alliance_id OR a1.alliance_id IS NULL)
              AND k.npc_kill = 0
            GROUP BY a2.alliance_id
            ORDER BY participant_count DESC
            LIMIT ?
            """,
            (date_from, date_to, entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_alliance_daily_stats(alliance_id: int, date_from: str, date_to: str) -> dict:
    """联盟昨日击杀/损失汇总统计。"""
    with get_db_read() as conn:
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
    with get_db_read() as conn:
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
