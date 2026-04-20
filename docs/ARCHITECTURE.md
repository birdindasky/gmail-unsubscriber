# 系统架构文档

## 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                     用户 (命令行 / 交互菜单)                      │
│    python main.py  ·  scan / unsubscribe / whitelist / history   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│    CLI 解析 · 交互菜单 · 日志初始化 · 扫描结果缓存 · 流程调度     │
└──┬────────┬──────────┬──────────────────┬──────────────┬────────┘
   │        │          │                  │              │
   ▼        ▼          ▼                  ▼              ▼
┌─────┐ ┌────────┐ ┌───────────┐   ┌──────────────┐ ┌──────────┐
│auth │ │scanner │ │ classifier│   │ unsubscriber │ │ database │
│ .py │ │ .py    │ │  .py      │   │  .py         │ │  .py     │
│OAuth│ │3 线程并│ │白名单/广告│   │三种退订方式  │ │SQLite 持 │
│认证 │ │发 + 重试│ │敏感词判断│   │HTTP/mailto/  │ │久化：已退│
│     │ │Gmail API│ │+ AI 辅助 │   │  正文链接    │ │订 + 历史 │
└──┬──┘ └───┬────┘ └─────┬─────┘   └──────┬───────┘ └────┬─────┘
   │        │            │                │              │
   │        │            ▼                │              │
   │        │   ┌─────────────────┐       │              │
   │        │   │ ai_classifier.py│       │              │
   │        │   │ 9 提供商注册表  │       │              │
   │        │   │ 2 层缓存防重复  │       │              │
   │        │   └────────┬────────┘       │              │
   │        │            │                │              │
   │        ▼            ▼                ▼              │
   │     ┌─────────────────────────────────────┐         │
   └────▶│           config.py                 │◀────────┘
         │ 白名单/关键词/域名分类/USE_AI_CLASSIFIER │
         └─────────────────────────────────────┘
```

## 数据流向

```
Gmail 服务器
    │
    │ Gmail API (OAuth 2.0 认证)
    ▼
scanner.scan_emails()
    │ 3 线程并发拉取 metadata，遇 429/SSL 自动重试
    │ database.is_already_unsubscribed() 过滤已退订发件人
    │ 返回邮件列表（主题/发件人/头部/Gmail 标签）
    ▼
classifier.classify_emails()
    │
    ├─ is_whitelisted()         → 白名单域名      → 跳过
    ├─ is_sensitive()           → 敏感关键词      → 跳过
    ├─ is_advertisement()       → ≥ 2 条件命中    → 标记退订
    └─ 恰好 1 条件命中 → ai_classifier.classify_with_ai()
                         （同发件人只调一次，缓存在 _ai_cache）
    │
    │ 返回按发件人归组的待退订列表
    ▼
classifier.categorize_groups()
    │ 按域名归类（电商/新闻/社交…）
    │ 未知域名 → ai_classifier.categorize_with_ai()
    │         （同域名只调一次，缓存在 domain_cat_cache）
    ▼
main._last_scan 缓存结果（交互菜单复用）
    ▼
unsubscriber.execute_unsubscribe()
    │
    ├─ 方式1: List-Unsubscribe POST (RFC 8058 一键退订)
    ├─ 方式2: List-Unsubscribe mailto (发送退订邮件)
    └─ 方式3: 解析 HTML 正文，提取退订链接，发 GET 请求
    │
    ▼
