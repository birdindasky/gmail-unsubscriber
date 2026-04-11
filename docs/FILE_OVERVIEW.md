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

**职责：** 负责与 Gmail API「对话」，批量拉取邮件并解析成结构化数据。就像一个图书馆助理，把书架上的书一本一本取出来，翻开封面（解析 headers）、读取内容，整理成规范的档案交给后续模块处理。

**关键函数：**

| 函数名 | 说明 |
|--------|------|
| `scan_emails(service, days=30)` | 主函数：扫描最近 N 天邮件，返回邮件详情列表 |
| `get_email_detail(service, msg_id)` | 获取单封邮件的完整详情 |
| `_list_all_messages(service, query)` | 分页获取邮件 ID 列表（内部函数） |
| `_parse_message(msg)` | 将 API 原始对象解析为结构化字典（内部函数） |
| `_parse_sender(sender_raw)` | 从 "名字 <邮箱>" 格式提取邮箱和域名（内部函数） |
| `_extract_body(payload)` | 递归提取邮件纯文本和 HTML 正文（内部函数） |
| `_decode_base64(data)` | 解码 Gmail 使用的 URL-safe Base64（内部函数） |

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
    "body_text": "纯文本正文",
    "body_html": "<html>...</html>",
    "labels": ["INBOX", "CATEGORY_PROMOTIONS"],
}
```

**被哪些模块调用：**
- `main.py` 中 `cmd_scan()` 和 `cmd_unsubscribe()` 调用 `scan_emails()`

**依赖：**
- `google-api-python-client`：`HttpError`
- 标准库：`base64`、`email`、`logging`、`time`、`datetime`

---

## `classifier.py` — 邮件分类器

**职责：** 拿到 `scanner` 解析好的邮件数据，判断「这封邮件应不应该退订」。相当于一个有丰富经验的邮件审核官，按照一套严格的规则逐条比对，给出有理有据的判定。

**判定流程（优先级从高到低）：**
```
白名单域名？ → 绝对不退订（最高优先级）
     ↓ 否
含敏感词？   → 绝对不退订（保护重要邮件）
     ↓ 否
满足 2+ 广告条件？ → 建议退订
     ↓ 否
默认         → 不退订（保守策略）
```

**关键函数：**

| 函数名 | 签名 | 说明 |
|--------|------|------|
| `is_whitelisted(sender)` | `str → bool` | 检查发件人是否在白名单 |
| `is_sensitive(email_data)` | `dict → bool` | 检查是否含敏感词 |
| `is_advertisement(email_data)` | `dict → (bool, list[str])` | 广告判定，返回结果和命中条件列表 |
| `should_unsubscribe(email_data)` | `dict → (bool, str)` | 最终决策，返回是否退订和原因 |
| `classify_emails(emails)` | `list[dict] → dict` | 批量分类，按发件人归组 |

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
- `main.py` 中 `cmd_scan()` 和 `cmd_unsubscribe()` 调用 `classify_emails()`

**依赖：**
- 本地模块：`config`（读取白名单和关键词）
- 标准库：`logging`、`re`

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

## `main.py` — 主入口 & CLI

**职责：** 程序的总指挥。解析用户在命令行输入的指令，调度各个模块完成任务，并把结果以友好的方式展示给用户。

**命令列表：**

| 命令 | 函数 | 说明 |
|------|------|------|
| `scan [--days N]` | `cmd_scan()` | 扫描邮件并展示分析报告 |
| `unsubscribe --dry-run` | `cmd_unsubscribe()` | 试运行：预览退订内容，不实际执行 |
| `unsubscribe --confirm` | `cmd_unsubscribe()` | 逐个确认后执行退订 |
| `unsubscribe --confirm --auto` | `cmd_unsubscribe()` | 自动确认全部退订 |
| `whitelist add <domain>` | `cmd_whitelist()` | 将域名加入用户白名单 |
| `whitelist list` | `cmd_whitelist()` | 查看当前白名单 |
| `logs` | `cmd_logs()` | 查看运行日志 |

**关键函数：**

| 函数名 | 说明 |
|--------|------|
| `setup_logging(verbose)` | 初始化日志系统（文件 + 控制台双输出） |
| `cmd_scan(args)` | scan 命令的处理函数 |
| `cmd_unsubscribe(args)` | unsubscribe 命令的处理函数 |
| `cmd_whitelist(args)` | whitelist 命令的处理函数 |
| `cmd_logs(args)` | logs 命令的处理函数 |
| `build_parser()` | 构建 argparse 命令行解析器 |
| `main()` | 程序总入口 |

**日志策略：**
- 文件日志（`logs/gmail-unsubscriber-YYYYMMDD.log`）：记录 DEBUG 级别及以上的所有信息
- 控制台日志：仅显示 WARNING 及以上（除非 `--verbose`）
- 这样设计的原因：用户只需看到关键信息，详细调试信息写入文件备查

**依赖：**
- 本地模块：`auth`、`scanner`、`classifier`、`unsubscriber`、`config`（全部）
- 标准库：`argparse`、`logging`、`os`、`sys`、`datetime`
