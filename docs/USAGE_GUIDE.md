# Gmail 智能退订器 · 详细使用说明

> 一个帮您自动清理 Gmail 广告邮件订阅的工具。安全、可靠、有记忆。

---

## 目录

1. [这个工具能做什么](#1-这个工具能做什么)
2. [首次配置（只需做一次）](#2-首次配置只需做一次)
3. [日常使用流程](#3-日常使用流程)
4. [所有命令详解](#4-所有命令详解)
5. [Claude AI 辅助判断](#5-claude-ai-辅助判断)
6. [白名单管理](#6-白名单管理)
7. [查看历史记录](#7-查看历史记录)
8. [常见问题](#8-常见问题)
9. [安全说明](#9-安全说明)

---

## 1. 这个工具能做什么

- **扫描**：自动分析 Gmail 中最近的广告/促销邮件
- **退订**：用三种方式尝试退订（一键 POST、发退订邮件、点退订链接）
- **标记**：退订成功后在 Gmail 里打上「已退订」标签，一目了然
- **归档**：可选择把旧的广告邮件从收件箱移走（不删除）
- **记忆**：记住退订过的发件人，下次不会重复处理
- **AI 辅助**：遇到模棱两可的邮件，可以请 Claude AI 帮忙判断

**绝对不会做的事：**
- 不会删除任何邮件
- 不会碰白名单里的发件人（银行、Google、政府等）
- 不会在没有您确认的情况下自动退订

---

## 2. 首次配置（只需做一次）

### 第一步：安装依赖

```bash
cd /Users/bossoffice/gmail-unsubscriber
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 第二步：获取 Google API 凭证

这一步让程序能读取您的 Gmail。操作步骤：

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建一个新项目（名字随意，如 "Gmail Unsubscriber"）
3. 左侧菜单 → **API 和服务** → **启用 API 和服务**
4. 搜索 **Gmail API** → 启用
5. 左侧菜单 → **凭据** → **创建凭据** → **OAuth 客户端 ID**
6. 应用类型选 **桌面应用**
7. 点击下载，将文件重命名为 `credentials.json`
8. 将 `credentials.json` 放入 `/Users/bossoffice/gmail-unsubscriber/` 目录

### 第三步：首次授权

```bash
python main.py scan --days 7
```

首次运行会弹出浏览器，请登录您的 Gmail 账号并点击「允许」。授权只需做一次，之后会自动记住。

---

## 3. 日常使用流程

**推荐的标准流程（五步走）：**

```bash
# 激活虚拟环境（每次打开终端后需要运行一次）
source venv/bin/activate

# 第一步：扫描，看看有哪些广告发件人
python main.py scan

# 第二步：如果扫描结果里有重要联系人，把他们加白名单
python main.py whitelist add 某公司.com

# 第三步：试运行，预览将要执行的操作（安全，不会真的退订）
python main.py unsubscribe --dry-run

# 第四步：确认没问题后，逐个确认执行退订
python main.py unsubscribe --confirm

# 第五步：隔几天再扫一次，看看效果
python main.py scan
```

---

## 4. 所有命令详解

### `scan` — 扫描邮件

```bash
python main.py scan [选项]
```

| 选项 | 说明 | 示例 |
|------|------|------|
| `--days N` | 扫描最近 N 天（默认 30） | `--days 60` |
| `--all` | 扫描全部邮件（默认只扫促销标签） | `--all` |
| `--no-ai` | 不使用 AI 辅助判断 | `--no-ai` |

**示例：**
```bash
python main.py scan                    # 扫描最近 30 天的促销邮件
python main.py scan --days 90 --all   # 扫描最近 3 个月的全部邮件
python main.py scan --no-ai           # 只用关键词判断，不调用 AI
```

---

### `unsubscribe` — 执行退订

```bash
python main.py unsubscribe --dry-run | --confirm [选项]
```

**必须选一个模式（二选一）：**

| 模式 | 说明 |
|------|------|
| `--dry-run` | 试运行，只展示会退订什么，不实际执行 |
| `--confirm` | 实际执行，默认逐个询问您 |

**可选参数：**

| 选项 | 说明 |
|------|------|
| `--auto` | 配合 `--confirm` 使用，自动确认所有退订（不逐个询问） |
| `--archive` | 退订成功后，把该发件人的旧邮件从收件箱移到归档 |
| `--days N` | 扫描最近 N 天（默认 30） |
| `--all` | 扫描全部邮件 |
| `--no-ai` | 不使用 AI |

**示例：**
```bash
# 试运行（最安全，先看看会发生什么）
python main.py unsubscribe --dry-run

# 逐个确认执行（推荐）
python main.py unsubscribe --confirm

# 全自动执行（不询问，直接全部退订）
python main.py unsubscribe --confirm --auto

# 退订 + 归档旧邮件（收件箱会变干净）
python main.py unsubscribe --confirm --archive

# 扫描最近 60 天，逐个确认，退订后归档
python main.py unsubscribe --days 60 --confirm --archive
```

**逐个确认时的操作说明：**
- 输入 `y` 或回车 → 退订这个发件人
- 输入 `n` → 跳过，不退订
- 输入 `q` → 立即停止，不再处理后续发件人

---

### `history` — 查看退订历史

```bash
python main.py history [--limit N]
```

查看所有退订过的发件人记录，包括时间、退订方式、是否成功。

```bash
python main.py history             # 显示最近 50 条记录
python main.py history --limit 20  # 只显示最近 20 条
```

---

### `whitelist` — 管理白名单

```bash
python main.py whitelist add <域名>   # 添加域名到白名单
python main.py whitelist list         # 查看白名单
```

**示例：**
```bash
# 把公司邮件域名加入白名单（不会被退订）
python main.py whitelist add mycompany.com

# 查看当前白名单
python main.py whitelist list
```

**内置白名单已包含（无需手动添加）：**
- 银行：工商银行、招商银行、PayPal 等
- 科技公司：Google、Apple、Microsoft、GitHub 等
- 中国平台：淘宝、京东、163 邮箱等
- 政府机构：gov.cn 等
- 教育机构：.edu 结尾的域名

---

### `logs` — 查看运行日志

```bash
python main.py logs
```

显示最新日志文件的最后 50 行，用于排查问题。

---

## 5. Claude AI 辅助判断

### 工作原理

当一封邮件的广告特征**恰好命中 1 个条件**（不够确定是广告），程序会把邮件的发件人、主题、摘要发给 Claude AI 判断。AI 只回答"是广告/不是广告"，不会接触邮件正文。

### 配置 API Key

有两种方式配置：

**方式一：修改 config.py（永久生效）**
```python
ANTHROPIC_API_KEY = "sk-ant-xxxxxxxxxxxx"
```

**方式二：环境变量（推荐，更安全）**
```bash
export ANTHROPIC_API_KEY="sk-ant-xxxxxxxxxxxx"
python main.py scan
```

如果没有配置 API Key，AI 判断会自动跳过，不影响基本功能。

### 关闭 AI

```bash
python main.py scan --no-ai           # 本次扫描不用 AI
python main.py unsubscribe --no-ai    # 本次退订不用 AI
```

或者在 `config.py` 中永久关闭：
```python
USE_AI_CLASSIFIER = False
```

### 费用参考

使用的是 Claude Haiku 模型，速度快且便宜。1000 封模糊邮件的 AI 判断费用约 **$0.01 美元**（约 0.07 元人民币）。大多数情况下，只有少数邮件会触发 AI 判断。

---

## 6. 白名单管理

白名单分两层：

1. **内置白名单**：银行、Google、政府等，写死在代码里，不会误退订
2. **用户自定义白名单**：您自己添加的域名，存在本地数据库里

```bash
# 添加白名单
python main.py whitelist add mycompany.com    # 公司邮件
python main.py whitelist add newsletter.com  # 您想保留的订阅

# 查看白名单
python main.py whitelist list
```

**什么时候需要手动添加白名单？**
- 公司内部系统发的通知邮件
- 您真心想收到的某个 newsletter
- 扫描结果里出现了不该退订的发件人

---

## 7. 查看历史记录

```bash
python main.py history
```

输出示例：
```
📋 退订历史记录（共 15 条，最近 50 条）
────────────────────────────────────────────────────────────
  [1] 某购物平台 <newsletter@shop.example.com>
      邮箱：newsletter@shop.example.com
      时间：2026-04-11 09:30  方式：一键退订（POST）  ✅

  [2] 广告邮件 <promo@ads.example.com>
      邮箱：promo@ads.example.com
      时间：2026-04-11 09:31  方式：退订邮件发送  ✅

  [3] 某服务通知
      邮箱：info@service.example.com
      时间：2026-04-11 09:32  方式：退订失败  ❌
```

已退订的发件人**下次扫描不会再出现**，无需担心重复处理。

---

## 8. 常见问题

**Q：程序说"未发现需要退订的广告邮件"，但我明明有很多广告邮件？**

A：可能原因：
1. 这些广告邮件比较老，超出了扫描天数。试试 `--days 90` 扫更多天
2. Gmail 没有把这些邮件分到促销标签，试试加 `--all` 参数扫全部邮件
3. 这些发件人在白名单里。用 `python main.py whitelist list` 查看

**Q：退订成功了，但邮件还在收件箱里？**

A：这是正常的。退订只是告诉对方"别再发了"，不会删除已有邮件。如果想清理旧邮件，下次退订时加 `--archive` 参数，会把旧邮件移到 Gmail 归档。

**Q：退订失败是什么意思？**

A：对方的退订系统没有响应或返回了错误。这种情况下您需要手动打开邮件，点击邮件底部的「退订」链接。

**Q：担心误退订重要邮件怎么办？**

A：有三道保护：
1. 内置白名单（银行、Google 等绝对不会被退订）
2. 敏感词检测（含验证码、订单、账单的邮件跳过）
3. 先用 `--dry-run` 看一遍，确认没问题再用 `--confirm` 执行

**Q：想取消之前的退订怎么办？**

A：本工具不支持重新订阅（每个网站的重新订阅方式不同）。需要的话，请直接访问对方网站手动重新订阅。

**Q：credentials.json 怎么获取？**

A：参考本文档第 2 节「首次配置」的步骤，从 Google Cloud Console 下载。

---

## 9. 安全说明

| 内容 | 保护措施 |
|------|---------|
| Google 账号 | 使用 OAuth 2.0，程序拿到的是临时授权令牌，不是您的密码 |
| 授权令牌 | 保存在 `token.json`，已加入 .gitignore，不会上传到 git |
| API 凭证 | `credentials.json` 已加入 .gitignore，不会上传到 git |
| Anthropic API Key | 建议用环境变量设置，不要写进代码文件 |
| 数据库文件 | `gmail-unsubscriber.db` 已加入 .gitignore，只在本地 |
| 邮件内容 | AI 判断只发送发件人+主题+摘要，不发送邮件正文 |
| 退订操作 | 不删除任何邮件，只发退订请求 |

**随时撤销授权的方法：**
访问 [Google 账号安全设置](https://myaccount.google.com/permissions)，找到您的 OAuth 应用，点击撤销即可。
