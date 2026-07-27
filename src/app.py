"""击杀日报 — Streamlit 主界面。"""

import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

from src.storage.database import init_db
from src.collector.zkillboard import fetch_entity_kills, search_entities
from src.storage.repository import save_killmail, has_killmail, is_cache_valid, upsert_fetch_log
from src.analysis.corp_analysis import analyze_entity_yesterday, _get_date_range


def _save_history(entity_id, entity_name, entity_type, ticker=""):
    """保存查询历史到 session_state 并通过 URL 参数同步到浏览器。"""
    import json
    _h = st.session_state.get("query_history", [])
    _h[:] = [x for x in _h if not (x["id"] == entity_id and x.get("type") == (entity_type or "corporation"))]
    _h.insert(0, {"id": entity_id, "name": entity_name, "type": entity_type or "corporation", "ticker": ticker})
    st.session_state.query_history = _h[:10]
    # 通过 URL query param 持久化到浏览器（不同用户不同 URL，历史互不干扰）
    st.query_params["qh"] = json.dumps(st.session_state.query_history, ensure_ascii=False)
    _debug(f"save_history: {entity_name} <{ticker}> pos=0")


# ── Debug 日志 ──────────────────────────────────────────

def _debug(msg: str):
    """写入调试日志到 session_state。"""
    if "_debug_logs" not in st.session_state:
        st.session_state._debug_logs = []
    st.session_state._debug_logs.append(msg)
    if len(st.session_state._debug_logs) > 50:
        st.session_state._debug_logs = st.session_state._debug_logs[-50:]


# ── 回调函数 ────────────────────────────────────────────

def _cb_search():
    """搜索表单提交回调：解析输入并设置 entity session_state。"""
    raw = st.session_state.get("search_input", "").strip()
    if not raw:
        return
    st.session_state._last_input = raw
    st.session_state.entity_id = None
    st.session_state.entity_name = None
    st.session_state.entity_type = None
    st.session_state.data_loaded = False
    st.session_state._search_options = None
    st.session_state.pop("_search_msg", None)

    if raw.isdigit():
        _resolve_numeric_id(int(raw))
    else:
        _search_by_name(raw)


def _resolve_numeric_id(cid: int):
    """回调辅助：解析纯数字 ID。"""
    detected_type = "corporation"
    try:
        import requests as _req
        _resp = _req.post(
            "https://esi.evetech.net/latest/universe/names/",
            json=[cid],
            headers={"User-Agent": "EVE-Killboard-Analysis/1.0"},
            timeout=10,
        )
        _data = _resp.json()
        if isinstance(_data, list) and len(_data) > 0:
            item = _data[0]
            st.session_state.entity_name = item.get("name", str(cid))
            cat = item.get("category", "")
            if cat in ("alliance", "corporation"):
                detected_type = cat
        else:
            st.session_state.entity_name = str(cid)
    except Exception:
        st.session_state.entity_name = str(cid)
    st.session_state.entity_id = cid
    st.session_state.entity_type = detected_type
    st.session_state._pending_rerun = True


def _search_by_name(name: str):
    """回调辅助：按名称搜索军团/联盟。"""
    try:
        results = search_entities(name)
    except Exception as e:
        st.session_state._search_msg = ("error", f"❌ 搜索失败: {e}")
        return

    corps = results.get("corporation", [])
    alliances = results.get("alliance", [])
    all_options = []

    if not corps and not alliances:
        st.session_state._search_msg = ("error", f"❌ 未找到匹配「{name}」的军团或联盟")
        return

    if alliances:
        all_options.append(("── 联盟 ──", None, None))
        for a in alliances:
            all_options.append((f"{a['name']} (ID: {a['id']})", a["id"], "alliance"))
    if corps:
        all_options.append(("── 军团 ──", None, None))
        for c in corps:
            all_options.append((f"{c['name']} (ID: {c['id']})", c["id"], "corporation"))

    non_sep = [o for o in all_options if o[1] is not None]
    if len(non_sep) == 1:
        st.session_state.entity_id = non_sep[0][1]
        st.session_state.entity_name = non_sep[0][0].split(" (ID:")[0]
        st.session_state.entity_type = non_sep[0][2]
        st.session_state._pending_rerun = True
        label = "联盟" if st.session_state.entity_type == "alliance" else "军团"
        st.session_state._search_msg = ("success", f"✅ 已匹配 {label}: **{st.session_state.entity_name}**")
    else:
        st.session_state._search_options = all_options


def _cb_select_entity():
    """搜索结果 radio 选择回调。"""
    selected = st.session_state.get("_search_radio")
    if not selected:
        return
    opts = st.session_state.get("_search_options", [])
    for label_t, eid, etype in opts:
        if label_t == selected and eid is not None:
            st.session_state.entity_id = eid
            st.session_state.entity_name = label_t.split(" (ID:")[0]
            st.session_state.entity_type = etype
            st.session_state.data_loaded = False
            st.session_state._search_options = None
            st.session_state._pending_rerun = True
            break


