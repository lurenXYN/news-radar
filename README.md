# 新闻雷达（news-radar）

抓取近期财经新闻 → 关键词映射到 **A 股优先** 板块 → 热度排序 → 可选 **Server酱** 微信推送。

> 全球新闻可接入，但打分与推送优先映射大 A 板块/ETF。仅供学习观察，不构成投资建议。

## 功能

| 模块 | 说明 |
|------|------|
| 采集 | 东财多栏目 + 财联社电报（签名接口，题材/个股标签参与映射，A/B 级加权）+ 新浪；时间统一规整；东财按文章代码去重、跨轮次标题去重（近 24h）、超保留期旧文不入库；某源连续 3 轮无数据在页头提示（悬停看各源条数） |
| 映射 | 词典 → 板块 + ETF + 东财 BK；标题/财联社标签命中算满分，只在摘要命中 ×0.5，泛词再 ×0.5；歧义词排除语境（航空≠航班、银行≠高盛/外资行、黄金周≠黄金…）；大盘/宏观、美股映射为背景桶，不进 Top / 导出，总报单列「宏观与外盘」；隔夜/全球 → A 股传导 |
| 热度 | 相对上一窗口；利空降权；盘面确认；`DIGEST_DEMOTE_NEWS_ONLY`：仅新闻不占 Top；排序共振>盘面已动>背离>仅新闻 |
| 情绪 | 反转短语优先 + 否定处理 + 摘要/泛词降权，净分门槛离中性 |
| 推送 | 09/13/21 三档；默认 `DIGEST_REQUIRE_BOARD_CONFIRM`：Top 无共振/盘面已动则整档不发。Server酱与作战台收盘页共用额度 |
| 自检 | 推送自检 + 共振次日（含相对全板块中位数的超额） |
| 效果 | 「效果观察」手标 + 超额；作战台影子对比有/无共振亮灯卡（不改闸） |
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

## 测试

```bat
python -m pytest -q tests
```
