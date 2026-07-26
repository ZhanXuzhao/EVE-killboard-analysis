"""军团击杀日报 — Streamlit 主界面。"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from src.storage.database import init_db
from src.collector.zkillboard import fetch_entity_yesterday_kills, search_entities
from src.storage.repository import save_killmail, has_killmail
from src.analysis.corp_analysis import analyze_entity_yesterday

# ── 页面配置 ────────────────────────────────────────────

st.set_page_config(
    page_title="EVE 军团击杀日报",
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
    """渲染页面标题，统一格式：EVE 军团击杀日报：军团名"""
    if corp_name:
        title = f"🚀 EVE 军团击杀日报：{corp_name}"
    else:
        title = "🚀 EVE 军团击杀日报"
    st.markdown(
        f"<h1 style='text-align: center;'>{title}</h1>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

# ── 侧边栏输入 ──────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ 设置")

    # 默认联盟：Kuan.Dai.Shan (ID: 99009163)
    DEFAULT_ENTITY_ID = "99009163"

    # ── 查询历史（输入框上方） ──────────────────────────

    if "query_history" not in st.session_state:
        st.session_state.query_history = []

    if st.session_state.query_history:
        st.markdown("**📜 最近查询**")
        cols = st.columns(min(4, len(st.session_state.query_history)))
        for i, h in enumerate(st.session_state.query_history[:4]):
            with cols[i]:
                label = f"{h['name']}"
                if st.button(label, key=f"hist_{i}", use_container_width=True):
                    st.session_state.entity_id = h["id"]
                    st.session_state.entity_name = h["name"]
                    st.session_state.entity_type = h["type"]
                    st.session_state.data_loaded = False
                    st.session_state._last_input = str(h["id"])
                    st.session_state._history_click = True
                    st.rerun()

    # 军团输入：支持名称或 ID
    corp_input = st.text_input(
        "军团名称 / ID",
        value=DEFAULT_ENTITY_ID,
        placeholder="例如: Goonswarm Federation 或 987654321",
        help="输入军团名称（自动搜索）或直接输入数字 ID",
    )

    col1, col2 = st.columns(2)
    with col1:
        analyze_btn = st.button("📊 分析昨日击杀", width="stretch", type="primary")
    with col2:
        refresh_btn = st.button("🔄 强制刷新数据", width="stretch")

    st.divider()
    st.markdown("**💡 使用说明**")
    st.markdown(
        """