database 写入历史 · 打印结果 · 写入日志文件
```

---

## 架构决策说明

### 为什么使用 Gmail API，而不是直接读取邮件文件？

直接处理 `.eml` 文件或通过 IMAP 读取邮件，需要存储账号密码，存在安全隐患。Gmail API 使用 OAuth 2.0 协议——就像让快递员进门取件，你给他一把只能开指定房间的钥匙（令牌），而不是把家门钥匙给他。令牌有过期时间，即使泄露危害也有限，而且随时可以在 Google 账号设置中吊销。

### 为什么采用「白名单优先」策略？

银行验证码、医院就诊提醒、政府通知……这些邮件千万不能误退订。白名单相当于一道「免检通道」：哪怕邮件长得再像广告，只要发件人在白名单里，一律放行。错退订一次重要邮件，后果可能很严重（错过还款通知、丢失验证码）；多收几封广告邮件，只是稍微烦人而已。宁可漏掉广告，绝不误伤重要邮件。

### 为什么判定广告需要满足「2 个或以上」条件？

单一条件太容易误判：
- 仅凭「含有"优惠"二字」→ 银行也会发"优惠利率"通知
- 仅凭「发件人是 noreply」→ GitHub 通知也是 noreply
- 仅凭「有 List-Unsubscribe」→ 这是一个正当的邮件头部

需要多个特征同时出现，才能确信这封邮件是广告。就像判断一个人是不是骗子，一个可疑点不够，需要几个特征叠加才能下结论。

### 为什么按发件人分组处理，而不是逐封处理？

同一个广告发件人可能给你发了 100 封邮件。退订一次就能解决全部问题，没必要对同一个发件人发 100 次退订请求（那反而可能触发对方的反爬机制）。按发件人分组后，只需退订一次，且用户界面也更清晰——「退订这个发件人」比「退订这 100 封邮件」更符合用户的心智模型。

### 为什么优先使用 List-Unsubscribe，而不是直接点击邮件中的链接？

`List-Unsubscribe` 是 RFC 2369 和 RFC 8058 定义的标准邮件头部，是发件人「官方公告」的退订方式。正规邮件服务商（Mailchimp、SendGrid 等）都支持它，且通常是幂等的（多次请求结果相同）。相比之下，邮件正文中的退订链接：
1. 可能只是收集「真实用户」的追踪链接
2. 可能跳转到需要填写验证码的页面
3. 可能链接失效

所以优先级：RFC 8058 POST → List-Unsubscribe HTTP → List-Unsubscribe mailto → 正文链接。

### 为什么支持 9 个 AI 提供商？

不同用户有不同需求：国内用户希望低延迟低费用（MiniMax、DeepSeek、通义千问、智谱、Moonshot），有海外网络的用户可以选 OpenAI 或 Anthropic Claude，本地部署用户可以用 Ollama，还有自定义入口兜底任何 OpenAI 兼容服务。`ai_classifier.py` 里维护一个 `PROVIDERS` 注册表（9 条目），每条记录协议类型（`openai` 或 `anthropic`）、默认模型、base_url 等；`_call_ai()` 按协议分发到对应 SDK，接入新提供商只需在注册表加一行。

AI 提供商选择和 API Key 不再放 `config.py` / 环境变量，改为存入 `user_config.json`（由 `user_config.py` 管理，已加入 `.gitignore`），通过交互菜单配置，首次启动会自动从旧环境变量迁移。

MiniMax 的 M 系列是推理模型，响应可能只返回 `ThinkingBlock` 而没有独立的 `TextBlock`，因此 `_extract_text_from_response()` 做了 fallback：先找 `text`，找不到再从 `thinking` 里用正则抠 JSON。

### 为什么 AI 判定要按「发件人 + 域名」双层缓存？

同一个广告发件人可能有上百封邮件，每封都问一次 AI 既慢又费钱。第一层 `_ai_cache` 按 `sender_email` 缓存"这个发件人是不是广告"；第二层 `domain_cat_cache` 按 `sender_domain` 缓存"这个域名属于什么类别"。实测 1 万封邮件通常只触发几十到几百次 AI 调用，绝大多数走缓存。缓存只在进程内存里（一次运行有效），下次运行重新算，避免误判被永久固化。

### 为什么扫描用 3 线程并发、而不是更多？

Gmail API 单用户并发有隐性上限，超过会触发 429 限流。3 线程配合每请求 0.15 秒间隔，约 20 req/s，是实测"又快又稳"的平衡点。每个线程维护自己的 `Gmail service` 对象（`thread_local`），避免线程间共享带来的 SSL/连接池问题。拉取 metadata 失败会自动重试（429、500、503、SSL、网络错误），在代理不稳的环境下也能跑完大规模扫描。

### 为什么扫描结果要缓存到 `_last_scan`？

交互菜单场景下，用户常常是"先扫一眼 → 决定退订"两步操作。如果每步都重新扫描（尤其是 14000+ 封历史邮件），体验会崩溃。`main._last_scan` 在一次运行里保留上次扫描的分类结果，退订时默认复用，用户也可以主动重扫。命令行模式（`scan` / `unsubscribe` 各自独立）仍保持原来的行为，互不干扰。

### 为什么设计试运行（dry-run）模式？

防止手误。就像在真正删除数据库之前先运行 `SELECT` 查一查，试运行让用户先看到「如果执行，会发生什么」，确认没问题再真正动手。对于不熟悉技术的用户尤其重要——先用 `--dry-run` 看看结果，觉得合理了再用 `--confirm` 执行。

### 为什么不直接删除邮件？

退订只是「告诉对方不要再发」，不是「清理已有邮件」。删除邮件是破坏性操作，无法撤销。万一程序判断失误，删除了重要邮件，用户可能损失重要信息。退订操作只会影响「未来」，不影响「过去」——这是最保守、最安全的策略。用户如果想清理已有广告邮件，可以在 Gmail 界面手动操作。

---

## 模块依赖关系

```
main.py
 ├── auth.py            (get_gmail_service)
 ├── scanner.py         (scan_emails)
 │    ├── auth.py       (每线程获取独立 service)
 │    └── database.py   (过滤已退订发件人)
 ├── classifier.py      (classify_emails, categorize_groups)
 │    ├── config.py     (白名单/关键词/域名分类表)
 │    └── ai_classifier.py (classify_with_ai, categorize_with_ai; PROVIDERS 注册表)
 │                      ├── config.py     (USE_AI_CLASSIFIER / AI_MAX_TOKENS)
 │                      └── user_config.py (活跃提供商 & API Key)
 ├── unsubscriber.py    (execute_unsubscribe)
 │    └── (requests, beautifulsoup4 - 第三方库)
 ├── database.py        (SQLite: 已退订 + 历史记录)
 ├── config.py          (whitelist 命令直接操作)
 └── user_config.py     (启动时 migrate_from_env；_interactive_settings 写入配置)
