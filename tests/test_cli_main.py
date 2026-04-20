# -*- coding: utf-8 -*-
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


def test_get_runtime_warnings_for_old_python_and_libressl():
    warnings = main.get_runtime_warnings(
        version_info=(3, 9, 6),
        openssl_version="LibreSSL 2.8.3",
    )

    assert any("Python 3.10+" in item for item in warnings)
    assert any("LibreSSL" in item for item in warnings)


def test_get_runtime_warnings_clean_runtime():
    warnings = main.get_runtime_warnings(
        version_info=(3, 11, 9),
        openssl_version="OpenSSL 3.0.13 30 Jan 2024",
    )

    assert warnings == []


def test_print_runtime_warnings_outputs_to_stderr(monkeypatch, capsys):
    monkeypatch.setattr(
        main,
        "get_runtime_warnings",
        lambda version_info=None, openssl_version=None: ["warn 1", "warn 2"],
    )

    main.print_runtime_warnings()
    captured = capsys.readouterr()

    assert "运行环境提示" in captured.err
    assert "warn 1" in captured.err
    assert "warn 2" in captured.err


def test_main_shows_runtime_warning_before_interactive_mode(monkeypatch, capsys):
    monkeypatch.setattr(main.sys, "argv", ["main.py"])
    monkeypatch.setattr(main, "print_runtime_warnings", Mock())
    monkeypatch.setattr(main, "interactive_menu", Mock())
    monkeypatch.setattr(main.user_config if hasattr(main, "user_config") else main, "migrate_from_env", Mock(return_value=False), raising=False)

    # main() 内部会 import user_config，这里直接替换模块方法
    import user_config
    monkeypatch.setattr(user_config, "migrate_from_env", Mock(return_value=False))

    main.main()

    main.print_runtime_warnings.assert_called_once()
    main.interactive_menu.assert_called_once()
    captured = capsys.readouterr()
    assert captured.out == ""


def test_main_executes_cli_command(monkeypatch):
    import user_config

    func = Mock()
    args = SimpleNamespace(verbose=False, func=func)
    parser = Mock()
    parser.parse_args.return_value = args

    monkeypatch.setattr(user_config, "migrate_from_env", Mock(return_value=False))
    monkeypatch.setattr(main.sys, "argv", ["main.py", "history"])
    monkeypatch.setattr(main, "build_parser", Mock(return_value=parser))
    monkeypatch.setattr(main, "setup_logging", Mock())
    monkeypatch.setattr(main.database, "init_db", Mock())
    monkeypatch.setattr(main, "print_runtime_warnings", Mock())

    main.main()

    main.print_runtime_warnings.assert_called_once()
    main.setup_logging.assert_called_once_with(verbose=False)
    main.database.init_db.assert_called_once()
    func.assert_called_once_with(args)


def test_resolve_scan_limit_applies_default_cap(capsys):
    args = SimpleNamespace(days=0, all=True, full_scan=False, max_messages=None)

    limit = main.resolve_scan_limit(args)
    captured = capsys.readouterr()

    assert limit == main.DEFAULT_FULL_SCAN_MAX_MESSAGES
    assert "默认仅处理前" in captured.out


def test_resolve_scan_limit_respects_explicit_full_scan():
    args = SimpleNamespace(days=0, all=True, full_scan=True, max_messages=None)
    assert main.resolve_scan_limit(args) is None


def test_resolve_scan_limit_respects_explicit_max_messages():
    args = SimpleNamespace(days=0, all=True, full_scan=False, max_messages=500)
    assert main.resolve_scan_limit(args) == 500
