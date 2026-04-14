# 文件详解

本文档逐一介绍项目中每个 Python 文件的职责、核心函数和依赖关系。

---

## `config.py` — 配置中心

**职责：** 存放所有「写死」的配置数据，以及动态修改用户白名单的工具函数。把配置集中在一个地方，修改时不需要翻遍所有源文件。

**关键数据：**

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `WHITELIST_DOMAINS` | `list[str]` | 内置白名单域名（100+ 个常用机构） |
| `AD_KEYWORDS` | `list[str]` | 广告关键词（中英文各 30+ 个） |
| `SENSITIVE_KEYWORDS` | `list[str]` | 敏感关键词（验证码/订单/账单等） |
| `SUSPICIOUS_SENDER_KEYWORDS` | `list[str]` | 可疑发件人关键词（noreply/newsletter 等） |
| `DOMAIN_TO_CATEGORY` | `dict[str, str]` | 域名到邮件类别的映射表（用于归类展示） |
| `CATEGORY_NAMES` | `list[str]` | 所有可用类别（电商购物/社交/新闻…） |
| `AI_PROVIDER` | `str` | `"minimax"` 或 `"anthropic"`，默认 `"minimax"` |
| `MINIMAX_API_KEY` / `ANTHROPIC_API_KEY` | `str` | 分别对应两种 AI 的 Key（优先从环境变量读取） |
| `MINIMAX_BASE_URL` / `MINIMAX_MODEL` | `str` | MiniMax 的 Anthropic 兼容端点和模型名 |
| `USE_AI_CLASSIFIER` | `bool` | AI 辅助判断总开关 |

**关键函数：**

| 函数名 | 说明 |
|--------|------|
| `get_all_whitelist_domains()` | 返回内置 + 用户自定义白名单的合集 |
| `load_user_whitelist()` | 从 `user_whitelist.json` 加载用户自定义白名单 |
| `save_user_whitelist(domains)` | 将用户白名单保存到 `user_whitelist.json` |
| `add_to_user_whitelist(domain)` | 向用户白名单新增域名，返回是否新增成功 |

**被哪些模块调用：**
- `classifier.py` 调用 `get_all_whitelist_domains()`、`AD_KEYWORDS`、`SENSITIVE_KEYWORDS`、`SUSPICIOUS_SENDER_KEYWORDS`
- `main.py` 调用 `add_to_user_whitelist()`、`load_user_whitelist()` 用于白名单管理命令

**依赖：**
- 标准库：`json`、`os`
- 不依赖任何其他本地模块（最底层）

---

## `auth.py` — 身份认证

**职责：** 处理所有 Google OAuth 2.0 相关事务。就像一个「门卫」，负责向 Google 证明「我是这个账号的合法用户」，拿到通行证（access token）后再把证件交给其他模块使用。

**关键函数：**

| 函数名 | 说明 |
|--------|------|
| `authenticate()` | 执行 OAuth 认证流程，返回 `Credentials` 对象 |
| `get_gmail_service()` | 调用 `authenticate()`，返回 Gmail API 服务对象 |

**`authenticate()` 内部流程：**
1. 检查 `credentials.json` 是否存在，不存在则提示并退出
2. 检查 `token.json` 是否存在，存在则加载
3. 若令牌有效，直接返回
4. 若令牌过期但有刷新令牌，自动刷新
5. 若无有效令牌，启动浏览器授权（`InstalledAppFlow`）
6. 授权成功后，将新令牌保存到 `token.json`

**被哪些模块调用：**
- `main.py` 在每个需要访问 Gmail 的命令开始时调用 `get_gmail_service()`
- 返回的 `service` 对象被传入 `scanner.scan_emails(service, ...)`

**依赖：**
- `google-auth`：`google.oauth2.credentials.Credentials`、`google.auth.transport.requests.Request`
- `google-auth-oauthlib`：`InstalledAppFlow`
- `google-api-python-client`：`build`

