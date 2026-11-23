"""Options Intel - live research board for options traders.

Run locally:   streamlit run app.py
"""
from __future__ import annotations

import html as _html
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import engine

st.set_page_config(page_title="Options Intel", page_icon="◆", layout="wide",
                   initial_sidebar_state="expanded")

GREEN, RED, AMBER, MUTED = "#21c07a", "#f0524f", "#f2b33d", "#8a94a6"

st.markdown("""
<style>
.block-container{padding-top:1.6rem;max-width:1400px}
h1,h2,h3{letter-spacing:-.01em}
.kpi{border:1px solid rgba(138,148,166,.25);border-radius:10px;padding:14px 16px;height:100%}
.kpi .l{font-size:13px;color:#8a94a6}
.kpi .v{font-size:26px;font-weight:700;line-height:1.15;margin-top:2px}
.kpi .s{font-size:13px;color:#8a94a6;margin-top:2px}
.tag{display:inline-block;padding:2px 10px;border-radius:999px;font-size:13px;font-weight:600}
.news{padding:10px 0;border-bottom:1px solid rgba(138,148,166,.18)}
.news a{text-decoration:none;font-weight:600}
.news .m{font-size:12.5px;color:#8a94a6;margin-top:2px}
.bar{height:8px;border-radius:4px;background:rgba(138,148,166,.2);position:relative}
.bar>i{position:absolute;top:0;bottom:0;border-radius:4px}
.small{font-size:13px;color:#8a94a6}
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def money(x, d=2):
    if x is None or pd.isna(x):
        return "—"
    a = abs(x)
    if a >= 1e12: return f"${x/1e12:.2f}T"
    if a >= 1e9: return f"${x/1e9:.2f}B"
    if a >= 1e6: return f"${x/1e6:.1f}M"
    return f"${x:,.{d}f}"


def pct(x, d=1, sign=False):
    if x is None or pd.isna(x):
        return "—"
    return f"{x*100:+.{d}f}%" if sign else f"{x*100:.{d}f}%"


def num(x, d=2, suffix=""):
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{d}f}{suffix}"


def tone(label: str) -> str:
    l = (label or "").lower()
    if "bull" in l or "under" in l: return GREEN
    if "bear" in l or "over" in l: return RED
    return AMBER


def tag(label, color=None):
    c = color or tone(label)
    return f'<span class="tag" style="background:{c}22;color:{c}">{label}</span>'


def kpi(label, value, sub="", color=None):
    style = f' style="color:{color}"' if color else ""
    return (f'<div class="kpi"><div class="l">{label}</div><div class="v"{style}>{value}</div>'
            f'<div class="s">{sub}</div></div>')


def ago(h):
    if h is None: return ""
    if h < 1: return f"{int(h*60)}m ago"
    if h < 48: return f"{int(h)}h ago"
    return f"{int(h/24)}d ago"


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
qp = st.query_params
default_watch = qp.get("t", "NVDA,AAPL,MSFT,TSLA,AMZN,META,AMD,SPY")
with st.sidebar:
    st.markdown("### ◆ Options Intel")
    watch_raw = st.text_area("Watchlist (comma-separated tickers)", default_watch, height=90)
    symbols = [s.strip().upper() for s in watch_raw.replace("\n", ",").split(",") if s.strip()][:20]
    if ",".join(symbols) != qp.get("t"):
        st.query_params["t"] = ",".join(symbols)
    refresh_min = st.select_slider("Auto-refresh every", options=[1, 2, 5, 10, 15, 30],
                                   value=5, format_func=lambda m: f"{m} min")
    rf = st.number_input("Risk-free rate (for DCF)", 0.0, 10.0, 4.25, 0.05,
                         format="%.2f", help="Roughly the 10-year US Treasury yield, in %") / 100
    if st.button("Refresh now", width="stretch"):
        engine.clear_cache()
        st.rerun()
    st.caption("Tip: bookmark this page - your watchlist is saved in the link.")
    st.divider()
    st.caption("Data: Yahoo Finance (prices, fundamentals, earnings, options) and Google News "
               "(company and political news). Quotes can be delayed ~15 min. "
               "Research tool only - not financial advice.")


# --------------------------------------------------------------------------- #
# Main board (re-runs on a timer)
# --------------------------------------------------------------------------- #
@st.fragment(run_every=refresh_min * 60)
def board():
    if not symbols:
        st.info("Add at least one ticker in the sidebar.")
        return
    with st.spinner("Pulling prices, filings, options and news..."):
        res = engine.analyze_many(symbols, rf)

    top_l, top_r = st.columns([3, 1])
    top_l.markdown("## Watchlist")
    top_r.markdown(f'<div class="small" style="text-align:right;padding-top:18px">'
                   f'Updated {datetime.now():%b %d, %H:%M:%S} · refreshes every {refresh_min} min</div>',
                   unsafe_allow_html=True)

    rows, bad = [], []
    for s in symbols:
        r = res.get(s)
        if not r or not r.get("ok"):
            bad.append(s)
            continue
        nd = r["earnings"].get("next_date")
        days = (pd.Timestamp(nd).normalize() - pd.Timestamp.now().normalize()).days if nd else None
        rows.append({
            "Ticker": s,
            "Company": r["info"]["name"],
            "Price": r["info"]["price"],
            "Day": (r["day_change"] or 0) * 100,
            "Valuation": r["valuation"]["verdict"],
            "Fair value gap": r["valuation"]["upside"] * 100 if r["valuation"]["upside"] is not None else float("nan"),
            "Direction": r["direction"]["label"],
            "Certainty": r["direction"]["certainty"],
            "ATM IV": r["vol"]["iv"] * 100 if r["vol"]["iv"] else float("nan"),
            "IV / HV": r["vol"]["ratio"] if r["vol"]["ratio"] else float("nan"),
            "Next earnings": f"{nd:%b %d} ({days}d)" if nd and days is not None and days >= 0 else "—",
            "Earnings move": r["earn_move"]["move"] * 100 if r["earn_move"] else float("nan"),
        })
    if bad:
        st.warning("No data for: " + ", ".join(bad) + ". Check the symbol, or the data source may "
                   "be rate-limiting - it usually clears within a minute.")
    if not rows:
        return
    df = pd.DataFrame(rows)

    def colour(v):
        return f"color:{tone(v)};font-weight:600"

    styled = (df.style
              .map(colour, subset=["Valuation", "Direction"])
              .map(lambda v: f"color:{GREEN if v > 0 else RED if v < 0 else MUTED}",
                   subset=["Day", "Fair value gap"])
              .format({"Price": "${:,.2f}", "Day": "{:+.2f}%", "Fair value gap": "{:+.0f}%",
                       "Certainty": "{:.0f}%", "ATM IV": "{:.0f}%", "IV / HV": "{:.2f}",
                       "Earnings move": "±{:.1f}%"}, na_rep="—"))
    st.dataframe(styled, hide_index=True, width="stretch",
                 height=min(42 + 35 * len(df), 560))

    st.markdown("")
    pick = st.segmented_control("Company detail", [r["Ticker"] for r in rows],
                                default=rows[0]["Ticker"], key="pick")
    if pick:
        detail(res[pick])


# --------------------------------------------------------------------------- #
# Company detail
# --------------------------------------------------------------------------- #
def detail(r):
    info, val, drn, vol = r["info"], r["valuation"], r["direction"], r["vol"]
    st.markdown(f"## {info['name']} ({r['symbol']})")
    st.markdown(f'<div class="small">{info.get("sector") or ""} · {info.get("industry") or ""}'
                f' · {info.get("exchange") or ""}</div>', unsafe_allow_html=True)
    st.markdown("")

    c = st.columns(5)
    day = r["day_change"]
    c[0].markdown(kpi("Price", money(info["price"]), pct(day, 2, True) + " today",
                      GREEN if day and day > 0 else RED if day and day < 0 else None),
                  unsafe_allow_html=True)
    c[1].markdown(kpi("Valuation", val["verdict"],
                      f"Fair value {money(val['fair_value'])} ({pct(val['upside'], 0, True)})",
                      tone(val["verdict"])), unsafe_allow_html=True)
    c[2].markdown(kpi("Direction", drn["label"], f"Score {drn['score']:+.2f} on −1…+1",
                      tone(drn["label"])), unsafe_allow_html=True)
    c[3].markdown(kpi("Certainty", f"{drn['certainty']}%",
                      f"{pct(drn.get('agreement'), 0)} of signals agree · "
                      f"{pct(drn.get('coverage'), 0)} data coverage"), unsafe_allow_html=True)
    em = r["earn_move"]
    c[4].markdown(kpi("Implied vol (ATM)", pct(vol["iv"], 0),
                      f"vs 30d realised {pct(vol['hv'], 0)}"
                      + (f" · earnings ±{em['move']*100:.1f}%" if em else "")), unsafe_allow_html=True)

    st.markdown(f'<div style="margin-top:12px" class="small"><b>Options read:</b> {vol["read"]}. '
                f'<b>Fits the setup:</b> {r["hint"]}.</div>', unsafe_allow_html=True)

    tabs = st.tabs(["Chart", "Key metrics", "Valuation", "Signals", "Earnings", "Options",
                    f"Company news ({len(r['company_news'])})",
                    f"Political & policy ({len(r['political_news'])})", "About"])
    with tabs[0]: chart_tab(r)
    with tabs[1]: metrics_tab(info)
    with tabs[2]: valuation_tab(val)
    with tabs[3]: signals_tab(drn)
    with tabs[4]: earnings_tab(r)
    with tabs[5]: options_tab(r)
    with tabs[6]: news_list(r["company_news"], political=False)
    with tabs[7]: news_list(r["political_news"], political=True)
    with tabs[8]:
        st.write(info.get("longBusinessSummary") or "No description available.")
        if info.get("website"):
            st.markdown(f"[{info['website']}]({info['website']})")


def chart_tab(r):
    h = r["hist"]
    if h is None or h.empty:
        st.info("No price history.")
        return
    span = st.segmented_control("Range", ["1M", "3M", "6M", "1Y", "2Y"], default="6M",
                                key=f"rng_{r['symbol']}")
    days = {"1M": 22, "3M": 66, "6M": 130, "1Y": 252, "2Y": 504}[span or "6M"]
    d = h.tail(days)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[.62, .18, .2],
                        vertical_spacing=.03)
    fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close,
                                 name="Price", increasing_line_color=GREEN,
                                 decreasing_line_color=RED), 1, 1)
    for col, colr in [("SMA20", "#9aa5b8"), ("SMA50", "#4c8dff"), ("SMA200", AMBER)]:
        fig.add_trace(go.Scatter(x=d.index, y=d[col], name=col, line=dict(width=1.4, color=colr)), 1, 1)
    fv = r["valuation"].get("fair_value")
    if fv:
        fig.add_hline(y=fv, line_dash="dot", line_color=tone(r["valuation"]["verdict"]),
                      annotation_text=f"Fair value {money(fv)}", row=1, col=1)
    fig.add_trace(go.Bar(x=d.index, y=d.Volume, name="Volume", marker_color="#6b7486"), 2, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d.RSI, name="RSI", line=dict(color="#b48cff")), 3, 1)
    for y in (30, 70):
        fig.add_hline(y=y, line_dash="dot", line_color=MUTED, row=3, col=1)
    fig.update_layout(height=620, margin=dict(l=10, r=10, t=10, b=10), xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", y=1.04), hovermode="x unified")
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(fig, width="stretch")


METRIC_GROUPS = {
    "Valuation multiples": [
        ("Market cap", "marketCap", money), ("Enterprise value", "enterpriseValue", money),
        ("P/E (trailing)", "trailingPE", num), ("P/E (forward)", "forwardPE", num),
        ("PEG ratio", "pegRatio", num), ("Price / book", "priceToBook", num),
        ("Price / sales", "priceToSalesTrailing12Months", num),
        ("EV / EBITDA", "enterpriseToEbitda", num), ("EV / revenue", "enterpriseToRevenue", num)],
    "Profitability": [
        ("Gross margin", "grossMargins", pct), ("Operating margin", "operatingMargins", pct),
        ("Net margin", "profitMargins", pct), ("EBITDA margin", "ebitdaMargins", pct),
        ("Return on equity", "returnOnEquity", pct), ("Return on assets", "returnOnAssets", pct)],
    "Growth & earnings": [
        ("Revenue (TTM)", "totalRevenue", money), ("Revenue growth (YoY)", "revenueGrowth", pct),
        ("Earnings growth (YoY)", "earningsGrowth", pct), ("EPS (trailing)", "trailingEps", num),
        ("EPS (forward)", "forwardEps", num), ("Dividend yield", "dividendYield",
                                               lambda v: "—" if v is None else f"{v:.2f}%" if v > 0.5 else pct(v, 2))],
    "Balance sheet & cash": [
        ("Cash", "totalCash", money), ("Debt", "totalDebt", money),
        ("Debt / equity", "debtToEquity", lambda v: num(v / 100 if v else v)),
        ("Current ratio", "currentRatio", num), ("Quick ratio", "quickRatio", num),
        ("Free cash flow", "freeCashflow", money), ("Operating cash flow", "operatingCashflow", money)],
    "Risk & positioning": [
        ("Beta", "beta", num), ("52-week high", "fiftyTwoWeekHigh", money),
        ("52-week low", "fiftyTwoWeekLow", money), ("Short % of float", "shortPercentOfFloat", pct),
        ("Short ratio (days)", "shortRatio", num), ("Institutional ownership", "heldPercentInstitutions", pct),
        ("Analyst target (mean)", "targetMeanPrice", money),
        ("Analyst target range", None, None), ("Analyst rating", "recommendationKey",
                                               lambda v: (v or "—").replace("_", " ").title())],
}


def metrics_tab(info):
    cols = st.columns(len(METRIC_GROUPS))
    for col, (group, items) in zip(cols, METRIC_GROUPS.items()):
        lines = [f"**{group}**"]
        for label, key, f in items:
            if key is None:
                v = f"{money(info.get('targetLowPrice'))} – {money(info.get('targetHighPrice'))}"
            else:
                v = f(info.get(key))
            lines.append(f"<div style='display:flex;justify-content:space-between;gap:8px;"
                         f"padding:5px 0;border-bottom:1px solid rgba(138,148,166,.15)'>"
                         f"<span class='small'>{label}</span><b style='white-space:nowrap'>{v}</b></div>")
        col.markdown(lines[0])
        col.markdown("".join(lines[1:]), unsafe_allow_html=True)


def valuation_tab(val):
    if not val.get("models"):
        st.info("Not enough fundamentals to value this one (common for ETFs and loss-making companies).")
        return
    price = val["price"]
    st.markdown(f"Blended fair value **{money(val['fair_value'])}** vs price **{money(price)}** → "
                f"{tag(val['verdict'])} &nbsp; ({pct(val['upside'], 0, True)}). "
                f"Range across models: {money(val['low'])} – {money(val['high'])}.",
                unsafe_allow_html=True)
    fig = go.Figure()
    names = [m[0] for m in val["models"]]
    vals = [m[1] for m in val["models"]]
    fig.add_trace(go.Bar(y=names, x=vals, orientation="h",
                         marker_color=[GREEN if v > price else RED for v in vals],
                         text=[money(v) for v in vals], textposition="outside"))
    fig.add_vline(x=price, line_color="#cbd2dc", line_dash="dash", annotation_text="Price")
    fig.add_vline(x=val["fair_value"], line_color=AMBER, annotation_text="Blended")
    fig.update_layout(height=80 + 52 * len(names), margin=dict(l=10, r=40, t=30, b=10),
                      yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, width="stretch")
    st.dataframe(pd.DataFrame([{"Model": m[0], "Fair value": money(m[1]),
                                "vs price": pct(m[1] / price - 1, 0, True),
                                "Weight": pct(m[2], 0), "How": m[3]} for m in val["models"]]),
                 hide_index=True, width="stretch")
    st.caption("Above +15% = undervalued, below −15% = overvalued. Weights are re-balanced across "
               "whichever models have data.")


def signals_tab(drn):
    if not drn["signals"]:
        st.info("No signals available.")
        return
    st.markdown(f"Overall: {tag(drn['label'])} &nbsp; score **{drn['score']:+.2f}**, "
                f"certainty **{drn['certainty']}%**", unsafe_allow_html=True)
    html = []
    for name, s in sorted(drn["signals"].items(), key=lambda kv: -abs(kv[1]["contribution"])):
        v = s["value"]
        colr = GREEN if v > 0.05 else RED if v < -0.05 else AMBER
        left = 50 if v >= 0 else 50 + v * 50
        width = abs(v) * 50
        html.append(
            f"<div style='display:grid;grid-template-columns:minmax(0,190px) minmax(0,1fr) 70px;"
            f"gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid rgba(138,148,166,.15)'>"
            f"<div><b>{name}</b><div class='small'>weight {s['weight']:.0%}</div></div>"
            f"<div><div class='bar'><i style='left:{left}%;width:{width}%;background:{colr}'></i>"
            f"<i style='left:50%;width:1px;background:#8a94a6'></i></div>"
            f"<div class='small' style='margin-top:4px'>{s['detail']}</div></div>"
            f"<div style='text-align:right;color:{colr};font-weight:700'>{v:+.2f}</div></div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    st.caption("Certainty blends how strong the combined score is, how many signals agree, and how "
               "much data was available. It is a confidence index from a rules-based model, not a "
               "back-tested probability.")


def earnings_tab(r):
    e = r["earnings"]
    nd = e.get("next_date")
    c = st.columns(3)
    c[0].markdown(kpi("Next earnings", f"{nd:%b %d, %Y}" if nd else "—",
                      "Date per Yahoo; confirm with company IR"), unsafe_allow_html=True)
    c[1].markdown(kpi("EPS estimate", num(e.get("next_eps_est")),
                      f"Revenue est. {money(e.get('next_rev_est'))}" if e.get("next_rev_est") else ""),
                  unsafe_allow_html=True)
    em = r["earn_move"]
    c[2].markdown(kpi("Move priced in", f"±{em['move']*100:.1f}%" if em else "—",
                      f"ATM straddle {money(em['straddle'])} exp {em['expiry']}" if em else
                      "No listed expiry after the date yet"), unsafe_allow_html=True)
    h = e.get("history")
    if h is not None and not h.empty and "Reported EPS" in h.columns:
        hh = h.sort_index()
        fig = go.Figure()
        x = [f"{d:%b %Y}" for d in hh.index]
        if "EPS Estimate" in hh:
            fig.add_trace(go.Bar(x=x, y=hh["EPS Estimate"], name="Estimate", marker_color="#5b6578"))
        fig.add_trace(go.Bar(x=x, y=hh["Reported EPS"], name="Reported",
                             marker_color=[GREEN if (s or 0) >= 0 else RED
                                           for s in hh.get("Surprise(%)", pd.Series(0, index=hh.index))]))
        fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=30, b=10),
                          title="EPS: estimate vs reported", legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")
        show = hh.sort_index(ascending=False).copy()
        show.index = [f"{d:%Y-%m-%d}" for d in show.index]
        st.dataframe(show, width="stretch")
    f = r["financials"]
    if f is not None and not f.empty:
        st.markdown("**Quarterly results**")
        t = f.copy()
        t.index = [f"{d:%b %Y}" for d in t.index]
        fmt = t.T.copy()
        for col in fmt.columns:
            fmt[col] = [pct(v) if idx == "Net margin" else num(v) if idx == "Diluted EPS" else money(v)
                        for idx, v in zip(fmt.index, fmt[col])]
        st.dataframe(fmt, width="stretch")
    if r.get("recs"):
        rc = r["recs"]
        st.markdown("**Analyst ratings (current month)**")
        fig = go.Figure(go.Bar(x=list(rc.values()), y=["Strong buy", "Buy", "Hold", "Sell", "Strong sell"],
                               orientation="h", marker_color=[GREEN, "#7fd8a8", AMBER, "#f59a97", RED]))
        fig.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, width="stretch")


def options_tab(r):
    o = r["options"]
    ex = o.get("expiries")
    if ex is None or ex.empty:
        st.info("No listed options found for this symbol.")
        return
    c = st.columns(4)
    c[0].markdown(kpi("ATM implied vol", pct(r["vol"]["iv"], 0)), unsafe_allow_html=True)
    c[1].markdown(kpi("IV / 30d realised", num(r["vol"]["ratio"]),
                      "&gt;1.3 rich · &lt;0.9 cheap"), unsafe_allow_html=True)
    c[2].markdown(kpi("Put/call open interest", num(o.get("pc_oi")),
                      "&gt;1.2 defensive · &lt;0.7 bullish"), unsafe_allow_html=True)
    c[3].markdown(kpi("Put/call volume", num(o.get("pc_vol")), "today's flow"), unsafe_allow_html=True)

    fig = go.Figure(go.Scatter(x=ex["Expiry"], y=ex["ATM IV"] * 100, mode="lines+markers",
                               line=dict(color="#4c8dff")))
    fig.update_layout(title="IV term structure (ATM, %)", height=260, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")

    show = ex.copy()
    show["ATM IV"] = show["ATM IV"].map(lambda v: pct(v, 1))
    show["Expected move"] = show["Expected move"].map(lambda v: f"±{v*100:.1f}%" if pd.notna(v) else "—")
    show["Straddle"] = show["Straddle"].map(money)
    show["Max pain"] = show["Max pain"].map(money)
    show["Put/Call OI"] = show["Put/Call OI"].map(num)
    show["Put/Call vol"] = show["Put/Call vol"].map(num)
    st.dataframe(show, hide_index=True, width="stretch")

    exp = st.selectbox("Open interest by strike", list(o["chains"].keys()), key=f"exp_{r['symbol']}")
    if exp:
        calls, puts = o["chains"][exp]
        px = r["info"]["price"]
        lo, hi = px * 0.75, px * 1.25
        cc, pp = calls[(calls.strike >= lo) & (calls.strike <= hi)], puts[(puts.strike >= lo) & (puts.strike <= hi)]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=cc.strike, y=cc.openInterest, name="Calls", marker_color=GREEN))
        fig.add_trace(go.Bar(x=pp.strike, y=-pp.openInterest, name="Puts", marker_color=RED))
        fig.add_vline(x=px, line_dash="dash", line_color="#cbd2dc", annotation_text="Spot")
        fig.update_layout(barmode="relative", height=320, margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")
        with st.expander("Full chain"):
            cols = ["contractSymbol", "strike", "lastPrice", "bid", "ask", "volume", "openInterest",
                    "impliedVolatility", "inTheMoney"]
            a, b = st.columns(2)
            a.markdown("**Calls**"); a.dataframe(calls[[c for c in cols if c in calls]], hide_index=True)
            b.markdown("**Puts**"); b.dataframe(puts[[c for c in cols if c in puts]], hide_index=True)


def news_list(items, political):
    if not items:
        st.info("No recent stories found.")
        return
    if political:
        only = st.toggle("Only stories that name this company", key=f"direct_{id(items)}")
        if only:
            items = [i for i in items if i.get("direct")]
    html = []
    for it in items:
        s = it.get("sentiment", 0)
        lab = "Positive" if s > 0.15 else "Negative" if s < -0.15 else "Neutral"
        colr = GREEN if s > 0.15 else RED if s < -0.15 else MUTED
        extra = ""
        if political:
            extra = (f" · relevance {it['relevance']:.0%}" + (" · names company" if it.get("direct") else "")
                     + (f" · {', '.join(it['themes'])}" if it.get("themes") else ""))
        title = _html.escape(it["title"] or "")
        link = _html.escape(it.get("link") or "#", quote=True)
        html.append(f"<div class='news'><a href='{link}' target='_blank'>{title}</a>"
                    f"<div class='m'>{tag(lab, colr)} &nbsp;{_html.escape(it.get('source') or '')} · {ago(it.get('hours'))}"
                    f"{extra}</div></div>")
    st.markdown("".join(html), unsafe_allow_html=True)


board()
