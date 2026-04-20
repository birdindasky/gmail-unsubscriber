# -*- coding: utf-8 -*-
"""
配置文件 - 白名单、关键词和全局设置
所有可自定义的参数集中在这里，方便用户调整而不需要改动核心逻辑。
"""

import os

# ────────────────────────────────────────────────────────────────
#  白名单域名（这些发件人的邮件绝对不会被退订）
# ────────────────────────────────────────────────────────────────

WHITELIST_DOMAINS = [
    # 银行 & 金融
    "icbc.com.cn", "ccb.com", "abchina.com", "boc.cn", "bankcomm.com",
    "cmbchina.com", "pingan.com", "alipay.com", "unionpay.com",
    "paypal.com", "chase.com", "bankofamerica.com", "wellsfargo.com",
    "citibank.com", "hsbc.com", "barclays.co.uk",
    "stripe.com", "visa.com", "mastercard.com", "amex.com",
    "dbs.com", "ocbc.com", "uob.com",

    # Google 全家桶
    "google.com", "gmail.com", "googlemail.com", "youtube.com",
    "google.cn", "googleplex.com", "firebase.com", "gcp.google.com",
    "nest.com",

    # 主要科技公司
    "apple.com", "microsoft.com", "amazon.com", "amazon.cn",
    "github.com", "gitlab.com", "stackoverflow.com",
    "cloudflare.com", "digitalocean.com", "aws.amazon.com",
    "azure.com", "icloud.com",

    # 中国科技平台
    "taobao.com", "tmall.com", "jd.com", "163.com", "126.com",
    "qq.com", "weixin.qq.com", "meituan.com", "dianping.com",

    # 政府 & 公共服务
    "gov.cn", "gov.com", "gov.sg", "irs.gov", "usa.gov", "hmrc.gov.uk",
    "canada.ca", "iras.gov.sg",

    # 医疗 & 健康
    "nih.gov", "cdc.gov", "who.int", "nhc.gov.cn",

    # 教育
    "edu.cn", "coursera.org", "edx.org", "khanacademy.org",
    "mit.edu", "stanford.edu", "harvard.edu",

    # 公共事业 & 新加坡电信
    "electricity.com", "water.com", "gas.com",
    "state.gov", "unitedstates.gov",
    "singtel.com", "starhub.com", "m1.com", "m1.com.sg",
]

# ────────────────────────────────────────────────────────────────
#  广告关键词（邮件主题/内容含这些词语时，倾向于认定为广告）
# ────────────────────────────────────────────────────────────────

AD_KEYWORDS = [
    # 中文促销词
    "限时优惠", "超低折扣", "特价", "秒杀", "抢购", "大促", "双十一",
    "618", "黑五", "清仓", "满减", "返现", "红包", "优惠券", "积分兑换",
    "免费领取", "专属福利", "会员专享", "会员日", "立即抢购", "今日特卖", "爆款",
    "热销", "新品上市", "新品", "买一送一", "折扣", "打折", "降价", "促销",
    "广告", "推广", "营销", "活动", "优惠活动", "精选好物", "好货推荐",

    # 英文促销词
    "sale", "discount", "offer", "deal", "promo", "promotion",
    "% off", "limited time", "flash sale", "clearance", "free shipping",
    "buy now", "shop now", "exclusive", "special offer", "best price",
    "coupon", "voucher", "cashback", "rewards", "loyalty",
    "newsletter", "unsubscribe", "marketing", "advertisement",
    "sponsored", "partner", "affiliate",
]

# ────────────────────────────────────────────────────────────────
#  敏感关键词（含这些词语时，绝对不退订）
# ────────────────────────────────────────────────────────────────

