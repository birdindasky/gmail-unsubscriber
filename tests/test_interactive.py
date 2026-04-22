# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import parse_selection, format_category_summary


def test_parse_selection_single():
    assert parse_selection("1", 5) == [0]


def test_parse_selection_multiple_comma():
    assert parse_selection("1,3,5", 5) == [0, 2, 4]


def test_parse_selection_all():
    assert parse_selection("all", 5) == [0, 1, 2, 3, 4]


def test_parse_selection_invalid():
    assert parse_selection("abc", 5) == []


def test_parse_selection_out_of_range():
    assert parse_selection("99", 5) == []


def test_parse_selection_zero_returns_empty():
    assert parse_selection("0", 5) == []


def test_format_category_summary():
    categorized = {
        "E-commerce": [
            {"sender_email": "a@taobao.com", "count": 10},
            {"sender_email": "b@jd.com", "count": 5},
        ],
        "Newsletter": [
            {"sender_email": "c@36kr.com", "count": 3},
        ],
    }
    lines = format_category_summary(categorized)
    assert len(lines) == 2
    assert "E-commerce" in lines[0]
    assert "2 senders" in lines[0]
    assert "15 emails" in lines[0]
    assert "Newsletter" in lines[1]