**重要常量：**
```python
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
# modify 权限：可读取、修改标签，但不能永久删除邮件
```

---

## `scanner.py` — 邮件扫描器

**职责：** 负责与 Gmail API「对话」，批量并发拉取邮件元数据并解析成结构化数据。就像一个有 3 个图书馆助理的团队，分头把书架上的书取出来翻开封面（解析 headers），整理成规范的档案交给后续模块处理。遇到网络抖动会自动重试，不会中途翻车。

**关键函数：**

| 函数名 | 说明 |
|--------|------|
| `scan_emails(service, days=30, scan_all=False)` | 主函数：扫描邮件，过滤已退订发件人，返回邮件列表。`days=0` 表示扫全部历史，`scan_all=True` 表示扫全部分类 |
| `_fetch_messages_batch(service, stubs)` | 3 线程并发拉取邮件 metadata，自带重试（内部函数） |
| `_get_thread_service()` | 每个线程维护独立的 Gmail service 对象（thread-local） |
| `_list_all_messages(service, query)` | 分页获取邮件 ID 列表（内部函数） |
| `_parse_message(msg)` | 将 API 原始对象解析为结构化字典（内部函数） |
| `_parse_sender(sender_raw)` | 从 "名字 <邮箱>" 格式提取邮箱和域名（内部函数） |
| `_retry_request(func, ...)` | 通用重试包装器，处理 429/500/503/SSL/网络错误 |

**并发与容错：**
- 并发线程数 `CONCURRENT_WORKERS = 3`，每请求间隔 `REQUEST_SLEEP = 0.15s`，约 20 req/s
- 每 50 封邮件打印一次进度
- 自动退避重试：429（限流）、500 / 503（服务端错误）、`ssl.SSLError` / `ConnectionError` / `OSError`（网络抖动）

**已退订发件人过滤：** 解析完成后调用 `database.is_already_unsubscribed(sender_email)`，命中的直接过滤，避免重复处理。

**返回数据结构（每封邮件）：**
```python
{
    "id": "邮件ID",
    "subject": "主题",
    "sender": "Google <noreply@google.com>",
    "sender_email": "noreply@google.com",
    "sender_domain": "google.com",
    "date": "日期字符串",
    "list_unsubscribe": "<https://...>, <mailto:...>",  # 可能为 None
    "list_unsubscribe_post": "List-Unsubscribe=One-Click",  # 可能为 None
    "snippet": "邮件摘要前200字...",
    "body_text": "",   # metadata 格式不含正文，退订时按需获取
    "body_html": "",   # 见 unsubscriber._fetch_html_body()
    "labels": ["INBOX", "CATEGORY_PROMOTIONS"],
}
```

**被哪些模块调用：**
- `main.py` 中 `cmd_scan()`、`cmd_unsubscribe()` 和交互菜单调用 `scan_emails()`

**依赖：**
- `google-api-python-client`：`HttpError`
- 本地模块：`auth`（获取 service）、`database`（过滤已退订）
- 标准库：`ssl`、`threading`、`concurrent.futures`、`logging`、`time`、`datetime`

---

## `classifier.py` — 邮件分类器

**职责：** 拿到 `scanner` 解析好的邮件数据，判断「这封邮件应不应该退订」。相当于一个有丰富经验的邮件审核官，按照一套严格的规则逐条比对，给出有理有据的判定。

**判定流程（优先级从高到低）：**
```
白名单域名？            → 绝对不退订（最高优先级）
     ↓ 否
含敏感词？              → 绝对不退订（保护重要邮件）
     ↓ 否
满足 2+ 广告条件？      → 建议退订
     ↓ 否
恰好命中 1 个条件？     → 交给 AI 判断（同发件人缓存，只调一次）
     ↓ AI 判定非广告或未启用
默认                    → 不退订（保守策略）
```

**关键函数：**

