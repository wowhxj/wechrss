# WeRSS 技术核心、代码结构与扩展指南

适用版本：**v4.1.0**

本文面向准备阅读、修改或二次开发项目的开发者。重点不是“怎么点击 Web 页面”，而是解释：

- 公众号身份如何解析；
- 微信读书会话如何建立；
- RefreshToken 如何续期；
- 公众号文章如何获取；
- 原文 URL 如何恢复；
- 为什么默认流程只保存文章元数据；
- SQLite 如何组织；
- Web 与调度器如何组合；
- 修改协议时应该改哪里；
- 如何增加新功能而不破坏安全边界。

> 本项目依赖非公开、可能变化的移动端接口。文档描述的是**当前代码实现**，不是平台公开 API 契约。任何协议升级都应先做最小请求验证，再修改代码，不应通过高频重试、验证码自动化、代理轮换等方式规避平台控制。

---

## 1. 总体架构

项目可以分为 5 层：

```text
+--------------------------------------------------+
| Web / CLI                                       |
| web_app.py / wechat_mp_fetcher.py CLI           |
+--------------------------+-----------------------+
                           |
+--------------------------v-----------------------+
| Application Service                              |
| service.py                                       |
| Source CRUD / SyncService / Scheduler / RSS      |
+-------------+---------------------+--------------+
              |                     |
+-------------v----------+  +-------v--------------+
| WeRead Protocol        |  | Article Identity     |
| weread_auth.py         |  | article_identity.py  |
| wechat_mp_fetcher.py   |  | URL/HTML/Playwright  |
+-------------+----------+  +----------------------+
              |
+-------------v------------------------------------+
| Persistence / External Content                  |
| SQLite + mp.weixin.qq.com public article HTML   |
+--------------------------------------------------+
```

核心原则是：

1. **账号生命周期**和**文章读取协议**分开；
2. Web 不直接操作 HTTP 协议，统一经 `SyncService`；
3. SQLite 是唯一持久化业务数据源；
4. 风控和人工验证是终止条件，不是自动绕过目标；
5. 只有明确的认证失效才触发一次 RefreshToken 续期。

---

## 2. 代码目录

```text
web_app.py
```

负责 WSGI Web 层：

- URL 路由；
- Jinja2 模板；
- Basic Auth；
- CSRF；
- Dashboard；
- 设置页面；
- 扫码状态 API；
- 手工同步；
- RSS HTTP 输出。

```text
service.py
```

应用服务层：

- `CredentialStore`；
- `AppDB`；
- `SyncService`；
- `Scheduler`；
- 公众号 CRUD；
- 同步记录；
- URL 回填；
- Feed 生成协调。

```text
wechat_mp_fetcher.py
```

文章协议与数据模型：

- `Article`；
- `WeReadMobileClient`；
- `/mp/chapters`；
- `/review/single`；
- 当前和 legacy 响应解析；
- 旧版正文解析兼容函数（产品入口不调用）；
- `articles` SQLite schema；
- RSS renderer；
- CLI。

```text
weread_auth.py
```

微信读书账号生命周期：

- QR ticket；
- 微信 QR 登录；
- 长轮询；
- `/login` 会话交换；
- RefreshToken 续期；
- `/feature` 初始化；
- `LoginManager` Web 状态机。

```text
article_identity.py
```

把一篇微信文章 URL 解析为：

```text
biz
BID
MP_WXS_<BID>
公众号名称
文章标题
```

支持 URL query、HTML 静态解析和 Playwright browser fallback。

```text
templates/
```

Web 页面模板。

```text
static/app.css
```

Web 样式。

```text
tests/
```

离线单元/集成测试。协议变更必须先补测试再改实现。

---

## 3. 核心数据模型

### 3.1 `Article`

定义在 `wechat_mp_fetcher.py`。

主要字段：

```text
review_id
book_id
title
summary
cover_url
url
publish_at
original_id
read_num
like_num
content_html
author
raw
```

关键主键是：

```text
review_id
```

而不是 URL。

原因是 URL 可能缺失、变化或需要后续补全，但微信读书 `reviewId` 更适合作为文章记录的内部稳定 ID。

### 3.2 `Source`

定义在 `service.py`。

