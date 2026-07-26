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
from src.collector.zkillboard import fetch_corp_yesterday_kills, search_corporation
from src.storage.repository import save_killmail, has_killmail
from src.analysis.corp_analysis import analyze_corp_yesterday

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

    # 默认军团 Kuan.Dai.Shan (ID: 98626718)
    DEFAULT_CORP_ID = "98626718"

    # 军团输入：支持名称或 ID
    corp_input = st.text_input(
        "军团名称 / ID",
        value=DEFAULT_CORP_ID,
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

if not corp_input or not corp_input.strip():
    st.info("👈 请在左侧输入军团名称或 ID 并点击「分析昨日击杀」")
    st.stop()

corp_input = corp_input.strip()

# ── 军团名称搜索 / ID 解析 ────────────────────────────

if "corp_id" not in st.session_state:
    st.session_state.corp_id = None
    st.session_state.corp_name = None

corp_id_int = st.session_state.corp_id
corp_name_display = st.session_state.corp_name

# 输入变了或首次输入 → 重新解析
_input_changed = (
    corp_input != st.session_state.get("_last_input", "")
)

if _input_changed:
    st.session_state._last_input = corp_input
    st.session_state.corp_id = None
    st.session_state.corp_name = None
    st.session_state.data_loaded = False

    if corp_input.isdigit():
        # 纯数字 → 解析 ID 获取军团名
        corp_id_int = int(corp_input)
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
                corp_name_display = _data[0].get("name", str(corp_id_int))
            else:
                corp_name_display = str(corp_id_int)
        except Exception:
            corp_name_display = str(corp_id_int)
        st.session_state.corp_id = corp_id_int
        st.session_state.corp_name = corp_name_display
    else:
        # 文字 → 搜索军团
        with st.spinner(f"正在搜索「{corp_input}」..."):
            results = search_corporation(corp_input)

        if not results:
            st.error(f"❌ 未找到匹配「{corp_input}」的军团，请检查名称后重试")
            st.stop()

        if len(results) == 1:
            corp_id_int = results[0]["id"]
            corp_name_display = results[0]["name"]
            st.session_state.corp_id = corp_id_int
            st.session_state.corp_name = corp_name_display
            st.sidebar.success(f"✅ 已匹配: **{corp_name_display}** (ID: {corp_id_int})")
        else:
            # 多个结果 → 让用户选择
            options = {f"{r['name']} (ID: {r['id']})": r["id"] for r in results}
            selected = st.sidebar.radio(
                "🔍 找到多个匹配，请选择:",
                options=list(options.keys()),
                index=0,
            )
            corp_id_int = options[selected]
            corp_name_display = selected.split(" (ID:")[0]
            st.session_state.corp_id = corp_id_int
            st.session_state.corp_name = corp_name_display
elif corp_id_int is None:
    st.info("👈 请在左侧输入军团名称或 ID 并点击「分析昨日击杀」")
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
        results = fetch_corp_yesterday_kills(corp_id_int, on_progress=on_progress)
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

    display_name = corp_name_display or f"ID: {corp_id_int}"
    render_title(display_name)

    # 更新浏览器标签页标题
    st.markdown(
        f"<script>document.title = 'EVE 军团击杀日报：{display_name}';</script>",
        unsafe_allow_html=True,
    )

    analysis = analyze_corp_yesterday(corp_id_int)

    if not analysis.has_data:
        st.warning(f"😴 **{display_name}** 昨日没有击杀/损失记录，或数据尚未拉取。")
        st.info("💡 如果是首次使用，请点击「强制刷新数据」从 zKillboard 拉取。")
        st.stop()

    dfs = analysis.to_dataframes()
    stats = analysis.stats

    # ── KPI 指标卡 ──────────────────────────────────────

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "🎯 总击杀",
            stats["kills"]["count"],
            help="本方成员参与击杀的总数（不含 NPC）",
        )
    with col2:
        st.metric(
            "💀 总损失",
            stats["losses"]["count"],
            help="本方成员被击杀的总数",
        )
    with col3:
        isk_killed = stats["kills"]["isk"]
        isk_lost = stats["losses"]["isk"]
        kd_ratio = (
            round(isk_killed / isk_lost, 2) if isk_lost > 0 else "∞"
        )
        st.metric(
            "💰 ISK 击杀/损失比",
            f"{kd_ratio}",
            help="击杀 ISK 总值 ÷ 损失 ISK 总值",
        )
    with col4:
        st.metric(
            "👥 活跃成员",
            analysis.active_members,
            help="昨日有击杀或损失记录的成员数",
        )

    # ISK 金额格式化辅助
    def fmt_isk(val: float) -> str:
        if val >= 1_000_000_000:
            return f"{val / 1_000_000_000:.2f}B"
        elif val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M"
        elif val >= 1_000:
            return f"{val / 1_000:.0f}K"
        return f"{val:.0f}"

    # ── 第一行：双图表 ───────────────────────────────────

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📈 击杀时间分布")
        if "hourly_timeline" in dfs:
            df = dfs["hourly_timeline"]
            fig = px.bar(
                df,
                x="hour",
                y="kills",
                labels={"hour": "小时 (UTC)", "kills": "击杀数"},
                color="kills",
                color_continuous_scale="Blues",
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_xaxes(dtick=2)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无时间分布数据")

    with col2:
        st.subheader("🗺️ 星系热区 Top 10")
        if "system_hotspots" in dfs:
            df = dfs["system_hotspots"]
            df["display"] = df.apply(
                lambda r: f"{r['solar_system_name']} ({r['kills']})",
                axis=1,
            )
            fig = px.bar(
                df.head(10),
                x="kills",
                y="display",
                orientation="h",
                labels={"kills": "击杀数", "display": "星系"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="kills",
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无星系数据")

    # ── 星域热区 ────────────────────────────────────────

    st.subheader("🌍 星域热区 Top 10")
    if "region_hotspots" in dfs:
        df = dfs["region_hotspots"]
        fig = px.bar(
            df.head(10),
            x="kills",
            y="solar_system_region_name",
            orientation="h",
            labels={"kills": "击杀数", "solar_system_region_name": "星域"},
            color="total_isk",
            color_continuous_scale="Viridis",
            text="kills",
        )
        fig.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20))
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("暂无星域数据")

    # ── 第二行：双图表 ───────────────────────────────────

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🚢 击杀用舰船 Top 10")
        if "top_kill_ships" in dfs:
            df = dfs["top_kill_ships"]
            df["display"] = df.apply(
                lambda r: f"{r['ship_name']} ({r['count']})", axis=1
            )
            fig = px.bar(
                df.head(10),
                x="count",
                y="display",
                orientation="h",
                labels={"count": "击杀数", "display": "舰船"},
                color="total_isk",
                color_continuous_scale="Greens",
                text="count",
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无数据")

    with col2:
        st.subheader("💀 被击毁舰船 Top 10")
        if "top_loss_ships" in dfs:
            df = dfs["top_loss_ships"]
            df["display"] = df.apply(
                lambda r: f"{r['victim_ship_name']} ({r['count']})", axis=1
            )
            fig = px.bar(
                df.head(10),
                x="count",
                y="display",
                orientation="h",
                labels={"count": "损失数", "display": "舰船"},
                color="total_isk",
                color_continuous_scale="OrRd",
                text="count",
            )
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无数据")

    # ── 第三行：击杀排行表格 ─────────────────────────────

    st.subheader("🏆 击杀排行")
    if "top_killers" in dfs:
        df = dfs["top_killers"]
        df["total_isk_display"] = df["total_isk"].apply(fmt_isk)
        display_df = df[["character_name", "ship_name", "kills", "total_isk_display"]]
        display_df.columns = ["角色名", "主要舰船", "击杀数", "总 ISK"]

        # 排名列
        display_df.index = range(1, len(display_df) + 1)
        display_df.index.name = "排名"

        st.dataframe(display_df, width="stretch")
    else:
        st.info("暂无击杀排行数据")

    # ── 第四行：受害者排行 ────────────────────────────────

    st.subheader("🎯 常被击杀的目标")
    if "top_victims" in dfs:
        df = dfs["top_victims"]
        df["total_isk_display"] = df["total_isk"].apply(fmt_isk)
        display_df = df[
            ["victim_character_name", "victim_corporation_name", "count", "total_isk_display"]
        ]
        display_df.columns = ["角色名", "军团", "被击杀次数", "总 ISK"]
        display_df.index = range(1, len(display_df) + 1)
        display_df.index.name = "排名"

        st.dataframe(display_df, width="stretch")
    else:
        st.info("暂无数据")

    # ── 联盟分析 ────────────────────────────────────────

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("⚔️ 击杀最多的联盟")
        if "top_killed_alliances" in dfs:
            df = dfs["top_killed_alliances"]
            df["display"] = df.apply(
                lambda r: f"{r['victim_alliance_name']} ({r['kills']})", axis=1
            )
            fig = px.bar(
                df.head(10),
                x="kills",
                y="display",
                orientation="h",
                labels={"kills": "击杀数", "display": "联盟"},
                color="total_isk",
                color_continuous_scale="Reds",
                text="kills",
            )
            fig.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无数据")

    with col2:
        st.subheader("🛡️ 击杀我们最多的联盟")
        if "top_attacker_alliances" in dfs:
            df = dfs["top_attacker_alliances"]
            df["display"] = df.apply(
                lambda r: f"{r['alliance_name']} ({r['kills']})", axis=1
            )
            fig = px.bar(
                df.head(10),
                x="kills",
                y="display",
                orientation="h",
                labels={"kills": "击杀数", "display": "联盟"},
                color="total_isk",
                color_continuous_scale="OrRd",
                text="kills",
            )
            fig.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无数据")


else:
    render_title()
    st.info("👈 请在左侧输入军团名称或 ID")
