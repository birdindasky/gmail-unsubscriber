# Gmail 智能退订器 · 使用手册

> 帮您自动清理 Gmail 广告邮件订阅的工具。安全、可靠、有记忆。

---

## 目录

1. [这个工具能做什么](#1-这个工具能做什么)
2. [首次配置（只需做一次）](#2-首次配置只需做一次)
3. [理解两个核心命令](#3-理解两个核心命令)
4. [推荐工作流程](#4-推荐工作流程)
5. [所有命令详解](#5-所有命令详解)
6. [白名单管理](#6-白名单管理)
7. [其他命令](#7-其他命令)
8. [常见问题](#8-常见问题)
9. [安全说明](#9-安全说明)

---

## 1. 这个工具能做什么

- **扫描**：自动分析 Gmail 中的广告/促销邮件，列出建议退订的发件人
- **退订**：自动向对方发送退订请求（三种方式依次尝试）
- **标记**：退订成功后在 Gmail 里打上「已退订」标签
- **归档**：可选择把退订成功的旧广告邮件从收件箱移走（不删除）
- **记忆**：记住退订过的发件人，下次不会重复处理
- **AI 辅助**：遇到模棱两可的邮件，由 AI 帮忙判断（支持 9 家提供商，通过菜单配置）

**绝对不会做的事：**
- 不会删除任何邮件
- 不会碰白名单里的发件人（银行、Google、政府等）

---

## 2. 首次配置（只需做一次）

> **跨平台说明**：本工具是纯 Python 程序，**Mac / Linux / Windows / WSL2 都可以跑**。文档命令默认是 Mac/Linux 写法，Windows 原生用户请看下方「Windows 用户适配」小节。

### 第一步：安装依赖

```bash
cd /path/to/gmail-unsubscriber   # 改成项目实际路径
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # 需要跑测试时再装
```

> **Python 版本建议**：请尽量使用 **Python 3.10 或更高版本**。项目在较老版本上可能还能运行，但 Google 相关依赖已经对 Python 3.9 发出停止常规支持提示。

> 每次打开新的终端窗口，都需要重新运行 `source venv/bin/activate` 激活环境（命令行前面会显示 `(venv)`）。

#### 🪟 Windows 用户适配

Windows 原生（PowerShell / CMD）和 Mac 的命令稍有不同：

| 操作 | Mac / Linux / WSL2 | Windows 原生 |
|------|-------------------|-------------|
| 激活虚拟环境 | `source venv/bin/activate` | `venv\Scripts\activate` |
| 设置环境变量（临时） | `export KEY=value` | `set KEY=value` （CMD）<br>`$env:KEY="value"` （PowerShell） |
| 设置环境变量（永久） | 写入 `~/.zshrc` 或 `~/.bashrc` | 系统属性 → 环境变量，或 PowerShell 的 `$PROFILE` |
| 文件路径分隔符 | `/` | `\`（Python 代码内两者都支持，命令行用 `\`）|

其余命令（`python3 main.py ...`）完全相同。如果您装的是 Python 3.x 官方版，命令可能是 `python` 而不是 `python3`，按实际情况替换即可。

#### 🐧 WSL2 用户（推荐 Windows 用户使用）

WSL2（Windows Subsystem for Linux 2）本质是 Windows 里跑的 Ubuntu，**命令和 Mac/Linux 完全一致**，不用记两套语法。推荐 Windows 用户用这种方式，体验最接近 Mac。

在 WSL2 里一次性初始化：

```bash
# 进入 WSL2 终端后
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
cd ~                             # 或其他您想放项目的目录
git clone <本项目仓库地址> gmail-unsubscriber
cd gmail-unsubscriber
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**WSL2 下 OAuth 浏览器授权的小坑**：WSL2 没有图形界面，首次授权时程序会打印一个 `http://localhost:xxxxx/?code=...` 链接。把这个链接复制到 Windows 的浏览器里打开，完成授权即可。现代 WSL2（Windows 11 + 最新版）已支持自动唤起 Windows 浏览器，大多数情况下会直接弹出来。

**WSL2 下的文件路径**：项目最好放在 WSL2 的文件系统里（如 `~/gmail-unsubscriber`），**不要放在 `/mnt/c/...`**（Windows 盘挂载路径），否则 Python 读写性能会断崖下降。

### 第二步：获取 Google API 凭证

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建一个新项目（名字随意，如 "Gmail Unsubscriber"）
3. 左侧菜单 → **API 和服务** → **启用 API 和服务** → 搜索并启用 **Gmail API**
4. 左侧菜单 → **凭据** → **创建凭据** → **OAuth 客户端 ID**
5. 应用类型选 **桌面应用**，点击下载
6. 将下载的文件重命名为 `credentials.json`，放入项目根目录

```
gmail-unsubscriber/
├── credentials.json   ← 放这里
├── main.py
└── ...
```

> ⚠️ `credentials.json` 是访问 Google 服务的凭据，切勿上传到 GitHub 或分享给他人。该文件已被加入 `.gitignore`。

### 第三步：首次 OAuth 授权

首次运行任何命令时，程序会自动打开浏览器要求授权：

```bash
python3 main.py scan
```

1. 在浏览器中选择您的 Google 账号
2. 看到"此应用未经 Google 验证"警告时：点击 **高级** → **前往（不安全）**
3. 勾选所有权限，点击 **继续**
4. 浏览器显示授权完成后，回到终端即可

**授权只需做一次**，之后自动使用保存的 `token.json`。

---

## 3. 理解两个核心命令

这是理解本工具的关键：

| 命令 | 做什么 | 适合什么时候用 |
|------|--------|---------------|
| `scan` | **只扫描，不退订**。列出建议退订的发件人供您查看 | 想先看看有哪些广告发件人，再决定是否退订 |
| `unsubscribe` | **扫描 + 退订**。内部会先做一次扫描，然后执行退订 | 想直接退订时 |

**命令行模式**：`scan` 和 `unsubscribe` 各自独立运行扫描，互不影响。`scan` 的价值在于让您**提前预览**，方便您先把不想退订的域名加入白名单，再执行 `unsubscribe`。

**交互菜单模式**（`python3 main.py` 不带参数）：扫描结果会在本次运行中**自动缓存**。在菜单里先选 1 扫描，再选 2 退订时，程序会直接使用上次扫描的结果，不用重新扫一遍；也可以选择重新扫。菜单里「扫描邮件」旁显示 ✅ 表示已有缓存。

---

## 4. 推荐工作流程

### 首次深度清理（建议按顺序执行）

```bash
# 第一步：激活虚拟环境
source venv/bin/activate

# 第二步：扫描，看看有哪些广告发件人
# 先从“全部历史促销邮件”开始，而不是直接扫整个邮箱
python3 main.py scan --days 0

# 第三步：如果扫描结果里有不想退订的发件人，把他们的域名加白名单
python3 main.py whitelist add 某公司.com

# 第四步：试运行退订，确认程序打算怎么做（不会真的发送退订请求）
python3 main.py unsubscribe --dry-run --days 0

# 第五步：确认没问题后，正式执行退订（逐个询问您）
python3 main.py unsubscribe --confirm --days 0
```

### 全邮箱历史排查（先抽样，再决定是否全量）

```bash
# 先抽样 500 封，确认结果是否靠谱
python3 main.py scan --days 0 --all --max-messages 500 --no-ai

# 不写 --max-messages 时，程序也会默认保护到前 2000 封
python3 main.py scan --days 0 --all --no-ai

# 只有在您明确知道自己要扫完整个邮箱时，才使用 --full-scan
python3 main.py scan --days 0 --all --full-scan --no-ai
```

> **重要**：`--all` 会把扫描范围从“促销标签”扩大到“全部收到的邮件”（同时默认排除已发送、草稿、垃圾箱、垃圾邮件），速度明显更慢。建议总是先用 `--max-messages` 抽样验证。

### 日常维护（每月一次，快速扫最近 30 天）

```bash
source venv/bin/activate
python3 main.py unsubscribe --confirm --days 30
```

### 跑测试（建议改动代码后执行）

```bash
source venv/bin/activate
python -m pytest
```

如果提示 `No module named pytest`，通常说明您还没安装测试依赖，或者没有激活项目的 `venv`。

---

## 5. 所有命令详解

### `scan` — 扫描邮件（只看，不退订）

```bash
python3 main.py scan [选项]
```

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--days N` | 扫描最近 N 天；`0` 表示不限时间扫全部历史 | 30 天 |
| `--all` | 扫描全部分类（默认只扫 Gmail 的促销标签） | 关闭 |
| `--max-messages N` | 最多处理前 N 封邮件，适合大样本抽样验证 | 不限 |
| `--full-scan` | 在 `--days 0 --all` 下关闭默认保护上限，执行完整扫描 | 关闭 |
| `--no-ai` | 不使用 AI 辅助判断，只用关键词规则 | 开启 AI |

**示例：**
```bash
python3 main.py scan                          # 扫描最近 30 天的促销邮件
python3 main.py scan --days 90               # 扫描最近 3 个月的促销邮件
python3 main.py scan --days 0                # 扫描全部历史促销邮件
python3 main.py scan --days 0 --all          # 扫描全部历史邮件（默认保护到前 2000 封）
python3 main.py scan --days 0 --all --max-messages 500
python3 main.py scan --days 0 --all --full-scan
python3 main.py scan --no-ai                 # 不调用 AI，纯规则判断
```

**关于 `--days 0 --all` 的默认保护：**
- 如果您没有写 `--max-messages`，程序会默认只处理前 `2000` 封邮件
- 这是为了避免第一次运行时误扫整个邮箱，导致等待时间过长
- 如果您确实要完整扫描，请显式加 `--full-scan`

---

### `unsubscribe` — 执行退订

```bash
python3 main.py unsubscribe (--dry-run | --confirm) [选项]
```

**必须二选一的模式：**

| 模式 | 说明 |
|------|------|
| `--dry-run` | 试运行：只展示会退订什么，**不实际发送退订请求** |
| `--confirm` | 执行退订：默认逐个询问您是否确认 |

**可选参数：**

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--auto` | 配合 `--confirm` 使用，自动确认所有退订（不逐个询问） | 关闭 |
| `--archive` | 退订成功后，把该发件人的旧邮件从收件箱移到归档 | 关闭 |
| `--days N` | 扫描最近 N 天；`0` 表示不限时间扫全部历史 | 30 天 |
| `--all` | 扫描全部分类（默认只扫促销标签） | 关闭 |
| `--max-messages N` | 最多处理前 N 封邮件，适合大样本抽样验证 | 不限 |
| `--full-scan` | 在 `--days 0 --all` 下关闭默认保护上限，执行完整扫描 | 关闭 |
| `--no-ai` | 不使用 AI 辅助判断 | 开启 AI |

**示例：**
```bash
# 试运行，看看程序打算退订哪些（最安全，推荐第一次使用时运行）
python3 main.py unsubscribe --dry-run

# 逐个确认执行退订（推荐日常使用）
python3 main.py unsubscribe --confirm

# 自动退订所有建议发件人（不逐个询问）
python3 main.py unsubscribe --confirm --auto

# 退订 + 顺手把旧广告邮件从收件箱移走
python3 main.py unsubscribe --confirm --archive

# 全邮箱先抽样 dry-run，再决定是否完整执行
python3 main.py unsubscribe --dry-run --days 0 --all --max-messages 500

# 扫全部历史邮件，逐个确认，退订后归档（默认仍受 2000 封保护）
python3 main.py unsubscribe --confirm --archive --days 0 --all
```

**逐个确认时的按键说明：**
- `y` 或直接回车 → 退订这个发件人
- `n` → 跳过，不退订
- `q` → 立即停止，退出程序

---

## 6. 白名单管理

白名单分两层：

- **内置白名单**：银行、Google、Apple、政府、教育机构等，已写入代码，永远不会被退订
- **用户自定义白名单**：您自己添加的域名，存在本地数据库

```bash
# 查看白名单（含内置类别和您自己添加的）
python3 main.py whitelist list

# 添加域名到白名单
python3 main.py whitelist add mycompany.com
python3 main.py whitelist add newsletter-i-like.com
```

**内置白名单已覆盖的类别（无需手动添加）：**
- 银行 & 金融：工商银行、招商银行、PayPal、Alipay 等
- 科技公司：Google、Apple、Microsoft、GitHub 等
- 中国平台：淘宝、京东、163 邮箱等
- 政府机构：gov.cn 等
- 教育机构：.edu、edu.cn、coursera.org 等

---

## 7. 其他命令

### `history` — 查看退订历史

```bash
python3 main.py history             # 显示最近 50 条退订记录
python3 main.py history --limit 20  # 只显示最近 20 条
```

已退订的发件人**下次扫描不会再出现**，无需担心重复处理。

### `logs` — 查看运行日志

```bash
python3 main.py logs
```

显示最新日志文件的最后 50 行，排查问题时使用。

### `--verbose` — 输出详细调试信息

```bash
python3 main.py --verbose scan
python3 main.py --verbose unsubscribe --confirm
```

`--verbose` 需要放在命令名称前面（紧跟 `main.py` 之后）。

---

## 8. 常见问题

**Q：扫不到广告邮件，但我明明有很多？**

A：可能原因：
1. 邮件超出了默认 30 天范围 → 试试 `--days 90` 或 `--days 0`（全部历史）
2. Gmail 把这些邮件归到了促销标签以外的分类 → 加上 `--all` 参数
3. 如果 `--all` 看起来太慢，先加 `--max-messages 500` 做抽样验证，再决定是否 `--full-scan`
3. 发件人在白名单里 → 运行 `python3 main.py whitelist list` 查看

**Q：扫描 10000 封邮件大概要多久？**

A：按当前版本在真实邮箱上的测试经验，粗略可以这样估：
- **只扫描和分类**：约 `10 到 15 分钟`
- **扫描 + 实际退订少量候选发件人**：约 `12 到 20 分钟`

影响时间的主要因素：
1. 是否用了 `--all`（比只扫促销标签慢很多）
2. 是否开启 AI
3. 最终需要实际退订的发件人数
4. Gmail API 是否触发重试

如果您只是想先判断结果靠不靠谱，建议先用：
`python3 main.py scan --days 0 --all --max-messages 500 --no-ai`

**Q：退订成功了，但旧邮件还在收件箱？**

A：这是正常的。退订只告诉对方"别再发了"，不会动已有邮件。如需清理旧邮件，退订时加上 `--archive` 参数。

**Q：退订失败怎么办？**

A：对方的退订系统没有响应。此时请手动打开邮件，点击邮件底部的退订链接。

**Q：担心误退订重要邮件怎么办？**

A：三道保险：① 内置白名单（银行、Google 等绝对跳过）② 敏感词检测（含验证码、订单、账单的邮件跳过）③ 先用 `--dry-run` 预览确认。

**Q：credentials.json / token.json 是什么？**

A：`credentials.json` 是 Google 颁发给本应用的"身份证"。`token.json` 是您授权后保存的"通行令牌"。两个文件都只存在本地，已加入 `.gitignore`。删除 `token.json` 后，下次运行会重新弹出浏览器授权。

**Q：AI 辅助判断会产生费用吗？**

A：会，但极低。默认使用 MiniMax（国内模型，费用低）；可切换到 Anthropic Claude。配合程序内置的**同发件人只调一次**缓存，通常 1 万封邮件只会触发几十到几百次 AI 调用。大多数邮件走本地规则判断，不花钱。没有配置 API Key 时 AI 判断自动跳过，不影响基本功能。

**Q：可以用于多个 Gmail 账号吗？**

A：目前一个项目目录对应一个账号。多账号请复制多份项目目录，分别完成授权。

---

## 9. AI 辅助判断（可选）

### 一键配置：使用交互菜单

```bash
python3 main.py
# 选择 5. 设置
# 选择 1. 配置 AI 提供商
```

按提示选择提供商、粘贴 API Key、确认模型，程序会自动测试连接，成功后立即保存。

### 支持的提供商

| 提供商 | 协议 | 备注 |
|--------|------|------|
| OpenAI | OpenAI | 模型：gpt-4o-mini（默认） |
| Anthropic Claude | Anthropic | 模型：claude-haiku-4-5（默认） |
| MiniMax | Anthropic 兼容 | 国内模型，费用低 |
| DeepSeek | OpenAI 兼容 | 国内模型，费用低 |
| Moonshot (Kimi) | OpenAI 兼容 | 国内模型 |
| 通义千问 | OpenAI 兼容 | 阿里云 |
| 智谱 GLM | OpenAI 兼容 | GLM-4-Flash 默认 |
| Ollama (本地) | OpenAI 兼容 | 自己电脑跑，免费 |
| 自定义 | OpenAI 兼容 | 任何 OpenAI 协议服务都能接 |

### 配置文件位置

所有配置存于项目根目录 `user_config.json`（已加入 `.gitignore`，不会上传 git）：

```json
{
  "ai_provider": "deepseek",
  "providers": {
    "deepseek": {"api_key": "sk-...", "model": "deepseek-chat"}
  }
}
```

### AI 调用会被缓存

- **按发件人缓存**：同一个发件人邮箱，AI 只会被问一次，后续同发件人的邮件直接复用结果
- **按域名缓存**：归类阶段，同一个域名也只问一次
- 缓存只在本次运行内有效，重新启动程序后重新计算

### 关闭 AI

```bash
python3 main.py scan --no-ai              # 本次不用 AI
python3 main.py unsubscribe --no-ai ...   # 本次不用 AI
```

或者在 `config.py` 中永久关闭：
```python
USE_AI_CLASSIFIER = False
```

### 老用户无感迁移

如果您之前通过 `export MINIMAX_API_KEY=...` 等环境变量配置过，首次启动新版本会自动生成 `user_config.json`，您不需要做任何事。

### 查看当前配置

交互菜单 → 5. 设置 → 2. 查看当前配置。API Key 会脱敏展示（前 6 位 + 后 6 位）。

---

## 10. 安全说明

| 内容 | 保护措施 |
|------|---------|
| Google 账号密码 | 程序**永远不接触**您的密码，使用 OAuth 2.0 临时令牌 |
| OAuth 令牌 | 保存在 `token.json`，已加入 .gitignore，不会上传 git |
| API 凭证 | `credentials.json` 已加入 .gitignore，不会上传 git |
| AI API Key | 存入 `user_config.json`（已加入 `.gitignore`），不写入代码；展示时脱敏 |
| 邮件内容 | AI 判断只发送发件人 + 主题 + 摘要，不发送邮件正文 |
| 退订操作 | 只发退订请求，**不删除任何邮件** |

**随时撤销授权：**
访问 [Google 账号安全设置](https://myaccount.google.com/permissions)，找到本应用，点击撤销即可。