代表一个订阅的公众号：

```text
id
book_id
name
article_url
enabled
fetch_content（兼容字段，固定为 0）
sync_interval_minutes
rss_limit
last_sync_at
next_sync_at
last_status
last_error
```

其中真正用于微信读书查询的是：

```text
book_id = MP_WXS_<BID>
```

`article_url` 只是添加订阅时使用的来源文章 URL，不是后续同步依赖。

### 3.3 `WeReadCredentials`

定义在 `weread_auth.py`。

```text
vid
accessToken
refreshToken
deviceId
deviceName
profile
skey
wxAccessToken
guestToken
syncKey
name
updatedAt
```

最基本的读取请求至少需要：

```text
vid + accessToken
```

自动续期还需要：

```text
refreshToken + deviceId + 匹配的 profile
```

---

## 4. 公众号身份解析

入口：

```python
resolve_article_identity(...)
```

文件：

```text
article_identity.py
```

### 4.1 为什么不能只从 URL 找 `__biz`

旧文章可能是：

```text
https://mp.weixin.qq.com/s?__biz=Mz...&mid=...
```

但新文章大量使用：

```text
https://mp.weixin.qq.com/s/<token>
```

短 token 不是可直接 Base64 解码得到 BID 的字段，因此代码实现三级解析。

### 4.2 第一级：URL query

函数：

```python
biz_from_url(url)
```

如果有：

```text
__biz
biz
```

则完全不发网络请求。

### 4.3 第二级：普通 HTTP HTML

`resolve_article_identity()` 使用 `requests.Session` 打开页面。

`extract_identity_from_html()` 会从 HTML/脚本中寻找可恢复的身份字段，例如：

```text
window.biz
var biz
msg_link
canonical URL
页面中的完整微信文章 URL
```

同时尝试获取公众号名称、文章标题等元数据。

### 4.4 第三级：Playwright

普通 HTTP 解析不到时调用：

```python
_resolve_with_browser(...)
```

用 Chromium 真正加载页面，再从页面环境读取身份信息。

该步骤只用于**添加公众号时识别一次**，后续周期同步不依赖浏览器。

### 4.5 `biz -> BID -> MP_WXS`

代码对 `biz` 做 Base64 解码：

```text
biz
  -> base64 decode
  -> 十进制 BID
  -> "MP_WXS_" + BID
```

最终得到：

```text
MP_WXS_3911685025
```

---

## 5. 微信扫码登录实现

文件：

```text
weread_auth.py
```

核心类：

```python
WeReadAuthClient
LoginManager
```

### 5.1 登录链路

当前流程：

```text
1. GET 微信读书 wxticket
2. GET open.weixin.qq.com/connect/sdk/qrconnect
3. 生成 confirm URL 和二维码 PNG Data URI
4. 轮询 long.open.weixin.qq.com/connect/l/qrconnect
5. 扫码确认后获得 wx_code
6. POST i.weread.qq.com/login
7. 保存 VID / AccessToken / RefreshToken / DeviceId
8. best-effort GET /feature
```

Web 二维码不会写到磁盘，`LoginManager` 只在内存保存二维码和当前状态。

### 5.2 QR 状态机

`LoginManager.ACTIVE`：

```text
requesting
waiting
scanned
exchanging
initializing
```

终态包括：

```text
success
expired
cancelled
error
```

Web 通过：

```text
GET /api/login/status
```

轮询状态。

该 API 不返回 Token。

### 5.3 设备画像

当前 `weread_auth.py` 使用固定 e-ink profile：

```text
PROFILE_NAME = eink-2.1.2
DEVICE_NAME  = BOOX
DEVICE_TYPE  = 3
```

版本头由：

```python
VERSION_HEADERS
```

统一定义。

**如果未来登录协议变化，应优先修改这里，不要在多个模块重复硬编码 Header。**

---

## 6. RefreshToken 续期

入口：

```python
WeReadAuthClient.refresh(...)
```

应用层包装：

```python
SyncService.refresh_credentials(...)
```

### 6.1 触发条件

正常文章读取抛出：

```python
AuthExpiredError
```

应用层才执行 Refresh。

典型来源：

```text
HTTP 401 / 403
业务码 -2012
```

