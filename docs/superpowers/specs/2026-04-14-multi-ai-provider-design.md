# 多 AI 提供商 + 交互式配置 设计文档

**日期：** 2026-04-14
**作者：** Claude（受陛下委托）
**状态：** 待实施

---

## 1. 背景与目标

### 1.1 现状

当前 `ai_classifier.py` 只支持 MiniMax 和 Anthropic 两家 AI 提供商，配置方式只有两种：

1. 在 `config.py` 中硬编码 API Key
2. 通过环境变量（`MINIMAX_API_KEY` / `ANTHROPIC_API_KEY` / `AI_PROVIDER`）

对编程小白极不友好：需要懂 shell 命令、知道 `~/.zshrc` 是什么，改完还要 `source` 生效。

### 1.2 目标

让 Gmail 退订工具变成一款**不懂编程也能配置 AI** 的工具：

1. **交互式配置**：菜单里选提供商、填 Key、自动测试，30 秒完成
2. **多提供商支持**：内置 8 家主流 AI（OpenAI、Anthropic、MiniMax、DeepSeek、Moonshot、通义千问、智谱、Ollama）+ 自定义兜底
3. **零破坏迁移**：现有用户的环境变量自动迁移到新配置文件，无感切换

### 1.3 非目标

- 不做多账号切换（一次只激活一个提供商）
- 不做 Gemini 接入（需要独立 SDK，工作量大，且国内用户访问不便）
- 不对 API Key 加密存储（和 `token.json` 同级安全度，足够）

---

## 2. 用户体验设计

### 2.1 首次运行（有环境变量的老用户）

程序检测到 `user_config.json` 不存在但环境变量有 Key，自动生成配置文件：

```
$ python3 main.py
🔄 检测到环境变量中的 AI 配置，已自动迁移到 user_config.json
✅ 当前使用 MiniMax（模型：MiniMax-M2）

╔══════════════════════════════════╗
║      Gmail 邮件退订工具 📬       ║
╚══════════════════════════════════╝
```

### 2.2 新用户首次配置

进入 `5. 设置` → `1. 配置 AI 提供商`：

```
请选择 AI 提供商：
  1. OpenAI              (sk-...)
  2. Anthropic Claude    (sk-ant-...)
  3. MiniMax             (sk-cp-...)
  4. DeepSeek            (sk-...)
  5. Moonshot (Kimi)     (sk-...)
  6. 通义千问            (sk-...)
  7. 智谱 GLM            (...)
  8. Ollama (本地)       (随便填)
  9. 自定义 OpenAI 兼容
  0. 返回

请选择：4

【DeepSeek】
请输入 API Key: sk-abc123xyz789...
默认模型：deepseek-chat，使用默认吗？(Y/n): y

🔍 测试连接中...
✅ 连接成功！

已保存配置。当前使用：DeepSeek（模型：deepseek-chat）
```

### 2.3 自定义提供商流程

选 `9. 自定义 OpenAI 兼容` 时，额外询问 `base_url` 和 `model`：

```
【自定义 OpenAI 兼容】
请输入 base_url: https://api.example.com/v1
请输入 model: my-model-v2
请输入 API Key: sk-xxx...

🔍 测试连接中...
✅ 连接成功！
```

### 2.4 查看当前配置（Key 脱敏）

```
当前 AI 配置：
  提供商：DeepSeek
  模型：  deepseek-chat
  Key：   sk-abc***...xyz789
  状态：  ✅ 可用
```

**脱敏规则：** 前 6 位 + `***...` + 后 6 位；长度不足 15 位的 Key 显示 `sk-***`。

### 2.5 输入时的行为

- **API Key 输入：** 普通 `input()` 明文回显（方便粘贴核对），保存后仅存全量，展示时脱敏
- **确认选项（y/n）：** 回车默认 y
- **选错号码：** 提示"无效选择"，返回菜单

### 2.6 连接测试

保存配置前自动测试：

- **成功：** `✅ 连接成功！`
- **认证失败（401）：** `❌ API Key 无效，请检查后重试`
- **模型不存在（404）：** `❌ 模型 "xxx" 不存在，请检查模型名`
- **网络不通：** `❌ 网络连接失败：<错误详情>`

测试失败时不保存，回到菜单让用户重填。

---

## 3. 技术设计

### 3.1 配置文件结构

**文件位置：** `user_config.json`（项目根目录，加入 `.gitignore`）

```json
{
  "ai_provider": "deepseek",
  "providers": {
    "deepseek": {
      "api_key": "sk-abc123xyz789",
      "model": "deepseek-chat"
    }
  }
}
```

**自定义提供商额外字段：**

```json
{
  "ai_provider": "custom",
  "providers": {
    "custom": {
      "api_key": "sk-xxx",
      "model": "my-model-v2",
      "base_url": "https://api.example.com/v1"
    }
  }
}
```

### 3.2 提供商注册表

