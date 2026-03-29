# data/watchlist_store.py — Persist the user's watchlist to a local JSON file.

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import WATCHLIST_FILE


def _load_raw() -> dict:
    """Load raw JSON from disk. Returns {'stocks': [{'code': ..., 'name': ...}]}"""
    if not os.path.exists(WATCHLIST_FILE):
        return {"stocks": []}
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"stocks": []}


def _save_raw(data: dict):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_watchlist() -> list:
    """Return list of dicts: [{'code': '000001', 'name': '平安银行'}, ...]"""
    return _load_raw().get("stocks", [])


def add_stock(code: str, name: str):
    """Add a stock if not already present."""
    data = _load_raw()
    stocks = data.get("stocks", [])
    if not any(s["code"] == code for s in stocks):
        stocks.append({"code": code, "name": name})
    data["stocks"] = stocks
    _save_raw(data)


def remove_stock(code: str):
    """Remove a stock by code."""
    data = _load_raw()
    data["stocks"] = [s for s in data.get("stocks", []) if s["code"] != code]
    _save_raw(data)


def is_in_watchlist(code: str) -> bool:
    return any(s["code"] == code for s in load_watchlist())
