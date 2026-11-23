"""Data layer: prices, fundamentals, earnings, options chains.

All market data comes from Yahoo Finance via the `yfinance` library (free,
no API key). Every function is defensive: Yahoo changes field names from time
to time, so anything missing comes back as None instead of crashing the app.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yfinance as yf


def _num(x):
    """Return a clean float or None."""
    try:
        if x is None:
            return None
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Company profile + fundamentals
# --------------------------------------------------------------------------- #
INFO_FIELDS = [
    "longName", "shortName", "sector", "industry", "longBusinessSummary", "website",
    "currentPrice", "regularMarketPrice", "previousClose", "marketCap", "enterpriseValue",
    "trailingPE", "forwardPE", "pegRatio", "trailingPegRatio", "priceToBook",
    "priceToSalesTrailing12Months", "enterpriseToEbitda", "enterpriseToRevenue",
    "profitMargins", "operatingMargins", "grossMargins", "ebitdaMargins",
    "returnOnEquity", "returnOnAssets", "debtToEquity", "currentRatio", "quickRatio",
    "freeCashflow", "operatingCashflow", "totalCash", "totalDebt", "totalRevenue",
    "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
    "trailingEps", "forwardEps", "bookValue", "dividendYield", "payoutRatio",
    "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage",
    "targetMeanPrice", "targetHighPrice", "targetLowPrice", "targetMedianPrice",
    "numberOfAnalystOpinions", "recommendationMean", "recommendationKey",
    "shortPercentOfFloat", "shortRatio", "sharesOutstanding", "heldPercentInstitutions",
    "currency", "exchange", "averageVolume",
]


def get_info(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    try:
        raw = t.info or {}
    except Exception:
        raw = {}
    info = {k: raw.get(k) for k in INFO_FIELDS}
    info["symbol"] = symbol.upper()
    info["name"] = info.get("longName") or info.get("shortName") or symbol.upper()
    info["price"] = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
    if info.get("pegRatio") is None:
        info["pegRatio"] = info.get("trailingPegRatio")
    return info


def get_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    try:
        df = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return add_indicators(df)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["Close"]
    df["SMA20"] = c.rolling(20).mean()
    df["SMA50"] = c.rolling(50).mean()
    df["SMA200"] = c.rolling(200).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["RSI"] = 100 - 100 / (1 + rs)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACDsig"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACDhist"] = df["MACD"] - df["MACDsig"]
    df["LogRet"] = np.log(c / c.shift(1))
    df["HV30"] = df["LogRet"].rolling(30).std() * math.sqrt(252)
    return df


# --------------------------------------------------------------------------- #
# Earnings
# --------------------------------------------------------------------------- #
def get_earnings(symbol: str) -> dict:
    """Past EPS surprises + next earnings date."""
    t = yf.Ticker(symbol)
    out = {"history": pd.DataFrame(), "next_date": None, "next_eps_est": None,
           "next_rev_est": None}

    # Earnings history with surprises
    try:
        ed = t.get_earnings_dates(limit=16)
    except Exception:
        ed = None
    if ed is not None and not ed.empty:
        ed = ed.copy()
        ed.index = pd.to_datetime(ed.index).tz_localize(None)
        cols = {c: c.strip() for c in ed.columns}
        ed = ed.rename(columns=cols)
        now = pd.Timestamp.now()
        future = ed[ed.index > now]
        past = ed[ed.index <= now].dropna(subset=[c for c in ["Reported EPS"] if c in ed.columns])
        if not future.empty:
            out["next_date"] = future.index.min().to_pydatetime()
            if "EPS Estimate" in future.columns:
                out["next_eps_est"] = _num(future.sort_index().iloc[0].get("EPS Estimate"))
        out["history"] = past.sort_index(ascending=False).head(8)

    # Fallback for next date from the calendar
    if out["next_date"] is None:
        try:
            cal = t.calendar
            dates = None
            if isinstance(cal, dict):
                dates = cal.get("Earnings Date")
                out["next_eps_est"] = out["next_eps_est"] or _num(cal.get("Earnings Average"))
                out["next_rev_est"] = _num(cal.get("Revenue Average"))
            elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                dates = list(cal.loc["Earnings Date"].values)
            if dates:
                d = dates[0] if isinstance(dates, (list, tuple)) else dates
                out["next_date"] = pd.to_datetime(d).to_pydatetime()
        except Exception:
            pass
    return out


def get_quarterly_financials(symbol: str) -> pd.DataFrame:
    """Revenue, net income, margins for the last few quarters."""
    t = yf.Ticker(symbol)
    try:
        inc = t.quarterly_income_stmt
    except Exception:
        return pd.DataFrame()
    if inc is None or inc.empty:
        return pd.DataFrame()
    rows = {}
    for label, keys in {
        "Revenue": ["Total Revenue", "Operating Revenue"],
        "Gross profit": ["Gross Profit"],
        "Operating income": ["Operating Income"],
        "Net income": ["Net Income", "Net Income Common Stockholders"],
        "Diluted EPS": ["Diluted EPS"],
    }.items():
        for k in keys:
            if k in inc.index:
                rows[label] = inc.loc[k]
                break
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index().tail(6)
    if "Revenue" in df and "Net income" in df:
        df["Net margin"] = df["Net income"] / df["Revenue"]
    return df


def get_recommendations(symbol: str) -> dict | None:
    try:
        rs = yf.Ticker(symbol).recommendations_summary
        if rs is None or rs.empty:
            rs = yf.Ticker(symbol).recommendations
        if rs is None or rs.empty:
            return None
        row = rs.iloc[0]
        return {k: int(row.get(k, 0) or 0) for k in ["strongBuy", "buy", "hold", "sell", "strongSell"]}
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Options
# --------------------------------------------------------------------------- #
def _mid(row) -> float | None:
    bid, ask, last = _num(row.get("bid")), _num(row.get("ask")), _num(row.get("lastPrice"))
    if bid and ask and ask >= bid > 0:
        return (bid + ask) / 2
    return last


def get_options(symbol: str, price: float | None, max_expiries: int = 8) -> dict:
    """Per-expiry summary: ATM IV, straddle, expected move, put/call ratios."""
    t = yf.Ticker(symbol)
    out = {"expiries": pd.DataFrame(), "chains": {}, "pc_oi": None, "pc_vol": None,
           "atm_iv": None}
    if not price:
        return out
    try:
        expiries = list(t.options or [])
    except Exception:
        expiries = []
    today = datetime.now().date()
    rows = []
    tot = {"call_oi": 0, "put_oi": 0, "call_vol": 0, "put_vol": 0}
    for exp in expiries[:max_expiries]:
        try:
            ch = t.option_chain(exp)
        except Exception:
            continue
        calls, puts = ch.calls.copy(), ch.puts.copy()
        if calls.empty or puts.empty:
            continue
        out["chains"][exp] = (calls, puts)
        k_call = calls.iloc[(calls["strike"] - price).abs().argsort()[:1]].iloc[0]
        k_put = puts.iloc[(puts["strike"] - price).abs().argsort()[:1]].iloc[0]
        ivs = [v for v in [_num(k_call.get("impliedVolatility")), _num(k_put.get("impliedVolatility"))] if v and v > 0.01]
        atm_iv = sum(ivs) / len(ivs) if ivs else None
        c_mid, p_mid = _mid(k_call), _mid(k_put)
        straddle = (c_mid or 0) + (p_mid or 0) if (c_mid and p_mid) else None
        c_oi, p_oi = calls["openInterest"].fillna(0).sum(), puts["openInterest"].fillna(0).sum()
        c_v, p_v = calls["volume"].fillna(0).sum(), puts["volume"].fillna(0).sum()
        tot["call_oi"] += c_oi; tot["put_oi"] += p_oi; tot["call_vol"] += c_v; tot["put_vol"] += p_v
        dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        rows.append({
            "Expiry": exp, "DTE": dte, "ATM strike": float(k_call["strike"]),
            "ATM IV": atm_iv, "Straddle": straddle,
            "Expected move": (straddle / price) if straddle else None,
            "Put/Call OI": (p_oi / c_oi) if c_oi else None,
            "Put/Call vol": (p_v / c_v) if c_v else None,
            "Call OI": int(c_oi), "Put OI": int(p_oi),
            "Max pain": max_pain(calls, puts),
        })
    df = pd.DataFrame(rows)
    out["expiries"] = df
    if tot["call_oi"]:
        out["pc_oi"] = tot["put_oi"] / tot["call_oi"]
    if tot["call_vol"]:
        out["pc_vol"] = tot["put_vol"] / tot["call_vol"]
    if not df.empty:
        # ATM IV of the first expiry at least a week out (front week is noisy)
        valid = df[(df["DTE"] >= 7) & df["ATM IV"].notna()]
        pick = valid.iloc[0] if not valid.empty else df.dropna(subset=["ATM IV"]).head(1)
        if isinstance(pick, pd.DataFrame):
            pick = pick.iloc[0] if not pick.empty else None
        out["atm_iv"] = _num(pick["ATM IV"]) if pick is not None else None
    return out


def max_pain(calls: pd.DataFrame, puts: pd.DataFrame) -> float | None:
    """Strike at which option holders' total payout is smallest."""
    try:
        strikes = sorted(set(calls["strike"]).union(puts["strike"]))
        c = calls[["strike", "openInterest"]].fillna(0).values
        p = puts[["strike", "openInterest"]].fillna(0).values
        best, best_k = None, None
        for k in strikes:
            pain = sum(max(0, k - s) * oi for s, oi in c) + sum(max(0, s - k) * oi for s, oi in p)
            if best is None or pain < best:
                best, best_k = pain, k
        return float(best_k) if best_k is not None else None
    except Exception:
        return None


def earnings_expected_move(options: dict, next_date) -> dict | None:
    """Expected move priced in for the first expiry after the next earnings date."""
    df = options.get("expiries")
    if df is None or df.empty or not next_date:
        return None
    nd = pd.Timestamp(next_date).normalize()
    after = df[pd.to_datetime(df["Expiry"]) >= nd]
    if after.empty:
        return None
    r = after.iloc[0]
    if r.get("Expected move") is None or pd.isna(r.get("Expected move")):
        return None
    return {"expiry": r["Expiry"], "move": float(r["Expected move"]), "straddle": float(r["Straddle"])}
