"""zKillboard API 客户端 — 获取并解析击杀数据。"""

import json
import logging
from pathlib import Path
from typing import Optional

import requests

from src.config import (
    DATA_DIR,
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
        msg = f"zKillboard API 请求失败: {e}"
        logger.warning(msg)
        raise RuntimeError(msg)


# ── ESI 名称解析 ────────────────────────────────────────

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


# ── 星系→星域 本地缓存 ──────────────────────────────────

_SYSTEM_REGION_CACHE: dict[int, str] = {}
_SYSTEM_REGION_CACHE_FILE = DATA_DIR / "system_region_cache.json"


def _load_system_region_cache():
    """加载本地缓存。"""
    global _SYSTEM_REGION_CACHE
    if not _SYSTEM_REGION_CACHE and _SYSTEM_REGION_CACHE_FILE.exists():
        try:
            with open(_SYSTEM_REGION_CACHE_FILE, encoding="utf-8") as f:
                _SYSTEM_REGION_CACHE = {int(k): v for k, v in json.load(f).items()}
        except Exception:
            _SYSTEM_REGION_CACHE = {}


def _save_system_region_cache():
    """保存本地缓存。"""
    try:
        _SYSTEM_REGION_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SYSTEM_REGION_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_SYSTEM_REGION_CACHE, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"保存星域缓存失败: {e}")


# ── 通用 ID→名称 本地缓存 ───────────────────────────────

_ID_NAME_CACHE: dict[int, str] = {}
_ID_NAME_CACHE_FILE = DATA_DIR / "id_name_cache.json"


def _load_id_name_cache():
    """加载 ID→名称缓存。"""
    global _ID_NAME_CACHE
    if not _ID_NAME_CACHE and _ID_NAME_CACHE_FILE.exists():
        try:
            with open(_ID_NAME_CACHE_FILE, encoding="utf-8") as f:
                _ID_NAME_CACHE = {int(k): v for k, v in json.load(f).items()}
        except Exception:
            _ID_NAME_CACHE = {}


def _save_id_name_cache():
    """保存 ID→名称缓存。"""
    try:
        _ID_NAME_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_ID_NAME_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_ID_NAME_CACHE, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"保存 ID 名称缓存失败: {e}")


def _enrich_system_regions(kills: list[dict]) -> list[dict]:
    """解析星系 ID 对应的星域名称并注入。

    流程：星系 → 星座(获取 region_id) → 星域(获取名称)
    使用本地 JSON 缓存加速后续查询。
    """
    _load_system_region_cache()

    # 收集所有唯一星系 ID（排除已缓存的）
    system_ids = set()
    for km in kills:
        sid = km.get("solar_system_id")
        if sid and sid not in _SYSTEM_REGION_CACHE:
            system_ids.add(sid)

    if not system_ids and _SYSTEM_REGION_CACHE:
        # 全部已缓存，直接注入
        for km in kills:
            sid = km.get("solar_system_id")
            if sid in _SYSTEM_REGION_CACHE:
                km["solar_system_region_name"] = _SYSTEM_REGION_CACHE[sid]
        return kills

    system_list = sorted(system_ids) if system_ids else []

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

    # 步骤4: 注入 region_name 到每个击杀（优先从缓存）
    for km in kills:
        sid = km.get("solar_system_id")
        if sid in _SYSTEM_REGION_CACHE:
            km["solar_system_region_name"] = _SYSTEM_REGION_CACHE[sid]
        elif sid in sys_to_const:
            cid = sys_to_const[sid]
            rid = const_to_region.get(cid)
            if rid and rid in region_name_map:
                region_name = region_name_map[rid]
                km["solar_system_region_name"] = region_name
                _SYSTEM_REGION_CACHE[sid] = region_name

    if sys_to_const:
        _save_system_region_cache()

    return kills