1. 输入**军团名称**（中文/英文均可）或**数字 ID**
2. 输入名称后会自动搜索，从结果中选择目标军团
3. 点击「分析昨日击杀」
4. 首次分析会自动拉取数据，之后使用缓存
5. 点击「强制刷新」重新从 zKillboard 拉取
        """
    )

# ── 主逻辑 ──────────────────────────────────────────────

# 处理历史点击（强制走输入变化分支）
if st.session_state.get("_history_click"):
    st.session_state._history_click = False
    st.session_state._last_input = None  # 触发重新解析

if not corp_input or not corp_input.strip():
    st.info("👈 请在左侧输入军团名称或 ID 并点击「分析昨日击杀」")
    st.stop()

corp_input = corp_input.strip()

# ── 军团/联盟 搜索 / ID 解析 ──────────────────────────

if "entity_id" not in st.session_state:
    st.session_state.entity_id = None
    st.session_state.entity_name = None
    st.session_state.entity_type = None

entity_id = st.session_state.entity_id
entity_name = st.session_state.entity_name
entity_type = st.session_state.entity_type

# 输入变了或首次输入 → 重新解析
_input_changed = (
    corp_input != st.session_state.get("_last_input", "")
)

if _input_changed:
    st.session_state._last_input = corp_input
    st.session_state.entity_id = None
    st.session_state.entity_name = None
    st.session_state.entity_type = None
    st.session_state.data_loaded = False

    if corp_input.isdigit():
        # 纯数字 → 解析 ID
        corp_id_int = int(corp_input)
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
                entity_name = item.get("name", str(corp_id_int))
                cat = item.get("category", "")
                if cat in ("alliance", "corporation"):
                    detected_type = cat
            else:
                entity_name = str(corp_id_int)
        except Exception:
            entity_name = str(corp_id_int)
        st.session_state.entity_id = corp_id_int
        st.session_state.entity_name = entity_name
        st.session_state.entity_type = detected_type
        # 同步本地变量
        entity_id = corp_id_int
        entity_type = detected_type
    else:
        # 文字 → 搜索军团和联盟
        with st.spinner(f"正在搜索「{corp_input}」..."):
            results = search_entities(corp_input)

        corps = results.get("corporation", [])
        alliances = results.get("alliance", [])
        all_options = []

        if not corps and not alliances:
            st.error(f"❌ 未找到匹配「{corp_input}」的军团或联盟")
            st.stop()

        if alliances:
            all_options.append(("── 联盟 ──", None, None))
            for a in alliances:
                all_options.append((f"{a['name']} (ID: {a['id']})", a["id"], "alliance"))

        if corps:
            all_options.append(("── 军团 ──", None, None))
            for c in corps:
                all_options.append((f"{c['name']} (ID: {c['id']})", c["id"], "corporation"))

        # 只有一个选项（不含分隔符）
        non_sep = [o for o in all_options if o[1] is not None]
        if len(non_sep) == 1:
            entity_id = non_sep[0][1]
            entity_name = non_sep[0][0].split(" (ID:")[0]
            entity_type = non_sep[0][2]
            st.session_state.entity_id = entity_id
            st.session_state.entity_name = entity_name
            st.session_state.entity_type = entity_type
            label = "联盟" if entity_type == "alliance" else "军团"
            st.sidebar.success(f"✅ 已匹配 {label}: **{entity_name}**")
        else:
            selected = st.sidebar.radio(
                "🔍 找到多个匹配，请选择:",
                options=[o[0] for o in all_options],
                index=0,
            )
            for label_t, eid, etype in all_options:
                if label_t == selected and eid is not None:
                    entity_id = eid
                    entity_name = label_t.split(" (ID:")[0]
                    entity_type = etype
                    st.session_state.entity_id = entity_id
                    st.session_state.entity_name = entity_name
                    st.session_state.entity_type = entity_type
                    break

elif entity_id is None:
    st.info("👈 请在左侧输入军团名称或 ID")
    st.stop()

# 状态位
if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False

# 首次启动自动触发分析（默认军团）
if "auto_triggered" not in st.session_state:
    st.session_state.auto_triggered = True
    analyze_btn = True


# ── 数据加载 ────────────────────────────────────────────

def load_data(force_refresh: bool = False):
    """拉取并存储昨日数据。"""
    progress_bar = st.progress(0, text="正在拉取击杀数据...")
    status_text = st.empty()

    def on_progress(current, total):
        pct = current / total
        progress_bar.progress(pct, text=f"正在拉取击杀详情 ({current}/{total})...")
        status_text.text(f"已处理 {current}/{total} 条")

    try:
        results = fetch_entity_yesterday_kills(entity_id, entity_type=entity_type or "corporation", on_progress=on_progress)
    except Exception as e:
        st.error(f"❌ 数据拉取失败: {e}")
        return False

    progress_bar.progress(1.0, text="正在存入数据库...")

    saved = 0
    skipped = 0
    for r in results:
        if has_killmail(r["killmail"]["killmail_id"]):
            skipped += 1
            if force_refresh:
                # 暂时简单处理：跳过已存在的
                skipped += 0
            else:
                skipped += 0
        else:
            save_killmail(r["killmail"], r["attackers"], r["items"])
            saved += 1

    progress_bar.empty()
    status_text.empty()

    st.success(f"✅ 拉取完成! 新增 {saved} 条, 跳过 {skipped} 条重复")
    return True


# ── 分析按钮逻辑 ────────────────────────────────────────

if analyze_btn or refresh_btn or st.session_state.data_loaded:
    if refresh_btn:
        st.session_state.data_loaded = False

    if not st.session_state.data_loaded:
        with st.spinner("正在拉取并分析数据..."):
            load_data(force_refresh=refresh_btn)
        st.session_state.data_loaded = True

    # ── 执行分析 ──────────────────────────────────────────

    display_name = entity_name or f"ID: {entity_id}"
    render_title(display_name)

    st.markdown(
        f"<script>document.title = 'EVE {entity_type or '军团'}击杀日报：{display_name}';</script>",
        unsafe_allow_html=True,
    )

    analysis = analyze_entity_yesterday(entity_id, entity_type=entity_type or "corporation")

    if not analysis.has_data:
        st.warning(f"😴 **{display_name}** 昨日没有击杀/损失记录，或数据尚未拉取。")
        st.info("💡 如果是首次使用，请点击「强制刷新数据」从 zKillboard 拉取。")
        st.stop()

    # 记录查询历史
    _history = st.session_state.query_history
    _entry = {"id": entity_id, "name": display_name, "type": entity_type or "corporation"}
    # 去重：如果已存在则删除旧记录
    _history[:] = [h for h in _history if not (h["id"] == entity_id and h["type"] == (entity_type or "corporation"))]
    _history.insert(0, _entry)
    st.session_state.query_history = _history[:10]  # 最多保留 10 条

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
        st.subheader("🌍 星域 Top 10")
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
        st.subheader("🗺️ 星系 Top 10")
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
        st.subheader("⚔️ 击杀联盟 Top 10")
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
        st.subheader("🛡️ 被杀联盟 Top 10")
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
        st.subheader("🚢 击杀用舰船 Top 10")
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
        st.subheader("💀 被击毁舰船 Top 10")
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

    st.subheader("🎯 常被击杀的目标")
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