### 6.2 不触发续期的错误

```text
-2041
-2010
HTTP 429
```

这些被映射成：

```python
RiskControlError
```

系统不会用 RefreshToken 循环撞接口。

### 6.3 Single retry

读取型请求最多：

```text
原请求
 -> AuthExpiredError
 -> refresh 一次
 -> 重放原请求一次
```

没有无限 retry loop。

这种设计对非公开接口非常重要，否则认证异常可能被错误地放大成大量请求。

---

## 7. 微信读书文章列表协议

实现类：

```python
WeReadMobileClient
```

文件：

```text
wechat_mp_fetcher.py
```

### 7.1 当前 endpoint

```text
GET https://i.weread.qq.com/mp/chapters
```

### 7.2 首请求参数

```text
bookId=MP_WXS_<BID>
count=20
synckey=0
```

代码：

```python
client.get_articles(book_id, count=20, synckey=0)
```

首请求**不应该**同时携带 `offset=0`。

### 7.3 翻页参数

翻页时使用：

```text
bookId
count
offset
```

而不再发送 `synckey`。

当前 Web 同步只读取最近一页；如果未来增加历史翻页功能，应保持这两种 request shape 互斥。

### 7.4 认证 Header

`WeReadMobileClient` 初始化时至少注入：

```text
accessToken
vid
User-Agent
Accept
Accept-Language
```

扫码创建的 e-ink 会话还会带 `VERSION_HEADERS`。

---

## 8. 响应解析

入口：

```python
parse_articles_payload(payload, book_id)
```

### 8.1 当前格式

当前 `/mp/chapters`：

```json
{
  "data": [
    {
      "reviewId": "...",
      "title": "...",
      "createTime": 0,
      "mpInfo": {}
    }
  ]
}
```

### 8.2 Legacy 格式

为了兼容历史逆向结果，仍支持：

```text
reviews[].subReviews[].review
```

对应旧 `/book/articles`。

旧 endpoint 保留在：

```python
get_articles_legacy(...)
```

Web 调度器不会调用它。

### 8.3 单条转换

```python
_article_from_entry(...)
```

负责把上游 JSON 转换为 `Article`。

URL 优先通过：

```python
article_url_from_mpinfo(...)
```

从 `mpInfo.doc_url` 等字段恢复。

---

## 9. 原文 URL 补全

### 9.1 为什么 URL 会为空

`/mp/chapters` 并不保证每一条都包含：

```text
mpInfo.doc_url
```

所以文章可以已经同步成功，但 `articles.url` 为空。

### 9.2 回填协议

`WeReadMobileClient.resolve_article_url(review_id)`：

```text
reviewId
  -> GET /review/single
  -> review.mpInfo.doc_url
```

### 9.3 Service 层

单篇：

```python
SyncService.resolve_article_url(review_id)
```

批量最多 5 篇：

```python
SyncService.backfill_source_urls(source_id, limit=5)
```

### 9.4 Web 路由

单篇：

```text
POST /articles/<reviewId>/resolve-url
```

批量：

```text
POST /sources/<sourceId>/resolve-urls
```

v3.3.1 补齐了前一个 POST 路由。

---

## 10. 文章正文策略

从 v4.1.0 起，Web、后台调度器和 CLI 同步只保存文章元数据：

```text
标题 / 作者 / 发布时间 / 摘要 / 封面 / reviewId / 微信原文 URL
```

这样可以减少额外访问微信公开文章页面，降低同步失败和页面验证对 RSS 链路的影响。

数据库继续保留 `fetch_content` 与 `content_html` 字段，以兼容旧版本数据；`AppDB` 初始化时会把所有来源的 `fetch_content` 统一设为 `0`。历史上已保存的 `content_html` 不会被删除，但新同步不会再写入正文。

底层 `fetch_public_article()` 目前只作为兼容代码保留，不由产品入口调用。新增功能不应重新暴露正文抓取开关。

---

## 11. 风控和错误模型

### 11.1 异常类

定义在 `wechat_mp_fetcher.py`：

```python
FetcherError
AuthExpiredError
RiskControlError
ContentBlockedError
```

### 11.2 业务码

`check_weread_error()` 当前映射：

