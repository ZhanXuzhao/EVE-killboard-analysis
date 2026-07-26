"""zKillboard API 客户端 — 获取击杀数据。"""

import time
import logging
from typing import Optional

import requests

from src.config import (
    ZKILLBOARD_BASE_URL,
    REQUEST_INTERVAL,
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
        # zKillboard 返回纯 JSON 数组或对象
        return resp.json()
    except requests.RequestException as e:
        logger.warning(f"API 请求失败 [{url}]: {e}")
        return None


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