| 函数名 | 签名 | 说明 |
|--------|------|------|
| `is_whitelisted(sender)` | `str → bool` | 检查发件人是否在白名单 |
| `is_sensitive(email_data)` | `dict → bool` | 检查是否含敏感词 |
| `is_advertisement(email_data)` | `dict → (bool, list[str])` | 广告判定，返回结果和命中条件列表 |
| `should_unsubscribe(email_data, use_ai=True)` | `dict → (bool, str)` | 最终决策，1 条件命中时调 AI 辅助 |
| `classify_emails(emails, use_ai=True)` | `list[dict] → dict` | 批量分类，按发件人归组 |
| `categorize_groups(groups, use_ai=True)` | `list[dict] → dict[str, list[dict]]` | 按邮件类别（电商/新闻/社交…）归组，未知域名调 AI |

**两层 AI 缓存（关键优化）：**
- `_ai_cache: dict[str, tuple[bool, str]]` — 按发件人邮箱缓存"是不是广告"，`should_unsubscribe` 使用
- `domain_cat_cache: dict[str, str]` — 按域名缓存归类结果，`categorize_groups` 内部使用
- 缓存生命周期仅限本次进程运行，避免误判被永久固化

**`is_advertisement()` 的五个条件：**
1. 主题/正文含 `AD_KEYWORDS` 中的关键词
2. 发件人名称或地址含 `SUSPICIOUS_SENDER_KEYWORDS` 关键词
3. 邮件头部有 `List-Unsubscribe`
4. Gmail 自动打了 `CATEGORY_PROMOTIONS` 标签
5. 发件人是 `noreply` / `no-reply` 类型地址

**`classify_emails()` 返回结构：**
```python
{
    "to_unsubscribe": [
        {
            "sender_email": "promo@shop.com",
            "sender": "某购物平台 <promo@shop.com>",
            "count": 15,          # 该发件人邮件数量
            "reasons": ["命中广告特征：含广告关键词；含 List-Unsubscribe 头部"],
            "sample_subjects": ["周年庆大促！", "限时折扣"],
            "list_unsubscribe": "<https://...>",
            "sample_html": "<html>...",  # 用于退订的 HTML 样本
        },
        ...
    ],
    "skipped": 120,  # 被白名单/敏感词保护跳过的邮件数
}
```

**被哪些模块调用：**
- `main.py` 中 `cmd_scan()`、`cmd_unsubscribe()` 和交互菜单调用 `classify_emails()` + `categorize_groups()`

**依赖：**
- 本地模块：`config`（读取白名单和关键词）、`ai_classifier`（AI 辅助判定）
- 标准库：`logging`、`re`

---

## `ai_classifier.py` — AI 辅助判定

**职责：** 封装 AI 调用细节，对外提供「判断是不是广告」和「判断属于什么类别」两个能力。对 `classifier.py` 屏蔽 AI 提供商差异：上层只管问问题，底层自动走 MiniMax 或 Anthropic。就像一个统一的翻译官——不管您雇的是中国翻译还是外国翻译，跟您对话的接口是一样的。

**两种 AI 提供商：**

| 提供商 | 启用方式 | 说明 |
|--------|---------|------|
| MiniMax（默认） | `AI_PROVIDER=minimax` + `MINIMAX_API_KEY` | 国内服务，费用低；走 Anthropic Messages 兼容端点 |
| Anthropic Claude | `AI_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` | 质量高，需海外网络 |

**关键函数：**

| 函数名 | 说明 |
|--------|------|
| `classify_with_ai(sender, subject, snippet)` | 判断邮件是不是广告，返回 `(is_ad, reason)` |
| `categorize_with_ai(sender, subject)` | 判断发件人属于哪个类别，返回类别名 |
| `_call_ai(prompt)` | 按 `AI_PROVIDER` 分发到 MiniMax / Anthropic（内部函数） |
| `_extract_text_from_response(message)` | 从响应中抠文本，兼容推理模型只返回 `ThinkingBlock` 的情况（内部函数） |
| `_parse_json_response(text)` | 容错解析 JSON，支持从思考内容的夹缝中用正则找 JSON（内部函数） |
| `_check_ai_available()` | 检查 AI 是否可用（总开关 + API Key）（内部函数） |

