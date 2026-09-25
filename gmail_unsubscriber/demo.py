"""Clearly synthetic mailbox for offline onboarding and deterministic UI tests."""
from datetime import datetime, timedelta, timezone


def messages() -> list[dict]:
    sources = [
        ("daily@design-notes.example", "Design Notes", "design.notes.example", "资讯", ["本周值得收藏的 5 个设计灵感", "关于留白，我们可以做得更少"], 12, True),
        ("offers@shop-weekly.example", "周末好物", "offers.shop-weekly.example", "购物", ["本周精选：给生活留一点新鲜", "会员限时优惠，低至 5 折"], 24, True),
        ("news@field-journal.example", "旷野来信", "journal.field-journal.example", "资讯", ["五月，在山野里走走", "从城市到旷野的一封信"], 8, True),
        ("digest@makers.example", "Makers Weekly", "digest.makers.example", "工作与服务", ["这周，大家又做了些什么？", "一些关于创造的小事"], 9, True),
        ("community@social-roundup.example", "社区动态", "digest.social-roundup.example", "社交", ["你关注的社区有新动态", "本周热门讨论"], 18, False),
        ("members@slow-living.example", "慢生活俱乐部", "members.slow-living.example", "其他", ["下周的线下见面会", "一份周末阅读清单"], 6, False),
        ("alerts@google.com", "Google 账号", "account.google.com", "工作与服务", ["你的账号安全提醒", "请确认新的登录活动"], 3, True),
        ("care@health-clinic.example", "健康服务", "care.health-clinic.example", "其他", ["您的检查结果已更新", "预约就诊提醒"], 2, False),
        ("offers@shop-weekly.example", "周末好物 · 家居", "home.shop-weekly.example", "购物", ["让家更舒适的几个选择", "家居季优惠精选"], 7, True),
    ]
    out = []
    now = datetime.now(timezone.utc)
    for s, (sender, title, list_id, category, subjects, count, signed) in enumerate(sources):
        for i in range(count):
            out.append({
                "id": f"{s + 10:x}{i + 1000:x}", "sender_email": sender,
                "sender_name": title, "subject": subjects[i % len(subjects)],
                "snippet": "合成演示邮件，仅用于体验整理流程。", "date": (now - timedelta(days=i % 28)).isoformat(),
                "list_id": list_id, "list_unsubscribe": f"<https://{sender.split('@')[1]}/unsubscribe/{list_id}>",
                "list_unsubscribe_post": "List-Unsubscribe=One-Click" if signed else "",
                "authenticated": signed, "category": category,
            })
    return out


def submit(url: str) -> dict:
    # Never delegates to a network implementation.
    return {"status": "accepted", "detail": "演示：已模拟接受退订请求，没有访问任何网站或真实邮箱。"}
