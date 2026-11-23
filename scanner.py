"""Background market scanner.

One scanner runs per server (shared by every viewer). It works through the
whole universe on its own, so the page always has a fresh table to show:

  * Price pass: daily history for every stock (trend, momentum, RSI, MACD,
    volatility), re-run on a timer.
  * Fundamentals pass: company info for every stock (multiples, margins,
    growth, analyst targets), refreshed once a day and saved to disk so a
    restart doesn't start from zero.

The table scores each stock on valuation plus a quick direction read from
price trend, analysts and valuation. News, political news, earnings history
and options are fetched only when you open a company (that's ~15 calls per
stock, too many to run for thousands of stocks on free data).
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

import data
import signals
import universe

CACHE_DIR = os.environ.get("OI_CACHE_DIR", "/tmp/options_intel_cache")
INFO_TTL = 24 * 3600
CHUNK = 100


def _f(x):
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


class Scanner:
    def __init__(self):
        self.lock = threading.Lock()
        self.choices: list[str] = ["S&P 500", "Nasdaq-100"]
        self.extra: list[str] = []
        self.price_every = 600
        self.uni = pd.DataFrame(columns=["symbol", "name", "sector", "index"])
        self.prices: dict[str, dict] = {}
        self.info: dict[str, dict] = {}
        self.info_ts: dict[str, float] = {}
        self.last_price_pass: float = 0
        self.price_pass_running = False
        self.price_done = 0
        self.status = "Starting"
        self.version = 0
        self._table_cache = (None, None)
        self._thread = None
        self._wake = threading.Event()
        self._load_disk()

    # ------------------------------------------------------------------ setup
    def configure(self, choices: list[str], extra: list[str], price_every_min: int):
        changed = (sorted(choices) != sorted(self.choices)) or (sorted(extra) != sorted(self.extra))
        self.choices, self.extra = list(choices), list(extra)
        self.price_every = max(60, price_every_min * 60)
        if changed or self.uni.empty:
            self._refresh_universe()
            self.last_price_pass = 0
            self._wake.set()

    def _refresh_universe(self):
        try:
            u = universe.combined(self.choices)
        except Exception as e:
            self.status = f"Could not load index lists: {e}"
            u = pd.DataFrame(columns=["symbol", "name", "sector", "index"])
        if self.extra:
            add = pd.DataFrame({"symbol": [s for s in self.extra if s not in set(u["symbol"])],
                                "name": "", "sector": "", "index": "Watchlist"})
            u = pd.concat([add, u], ignore_index=True)
        with self.lock:
            self.uni = u
            self.version += 1

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True, name="scanner")
            self._thread.start()

    def kick(self):
        self.last_price_pass = 0
        self._wake.set()

    # ------------------------------------------------------------------ disk
    def _load_disk(self):
        try:
            with open(os.path.join(CACHE_DIR, "info.json")) as f:
                blob = json.load(f)
            self.info, self.info_ts = blob.get("info", {}), blob.get("ts", {})
        except Exception:
            pass

    def _save_disk(self):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = os.path.join(CACHE_DIR, "info.json.tmp")
            with self.lock:
                blob = {"info": self.info, "ts": self.info_ts}
            with open(tmp, "w") as f:
                json.dump(blob, f, default=str)
            os.replace(tmp, os.path.join(CACHE_DIR, "info.json"))
        except Exception:
            pass

    # ------------------------------------------------------------------ loop
    def _loop(self):
        last_uni = time.time()
        while True:
            try:
                if time.time() - last_uni > 24 * 3600:
                    self._refresh_universe()
                    last_uni = time.time()
                syms = list(self.uni["symbol"])
                if not syms:
                    self._wake.wait(30); self._wake.clear()
                    continue
                # Big universes can't be re-priced every minute on free data:
                # allow roughly one request per second per pass.
                every = max(self.price_every, len(syms))
                if time.time() - self.last_price_pass > every:
                    self._price_pass(syms)
                stale = [s for s in syms if time.time() - self.info_ts.get(s, 0) > INFO_TTL]
                if stale:
                    self._info_batch(stale[:24])
                    continue
                self.status = "Up to date"
                self._wake.wait(15); self._wake.clear()
            except Exception as e:  # keep the scanner alive no matter what
                self.status = f"Scanner hiccup ({type(e).__name__}); retrying"
                time.sleep(20)

    def _price_pass(self, syms):
        self.price_pass_running, self.price_done = True, 0
        for i in range(0, len(syms), CHUNK):
            chunk = syms[i:i + CHUNK]
            self.status = f"Updating prices {i + len(chunk)}/{len(syms)}"
            try:
                raw = yf.download(chunk, period="1y", interval="1d", group_by="ticker",
                                  auto_adjust=True, threads=True, progress=False)
            except Exception:
                raw = None
            if raw is not None and not raw.empty:
                upd = {}
                for s in chunk:
                    try:
                        df = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
                        df = df.dropna(subset=["Close"])
                        if len(df) < 5:
                            continue
                        upd[s] = self._summarise(df)
                    except Exception:
                        continue
                with self.lock:
                    self.prices.update(upd)
                    self.version += 1
            self.price_done = i + len(chunk)
            time.sleep(1.0)
        self.last_price_pass = time.time()
        self.price_pass_running = False

    @staticmethod
    def _summarise(df: pd.DataFrame) -> dict:
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        h = data.add_indicators(df)
        c = h["Close"]
        last = h.iloc[-1]
        px = float(last["Close"])
        prev = float(c.iloc[-2]) if len(c) > 1 else None

        def ret(n):
            return px / float(c.iloc[-n - 1]) - 1 if len(c) > n else None

        ytd = c[c.index >= pd.Timestamp(datetime.now().year, 1, 1)]
        hi, lo = float(h["High"].max()), float(h["Low"].min())
        return {
            "price": px, "day": (px / prev - 1) if prev else None,
            "r1m": ret(21), "r3m": ret(63), "ytd": (px / float(ytd.iloc[0]) - 1) if len(ytd) else None,
            "rsi": _f(last.get("RSI")), "hv30": _f(last.get("HV30")),
            "pos52": (px - lo) / (hi - lo) if hi > lo else None,
            "vol_ratio": (float(last["Volume"]) / float(h["Volume"].tail(20).mean())
                          if h["Volume"].tail(20).mean() else None),
            "spark": [round(float(x), 2) for x in c.tail(60)],
            "tech": signals.tech_signals(h),
            "asof": h.index[-1].to_pydatetime(),
        }

    def _info_batch(self, syms):
        self.status = f"Loading fundamentals ({self.fundamentals_loaded()}/{len(self.uni)})"
        with ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(self._one_info, syms))
        got = 0
        with self.lock:
            for s, inf in zip(syms, results):
                if inf:
                    self.info[s] = inf
                    got += 1
                # Mark attempted either way; failures retry after 1 hour
                self.info_ts[s] = time.time() if inf else time.time() - INFO_TTL + 3600
            self.version += 1
        if got < len(syms) / 3:
            self.status = "Data source is rate-limiting; pausing 60s"
            time.sleep(60)
        else:
            time.sleep(1.5)
        if len(self.info) % 96 < 24:
            self._save_disk()

    @staticmethod
    def _one_info(s):
        try:
            inf = data.get_info(s)
            if not inf.get("price") and not inf.get("marketCap") and not inf.get("longName"):
                return None
            return {k: v for k, v in inf.items()
                    if k != "longBusinessSummary" and (v is None or isinstance(v, (int, float, str)))}
        except Exception:
            return None

    # ------------------------------------------------------------------ read
    def fundamentals_loaded(self) -> int:
        syms = set(self.uni["symbol"])
        return sum(1 for s in syms if s in self.info)

    def progress(self) -> dict:
        n = len(self.uni)
        priced = sum(1 for s in self.uni["symbol"] if s in self.prices)
        return {"total": n, "priced": priced, "fundamentals": self.fundamentals_loaded(),
                "status": self.status,
                "last_price": datetime.fromtimestamp(self.last_price_pass) if self.last_price_pass else None}

    def table(self, risk_free: float) -> pd.DataFrame:
        key = (self.version, risk_free)
        if self._table_cache[0] == key:
            return self._table_cache[1]
        with self.lock:
            uni = self.uni.copy()
            prices = dict(self.prices)
            info = dict(self.info)
        rows = []
        for u in uni.itertuples(index=False):
            p, inf = prices.get(u.symbol), info.get(u.symbol)
            if not p and not inf:
                continue
            inf = dict(inf or {})
            price = (p or {}).get("price") or _f(inf.get("price"))
            if not price:
                continue
            old_px = _f(inf.get("price"))
            if old_px and price and inf.get("marketCap"):
                inf["marketCap"] = inf["marketCap"] * price / old_px
            inf["price"] = price
            val = signals.valuation(inf, risk_free) if inf.get("sharesOutstanding") or inf.get("targetMeanPrice") else None
            sig = {**((p or {}).get("tech") or {}), **signals.info_signals(inf, val)}
            d = signals.combine(sig)
            ets = inf.get("earningsTimestampStart") or inf.get("earningsTimestamp")
            nxt = datetime.fromtimestamp(ets) if ets else None
            if nxt and nxt.date() < datetime.now().date():
                nxt = None
            rows.append({
                "Ticker": u.symbol,
                "Company": inf.get("name") or u.name or u.symbol,
                "Sector": inf.get("sector") or u.sector or "",
                "Index": u.index,
                "Price": price,
                "Day %": _pct((p or {}).get("day")),
                "1M %": _pct((p or {}).get("r1m")),
                "3M %": _pct((p or {}).get("r3m")),
                "YTD %": _pct((p or {}).get("ytd")),
                "Trend (60d)": (p or {}).get("spark") or [],
                "Market cap ($B)": (inf.get("marketCap") or np.nan) / 1e9,
                "Valuation": val["verdict"] if val else ("Loading" if u.symbol not in info else "Not enough data"),
                "Fair value": (val or {}).get("fair_value") or np.nan,
                "Fair value gap %": _pct((val or {}).get("upside")),
                "Direction": d["label"],
                "Certainty %": d["certainty"],
                "Score": d["score"],
                "P/E (fwd)": _f(inf.get("forwardPE")) or np.nan,
                "PEG": _f(inf.get("pegRatio")) or np.nan,
                "EV/EBITDA": _f(inf.get("enterpriseToEbitda")) or np.nan,
                "Rev growth %": _pct(_f(inf.get("revenueGrowth"))),
                "Net margin %": _pct(_f(inf.get("profitMargins"))),
                "ROE %": _pct(_f(inf.get("returnOnEquity"))),
                "Debt/Equity": (_f(inf.get("debtToEquity")) or np.nan) / 100,
                "RSI": (p or {}).get("rsi") or np.nan,
                "Realised vol %": _pct((p or {}).get("hv30")),
                "52w range pos %": _pct((p or {}).get("pos52")),
                "Rel volume": (p or {}).get("vol_ratio") or np.nan,
                "Analyst target": _f(inf.get("targetMeanPrice")) or np.nan,
                "Next earnings": nxt,
                "Short % float": _pct(_f(inf.get("shortPercentOfFloat"))),
                "Beta": _f(inf.get("beta")) or np.nan,
            })
        df = pd.DataFrame(rows)
        self._table_cache = (key, df)
        return df


def _pct(x):
    v = _f(x)
    return v * 100 if v is not None else np.nan
