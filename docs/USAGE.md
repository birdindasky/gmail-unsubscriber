# Gmail 退订工具 · 使用指南

详细说明请看 [USAGE_GUIDE.md](USAGE_GUIDE.md)。

---

## 激活环境（每次打开终端后运行一次）

```bash
source venv/bin/activate
```

---

## 方式一：交互式菜单（推荐）

```bash
python3 main.py
```

直接运行，不带任何参数，会进入交互式菜单：

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
```

**扫描**：选择 1，按提示输入扫描天数和范围，完成后邮件会按类别分组展示。扫描完成后菜单里「扫描邮件」会显示 ✅ 标记，代表结果已缓存。

**退订**：选择 2，如果上次扫描结果还在，会直接复用，无需重新扫描；也可以选择重新扫一次。按字母选择类别展开，输入编号选择退订的发件人。

---

## 方式二：命令行参数（高级用户）

```bash
# 扫描最近 30 天的促销邮件（只看，不退订）
python3 main.py scan

# 扫描全部历史邮件 + 全部分类（首次深度清理推荐）
python3 main.py scan --days 0 --all

# 试运行退订，预览将要发生什么（不会真的退订）
python3 main.py unsubscribe --dry-run

# 逐个确认执行退订（推荐日常使用）
python3 main.py unsubscribe --confirm

# 自动退订所有建议发件人（不逐个询问）
python3 main.py unsubscribe --confirm --auto

# 退订 + 把旧广告邮件移出收件箱
python3 main.py unsubscribe --confirm --archive

# 把某个域名加入白名单（不再被退订）
python3 main.py whitelist add 某公司.com

# 查看退订历史
python3 main.py history

# 查看日志（排查问题用）
python3 main.py logs
```

---

## AI 模型配置

工具支持两种 AI 提供商，用于辅助判断模糊邮件和自动分类发件人类别：

### MiniMax（默认）

```bash
export MINIMAX_API_KEY="你的MiniMax API Key"
```

### Anthropic Claude

```bash
export AI_PROVIDER=anthropic
export ANTHROPIC_API_KEY="你的Anthropic API Key"
```

永久生效建议写入 `~/.zshrc`。交互菜单「5. 设置」可查看当前 AI 配置状态。

**AI 调用是缓存的**：同一个发件人邮箱只会调用一次 AI，结果在本次运行内复用，避免对同一域名的 100 封邮件做 100 次 AI 请求。

---

## 首次深度清理流程

### 交互模式

1. 运行 `python3 main.py`
2. 选择 1 扫描，天数输入 0，范围选全部
3. 查看分类结果，把不想退订的加白名单（选择 4）
4. 选择 2 退订，按类别选择退订

### 命令行模式

```bash
# 1. 扫描，看看有哪些广告发件人
python3 main.py scan --days 0 --all

# 2. 把不想退订的加白名单
python3 main.py whitelist add 某公司.com

# 3. 试运行，确认无误
python3 main.py unsubscribe --dry-run --days 0 --all

# 4. 正式执行退订
python3 main.py unsubscribe --confirm --days 0 --all
```

---

## 关键说明

- 直接运行 `python3 main.py`（无参数）进入交互式菜单
- `scan` 只扫描，**不退订**；`unsubscribe` 内部会自己扫描
- `--days 0` 表示扫全部历史邮件（无时间限制），邮件多时需要等待
- `--all` 扫全部分类，默认只扫 Gmail 的促销标签
- `--auto` 必须配合 `--confirm` 一起使用
- 退订后旧邮件仍在收件箱，加 `--archive` 可以顺手移走
- 扫描结果自动按邮件类别分组（电商、新闻、社交等）
