"""Ties data, news and scoring together, with a shared time-based cache so
many viewers and auto-refreshes don't hammer the data sources."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import data
import news
import signals

_CACHE: dict = {}
_LOCK = threading.Lock()


def _cached(key, ttl, fn):
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _LOCK:
        _CACHE[key] = (now, val)
    return val


def clear_cache():
    with _LOCK:
        _CACHE.clear()


def analyze(symbol: str, risk_free: float = signals.RISK_FREE,
            price_ttl: int = 120, slow_ttl: int = 900) -> dict:
    symbol = symbol.upper().strip()
    try:
        info = _cached(("info", symbol), price_ttl, lambda: data.get_info(symbol))
        hist = _cached(("hist", symbol), price_ttl, lambda: data.get_history(symbol, "2y"))
        if not info.get("price") and hist is not None and not hist.empty:
            info["price"] = float(hist["Close"].iloc[-1])
        if not info.get("previousClose") and hist is not None and len(hist) > 1:
            info["previousClose"] = float(hist["Close"].iloc[-2])

        earn = _cached(("earn", symbol), slow_ttl, lambda: data.get_earnings(symbol))
        fin = _cached(("fin", symbol), slow_ttl, lambda: data.get_quarterly_financials(symbol))
        recs = _cached(("recs", symbol), slow_ttl, lambda: data.get_recommendations(symbol))
        opts = _cached(("opts", symbol), price_ttl * 2,
                       lambda: data.get_options(symbol, info.get("price")))
        cnews = _cached(("cnews", symbol), slow_ttl // 2,
                        lambda: news.company_news(symbol, info["name"]))
        pnews = _cached(("pnews", symbol), slow_ttl // 2,
                        lambda: news.political_news(symbol, info["name"], info.get("sector")))

        val = signals.valuation(info, risk_free)
        ns = news.weighted_sentiment(cnews)
        ps = news.weighted_sentiment(pnews, use_relevance=True)
        drn = signals.direction(info, hist, earn, ns, ps, opts, val)
        vol = signals.volatility_view(opts, hist)
        em = data.earnings_expected_move(opts, earn.get("next_date"))
        hint = signals.strategy_hint(drn["label"], vol)

        price, prev = info.get("price"), info.get("previousClose")
        day = (price / prev - 1) if price and prev else None
        return {"ok": bool(price), "symbol": symbol, "info": info, "hist": hist,
                "earnings": earn, "financials": fin, "recs": recs, "options": opts,
                "company_news": cnews, "political_news": pnews, "valuation": val,
                "direction": drn, "vol": vol, "earn_move": em, "hint": hint,
                "day_change": day, "updated": datetime.now()}
    except Exception as e:  # never take the whole board down for one ticker
        return {"ok": False, "symbol": symbol, "error": f"{type(e).__name__}: {e}"}


def analyze_many(symbols: list[str], risk_free: float = signals.RISK_FREE) -> dict:
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(symbols)))) as ex:
        results = list(ex.map(lambda s: analyze(s, risk_free), symbols))
    return {r["symbol"]: r for r in results}
