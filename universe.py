"""Which companies to scan.

Lists are downloaded live (refreshed daily) so index changes are picked up
automatically. If a source is unreachable, the bundled CSVs in /universe are
used instead.

  S&P 500          ~503 stocks   (GitHub datasets mirror, then Wikipedia)
  Nasdaq-100       ~101 stocks   (Nasdaq API, then Wikipedia)
  All Nasdaq-listed ~3,000+ stocks (Nasdaq Trader symbol directory)
"""
from __future__ import annotations

import io
import os
import time

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*"}

UNIVERSES = {
    "S&P 500": "sp500",
    "Nasdaq-100": "nasdaq100",
    "All Nasdaq-listed stocks": "nasdaq_all",
}

_cache: dict = {}


def _yahoo(sym: str) -> str:
    return str(sym).strip().upper().replace(".", "-").replace("/", "-")


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=20, **kw)
    r.raise_for_status()
    return r


def _bundled(name: str) -> pd.DataFrame:
    return pd.read_csv(os.path.join(HERE, "universe", f"{name}.csv"))


def _sp500() -> pd.DataFrame:
    try:
        df = pd.read_csv(io.StringIO(_get(
            "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv").text))
        df = df.rename(columns={"Symbol": "symbol", "Security": "name", "GICS Sector": "sector"})
        if len(df) > 450:
            return df[["symbol", "name", "sector"]]
    except Exception:
        pass
    try:
        html = _get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies").text
        df = pd.read_html(io.StringIO(html))[0]
        df = df.rename(columns={"Symbol": "symbol", "Security": "name", "GICS Sector": "sector"})
        if len(df) > 450:
            return df[["symbol", "name", "sector"]]
    except Exception:
        pass
    return _bundled("sp500")


def _nasdaq100() -> pd.DataFrame:
    try:
        j = _get("https://api.nasdaq.com/api/quote/list-type/nasdaq100").json()
        rows = j["data"]["data"]["rows"]
        df = pd.DataFrame([{"symbol": r["symbol"], "name": r.get("companyName", r["symbol"]),
                            "sector": ""} for r in rows])
        if len(df) > 90:
            return df
    except Exception:
        pass
    try:
        html = _get("https://en.wikipedia.org/wiki/Nasdaq-100").text
        for t in pd.read_html(io.StringIO(html)):
            cols = [str(c) for c in t.columns]
            if "Ticker" in cols and len(t) > 90:
                name_col = "Company" if "Company" in cols else cols[0]
                sec_col = next((c for c in cols if "Sector" in c), None)
                return pd.DataFrame({"symbol": t["Ticker"], "name": t[name_col],
                                     "sector": t[sec_col] if sec_col else ""})
    except Exception:
        pass
    return _bundled("nasdaq100")


def _nasdaq_all() -> pd.DataFrame:
    """Every common stock listed on Nasdaq (no ETFs, test issues, warrants, units, etc.)."""
    for url in ["https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
                "https://ftp.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"]:
        try:
            df = pd.read_csv(io.StringIO(_get(url).text), sep="|")
            df = df[df["Symbol"].notna() & ~df["Symbol"].astype(str).str.startswith("File Creation")]
            df = df[(df["ETF"] == "N") & (df["Test Issue"] == "N")]
            if "Financial Status" in df:
                df = df[df["Financial Status"].isin(["N"]) | df["Financial Status"].isna()]
            bad = r"warrant|right|unit|preferred|notes due|depositary share|% |subordinated|debenture"
            df = df[~df["Security Name"].str.contains(bad, case=False, na=False)]
            df = df[~df["Symbol"].astype(str).str.contains(r"[\$\.]")]
            name = df["Security Name"].str.replace(r"\s*-\s*(Class [A-Z] )?(Common|Ordinary|American).*$",
                                                   "", regex=True)
            return pd.DataFrame({"symbol": df["Symbol"], "name": name, "sector": ""})
        except Exception:
            continue
    # Fallback: at least the Nasdaq-100
    return _nasdaq100()


_LOADERS = {"sp500": _sp500, "nasdaq100": _nasdaq100, "nasdaq_all": _nasdaq_all}


def load(name: str) -> pd.DataFrame:
    hit = _cache.get(name)
    if hit and time.time() - hit[0] < 24 * 3600:
        return hit[1]
    df = _LOADERS[name]()
    df = df.copy()
    df["symbol"] = df["symbol"].map(_yahoo)
    df["sector"] = df["sector"].fillna("")
    df = df.drop_duplicates("symbol").reset_index(drop=True)
    _cache[name] = (time.time(), df)
    return df


def combined(choices: list[str]) -> pd.DataFrame:
    """Merge the chosen universes; each stock lists which indexes it belongs to."""
    frames = []
    for label in choices:
        df = load(UNIVERSES[label]).copy()
        df["index"] = label
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["symbol", "name", "sector", "index"])
    allf = pd.concat(frames, ignore_index=True)
    allf["order"] = range(len(allf))
    idx = allf.groupby("symbol")["index"].apply(lambda s: " · ".join(dict.fromkeys(s)))
    sector = allf[allf["sector"] != ""].drop_duplicates("symbol").set_index("symbol")["sector"]
    first = allf.drop_duplicates("symbol").set_index("symbol").sort_values("order")
    first["index"] = idx
    first["sector"] = sector.reindex(first.index).fillna("")
    return first.reset_index()[["symbol", "name", "sector", "index"]]
