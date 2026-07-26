# 🚀 EVE 军团击杀日报

EVE Online 军团击杀记录查询与分析工具。

## 功能

- 📊 **军团击杀日报**：分析指定军团前一天的击杀/损失数据
- 🚢 **舰船分布**：击杀用舰船与被击毁舰船排行
- 🏆 **击杀排行**：军团成员击杀榜
- 📈 **时间分布**：24 小时击杀热力图
- 🗺️ **星系热区**：击杀发生最多的星系

## 技术栈

- **前端**: Streamlit
- **数据库**: SQLite
- **数据源**: zKillboard API
- **图表**: Plotly

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动应用
streamlit run src/app.py
```

## 使用方法

1. 启动后访问 `http://localhost:8501`
2. 在左侧输入军团 ID
3. 点击「分析昨日击杀」
4. 首次使用会自动从 zKillboard 拉取数据

> 军团 ID 可在 zKillboard 网站搜索军团后在 URL 中找到。
