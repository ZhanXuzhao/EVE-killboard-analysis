"""zKillboard API 客户端 — 获取并解析击杀数据。"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from src.config import (
    ZKILLBOARD_BASE_URL,
    REQUEST_TIMEOUT,
    USER_AGENT,
)
from src.storage.database import (
    batch_get_id_names,
    batch_get_ids_missing_category,
    batch_get_system_data,
    batch_get_system_regions,
    batch_set_id_names,
    batch_upsert_id_names,
    batch_fill_category,
    set_system_region,
)


logger = logging.getLogger(__name__)

# 请求会话（连接复用）
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})

# ESI API 端点
_ESI_NAMES_URLS = [
    "https://esi.evetech.net/latest/universe/names/",
    "https://esi.evetech.net/v1/universe/names/",
]


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

def _post_names_request(id_batch: list[int]) -> list[dict]:
    """尝试通过 ESI /universe/names/ 解析 ID 列表，必要时回退到 v1。"""
    if not id_batch:
        return []

    last_error: Exception | None = None
    for url in _ESI_NAMES_URLS:
        try:
            resp = _session.post(
                url,
                json=id_batch,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 404:
                raise RuntimeError(f"{url} not found")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            last_error = e
            logger.warning(f"ESI 名称解析失败 (url={url}, batch size={len(id_batch)}): {e}")

    if last_error is not None:
        logger.warning(f"ESI 名称解析全部失败 (batch size={len(id_batch)}): {last_error}")
    return []


def _batch_resolve_ids(id_batch: list[int]) -> dict[int, str]:
    """批量调用 ESI /universe/names/ 解析 ID→名称。

    Args:
        id_batch: 最多 1000 个 ID

    Returns:
        {id: name, ...}
    """
    data = _post_names_request(id_batch)
    return {item["id"]: item["name"] for item in data if "name" in item}


def _batch_resolve_ids_with_category(id_batch: list[int]) -> dict[int, tuple[str, str]]:
    """批量调用 ESI /universe/names/ 解析 ID→(名称, 类别)。

    Args:
        id_batch: 最多 1000 个 ID

    Returns:
        {id: (name, category), ...}
        category 取值: character, corporation, alliance, solar_system, inventory_type, region, station, faction, constellation
    """
    data = _post_names_request(id_batch)
    return {
        item["id"]: (item["name"], item.get("category", ""))
        for item in data if "name" in item
    }


# ── 星系→星域 缓存操作（直连 SQLite，无全局状态） ──────


def _enrich_system_regions(kills: list[dict]) -> list[dict]:
    """解析星系 ID 对应的星域名称及安全等级并注入。

    流程：星系 → 星座(获取 region_id) → 星域(获取名称)
    所有缓存直接读写 SQLite，无全局内存变量，线程安全。
    """
    # 收集所有唯一星系 ID
    all_system_ids = set()
    for km in kills:
        sid = km.get("solar_system_id")
        if sid:
            all_system_ids.add(sid)

    if not all_system_ids:
        return kills

    # 从 SQLite 批量查询已缓存的星系数据
    cached = batch_get_system_regions(sorted(all_system_ids))
    sec_data = batch_get_system_data(sorted(all_system_ids))

    # 找出未缓存的星系 ID，或已缓存但缺少安全等级
    uncached = sorted(sid for sid in all_system_ids if sid not in cached)
    missing_sec = sorted(sid for sid in all_system_ids
                         if sid in cached and sec_data.get(sid, {}).get("security_status") is None)

    if uncached or missing_sec:
        # 步骤1: 获取每个星系的 constellation_id 和 security_status
        sys_to_const: dict[int, int] = {}
        sys_to_sec: dict[int, float] = {}
        need_fetch = sorted(set(uncached + missing_sec))
        for sid in need_fetch:
            try:
                resp = _session.get(
                    f"https://esi.evetech.net/latest/universe/systems/{sid}/",
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                info = resp.json()
                cid = info.get("constellation_id")
                ss = info.get("security_status")
                if cid:
                    sys_to_const[sid] = cid
                if ss is not None:
                    sys_to_sec[sid] = round(ss, 2)
            except Exception as e:
                logger.warning(f"ESI 星系查询失败 (system={sid}): {e}")

        if sys_to_const:
            # 步骤2: 获取每个星座的 region_id
            const_ids = set(sys_to_const.values())
            const_to_region: dict[int, int] = {}
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

            if const_to_region:
                # 步骤3: 批量解析 region_id → region_name
                region_ids = set(const_to_region.values())
                region_name_map: dict[int, str] = {}
                id_list = sorted(region_ids)
                for i in range(0, len(id_list), 1000):
                    batch = id_list[i:i + 1000]
                    region_name_map.update(_batch_resolve_ids(batch))

                # 步骤4: 将新结果写入 SQLite
                for sid in need_fetch:
                    cid = sys_to_const.get(sid)
                    rid = const_to_region.get(cid) if cid else None
                    rname = region_name_map.get(rid) if rid else None
                    ss = sys_to_sec.get(sid)
                    if rname:
                        cached[sid] = rname
                        try:
                            set_system_region(sid, rname, security_status=ss)
                        except Exception as e:
                            logger.warning(f"写入星域缓存失败 (system={sid}): {e}")
                    elif ss is not None and sid in cached:
                        # 已有 region_name，只需更新安全等级
                        try:
                            set_system_region(sid, cached[sid], security_status=ss)
                        except Exception as e:
                            logger.warning(f"更新安全等级失败 (system={sid}): {e}")
        elif sys_to_sec:
            # 只有安全等级数据（没有星座/星域数据），更新已有缓存的记录
            for sid in need_fetch:
                ss = sys_to_sec.get(sid)
                if ss is not None and sid in cached:
                    try:
                        set_system_region(sid, cached[sid], security_status=ss)
                    except Exception as e:
                        logger.warning(f"更新安全等级失败 (system={sid}): {e}")

    # 重新查询完整的安全等级数据（含本次新增）
    sec_data = batch_get_system_data(sorted(all_system_ids))

    # 注入 region_name 和 security_status 到每个击杀
    for km in kills:
        sid = km.get("solar_system_id")
        if sid in cached:
            km["solar_system_region_name"] = cached[sid]
        sd = sec_data.get(sid, {})
        if sd.get("security_status") is not None:
            km["system_security_status"] = sd["security_status"]

    return kills


# ── 通用 ID→名称 缓存操作（直连 SQLite，无全局状态） ──


def _enrich_killmail_names(kills: list[dict]) -> list[dict]:
    """批量解析击杀数据中所有 ID 的名称并注入。

    所有缓存直接读写 SQLite，无全局内存变量，线程安全。
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

    # 从 SQLite 批量查询已缓存的名称
    id_list = sorted(all_ids)
    name_map: dict[int, str] = batch_get_id_names(id_list)

    # 找出未缓存的 ID，调用 ESI 批量解析（含 category）
    uncached = [i for i in id_list if i not in name_map]
    if uncached:
        new_data: dict[int, tuple[str, str]] = {}
        for i in range(0, len(uncached), 1000):
            batch = uncached[i:i + 1000]
            new_data.update(_batch_resolve_ids_with_category(batch))
        if new_data:
            # 立即写入 SQLite（含 category）
            try:
                batch_upsert_id_names(new_data)
            except Exception as e:
                logger.warning(f"写入 ID 名称缓存失败: {e}")
            name_map.update({k: v[0] for k, v in new_data.items()})

    # 对已有记录增量补 category（仅补数据库中 category 为 NULL 的记录）
    existing_ids = [i for i in id_list if i in name_map]
    if existing_ids:
        missing_cat_ids = batch_get_ids_missing_category(existing_ids)
        if missing_cat_ids:
            for i in range(0, len(missing_cat_ids), 1000):
                batch = missing_cat_ids[i:i + 1000]
                try:
                    resolved = _batch_resolve_ids_with_category(batch)
                    cat_map = {eid: cat for eid, (_, cat) in resolved.items() if cat}
                    if cat_map:
                        try:
                            batch_fill_category(cat_map)
                        except Exception as e:
                            logger.warning(f"增量更新 category 失败: {e}")
                except Exception:
                    pass  # 非关键操作，跳过即可

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
    page: int = 1,
) -> list[dict]:
    """获取指定军团在最近 N 秒内的一页击杀数据。

    zKillboard API 每页最多返回 200 条，通过 page 路径参数翻页。

    Args:
        corporation_id: 军团 ID
        past_seconds: 回溯秒数，默认 86400（1 天）
        page: 页码，从 1 开始

    Returns:
        击杀详情字典列表
    """
    path = f"corporationID/{corporation_id}/pastSeconds/{past_seconds}/page/{page}/"
    data = _request(path)

    if isinstance(data, list):
        return data

    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"zKillboard API 返回错误: {data['error']}")

    raise RuntimeError(f"zKillboard API 返回格式异常: {type(data)}")


