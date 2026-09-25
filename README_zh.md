# 轻邮 · Gmail Unsubscriber v2

在本机看清 Gmail 里有哪些订阅，保留重要邮件，审阅后再提交退订请求。

当前定位为本机受限试用；对方是否接受退订及以后是否停信尚不能保证。结果待确认的请求不要重复提交。

新版提供完整中文界面：订阅清单、搜索筛选、样本详情、批量预览、域名保护、扫描进度与取消、逐项操作记录。不需要付费 AI，也不上传邮件给模型服务。

## 先体验

macOS 双击 **体验演示.command**，或运行：

```bash
python3 app.py --demo
```

页面会明确显示“演示邮箱”。其中邮件和执行结果是合成数据，不会访问真实 Gmail 或退订网站。命令行演示只需要 Python 3.10+；双击启动器需要先按下文准备项目虚拟环境。

## 连接自己的 Gmail

在项目虚拟环境中安装真实邮箱适配器：

```bash
python3 -m venv .venv-v2
source .venv-v2/bin/activate
python -m pip install -r requirements-v2.lock
```

准备好 Google 桌面 OAuth 客户端文件 `credentials.json` 后，双击 **启动轻邮.command**，或运行 `python app.py --live`。启动后点击连接才会读取凭据并打开 Google 授权；新版只申请读取邮箱的权限。

## 怎样整理

1. 扫描最近30天的促销邮件，先用默认100封上限。
2. 看样本主题与理由，将要保留的域名加入保护。
3. 选择最多20个订阅，查看可提交、需人工处理和被保护的项目。
4. 明确确认计划，逐项查看结果。

一键退订会先检查原始邮件的 DKIM 签名；无法验证的项目打开 Gmail 人工处理。普通网页、登录页与邮件发送成功都不会被直接当作完成退订。**“请求已接受”只是站点回执，不保证以后一定不再发信。**

## 数据与运行边界

- 数据只写入本项目 `.local/v2-demo/` 与 `.local/v2-live/`，两种模式分开保存。
- 新版不自动复用旧 token，不把旧版成功历史直接导入。
- 不发送 Gmail 邮件、不删除或归档邮件；没有自启动、定时任务或后台安装。
- 本机网页仅绑定回环地址，在启动终端按 Control+C 即可停止应用。
- 旧模块保留用于历史对照；`python main.py` 已转到新版入口，旧 `unsubscribe --confirm` 命令不再受支持。

[完整使用说明](docs/V2_USAGE.md) · [新版架构](docs/V2_ARCHITECTURE.md) · [English](README.md)

## 开发验证

```bash
python -m pip install -r requirements-v2-test.lock
python -m pytest tests_v2 -q
```

离线通过只说明本地行为得到验证，不代表退订方已接受请求或以后不会再来信。本机试用记录和私人邮箱数据不上传到公开仓库；已测试依赖版本见[重建说明](docs/V2_REBUILD.md)。

MIT 许可。原项目作者：[birdindasky](https://github.com/birdindasky)。
