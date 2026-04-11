# -*- coding: utf-8 -*-
"""
配置文件 - 白名单、关键词和全局设置
所有可自定义的参数集中在这里，方便用户调整而不需要改动核心逻辑。
"""

import json
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
    "edu", "edu.cn", "coursera.org", "edx.org", "khanacademy.org",
    "mit.edu", "stanford.edu", "harvard.edu",

    # 公共事业 & 新加坡电信
    "electricity.com", "water.com", "gas.com",
    "state.gov", "unitedstates.gov",
    "singtel.com", "starhub.com", "m1.com", "m1.com.sg",
    "utility", "telecom",
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
    "newsletter", "news", "promo", "promotion", "marketing",
    "offers", "deals", "sales", "shop", "store",
    "info", "hello", "hi", "contact", "team",
    "notification", "alert", "updates", "digest",
    "广告", "推广", "营销", "促销", "优惠", "通知",
]

# ────────────────────────────────────────────────────────────────
#  运行时配置（运行时可动态修改白名单）
# ────────────────────────────────────────────────────────────────

# 用户自定义白名单（存储在本地 JSON 文件中）
USER_WHITELIST_FILE = os.path.join(os.path.dirname(__file__), "user_whitelist.json")


def load_user_whitelist() -> list[str]:
    """加载用户自定义白名单。"""
    if not os.path.exists(USER_WHITELIST_FILE):
        return []
    try:
        with open(USER_WHITELIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("domains", [])
    except (json.JSONDecodeError, KeyError):
        return []


def save_user_whitelist(domains: list[str]) -> None:
    """保存用户自定义白名单到本地文件。"""
    with open(USER_WHITELIST_FILE, "w", encoding="utf-8") as f:
        json.dump({"domains": domains}, f, ensure_ascii=False, indent=2)


def get_all_whitelist_domains() -> list[str]:
    """返回内置白名单 + 用户自定义白名单的合集。"""
    user_domains = load_user_whitelist()
    all_domains = list(set(WHITELIST_DOMAINS + user_domains))
    return all_domains


def add_to_user_whitelist(domain: str) -> bool:
    """
    将域名加入用户白名单。
    返回 True 表示新增成功，False 表示已存在。
    """
    current = load_user_whitelist()
    domain = domain.lower().strip()
    if domain in current or domain in WHITELIST_DOMAINS:
        return False
    current.append(domain)
    save_user_whitelist(current)
    return True
