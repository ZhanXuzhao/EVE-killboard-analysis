"""击杀日报 — Streamlit 主界面。"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

from src.storage.database import init_db
from src.collector.zkillboard import fetch_entity_yesterday_kills, search_entities
from src.storage.repository import save_killmail, has_killmail
from src.analysis.corp_analysis import analyze_entity_yesterday, _get_date_range, _has_data

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
    """渲染页面标题，统一格式：EVE 击杀日报：军团名"""
    if corp_name:
        title = f"🚀 EVE 击杀日报：{corp_name}"
    else:
        title = "🚀 EVE 击杀日报"
    st.markdown(
        f"<h1 style='text-align: center;'>{title}</h1>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

# ── 侧边栏输入 ──────────────────────────────────────────

# 默认联盟：Kuan.Dai.Shan (ID: 99009163)
DEFAULT_ENTITY_ID = "Dracarys."
DEFAULT_ENTITY_RESOLVE = (99009163, "Dracarys.", "alliance")

with st.sidebar:
    st.header("⚙️ 设置")

    # ── 查询历史（输入框上方） ──────────────────────────

    if "query_history" not in st.session_state:
        # 从本地文件加载持久化的查询历史
        _hist_file = Path(__file__).resolve().parent.parent / "data" / "query_history.json"
        if _hist_file.exists():
            try:
                import json
                with open(_hist_file, encoding="utf-8") as _f:
                    st.session_state.query_history = json.load(_f)
            except Exception:
                st.session_state.query_history = []
        else:
            st.session_state.query_history = []

    # 检测清空历史链接点击
    if st.query_params.get_all("clear"):
        st.session_state.query_history = []
        try:
            import json
            _hist_file = Path(__file__).resolve().parent.parent / "data" / "query_history.json"
            with open(_hist_file, "w", encoding="utf-8") as _f:
                json.dump([], _f)
        except Exception:
            pass
        st.query_params.clear()

    if st.session_state.query_history:
        hcol1, hcol2 = st.columns([3, 1])
        with hcol1:
            st.markdown("**📜 最近查询**")
        with hcol2:
            st.markdown(
                f'<a href="/?clear=1" target="_self" style="color:#999;text-decoration:none;font-size:0.85em" title="清空所有查询历史">✕</a>',
                unsafe_allow_html=True,
            )
        num_cols = min(3, len(st.session_state.query_history))
        cols = st.columns(num_cols)
        for i, h in enumerate(st.session_state.query_history[:num_cols]):
            with cols[i]:
                label = f"{h.get('ticker', h['name'])}"
                if st.button(label, key=f"hist_{i}", use_container_width=True):
                    st.session_state.entity_id = h["id"]
                    st.session_state.entity_name = h["name"]
                    st.session_state.entity_type = h["type"]
                    st.session_state.data_loaded = False
                    st.session_state._last_input = str(h["id"])
                    st.session_state._history_click = True
                    st.session_state._history_trigger = True

    # ── 初始化 session_state ──────────────────────────

    if "entity_id" not in st.session_state:
        st.session_state.entity_id = None
        st.session_state.entity_name = None
        st.session_state.entity_type = None
        st.session_state.data_loaded = False

    # ── 日期选择 ────────────────────────────────────

    today = datetime.now(timezone.utc).date()
    if "selected_date" not in st.session_state:
        st.session_state.selected_date = today - timedelta(days=1)
    selected_date = st.date_input(
        "📅 选择日期",
        value=st.session_state.selected_date,
        max_value=today,
        help="选择要分析的日期",
    )
    if selected_date != st.session_state.selected_date:
        st.session_state.selected_date = selected_date
        st.session_state.data_loaded = False
        st.rerun()

    # ── 搜索表单（仅按 Enter 或点击按钮时触发） ──────

    with st.form(key="search_form"):
        corp_input = st.text_input(
            "军团名称 / ID",
            value=DEFAULT_ENTITY_ID,
            placeholder="例如: Goonswarm Federation 或 987654321",
            help="输入军团名称（自动搜索）或直接输入数字 ID",
        )
        analyze_btn = st.form_submit_button("📊 分析", type="primary", use_container_width=True)

        # 表单提交时才执行搜索/解析

        # 表单提交时才执行搜索/解析
        if analyze_btn:
            st.session_state._last_input = corp_input.strip()
            st.session_state.entity_id = None
            st.session_state.entity_name = None
            st.session_state.entity_type = None
            st.session_state.data_loaded = False

            if corp_input.strip().isdigit():
                # 纯数字 → 解析 ID
                corp_id_int = int(corp_input.strip())
                detected_type = "corporation"
                try:
                    import requests as _req
                    _resp = _req.post(
                        "https://esi.evetech.net/latest/universe/names/",
                        json=[corp_id_int],
                        headers={"User-Agent": "EVE-Killboard-Analysis/1.0"},
                        timeout=10,
                    )
                    _data = _resp.json()
                    if isinstance(_data, list) and len(_data) > 0:
                        item = _data[0]
                        st.session_state.entity_name = item.get("name", str(corp_id_int))
                        cat = item.get("category", "")
                        if cat in ("alliance", "corporation"):
                            detected_type = cat
                    else:
                        st.session_state.entity_name = str(corp_id_int)
                except Exception:
                    st.session_state.entity_name = str(corp_id_int)
                st.session_state.entity_id = corp_id_int
                st.session_state.entity_type = detected_type
            else:
                # 文字 → 搜索军团和联盟
                with st.spinner(f"正在搜索「{corp_input.strip()}」..."):
                    results = search_entities(corp_input.strip())

                corps = results.get("corporation", [])
                alliances = results.get("alliance", [])
                all_options = []

                if corps or alliances:
                    if alliances:
                        all_options.append(("── 联盟 ──", None, None))
                        for a in alliances:
                            all_options.append((f"{a['name']} (ID: {a['id']})", a["id"], "alliance"))
                    if corps:
                        all_options.append(("── 军团 ──", None, None))
                        for c in corps:
                            all_options.append((f"{c['name']} (ID: {c['id']})", c["id"], "corporation"))

                    st.session_state._search_options = all_options
                    st.session_state._search_input = corp_input.strip()

                    non_sep = [o for o in all_options if o[1] is not None]
                    if len(non_sep) == 1:
                        st.session_state.entity_id = non_sep[0][1]
                        st.session_state.entity_name = non_sep[0][0].split(" (ID:")[0]
                        st.session_state.entity_type = non_sep[0][2]
                        st.session_state._search_options = None
                        label = "联盟" if st.session_state.entity_type == "alliance" else "军团"
                        st.success(f"✅ 已匹配 {label}: **{st.session_state.entity_name}**")
                else:
                    st.error(f"❌ 未找到匹配「{corp_input.strip()}」的军团或联盟")

    # ── 搜索结果（表单外渲染以维持 widget 状态） ─────

    _search_opts = st.session_state.get("_search_options")
    _search_inp = st.session_state.get("_search_input")
    if _search_opts and _search_inp and corp_input.strip() == _search_inp and st.session_state.entity_id is None:
        selected = st.radio(
            "🔍 找到多个匹配，请选择:",
            options=[o[0] for o in _search_opts],
            index=0,
        )
        for label_t, eid, etype in _search_opts:
            if label_t == selected and eid is not None:
                st.session_state.entity_id = eid
                st.session_state.entity_name = label_t.split(" (ID:")[0]
                st.session_state.entity_type = etype
                st.session_state.data_loaded = False
                st.session_state._search_selected = True
                break

    st.divider()
    st.markdown("**💡 使用说明**")
    st.markdown(
        """
