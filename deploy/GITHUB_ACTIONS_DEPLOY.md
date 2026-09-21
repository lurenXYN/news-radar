# GitHub Actions 自动部署 news-radar（SSH → VPS）

push `main`（或手动 Run workflow）后：

1. `git fetch` + `reset --hard origin/main`
2. `rsync` 到 `/opt/news-radar`（保留 `.venv` 与 `data/`）
3. `pip install` + `systemctl restart news-radar`
4. 探活 `http://127.0.0.1:8770/api/health`

可与「牛来」共用同一组 SSH Secrets（同一台 VPS 时）。

## 服务器一次性准备

```bash
apt install -y git rsync curl python3-venv

git clone https://github.com/lurenXYN/news-radar.git ~/github/news-radar
cd ~/github/news-radar
chmod +x deploy/install-systemd.sh deploy/remote-update.sh
./deploy/install-systemd.sh
# 默认: /opt/news-radar · 0.0.0.0:8770
```

确认：

```bash
systemctl status news-radar
curl -sS http://127.0.0.1:8770/api/health
```

## GitHub Secrets

打开：https://github.com/lurenXYN/news-radar/settings/secrets/actions

| Name | 必填 | 说明 |
|------|------|------|
| `DEPLOY_HOST` | 是 | VPS IP |
| `DEPLOY_USER` | 是 | 如 `root` |
| `DEPLOY_SSH_KEY` | 是 | 部署私钥全文 |
| `DEPLOY_PORT` | 否 | 默认 22 |

可选 Variables：

| Name | 默认 |
|------|------|
| `DEPLOY_REPO_DIR` | `$HOME/github/news-radar` |
| `DEPLOY_INSTALL_DIR` | `/opt/news-radar` |

若与 market-desk **同一台机、同一密钥**，Secrets 内容可相同，但要在 **news-radar 仓库** 里各配一份（Secrets 不跨仓共享）。

## 验证

1. Actions → Deploy → Run workflow  
2. 或 push `main`  
3. https://github.com/lurenXYN/news-radar/actions

```bash
journalctl -u news-radar -n 30 --no-pager
curl -sS http://127.0.0.1:8770/api/health
```