在 `ai_classifier.py` 中硬编码：

```python
PROVIDERS = {
    "openai":    {"name": "OpenAI", "protocol": "openai", "base_url": "https://api.openai.com/v1", "default_model": "gpt-4o-mini", "key_hint": "sk-..."},
    "anthropic": {"name": "Anthropic Claude", "protocol": "anthropic", "base_url": None, "default_model": "claude-haiku-4-5", "key_hint": "sk-ant-..."},
    "minimax":   {"name": "MiniMax", "protocol": "anthropic", "base_url": "https://api.minimaxi.com/anthropic", "default_model": "MiniMax-M2", "key_hint": "sk-cp-..."},
    "deepseek":  {"name": "DeepSeek", "protocol": "openai", "base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat", "key_hint": "sk-..."},
    "moonshot":  {"name": "Moonshot (Kimi)", "protocol": "openai", "base_url": "https://api.moonshot.cn/v1", "default_model": "moonshot-v1-8k", "key_hint": "sk-..."},
    "qwen":      {"name": "通义千问", "protocol": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-turbo", "key_hint": "sk-..."},
    "zhipu":     {"name": "智谱 GLM", "protocol": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4", "default_model": "glm-4-flash", "key_hint": "..."},
    "ollama":    {"name": "Ollama (本地)", "protocol": "openai", "base_url": "http://localhost:11434/v1", "default_model": "llama3", "key_hint": "随便填"},
    "custom":    {"name": "自定义 OpenAI 兼容", "protocol": "openai", "base_url": None, "default_model": None, "key_hint": "..."},
}
```

**protocol 只有两个值**：
- `"openai"`：走 `openai` SDK
- `"anthropic"`：走 `anthropic` SDK（含 MiniMax 兼容端点）

### 3.3 模块改动清单

| 文件 | 改动 |
|------|------|
| **`user_config.py`** | **新建**。管理 `user_config.json` 的读写、迁移、脱敏展示 |
| **`ai_classifier.py`** | 重构：加 `PROVIDERS` 注册表、`_call_openai()` 分支、配置源从 `user_config` 读取 |
| **`config.py`** | 保留 `SENSITIVE_KEYWORDS` / `AD_KEYWORDS` / `DOMAIN_TO_CATEGORY` 等常量；保留 `USE_AI_CLASSIFIER`（全局 AI 开关）；**移除** `ANTHROPIC_API_KEY` / `MINIMAX_API_KEY` / `AI_PROVIDER` / `MINIMAX_BASE_URL` / `MINIMAX_MODEL` / `AI_MODEL` 等与提供商相关的常量（改由 `user_config` 管理） |
| **`main.py`** | `_interactive_settings()` 扩展为完整的 AI 配置菜单 |
| **`requirements.txt`** | 新增 `openai>=1.0` |
| **`.gitignore`** | 新增 `user_config.json` |

### 3.4 `user_config.py` 新模块职责

```python
# 加载 & 保存
def load_config() -> dict
def save_config(config: dict) -> None

# 读取当前活跃提供商
def get_active_provider() -> Optional[dict]
    # 返回 {"id": "deepseek", "api_key": "...", "model": "...", "base_url": "..."}
    # 不存在时返回 None

# 设置活跃提供商
def set_active_provider(provider_id: str, api_key: str, model: str, base_url: Optional[str] = None) -> None

# 首次运行迁移（只在 user_config.json 不存在时触发）
def migrate_from_env() -> bool
    # 返回是否迁移成功

# 脱敏展示
def mask_key(key: str) -> str
```

### 3.5 AI 调用分发重构

`ai_classifier.py` 核心调度逻辑：

`_check_ai_available()` 更新：同时检查 `config.USE_AI_CLASSIFIER` 总开关 + `user_config.get_active_provider()` 非空。两者皆真才启用 AI。

```python
def _call_ai(prompt: str) -> str:
    provider = user_config.get_active_provider()
    if not provider:
        raise RuntimeError("未配置 AI 提供商")

    protocol = PROVIDERS[provider["id"]]["protocol"]
    if protocol == "openai":
        return _call_openai(prompt, provider)
    elif protocol == "anthropic":
        return _call_anthropic(prompt, provider)
    else:
        raise ValueError(f"未知协议：{protocol}")
```

`_call_openai()` 使用 `openai.OpenAI(api_key=..., base_url=...)` 客户端，调用 `chat.completions.create()`。

### 3.6 连接测试

```python
def test_connection(provider_id: str, api_key: str, model: str, base_url: Optional[str] = None) -> tuple[bool, str]:
    """返回 (是否成功, 错误信息)"""
```

实现方式：发一个极短的 prompt（"Say hi in one word."）、限制 `max_tokens=10`，检查响应是否有效。

### 3.7 环境变量迁移逻辑

首次启动 `main.py` 时调用 `user_config.migrate_from_env()`：

