# 使用指南

本文档详细介绍从零开始配置并运行 Gmail 退订工具的完整步骤。

---

## 第一步：macOS 环境准备

### 1.1 安装 Python 3

打开终端（Terminal），检查 Python 版本：

```bash
python3 --version
```

如果显示 `Python 3.10` 或更高版本，可以跳过此步骤。

如果未安装，推荐通过 Homebrew 安装：

```bash
# 先安装 Homebrew（如果还没有）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 再安装 Python
brew install python3
```

### 1.2 下载项目并创建虚拟环境

```bash
# 进入项目目录
cd /path/to/gmail-unsubscriber

# 创建虚拟环境（把依赖装在一个隔离的小盒子里，不污染系统）
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装项目依赖
pip install -r requirements.txt
```

安装完成后，命令行前面会显示 `(venv)` 字样，表示虚拟环境已激活。

> **提示：** 每次打开新的终端窗口后，都需要重新运行 `source venv/bin/activate` 来激活虚拟环境。

---

## 第二步：Google Cloud Console 配置

这一步的目的是让你的程序获得访问 Gmail 的「官方通行证」。大约需要 10 分钟。

### 2.1 创建 Google Cloud 项目

1. 在浏览器中打开 [Google Cloud Console](https://console.cloud.google.com/)
2. 点击顶部的项目选择器（可能显示为 "选择项目" 或当前项目名）
3. 点击 **新建项目**
4. 项目名称填写：`gmail-unsubscriber`（随便填，只是方便自己识别）
5. 点击 **创建**

### 2.2 启用 Gmail API

1. 在左侧菜单找到 **API 和服务 → 库**
2. 搜索框中输入 `Gmail API`
3. 点击 **Gmail API**，然后点击 **启用**

### 2.3 配置 OAuth 同意屏幕

1. 在左侧菜单找到 **API 和服务 → OAuth 同意屏幕**
2. 选择 **外部**，点击 **创建**
3. 填写必填项：
   - 应用名称：`Gmail 退订工具`（随便填）
   - 用户支持电子邮件：选择你的 Gmail 地址
   - 开发者联系信息：填写你的 Gmail 地址
4. 点击 **保存并继续**
5. 在「范围」页面，直接点击 **保存并继续**
6. 在「测试用户」页面，点击 **添加用户**，输入你的 Gmail 地址，点击 **保存并继续**
7. 最后点击 **返回信息中心**

### 2.4 创建 OAuth 客户端 ID

1. 在左侧菜单找到 **API 和服务 → 凭据**
2. 点击顶部 **创建凭据 → OAuth 客户端 ID**
3. 应用类型选择：**桌面应用**
4. 名称填写：`gmail-unsubscriber-desktop`（随便填）
5. 点击 **创建**

### 2.5 下载凭据文件

1. 在弹出的对话框中，点击 **下载 JSON**
2. 将下载的文件**重命名为 `credentials.json`**
3. 将 `credentials.json` 移动到项目根目录（与 `main.py` 同一层）：

```
gmail-unsubscriber/
├── credentials.json   ← 放这里
├── main.py
└── ...
```

> ⚠️ **重要安全提示：**
> - `credentials.json` 是你访问 Google 服务的凭据，绝对不要上传到 GitHub 或分享给他人
> - 该文件已被加入 `.gitignore`，正常操作下不会被 git 追踪
> - 如果不小心泄露，请立即在 Google Cloud Console 中删除该凭据并重新创建

---

## 第三步：首次运行（OAuth 授权）

配置完成后，第一次运行程序时需要完成 OAuth 授权：

```bash
# 确保虚拟环境已激活
source venv/bin/activate

# 运行扫描命令（任意命令都会触发授权）
python main.py scan
```

程序会自动在浏览器中打开 Google 登录页面：

1. 选择你的 Google 账号
2. 可能会看到「此应用未经 Google 验证」的警告 — 这是正常的，因为是你自己创建的应用
   - 点击 **高级**
   - 点击 **前往 gmail-退订工具（不安全）**（这里的「不安全」只是 Google 的措辞，因为应用未提交审核）
3. 勾选所有权限，点击 **继续**
4. 授权成功后，浏览器会显示「The authentication flow has completed」
5. 回到终端，程序会继续运行

> **后续运行无需重复授权。** 授权信息保存在 `token.json` 中，程序会自动使用。

---

## 命令行使用说明

### 扫描邮件

```bash
# 扫描最近 30 天（默认）
python main.py scan

# 扫描最近 60 天
python main.py scan --days 60

# 扫描最近 7 天
python main.py scan --days 7
```

输出示例：
```
📬 正在扫描最近 30 天的邮件...
   共找到 342 封邮件，正在解析详情...

📊 扫描报告
   总邮件数：342
   建议退订发件人数：8
   已跳过邮件数（白名单/敏感）：189

──────────────────────────────────────────────────────────
  建议退订的发件人列表：
──────────────────────────────────────────────────────────

  [1] 某购物平台 <promo@shop-example.com>
      邮箱：promo@shop-example.com
      邮件数量：23 封
      判定依据：含广告关键词：限时优惠, 大促, 秒杀；含 List-Unsubscribe 头部
      邮件主题示例：
        · 双十一大促！全场5折起，限时24小时！
        · 您的专属优惠券已到账，立即领取
      支持 List-Unsubscribe：✓
```

### 预览退订（试运行）

```bash
python main.py unsubscribe --dry-run
```

试运行不会实际发送任何退订请求，只是告诉你「如果真的执行，会怎样」。**建议第一次使用时先跑试运行。**

### 逐个确认退订

```bash
python main.py unsubscribe --confirm
```

程序会对每个发件人询问你是否退订：
```
[1/8] 某购物平台 <promo@shop-example.com>
         邮箱：promo@shop-example.com  |  邮件数：23 封

         退订这个发件人？[y/n/q（退出）] y
         ✅ 退订成功：一键退订请求已发送（HTTP 200）

[2/8] 某资讯平台 <news@info-example.com>
         邮箱：news@info-example.com  |  邮件数：15 封

         退订这个发件人？[y/n/q（退出）] n
         ⏭️  跳过 news@info-example.com
```

按 `q` 可以随时退出。

### 自动退订全部

```bash
python main.py unsubscribe --confirm --auto
```

不询问，自动对所有建议退订的发件人执行退订。**建议先用 `--dry-run` 确认过一遍再使用此模式。**

### 管理白名单

```bash
# 查看白名单
python main.py whitelist list

# 添加域名到白名单（此后来自该域名的邮件将不会被分析为广告）
python main.py whitelist add taobao.com
python main.py whitelist add yourcompany.com
```

### 查看日志

```bash
python main.py logs
```

---

## 推荐工作流程

**第一次使用：**
```bash
# 1. 先扫描，了解情况
python main.py scan --days 30

# 2. 试运行退订，看看程序打算怎么做
python main.py unsubscribe --dry-run

# 3. 如果有不想退订的，先加白名单
python main.py whitelist add 某域名.com

# 4. 逐个确认执行退订
python main.py unsubscribe --confirm
```

**日常维护（每月一次）：**
```bash
python main.py unsubscribe --confirm --auto
```

---

## 常见问题（FAQ）

### Q：运行时出现「找不到 credentials.json」？

**A：** 请按照「第二步」配置 Google Cloud Console，并将下载的 JSON 文件重命名为 `credentials.json` 放到项目根目录。

### Q：浏览器授权后，终端没有反应？

**A：** 等待几秒钟。如果一直没反应，关闭浏览器窗口，回到终端按 `Ctrl+C`，然后重新运行命令。

### Q：出现「此应用未经 Google 验证」警告怎么办？

**A：** 这是正常现象。你自己创建的应用没有经过 Google 官方审核，所以会显示此警告。点击「高级」→「前往（不安全）」即可继续。你的数据只会在你的电脑和你的 Google 账号之间传输，不会经过任何第三方服务器。

### Q：退订后对方还在发邮件怎么办？

**A：** 退订请求已发送，但有些发件人处理退订请求需要 1-10 个工作日。如果超过 2 周还在收，可以直接在 Gmail 中点击「举报垃圾邮件」。

### Q：我不想退订某个发件人，但程序每次都分析它怎么办？

**A：** 将其域名加入白名单：
```bash
python main.py whitelist add 该发件人的域名.com
```
之后扫描时该发件人会被自动跳过。

### Q：程序会删除我的邮件吗？

**A：** 不会。程序只会向对方的退订接口发送请求，告知「请停止向此邮箱发送邮件」。您邮箱中已有的邮件不会有任何变动。

### Q：token.json 是什么？可以删吗？

**A：** `token.json` 是 OAuth 授权令牌的缓存文件，用于避免每次运行都需要重新登录。可以删除，删除后下次运行会再次打开浏览器要求授权，正常重新授权即可。

### Q：可以用于多个 Gmail 账号吗？

**A：** 目前每个项目目录只支持一个账号（一个 `token.json`）。如需管理多个账号，可以为每个账号复制一份项目目录，分别完成授权。

### Q：`--verbose` 参数有什么用？

**A：** 加上 `--verbose` 后，程序会在控制台输出详细的调试信息（默认只写入日志文件）。
```bash
python main.py --verbose scan
```

---

## 权限说明

本工具申请的 Gmail 权限为 `gmail.modify`，该权限允许：
- ✅ 读取邮件内容和头部信息
- ✅ 修改邮件标签（如已读/未读）
- ❌ 永久删除邮件（需要 `gmail.readonly` 或 `mail.google.com` 权限才能删除）

选择 `gmail.modify` 而非更高权限（如完整访问），是出于「最小权限原则」——程序只申请完成任务所必需的权限。
