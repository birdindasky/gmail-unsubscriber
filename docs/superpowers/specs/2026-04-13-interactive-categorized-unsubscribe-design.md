# Gmail 退订工具升级：交互菜单 + 分类退订 + 扫描加速

日期：2026-04-13

## 背景

当前程序扫描速度慢（逐封串行请求），扫描结果以扁平列表展示，且只能通过命令行参数操作，对非技术用户不友好。

## 目标

1. 提供交互式终端菜单，无需记忆命令行参数即可使用
2. 扫描结果按邮件类别分组展示，支持按类别批量退订
3. 将扫描速度提升约 3 倍（3 线程并发）
4. 支持 MiniMax AI 模型（兼容 OpenAI 格式）
5. 同步更新 README.md 和 USAGE.md 使用说明

## 设计

### 1. 交互式主菜单

运行 `python main.py`（不带参数）时进入交互菜单：

```
╔══════════════════════════════════╗
║      Gmail 邮件退订工具 📬       ║
╠══════════════════════════════════╣
║  1. 扫描邮件                     ║
║  2. 执行退订                     ║
║  3. 查看退订历史                 ║
║  4. 管理白名单                   ║
║  5. 设置                         ║
║  0. 退出                         ║
╚══════════════════════════════════╝
请选择 >
```

**扫描子流程**：
- 提问：扫描天数（默认 30，输入 0 扫全部）
- 提问：只扫促销还是全部邮件
- 提问：是否使用 AI 辅助
- 自动开始扫描 → 展示分类结果

**退订子流程**：
- 先执行扫描（复用扫描子流程的提问）
- 按类别分组展示结果
- 用户选择类别字母 → 展开该类别的发件人列表
- 用户输入编号退订单个/多个，或 all 退订该类别全部
- 输入 0 返回类别列表

**设置子菜单**：
- 切换 AI 模型（MiniMax / Claude）
- 设置默认扫描天数
- 设置是否默认使用 AI

**兼容性**：原有 CLI 参数全部保留。带子命令（如 `python main.py scan --days 30`）时直接执行，不进菜单。

### 2. 扫描加速（3 线程并发）

改造 `scanner.py` 的 `_fetch_messages_batch`：

- 使用 `ThreadPoolExecutor(max_workers=3)` 并发获取邮件 metadata
- 每个线程通过 `_get_thread_service()` 获取独立的 Gmail service 对象（已有实现）
- 每个线程在请求后 sleep `REQUEST_SLEEP`（0.15s），总 QPS ≈ 20
- 429/500/503 错误重试逻辑保持不变（每线程独立重试）
- 进度打印使用 `threading.Lock` 防止输出交错
- 预期提速：约 3 倍（从串行变 3 并发）

### 3. AI 模型支持 MiniMax

`config.py` 新增配置：

```python
AI_PROVIDER = "minimax"  # "minimax" 或 "anthropic"
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_MODEL = "MiniMax-Text-01"
MINIMAX_BASE_URL = "https://api.minimax.chat/v1"
```

`ai_classifier.py` 改造：
- 新增 `_call_minimax(prompt)` 函数，使用 `openai` 库 + 自定义 base_url
- 原有 `_call_anthropic(prompt)` 保留
- `classify_with_ai()` 根据 `config.AI_PROVIDER` 分派到对应引擎
- 新增 `categorize_with_ai(sender, subject)` 函数，让 AI 返回类别名

### 4. 邮件分类系统

**类别定义**（`config.py`）：

```python
EMAIL_CATEGORIES = {
    "电商购物": {"icon": "🛒", "domains": ["taobao.com", "jd.com", "amazon.com", "pinduoduo.com", ...]},
    "社交媒体": {"icon": "📱", "domains": ["linkedin.com", "facebook.com", "weibo.com", ...]},
    "金融理财": {"icon": "💰", "domains": ["fund.eastmoney.com", ...]},
    "新闻资讯": {"icon": "📰", "domains": ["36kr.com", "toutiao.com", ...]},
    "娱乐游戏": {"icon": "🎮", "domains": ["steam.com", "epicgames.com", ...]},
    "餐饮外卖": {"icon": "🍔", "domains": ["meituan.com", "ele.me", ...]},
    "旅行出行": {"icon": "✈️", "domains": ["ctrip.com", "booking.com", ...]},
    "科技服务": {"icon": "💻", "domains": ["heroku.com", "vercel.com", ...]},
    "其他":     {"icon": "📧", "domains": []},
}
```

**分类逻辑**（`classifier.py` 新增 `categorize_groups()`）：
1. 遍历已归组的发件人
2. 先查域名映射表，命中则直接分类
3. 未命中且 AI 开启时，调用 `ai_classifier.categorize_with_ai()` 判断
4. 都没命中则归入"其他"
5. 返回 `{类别名: [发件人分组列表]}` 的字典

**分类时机**：在 `classifier.classify_emails()` 之后、展示结果之前调用。

### 5. 按类别退订交互

展示格式：

```
📊 扫描完成！按类别分组：

  [A] 🛒 电商购物（15 个发件人，87 封）
  [B] 📰 新闻资讯（8 个发件人，45 封）
  [C] 💻 科技服务（5 个发件人，23 封）

操作：输入字母展开类别 / all 退订全部 / 0 返回
>
```

展开后：

```
🛒 电商购物 — 15 个发件人：

  [1] 淘宝营销 (taobao@em.taobao.com) — 32封
  [2] 拼多多 (pdd@pinduoduo.com) — 28封

输入编号退订（如 1,3,5）/ all 退订全部 / 0 返回
>
```

### 6. 文档更新

- `README.md`：更新快速启动（加入交互模式说明）、推荐流程
- `docs/USAGE.md`：更新命令速查、新增交互模式说明、MiniMax 配置说明

## 文件改动清单

| 文件 | 改动 |
|------|------|
| `main.py` | 新增交互菜单系统 + 分类展示 + 按类别退订交互 |
| `scanner.py` | `_fetch_messages_batch` 改为 3 线程并发 |
| `config.py` | MiniMax 配置 + EMAIL_CATEGORIES 域名分类映射 |
| `ai_classifier.py` | 支持 MiniMax 调用 + 新增 `categorize_with_ai()` |
| `classifier.py` | 新增 `categorize_groups()` 按类别归组 |
| `README.md` | 更新使用说明 |
| `docs/USAGE.md` | 更新命令速查 + 交互模式 + MiniMax 配置 |

**不改动**：`auth.py`、`database.py`、`unsubscriber.py`

## 新增依赖

- `openai` — 用于调用 MiniMax API（OpenAI 兼容格式）

## 不做的事

- 不做 Web GUI（终端菜单足够，避免额外复杂度）
- 不做邮件缓存（本次只做并发加速，缓存留给以后）
- 不改退订执行逻辑（unsubscriber.py 不动）
- 不改数据库结构（database.py 不动）
