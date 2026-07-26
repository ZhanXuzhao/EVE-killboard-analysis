"""军团分析逻辑 — 将原始数据转换为分析结果。"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from src.storage import repository as repo


def _get_date_range(target_date: datetime = None) -> tuple[str, str]:
    """获取指定日期的 UTC 范围 [00:00:00, 次日00:00:00)。"""
    tz = timezone.utc
    if target_date is None:
        now = datetime.now(tz)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = today_start - timedelta(days=1)
    else:
        # target_date 可能是 datetime.date 或 datetime.datetime
        if isinstance(target_date, datetime):
            day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)
        else:
            day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)
    next_day = day_start + timedelta(days=1)
    return day_start.isoformat(), next_day.isoformat()


_get_yesterday_range = _get_date_range  # 保持向后兼容


def _has_data(entity_id: int, date_from: str, date_to: str, entity_type: str = "corporation") -> bool:
    """检查数据库中是否有指定实体指定日期的数据。"""
    if entity_type == "alliance":
        km_ids = repo.get_alliance_killmail_ids(entity_id, date_from, date_to)
    else:
        km_ids = repo.get_corporation_killmail_ids(entity_id, date_from, date_to)
    return len(km_ids) > 0


class CorpDailyAnalysis:
    """军团/联盟昨日击杀分析结果容器。"""

    def __init__(self, entity_id: int, date_from: str, date_to: str, entity_type: str = "corporation"):
        self.entity_id = entity_id
        self.entity_type = entity_type
        self.date_from = date_from
        self.date_to = date_to

        self.stats = {}
        self.top_killers = []
        self.top_kill_ships = []
        self.top_loss_ships = []
        self.top_victims = []
        self.hourly_timeline = []
        self.system_hotspots = []
        self.region_hotspots = []
        self.top_killed_alliances = []
        self.top_attacker_alliances = []
        self.active_members = 0
        self.has_data = False

    def run(self):
        """执行所有分析。"""
        eid = self.entity_id
        etype = self.entity_type

        self.has_data = _has_data(eid, self.date_from, self.date_to, etype)
        if not self.has_data:
            return

        if etype == "alliance":
            self.stats = repo.query_alliance_daily_stats(eid, self.date_from, self.date_to)
            self.active_members = repo.query_alliance_active_members(eid, self.date_from, self.date_to)
        else:
            self.stats = repo.query_corp_daily_stats(eid, self.date_from, self.date_to)
            self.active_members = repo.query_active_members(eid, self.date_from, self.date_to, entity_type=etype)

        self.top_killers = repo.query_top_killers(eid, self.date_from, self.date_to, entity_type=etype)
        self.top_kill_ships = repo.query_top_kill_ships(eid, self.date_from, self.date_to, entity_type=etype)
        self.top_loss_ships = repo.query_top_loss_ships(eid, self.date_from, self.date_to, entity_type=etype)
        self.top_victims = repo.query_top_victims(eid, self.date_from, self.date_to, entity_type=etype)
        self.hourly_timeline = repo.query_hourly_timeline(eid, self.date_from, self.date_to, entity_type=etype)
        self.system_hotspots = repo.query_system_hotspots(eid, self.date_from, self.date_to, entity_type=etype)
        self.region_hotspots = repo.query_region_hotspots(eid, self.date_from, self.date_to, entity_type=etype)
        self.top_killed_alliances = repo.query_top_killed_alliances(eid, self.date_from, self.date_to, entity_type=etype)
        self.top_attacker_alliances = repo.query_top_attacker_alliances(eid, self.date_from, self.date_to, entity_type=etype)

    def to_dataframes(self) -> dict[str, pd.DataFrame]:
        """将分析结果转换为 Pandas DataFrame 字典。"""
        dfs = {}

        if self.top_killers:
            dfs["top_killers"] = pd.DataFrame(self.top_killers)

        if self.top_kill_ships:
            dfs["top_kill_ships"] = pd.DataFrame(self.top_kill_ships)

        if self.top_loss_ships:
            dfs["top_loss_ships"] = pd.DataFrame(self.top_loss_ships)

        if self.top_victims:
            dfs["top_victims"] = pd.DataFrame(self.top_victims)

        if self.hourly_timeline:
            df = pd.DataFrame(self.hourly_timeline)
            df["kills"] = df["kills"].astype(int)
            df["losses"] = df["losses"].astype(int)
            dfs["hourly_timeline"] = df

        if self.system_hotspots:
            dfs["system_hotspots"] = pd.DataFrame(self.system_hotspots)

        if self.region_hotspots:
            dfs["region_hotspots"] = pd.DataFrame(self.region_hotspots)

        if self.top_killed_alliances:
            dfs["top_killed_alliances"] = pd.DataFrame(self.top_killed_alliances)

        if self.top_attacker_alliances:
            dfs["top_attacker_alliances"] = pd.DataFrame(self.top_attacker_alliances)

        return dfs


def analyze_entity_yesterday(entity_id: int, entity_type: str = "corporation", target_date: datetime = None) -> CorpDailyAnalysis:
    """分析军团/联盟指定日期的数据，默认昨日。"""
    date_from, date_to = _get_date_range(target_date)
    analysis = CorpDailyAnalysis(entity_id, date_from, date_to, entity_type)
    analysis.run()
    return analysis