def get_alliance_kills(
    alliance_id: int,
    past_seconds: int = 86400,
    page: int = 1,
) -> list[dict]:
    """获取指定联盟在最近 N 秒内的一页击杀数据。"""
    path = f"allianceID/{alliance_id}/pastSeconds/{past_seconds}/page/{page}/"
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


def fetch_entity_kills(
    entity_id: int,
    entity_type: str = "corporation",
    on_progress: Optional[callable] = None,
    past_seconds: int = 86400,
) -> tuple[list[dict], bool]:
    """拉取军团/联盟在最近 N 秒内的击杀数据（自动翻页），返回数据和完整性标志。"""
    get_fn = get_alliance_kills if entity_type == "alliance" else get_corporation_kills

    # 计算时间下界：只保留不早于 (now - past_seconds) 的数据
    _cutoff = datetime.now(timezone.utc) - timedelta(seconds=past_seconds)

    all_kills = []
    page = 1
    complete = True
    while True:
        try:
            kills = get_fn(entity_id, past_seconds=past_seconds, page=page)
        except RuntimeError:
            complete = False
            break

        if not kills:
            break

        # 过滤空值并检查时间下界
        valid_kills = [k for k in kills if k is not None]

        # zKillboard 按 killmail_time 降序排列，检查本页最老数据是否已超出 range
        # 如果最后一页最后一击已经早于时间下界，提前停止翻页
        if valid_kills:
            oldest = valid_kills[-1]
            km_time = oldest.get("killmail_time")
            if km_time:
                try:
                    km_dt = datetime.fromisoformat(km_time.replace("Z", "+00:00"))
                    if km_dt.tzinfo is None:
                        km_dt = km_dt.replace(tzinfo=timezone.utc)
                    if km_dt < _cutoff:
                        # 只保留在时间范围内的数据
                        valid_kills = [k for k in valid_kills
                                       if datetime.fromisoformat(
                                           k["killmail_time"].replace("Z", "+00:00")
                                       ).replace(tzinfo=timezone.utc) >= _cutoff]
                        all_kills.extend(valid_kills)
                        if on_progress:
                            on_progress(page, len(valid_kills))
                        complete = True
                        break
                except Exception:
                    pass

        all_kills.extend(valid_kills)
        if on_progress:
            on_progress(page, len(kills))

        # 翻页：zKillboard 首页可能 <200 但还有下一页
        # 策略：至少试 2 页；之后 <200 才停；最多 500 页防超时
        if page >= 500:
            if len(kills) >= 200:
                complete = False  # 可能还有更多页未拉取
            break
        if page >= 2 and len(kills) < 200:
            break
        page += 1

    if not all_kills:
        if on_progress:
            on_progress(1, 0)
        return [], complete

    if on_progress:
        on_progress(page, 0)

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

    logger.info(f"拉取完成: 获取 {len(results)} 条击杀数据, complete={complete}")
    return results, complete