**关键细节：**
- **ThinkingBlock 兼容**：MiniMax M 系列是推理模型，响应可能只有 `ThinkingBlock` 没有 `TextBlock`，`_extract_text_from_response` 会 fallback 到 `thinking` 字段
- **max_tokens**：MiniMax 调用强制至少 1024 token，防止思考内容被截断
- **JSON 解析容错**：先试 `json.loads`，失败后用正则 `\{[^{}]+\}` 在文本里找 JSON

**被哪些模块调用：**
- `classifier.should_unsubscribe()` 在 1 条件命中时调用 `classify_with_ai()`
- `classifier.categorize_groups()` 对未知域名调用 `categorize_with_ai()`

**依赖：**
- `anthropic`（Python SDK，同时兼容 MiniMax 的 Anthropic 端点）
- 本地模块：`config`（读取 AI_PROVIDER 和 API Key）
- 标准库：`json`、`logging`、`os`、`re`

---

## `database.py` — 退订历史与持久化

**职责：** 用 SQLite 本地文件记账——谁退订过了、什么时候退订的、成功还是失败。就像给每次退订动作留个签到记录，下次扫描时自动跳过已处理过的发件人，避免重复打扰对方。

**数据存储：**
- 文件位置：项目根目录下 `unsubscribe_history.db`（SQLite）
- 不上传 git（在 `.gitignore` 中）

**关键函数：**

| 函数名 | 说明 |
|--------|------|
| `init_db()` | 初始化数据库和表结构（首次运行自动创建） |
| `record_unsubscribe(sender_email, sender, method, success, message)` | 记录一次退订操作 |
| `is_already_unsubscribed(sender_email)` | 检查是否已经成功退订过（扫描阶段过滤用） |
| `get_history(limit=50)` | 查询最近的退订历史 |

**被哪些模块调用：**
- `scanner.scan_emails()` 调用 `is_already_unsubscribed()` 过滤邮件列表
- `unsubscriber.execute_unsubscribe()` 成功后调用 `record_unsubscribe()`
- `main.cmd_history()` 和交互菜单调用 `get_history()`

**依赖：**
- 标准库：`sqlite3`、`logging`、`datetime`

---

## `unsubscriber.py` — 退订执行器

**职责：** 真正动手执行退订操作。就像一个代理人，按照你的授权，以不同方式联系各个发件人说「请把我从你的邮件列表中移除」。

**三种退订方式（按优先级）：**

```
方式 1：一键退订（RFC 8058）
         向 List-Unsubscribe 中的 URL 发 POST 请求
         {"List-Unsubscribe": "One-Click"}
         ↓ 失败则尝试
方式 2：HTTP GET
         向 URL 发 GET 请求（模拟浏览器点击）
         ↓ 无 HTTP URL 则尝试 mailto
       ：mailto 退订
         解析 mailto 地址和 subject，提示用户手动发送
         ↓ 无 List-Unsubscribe 则尝试
方式 3：正文链接退订
         从 HTML 中找含退订关键词的 <a> 链接，发 GET 请求
```

**关键函数：**

| 函数名 | 说明 |
|--------|------|
| `get_list_unsubscribe_url(headers_or_value)` | 解析 List-Unsubscribe 头部，提取 HTTP URL 和 mailto |
| `unsubscribe_via_one_click(url)` | 发送 RFC 8058 POST 请求执行一键退订 |
| `unsubscribe_via_mailto(mailto_info)` | 生成 mailto 退订信息（地址和主题） |
| `unsubscribe_via_link(html_body)` | 从 HTML 正文提取退订链接并发 GET 请求 |
| `execute_unsubscribe(sender_group, dry_run)` | 统一入口，按优先级尝试各种退订方式 |
| `_find_unsubscribe_link(html_body)` | 从 HTML 中提取最可能的退订链接（内部函数） |

