# 旅行共享 · Trip Share

> 一个多人旅行协作的小工具（行程、想去的地方、酒店、集合点、费用分摊）。

---

## 给使用者

直接打开链接（如 `https://trip-share-xxxx.onrender.com`），注册账号，
创建/加入旅行，发邀请码给朋友一起协作。

### 核心功能
- **想去**：收藏景点/餐厅/路线，附链接和图片
- **行程**：按天排每天的安排
- **酒店**：共享酒店信息、入住时间、房号、预订链接
- **集合点**：约时间和地点，避免走散
- **费用分摊**：建群组，每笔费用自动按群组人数平摊，实时算每人余额

---

## 给维护者

### 本地启动（Windows）

```bat
start.bat
```

默认端口 8000。如果 8000 被占用，脚本会自动找下一个空端口（最长找 10 个）。

### 本地启动（带公网链接）

需要先装 `cloudflared`（下载 https://github.com/cloudflare/cloudflared/releases
，丢到 `C:\Windows\`），然后：

```bat
start_with_tunnel.bat
```

你会拿到一个 `https://xxx.trycloudflare.com` 的临时链接。⚠️ 本地电脑关了就失效。

### 部署到 Render（永久公共链接）

看 `DEPLOY.md`。

简版：
1. 注册 GitHub 账号
2. `deploy_to_render.bat` 一键推到 GitHub
3. Render Dashboard → New Blueprint → 选仓库 → Apply

### 改代码 → 发布

```bat
git add .
git commit -m "什么改动"
git push
```

Render 自动部署，你的链接不变。

### 项目结构

```
trip-share/
├── server.py          # Flask API 路由
├── db.py              # PostgreSQL 数据层
├── wsgi.py            # gunicorn 入口（Render 用）
├── static/
│   └── index.html     # 单文件 SPA（Tailwind CDN）
├── requirements.txt
├── render.yaml        # Render 自动部署配置
├── start.bat          # 本地启动
├── start_with_tunnel.bat  # 本地 + 公网链接
├── deploy_to_render.bat   # 一键推 GitHub
└── DEPLOY.md          # 部署傻瓜式手册
```

### 数据迁移 / 升级

数据库用 **PostgreSQL**（Render 免费层自带 1GB）。改 `db.py` 加字段后，
部署时会自动 `CREATE TABLE IF NOT EXISTS`，但加字段要写手动 migration
（或用 alembic / sql-migrate）。

短期方案：升级时直接 `python -c "import db; db.init_db()"` 重新建表，再手动导数据。

### 主题色

- 主色：indigo
- 强调：emerald
- 字体：PingFang SC / Microsoft YaHei

直接在 `static/index.html` 里改 Tailwind class 即可。

---

## 已知限制

- **免费 Render 冷启动**：15 分钟没人访问后休眠，下次访问要 30 秒等待
- **Render 免费 Postgres**：连续 90 天无活动需邮件点续期
- **CSV / Excel 导出**：暂未实现，需要时跟我说

---

## License

个人项目，自用为主。如果你也想跑，DEPLOY.md 里有完整步骤。