SENSITIVE_KEYWORDS = [
    # 中文敏感词
    "验证码", "登录", "密码", "账号安全", "异常登录", "支付", "转账",
    "订单", "发货", "快递", "物流", "收货", "退款", "投诉", "售后",
    "合同", "发票", "税务", "社保", "医疗", "就诊", "处方", "检查结果",
    "银行卡", "信用卡", "还款", "账单", "流水", "对账",
    "工资", "薪资", "劳动合同", "录用通知", "面试",
    "学籍", "成绩", "录取通知", "毕业", "学历认证",
    "护照", "签证", "机票", "酒店预订",

    # 英文敏感词
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
#  可疑发件人关键词（发件人域名/名称含这些时，加分认定为广告）
# ────────────────────────────────────────────────────────────────

SUSPICIOUS_SENDER_KEYWORDS = [
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "newsletter", "promo", "promotion", "marketing",
    "offers", "deals", "sales", "shop", "store",
    "广告", "推广", "营销", "促销", "优惠",
]

# ────────────────────────────────────────────────────────────────
#  运行时配置（运行时可动态修改白名单）
# ────────────────────────────────────────────────────────────────

def get_all_whitelist_domains() -> list[str]:
    """返回内置白名单 + 用户自定义白名单（SQLite）的合集。"""
    import database
    try:
        user_domains = database.get_user_whitelist()
    except Exception:
        user_domains = []
    return list(set(WHITELIST_DOMAINS + user_domains))


# ────────────────────────────────────────────────────────────────
#  AI 分类配置
# ────────────────────────────────────────────────────────────────

# 是否启用 AI 辅助分类（关键词命中 1 条时触发）
# 提供商 / API Key / 模型等存储在 user_config.json，由交互式设置菜单管理
USE_AI_CLASSIFIER = True

# AI 回复的最大 token 数（只需简短 JSON）
AI_MAX_TOKENS = 150

# ────────────────────────────────────────────────────────────────
#  邮件类别定义 & 域名映射
# ────────────────────────────────────────────────────────────────

EMAIL_CATEGORIES = [
    {"name": "电商购物", "icon": "🛒"},
    {"name": "社交媒体", "icon": "📱"},
    {"name": "金融理财", "icon": "💰"},
    {"name": "新闻资讯", "icon": "📰"},
    {"name": "娱乐游戏", "icon": "🎮"},
    {"name": "餐饮外卖", "icon": "🍔"},
    {"name": "旅行出行", "icon": "✈️"},
    {"name": "科技服务", "icon": "💻"},
    {"name": "其他", "icon": "📧"},
]

CATEGORY_NAMES = [c["name"] for c in EMAIL_CATEGORIES]
CATEGORY_ICONS = {c["name"]: c["icon"] for c in EMAIL_CATEGORIES}

DOMAIN_TO_CATEGORY = {
    # 电商购物
    "taobao.com": "电商购物", "tmall.com": "电商购物", "jd.com": "电商购物",
    "pinduoduo.com": "电商购物", "amazon.com": "电商购物", "amazon.cn": "电商购物",
    "ebay.com": "电商购物", "shopee.com": "电商购物", "lazada.com": "电商购物",
    "aliexpress.com": "电商购物", "walmart.com": "电商购物", "target.com": "电商购物",
    "bestbuy.com": "电商购物", "etsy.com": "电商购物", "shein.com": "电商购物",
    "suning.com": "电商购物", "dangdang.com": "电商购物", "vip.com": "电商购物",
    # 社交媒体
    "linkedin.com": "社交媒体", "facebook.com": "社交媒体", "instagram.com": "社交媒体",
    "twitter.com": "社交媒体", "x.com": "社交媒体", "weibo.com": "社交媒体",
    "tiktok.com": "社交媒体", "douyin.com": "社交媒体", "xiaohongshu.com": "社交媒体",
    "reddit.com": "社交媒体", "discord.com": "社交媒体", "snapchat.com": "社交媒体",
    "pinterest.com": "社交媒体", "quora.com": "社交媒体", "zhihu.com": "社交媒体",
    # 金融理财
    "eastmoney.com": "金融理财", "xueqiu.com": "金融理财", "futu.com": "金融理财",
    "lufax.com": "金融理财", "creditkarma.com": "金融理财", "mint.com": "金融理财",
    "robinhood.com": "金融理财", "coinbase.com": "金融理财", "binance.com": "金融理财",
    # 新闻资讯
    "36kr.com": "新闻资讯", "huxiu.com": "新闻资讯", "toutiao.com": "新闻资讯",
    "substack.com": "新闻资讯", "medium.com": "新闻资讯", "nytimes.com": "新闻资讯",
    "wsj.com": "新闻资讯", "bbc.com": "新闻资讯", "cnn.com": "新闻资讯",
    "reuters.com": "新闻资讯", "bloomberg.com": "新闻资讯", "theguardian.com": "新闻资讯",
    "sspai.com": "新闻资讯", "infoq.cn": "新闻资讯",
    # 娱乐游戏
    "steampowered.com": "娱乐游戏", "epicgames.com": "娱乐游戏", "ea.com": "娱乐游戏",
    "blizzard.com": "娱乐游戏", "playstation.com": "娱乐游戏", "xbox.com": "娱乐游戏",
    "netflix.com": "娱乐游戏", "spotify.com": "娱乐游戏", "hulu.com": "娱乐游戏",
    "iqiyi.com": "娱乐游戏", "bilibili.com": "娱乐游戏", "youku.com": "娱乐游戏",
    # 餐饮外卖
    "meituan.com": "餐饮外卖", "ele.me": "餐饮外卖", "doordash.com": "餐饮外卖",
    "ubereats.com": "餐饮外卖", "grubhub.com": "餐饮外卖", "deliveroo.com": "餐饮外卖",
    "starbucks.com": "餐饮外卖", "mcdonalds.com": "餐饮外卖", "dominos.com": "餐饮外卖",
    "grabfood.com": "餐饮外卖", "foodpanda.com": "餐饮外卖",
    # 旅行出行
    "ctrip.com": "旅行出行", "booking.com": "旅行出行", "airbnb.com": "旅行出行",
    "expedia.com": "旅行出行", "trip.com": "旅行出行", "agoda.com": "旅行出行",
    "skyscanner.com": "旅行出行", "kayak.com": "旅行出行", "tripadvisor.com": "旅行出行",
    "uber.com": "旅行出行", "lyft.com": "旅行出行", "didi.com": "旅行出行",
    "grab.com": "旅行出行", "klook.com": "旅行出行",
    # 科技服务
    "heroku.com": "科技服务", "vercel.com": "科技服务", "netlify.com": "科技服务",
    "digitalocean.com": "科技服务", "vultr.com": "科技服务", "linode.com": "科技服务",
    "notion.so": "科技服务", "slack.com": "科技服务", "atlassian.com": "科技服务",
    "jetbrains.com": "科技服务", "figma.com": "科技服务", "canva.com": "科技服务",
    "zoom.us": "科技服务", "dropbox.com": "科技服务", "grammarly.com": "科技服务",
    "openai.com": "科技服务", "anthropic.com": "科技服务",
}

# ────────────────────────────────────────────────────────────────
#  数据库配置
# ────────────────────────────────────────────────────────────────

# SQLite 数据库文件路径
DB_PATH = os.path.join(os.path.dirname(__file__), "gmail-unsubscriber.db")
