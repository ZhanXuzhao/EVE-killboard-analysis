"""军团分析逻辑 — 将原始数据转换为分析结果。"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from src.storage import repository as repo


def _get_yesterday_range() -> tuple[str, str]:
    """获取昨天的日期范围 [00:00:00, 00:00:00)。"""
    tz = timezone.utc
    now = datetime.now(tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    return yesterday_start.isoformat(), today_start.isoformat()


def _has_data(corp_id: int, date_from: str, date_to: str) -> bool:
    """检查数据库中是否有指定军团指定日期的数据。"""
    km_ids = repo.get_corporation_killmail_ids(corp_id, date_from, date_to)
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

        self.has_data = _has_data(eid, self.date_from, self.date_to)
        if not self.has_data:
            return

        if etype == "alliance":
            self.stats = repo.query_alliance_daily_stats(eid, self.date_from, self.date_to)
            self.active_members = repo.query_alliance_active_members(eid, self.date_from, self.date_to)
        else:
            self.stats = repo.query_corp_daily_stats(eid, self.date_from, self.date_to)
            self.active_members = repo.query_active_members(eid, self.date_from, self.date_to)

        self.top_killers = repo.query_top_killers(eid, self.date_from, self.date_to)
        self.top_kill_ships = repo.query_top_kill_ships(eid, self.date_from, self.date_to)
        self.top_loss_ships = repo.query_top_loss_ships(eid, self.date_from, self.date_to)
        self.top_victims = repo.query_top_victims(eid, self.date_from, self.date_to)
        self.hourly_timeline = repo.query_hourly_timeline(eid, self.date_from, self.date_to)
        self.system_hotspots = repo.query_system_hotspots(eid, self.date_from, self.date_to)
        self.region_hotspots = repo.query_region_hotspots(eid, self.date_from, self.date_to)
        self.top_killed_alliances = repo.query_top_killed_alliances(eid, self.date_from, self.date_to)
        self.top_attacker_alliances = repo.query_top_attacker_alliances(eid, self.date_from, self.date_to)

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
            # 补全缺失的小时
            all_hours = pd.DataFrame({"hour": range(24)})
            df = all_hours.merge(df, on="hour", how="left").fillna(0)
            df["kills"] = df["kills"].astype(int)
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


def analyze_entity_yesterday(entity_id: int, entity_type: str = "corporation") -> CorpDailyAnalysis:
    """便捷方法：分析军团/联盟昨日数据。"""
    date_from, date_to = _get_yesterday_range()
    analysis = CorpDailyAnalysis(entity_id, date_from, date_to, entity_type)
    analysis.run()
    return analysis