def _enrich_killmail_names(kills: list[dict]) -> list[dict]:
    """批量解析击杀数据中所有 ID 的名称并注入。

    使用本地缓存避免重复 ESI 查询。
    """
    _load_id_name_cache()

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

    # 从缓存中取，只查询未缓存的 ID
    name_map: dict[int, str] = {}
    uncached = [i for i in all_ids if i not in _ID_NAME_CACHE]

    if uncached:
        id_list = sorted(uncached)
        for i in range(0, len(id_list), 1000):
            batch = id_list[i:i + 1000]
            name_map.update(_batch_resolve_ids(batch))
        # 缓存新结果
        if name_map:
            _ID_NAME_CACHE.update(name_map)
            _save_id_name_cache()

    # 合并缓存
    for i in all_ids:
        if i in _ID_NAME_CACHE:
            name_map[i] = _ID_NAME_CACHE[i]

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
    start_time: int,
    end_time: int,
    page: int = 1,
) -> list[dict]:
    """获取指定军团在指定时间范围内的一页击杀数据。

    zKillboard API 每页最多返回 200 条，通过 page 路径参数翻页。

    Args:
        corporation_id: 军团 ID
        start_time: 开始时间（Unix 时间戳）
        end_time: 结束时间（Unix 时间戳）
        page: 页码，从 1 开始

    Returns:
        击杀详情字典列表
    """
    path = f"corporationID/{corporation_id}/startTime/{start_time}/endTime/{end_time}/page/{page}/"
    data = _request(path)

    if isinstance(data, list):
        return data

    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"zKillboard API 返回错误: {data['error']}")

    raise RuntimeError(f"zKillboard API 返回格式异常: {type(data)}")


def get_alliance_kills(
    alliance_id: int,
    start_time: int,
    end_time: int,
    page: int = 1,
) -> list[dict]:
    """获取指定联盟在指定时间范围内的一页击杀数据。"""
    path = f"allianceID/{alliance_id}/startTime/{start_time}/endTime/{end_time}/page/{page}/"
    data = _request(path)

    if isinstance(data, list):
        return data

    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"zKillboard API 返回错误: {data['error']}")

    raise RuntimeError(f"zKillboard API 返回格式异常: {type(data)}")


def search_entities(query: str, limit: int = 10) -> dict:
    """搜索军团或联盟名称，返回分类结果。

    使用 zKillboard 的 autocomplete 接口，按类型分组返回。

    Returns:
        {"corporation": [{"id": int, "name": str}, ...],
         "alliance":    [{"id": int, "name": str}, ...]}
    """
    url = f"https://zkillboard.com/autocomplete/{query}/"

    try:
        resp = _session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"搜索请求失败 [{query}]: {e}")
        return {"corporation": [], "alliance": []}

    if not isinstance(data, list):
        return {"corporation": [], "alliance": []}

    result = {"corporation": [], "alliance": []}
    seen = {"corporation": set(), "alliance": set()}

    for item in data:
        t = item.get("type")
        if t not in ("corporation", "alliance"):
            continue
        cid = item.get("id")
        name = item.get("name", "")
        if cid and cid not in seen[t]:
            seen[t].add(cid)
            result[t].append({"id": cid, "name": name})

    result["corporation"] = result["corporation"][:limit]
    result["alliance"] = result["alliance"][:limit]
    return result


def fetch_entity_kills_by_range(
    entity_id: int,
    entity_type: str,
    start_time: int,
    end_time: int,
    on_progress: Optional[callable] = None,
) -> tuple[list[dict], bool]:
    """拉取军团/联盟在指定时间戳范围内的击杀数据（自动翻页），返回数据和完整性标志。

    zKillboard 每页最多 200 条，自动逐页拉取直到无数据。
    如果最后一页不足 200 条，标记为 complete=True，否则为 False。

    Args:
        entity_id: ID
        entity_type: "corporation" 或 "alliance"
        start_time: 开始时间（Unix 时间戳）
        end_time: 结束时间（Unix 时间戳）
        on_progress: 进度回调 (page, items_in_page)

    Returns:
        (results, complete) — results 为击杀详情列表，complete 表示是否拉完整
    """
    get_fn = get_alliance_kills if entity_type == "alliance" else get_corporation_kills

    all_kills = []
    page = 1
    complete = True
    while True:
        try:
            kills = get_fn(entity_id, start_time=start_time, end_time=end_time, page=page)
        except RuntimeError:
            complete = False
            break

        if not kills:
            break

        all_kills.extend(kills)
        if on_progress:
            on_progress(page, len(kills))

        if len(kills) < 200:
            break  # 不足 200 说明是最后一页
        page += 1

    if not all_kills:
        if on_progress:
            on_progress(1, 0)
        return [], complete

    if on_progress:
        on_progress(page, 0)

    # 批量解析名称和星域
    all_kills = _enrich_killmail_names(all_kills)
    all_kills = _enrich_system_regions(all_kills)

    results = []
    for km in all_kills:
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

    logger.info(f"拉取完成: 获取 {len(results)} 条击杀数据, complete={complete}")
    return results, complete