def _cb_history_click(h: dict):
    """历史记录按钮回调。"""
    st.session_state.entity_id = h["id"]
    st.session_state.entity_name = h["name"]
    st.session_state.entity_type = h["type"]
    st.session_state.data_loaded = False
    st.session_state._last_input = str(h["id"])
    st.session_state._input_value = h.get("ticker", h["name"])
    st.session_state.search_input = h.get("ticker", h["name"])
    st.session_state._pending_rerun = True
    _debug(f"hist_click: {h['name']} <{h.get('ticker','')}>")



# ── 页面配置 ────────────────────────────────────────────

st.set_page_config(
    page_title="EVE 击杀日报",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 隐藏 Streamlit 默认样式
hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.stDeployButton {display:none;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# ── 初始化 ──────────────────────────────────────────────

init_db()

# ── 动态标题 ────────────────────────────────────────────

def render_title(corp_name: str = None):
    """渲染页面标题，统一格式：EVE 击杀日报/周报：军团名"""
    if corp_name:
        title = f"🚀 EVE 击杀{_report_label}：{corp_name}"
    else:
        title = f"🚀 EVE 击杀{_report_label}"
    st.markdown(
        f"<h1 style='text-align: center;'>{title}</h1>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

# ── 侧边栏输入 ──────────────────────────────────────────

# 默认输入：D.C (Dracarys.)
DEFAULT_ENTITY_ID = "D.C"
DEFAULT_ENTITY_RESOLVE = (99009163, "Dracarys.", "alliance")

with st.sidebar:
    st.header("⚙️ 设置")

    # ── 查询历史：初始化（从浏览器 URL 参数读取） ────

    if "query_history" not in st.session_state:
        import json
        qh_raw = st.query_params.get("qh")
        if qh_raw:
            try:
                st.session_state.query_history = json.loads(qh_raw)
            except Exception:
                st.session_state.query_history = []
        else:
            st.session_state.query_history = []

    if st.query_params.get_all("clear"):
        st.session_state.query_history = []
        st.query_params.clear()
        # 同时清除浏览器 localStorage
        st.markdown(
            "<script>localStorage.removeItem('eve_query_history');</script>",
            unsafe_allow_html=True,
        )

    # ── 初始化 session_state ──────────────────────────

    if "entity_id" not in st.session_state:
        st.session_state.entity_id = None
        st.session_state.entity_name = None
        st.session_state.entity_type = None
        st.session_state.data_loaded = False

    # ── 日期选择 + 报告类型 ──────────────────────────

    today = datetime.now(timezone.utc).date()
    if "selected_date" not in st.session_state:
        st.session_state.selected_date = today - timedelta(days=1)
    if "_report_type" not in st.session_state:
        st.session_state._report_type = "daily"

    col_type, col_date = st.columns([1, 3])
    with col_type:
        _rt = st.radio("📊 类型", ["日报", "周报"], horizontal=True,
                       index=0 if st.session_state._report_type == "daily" else 1,
                       label_visibility="collapsed")
        report_type = "daily" if _rt == "日报" else "weekly"
    with col_date:
        selected_date = st.date_input(
            "📅 选择日期",
            value=st.session_state.selected_date,
            max_value=today,
            help="选择要分析的日期",
        )

    if selected_date != st.session_state.selected_date or report_type != st.session_state._report_type:
        st.session_state.selected_date = selected_date
        st.session_state._report_type = report_type
        st.session_state.data_loaded = False
        _debug(f"date_change: {selected_date} type={report_type}")
        st.rerun()

    # ── 搜索输入（内联方式，避免额外 rerun） ─────────

    if "search_input" not in st.session_state:
        st.session_state.search_input = st.session_state.get("_input_value", DEFAULT_ENTITY_ID)

    with st.form(key="search_form"):
        st.text_input(
            "军团/联盟名称或代码",
            key="search_input",
            placeholder="例如: Goonswarm Federation 或 987654321",
            help="输入军团名称（自动搜索）或直接输入数字 ID",
        )
        if st.form_submit_button("📊 分析", type="primary", use_container_width=True):
            _cb_search()

    # 显示搜索消息（成功/错误）
    _msg = st.session_state.pop("_search_msg", None)
    if _msg:
        mtype, mtext = _msg
        if mtype == "success":
            st.success(mtext)
        elif mtype == "error":
            st.error(mtext)

    # ── 搜索结果（多选 radio，回调方式） ────────────

    _search_opts = st.session_state.get("_search_options")
    if _search_opts and st.session_state.entity_id is None:
        st.radio(
            "🔍 找到多个匹配，请选择:",
            options=[o[0] for o in _search_opts],
            key="_search_radio",
            on_change=_cb_select_entity,
        )

    # ── 查询历史（仅渲染按钮，不自动移动） ─────

    if st.session_state.query_history:
        hcol1, hcol2 = st.columns([3, 1])
        with hcol1:
            st.markdown("**📜 最近查询**")
        with hcol2:
            st.markdown(
                f'<a href="/?clear=1" target="_self" style="color:#999;text-decoration:none;font-size:0.85em" title="清空所有查询历史">✕</a>',
                unsafe_allow_html=True,
            )
        cols = st.columns(3)
        for i, h in enumerate(st.session_state.query_history[:9]):
            with cols[i % 3]:
                label = f"{h.get('ticker', h['name'])}"
                st.button(label, key=f"hist_{i}", use_container_width=True,
                          on_click=_cb_history_click, args=(h,))

    # ── localStorage ↔ URL 参数双向同步 ─────────────
    # 首次访问时从 localStorage 恢复历史；后续每次自动备份到 localStorage
    st.markdown(
        """
<script>
(function() {
    const KEY = 'eve_query_history';
    const stored = localStorage.getItem(KEY);
    const url = new URL(window.location);
    const hasParam = url.searchParams.has('qh');

    if (stored && !hasParam) {
        // 从 localStorage 恢复 → 设置 URL 参数并刷新
        url.searchParams.set('qh', stored);
        window.location.replace(url.toString());
    } else if (hasParam) {
        // 将当前 URL 参数备份到 localStorage
        localStorage.setItem(KEY, url.searchParams.get('qh'));
    }
})();
</script>
""",
        unsafe_allow_html=True,
    )

    st.divider()
    st.markdown("**💡 使用说明**")
    st.markdown(
        """
1. 输入**军团/联盟名称**或**数字 ID**，输入名称后会自动搜索
2. 在搜索结果中选择目标军团/联盟
3. 选择**日报**或**周报**模式，并选择要分析的**日期**
4. 点击「📊 分析」按钮
5. **最近查询**按钮可直接跳转到历史记录
6. ⚠️ zKillboard API 最多支持查询 **7 天以内** 的数据
        """
    )



# ── 中文名称辅助 ────────────────────────────────────────

def _apply_zh_ship_names(df, type_col: str, name_col: str):
    """舰船名加中英双语列。原列变纯中文（y轴用），新增 _bil 列（tooltip用）。"""
    from src.storage.database import batch_get_names_zh
    ids = df[type_col].dropna().unique().tolist()
    if not ids:
        return df
    bil_col = f"{name_col}_bil"
    zh_map = batch_get_names_zh([int(x) for x in ids])
    if zh_map:
        df[bil_col] = df.apply(
            lambda r: f"{zh_map.get(int(r[type_col]), r[name_col])} ({r[name_col]})"
            if int(r[type_col]) in zh_map else r[name_col],
            axis=1,
        )
        df[name_col] = df.apply(
            lambda r: zh_map.get(int(r[type_col]), r[name_col])
            if pd.notna(r[type_col]) else r[name_col],
            axis=1,
        )
    else:
        df[bil_col] = df[name_col]
    return df


def _apply_zh_region_names(df, name_col: str):
    """添加星域中英双语列，原列改为纯中文（y轴用），新增 _bil 列（tooltip用）。"""
    from src.storage.database import get_db_read
    en_names = df[name_col].dropna().unique().tolist()
    if not en_names:
        return df
    bil_col = f"{name_col}_bil"
    try:
        ph = ",".join("?" * len(en_names))
        with get_db_read() as conn:
            rows = conn.execute(
                f"SELECT name_en, name_zh FROM type_translations WHERE name_en IN ({ph})",
                en_names,
            ).fetchall()
        zh_map = {r["name_en"]: r["name_zh"] for r in rows}
        if zh_map:
            df[bil_col] = df[name_col].map(
                lambda x: f"{zh_map[x]} ({x})" if x in zh_map else x
            )
            df[name_col] = df[name_col].map(
                lambda x: zh_map.get(x, x)
            )
        else:
            df[bil_col] = df[name_col]
    except Exception:
        df[bil_col] = df[name_col]
        pass
    return df



# ── 主逻辑 ──────────────────────────────────────────────

# 首次加载：设置默认实体
# 数据加载由 entity_id != None && data_loaded == False 自动触发
if "auto_triggered" not in st.session_state:
    st.session_state.auto_triggered = True
    if st.session_state.entity_id is None:
        _did, _dname, _dtype = DEFAULT_ENTITY_RESOLVE
        st.session_state.entity_id = _did
        st.session_state.entity_name = _dname
        st.session_state.entity_type = _dtype
        st.session_state._last_input = DEFAULT_ENTITY_ID
        st.session_state._input_value = DEFAULT_ENTITY_ID

entity_id = st.session_state.entity_id
entity_name = st.session_state.entity_name
entity_type = st.session_state.entity_type

if entity_id is None:
    st.info("👈 请在左侧输入或选择军团/联盟名称")
    st.stop()


# ── 数据加载 ────────────────────────────────────────────

class _ProgressDisplay:
    """替代 st.status()，用 st.empty() + markdown 确保每次加载完全刷新，不残留旧步骤。"""
    def __init__(self, container, label=""):
        self._c = container
        self._lines: list[str] = []
        self._label = label
        self._state = "running"

    def write(self, text: str):
        self._lines.append(text)
        self._render()

    def update(self, *, label=None, state=None):
        if label is not None:
            self._label = label
        if state is not None:
            self._state = state
        self._render()

    def _render(self):
        icon = {"running": "🔄", "complete": "✅", "error": "❌"}.get(self._state, "🔄")
        header = f"{icon} {self._label}"
        body = "<br>".join(self._lines)
        if self._state == "running":
            content = f"{header}<br>{body}" if body else header
            self._c.markdown(content, unsafe_allow_html=True)
        else:
            # 完成后折叠，点击可展开查看详细步骤
            content = f"<details><summary>{header}</summary><br>{body}</details>" if body else header
            self._c.markdown(content, unsafe_allow_html=True)


def _step_timer(status, step_num: int, total: int, label: str):
    """上下文管理器，自动计时步骤并更新 status。"""
    import contextlib

    @contextlib.contextmanager
    def _step():
        _s = time.time()
        status.write(f"⏳ 步骤 {step_num}/{total}: {label} ...")
        yield
        _elapsed = time.time() - _s
        status.write(f"✅ 步骤 {step_num}/{total}: {label}  ({_elapsed:.1f}s)")
    return _step()


def load_data(date_from, date_to, status):
    """拉取并存储指定日期范围的数据，返回是否成功。"""
    total = 6
    etype = entity_type or "corporation"

    # 步骤 1: 检查缓存
    with _step_timer(status, 1, total, "检查本地缓存"):
        if is_cache_valid(entity_id, etype, date_from, date_to):
            status.write("📦 本地数据有效，跳过 API 请求")
            status.update(label="数据分析中...", state="running")
            status._c.empty()
            return True

    # 计算回溯秒数：zKillboard API 最大支持 604800 秒（7天）
    # 注意：pastSeconds 是相对"当前时间"的回溯，不是指定日期范围
    ZKILL_MAX_PAST = 604800
    start_dt = datetime.fromisoformat(date_from)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    # 计算从 date_from 到 now 的秒数，加上小缓冲（1小时）避免边界问题
    _past_sec = int((now - start_dt).total_seconds()) + 3600
    # 向上取整到天的整倍数（避免 zKillboard 某些秒数返回空的 bug）
    _past_sec = ((_past_sec + 86399) // 86400) * 86400
    if _past_sec > ZKILL_MAX_PAST:
        _past_sec = ZKILL_MAX_PAST

    # 如果需要的数据早于 API 最大回溯范围，给出提示
    days_needed = (now - start_dt).days
    if days_needed > 7:
        status.write(f"⚠️ 所选周期起始于 {days_needed} 天前，超出 zKillboard API 最大回溯范围（7天），早期数据可能无法获取")

    # 步骤 2: 拉取击杀列表
    with _step_timer(status, 2, total, "从 zKillboard 拉取击杀列表"):
        def on_progress(page, items_in_page):
            if items_in_page > 0:
                status.write(f"   ↳ 第 {page} 页（{items_in_page} 条）")
        try:
            results, complete = fetch_entity_kills(
                entity_id, etype,
                past_seconds=_past_sec,
                on_progress=on_progress,
            )
        except RuntimeError as e:
            status.write(f"❌ 数据拉取失败: {e}")
            status.update(label="数据拉取失败", state="error")
            return False
        except Exception as e:
            status.write(f"❌ 数据拉取失败: {e}")
            status.update(label="数据拉取失败", state="error")
            return False

    if not results:
        _fetch_start = (now - timedelta(seconds=_past_sec)).replace(tzinfo=timezone.utc)
        _day = _fetch_start
        while _day < now:
            _next = _day + timedelta(days=1)
            upsert_fetch_log(entity_id, etype, _day.isoformat(), _next.isoformat(), 0, True)
            _day = _next
        upsert_fetch_log(entity_id, etype, date_from, date_to, 0, True)
        status.write("   ↳ 无数据")
        status.update(label="该时段无击杀记录", state="complete")
        status._c.empty()
        return True

    # 步骤 3: ESI 名称解析（角色/军团/联盟/舰船）
    with _step_timer(status, 3, total, "ESI 名称解析（角色/军团/联盟/舰船）"):
        from src.collector.zkillboard import _enrich_killmail_names
        raw_kills = [r["killmail"] for r in results]
        _enrich_killmail_names(raw_kills)

    # 步骤 4: ESI 星域解析（星系→星域）
    with _step_timer(status, 4, total, "ESI 星域解析（星系→星域）"):
        from src.collector.zkillboard import _enrich_system_regions
        raw_kills = [r["killmail"] for r in results]
        _enrich_system_regions(raw_kills)

    # 步骤 5: 存入 SQLite
    with _step_timer(status, 5, total, f"存入 SQLite 数据库（{len(results)} 条）"):
        saved = 0
        skipped = 0
        for r in results:
            if has_killmail(r["killmail"]["killmail_id"]):
                skipped += 1
            else:
                save_killmail(r["killmail"], r["attackers"], r["items"])
                saved += 1
        status.write(f"   ↳ 新增 {saved} 条, 跳过 {skipped} 条重复")

    # 写入 fetch log：按实际拉取范围拆成每天一条
    _fetch_start = (now - timedelta(seconds=_past_sec)).replace(tzinfo=timezone.utc)
    _fetch_end = now
    _day = _fetch_start
    while _day < _fetch_end:
        _next = _day + timedelta(days=1)
        _day_from = _day.isoformat()
        _day_to = _next.isoformat()
        upsert_fetch_log(entity_id, etype, _day_from, _day_to, 0 if not results else saved + skipped, complete)
        _day = _next
    # 同时存一份精确范围，供 is_cache_valid 精确匹配
    upsert_fetch_log(entity_id, etype, date_from, date_to, saved + skipped, complete)
    status.write(f"   ↳ 拉取{'完整' if complete else '不完整（可能还有下一页）'}")

    # 步骤 6: 名称重试（在分析阶段执行）
    with _step_timer(status, 6, total, "ESI 名称重试回填"):
        pass

    status._c.empty()
    return True


# ── 分析按钮逻辑 ────────────────────────────────────────

# 计算日期范围（日报/周报）
report_type = st.session_state.get("_report_type", "daily")
_date_from, _date_to = _get_date_range(selected_date, report_type=report_type)
_report_label = "周报" if report_type == "weekly" else "日报"

# 有实体时始终进入分析/展示流程
if entity_id is not None:
    if not st.session_state.data_loaded and entity_id is not None:
        # 用空容器 + 自定义进度面板，保证每次加载完全刷新
        _status_box = st.empty()
        status = _ProgressDisplay(_status_box, "正在拉取并分析数据 ...")
        _total_start = time.time()
        ok = load_data(_date_from, _date_to, status)
        if not ok:
            status.update(label="数据加载失败", state="error")
            st.stop()

        # ── 执行分析（步骤 7） ──────────────────────────
        with _step_timer(status, 7, 7, "执行 12 个分析查询"):
            analysis = analyze_entity_yesterday(
                entity_id, entity_type=entity_type or "corporation",
                target_date=selected_date, report_type=report_type
            )

        _total_elapsed = time.time() - _total_start
        status.update(label=f"数据分析完成 ✓ 总耗时: {_total_elapsed:.1f}s", state="complete")
        st.session_state.data_loaded = True
    else:
        # 后续 rerun：直接从数据库读取分析结果
        analysis = analyze_entity_yesterday(
            entity_id, entity_type=entity_type or "corporation",
            target_date=selected_date, report_type=report_type
        )

    # ── ticker 解析 ─────────────────────────────────────

    # 解析 ticker 用于展示
    _ticker = st.session_state.get("_ticker_cache", {}).get(entity_id)
    if not _ticker:
        try:
            import requests as _req
            if (entity_type or "corporation") == "alliance":
                _resp = _req.get(f"https://esi.evetech.net/latest/alliances/{entity_id}/",
                                 headers={"User-Agent": "EVE-Killboard-Analysis/1.0"}, timeout=10)
            else:
                _resp = _req.get(f"https://esi.evetech.net/latest/corporations/{entity_id}/",
                                 headers={"User-Agent": "EVE-Killboard-Analysis/1.0"}, timeout=10)
            _ticker = _resp.json().get("ticker", "")
        except Exception:
            _ticker = ""
        _tc = st.session_state.get("_ticker_cache", {})
        _tc[entity_id] = _ticker
        st.session_state._ticker_cache = _tc
    _debug(f"analysis: ticker={_ticker or ''}, data_loaded={st.session_state.data_loaded}")
    st.session_state._last_ticker = _ticker or ""
    # 数据加载完成后统一保存历史
    _save_history(entity_id, entity_name, entity_type, _ticker or "")

    # 新查询/历史点击后 rerun 一次，让侧边栏 UI 刷新查询历史
    if st.session_state.pop("_pending_rerun", False):
        st.rerun()

    display_name = entity_name or f"ID: {entity_id}"
    if _ticker:
        display_name = f"{display_name} <{_ticker}>"

    if report_type == "weekly":
        _start = datetime.fromisoformat(_date_from)
        _end = datetime.fromisoformat(_date_to) - timedelta(days=1)
        date_label = f"{_start.strftime('%Y-%m-%d')} ~ {_end.strftime('%Y-%m-%d')}"
    else:
        date_label = selected_date.strftime("%Y-%m-%d")
    render_title(f"{date_label} {display_name}")

    st.markdown(
        f"<script>document.title = 'EVE {entity_type or '军团'}击杀{_report_label}：{date_label} {display_name}';</script>",
        unsafe_allow_html=True,
    )

    if not analysis.has_data:
        st.warning(f"😴 **{display_name}** 该时段没有击杀/损失记录，或数据尚未拉取。")
        st.info("💡 可切换到其他日期重新拉取数据。")
        st.stop()

    dfs = analysis.to_dataframes()
    stats = analysis.stats

    # ── KPI 指标卡 ──────────────────────────────────────

    isk_killed = stats["kills"]["isk"]
    isk_lost = stats["losses"]["isk"]
    kd_ratio = round(isk_killed / isk_lost, 2) if isk_lost > 0 else "∞"

    def _fmt(v):
        if v >= 1e12:
            return f"{v/1e12:.2f}T"
        if v >= 1e9:
            return f"{v/1e9:.2f}B"
        return f"{v/1e6:.1f}M"

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        st.metric("🎯 击杀", stats["kills"]["count"],
                  help="本方击杀总数（不含 NPC）")
    with k2:
        st.metric("💰 击杀 ISK", _fmt(isk_killed),
                  help="击杀总价值")
    with k3:
        st.metric("💀 损失", stats["losses"]["count"],
                  help="本方被击杀总数")
    with k4:
        st.metric("💸 损失 ISK", _fmt(isk_lost),
                  help="损失总价值")
    with k5:
        st.metric("📊 ISK 比", f"{kd_ratio}",
                  help="击杀 ISK ÷ 损失 ISK")
    with k6:
        st.metric("👥 活跃", analysis.active_members,
                  help="该时段有击杀/损失记录的成员数")

    # ISK 金额格式化辅助（图表 tooltip 用）
    def fmt_isk(val: float) -> str:
        if val >= 1_000_000_000:
            return f"{val / 1_000_000_000:.2f}B"
        elif val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M"
        elif val >= 1_000:
            return f"{val / 1_000:.0f}K"
        return f"{val:.0f}"

    # ── Row 1: 按时统计 ────────────────────────────────

    st.subheader("📈 按时统计")
    if "hourly_timeline" in dfs:
        df = dfs["hourly_timeline"].copy()
        df["kill_isk_label"] = df["kill_isk"].apply(_fmt)
        df["loss_isk_label"] = df["loss_isk"].apply(_fmt)
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df["hour"], y=df["kills"],
            name="击杀",
            marker=dict(
                color=df["kill_isk"],
                colorscale="Greens",
                showscale=False,
            ),
            hovertemplate="小时 %{x}:00<br>击杀: %{y}<br>ISK: %{customdata[0]}<extra></extra>",
            customdata=df[["kill_isk_label"]].values,
        ))
        fig.add_trace(go.Bar(
            x=df["hour"], y=df["losses"],
            name="损失",
            marker=dict(
                color=df["loss_isk"],
                colorscale="Reds",
                showscale=False,
            ),
            hovertemplate="小时 %{x}:00<br>损失: %{y}<br>ISK: %{customdata[0]}<extra></extra>",
            customdata=df[["loss_isk_label"]].values,
        ))
        fig.update_layout(
            barmode="group",
            height=300,
            margin=dict(l=20, r=20, t=20, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
            xaxis_title="小时 (UTC)",
            yaxis_title="数量",
        )
        fig.update_xaxes(dtick=2)

        # 周报模式：按时(3) + 按日(1) 同行
        if report_type == "weekly" and "daily_timeline" in dfs:
            col_h, col_d = st.columns([3, 1])
            with col_h:
                st.plotly_chart(fig, width="stretch")
            with col_d:
                dfd = dfs["daily_timeline"].copy()
                dfd["kill_isk_label"] = dfd["kill_isk"].apply(_fmt)
                dfd["loss_isk_label"] = dfd["loss_isk"].apply(_fmt)
                figd = go.Figure()
                figd.add_trace(go.Bar(
                    x=dfd["day"], y=dfd["kills"],
                    name="击杀",
                    marker=dict(color=dfd["kill_isk"], colorscale="Greens", showscale=False),
                    hovertemplate="%{x}<br>击杀: %{y}<br>ISK: %{customdata[0]}<extra></extra>",
                    customdata=dfd[["kill_isk_label"]].values,
                ))
                figd.add_trace(go.Bar(
                    x=dfd["day"], y=dfd["losses"],
                    name="损失",
                    marker=dict(color=dfd["loss_isk"], colorscale="Reds", showscale=False),
                    hovertemplate="%{x}<br>损失: %{y}<br>ISK: %{customdata[0]}<extra></extra>",
                    customdata=dfd[["loss_isk_label"]].values,
                ))
                figd.update_layout(
                    barmode="group",
                    height=300,
                    margin=dict(l=10, r=10, t=20, b=20),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
                    xaxis_title="日期",
                    yaxis_title="数量",
                    xaxis_tickangle=-45,
                )
                st.plotly_chart(figd, width="stretch")
        else:
            st.plotly_chart(fig, width="stretch")
    else:
        st.info("暂无时间分布数据")

    # ── Row 2: 星域 + 星系 ─────────────────────────────

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🌍 星域")
        if "region_hotspots" in dfs:
            df = dfs["region_hotspots"].copy()
            df = _apply_zh_region_names(df, "solar_system_region_name")
            df["isk_label"] = df["total_isk"].apply(_fmt)
            fig = px.bar(
                df.head(10).iloc[::-1],
                x="kills",
                y="solar_system_region_name",
                orientation="h",
                labels={"kills": "击杀数", "solar_system_region_name": "星域"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="kills",
                hover_data={"solar_system_region_name_bil": False,
                            "total_isk": False, "isk_label": False},
            )
            _chart_df = df.head(10).iloc[::-1]
            fig.update_traces(
                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>"
                    "击杀: %{x}<br>"
                    "ISK: %{customdata[0]}<extra></extra>"
                ),
                customdata=_chart_df[["isk_label", "solar_system_region_name_bil"]].values,
                textposition="outside",
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无星域数据")

    with col2:
        st.subheader("🗺️ 星系")
        if "system_hotspots" in dfs:
            df = dfs["system_hotspots"].copy()
            df["isk_label"] = df["total_isk"].apply(_fmt)
            # 补充所在星域名
            try:
                from src.storage.database import get_db_read
                sys_ids = df["solar_system_id"].dropna().unique().tolist()
                if sys_ids:
                    ph = ",".join("?" * len(sys_ids))
                    with get_db_read() as conn:
                        rows = conn.execute(
                            f"SELECT system_id, region_name FROM system_region_cache WHERE system_id IN ({ph})",
                            sys_ids,
                        ).fetchall()
                    region_map = {r["system_id"]: r["region_name"] for r in rows}
                    df["region_name"] = df["solar_system_id"].map(
                        lambda x: region_map.get(x, "") if pd.notna(x) else ""
                    )
            except Exception:
                df["region_name"] = ""
            df["display"] = df.apply(
                lambda r: f"{r['solar_system_name']} ({r['kills']})",
                axis=1,
            )
            _chart_df = df.head(10).iloc[::-1]
            fig = px.bar(
                _chart_df,
                x="kills",
                y="display",
                orientation="h",
                labels={"kills": "击杀数", "display": "星系"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="kills",
                hover_data={"total_isk": False, "isk_label": False, "region_name": False},
            )
            fig.update_traces(
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "击杀: %{x}<br>"
                    "ISK: %{customdata[0]}<br>"
                    "星域: %{customdata[1]}<extra></extra>"
                ),
                customdata=_chart_df[["isk_label", "region_name"]].values,
                textposition="outside",
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无星系数据")

    # ── Row 3: 联盟排行 ───────────────────────────────

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("⚔️ 杀了谁")
        if "top_killed_alliances" in dfs:
            df = dfs["top_killed_alliances"].copy()
            df["isk_label"] = df["total_isk"].apply(_fmt)
            df["display"] = df.apply(
                lambda r: f"{r['victim_alliance_name']} ({r['kills']})", axis=1
            )
            fig = px.bar(
                df.head(10).iloc[::-1],
                x="kills",
                y="display",
                orientation="h",
                labels={"kills": "击杀数", "display": "联盟"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="kills",
                hover_data={"total_isk": False, "isk_label": True},
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无数据")

    with col2:
        st.subheader("🛡️ 被谁杀")
        if "top_attacker_alliances" in dfs:
            df = dfs["top_attacker_alliances"].copy()
            df["isk_label"] = df["total_isk"].apply(_fmt)
            df["display"] = df.apply(
                lambda r: f"{r['alliance_name']} ({r['kills']})", axis=1
            )
            fig = px.bar(
                df.head(10).iloc[::-1],
                x="kills",
                y="display",
                orientation="h",
                labels={"kills": "击杀数", "display": "联盟"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="kills",
                hover_data={"total_isk": False, "isk_label": True},
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无数据")

    # ── Row 4: 联合击杀 ───────────────────────────────

    col_j1, col_j2 = st.columns(2)

    with col_j1:
        st.subheader("🤝 合作击杀（合作联盟）")
        if "joint_kills_alliances" in dfs:
            df = dfs["joint_kills_alliances"].copy()
            df["isk_label"] = df["total_isk"].apply(_fmt)
            df["display"] = df.apply(
                lambda r: f"{r['alliance_name']}  ({r['joint_kills']}次)", axis=1
            )
            fig = px.bar(
                df.head(10).iloc[::-1],
                x="joint_kills",
                y="display",
                orientation="h",
                labels={"joint_kills": "合作击杀数", "display": "联盟"},
                color="total_isk",
                color_continuous_scale="Blues",
                text="joint_kills",
                hover_data={"total_isk": False, "isk_label": True},
            )
            fig.update_layout(
                height=300,
                margin=dict(l=20, r=20, t=20, b=20),
                xaxis_title="联合击杀数",
            )
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无联合击杀数据")

    with col_j2:
        st.subheader("👥 合作人数（合作联盟参战人数）")
        if "joint_kills_alliances" in dfs:
            df = dfs["joint_kills_alliances"].copy()
            df["isk_label"] = df["total_isk"].apply(_fmt)
            # 按参战人数排序
            df = df.sort_values("participant_count", ascending=False).head(10)
            df["display"] = df.apply(
                lambda r: f"{r['alliance_name']}  ({r['participant_count']}人)", axis=1
            )
            fig = px.bar(
                df.iloc[::-1],
                x="participant_count",
                y="display",
                orientation="h",
                labels={"participant_count": "合作联盟参战人数", "display": "联盟"},
                color="joint_kills",
                color_continuous_scale="Blues",
                text="participant_count",
                hover_data={"total_isk": False, "isk_label": True, "joint_kills": True},
            )
            fig.update_layout(
                height=300,
                margin=dict(l=20, r=20, t=20, b=20),
                xaxis_title="参战人数",
                coloraxis_colorbar_title="合作击杀数",
            )
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无联合参战数据")

    st.markdown("---")

    # ── Row 5: 舰船排行 ───────────────────────────────

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🚢 击杀舰船")
        if "top_kill_ships" in dfs:
            df = dfs["top_kill_ships"].copy()
            df = _apply_zh_ship_names(df, "ship_type_id", "ship_name")
            df["isk_label"] = df["total_isk"].apply(_fmt)
            df["display"] = df.apply(
                lambda r: f"{r['ship_name']} ({r['count']})", axis=1
            )
            _chart_df = df.head(10).iloc[::-1]
            fig = px.bar(
                _chart_df,
                x="count",
                y="display",
                orientation="h",
                labels={"count": "击杀数", "display": "舰船"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="count",
                hover_data={"total_isk": False, "isk_label": False},
            )
            fig.update_traces(
                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>"
                    "击杀: %{x}<br>"
                    "ISK: %{customdata[0]}<extra></extra>"
                ),
                customdata=_chart_df[["isk_label", "ship_name_bil"]].values,
                textposition="outside",
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无数据")

    with col2:
        st.subheader("💀 损失舰船")
        if "top_loss_ships" in dfs:
            df = dfs["top_loss_ships"].copy()
            df = _apply_zh_ship_names(df, "victim_ship_type_id", "victim_ship_name")
            df["isk_label"] = df["total_isk"].apply(_fmt)
            df["display"] = df.apply(
                lambda r: f"{r['victim_ship_name']} ({r['count']})", axis=1
            )
            _chart_df = df.head(10).iloc[::-1]
            fig = px.bar(
                _chart_df,
                x="count",
                y="display",
                orientation="h",
                labels={"count": "损失数", "display": "舰船"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="count",
                hover_data={"total_isk": False, "isk_label": False},
            )
            fig.update_traces(
                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>"
                    "损失: %{x}<br>"
                    "ISK: %{customdata[0]}<extra></extra>"
                ),
                customdata=_chart_df[["isk_label", "victim_ship_name_bil"]].values,
                textposition="outside",
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无数据")

    # ── 第三行：击杀排行表格 ─────────────────────────────

    st.subheader("🏆 击杀排行")
    if "top_killers" in dfs:
        df = dfs["top_killers"].copy()
        # ISK 转为百万单位（保留数值，可排序）
        df["isk_m"] = (df["total_isk"] / 1_000_000).round(1)
        display_df = df[["character_name", "ship_name", "kills", "isk_m"]]
        display_df.columns = ["角色名", "主要舰船", "击杀数", "总 ISK (M)"]

        display_df.index = range(1, len(display_df) + 1)
        display_df.index.name = "排名"

        st.dataframe(display_df, width="stretch")
    else:
        st.info("暂无击杀排行数据")

    # ── 第四行：受害者排行 ────────────────────────────────

    st.subheader("🎯 被杀排行")
    if "top_victims" in dfs:
        df = dfs["top_victims"].copy()
        df["isk_m"] = (df["total_isk"] / 1_000_000).round(1)
        display_df = df[
            ["victim_character_name", "victim_corporation_name", "count", "isk_m"]
        ]
        display_df.columns = ["角色名", "军团", "被击杀次数", "总 ISK (M)"]
        display_df.index = range(1, len(display_df) + 1)
        display_df.index.name = "排名"

        st.dataframe(display_df, width="stretch")
    else:
        st.info("暂无数据")


else:
    render_title()
    st.info("👈 请在左侧输入或选择军团/联盟名称")
