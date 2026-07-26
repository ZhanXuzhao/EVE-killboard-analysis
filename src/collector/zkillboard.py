"""zKillboard API 客户端 — 获取并解析击杀数据。"""

import logging
from typing import Optional

import requests

from src.config import (
    ZKILLBOARD_BASE_URL,
    REQUEST_TIMEOUT,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

# 请求会话（连接复用）
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def _request(path: str, params: Optional[dict] = None) -> Optional[dict | list]:
    """发送 GET 请求到 zKillboard API。"""
    url = f"{ZKILLBOARD_BASE_URL}/{path.lstrip('/')}"
    try:
        resp = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.warning(f"API 请求失败 [{url}]: {e}")
        return None


# ── ESI 名称解析 ────────────────────────────────────────

_ESI_NAMES_URL = "https://esi.evetech.net/latest/universe/names/"


def _batch_resolve_ids(id_batch: list[int]) -> dict[int, str]:
    """批量调用 ESI /universe/names/ 解析 ID→名称。

    Args:
        id_batch: 最多 1000 个 ID

    Returns:
        {id: name, ...}
    """
    if not id_batch:
        return {}
    try:
        resp = _session.post(
            _ESI_NAMES_URL,
            json=id_batch,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return {item["id"]: item["name"] for item in data if "name" in item}
    except Exception as e:
        logger.warning(f"ESI 名称解析失败 (batch size={len(id_batch)}): {e}")
    return {}


def _enrich_system_regions(kills: list[dict]) -> list[dict]:
    """解析星系 ID 对应的星域名称并注入。

    流程：星系 → 星座(获取 region_id) → 星域(获取名称)
    """
    # 收集所有唯一星系 ID
    system_ids = set()
    for km in kills:
        sid = km.get("solar_system_id")
        if sid:
            system_ids.add(sid)

    if not system_ids:
        return kills

    system_list = sorted(system_ids)

    # 步骤1: 获取每个星系的 constellation_id
    sys_to_const: dict[int, int] = {}  # system_id -> constellation_id
    for sid in system_list:
        try:
            resp = _session.get(
                f"https://esi.evetech.net/latest/universe/systems/{sid}/",
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            info = resp.json()
            cid = info.get("constellation_id")
            if cid:
                sys_to_const[sid] = cid
        except Exception as e:
            logger.warning(f"ESI 星系查询失败 (system={sid}): {e}")

    if not sys_to_const:
        return kills

    # 步骤2: 获取每个星座的 region_id
    const_ids = set(sys_to_const.values())
    const_to_region: dict[int, int] = {}  # constellation_id -> region_id
    for cid in sorted(const_ids):
        try:
            resp = _session.get(
                f"https://esi.evetech.net/latest/universe/constellations/{cid}/",
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            info = resp.json()
            rid = info.get("region_id")
            if rid:
                const_to_region[cid] = rid
        except Exception as e:
            logger.warning(f"ESI 星座查询失败 (constellation={cid}): {e}")

    if not const_to_region:
        return kills

    # 步骤3: 批量解析 region_id → region_name
    region_ids = set(const_to_region.values())
    region_name_map: dict[int, str] = {}
    id_list = sorted(region_ids)
    for i in range(0, len(id_list), 1000):
        batch = id_list[i:i + 1000]
        region_name_map.update(_batch_resolve_ids(batch))

    # 步骤4: 注入 region_name 到每个击杀
    for km in kills:
        sid = km.get("solar_system_id")
        if sid in sys_to_const:
            cid = sys_to_const[sid]
            rid = const_to_region.get(cid)
            if rid and rid in region_name_map:
                km["solar_system_region_name"] = region_name_map[rid]

    return kills


def _enrich_killmail_names(kills: list[dict]) -> list[dict]:
    """批量解析击杀数据中所有 ID 的名称并注入。

    遍历所有击杀，收集所有 ID 后通过 ESI 批量查询，
    然后将名称注入到对应字段（如 solar_system_name, ship_name 等）。
    """
    # 收集所有需要解析的 ID
    all_ids: set[int] = set()

    for km in kills:
        all_ids.add(km.get("solar_system_id"))
        victim = km.get("victim", {}) or {}
        all_ids.add(victim.get("character_id"))
        all_ids.add(victim.get("corporation_id"))
        all_ids.add(victim.get("alliance_id"))
        all_ids.add(victim.get("ship_type_id"))

        for a in km.get("attackers", []):
            all_ids.add(a.get("character_id"))
            all_ids.add(a.get("corporation_id"))
            all_ids.add(a.get("alliance_id"))
            all_ids.add(a.get("ship_type_id"))
            all_ids.add(a.get("weapon_type_id"))

        for it in (victim.get("items") or []):
            all_ids.add(it.get("item_type_id"))

    # 过滤掉 None/0
    all_ids = {i for i in all_ids if i}

    if not all_ids:
        return kills

    # ESI 一次最多 1000 个 ID，分批查询
    id_list = sorted(all_ids)
    name_map: dict[int, str] = {}
    for i in range(0, len(id_list), 1000):
        batch = id_list[i:i + 1000]
        name_map.update(_batch_resolve_ids(batch))

    # 注入名称
    for km in kills:
        sid = km.get("solar_system_id")
        if sid and sid not in km and sid in name_map:
            km["solar_system_name"] = name_map[sid]

        victim = km.get("victim", {}) or {}
        if victim.get("character_id") in name_map:
            victim["character_name"] = name_map[victim["character_id"]]
        if victim.get("corporation_id") in name_map:
            victim["corporation_name"] = name_map[victim["corporation_id"]]
        if victim.get("alliance_id") in name_map:
            victim["alliance_name"] = name_map[victim["alliance_id"]]
        if victim.get("ship_type_id") in name_map:
            victim["ship_name"] = name_map[victim["ship_type_id"]]

        for a in km.get("attackers", []):
            if a.get("character_id") in name_map:
                a["character_name"] = name_map[a["character_id"]]
            if a.get("corporation_id") in name_map:
                a["corporation_name"] = name_map[a["corporation_id"]]
            if a.get("alliance_id") in name_map:
                a["alliance_name"] = name_map[a["alliance_id"]]
            if a.get("ship_type_id") in name_map:
                a["ship_name"] = name_map[a["ship_type_id"]]
            if a.get("weapon_type_id") in name_map:
                a["weapon_name"] = name_map[a["weapon_type_id"]]

        for it in (victim.get("items") or []):
            if it.get("item_type_id") in name_map:
                it["item_name"] = name_map[it["item_type_id"]]

    return kills


def get_corporation_kills(
    corporation_id: int,
    past_seconds: int = 86400,
    limit: int = 200,
) -> list[dict]:
    """获取指定军团在最近 N 秒内的击杀数据。

    ⚠️ zKillboard 新版 API 直接返回完整的击杀详情（含攻击者、物品等），
       无需再单独调用 killID 接口。

    Args:
        corporation_id: 军团 ID
        past_seconds: 回溯秒数，默认 86400（1 天）
        limit: 最大返回条数

    Returns:
        击杀详情字典列表，每条含 killmail, attackers, victim, items 等
    """
    path = f"corporationID/{corporation_id}/pastSeconds/{past_seconds}/"
    data = _request(path, params={"limit": limit})

    if data is None:
        return []

    if isinstance(data, list):
        # 新版 API 直接返回完整击杀对象数组
        return data[:limit]

    if isinstance(data, dict) and "error" in data:
        logger.warning(f"API 返回错误: {data['error']}")
    else:
        logger.warning(f"意外的返回格式: {type(data)}")
    return []


def search_corporation(query: str, limit: int = 10) -> list[dict]:
    """搜索军团名称，返回匹配的军团列表。

    使用 zKillboard 的 autocomplete 接口，过滤出军团类型的结果。

    Args:
        query: 军团名称关键字（建议使用短名称，如 "Goonswarm" 而非全称）
        limit: 最大返回条数

    Returns:
        [{"id": int, "name": str}, ...]
    """
    url = f"https://zkillboard.com/autocomplete/{query}/"

    try:
        resp = _session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"搜索请求失败 [{query}]: {e}")
        return []

    if not isinstance(data, list):
        return []

    # 过滤出 corporation 类型
    corps = [item for item in data if item.get("type") == "corporation"]

    # 去重（按 id）
    seen = set()
    unique = []
    for c in corps:
        cid = c.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            unique.append({"id": cid, "name": c.get("name", "")})

    return unique[:limit]


def fetch_corp_yesterday_kills(
    corporation_id: int,
    on_progress: Optional[callable] = None,
) -> list[dict]:
    """拉取军团前一天的完整击杀数据。

    zKillboard 新版 API 一次请求即返回完整击杀详情，
    （含 killmail、attackers、victim、items 等）。

    Args:
        corporation_id: 军团 ID
        on_progress: 进度回调 (current, total) — 新版 API 一次返回，total=1

    Returns:
        包含击杀详情、攻击者列表、物品列表的字典列表
    """
    if on_progress:
        on_progress(0, 1)

    kills = get_corporation_kills(corporation_id, past_seconds=86400)

    if not kills:
        if on_progress:
            on_progress(1, 1)
        return []

    # 批量解析 ID→名称
    kills = _enrich_killmail_names(kills)
    # 批量解析星系→星域
    kills = _enrich_system_regions(kills)

    results = []
    for km in kills:
        km_id = km.get("killmail_id")
        if not km_id:
            continue

        result = {
            "killmail": km,
            "attackers": km.get("attackers", []),
            "items": (km.get("victim") or {}).get("items", []),
        }
        results.append(result)

    if on_progress:
        on_progress(1, 1)

    logger.info(f"拉取完成: 获取 {len(results)} 条击杀数据")
    return results
