# -*- coding: utf-8 -*-
"""
数据库模块 - SQLite 状态管理
管理三张表：退订历史、扫描记录、用户白名单
"""

import os
import sqlite3
import logging
from datetime import datetime

import config

logger = logging.getLogger(__name__)


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库，创建所需的三张表（如已存在则跳过）。"""
    conn = _get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS unsubscribed_senders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_email    TEXT NOT NULL UNIQUE,
            sender_name     TEXT,
            unsubscribed_at TEXT NOT NULL,
            method          TEXT,
            success         INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS scan_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at      TEXT NOT NULL,
            days            INTEGER,
            total_emails    INTEGER,
            candidates      INTEGER,
            unsubscribed    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS user_whitelist (
            domain          TEXT PRIMARY KEY,
            added_at        TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    # 确保数据库文件权限为 0o600（包含扫描历史等 PII）
    try:
        os.chmod(config.DB_PATH, 0o600)
    except OSError:
        pass
    logger.debug("数据库初始化完成")


def record_unsubscribe(sender_email: str, sender_name: str, method: str, success: bool) -> None:
    """记录退订操作（成功或失败）。已存在的记录会被覆盖更新。"""
    conn = _get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO unsubscribed_senders
            (sender_email, sender_name, unsubscribed_at, method, success)
        VALUES (?, ?, ?, ?, ?)
        """,
        (sender_email, sender_name, datetime.now().isoformat(), method, int(success)),
    )
    conn.commit()
    conn.close()
    logger.debug(f"退订记录已保存：{sender_email}（{'成功' if success else '失败'}）")


def is_already_unsubscribed(sender_email: str) -> bool:
    """检查该发件人是否已成功退订过（只有 success=1 才算）。"""
    conn = _get_connection()
    row = conn.execute(
        "SELECT id FROM unsubscribed_senders WHERE sender_email = ? AND success = 1",
        (sender_email,),
    ).fetchone()
    conn.close()
    return row is not None


def get_history(limit: int = 50) -> list[dict]:
    """返回退订历史记录，按时间倒序。"""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM unsubscribed_senders ORDER BY unsubscribed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_scan(days: int, total_emails: int, candidates: int, unsubscribed: int) -> None:
    """记录一次扫描操作的统计数据。"""
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO scan_history (scanned_at, days, total_emails, candidates, unsubscribed)
        VALUES (?, ?, ?, ?, ?)
        """,
        (datetime.now().isoformat(), days, total_emails, candidates, unsubscribed),
    )
    conn.commit()
    conn.close()


def add_to_user_whitelist(domain: str) -> bool:
    """将域名加入用户白名单。返回 True=新增成功，False=已存在。"""
    domain = domain.lower().strip()
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO user_whitelist (domain, added_at) VALUES (?, ?)",
            (domain, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        logger.info(f"白名单新增：{domain}")
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def get_user_whitelist() -> list[str]:
    """返回用户自定义白名单域名列表。"""
    conn = _get_connection()
    rows = conn.execute("SELECT domain FROM user_whitelist").fetchall()
    conn.close()
    return [r["domain"] for r in rows]
