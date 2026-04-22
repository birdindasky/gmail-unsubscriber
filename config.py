# -*- coding: utf-8 -*-
"""
Configuration file - whitelist, keywords, and global settings.
All user-adjustable parameters live here so the core logic does not need edits.
"""

import os

# ────────────────────────────────────────────────────────────────
#  Whitelist domains (emails from these senders should never be unsubscribed)
# ────────────────────────────────────────────────────────────────

WHITELIST_DOMAINS = [
    # Banking & finance
    "icbc.com.cn", "ccb.com", "abchina.com", "boc.cn", "bankcomm.com",
    "cmbchina.com", "pingan.com", "alipay.com", "unionpay.com",
    "paypal.com", "chase.com", "bankofamerica.com", "wellsfargo.com",
    "citibank.com", "hsbc.com", "barclays.co.uk",
    "stripe.com", "visa.com", "mastercard.com", "amex.com",
    "dbs.com", "ocbc.com", "uob.com",

    # Google ecosystem
    "google.com", "gmail.com", "googlemail.com", "youtube.com",
    "google.cn", "googleplex.com", "firebase.com", "gcp.google.com",
    "nest.com",

    # Major tech companies
    "apple.com", "microsoft.com", "amazon.com", "amazon.cn",
    "github.com", "gitlab.com", "stackoverflow.com",
    "cloudflare.com", "digitalocean.com", "aws.amazon.com",
    "azure.com", "icloud.com",

    # China tech platforms
    "taobao.com", "tmall.com", "jd.com", "163.com", "126.com",
    "qq.com", "weixin.qq.com", "meituan.com", "dianping.com",

    # Government & public services
    "gov.cn", "gov.com", "gov.sg", "irs.gov", "usa.gov", "hmrc.gov.uk",
    "canada.ca", "iras.gov.sg",

    # Medical & health
    "nih.gov", "cdc.gov", "who.int", "nhc.gov.cn",

    # Education
    "edu.cn", "coursera.org", "edx.org", "khanacademy.org",
    "mit.edu", "stanford.edu", "harvard.edu",

    # Utilities & Singapore telecom
    "electricity.com", "water.com", "gas.com",
    "state.gov", "unitedstates.gov",
    "singtel.com", "starhub.com", "m1.com", "m1.com.sg",
]

# ────────────────────────────────────────────────────────────────
#  Ad keywords (if found in subject/body, the email is more likely to be an ad)
# ────────────────────────────────────────────────────────────────

AD_KEYWORDS = [
    # Chinese promotion keywords
    "限时优惠", "超低折扣", "特价", "秒杀", "抢购", "大促", "双十一",
    "618", "黑五", "清仓", "满减", "返现", "红包", "优惠券", "积分兑换",
    "免费领取", "专属福利", "会员专享", "会员日", "立即抢购", "今日特卖", "爆款",
    "热销", "新品上市", "新品", "买一送一", "折扣", "打折", "降价", "促销",
    "广告", "推广", "营销", "活动", "优惠活动", "精选好物", "好货推荐",

    # English promotion keywords
    "sale", "discount", "offer", "deal", "promo", "promotion",
    "% off", "limited time", "flash sale", "clearance", "free shipping",
    "buy now", "shop now", "exclusive", "special offer", "best price",
    "coupon", "voucher", "cashback", "rewards", "loyalty",
    "newsletter", "unsubscribe", "marketing", "advertisement",
    "sponsored", "partner", "affiliate",
]

# ────────────────────────────────────────────────────────────────
#  Sensitive keywords (if found, never unsubscribe)
# ────────────────────────────────────────────────────────────────

SENSITIVE_KEYWORDS = [
    # Chinese sensitive keywords
    "验证码", "登录", "密码", "账号安全", "异常登录", "支付", "转账",
    "订单", "发货", "快递", "物流", "收货", "退款", "投诉", "售后",
    "合同", "发票", "税务", "社保", "医疗", "就诊", "处方", "检查结果",
    "银行卡", "信用卡", "还款", "账单", "流水", "对账",
    "工资", "薪资", "劳动合同", "录用通知", "面试",
    "学籍", "成绩", "录取通知", "毕业", "学历认证",
    "护照", "签证", "机票", "酒店预订",

    # English sensitive keywords
    "verification", "verify", "otp", "two-factor", "2fa",
    "password", "account", "security alert", "suspicious",
    "payment", "transaction", "invoice", "receipt", "order",
    "shipping", "delivery", "tracking",
    "contract", "agreement", "legal", "court", "lawsuit",
    "medical", "prescription", "diagnosis", "test result",
    "bank statement", "credit card", "billing",
    "salary", "payroll", "employment",
    "admission", "enrollment", "transcript",
    "passport", "visa", "boarding pass", "reservation",
]

# ────────────────────────────────────────────────────────────────
#  Suspicious sender keywords (adds weight when found in sender name/domain)
# ────────────────────────────────────────────────────────────────

SUSPICIOUS_SENDER_KEYWORDS = [
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "newsletter", "promo", "promotion", "marketing",
    "offers", "deals", "sales", "shop", "store",
    "广告", "推广", "营销", "促销", "优惠",
]

# ────────────────────────────────────────────────────────────────
#  Runtime config (whitelist can change at runtime)
# ────────────────────────────────────────────────────────────────

def get_all_whitelist_domains() -> list[str]:
    """Return the combined built-in and user-defined whitelist domains."""
    import database
    try:
        user_domains = database.get_user_whitelist()
    except Exception:
        user_domains = []
    return list(set(WHITELIST_DOMAINS + user_domains))


