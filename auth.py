# -*- coding: utf-8 -*-
"""
认证模块 - Gmail OAuth 2.0 授权
负责获取并刷新 Google OAuth 令牌，返回可用的 Gmail API 服务对象。

工作原理：
1. 首次运行时，打开浏览器让用户授权
2. 授权成功后，令牌保存到 token.json（已加入 .gitignore）
3. 下次运行时自动读取 token.json，若过期则自动刷新
"""

import os
import sys
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Gmail 权限范围：modify 权限允许读取、打标签，但不允许永久删除邮件
# 使用 modify 而非 readonly，是因为退订后需要给邮件打标签标记
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# 凭据文件路径（从 Google Cloud Console 下载）
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")

# 令牌缓存文件路径（首次授权后自动生成）
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")


def authenticate() -> Credentials:
    """
    执行 OAuth 2.0 认证流程，返回有效的凭据对象。

    流程：
    - 若 token.json 存在且有效，直接使用
    - 若令牌过期但有刷新令牌，自动刷新
    - 若无有效令牌，启动浏览器授权流程

    Returns:
        google.oauth2.credentials.Credentials: 已认证的凭据对象

    Raises:
        FileNotFoundError: credentials.json 不存在时抛出
        SystemExit: 用户取消授权时退出程序
    """
    if not os.path.exists(CREDENTIALS_FILE):
        logger.error("找不到 credentials.json，请先从 Google Cloud Console 下载")
        print("\n❌ 错误：找不到 credentials.json 文件")
        print("   请参考 docs/USAGE_GUIDE.md 中的「Google Cloud Console 配置步骤」")
        print(f"   将文件放置于：{CREDENTIALS_FILE}")
        sys.exit(1)

    # 兜底：凭据文件若权限过宽则收紧为 0o600（不影响 Google 的使用）
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except OSError:
        pass

    creds = None

    # 尝试从缓存文件加载令牌
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            logger.debug("从 token.json 加载令牌成功")
        except Exception as e:
            logger.warning(f"读取 token.json 失败，将重新授权：{e}")
            creds = None

    # 令牌无效或已过期
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # 令牌过期但可以刷新
            try:
                logger.info("令牌已过期，正在自动刷新...")
                creds.refresh(Request())
                logger.info("令牌刷新成功")
            except Exception as e:
                logger.warning(f"令牌刷新失败，将重新授权：{e}")
                creds = None

        if not creds:
            # 启动浏览器授权流程
            print("\n🔐 需要进行 Google 账号授权（首次使用）")
            print("   即将打开浏览器，请登录并授权访问 Gmail...\n")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
                logger.info("OAuth 授权成功")
            except KeyboardInterrupt:
                print("\n\n用户取消授权，程序退出。")
                sys.exit(0)
            except Exception as e:
                logger.error(f"OAuth 授权失败：{e}")
                print(f"\n❌ 授权失败：{e}")
                sys.exit(1)

        # 保存令牌到文件，下次免登录（权限 600，避免其他用户读取刷新令牌）
        try:
            fd = os.open(
                TOKEN_FILE,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(fd, "w") as f:
                f.write(creds.to_json())
            # 兜底：若文件已存在，os.open 不会改权限，显式修正一次
            os.chmod(TOKEN_FILE, 0o600)
            logger.debug(f"令牌已保存到 {TOKEN_FILE}")
        except IOError as e:
            logger.warning(f"保存令牌失败（不影响本次使用）：{e}")

    return creds


def get_gmail_service():
    """
    获取已认证的 Gmail API 服务对象。

    Returns:
        googleapiclient.discovery.Resource: Gmail API 服务对象

    Raises:
        SystemExit: 认证失败时退出程序
    """
    creds = authenticate()
    try:
        service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail API 服务初始化成功")
        return service
    except HttpError as e:
        logger.error(f"初始化 Gmail API 失败：{e}")
        print(f"\n❌ 无法连接 Gmail API：{e}")
        sys.exit(1)