**`execute_unsubscribe()` 返回结构：**
```python
{
    "sender_email": "promo@shop.com",
    "sender": "某购物平台 <promo@shop.com>",
    "dry_run": False,
    "attempted_method": "one_click_post",  # 实际使用的方式
    "success": True,
    "message": "一键退订请求已发送（HTTP 200）",
    "details": {
        "http": {"success": True, "method": "one_click_post", ...},
    }
}
```

**被哪些模块调用：**
- `main.py` 中 `cmd_unsubscribe()` 调用 `execute_unsubscribe()`

**依赖：**
- `requests`：HTTP 请求
- `beautifulsoup4` + `lxml`：解析 HTML 提取链接
- 标准库：`logging`、`re`、`time`、`urllib.parse`

---

## `main.py` — 主入口 & CLI & 交互菜单

**职责：** 程序的总指挥。两种入口：命令行参数模式（适合高级用户 / 脚本）和交互菜单模式（适合新手）。调度各个模块完成任务，并把结果以友好的方式展示给用户。

**两种使用模式：**

```
不带参数           python3 main.py                 → 进入交互菜单
带参数             python3 main.py scan ...        → 命令行模式
```

**命令行模式命令列表：**

| 命令 | 函数 | 说明 |
|------|------|------|
| `scan [--days N] [--all] [--no-ai]` | `cmd_scan()` | 扫描邮件并展示分类报告 |
| `unsubscribe --dry-run` | `cmd_unsubscribe()` | 试运行：预览退订内容，不实际执行 |
| `unsubscribe --confirm [--auto] [--archive]` | `cmd_unsubscribe()` | 逐个确认 / 自动确认 / 退订后归档 |
| `history [--limit N]` | `cmd_history()` | 查看退订历史 |
| `whitelist add <domain>` / `whitelist list` | `cmd_whitelist()` | 管理用户白名单 |
| `logs` | `cmd_logs()` | 查看运行日志 |

**交互菜单命令（`interactive_menu()`）：**

```
1. 扫描邮件       → _interactive_scan()
2. 执行退订       → _interactive_unsubscribe()（复用上次扫描结果）
3. 查看退订历史   → _interactive_history()
4. 管理白名单     → _interactive_whitelist()
5. 设置           → _interactive_settings()（查看 AI 状态等）
0. 退出
```

**扫描结果缓存：** 模块级变量 `_last_scan = {"categorized": ..., "to_unsub": ..., "total": ..., "days": ...}` 保存上次扫描结果。菜单里「扫描邮件」后会显示 ✅ 表示有缓存，选 2 退订时默认复用，也可选择重扫。

**关键函数：**

| 函数名 | 说明 |
|--------|------|
| `setup_logging(verbose)` | 初始化日志系统（文件 + 控制台双输出） |
| `interactive_menu()` | 交互菜单主循环 |
| `_do_scan_and_classify(days, scan_all, use_ai)` | 复用的扫描 + 分类 + 归类流程 |
| `cmd_scan(args)` / `cmd_unsubscribe(args)` / `cmd_whitelist(args)` / `cmd_history(args)` / `cmd_logs(args)` | 各 CLI 命令处理函数 |
| `parse_selection(user_input, total)` | 解析用户输入（支持 `1,3,5-8` 形式） |
| `format_category_summary(categorized)` | 格式化类别展示 |
| `build_parser()` | 构建 argparse 命令行解析器 |
| `main()` | 程序总入口 |

**日志策略：**
- 文件日志（`logs/gmail-unsubscriber-YYYYMMDD.log`）：记录 DEBUG 级别及以上的所有信息
- 控制台日志：仅显示 WARNING 及以上（除非 `--verbose`）
- 这样设计的原因：用户只需看到关键信息，详细调试信息写入文件备查

**依赖：**
- 本地模块：`auth`、`scanner`、`classifier`、`unsubscriber`、`config`、`database`（全部）
- 标准库：`argparse`、`logging`、`os`、`sys`、`datetime`
