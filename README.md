# WeRSS

把微信公众号文章整理成属于自己的 RSS 订阅。

WeRSS 是一个可自托管的微信公众号文章收集工具。它通过你自己的微信读书会话获取公众号文章元数据，并为每个公众号生成独立 RSS Feed。项目提供简洁的 Web 管理界面、扫码登录、自动续期、定时同步和 SQLite 持久化。

> [!IMPORTANT]
> 本项目依赖非公开且可能变化的微信读书移动端接口。请仅访问你有权访问的内容，并遵守相关平台条款。WeRSS 不处理验证码、不绕过人工验证，也不会通过代理轮换或高频重试规避风控。

## 主要能力

- 粘贴任意公众号文章链接，自动识别公众号；
- 支持常见短链接及 `MP_WXS_*` / 数字 BID；
- 微信扫码登录，RefreshToken 可用时自动续期；
- 获取文章标题、时间、封面、摘要和原文地址；
- 原文地址缺失时按需补全；
- 每个公众号独立配置同步频率和 RSS 条数；
- SQLite 本地持久化与后台定时同步；
- Basic Auth、CSRF 与基础安全响应头；
- Windows、macOS、Linux 一键安装启动；
- Docker Compose 部署。

## 快速开始

### 一键启动（小白推荐）

需要先安装 Python 3.10 或更高版本。Windows 安装 Python 时请勾选 **Add Python to PATH**。

Windows 用户直接双击：

```text
start.bat
```

macOS / Linux 用户在项目目录运行：

```bash
bash start.sh
```

脚本会自动创建独立虚拟环境、安装依赖和 Chromium，并在服务就绪后打开浏览器。第一次运行需要下载依赖，后续启动会直接复用。

停止服务时关闭启动窗口，或按 `Ctrl+C`。

### Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

打开 <http://127.0.0.1:8080>，然后：

1. 进入“设置”，使用微信扫码登录；
2. 点击“添加”，粘贴任意公众号文章链接；
3. 完成首次同步；
4. 复制 Feed 地址并加入 RSS 阅读器。

检查服务状态：

```bash
curl http://127.0.0.1:8080/api/health
```

查看日志：

```bash
docker compose logs -f --tail=200 wechat-mp-fetcher
```

### 手工启动（开发者）

需要 Python 3.10 或更高版本：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python web_app.py
```

Windows PowerShell 激活虚拟环境：

```powershell
.venv\Scripts\Activate.ps1
```

默认仅监听 `127.0.0.1:8080`。

## 部署与安全

默认 Compose 端口绑定为：

```text
127.0.0.1:8080:8080
```

如需从其他设备访问，优先使用 SSH 隧道：

```bash
ssh -L 8080:127.0.0.1:8080 user@server
```

如果确实需要监听局域网地址，在 `.env` 中设置：

```env
BIND_ADDRESS=0.0.0.0
ADMIN_PASSWORD=换成足够强的密码
```

管理用户名固定为 `admin`。对公网开放时还应使用带 HTTPS 的反向代理。

敏感凭证默认保存在 `data/credentials.json`。该文件已被 Git 忽略，但仍应限制文件访问权限并随数据目录一起安全备份。

## 配置

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `ADMIN_PASSWORD` | 空 | Web Basic Auth 密码；远程访问时必须设置 |
| `BIND_ADDRESS` | `127.0.0.1` | Compose 暴露地址 |
| `PORT` | `8080` | 宿主机端口 |
| `WEREAD_MIN_INTERVAL` | `2` | 微信读书请求最小间隔（秒） |
| `HTTP_TIMEOUT` | `20` | HTTP 请求超时（秒） |
| `WEREAD_QR_DEADLINE_SECONDS` | `300` | 扫码登录有效时间（秒） |
| `SCHEDULER_POLL_SECONDS` | `30` | 调度器检查周期（秒） |
| `WECHAT_MP_DATA` | `./data` | 数据目录 |
| `WECHAT_MP_DB` | 数据目录内 | SQLite 文件位置 |
| `WECHAT_MP_CREDENTIALS` | 数据目录内 | 凭证文件位置 |

`WEREAD_ACCESS_TOKEN`、`WEREAD_VID` 等旧版变量仅用于兼容迁移。正常使用请在 Web 中扫码登录。

## 数据与备份

主要持久化文件：

```text
data/
├── wechat_mp.db
└── credentials.json
```

备份前建议暂停服务：

```bash
docker compose stop
cp -a data data.backup
docker compose start
```

恢复时使用同一版本或先阅读 [CHANGELOG.md](CHANGELOG.md) 的升级说明。

## 常见问题

### 出现 `-2041`、HTTP 429 或要求验证

停止重复请求，打开官方微信读书或微信完成平台要求的人工操作，等待一段时间后再手动尝试一次。WeRSS 不会自动重试这些状态。

### 登录已过期

如果扫码登录保存了 RefreshToken 和 Device ID，服务会自动续期一次。续期仍失败时，请在“设置”中重新扫码。

### 公众号短链接无法识别

链接解析依次尝试 URL 参数、公开页面 HTML 和 Playwright 浏览器回退。页面要求人工验证时会直接停止。可用 CLI 查看更具体的错误：

```bash
python wechat_mp_fetcher.py resolve --url "https://mp.weixin.qq.com/s/..."
```

### RSS 会包含什么

Feed 包含标题、发布时间、摘要和微信原文链接。为保持同步稳定并减少对微信公开页面的额外访问，Web 与 CLI 默认流程不抓取文章正文。

## API

项目提供三个轻量只读接口：

```text
GET /api/health
GET /api/sources
GET /api/login/status
```

启用 `ADMIN_PASSWORD` 后，API 同样需要 Basic Auth。登录状态接口不会返回 AccessToken、RefreshToken 或扫码交换 code。

## 开发

安装开发依赖并运行测试：

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

测试使用模拟响应，不需要真实微信账号，也不会主动请求微信服务。

项目结构：

```text
.
├── web_app.py                 # WSGI 路由与页面
├── service.py                 # 数据库、同步服务与调度器
├── wechat_mp_fetcher.py       # 文章协议、元数据与 RSS
├── weread_auth.py             # 扫码登录与会话续期
├── article_identity.py        # 公众号链接识别
├── templates/                 # Jinja 页面
├── static/                    # 样式与轻量交互
├── scripts/bootstrap.py       # 一键安装启动逻辑
├── start.bat / start.sh       # Windows 与 Unix 启动入口
├── tests/                     # 自动化测试
└── docs/TECHNICAL_GUIDE.md    # 技术实现与扩展指南
```

更深入的实现说明见 [技术指南](docs/TECHNICAL_GUIDE.md)。提交改动前请阅读 [贡献指南](CONTRIBUTING.md)；安全问题请按 [安全策略](SECURITY.md) 私下报告。

## 贡献

Bug 报告、文档改进和功能提交都欢迎。请尽量让每个 PR 保持单一目的，并附上测试或清晰的验证步骤。涉及微信读书协议的改动不得加入验证码自动化、代理轮换、高频重试或其他规避平台控制的逻辑。

## 许可证

[MIT](LICENSE) © WeRSS contributors
