"""Scoring engine.

1. Valuation  -> blended fair value from up to five independent models,
                 then Undervalued / Fairly valued / Overvalued.
2. Direction  -> nine signals (trend, momentum, RSI, MACD, analysts, earnings
                 surprises, company news, political news, options positioning)
                 combined into a score from -1 (bearish) to +1 (bullish).
3. Certainty  -> how strong the score is x how much the signals agree x how
                 much data was available. 50% = coin flip, 95% = cap.

This is a transparent rules-based model, not a back-tested probability.
Every input and its contribution is returned so the UI can show the working.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

RISK_FREE = 0.0425      # ~10y US Treasury; adjust in the sidebar
EQUITY_PREMIUM = 0.05
TERMINAL_GROWTH = 0.03


def _n(x):
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------- #
# Valuation
# --------------------------------------------------------------------------- #
def valuation(info: dict, risk_free: float = RISK_FREE) -> dict:
    price = _n(info.get("price"))
    models = []

    # Growth assumption used by several models (earnings growth, else revenue)
    g_raw = _n(info.get("earningsGrowth"))
    if g_raw is None or g_raw > 1.5 or g_raw < -0.5:
        g_raw = _n(info.get("revenueGrowth"))
    growth = _clamp(g_raw if g_raw is not None else 0.05, 0.0, 0.25)

    beta = _clamp(_n(info.get("beta")) or 1.0, 0.6, 2.0)
    disc = _clamp(risk_free + beta * EQUITY_PREMIUM, 0.07, 0.14)

    # 1) Analyst consensus target
    tgt = _n(info.get("targetMeanPrice"))
    n_an = _n(info.get("numberOfAnalystOpinions")) or 0
    if tgt and n_an >= 3:
        models.append(("Analyst consensus target", tgt, 0.30,
                       f"Mean of {int(n_an)} analyst price targets"))

    # 2) DCF on free cash flow per share (5y growth fading to terminal)
    fcf = _n(info.get("freeCashflow"))
    shares = _n(info.get("sharesOutstanding"))
    if fcf and shares and fcf > 0:
        fcfps = fcf / shares
        pv, cf = 0.0, fcfps
        for yr in range(1, 6):
            g = growth + (TERMINAL_GROWTH - growth) * (yr - 1) / 5
            cf *= 1 + g
            pv += cf / (1 + disc) ** yr
        tv = cf * (1 + TERMINAL_GROWTH) / (disc - TERMINAL_GROWTH)
        pv += tv / (1 + disc) ** 5
        # add net cash per share
        cash, debt = _n(info.get("totalCash")) or 0, _n(info.get("totalDebt")) or 0
        pv += (cash - debt) / shares
        if pv > 0:
            models.append(("Discounted cash flow", pv, 0.30,
                           f"FCF/share {fcfps:.2f}, growth {growth:.0%} fading to 3%, "
                           f"discount rate {disc:.1%}"))

    # 3) Growth-adjusted P/E (Lynch: fair P/E ~ growth rate, floor 10, cap 30)
    feps = _n(info.get("forwardEps"))
    if feps and feps > 0:
        fair_pe = _clamp(growth * 100, 10, 30)
        models.append(("Growth-adjusted P/E", feps * fair_pe, 0.20,
                       f"Forward EPS {feps:.2f} x fair P/E {fair_pe:.0f}"))

    # 4) Graham number (conservative asset+earnings anchor)
    teps, bvps = _n(info.get("trailingEps")), _n(info.get("bookValue"))
    if teps and bvps and teps > 0 and bvps > 0:
        models.append(("Graham number", math.sqrt(22.5 * teps * bvps), 0.10,
                       "sqrt(22.5 x EPS x book value/share) - conservative"))

    # 5) EV/EBITDA reversion to a 12x market-typical multiple
    ev_ebitda = _n(info.get("enterpriseToEbitda"))
    mcap, ev = _n(info.get("marketCap")), _n(info.get("enterpriseValue"))
    if ev_ebitda and ev_ebitda > 0 and mcap and ev and shares and price:
        ebitda = ev / ev_ebitda
        target_mult = _clamp(12 * (1 + growth), 10, 22)
        fair_ev = ebitda * target_mult
        fair_eq = fair_ev - (ev - mcap)
        if fair_eq > 0:
            models.append(("EV/EBITDA multiple", fair_eq / shares, 0.10,
                           f"EBITDA x {target_mult:.1f} (growth-adjusted) less net debt"))

    if not price or not models:
        return {"fair_value": None, "upside": None, "verdict": "Not enough data",
                "models": models, "price": price}

    w = sum(m[2] for m in models)
    fair = sum(m[1] * m[2] for m in models) / w
    upside = fair / price - 1
    if upside > 0.15:
        verdict = "Undervalued"
    elif upside < -0.15:
        verdict = "Overvalued"
    else:
        verdict = "Fairly valued"
    return {"fair_value": fair, "upside": upside, "verdict": verdict, "models": models,
            "price": price, "growth": growth, "discount": disc,
            "low": min(m[1] for m in models), "high": max(m[1] for m in models)}


# --------------------------------------------------------------------------- #
# Direction (bullish / bearish)
# --------------------------------------------------------------------------- #
WEIGHTS = {
    "Trend (50/200-day)": 0.18,
    "Momentum (3-month)": 0.10,
    "RSI (14)": 0.05,
    "MACD": 0.08,
    "Analyst ratings": 0.10,
    "Earnings surprises": 0.10,
    "Company news": 0.14,
    "Political & policy news": 0.10,
    "Options positioning": 0.10,
    "Valuation gap": 0.05,
}


def tech_signals(hist: pd.DataFrame) -> dict:
    """Signals from price history alone: trend, momentum, RSI, MACD."""
    sig = {}
    if hist is None or len(hist) <= 60:
        return sig
    last = hist.iloc[-1]
    px = last["Close"]
    parts = []
    if pd.notna(last.get("SMA50")):
        parts.append(1 if px > last["SMA50"] else -1)
    if pd.notna(last.get("SMA200")):
        parts.append(1 if px > last["SMA200"] else -1)
        if pd.notna(last.get("SMA50")):
            parts.append(1 if last["SMA50"] > last["SMA200"] else -1)
    if parts:
        txt = f"Price {'above' if px > last['SMA50'] else 'below'} 50-day"
        if pd.notna(last.get("SMA200")):
            txt += f", {'above' if px > last['SMA200'] else 'below'} 200-day"
        sig["Trend (50/200-day)"] = (sum(parts) / len(parts), txt)
    if len(hist) > 63:
        r3 = px / hist["Close"].iloc[-64] - 1
        sig["Momentum (3-month)"] = (math.tanh(r3 / 0.15), f"{r3:+.1%} over 3 months")
    rsi = _n(last.get("RSI"))
    if rsi is not None:
        if rsi >= 75:
            v = -0.6
        elif rsi <= 25:
            v = 0.6
        else:
            v = _clamp((rsi - 50) / 25, -1, 1) * 0.6
        label = "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else "neutral zone"
        sig["RSI (14)"] = (v, f"RSI {rsi:.0f} ({label})")
    mh = _n(last.get("MACDhist"))
    if mh is not None and px:
        sig["MACD"] = (math.tanh(mh / px * 200),
                       f"Histogram {'positive' if mh > 0 else 'negative'} ({mh:+.2f})")
    return sig


def info_signals(info: dict, val: dict | None) -> dict:
    """Signals from fundamentals: analyst ratings and the valuation gap."""
    sig = {}
    rec = _n(info.get("recommendationMean")) if info else None
    if rec:
        sig["Analyst ratings"] = (_clamp((3 - rec) / 1.5, -1, 1),
                                  f"Mean rating {rec:.2f} (1 = strong buy, 5 = sell)")
    if val and val.get("upside") is not None:
        sig["Valuation gap"] = (math.tanh(val["upside"] / 0.3),
                                f"{val['upside']:+.0%} vs blended fair value")
    return sig


def deep_signals(earnings: dict, news_sent, pol_sent, options: dict) -> dict:
    """Signals that need per-company calls: earnings, news, political news, options."""
    sig = {}
    eh = earnings.get("history") if earnings else None
    if eh is not None and not eh.empty and "Surprise(%)" in eh.columns:
        s = pd.to_numeric(eh["Surprise(%)"], errors="coerce").dropna().head(4)
        if len(s):
            beats = int((s > 0).sum())
            sig["Earnings surprises"] = (math.tanh(s.mean() / 8),
                                         f"Beat {beats} of last {len(s)}; avg surprise {s.mean():+.1f}%")
    if news_sent and news_sent[0] is not None:
        sig["Company news"] = (_clamp(news_sent[0] * 2.2, -1, 1),
                               f"Avg headline sentiment {news_sent[0]:+.2f} across {news_sent[1]} stories")
    if pol_sent and pol_sent[0] is not None:
        sig["Political & policy news"] = (_clamp(pol_sent[0] * 2.2, -1, 1),
                                          f"Relevance-weighted sentiment {pol_sent[0]:+.2f} "
                                          f"across {pol_sent[1]} items")
    pc = options.get("pc_oi") if options else None
    if pc:
        sig["Options positioning"] = (_clamp((0.95 - pc) / 0.5, -1, 1), f"Put/call open interest {pc:.2f}")
    return sig


def combine(sig: dict) -> dict:
    """Weighted score, label and certainty from whichever signals are present."""
    if not sig:
        return {"score": 0.0, "label": "Neutral", "certainty": 50, "signals": {}, "coverage": 0,
                "agreement": 0}
    used_w = sum(WEIGHTS[k] for k in sig)
    score = sum(WEIGHTS[k] * v[0] for k, v in sig.items()) / used_w
    coverage = used_w / sum(WEIGHTS.values())
    sign = 1 if score >= 0 else -1
    agree = sum(WEIGHTS[k] for k, v in sig.items() if v[0] * sign > 0.05) / used_w
    strength = min(1.0, abs(score) / 0.55)
    certainty = 50 + 45 * strength * (0.4 + 0.6 * agree) * math.sqrt(coverage)
    certainty = round(_clamp(certainty, 50, 95))
    if score > 0.25:
        label = "Bullish"
    elif score > 0.08:
        label = "Leaning bullish"
    elif score < -0.25:
        label = "Bearish"
    elif score < -0.08:
        label = "Leaning bearish"
    else:
        label = "Neutral"
    return {"score": score, "label": label, "certainty": certainty, "agreement": agree,
            "coverage": coverage,
            "signals": {k: {"value": v[0], "weight": WEIGHTS[k], "detail": v[1],
                            "contribution": WEIGHTS[k] * v[0] / used_w}
                        for k, v in sig.items()}}


def direction(info: dict, hist: pd.DataFrame, earnings: dict, news_sent, pol_sent,
              options: dict, val: dict) -> dict:
    sig = {**tech_signals(hist), **info_signals(info, val),
           **deep_signals(earnings, news_sent, pol_sent, options)}
    return combine(sig)


# --------------------------------------------------------------------------- #
# Options read-out
# --------------------------------------------------------------------------- #
def volatility_view(options: dict, hist: pd.DataFrame) -> dict:
    iv = options.get("atm_iv") if options else None
    hv = None
    if hist is not None and not hist.empty and "HV30" in hist:
        hv = _n(hist["HV30"].iloc[-1])
    ratio = iv / hv if iv and hv else None
    if ratio is None:
        read = "Not enough options data"
    elif ratio > 1.3:
        read = "Options look expensive vs realised moves - favours selling premium (spreads, covered calls, iron condors)"
    elif ratio < 0.9:
        read = "Options look cheap vs realised moves - favours buying premium (long calls/puts, straddles)"
    else:
        read = "Options fairly priced vs realised volatility"
    return {"iv": iv, "hv": hv, "ratio": ratio, "read": read}


def strategy_hint(dir_label: str, vol: dict) -> str:
    rich = vol.get("ratio") and vol["ratio"] > 1.3
    cheap = vol.get("ratio") and vol["ratio"] < 0.9
    if "Bullish" in dir_label or "bullish" in dir_label:
        return ("Bull put spread or covered call (premium is rich)" if rich else
                "Long call or call debit spread (premium is cheap)" if cheap else
                "Call debit spread")
    if "Bearish" in dir_label or "bearish" in dir_label:
        return ("Bear call spread (premium is rich)" if rich else
                "Long put or put debit spread (premium is cheap)" if cheap else
                "Put debit spread")
    return ("Iron condor / short strangle with defined risk (premium is rich)" if rich else
            "Long straddle ahead of a catalyst (premium is cheap)" if cheap else
            "Stay small or wait for a clearer signal")
