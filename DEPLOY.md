# 旅行共享 · 一键部署到 Render（7×24 公共网页）

> 不用信用卡，5 分钟上线，拿到一个永久的 `https://trip-share-xxx.onrender.com`。
> 你和你朋友以后打开浏览器直接访问，不用依赖你电脑在线。

---

## 上线流程（4 步）

### 第 1 步：注册 GitHub 账号（如果你没有）

去 https://github.com 注册一个免费账号。注册完会自动建一个空的仓库列表（你之后要新建一个）。

### 第 2 步：把代码推到 GitHub

打开 PowerShell 或 cmd，运行：

```bat
cd "C:\Users\Administrator\WorkBuddy AI\2026-08-19-13-48-28\trip-share"

REM 1. 初始化 git
git init
git add .
git commit -m "init trip-share"

REM 2. 去 GitHub 网站，点右上角 "+" → New repository
REM    - Repository name: trip-share
REM    - Public / Private 任选
REM    - 不要勾选 "Add README" / "Add .gitignore" / "Choose a license"
REM    - 点 Create repository

REM 3. 把仓库替换成你的（替换 USERNAME）
git remote add origin https://github.com/USERNAME/trip-share.git
git branch -M main
git push -u origin main
```

> **如果推送时要求登录**：用 GitHub 网页登录后，**Settings → Developer settings → Personal access tokens → Generate new token (classic)**，勾 `repo`，拿到一串字符串，复制粘贴当密码用。

### 第 3 步：在 Render 部署

1. 打开 https://render.com
2. 点 **Sign in with GitHub**（用你刚注册的 GitHub 账号）
3. 第一次登录会问授权，确认
4. Dashboard → 点 **New +** → 选 **Blueprint**
5. 选 **Public GitHub repositories** → 找到 `trip-share` → 点 **Connect**
6. Render 自动识别 `render.yaml`，列出两个资源：
   - `trip-share-db` （Postgres 数据库）
   - `trip-share` （Web 服务）
7. 点 **Apply** → 等 3-5 分钟

### 第 4 步：拿到 URL

部署完成后，Dashboard 上 `trip-share` 这一行会显示：
```
https://trip-share-XXXX.onrender.com
```
把链接发给你朋友就行了。

⚠️ **第一次打开可能等 30 秒**（免费层冷启动）。以后 15 分钟没人访问会休眠，再激活又要 30 秒。

---

## 数据持久吗？数据会不会丢？

✅ **不会丢**。Render 免费层 Postgres 提供 1GB 持久存储（不是临时磁盘），
重启 server 不会动数据库。但要小心：**如果 Postgres 连续 90 天无活动，
Render 会发邮件提醒续期，你要点邮件里的链接确认一下**。

---

## 你以后改了代码，怎么更新？

如果你改了 `server.py` / `static/index.html` / `db.py`：

```bat
cd "C:\Users\Administrator\WorkBuddy AI\2026-08-19-13-48-28\trip-share"
git add .
git commit -m "改了哪里"
git push
```

Render 会**自动检测 push**，重新拉代码、重新部署。你和朋友那边的链接不变。

---

## 数据怎么备份？

Render Dashboard → 你的 `trip-share-db` 服务 → 右边菜单 **Connect** →
会显示一个 `psql` 命令行，照着贴在本地 cmd 里就能导出/导入。

或者每晚自动备份：
- Dashboard → `trip-share-db` → **Backups** → Create backup schedule

---

## 想完全删本地的代码？

可以。删除 `C:\Users\Administrator\WorkBuddy AI\2026-08-19-13-48-28\trip-share` 整个文件夹也没关系——
**代码已经在 GitHub 上**，随时可以重新拉下来继续开发：

```bat
git clone https://github.com/USERNAME/trip-share.git
```

---

## 你的朋友怎么加入维护？

让朋友登录 GitHub，**到你的仓库页面** → 点 **Fork** → 改完后发 **Pull Request**。
你审阅后合并进主分支，Render 自动部署。

---

## 常见问题

| 问题 | 答 |
|------|-----|
| 第一次打开页面要等 30 秒 | 免费层冷启动，正常 |
| 注册时报 "用户名已存在" | Postgres 不为空，第一次部署确认数据存在 |
| 部署完打开看到 "Internal Server Error" | 看 Render Dashboard → Logs，里面有 Python 堆栈 |
| 想换数据库（比如换 Neon） | 改 render.yaml 的 `fromService` 指向新数据库即可 |

---

## 费用

- Render 免费层：永久免费（带 1 个 web service + 1 个 Postgres）
- 升级到 $7/月：可挂持久磁盘 + 不用冷启动（仅 web；PG 是另一回事）
- 你目前的需求，免费层完全够用

---

## 想要不一样的部署？

- **HuggingFace Spaces**：完全免永久，但免费 Space 没有持久磁盘，server 重启数据会丢
- **Fly.io 免费层**：比 Render 灵活但要绑信用卡
- **本地常开 + Cloudflare Tunnel**：你电脑不能关机，否则朋友访问不了（违反你的初衷）
