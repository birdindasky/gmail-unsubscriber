# Gmail 智能退订器

自动识别并退订 Gmail 中的商业广告邮件，同时安全跳过重要邮件（银行、政府、医疗、工作等）。

## 🛡️ 安全特性

- **白名单优先**：银行、Google、政府、医疗等重要发件人一律跳过
- **默认 dry-run**：所有操作先预览再执行，不会误退订
- **不删除邮件**：只退订，不动收件箱
- **逐个确认**：默认逐个确认每个发件人

## 🚀 3 步快速启动

```bash
# 1. 克隆项目
cd /path/to/gmail-unsubscriber

# 2. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 获取 Google OAuth 凭证
# 参考 docs/USAGE.md 完成 Google Cloud Console 配置
# 将 credentials.json 放入项目根目录

# 4. 首次运行（会弹出浏览器授权）
python3 main.py scan
```

## 📖 文档

- [快速上手指南](./docs/USAGE.md) - 详细使用说明
- [架构设计](./docs/ARCHITECTURE.md) - 设计与思路
- [文件说明](./docs/FILE_OVERVIEW.md) - 代码结构

## ⚠️ 安全提示

1. **默认是预览模式**：`--dry-run` 不会真正退订
2. **白名单机制**：重要邮件不会被退订
3. **不删除任何邮件**：退订和删除是独立操作
4. **OAuth 安全**：使用 Gmail API 而非 IMAP 密码

## 📋 推荐使用流程

1. `python3 main.py scan` - 查看检测到的广告邮件
2. 检查白名单是否漏了重要发件人
3. `python3 main.py unsubscribe --dry-run` - 预览模拟
4. `python3 main.py unsubscribe --confirm` - 逐个确认执行
5. 几天后再 `scan` 一次看效果