```

所有模块均无循环依赖。`config.py` 和 `user_config.py` 是最底层（不依赖其他本地模块），`ai_classifier.py` 和 `database.py` 都只依赖它们，可独立测试。

---

## 安全考量

| 风险 | 缓解措施 |
|------|---------|
| OAuth 令牌泄露 | `token.json` 在 `.gitignore` 中；落盘即 `chmod 0o600`，仅当前用户可读写 |
| 误退订重要邮件 | 白名单 + 敏感词双重保护 + 2 条件门槛 |
| 广告链接追踪 | 使用 List-Unsubscribe 头部而非正文链接（优先） |
| 恶意退订链接（scheme 滥用） | `unsubscriber._is_safe_http_url()` 仅放行 `http://` / `https://`，拒绝 `javascript:` / `file:` / `data:` / `mailto:` 等 |
| 账号凭据泄露 | `credentials.json` 在 `.gitignore` 中；首次加载时自动 `chmod 0o600` |
| 本地数据库 PII 外泄 | `gmail-unsubscriber.db`（含扫描过的发件人邮箱）在 `init_db()` 后 `chmod 0o600` |
| 误操作 | `--dry-run` 模式 + `--confirm` 逐个确认模式 |
| 速率限制 | scanner 和 unsubscriber 均有请求间隔和重试机制（429/500/503/SSL/网络错误指数退避）；单封邮件重试 3 次仍失败时写 WARNING 日志而非静默跳过 |
| AI API Key 泄露 | 存入 `user_config.json`（已加入 `.gitignore`），不写入代码；展示时脱敏（前 6 位 + 后 6 位）；异常日志里的 `sk-...` / `pk-...` / `Bearer ...` 等会被 `_mask_secrets()` 遮蔽为 `[REDACTED]` |
| AI 接口泄露邮件内容 | 只发送发件人、主题、摘要片段，不发送邮件正文 |