```text
-2012 -> AuthExpiredError
-2041 -> RiskControlError
-2010 -> RiskControlError
其他非零 -> FetcherError
```

HTTP：

```text
401/403 -> AuthExpiredError
429     -> RiskControlError
```

### 11.3 为什么不自动处理 `-2041`

账号或会话要求人工验证时，继续自动请求并不能可靠解决问题，反而可能增加风险。

因此安全边界是：

```text
检测 -> 记录 -> 停止
```

而不是：

```text
检测 -> 换代理/换号/验证码自动化 -> 重试
```

如果未来增加“风控状态机”，可以增加**退避和暂停调度**，但不应增加绕过逻辑。

---

## 12. SQLite 设计

数据库默认：

```text
data/wechat_mp.db
```

连接设置：

```text
PRAGMA journal_mode=WAL
PRAGMA foreign_keys=ON
```

### 12.1 `articles`

在 `wechat_mp_fetcher.py` 中创建：

```sql
review_id      TEXT PRIMARY KEY
book_id        TEXT NOT NULL
title          TEXT NOT NULL
summary        TEXT
cover_url      TEXT
url            TEXT
publish_at     INTEGER
original_id    TEXT
read_num       INTEGER
like_num       INTEGER
author         TEXT
content_html   TEXT
raw_json       TEXT
fetched_at     INTEGER
```

索引：

```text
(book_id, publish_at DESC)
```

`save_article()` 使用 UPSERT：

```text
ON CONFLICT(review_id) DO UPDATE
```

旧版本已保存的 `content_html` 会保留，不会在升级时删除。

### 12.2 `sources`

订阅公众号配置。

### 12.3 `sync_runs`

每次同步记录：

```text
status
received
new_count
content_blocked（兼容字段，新任务固定为 0）
message
started_at
finished_at
```

### 12.4 `app_settings`

简单 key/value 设置，目前用于持久化调度器开关等状态。

---

## 13. 同步服务

核心：

```python
SyncService.sync_source(source_id)
```

大致逻辑：

```text
获取 source
 -> 全局同步锁
 -> 写 sync_runs running
 -> 读取凭证
 -> 构造 WeReadMobileClient
 -> 获取最近文章
 -> 认证失效则 refresh + retry once
 -> UPSERT articles
 -> 写 sync_runs finish
 -> 更新 source.next_sync_at
```

### 13.1 为什么有全局锁

`SyncService` 用：

```python
self._lock
```

保证同一个进程中只执行一个公众号同步任务。

这是刻意的保守设计，避免多个公众号同时打微信读书接口。

### 13.2 限速

微信读书请求：

```text
默认 >= 2 秒
```

代码会强制微信读书请求的最小间隔，不能通过环境变量把间隔降到 0。

---

## 14. Scheduler

类：

```python
Scheduler
```

线程名称：

```text
wechat-mp-scheduler
```

执行模型：

```text
循环
 -> 检查 scheduler.enabled
 -> 检查账号是否配置
 -> db.due_sources()
 -> 串行 sync_source()
 -> sleep/poll
```

公众号下次同步时间在：

```text
sources.next_sync_at
```

中持久化。

如果以后想实现“根据历史发布时间预测下一次同步”，建议新增独立调度策略模块，不要直接把统计逻辑塞进 `Scheduler._run()`。

例如：

```text
scheduler_policy.py
    FixedIntervalPolicy
    HistoricalPublishPolicy
```

然后让 `AppDB.mark_sync_finish()` 接收策略计算出的 next time。

---

## 15. Web 层

### 15.1 Server

`web_app.py` 使用：

```text
wsgiref + ThreadingMixIn
```

这是轻量内置服务器，依赖少，适合：

- localhost；
- NAS；
- 内网；
- 反向代理后部署。

不建议裸公网高并发使用。

### 15.2 Auth

如果设置：

```text
ADMIN_PASSWORD
```

则使用 Basic Auth。

用户名固定：

```text
admin
```

密码比较使用 `hmac.compare_digest()`。

### 15.3 CSRF

所有会改变状态的 POST 表单都要求：

```text
csrf
```

Token 默认进程启动时随机生成，也可用：

```text
WECHAT_MP_CSRF_TOKEN
```