1. 如果 `user_config.json` 已存在 → 跳过
2. 读取环境变量 `AI_PROVIDER`、`MINIMAX_API_KEY`、`ANTHROPIC_API_KEY`
3. 优先级：`AI_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` > `MINIMAX_API_KEY`
4. 生成配置文件，打印迁移提示

迁移后，环境变量**不再读取**（配置文件是唯一源）。

### 3.8 设置菜单流程图

```
5. 设置
├── 1. 配置 AI 提供商
│     ├── 显示当前配置（如有）
│     ├── 选择提供商（1-9, 0 返回）
│     ├── [若选 9 自定义] 输入 base_url + model
│     ├── 输入 API Key
│     ├── [非自定义] 问"用默认模型吗？"
│     ├── 测试连接 → 成功则保存，失败则返回
│     └── 保存 → 打印成功信息
├── 2. 查看当前配置（脱敏）
└── 0. 返回
```

---

## 4. 错误处理

| 场景 | 处理方式 |
|------|---------|
| `user_config.json` 损坏（JSON 解析失败） | 打印警告，当作"未配置"处理，不覆盖原文件 |
| `user_config.json` 中 `ai_provider` 不在 `PROVIDERS` 注册表里 | 警告 + 当作未配置 |
| 已配置提供商，调用 AI 时网络失败 | 沿用现有重试逻辑（`ai_classifier` 已有异常捕获） |
| 配置自定义提供商但缺 `base_url` | 菜单流程强制要求，不允许空 |
| 连接测试因网络慢超时 | 设置 10 秒超时，超时算失败 |

---

## 5. 安全考量

| 风险 | 措施 |
|------|------|
| `user_config.json` 被 git 误提交 | 加入 `.gitignore` |
| Key 在屏幕上暴露 | 展示时脱敏（前 6 + 后 6） |
| Key 明文存储 | 风险等级与 `token.json` 一致；不加密（加密反而引入密钥管理复杂度） |
| 测试连接泄露 Key 到日志 | 测试失败时只打印 HTTP 状态码和错误类型，不打印 Key |

---

## 6. 测试策略

### 6.1 单元测试

- **`tests/test_user_config.py`** 新建：
  - `test_load_save_roundtrip` — 读写往返
  - `test_load_missing_file` — 文件不存在返回空配置
  - `test_load_corrupted_json` — 损坏 JSON 不抛异常
  - `test_migrate_from_env_minimax` — 迁移 MiniMax 环境变量
  - `test_migrate_from_env_anthropic` — 迁移 Anthropic 环境变量
  - `test_migrate_skips_if_config_exists` — 已有配置不迁移
  - `test_mask_key` — Key 脱敏格式
  - `test_get_active_provider_none` — 未配置时返回 None
  - `test_set_active_provider_custom` — 自定义带 base_url

- **`tests/test_ai_classifier.py`** 扩展：
  - `test_call_openai_protocol` — OpenAI 协议分发
  - `test_call_anthropic_protocol` — Anthropic 协议分发
  - `test_no_provider_configured` — 未配置时跳过 AI
  - `test_test_connection_success` — Mock 成功
  - `test_test_connection_auth_fail` — Mock 401

### 6.2 手动测试清单

开发完成后陛下手动走一遍：
1. 删除 `user_config.json`，设置环境变量，运行 → 验证自动迁移
2. 菜单里配置 DeepSeek → 扫描一批邮件 → 确认 AI 调用生效
3. 菜单切换到 OpenAI（假 Key）→ 验证连接测试报错
4. 用自定义入口配置 DeepSeek（手填 base_url）→ 验证与选项 4 等效

---

## 7. 实施顺序概览

（详细分任务见 `docs/superpowers/plans/2026-04-14-multi-ai-provider.md`）

1. 新建 `user_config.py` 模块 + 测试
2. 重构 `ai_classifier.py`，加 `PROVIDERS` 注册表 + OpenAI 分支 + 测试
3. 改造 `main.py` 设置菜单
4. 首次启动迁移逻辑
5. 更新文档（USAGE_GUIDE、README、FILE_OVERVIEW、ARCHITECTURE）
6. 端到端手动测试

---

## 8. 向后兼容性

- **环境变量用户**：无感迁移，首次启动自动生成配置文件
- **`config.py` 硬编码 Key 的用户**：迁移时不会读 `config.py`，需要手动在菜单里重新填一次（发布说明里会提）
- **CLI 命令**：`scan` / `unsubscribe` 等参数一行不变
- **已有 token.json / unsubscribe_history.db**：完全不受影响

---

## 9. 未来可扩展性

- **多 Key 切换**：`providers` 已用 dict 结构，将来想让用户保存多家 Key，只需改菜单 + `get_active_provider()` 读取逻辑，无需改配置文件格式
- **新增提供商**：只需在 `PROVIDERS` 注册表加一行即可
- **加密存储**：若将来要求更高安全，可选接入 `keyring` 库，不影响现有逻辑

---

（文档结束）
