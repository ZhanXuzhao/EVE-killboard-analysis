# 🚀 EVE 击杀日报/周报

EVE Online 军团与联盟击杀记录查询与分析工具。

基于 **zKillboard API** + **ESI API**，提供军团/联盟的击杀/损失数据拉取、本地缓存、多维度分析与可视化展示。支持**中英文双语**显示。


---

## 📸 截图

[点这里开始体验](https://eve-killboard-analysis-kh7x2vrzkn9wky2ajcrkxn.streamlit.app/)

![应用截图1](images/屏幕截图%202026-07-27%20125652.png)
![应用截图2](images/屏幕截图%202026-07-27%20125945.png)
---

## ✨ 功能特性

### 📊 多维度分析

| 功能 | 说明 |
|------|------|
| **KPI 指标卡** | 击杀数、击杀 ISK、损失数、损失 ISK、ISK 比率、活跃成员数 |
| **📈 按时统计** | 24 小时击杀/损失分布柱状图（颜色编码 ISK 价值） |
| **📅 按日统计** | 周报模式下 7 天每天击杀/损失分布 |
| **🌍 星域热区** | 击杀发生最多的星域排行（中文显示） |
| **🗺️ 星系热区** | 击杀发生最多的星系排行（含星域 tooltip） |
| **⚔️ 击杀目标排行** | 被本方击杀的受害者联盟 Top 10 |
| **🛡️ 被击杀源排行** | 击杀本方的攻击者联盟 Top 10 |
| **🚢 击杀舰船排行** | 本方击杀时使用的舰船 Top 10（中文显示） |
| **💀 损失舰船排行** | 本方被击毁的舰船类型 Top 10（中文显示） |
| **🏆 击杀排行** | 军团/联盟成员击杀榜（含 ISK） |
| **🎯 被杀排行** | 被本方击杀最多的角色排行 |

### 🌐 中英文双语

- 所有舰船名、星域名默认显示**中文**
- Tooltip（悬浮窗）显示 **中文 (English)** 双语
- Y 轴标签保持纯中文，简洁清晰
- 翻译数据来自 CCP 官方 SDE + ESI 中文接口

### 🎯 支持的实体

- **军团 (Corporation)** — 按名称或 ID 搜索分析
- **联盟 (Alliance)** — 按名称或 ID 搜索分析
- 默认预置：**Dracarys.** 联盟 (ID: `99009163`)

### 📅 报告类型

- **日报** — 分析 UTC 某一天的数据 `[00:00, 次日 00:00)`
- **周报** — 分析所选日期所在周的数据（当周一 ~ 下周一）

### 🧠 智能特性

- **名称自动搜索** — 输入名称自动通过 zKillboard 联想搜索
- **数字 ID 直连** — 直接输入数字 ID 跳过搜索步骤
- **查询历史** — 最近 10 条查询一键回访（同步到浏览器 localStorage）
- **本地缓存** — 已拉取的数据自动缓存到 SQLite，避免重复请求
- **去重存储** — 击杀数据 `INSERT OR IGNORE`，不重复入库
- **ESI 名称解析** — 自动将 ID 解析为可读名称，DB 缓存避免重复调用
- **星域映射** — 自动将星系 ID 映射到所属星域名称

---

## 🏗️ 技术栈

| 组件 | 技术 |
|------|------|
| **Web UI** | Streamlit |
| **图表** | Plotly |
| **数据库** | SQLite（WAL 模式，读写分离） |
| **数据源** | zKillboard REST API |
| **名称解析** | EVE ESI API |
| **翻译数据** | CCP SDE (`fsd/types.yaml`) |
| **语言** | Python 3.10+ |

---

## 🚀 快速开始

### 前置要求

- Python 3.10+
- pip

### 安装

```bash
# 克隆仓库
git clone <repo-url>
cd EVE-killboard-analysis

# 创建虚拟环境（推荐）
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动应用
streamlit run src/app.py
```

启动后访问 **http://localhost:8501**

---

## 🗜️ 打包为独立 exe（无需 Python 环境）

可以将此项目打包成一个 **独立的 exe 文件包**，发给没有 Python 的同事/朋友直接使用。

### 打包方法

```bash
# 1. 确保已安装依赖
pip install -r requirements.txt

# 2. 一键打包（推荐）
双击 build_exe.bat
# 或
python build_exe.py

# 打包完成后输出到 dist/EVE-Killboard-Analysis/
```

### 使用打包后的 exe

1. 进入 `dist/EVE-Killboard-Analysis/` 目录
2. **双击 `EVE-Killboard-Analysis.exe`**
3. 程序会自动启动 Streamlit 服务器并打开浏览器
4. 关闭命令行窗口即可停止程序

### 给他人分发

直接把 **整个** `dist/EVE-Killboard-Analysis/` 文件夹压缩打包发给别人即可。

> ⚠️ 接收方无需安装 Python，双击 exe 就能用。
> 首次启动可能稍慢（Streamlit 初始化），请耐心等待几秒。

---

### 基本用法

1. 在左侧输入 **军团/联盟名称**（自动搜索）或 **数字 ID**
2. 多个匹配时从下拉列表中选择
3. 选择 **日报** 或 **周报** 模式
4. 选择要分析的 **日期**
5. 点击 **「📊 分析」**（或按回车）
6. 查看多维度的分析图表和表格

### 提示

- ✅ 本地数据有效时自动跳过 API 请求
- ⚠️ zKillboard API 最多支持查询 **7 天以内** 的数据
- 📜 点击 **最近查询** 按钮可快速切换历史实体

---

## 📁 项目结构

```
EVE-killboard-analysis/
├── README.md
├── requirements.txt
├── build_exe.bat / build_exe.py       # PyInstaller 打包脚本
├── data/                              # 运行时数据 + 种子文件
│   ├── killboard.db                   # SQLite 数据库（自动生成，gitignored）
│   ├── type_translations_seed.json    # 中英文翻译种子文件（50287 条）
│   ├── query_history.json             # （gitignored）
│   └── *.bak                          # 旧 JSON 缓存备份
├── images/                            # 截图
├── scripts/
│   ├── fetch_translations.py          # 从 SDE 导入类型翻译
│   └── fetch_region_translations.py   # 从 ESI 导入星域翻译
└── src/
    ├── __init__.py
    ├── app.py                         # Streamlit 主入口 + UI
    ├── config.py                      # 全局配置常量
    ├── analysis/
    │   ├── __init__.py
    │   └── corp_analysis.py           # 分析引擎 (CorpDailyAnalysis)
    ├── collector/
    │   ├── __init__.py
    │   └── zkillboard.py              # zKillboard + ESI API 客户端
    └── storage/
        ├── __init__.py
        ├── database.py                # SQLite 连接管理 & 建表（读写分离）
        └── repository.py              # CRUD + 分析查询
```

---

## 🔄 数据流

```
用户输入名称/ID
    │
    ▼
zKillboard API (自动补全 /autocomplete/)
    │
    ▼
用户选择实体
    │
    ▼
zKillboard API (击杀拉取，自动翻页，最多回溯 7 天)
    │
    ▼
ESI API (ID→名称解析 + 星系→星座→星域)
    │
    ▼
SQLite 数据库 (killboard.db)
  ├── killmails / attackers / items    ← 原始英文数据
  ├── system_region_cache             ← 星系→星域映射
  ├── id_name_cache                   ← ID→名称缓存
  └── type_translations               ← 中英文翻译（种子文件初始化 + ESI 增量补充）
    │
    ▼
CorpDailyAnalysis (SQL 分析查询)
    │
    ▼
展示层查 type_translations  →  中文显示 + 双语 tooltip
    │
    ▼
Plotly 图表 + Streamlit 指标/表格 (UI 展示)
```

---

## ⚙️ 配置

所有配置在 `src/config.py` 中集中管理：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ZKILLBOARD_BASE_URL` | `https://zkillboard.com/api` | zKillboard API 端点 |
| `REQUEST_TIMEOUT` | 30 秒 | HTTP 请求超时 |
| `USER_AGENT` | `EVE-Killboard-Analysis/1.0` | 自定义 UA |
| `DB_PATH` | `data/killboard.db` | SQLite 数据库路径 |

---

## 🗄️ 数据库

| 表 | 内容 |
|----|------|
| `killmails` | 击杀邮件（原始数据） |
| `attackers` | 攻击者明细（原始数据） |
| `items` | 掉落物品（原始数据） |
| `fetch_log` | API 拉取记录（含缓存有效期） |
| `id_name_cache` | ID→名称英文缓存 |
| `system_region_cache` | 星系→星域映射 |
| `type_translations` | **中英文翻译**（舰船/物品/星域等，50173 条） |

> SQLite 使用 WAL 模式 + 读写分离（`get_db_read` / `get_db_write`），支持并发读写。
> `type_translations` 由种子文件 `data/type_translations_seed.json` 初始化，首次启动自动加载。

---

## 📦 依赖

| 包 | 最低版本 | 用途 |
|----|---------|------|
| `streamlit` | ≥ 1.28.0 | Web UI 框架 |
| `requests` | ≥ 2.31.0 | HTTP 客户端 |
| `pandas` | ≥ 2.0.0 | 数据分析 |
| `plotly` | ≥ 5.18.0 | 交互式图表 |

---

## 📜 许可证

MIT
