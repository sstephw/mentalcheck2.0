"""Offline stand-in for Yahoo Finance + Google News, used only by tests."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd


class FakeChain:
    def __init__(self, calls, puts):
        self.calls, self.puts = calls, puts


class FakeTicker:
    def __init__(self, sym):
        self.sym = sym.upper()
        self.seed = sum(map(ord, self.sym))
        rng = np.random.default_rng(self.seed)
        n = 520
        drift = 0.0008 if self.seed % 2 else -0.0004
        r = rng.normal(drift, 0.02, n)
        close = 100 * np.exp(np.cumsum(r))
        idx = pd.bdate_range(end=datetime.now(), periods=n)
        self._hist = pd.DataFrame({"Open": close * 0.995, "High": close * 1.01, "Low": close * 0.99,
                                   "Close": close, "Volume": rng.integers(1e6, 5e6, n)}, index=idx)
        self.px = float(close[-1])

    def history(self, period="1y", auto_adjust=True):
        return self._hist

    @property
    def info(self):
        p = self.px
        if self.sym == "SPY":
            return {"longName": "SPDR S&P 500 ETF", "regularMarketPrice": p, "previousClose": p * .99}
        secs = ["Technology", "Healthcare", "Financial Services", "Energy", "Consumer Cyclical", "Industrials"]
        return {"longName": f"{self.sym} Corporation", "sector": secs[self.seed % 6],
                "earningsTimestampStart": (datetime.now() + timedelta(days=self.seed % 40)).timestamp(), "industry": "Semiconductors",
                "currentPrice": p, "previousClose": p * 0.985, "marketCap": 2.1e12, "enterpriseValue": 2.05e12,
                "trailingPE": 34.2, "forwardPE": 27.1, "trailingPegRatio": 1.4, "priceToBook": 12.0,
                "priceToSalesTrailing12Months": 9.5, "enterpriseToEbitda": 24.0, "enterpriseToRevenue": 9.3,
                "profitMargins": .26, "operatingMargins": .31, "grossMargins": .62, "ebitdaMargins": .36,
                "returnOnEquity": .45, "returnOnAssets": .2, "debtToEquity": 61.0, "currentRatio": 1.3,
                "quickRatio": 1.1, "freeCashflow": 6e10, "operatingCashflow": 8e10, "totalCash": 5e10,
                "totalDebt": 3e10, "totalRevenue": 2.2e11, "revenueGrowth": .12, "earningsGrowth": .18,
                "trailingEps": p / 34.2, "forwardEps": p / 27.1, "bookValue": p / 12, "dividendYield": 0.5,
                "beta": 1.2, "fiftyTwoWeekHigh": p * 1.2, "fiftyTwoWeekLow": p * .7,
                "targetMeanPrice": p * (1.18 if self.seed % 2 else 0.92), "targetHighPrice": p * 1.5,
                "targetLowPrice": p * .8, "numberOfAnalystOpinions": 40, "recommendationMean": 1.9,
                "recommendationKey": "buy", "shortPercentOfFloat": .012, "shortRatio": 1.4,
                "sharesOutstanding": 2.1e12 / p, "heldPercentInstitutions": .62, "exchange": "NMS",
                "longBusinessSummary": "Synthetic test company.", "website": "https://example.com"}

    @property
    def options(self):
        d0 = datetime.now().date()
        return tuple((d0 + timedelta(days=d)).isoformat() for d in (3, 10, 17, 31, 45, 73, 101, 164))

    def option_chain(self, exp):
        strikes = np.round(np.arange(self.px * .7, self.px * 1.3, self.px * .025), 1)
        dte = max(1, (datetime.fromisoformat(exp).date() - datetime.now().date()).days)
        iv = 0.38 + 0.02 * np.abs(strikes / self.px - 1) * 10
        tv = self.px * iv * np.sqrt(dte / 365) * 0.4
        calls = pd.DataFrame({"contractSymbol": [f"{self.sym}C{k}" for k in strikes], "strike": strikes,
                              "lastPrice": np.maximum(self.px - strikes, 0) + tv, "bid": np.maximum(self.px - strikes, 0) + tv * .97,
                              "ask": np.maximum(self.px - strikes, 0) + tv * 1.03, "volume": 900.0,
                              "openInterest": 5000 * np.exp(-np.abs(strikes / self.px - 1.05) * 8),
                              "impliedVolatility": iv, "inTheMoney": strikes < self.px})
        puts = calls.copy()
        puts["lastPrice"] = np.maximum(strikes - self.px, 0) + tv
        puts["bid"] = puts["lastPrice"] * .97; puts["ask"] = puts["lastPrice"] * 1.03
        puts["openInterest"] = 3500 * np.exp(-np.abs(strikes / self.px - .93) * 8)
        puts["volume"] = 600.0
        if self.sym == "SPY" and exp.endswith("x"):
            pass
        return FakeChain(calls, puts)

    def get_earnings_dates(self, limit=16):
        now = pd.Timestamp.now().normalize()
        idx = [now + pd.Timedelta(days=24)] + [now - pd.Timedelta(days=91 * i) for i in range(1, 8)]
        est = [1.10, 1.02, .95, .9, .85, .8, .76, .7]
        rep = [np.nan, 1.08, .99, .88, .9, .84, .79, .74]
        sur = [np.nan] + [(r / e - 1) * 100 for r, e in zip(rep[1:], est[1:])]
        return pd.DataFrame({"EPS Estimate": est, "Reported EPS": rep, "Surprise(%)": sur},
                            index=pd.DatetimeIndex(idx, name="Earnings Date").tz_localize("America/New_York"))

    @property
    def calendar(self):
        return {"Earnings Date": [datetime.now().date() + timedelta(days=24)],
                "Earnings Average": 1.1, "Revenue Average": 6.1e10}

    @property
    def quarterly_income_stmt(self):
        cols = pd.to_datetime([datetime.now() - timedelta(days=91 * i) for i in range(1, 6)])
        return pd.DataFrame({c: {"Total Revenue": 5.5e10 - i * 1e9, "Gross Profit": 3.4e10, "Operating Income": 1.7e10,
                                 "Net Income": 1.4e10 - i * 3e8, "Diluted EPS": 1.0 - i * .05}
                             for i, c in enumerate(cols)})

    @property
    def recommendations_summary(self):
        return pd.DataFrame([{"period": "0m", "strongBuy": 14, "buy": 20, "hold": 6, "sell": 1, "strongSell": 0}])

    @property
    def news(self):
        now = datetime.now(timezone.utc)
        heads = [f"{self.sym} beats earnings estimates, shares surge", f"Analysts upgrade {self.sym} on AI demand",
                 f"{self.sym} faces antitrust probe in Europe", f"{self.sym} stock falls after supplier warning"]
        return [{"content": {"title": h, "pubDate": (now - timedelta(hours=5 * i)).isoformat().replace("+00:00", "Z"),
                             "canonicalUrl": {"url": f"https://example.com/{i}"}, "provider": {"displayName": "Reuters"},
                             "summary": ""}} for i, h in enumerate(heads)]


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>White House weighs new chip export controls on China - Bloomberg</title><link>https://ex.com/a</link><pubDate>{d}</pubDate></item>
<item><title>Congress probes {name} over AI chips sales - Reuters</title><link>https://ex.com/b</link><pubDate>{d}</pubDate></item>
<item><title>Fed signals rate cut as tariffs ease, stocks rally - CNBC</title><link>https://ex.com/c</link><pubDate>{d}</pubDate></item>
<item><title>{name} shares jump on record data center sales - WSJ</title><link>https://ex.com/d</link><pubDate>{d}</pubDate></item>
</channel></rss>"""


class FakeResp:
    def raise_for_status(self):
        pass

    def __init__(self, url):
        if "news.google" not in url:
            raise ConnectionError("offline test")
        import urllib.parse
        q = urllib.parse.unquote(url)
        name = "Company"
        if '"' in q:
            name = q.split('"')[1]
        d = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        self.content = RSS.format(d=d, name=name).encode()


def download(tickers, **kw):
    if isinstance(tickers, str):
        tickers = [tickers]
    frames = {t: FakeTicker(t).history().tail(252) for t in tickers}
    return pd.concat(frames, axis=1)


def install():
    import requests
    import yfinance
    yfinance.Ticker = FakeTicker
    yfinance.download = download
    requests.get = lambda url, **kw: FakeResp(url)