# ────────────────────────────────────────────────────────────────
#  AI classification config
# ────────────────────────────────────────────────────────────────

# Whether to enable AI-assisted classification (triggered when exactly 1 rule matches)
# Provider / API key / model are stored in user_config.json and managed by the settings menu
USE_AI_CLASSIFIER = True

# Max tokens for AI replies (short JSON only)
AI_MAX_TOKENS = 150

# ────────────────────────────────────────────────────────────────
#  Email category definitions & domain mapping
# ────────────────────────────────────────────────────────────────

EMAIL_CATEGORIES = [
    {"name": "E-commerce", "icon": "🛒"},
    {"name": "Social", "icon": "📱"},
    {"name": "Finance", "icon": "💰"},
    {"name": "Newsletter", "icon": "📰"},
    {"name": "Entertainment", "icon": "🎮"},
    {"name": "Food Delivery", "icon": "🍔"},
    {"name": "Travel", "icon": "✈️"},
    {"name": "Tech Services", "icon": "💻"},
    {"name": "Other", "icon": "📧"},
]

CATEGORY_NAMES = [c["name"] for c in EMAIL_CATEGORIES]
CATEGORY_ICONS = {c["name"]: c["icon"] for c in EMAIL_CATEGORIES}

DOMAIN_TO_CATEGORY = {
    # Shopping
    "taobao.com": "E-commerce", "tmall.com": "E-commerce", "jd.com": "E-commerce",
    "pinduoduo.com": "E-commerce", "amazon.com": "E-commerce", "amazon.cn": "E-commerce",
    "ebay.com": "E-commerce", "shopee.com": "E-commerce", "lazada.com": "E-commerce",
    "aliexpress.com": "E-commerce", "walmart.com": "E-commerce", "target.com": "E-commerce",
    "bestbuy.com": "E-commerce", "etsy.com": "E-commerce", "shein.com": "E-commerce",
    "suning.com": "E-commerce", "dangdang.com": "E-commerce", "vip.com": "E-commerce",
    # Social media
    "linkedin.com": "Social", "facebook.com": "Social", "instagram.com": "Social",
    "twitter.com": "Social", "x.com": "Social", "weibo.com": "Social",
    "tiktok.com": "Social", "douyin.com": "Social", "xiaohongshu.com": "Social",
    "reddit.com": "Social", "discord.com": "Social", "snapchat.com": "Social",
    "pinterest.com": "Social", "quora.com": "Social", "zhihu.com": "Social",
    # Finance
    "eastmoney.com": "Finance", "xueqiu.com": "Finance", "futu.com": "Finance",
    "lufax.com": "Finance", "creditkarma.com": "Finance", "mint.com": "Finance",
    "robinhood.com": "Finance", "coinbase.com": "Finance", "binance.com": "Finance",
    # News
    "36kr.com": "Newsletter", "huxiu.com": "Newsletter", "toutiao.com": "Newsletter",
    "substack.com": "Newsletter", "medium.com": "Newsletter", "nytimes.com": "Newsletter",
    "wsj.com": "Newsletter", "bbc.com": "Newsletter", "cnn.com": "Newsletter",
    "reuters.com": "Newsletter", "bloomberg.com": "Newsletter", "theguardian.com": "Newsletter",
    "sspai.com": "Newsletter", "infoq.cn": "Newsletter",
    # Entertainment
    "steampowered.com": "Entertainment", "epicgames.com": "Entertainment", "ea.com": "Entertainment",
    "blizzard.com": "Entertainment", "playstation.com": "Entertainment", "xbox.com": "Entertainment",
    "netflix.com": "Entertainment", "spotify.com": "Entertainment", "hulu.com": "Entertainment",
    "iqiyi.com": "Entertainment", "bilibili.com": "Entertainment", "youku.com": "Entertainment",
    # Food delivery
    "meituan.com": "Food Delivery", "ele.me": "Food Delivery", "doordash.com": "Food Delivery",
    "ubereats.com": "Food Delivery", "grubhub.com": "Food Delivery", "deliveroo.com": "Food Delivery",
    "starbucks.com": "Food Delivery", "mcdonalds.com": "Food Delivery", "dominos.com": "Food Delivery",
    "grabfood.com": "Food Delivery", "foodpanda.com": "Food Delivery",
    # Travel
    "ctrip.com": "Travel", "booking.com": "Travel", "airbnb.com": "Travel",
    "expedia.com": "Travel", "trip.com": "Travel", "agoda.com": "Travel",
    "skyscanner.com": "Travel", "kayak.com": "Travel", "tripadvisor.com": "Travel",
    "uber.com": "Travel", "lyft.com": "Travel", "didi.com": "Travel",
    "grab.com": "Travel", "klook.com": "Travel",
    # Tech services
    "heroku.com": "Tech Services", "vercel.com": "Tech Services", "netlify.com": "Tech Services",
    "digitalocean.com": "Tech Services", "vultr.com": "Tech Services", "linode.com": "Tech Services",
    "notion.so": "Tech Services", "slack.com": "Tech Services", "atlassian.com": "Tech Services",
    "jetbrains.com": "Tech Services", "figma.com": "Tech Services", "canva.com": "Tech Services",
    "zoom.us": "Tech Services", "dropbox.com": "Tech Services", "grammarly.com": "Tech Services",
    "openai.com": "Tech Services", "anthropic.com": "Tech Services",
}

# ────────────────────────────────────────────────────────────────
#  Database config
# ────────────────────────────────────────────────────────────────

# SQLite database file path
DB_PATH = os.path.join(os.path.dirname(__file__), "gmail-unsubscriber.db")
