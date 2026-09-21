# news-radar backlog

Agents: **read this file before planning or coding** under `apps/news-radar/`.

## Open

- （暂无）后续可增强：LLM 摘要归因开关、个股实体映射、隔夜美股/商品传导、共振次日胜率回测

## Done recently

- [x] **1–8 优化** — 利空降权；去洗稿；BK 映射；源加量（东财多栏目+财联社+新浪）；导出 tone/action_hint；牛来软条可点 / 主线对照 / 盘前清单 / 健康状态 / 参数说明；`news_radar_enabled` 默认关。*(2026-09-21)*
- [x] **A · 盘面确认 + 相对热度 + 早报推送** — 东财板块对照；相对上一窗口热度；默认 08:00–09:25 Server酱 TopN。*(2026-09-21)*
- [x] **B · 接到牛来作战台** — `/api/export/sectors`；牛来早报 bullets + 作战页软条；`news_radar_enabled` / `news_radar_url`。*(2026-09-21)*
- [x] MVP：采集 + 词典映射 + SQLite + Server酱 + GitHub Actions 部署骨架

## Won’t do (for now)

- 新闻直接改作战台买卖结论
- 一上来全量 LLM 归因（仅作后续可选）
