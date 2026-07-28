"""军团分析逻辑 — 将原始数据转换为分析结果。"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from src.storage import repository as repo


def _get_date_range(target_date: datetime = None, report_type: str = "daily") -> tuple[str, str]:
    """获取指定日期的 UTC 范围。

    日报: [00:00:00, 次日00:00:00)
    周报: [当周一00:00:00, 下周一00:00:00)
    """
    tz = timezone.utc
    if target_date is None:
        now = datetime.now(tz)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if report_type == "daily":
            day_start -= timedelta(days=1)
    else:
        if isinstance(target_date, datetime):
            day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)
        else:
            day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)

    if report_type == "weekly":
        days_since_monday = day_start.weekday()  # Monday=0
        week_start = day_start - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=7)
        return week_start.isoformat(), week_end.isoformat()
    else:
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
        self.top_kill_ships_by_isk = []
        self.top_loss_ships_by_isk = []
        self.top_victims = []
        self.hourly_timeline = []
        self.daily_timeline = []
        self.system_hotspots = []
        self.region_hotspots = []
        self.top_killed_alliances = []
        self.top_attacker_alliances = []
        self.joint_kills_alliances = []
        self.joint_kills_participants = []
        self.participant_count = 0
        self.enemy_count = 0
        self.ally_count = 0
        self.has_data = False

    def run(self):
        """执行所有分析。"""
        eid = self.entity_id
        etype = self.entity_type

        self.has_data = _has_data(eid, self.date_from, self.date_to, etype)
        if not self.has_data:
            return

        # 尝试回填数据库中角色名为空的记录
        try:
            repo.retry_null_names()
        except Exception:
            pass

        if etype == "alliance":
            self.stats = repo.query_alliance_daily_stats(eid, self.date_from, self.date_to)
            self.participant_count = repo.query_alliance_participant_count(eid, self.date_from, self.date_to)
        else:
            self.stats = repo.query_corp_daily_stats(eid, self.date_from, self.date_to)
            self.participant_count = repo.query_participant_count(eid, self.date_from, self.date_to, entity_type=etype)

        self.enemy_count = repo.query_enemy_count(eid, self.date_from, self.date_to, entity_type=etype)
        self.ally_count = repo.query_ally_count(eid, self.date_from, self.date_to, entity_type=etype)

        self.top_killers = repo.query_top_killers(eid, self.date_from, self.date_to, entity_type=etype)
        self.top_kill_ships = repo.query_top_kill_ships(eid, self.date_from, self.date_to, limit=10, entity_type=etype)
        self.top_loss_ships = repo.query_top_loss_ships(eid, self.date_from, self.date_to, limit=10, entity_type=etype)
        self.top_kill_ships_by_isk = repo.query_top_kill_ships(eid, self.date_from, self.date_to, limit=10, entity_type=etype, sort_by="isk")
        self.top_loss_ships_by_isk = repo.query_top_loss_ships(eid, self.date_from, self.date_to, limit=10, entity_type=etype, sort_by="isk")
        self.top_victims = repo.query_top_victims(eid, self.date_from, self.date_to, entity_type=etype)
        self.hourly_timeline = repo.query_hourly_timeline(eid, self.date_from, self.date_to, entity_type=etype)
        self.daily_timeline = repo.query_daily_timeline(eid, self.date_from, self.date_to, entity_type=etype)
        self.system_hotspots = repo.query_system_hotspots(eid, self.date_from, self.date_to, entity_type=etype)
        self.region_hotspots = repo.query_region_hotspots(eid, self.date_from, self.date_to, entity_type=etype)
        self.top_killed_alliances = repo.query_top_killed_alliances(eid, self.date_from, self.date_to, entity_type=etype)
        self.top_attacker_alliances = repo.query_top_attacker_alliances(eid, self.date_from, self.date_to, entity_type=etype)
        self.joint_kills_alliances = repo.query_joint_kills_alliances(eid, self.date_from, self.date_to, entity_type=etype)
        self.joint_kills_participants = repo.query_joint_kills_participants(eid, self.date_from, self.date_to, entity_type=etype)

    def to_dataframes(self) -> dict[str, pd.DataFrame]:
        """将分析结果转换为 Pandas DataFrame 字典。"""
        dfs = {}

        if self.top_killers:
            dfs["top_killers"] = pd.DataFrame(self.top_killers)

        if self.top_kill_ships:
            dfs["top_kill_ships"] = pd.DataFrame(self.top_kill_ships)

        if self.top_loss_ships:
            dfs["top_loss_ships"] = pd.DataFrame(self.top_loss_ships)

        if self.top_kill_ships_by_isk:
            dfs["top_kill_ships_by_isk"] = pd.DataFrame(self.top_kill_ships_by_isk)

        if self.top_loss_ships_by_isk:
            dfs["top_loss_ships_by_isk"] = pd.DataFrame(self.top_loss_ships_by_isk)

        if self.top_victims:
            dfs["top_victims"] = pd.DataFrame(self.top_victims)

        if self.hourly_timeline:
            df = pd.DataFrame(self.hourly_timeline)
            df["kills"] = df["kills"].astype(int)
            df["losses"] = df["losses"].astype(int)
            dfs["hourly_timeline"] = df

        if self.daily_timeline:
            df = pd.DataFrame(self.daily_timeline)
            df["kills"] = df["kills"].astype(int)
            df["losses"] = df["losses"].astype(int)
            dfs["daily_timeline"] = df

        if self.system_hotspots:
            dfs["system_hotspots"] = pd.DataFrame(self.system_hotspots)

        if self.region_hotspots:
            dfs["region_hotspots"] = pd.DataFrame(self.region_hotspots)

        if self.top_killed_alliances:
            dfs["top_killed_alliances"] = pd.DataFrame(self.top_killed_alliances)

        if self.top_attacker_alliances:
            dfs["top_attacker_alliances"] = pd.DataFrame(self.top_attacker_alliances)

        if self.joint_kills_alliances:
            df = pd.DataFrame(self.joint_kills_alliances)
            # 确保 participant_count 列存在（可能在旧数据库查询中缺失）
            if "participant_count" not in df.columns:
                df["participant_count"] = 0
            dfs["joint_kills_alliances"] = df

        if self.joint_kills_participants:
            df = pd.DataFrame(self.joint_kills_participants)
            if "participant_count" not in df.columns:
                df["participant_count"] = 0
            dfs["joint_kills_participants"] = df

        return dfs


def analyze_entity_yesterday(entity_id: int, entity_type: str = "corporation", target_date: datetime = None, report_type: str = "daily") -> CorpDailyAnalysis:
    """分析军团/联盟指定日期的数据，默认昨日。"""
    date_from, date_to = _get_date_range(target_date, report_type=report_type)
    analysis = CorpDailyAnalysis(entity_id, date_from, date_to, entity_type)
    analysis.run()
    return analysis