固定。

### 15.4 主要路由

```text
GET  /
GET  /sources/new
POST /sources
GET  /sources/<id>
POST /sources/<id>/edit
POST /sources/<id>/sync
POST /sources/<id>/resolve-urls
POST /sources/<id>/toggle
POST /sources/<id>/delete
GET  /articles/<reviewId>
POST /articles/<reviewId>/resolve-url
GET  /feeds/<id>.xml
GET  /settings
POST /settings/login/start
POST /settings/login/cancel
POST /settings/session/refresh
POST /settings/credentials
POST /settings/credentials/clear
POST /settings/scheduler
GET  /api/health
GET  /api/sources
GET  /api/login/status
```

---

## 16. RSS 生成

函数：

```python
render_rss(...)
```

RSS 2.0 + `content:encoded`。

映射：

```text
Article.title        -> item/title
Article.url          -> item/link
Article.review_id    -> guid
Article.publish_at   -> pubDate
Article.summary      -> description
Article.content_html -> content:encoded
```

如果准备扩展 Atom/JSON Feed，建议新增单独 renderer：

```text
feeds.py
    render_rss()
    render_atom()
    render_json_feed()
```

而不是让 `web_app.py` 自己拼 XML/JSON。

---

## 17. 如何修改一个上游 endpoint

假设未来 `/mp/chapters` 变化。

推荐顺序：

### 第一步：确认变化位置

不要先改模板或 DB。

先确认：

```text
URL
method
query/body
required headers
HTTP status
business errcode
response JSON shape
```

### 第二步：修改 `WeReadMobileClient`

例如 endpoint 改名，只改：

```python
WeReadMobileClient.get_articles()
```

### 第三步：修改 parser

如果响应 JSON 变化，改：

```python
parse_articles_payload()
_article_from_entry()
```

### 第四步：增加 fixture/test

在 `tests/test_core.py` 增加一份新的 payload fixture。

要求至少验证：

```text
reviewId
title
publish_at
url
book_id
```

### 第五步：最后再检查 Service/Web

正常情况下 Service 和 Web 不需要知道 endpoint 变化。

这就是协议层隔离的价值。

---

## 18. 如何新增一个 Web API

例如新增：

```text
GET /api/sources/<id>/articles
```

推荐：

1. 在 `AppDB` 增加查询方法；
2. `WebApp.__call__()` 中增加 GET route；
3. 返回必要字段，不返回凭证；
4. 增加 `tests/test_web.py`；
5. 启用 `ADMIN_PASSWORD` 时沿用现有全局 Basic Auth。

不要让新 API 直接读取：

```text
credentials.json
```

也不要返回：

```text
accessToken
refreshToken
deviceId 全值
wx_code
```

---

## 19. 如何增加多账号

当前架构是：

```text
一个全局 CredentialStore
```

如果要真正支持多账号，应做数据模型升级，而不是在风控时自动“切号”。

推荐 schema：

```text
accounts
    id
    name
    vid
    encrypted_credentials / credential_ref
    profile
    status

sources
    ...
    account_id
```

架构改造：

```text
CredentialStore
 -> AccountStore

SyncService.sync_source()
 -> source.account_id
 -> load selected account
```

安全原则：

- 明确由用户指定公众号使用哪个账号；
- 不在 `-2041/429` 后自动轮换账号规避限制；
- 每个账号有独立的调度状态和风险状态。

---

## 20. 如何增加风控退避状态机

当前：

```text
RiskControlError -> 本次 sync_run = risk_control
```

如果需要更稳健，可以新增：

```text
account_state
risk_until
risk_level
last_risk_code
```

推荐行为：

```text
-2041
 -> 标记账号待人工验证
 -> 暂停该账号所有自动同步
 -> Web 显示状态
 -> 用户人工完成验证
 -> 手工“重新检测”
```

对于真正的短期限频，可以用保守指数退避。

不建议：

```text
代理轮换
自动 CAPTCHA
自动账号轮换
快速重复请求
```

---

## 21. 如何扩展全文处理

目前 `content_html` 直接存清理后的 HTML。

可以新增：

```text
markdown
plain_text
summary_ai
embedding_status
```