1. 输入**军团名称**（中文/英文均可）或**数字 ID**
2. 输入名称后会自动搜索，从结果中选择目标军团
3. 选择要分析的**日期**
4. 点击「分析」
5. **使用缓存**勾选时，跳过 API 请求，直接分析本地已有数据
6. 取消勾选则强制从 zKillboard 拉取最新数据
        """
    )

    use_cache = st.checkbox("📦 使用缓存", value=True,
                            help="勾选时相同查询直接从本地数据库读取，不请求网络")

# ── 主逻辑 ──────────────────────────────────────────────

# 处理历史点击
if st.session_state.get("_history_click"):
    st.session_state._history_click = False

# 首次加载：自动处理默认数字 ID + 触发分析
if "auto_triggered" not in st.session_state:
    st.session_state.auto_triggered = True
    if st.session_state.entity_id is None:
        _did, _dname, _dtype = DEFAULT_ENTITY_RESOLVE
        st.session_state.entity_id = _did
        st.session_state.entity_name = _dname
        st.session_state.entity_type = _dtype
        st.session_state._last_input = DEFAULT_ENTITY_ID
    if st.session_state.entity_id is not None:
        analyze_btn = True

entity_id = st.session_state.entity_id
entity_name = st.session_state.entity_name
entity_type = st.session_state.entity_type

# 点击最近查询记录 → 直接触发分析
if st.session_state.pop("_history_trigger", False):
    analyze_btn = True

if entity_id is None:
    st.info("👈 请在左侧输入军团名称或 ID")
    st.stop()

# 从搜索结果中选中了实体 → 自动触发分析
if st.session_state.pop("_search_selected", False):
    analyze_btn = True


# ── 数据加载 ────────────────────────────────────────────

def load_data(target_date, use_cache: bool = True):
    """拉取并存储指定日期的数据。"""
    # 使用缓存时检查数据库是否有数据
    if use_cache:
        dt_from, dt_to = _get_date_range(target_date)
        if _has_data(entity_id, dt_from, dt_to, entity_type=entity_type or "corporation"):
            st.info("📦 本地已有缓存数据，跳过 API 请求")
            return True

    # 根据选定日期计算 zKillboard 回溯秒数
    today = datetime.now(timezone.utc).date()
    days_ago = (today - target_date).days
    past_seconds = max(86400, (days_ago + 1) * 86400)

    progress_bar = st.progress(0, text="正在拉取击杀数据...")
    status_text = st.empty()

    def on_progress(page, items_in_page):
        if items_in_page > 0:
            progress_bar.progress(0.5, text=f"正在拉取击杀详情 (第{page}页, {items_in_page}条)...")
            status_text.text(f"第{page}页")
        else:
            progress_bar.empty()
            status_text.empty()

    try:
        results = fetch_entity_yesterday_kills(entity_id, entity_type=entity_type or "corporation", on_progress=on_progress, past_seconds=past_seconds)
    except RuntimeError as e:
        st.error(f"❌ {e}")
        return False
    except Exception as e:
        st.error(f"❌ 数据拉取失败: {e}")
        return False

    progress_bar.progress(1.0, text="正在存入数据库...")

    saved = 0
    skipped = 0
    for r in results:
        if has_killmail(r["killmail"]["killmail_id"]):
            skipped += 1
        else:
            save_killmail(r["killmail"], r["attackers"], r["items"])
            saved += 1

    progress_bar.empty()
    status_text.empty()

    st.success(f"✅ 拉取完成! 新增 {saved} 条, 跳过 {skipped} 条重复")
    return True


# ── 分析按钮逻辑 ────────────────────────────────────────

# 日期变更或表单提交 → 进入分析流程
if analyze_btn or not st.session_state.data_loaded:
    if not st.session_state.data_loaded and entity_id is not None:
        with st.spinner("正在拉取并分析数据..."):
            load_data(selected_date, use_cache=use_cache)
        st.session_state.data_loaded = True

    # ── 执行分析 ──────────────────────────────────────────

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

    display_name = entity_name or f"ID: {entity_id}"
    if _ticker:
        display_name = f"{display_name} <{_ticker}>"
    date_label = selected_date.strftime("%Y-%m-%d")
    render_title(f"{date_label} {display_name}")

    st.markdown(
        f"<script>document.title = 'EVE {entity_type or '军团'}击杀日报：{date_label} {display_name}';</script>",
        unsafe_allow_html=True,
    )

    analysis = analyze_entity_yesterday(entity_id, entity_type=entity_type or "corporation", target_date=selected_date)

    if not analysis.has_data:
        st.warning(f"😴 **{display_name}** 昨日没有击杀/损失记录，或数据尚未拉取。")
        st.info("💡 取消勾选「使用缓存」可强制从 zKillboard 拉取。")
        st.stop()

    # 记录查询历史
    _history = st.session_state.query_history
    _entry = {"id": entity_id, "name": display_name, "type": entity_type or "corporation", "ticker": _ticker}
    # 去重：如果已存在则删除旧记录
    _history[:] = [h for h in _history if not (h["id"] == entity_id and h["type"] == (entity_type or "corporation"))]
    _history.insert(0, _entry)
    st.session_state.query_history = _history[:10]  # 最多保留 10 条
    # 持久化到本地文件
    try:
        import json
        _hist_file = Path(__file__).resolve().parent.parent / "data" / "query_history.json"
        with open(_hist_file, "w", encoding="utf-8") as _f:
            json.dump(st.session_state.query_history, _f, ensure_ascii=False, indent=2)
    except Exception:
        pass

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
                  help="昨日有击杀/损失记录的成员数")

    # ISK 金额格式化辅助（图表 tooltip 用）
    def fmt_isk(val: float) -> str:
        if val >= 1_000_000_000:
            return f"{val / 1_000_000_000:.2f}B"
        elif val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M"
        elif val >= 1_000:
            return f"{val / 1_000:.0f}K"
        return f"{val:.0f}"

    # ── Row 1: 击杀时间分布 ────────────────────────────

    st.subheader("📈 击杀损失分布")
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
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("暂无时间分布数据")

    # ── Row 2: 星域 + 星系 ─────────────────────────────

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🌍 星域 Top")
        if "region_hotspots" in dfs:
            df = dfs["region_hotspots"].copy()
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
                hover_data={"total_isk": False, "isk_label": True},
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无星域数据")

    with col2:
        st.subheader("🗺️ 星系 Top")
        if "system_hotspots" in dfs:
            df = dfs["system_hotspots"].copy()
            df["isk_label"] = df["total_isk"].apply(_fmt)
            df["display"] = df.apply(
                lambda r: f"{r['solar_system_name']} ({r['kills']})",
                axis=1,
            )
            fig = px.bar(
                df.head(10).iloc[::-1],
                x="kills",
                y="display",
                orientation="h",
                labels={"kills": "击杀数", "display": "星系"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="kills",
                hover_data={"total_isk": False, "isk_label": True},
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无星系数据")

    # ── Row 3: 联盟排行 ───────────────────────────────

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("⚔️ 击杀联盟 Top")
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
        st.subheader("🛡️ 被杀联盟 Top")
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

    # ── Row 4: 舰船排行 ───────────────────────────────

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🚢 击杀舰船 Top")
        if "top_kill_ships" in dfs:
            df = dfs["top_kill_ships"].copy()
            df["isk_label"] = df["total_isk"].apply(_fmt)
            df["display"] = df.apply(
                lambda r: f"{r['ship_name']} ({r['count']})", axis=1
            )
            fig = px.bar(
                df.head(10).iloc[::-1],
                x="count",
                y="display",
                orientation="h",
                labels={"count": "击杀数", "display": "舰船"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="count",
                hover_data={"total_isk": False, "isk_label": True},
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无数据")

    with col2:
        st.subheader("💀 损失舰船 Top")
        if "top_loss_ships" in dfs:
            df = dfs["top_loss_ships"].copy()
            df["isk_label"] = df["total_isk"].apply(_fmt)
            df["display"] = df.apply(
                lambda r: f"{r['victim_ship_name']} ({r['count']})", axis=1
            )
            fig = px.bar(
                df.head(10).iloc[::-1],
                x="count",
                y="display",
                orientation="h",
                labels={"count": "损失数", "display": "舰船"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="count",
                hover_data={"total_isk": False, "isk_label": True},
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
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
    st.info("👈 请在左侧输入军团名称或 ID")
