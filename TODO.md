# news-radar backlog

Agents: **read this file before planning or coding** under `apps/news-radar/`.

## Open

- [ ] **A · 盘面确认 + 相对热度 + 早报推送** — 热度需对照板块涨跌；用较昨/较上小时的相对热度；每天盘前 Server酱 推 Top3（非全天刷屏）。
- [ ] **B · 接到牛来作战台** — 导出 `/api/export/sectors`；牛来早报/作战页软提示接入（不改 ready/闸门）；可选 `news_radar_url` 配置。

## Done recently

- [x] MVP：采集 + 词典映射 + SQLite + Server酱 + 独立仓 GitHub Actions 部署骨架

## Won’t do (for now)

- 新闻直接改作战台买卖结论
- 一上来全量 LLM 归因（仅作后续可选）