推荐拆成异步/离线内容处理层：

```text
文章同步
 -> SQLite metadata/content_html
 -> content_processor worker
 -> Markdown/摘要/索引
```

不要让 AI 处理阻塞微信读书同步线程，否则单篇文章分析超时会拖慢整个公众号同步。

---

## 22. 如何更换 Web 框架

当前没有 Flask/FastAPI 依赖。

如果项目规模扩大，可把：

```text
WebApp
```

迁移为 FastAPI/Starlette，但建议保留：

```text
AppDB
SyncService
WeReadMobileClient
WeReadAuthClient
Article Identity Resolver
```

作为纯业务层。

迁移原则：

```text
HTTP framework 只负责 request/response
业务逻辑不进 route handler
```

这样 CLI、测试和后台任务仍可复用同一核心。

---

## 23. 测试策略

### 23.1 默认测试不打真实微信接口

运行：

```bash
pytest -q
```

使用 mock payload/session 验证：

- biz 解析；
- `/s/<token>` HTML 解析；
- QR 状态；
- Token refresh；
- `/mp/chapters` request shape；
- 当前/legacy parser；
- URL 补全；
- SQLite；
- RSS；
- Web route；
- Token 不通过 API 泄露。

### 23.2 新协议必须写回归测试

不要只手工测试真实接口。

至少保存一份**去除敏感信息后的响应结构 fixture**，用来防止下次改动把 parser 搞坏。

### 23.3 真实接口测试原则

如果必须做 live test：

- 使用自己的测试账号；
- 单请求；
- 不循环重试；
- 日志不打印 Token；
- 遇到 `-2041/429` 立即停止。

---

## 24. 调试方法

### 查看容器日志

```bash
docker compose logs -f --tail=200 wechat-mp-fetcher
```

### 查看健康状态

```bash
curl http://127.0.0.1:8080/api/health
```

### 检查数据库文章 URL

```bash
docker compose exec wechat-mp-fetcher python - <<'PY'
import sqlite3

db = sqlite3.connect('/app/data/wechat_mp.db')
for row in db.execute('''
    SELECT title, review_id, url
    FROM articles
    ORDER BY publish_at DESC
    LIMIT 20
'''):
    print(row)
PY
```

### 测试身份解析器

```bash
docker compose exec wechat-mp-fetcher \
  python wechat_mp_fetcher.py resolve \
  --url 'https://mp.weixin.qq.com/s/xxxxxxxx'
```

### 查看当前版本

```bash
cat VERSION
```

容器内：

```bash
docker compose exec wechat-mp-fetcher cat /app/VERSION
```

---

## 25. 版本升级规范建议

如果后续继续维护，建议：

```text
PATCH  文档、Bug、兼容修复
MINOR  新功能但保持数据库/主要 API 兼容
MAJOR  大规模数据模型/API 破坏性调整
```

每次发包至少做：

```text
1. 更新 VERSION
2. 更新 README
3. 更新技术文档中的 endpoint/route
4. py_compile
5. pytest
6. Web smoke test
7. 打 ZIP
8. 计算 SHA-256
```

---

## 26. 当前安全边界

项目允许：

- 自己账号扫码登录；
- 正常 RefreshToken 生命周期；
- 正常读取自己的微信读书移动会话可访问内容；
- 解析公开微信文章；
- RSS 和本地归档。

项目明确不实现：

- CAPTCHA 自动识别/提交；
- 人工验证绕过；
- IP/代理轮换规避限制；
- 多账号自动切换规避风控；
- 高频重试；
- 未授权付费内容绕过。

扩展功能时应继续维持这条边界。

---

## 27. 推荐的下一步重构方向

如果继续把项目做成长期运行服务，优先级建议是：

```text
1. Account 状态表 + 风控暂停/退避
2. Feed read-token 与管理后台权限分离
3. 数据库 schema migration 机制
4. 结构化日志
5. JSON Feed / Atom
6. 历史翻页与增量 synckey
7. 调度策略模块化
8. content processor worker
9. 更完整的导入/导出
10. FastAPI + production WSGI/ASGI 部署（规模扩大后）
```

不要首先做“更多账号/更快请求”，稳定性和可观察性比吞吐量重要。
