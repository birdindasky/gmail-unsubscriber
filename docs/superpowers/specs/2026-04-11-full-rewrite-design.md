# Gmail 智能退订器 — 全面重构设计文档

**日期：** 2026-04-11
**状态：** 已批准，待实施

---

## 背景与目标

现有程序存在以下核心问题：

1. **功能残缺**：mailto 退订只打印信息，并不真正发送；退订成功后从不记录，下次扫描同一发件人还会重复出现
2. **性能低下**：扫描 500 封邮件需要 501 次 API 请求，慢且容易触发频率限制
3. **误判率高**：关键词过于宽泛（如 `"info"`, `"hello"`, `"hi"`），正经邮件容易被标记为广告
4. **权限浪费**：已申请 `gmail.modify` 权限用于打标签，但从未实际使用
5. **无历史记录**：用户无法查看退订过哪些发件人，也无法统计工具效果

目标：全面重构，打造一个准确、可靠、有记忆的 Gmail 退订工具。

---

## 整体架构

### 模块清单

| 模块 | 状态 | 职责 |
|------|------|------|
| `auth.py` | 保持不变 | OAuth 2.0 认证，返回 Gmail 服务对象 |
| `scanner.py` | 升级 | 用批量 API 拉取邮件；优先扫 CATEGORY_PROMOTIONS；过滤已退订发件人 |
| `classifier.py` | 升级 | 关键词判断 + 可选 Claude AI 二次确认；精简关键词 |
| `unsubscriber.py` | 升级 | 修复 mailto（真正发送）；退订后打 Gmail 标签；可选归档旧邮件 |
| `config.py` | 升级 | 新增 AI 开关、Anthropic API Key、SQLite 路径配置 |
| `database.py` | 新增 | SQLite 封装：退订历史 + 扫描记录 + 用户白名单 |
| `ai_classifier.py` | 新增 | Claude AI 分类模块，处理关键词模糊地带 |
| `main.py` | 升级 | 新增 `history` 命令；新增 `--archive` / `--no-ai` 参数 |

### 数据流

```
Gmail API（批量拉取，优先 CATEGORY_PROMOTIONS）
    ↓
scanner.py
    └─ 过滤：跳过数据库中已退订的发件人
    ↓
classifier.py
    ├─ 白名单检查 → 命中则跳过
    ├─ 敏感词检查 → 命中则跳过
    ├─ 关键词判断：
    │   ├─ 命中 2+ 条件 → 标记退订
    │   ├─ 命中 1 条件  → 交给 ai_classifier.py 判断（可关闭）
    │   └─ 命中 0 条件  → 跳过
    ↓
unsubscriber.py
    ├─ 方式1：List-Unsubscribe POST（RFC 8058 一键退订）
    ├─ 方式2：List-Unsubscribe mailto（Gmail API 发送退订邮件）
    └─ 方式3：正文退订链接（GET 请求）
    ↓
退订成功后：
    ├─ database.py → 记录退订历史
    ├─ Gmail API   → 给该发件人所有邮件打「已退订」标签
    └─ Gmail API   → （可选 --archive）移除 INBOX 标签，归档旧邮件
```

---

## 各模块详细设计

### 1. scanner.py — 批量 API + 智能过滤

**批量请求：**
- 用 `googleapiclient.http.BatchHttpRequest` 替代逐封请求
- 每批最多 100 封，500 封邮件只需 5 次 HTTP 请求（原来 500 次）
- 速度提升约 10 倍，API 配额消耗减少约 90%

**优先扫描促销标签：**
- 查询条件加入 `label:CATEGORY_PROMOTIONS`，优先处理 Gmail 已分类的促销邮件
- 也支持扫描全部邮件（`--all` 参数）

**已退订过滤：**
- 扫描前从 `database.py` 读取已退订发件人列表
- 扫描结果中自动排除这些发件人，不重复展示

---

### 2. classifier.py — 关键词 + AI 双引擎

**关键词精简：**
从 `SUSPICIOUS_SENDER_KEYWORDS` 中移除以下过宽泛的词：
- 移除：`"info"`, `"hello"`, `"hi"`, `"contact"`, `"team"`, `"notification"`, `"alert"`, `"updates"`
- 保留：`"noreply"`, `"newsletter"`, `"promo"`, `"promotion"`, `"marketing"`, `"offers"`, `"deals"`, `"sales"`, `"shop"`, `"store"`

