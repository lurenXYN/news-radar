# 新闻雷达（news-radar）

抓取近期财经新闻 → 关键词映射到 **A 股优先** 板块 → 热度排序 → 可选 **Server酱** 微信推送。

> 全球新闻可接入，但打分与推送优先映射大 A 板块/ETF。仅供学习观察，不构成投资建议。

## 功能

| 模块 | 说明 |
|------|------|
| 采集 | 东财多栏目 + 财联社 + 新浪；个股实体映射；去洗稿 |
| 映射 | 词典 → 板块 + ETF + 东财 BK；隔夜/全球 → A 股传导 |
| 热度 | 相对上一窗口；利空降权；盘面确认 |
| 推送 | 仅 **09:00 / 13:00 / 21:00** 三档总报（交易日）：概览 + Top5 详情（关键词/盘面/3 条新闻）+ 其余留意 + 较上一档进出 |
| 自检 | 页面「推送自检」：下次窗口、最近推送、共振次日回测 |
| 导出 | `GET /api/export/sectors` 供牛来软接入 |
| LLM | 预留，默认关闭 |

## 快速开始

```bat
cd D:\Source\Repos\news-radar
start.bat
```

或本仓开发路径：

```bat
cd D:\Source\Repos\mydemo\go-learning\apps\news-radar
start.bat
```

浏览器：http://127.0.0.1:8770/

### Server酱

1. 打开页面「Server酱 / 参数」
2. 填入 SendKey（`SCT...`），勾选启用，保存
3. 点「测试 Server酱」

也可用环境变量：

```bat
set NEWS_RADAR_SERVERCHAN_SENDKEY=SCTxxxx
```

## 数据

- SQLite：`data/radar.db`
- 设置存库表 `settings`（SendKey 也在库内；勿把库提交到 Git）

## 发布（独立仓）

GitHub：https://github.com/lurenXYN/news-radar

本目录可同步到独立 Git 仓再推 GitHub（**不要**从 go-learning push）：

1. 改 `apps/news-radar/`
2. 同步到 `D:\Source\Repos\news-radar`（排除 `.venv` / `data` / `__pycache__`）
3. 在独立仓 `git commit` + `git push origin main`

### 自动部署（push → VPS）

与牛来同款：GitHub Actions SSH 更新服务器。  
配置见 [`deploy/GITHUB_ACTIONS_DEPLOY.md`](./deploy/GITHUB_ACTIONS_DEPLOY.md)。

服务器首次：

```bash
git clone https://github.com/lurenXYN/news-radar.git ~/github/news-radar
cd ~/github/news-radar
./deploy/install-systemd.sh
```

## 待办

见 [`TODO.md`](./TODO.md)（A 盘面确认/相对热度/早报；B 接牛来）。

## 技术栈

FastAPI + uvicorn + httpx + SQLite
