"""News layer: company news, political/policy news, and headline sentiment.

Sources (all free, no key):
  * Yahoo Finance company news (via yfinance)
  * Google News RSS searches for the company and for political/policy topics

Political items are scored for *relevance* to the company: direct mentions of
the company or ticker count most, then policy themes that hit its sector
(e.g. export controls for chipmakers, drug pricing for pharma).
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

UA = {"User-Agent": "Mozilla/5.0 (compatible; OptionsIntel/1.0)"}

# --------------------------------------------------------------------------- #
# Sentiment: VADER tuned with market vocabulary
# --------------------------------------------------------------------------- #
_an = SentimentIntensityAnalyzer()
_an.lexicon.update({
    # bullish
    "beat": 2.0, "beats": 2.0, "tops": 1.6, "surge": 2.2, "surges": 2.2, "soar": 2.4,
    "soars": 2.4, "rally": 1.8, "rallies": 1.8, "jumps": 1.8, "upgrade": 2.2,
    "upgraded": 2.2, "outperform": 1.8, "record": 1.2, "raises": 1.2, "raised": 1.0,
    "buyback": 1.4, "bullish": 2.2, "breakout": 1.6, "approval": 1.8, "approved": 1.6,
    "exemption": 1.2, "deal": 0.8, "partnership": 1.0, "guidance raised": 2.0,
    # bearish
    "miss": -2.0, "misses": -2.0, "plunge": -2.6, "plunges": -2.6, "tumble": -2.2,
    "tumbles": -2.2, "slump": -2.0, "sinks": -2.0, "falls": -1.2, "drops": -1.2,
    "downgrade": -2.2, "downgraded": -2.2, "underperform": -1.8, "cut": -1.2, "cuts": -1.2,
    "lawsuit": -1.6, "probe": -1.8, "investigation": -1.6, "antitrust": -1.4,
    "sanction": -1.6, "sanctions": -1.6, "tariff": -1.2, "tariffs": -1.2, "ban": -1.8,
    "bans": -1.8, "recall": -1.8, "layoffs": -1.2, "bearish": -2.2, "warning": -1.6,
    "fine": -1.0, "fined": -1.8, "subpoena": -1.8, "delay": -1.2, "delays": -1.2,
    "restrictions": -1.4, "crackdown": -1.8, "shortfall": -1.8, "selloff": -2.0,
})


def sentiment(text: str) -> float:
    """-1 (very bearish) .. +1 (very bullish)."""
    if not text:
        return 0.0
    return _an.polarity_scores(text)["compound"]


# --------------------------------------------------------------------------- #
# Political / policy themes and which sectors they hit
# --------------------------------------------------------------------------- #
POLITICAL_TERMS = [
    "tariff", "tariffs", "sanction", "sanctions", "congress", "senate", "house committee",
    "white house", "president", "trump", "biden", "administration", "executive order",
    "regulation", "regulator", "regulators", "antitrust", "doj", "justice department",
    "ftc", "sec ", "fcc", "fda", "export control", "export controls", "commerce department",
    "trade war", "trade deal", "trade talks", "federal reserve", "fed ", "powell",
    "interest rate", "rate cut", "rate hike", "treasury", "subsidy", "subsidies",
    "chips act", "tax", "legislation", "bill ", "lawmakers", "election", "geopolitical",
    "china", "beijing", "taiwan", "russia", "ukraine", "middle east", "iran", "opec",
    "eu commission", "european commission", "brussels", "ban", "probe", "hearing", "shutdown",
]

SECTOR_THEMES = {
    "Technology": ["export control", "chips", "semiconductor", "china", "taiwan", "antitrust",
                   "ai regulation", "artificial intelligence", "data privacy", "tariff", "chips act"],
    "Communication Services": ["antitrust", "fcc", "section 230", "content moderation",
                               "privacy", "eu commission", "digital markets act", "tiktok"],
    "Consumer Cyclical": ["tariff", "consumer", "china", "ev tax credit", "emissions",
                          "trade", "import", "minimum wage"],
    "Consumer Defensive": ["tariff", "snap", "food prices", "import", "trade"],
    "Healthcare": ["drug pricing", "medicare", "medicaid", "fda", "aca", "obamacare",
                   "pharmacy benefit", "pbm", "inflation reduction act", "biosecure"],
    "Financial Services": ["federal reserve", "interest rate", "rate cut", "rate hike", "basel",
                           "capital requirements", "bank regulation", "sec ", "cfpb", "crypto"],
    "Energy": ["opec", "oil", "drilling", "pipeline", "sanctions", "russia", "iran", "lng",
               "emissions", "epa", "middle east"],
    "Industrials": ["defense", "pentagon", "infrastructure", "tariff", "steel", "aluminum",
                    "faa", "budget", "shutdown"],
    "Basic Materials": ["tariff", "steel", "aluminum", "rare earth", "mining", "china"],
    "Utilities": ["ferc", "epa", "emissions", "interest rate", "grid"],
    "Real Estate": ["interest rate", "federal reserve", "housing", "mortgage", "rate cut"],
}

MACRO_QUERY = ('(tariffs OR "Federal Reserve" OR "executive order" OR sanctions OR '
               '"trade deal" OR "export controls" OR Congress) stock market when:3d')


def _google_news(query: str, limit: int = 30) -> list[dict]:
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
           + "&hl=en-US&gl=US&ceid=US:en")
    try:
        r = requests.get(url, headers=UA, timeout=10)
        feed = feedparser.parse(r.content)
    except Exception:
        return []
    items = []
    for e in feed.entries[:limit]:
        title = e.get("title", "")
        source = ""
        if hasattr(e, "source") and isinstance(e.source, dict):
            source = e.source.get("title", "")
        if " - " in title and not source:
            title, source = title.rsplit(" - ", 1)
        elif source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)]
        try:
            ts = parsedate_to_datetime(e.get("published"))
        except Exception:
            ts = None
        items.append({"title": title.strip(), "source": source, "link": e.get("link", ""),
                      "time": ts, "summary": ""})
    return items


def _yahoo_news(symbol: str) -> list[dict]:
    try:
        raw = yf.Ticker(symbol).news or []
    except Exception:
        return []
    items = []
    for n in raw:
        c = n.get("content", n)  # new and old formats
        title = c.get("title") or ""
        link = ((c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict)
                else None) or c.get("link") or ""
        src = ((c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict)
               else None) or c.get("publisher") or "Yahoo Finance"
        ts = None
        if c.get("pubDate"):
            try:
                ts = datetime.fromisoformat(c["pubDate"].replace("Z", "+00:00"))
            except Exception:
                ts = None
        elif c.get("providerPublishTime"):
            ts = datetime.fromtimestamp(c["providerPublishTime"], tz=timezone.utc)
        items.append({"title": title, "source": src, "link": link, "time": ts,
                      "summary": c.get("summary") or ""})
    return items


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = re.sub(r"[^a-z0-9]", "", it["title"].lower())[:70]
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _short_name(name: str) -> str:
    n = re.sub(r",?\s+(inc|incorporated|corp|corporation|co|company|ltd|plc|holdings|group|"
               r"class [a-z]|n\.v\.|s\.a\.)\.?$", "", name, flags=re.I).strip()
    n = re.sub(r",?\s+(inc|corp|ltd|plc)\.?$", "", n, flags=re.I).strip()
    return n or name


def _hours_ago(ts) -> float:
    if not ts:
        return 72.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600)


def _has(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term.strip())}s?\b", text) is not None


def company_news(symbol: str, name: str) -> list[dict]:
    short = _short_name(name)
    items = _yahoo_news(symbol) + _google_news(f'"{short}" OR {symbol} stock when:7d', 25)
    items = _dedupe(items)
    for it in items:
        it["sentiment"] = sentiment(it["title"] + ". " + it.get("summary", "")[:300])
        it["hours"] = _hours_ago(it["time"])
    items.sort(key=lambda x: x["hours"])
    return items[:40]


def political_news(symbol: str, name: str, sector: str | None) -> list[dict]:
    short = _short_name(name)
    themes = SECTOR_THEMES.get(sector or "", [])
    q_company = (f'"{short}" (tariff OR sanctions OR Congress OR "White House" OR regulators OR '
                 f'antitrust OR "export controls" OR lawmakers OR administration OR FTC OR DOJ) when:14d')
    q_sector = ""
    if themes:
        q_sector = "(" + " OR ".join(f'"{t}"' for t in themes[:8]) + ") policy when:7d"
    items = _google_news(q_company, 30)
    if q_sector:
        items += _google_news(q_sector, 25)
    items += _google_news(MACRO_QUERY, 25)
    items = _dedupe(items)

    out = []
    sym_re = re.compile(rf"\b{re.escape(symbol)}\b")
    for it in items:
        t = it["title"].lower()
        pol_hits = [p.strip() for p in POLITICAL_TERMS if _has(t, p)]
        if not pol_hits:
            continue
        direct = short.lower() in t or bool(sym_re.search(it["title"]))
        theme_hits = [th.strip() for th in themes if _has(t, th)]
        relevance = min(1.0, (0.6 if direct else 0.0) + 0.15 * len(theme_hits)
                        + 0.08 * len(pol_hits) + 0.1)
        it["relevance"] = round(relevance, 2)
        it["direct"] = direct
        it["themes"] = sorted({h.rstrip("s") if h.endswith("controls") or h.endswith("tariffs") or h.endswith("sanctions") else h for h in theme_hits + pol_hits})[:5]
        it["sentiment"] = sentiment(it["title"])
        it["hours"] = _hours_ago(it["time"])
        out.append(it)
    out.sort(key=lambda x: (-x["relevance"], x["hours"]))
    return out[:40]


def weighted_sentiment(items: list[dict], use_relevance: bool = False) -> tuple[float | None, int]:
    """Recency-weighted (half-life 48h) mean sentiment."""
    if not items:
        return None, 0
    num = den = 0.0
    for it in items:
        w = 0.5 ** (it.get("hours", 72) / 48)
        if use_relevance:
            w *= it.get("relevance", 0.3)
        num += w * it.get("sentiment", 0)
        den += w
    return (num / den if den else None), len(items)