**AI 介入时机：**
- 命中 2+ 条件 → 直接判定为广告（不调用 AI，节省费用）
- 命中 1 条件 → 调用 `ai_classifier.py` 获取第二意见
- 命中 0 条件 → 直接跳过（不调用 AI）

---

### 3. ai_classifier.py — Claude AI 分类模块（新增）

**发给 AI 的信息：**
- 发件人名称 + 邮箱
- 邮件主题
- 邮件摘要（前 200 字）
- 不发送正文全文（保护隐私 + 控制 token 费用）

**AI 返回格式：**
```json
{"is_ad": true, "reason": "促销邮件，含限时折扣信息"}
```

**配置：**
```python
# config.py 新增
USE_AI_CLASSIFIER = True          # False 则完全关闭 AI
ANTHROPIC_API_KEY = ""            # 或从环境变量 ANTHROPIC_API_KEY 读取
AI_MODEL = "claude-haiku-4-5-20251001"   # 快且便宜
AI_MAX_TOKENS = 100               # 只需简短回答
```

**命令行开关：**
```bash
python main.py scan --no-ai       # 本次不使用 AI
python main.py unsubscribe --confirm --no-ai
```

---

### 4. database.py — SQLite 状态管理（新增）

**数据库文件：** `gmail-unsubscriber.db`（项目根目录，加入 .gitignore）

**表一：`unsubscribed_senders`（退订历史）**
```sql
CREATE TABLE unsubscribed_senders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_email    TEXT NOT NULL UNIQUE,
    sender_name     TEXT,
    unsubscribed_at TEXT NOT NULL,   -- ISO 8601 格式
    method          TEXT,            -- one_click / mailto / link / failed
    success         INTEGER          -- 1=成功, 0=失败
);
```

**表二：`scan_history`（扫描记录）**
```sql
CREATE TABLE scan_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at      TEXT NOT NULL,
    days            INTEGER,
    total_emails    INTEGER,
    candidates      INTEGER,         -- 建议退订的发件人数
    unsubscribed    INTEGER          -- 本次实际退订数
);
```

**表三：`user_whitelist`（用户白名单，从 JSON 迁移）**
```sql
CREATE TABLE user_whitelist (
    domain          TEXT PRIMARY KEY,
    added_at        TEXT NOT NULL
);
```

---

### 5. unsubscriber.py — 修复 mailto + 标签 + 归档

**修复 mailto 退订：**
- 不再打印"请手动发送"
- 用 Gmail API `users.messages.send` 实际发出退订邮件
- 邮件内容：收件人为退订地址，主题为 List-Unsubscribe 指定的 subject

**退订成功后打标签：**
- 自动在 Gmail 创建「已退订」标签（如已存在则复用）
- 对该发件人的所有邮件（在扫描范围内）调用 `messages.modify` 打上标签
- 用户在 Gmail 网页版可以直接看到哪些发件人已退订

**可选归档（`--archive` 参数）：**
- 退订成功后，对该发件人的邮件移除 `INBOX` 标签（即归档）
- 邮件不删除，仍可在「所有邮件」中找到
- 只归档扫描范围内的邮件（不影响更早的邮件）

---

### 6. main.py — 新增命令与参数

**新增命令：`history`**
```bash
python main.py history            # 查看退订历史
python main.py history --limit 20 # 只看最近 20 条
```

输出示例：
```
📋 退订历史记录（共 15 个发件人）
─────────────────────────────────────────
  [1] newsletter@shop.example.com
      退订时间：2026-04-11 09:30
      退订方式：一键退订（POST）✅

  [2] promo@ads.example.com
      退订时间：2026-04-11 09:31
      退订方式：mailto 退订邮件 ✅
...
```

**新增参数：**

| 参数 | 作用 |
|------|------|
| `--no-ai` | 本次运行不调用 Claude AI |
| `--archive` | 退订成功后归档该发件人的旧邮件 |
| `--all` | 扫描所有邮件，不仅限于促销标签 |

---

## 不在本次范围内

- 邮件删除功能（破坏性操作，保持不做）
- Web UI 界面（命令行即可）
- 多账号支持
- 定时自动运行

---

## 依赖变更

新增依赖：
```
anthropic          # Claude AI SDK
```

其余依赖不变（`google-auth`, `google-api-python-client`, `requests`, `beautifulsoup4`, `lxml`）。

SQLite 是 Python 标准库内置，无需额外安装。
