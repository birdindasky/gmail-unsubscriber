#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail 自动退订工具 - 主入口
用法：python main.py <命令> [选项]

命令：
  scan              扫描邮件（不执行退订）
  unsubscribe       执行退订
  history           查看退订历史
  whitelist         管理白名单
  logs              查看日志

示例：
  python main.py scan --days 30
  python main.py scan --all --no-ai
  python main.py unsubscribe --dry-run
  python main.py unsubscribe --confirm
  python main.py unsubscribe --confirm --auto
  python main.py unsubscribe --confirm --archive
  python main.py history
  python main.py history --limit 20
  python main.py whitelist add example.com
  python main.py whitelist list
  python main.py logs
"""

import argparse
import logging
import os
import sys
from datetime import datetime

import auth
import classifier
import config
import database
import scanner
import unsubscriber

# ────────────────────────────────────────────────────────────────
#  日志配置
# ────────────────────────────────────────────────────────────────

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, f"gmail-unsubscriber-{datetime.now().strftime('%Y%m%d')}.log")


def setup_logging(verbose: bool = False) -> None:
    """初始化日志系统，同时输出到控制台和文件。"""
    os.makedirs(LOG_DIR, exist_ok=True)

    level = logging.DEBUG if verbose else logging.INFO

    # 根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 移除已有的 handler（避免重复）
    root_logger.handlers.clear()

    # 文件 handler（详细格式）
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root_logger.addHandler(file_handler)

    # 控制台 handler（简洁格式，仅警告以上）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING if not verbose else logging.DEBUG)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger.addHandler(console_handler)


logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
#  命令：scan
# ────────────────────────────────────────────────────────────────

def cmd_scan(args: argparse.Namespace) -> None:
    """扫描邮件并展示分析结果（不执行退订）。"""
    print("=" * 60)
    print("  Gmail 广告邮件扫描器")
    print("=" * 60)

    service = auth.get_gmail_service()
    use_ai = not args.no_ai
    emails = scanner.scan_emails(service, days=args.days, scan_all=args.all)

    if not emails:
        print("📭 最近邮件为空或扫描结果为零。")
        return

    result = classifier.classify_emails(emails, use_ai=use_ai)
    to_unsub = result["to_unsubscribe"]
    skipped = result["skipped"]

    # 记录本次扫描
    database.record_scan(
        days=args.days,
        total_emails=len(emails),
        candidates=len(to_unsub),
        unsubscribed=0,
    )

    print(f"\n📊 扫描报告")
    print(f"   总邮件数：{len(emails)}")
    print(f"   建议退订发件人数：{len(to_unsub)}")
    print(f"   已跳过邮件数（白名单/敏感）：{skipped}")
    print()

    if not to_unsub:
        print("✅ 未发现需要退订的广告邮件。")
        return

    print("─" * 60)
    print("  建议退订的发件人列表：")
    print("─" * 60)

    for i, group in enumerate(to_unsub, 1):
        print(f"\n  [{i}] {group['sender']}")
        print(f"      邮箱：{group['sender_email']}")
        print(f"      邮件数量：{group['count']} 封")
        print(f"      判定依据：{group['reasons'][0] if group['reasons'] else '无'}")
        if group.get("sample_subjects"):
            print(f"      邮件主题示例：")
            for s in group["sample_subjects"][:3]:
                print(f"        · {s[:60]}{'...' if len(s) > 60 else ''}")
        has_unsub = "✓" if group.get("list_unsubscribe") else "✗"
        print(f"      支持 List-Unsubscribe：{has_unsub}")

    print()
    print("─" * 60)
    print(f"  运行 'python main.py unsubscribe --dry-run' 预览退订操作")
    print(f"  运行 'python main.py unsubscribe --confirm' 开始退订")
    print("─" * 60)

    logger.info(f"扫描完成：{len(to_unsub)} 个发件人建议退订，{skipped} 封邮件已跳过")


# ────────────────────────────────────────────────────────────────
#  命令：unsubscribe
# ────────────────────────────────────────────────────────────────

def cmd_unsubscribe(args: argparse.Namespace) -> None:
    """执行退订操作。"""
    dry_run = args.dry_run
    confirm_mode = args.confirm
    auto_mode = args.auto
    archive = getattr(args, "archive", False)
    use_ai = not getattr(args, "no_ai", False)

    if auto_mode and not confirm_mode:
        print("❌ --auto 必须配合 --confirm 使用。示例：python main.py unsubscribe --confirm --auto")
        sys.exit(1)

    if dry_run:
        print("=" * 60)
        print("  Gmail 退订工具 - 试运行模式（不会实际执行退订）")
        print("=" * 60)
    elif confirm_mode:
        mode_desc = "自动确认" if auto_mode else "逐个确认"
        print("=" * 60)
        print(f"  Gmail 退订工具 - {mode_desc}模式{'（退订后归档）' if archive else ''}")
        print("=" * 60)
        if not auto_mode:
            print("\n⚠️  注意：即将对以下发件人执行退订操作。")
            print("   退订后，对方将停止向您发送邮件。\n")

    days = getattr(args, "days", 30)
    scan_all = getattr(args, "all", False)
    service = auth.get_gmail_service()
    emails = scanner.scan_emails(service, days=days, scan_all=scan_all)

    if not emails:
        print("📭 未找到邮件。")
        return

    result = classifier.classify_emails(emails, use_ai=use_ai)
    to_unsub = result["to_unsubscribe"]

    if not to_unsub:
        print("✅ 未发现需要退订的广告邮件。")
        return

    print(f"\n📋 找到 {len(to_unsub)} 个建议退订的发件人\n")

    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, group in enumerate(to_unsub, 1):
        sender_email = group["sender_email"]
        sender_display = group.get("sender", sender_email)
        count = group["count"]

        print(f"[{i}/{len(to_unsub)}] {sender_display}")
        print(f"         邮箱：{sender_email}  |  邮件数：{count} 封")
        if group.get("reasons"):
            print(f"         原因：{group['reasons'][0]}")

        if confirm_mode and not auto_mode:
            user_skipped = False
            while True:
                answer = input(f"\n         退订这个发件人？[y/n/q（退出）] ").strip().lower()
                if answer in ("y", "yes", "是"):
                    break
                elif answer in ("n", "no", "否"):
                    print(f"         ⏭️  跳过 {sender_email}")
                    skip_count += 1
                    print()
                    user_skipped = True
                    break
                elif answer in ("q", "quit", "exit"):
                    print("\n用户退出，已停止退订。")
                    _print_summary(success_count, skip_count, fail_count)
                    return
                else:
                    print("         请输入 y（退订）、n（跳过）或 q（退出）")
            if user_skipped:
                continue

        exec_result = unsubscriber.execute_unsubscribe(
            group, service=service, dry_run=dry_run, archive=archive
        )

        if dry_run:
            methods = exec_result.get("details", {}).get("available_methods", [])
            if methods:
                print(f"         🔍 [试运行] 发现退订方式：")
                for m in methods:
                    print(f"              {m}")
            else:
                print(f"         ⚠️  [试运行] 未发现退订方式")
        elif exec_result["success"]:
            print(f"         ✅ 退订成功：{exec_result['message']}")
            success_count += 1
            database.record_unsubscribe(
                sender_email=sender_email,
                sender_name=sender_display,
                method=exec_result.get("attempted_method", "unknown"),
                success=True,
            )
        else:
            print(f"         ❌ 退订失败：{exec_result['message']}")
            fail_count += 1

        print()

    if not dry_run:
        _print_summary(success_count, skip_count, fail_count)
        database.record_scan(
            days=days,
            total_emails=len(emails),
            candidates=len(to_unsub),
            unsubscribed=success_count,
        )

    logger.info(f"退订任务完成：成功={success_count}，跳过={skip_count}，失败={fail_count}")


def _print_summary(success: int, skipped: int, failed: int) -> None:
    """打印退订操作汇总。"""
    print()
    print("─" * 60)
    print("  退订操作汇总")
    print("─" * 60)
    print(f"  ✅ 成功退订：{success} 个发件人")
    print(f"  ⏭️  已跳过：{skipped} 个发件人")
    print(f"  ❌ 退订失败：{failed} 个发件人")
    print("─" * 60)
    if failed > 0:
        print("  提示：退订失败通常是因为对方不支持自动退订。")
        print("  您可以手动打开邮件，点击邮件底部的退订链接。")
    print()


# ────────────────────────────────────────────────────────────────
#  命令：history
# ────────────────────────────────────────────────────────────────

def cmd_history(args: argparse.Namespace) -> None:
    """查看历史退订记录。"""
    limit = getattr(args, "limit", 50)
    history = database.get_history(limit=limit)

    if not history:
        print("📭 暂无退订历史记录。")
        print("   运行 'python main.py unsubscribe --confirm' 开始退订。")
        return

    print(f"\n📋 退订历史记录（共 {len(history)} 条，最近 {limit} 条）")
    print("─" * 60)

    method_labels = {
        "one_click_post": "一键退订（POST）",
        "http_get": "HTTP 链接退订",
        "mailto": "退订邮件发送",
        "link_click": "正文链接退订",
        "failed": "退订失败",
        "unknown": "未知方式",
    }

    for i, record in enumerate(history, 1):
        status = "✅" if record["success"] else "❌"
        method = method_labels.get(record.get("method", ""), record.get("method", ""))
        ts = record["unsubscribed_at"][:16].replace("T", " ")
        print(f"\n  [{i}] {record.get('sender_name', record['sender_email'])}")
        print(f"      邮箱：{record['sender_email']}")
        print(f"      时间：{ts}  方式：{method}  {status}")

    print()
    print("─" * 60)


# ────────────────────────────────────────────────────────────────
#  命令：whitelist
# ────────────────────────────────────────────────────────────────

def cmd_whitelist(args: argparse.Namespace) -> None:
    """管理用户自定义白名单。"""
    if args.whitelist_action == "add":
        domain = args.domain.lower().strip()
        if domain in config.WHITELIST_DOMAINS:
            print(f"ℹ️  '{domain}' 已在内置白名单中，无需重复添加。")
            return
        success = database.add_to_user_whitelist(domain)
        if success:
            print(f"✅ 已将 '{domain}' 加入白名单")
            print(f"   来自此域名的邮件将不会被退订。")
            logger.info(f"白名单新增：{domain}")
        else:
            print(f"ℹ️  '{domain}' 已在用户白名单中，无需重复添加。")

    elif args.whitelist_action == "list":
        user_domains = database.get_user_whitelist()
        builtin_count = len(config.WHITELIST_DOMAINS)

        print(f"\n📋 白名单概览")
        print(f"   内置域名数：{builtin_count} 个（银行、Google、科技公司、政府、医疗、教育等）")
        print(f"   用户自定义：{len(user_domains)} 个\n")

        if user_domains:
            print("  用户自定义白名单：")
            for d in sorted(user_domains):
                print(f"    · {d}")
        else:
            print("  用户自定义白名单：（空）")
            print("  使用 'python main.py whitelist add <域名>' 添加")

        print()
        print("  内置白名单类别（部分示例）：")
        categories = {
            "银行 & 金融": ["icbc.com.cn", "paypal.com", "alipay.com"],
            "Google 全家桶": ["google.com", "gmail.com", "youtube.com"],
            "科技公司": ["apple.com", "microsoft.com", "github.com"],
            "政府机构": ["gov.cn", "gov.com"],
            "教育机构": ["edu", "edu.cn", "coursera.org"],
        }
        for cat, examples in categories.items():
            print(f"    {cat}：{', '.join(examples)}")
        print()


# ────────────────────────────────────────────────────────────────
#  命令：logs
# ────────────────────────────────────────────────────────────────

def cmd_logs(args: argparse.Namespace) -> None:
    """查看日志文件列表和最新日志内容。"""
    if not os.path.exists(LOG_DIR):
        print("📁 日志目录不存在，还未生成任何日志。")
        return

    log_files = sorted(
        [f for f in os.listdir(LOG_DIR) if f.endswith(".log")],
        reverse=True
    )

    if not log_files:
        print("📭 暂无日志文件。")
        return

    print(f"\n📁 日志目录：{LOG_DIR}\n")
    print("  日志文件列表：")
    for f in log_files[:10]:
        fpath = os.path.join(LOG_DIR, f)
        size = os.path.getsize(fpath)
        print(f"    · {f}  ({size // 1024} KB)")

    # 显示最新日志的最后 50 行
    latest = os.path.join(LOG_DIR, log_files[0])
    print(f"\n  最新日志（{log_files[0]}）最后 50 行：")
    print("─" * 60)
    try:
        with open(latest, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-50:]:
                print(f"  {line.rstrip()}")
    except IOError as e:
        print(f"  无法读取日志：{e}")
    print("─" * 60)


# ────────────────────────────────────────────────────────────────
#  CLI 参数定义
# ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="gmail-unsubscriber",
        description="Gmail 广告邮件自动退订工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  %(prog)s scan                              扫描最近 30 天促销邮件
  %(prog)s scan --days 60 --all             扫描最近 60 天全部邮件
  %(prog)s scan --no-ai                     不使用 AI 辅助判断
  %(prog)s unsubscribe --dry-run            预览将要退订的发件人
  %(prog)s unsubscribe --confirm            逐个确认执行退订
  %(prog)s unsubscribe --confirm --auto     自动退订所有建议发件人
  %(prog)s unsubscribe --confirm --archive  退订并归档旧邮件
  %(prog)s history                          查看退订历史
  %(prog)s whitelist add taobao.com         加入白名单
  %(prog)s whitelist list                   查看白名单
  %(prog)s logs                             查看运行日志
        """,
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细调试日志")

    subparsers = parser.add_subparsers(dest="command", metavar="命令")
    subparsers.required = True

    # ── scan ──
    scan_parser = subparsers.add_parser("scan", help="扫描邮件，分析广告发件人")
    scan_parser.add_argument("--days", "-d", type=int, default=30, metavar="N",
                             help="扫描最近 N 天的邮件（默认：30；0 = 不限时间扫全部）")
    scan_parser.add_argument("--all", action="store_true",
                             help="扫描全部邮件（默认只扫促销标签）")
    scan_parser.add_argument("--no-ai", action="store_true", dest="no_ai",
                             help="不使用 Claude AI 辅助判断")
    scan_parser.set_defaults(func=cmd_scan)

    # ── unsubscribe ──
    unsub_parser = subparsers.add_parser("unsubscribe", help="执行退订操作")
    unsub_parser.add_argument("--days", "-d", type=int, default=30, metavar="N",
                              help="扫描最近 N 天的邮件（默认：30）")
    unsub_parser.add_argument("--all", action="store_true",
                              help="扫描全部邮件（默认只扫促销标签）")
    unsub_parser.add_argument("--no-ai", action="store_true", dest="no_ai",
                              help="不使用 Claude AI 辅助判断")
    unsub_parser.add_argument("--archive", action="store_true",
                              help="退订成功后归档该发件人的旧邮件")
    unsub_mode = unsub_parser.add_mutually_exclusive_group(required=True)
    unsub_mode.add_argument("--dry-run", action="store_true", dest="dry_run",
                            help="试运行：展示将要退订的发件人，不实际执行")
    unsub_mode.add_argument("--confirm", action="store_true", dest="confirm",
                            help="确认模式：逐个询问用户")
    unsub_parser.add_argument("--auto", action="store_true",
                              help="自动确认所有退订（需配合 --confirm）")
    unsub_parser.set_defaults(func=cmd_unsubscribe)

    # ── history ──
    history_parser = subparsers.add_parser("history", help="查看退订历史记录")
    history_parser.add_argument("--limit", type=int, default=50, metavar="N",
                                help="显示最近 N 条记录（默认：50）")
    history_parser.set_defaults(func=cmd_history)

    # ── whitelist ──
    wl_parser = subparsers.add_parser("whitelist", help="管理白名单域名")
    wl_sub = wl_parser.add_subparsers(dest="whitelist_action", metavar="操作")
    wl_sub.required = True
    wl_add = wl_sub.add_parser("add", help="添加域名到白名单")
    wl_add.add_argument("domain", help="要加入白名单的域名，如 example.com")
    wl_sub.add_parser("list", help="查看当前白名单")
    wl_parser.set_defaults(func=cmd_whitelist)

    # ── logs ──
    logs_parser = subparsers.add_parser("logs", help="查看运行日志")
    logs_parser.set_defaults(func=cmd_logs)

    return parser


# ────────────────────────────────────────────────────────────────
#  主入口
# ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    database.init_db()
    logger.info(f"启动命令：{' '.join(sys.argv)}")

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n\n用户中断，程序退出。")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"程序异常退出：{e}")
        print(f"\n❌ 程序遇到未预期的错误：{e}")
        print(f"   详细信息请查看日志：{LOG_FILE}")
        sys.exit(1)


if __name__ == "__main__":
    main()
