# Options Intel

A live research dashboard for options trading, with three views:

- **Market scanner**: every stock in the S&P 500 and Nasdaq-100 (about 520), plus all ~3,000 Nasdaq-listed stocks if you switch that on. Each one is scored for over/undervalued and bullish/bearish with a certainty %. You also get a sector heat map, stand-out lists (most undervalued, strongest bullish and bearish, earnings this week), filters, and sortable columns with 30+ metrics. Click any stock to run the full analysis.
- **My watchlist**: the full analysis for your own tickers, side by side.
- **Look up a company**: the full analysis for any US ticker.

The full analysis for a company pulls:

- **Prices**: candlestick chart, 20/50/200-day averages, volume, RSI
- **Key financial metrics**: valuation multiples, margins, returns, growth, balance sheet, cash flow, short interest, analyst targets
- **Earnings**: next date, EPS estimate, the last 8 quarters of beats and misses, quarterly revenue and income, and the move the options market is pricing in for earnings
- **Options**: at-the-money implied volatility, IV vs 30-day realised volatility, IV term structure, expected move per expiry, put/call ratios, max pain, open interest by strike, full chains
- **Company news** with a sentiment score on each headline
- **Political and policy news** (tariffs, export controls, the Fed, Congress, regulators, sanctions and so on), ranked by how relevant each story is to the company and its sector

From all of that it gives you:

- **Over or undervalued**: a blended fair value from up to five models (analyst consensus, DCF, growth-adjusted P/E, Graham number, EV/EBITDA). More than 15% above the price counts as undervalued; more than 15% below counts as overvalued.
- **Bullish or bearish, with a certainty %**: ten weighted signals (trend, momentum, RSI, MACD, analysts, earnings surprises, company news, political news, options positioning, valuation gap). Certainty runs from 50% (coin flip) to 95% (cap). It depends on how strong the combined signal is, how many signals agree, and how much data was available.
- **A strategy fit**: combines the direction with whether options are currently cheap or expensive.

Every score shows its working on the **Valuation** and **Signals** tabs.

The page refreshes on a timer you choose (1 to 30 minutes). You can also press **Refresh now** in the sidebar.

---

## Put it online (free, about 10 minutes)

1. Create a free account at **github.com**. Make a new repository called `options-intel` and upload every file in this folder to it, keeping the `.streamlit` folder. You can drag and drop the files on the repository page.
2. Go to **share.streamlit.io** and sign in with GitHub.
3. Click **Create app**, then **Deploy a public app from GitHub**, and choose:
   - Repository: `your-name/options-intel`
   - Branch: `main`
   - Main file path: `app.py`
4. Click **Deploy**. In a couple of minutes you get a link such as `options-intel.streamlit.app` that works on your phone and laptop.

Your watchlist is saved in the page link (`?t=NVDA,AAPL,...`). Bookmark it after you set the watchlist up.

To keep the app private, open the app's **Settings → Sharing** on Streamlit Cloud and limit it to your own email.

## Run it on your own computer

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501.

## Files

| File | What it does |
|---|---|
| `app.py` | The dashboard (layout, charts, tabs, auto-refresh) |
| `scanner.py` | Background scanner that works through every stock in the chosen markets |
| `universe.py` + `universe/` | S&P 500, Nasdaq-100 and all-Nasdaq ticker lists (downloaded daily, with bundled backups) |
| `engine.py` | Runs each ticker's analysis and caches results so refreshes don't overload the data sources |
| `data.py` | Prices, fundamentals, earnings, options chains (Yahoo Finance) |
| `news.py` | Company and political news (Yahoo plus Google News) and headline sentiment |
| `signals.py` | Valuation models, bullish/bearish scoring, certainty, volatility read |
| `tests/` | Offline test harness with simulated market data |

## Tuning

- **Signal weights**: `WEIGHTS` in `signals.py`
- **Valuation thresholds** (±15%) and **model weights**: `valuation()` in `signals.py`
- **Political themes per sector**: `SECTOR_THEMES` in `news.py`. For example, add "rare earth" to Technology.
- **Default watchlist**: `default_watch` in `app.py`

## Good to know

- **How the scanner works:** it runs in the background and is shared by everyone who opens the app. Prices for every stock refresh on your chosen timer. Fundamentals (multiples, margins, analyst targets) refresh once a day. After the app wakes up, the first full load takes about 5 minutes for S&P 500 + Nasdaq-100, and 20 to 30 minutes with all Nasdaq-listed stocks. The table fills in as data arrives.
- **Quick scan vs full analysis:** the scanner's direction uses 6 of the 10 signals (trend, momentum, RSI, MACD, analysts, valuation). Its certainty is capped lower because less data goes in. Opening a company adds news, political news, earnings surprises and options flow. Those need about 15 calls per stock, which free data can't support for thousands of stocks at once.
- **Sleeping:** free Streamlit apps go to sleep after a stretch with no visitors. Opening the link wakes the app up, and the scan restarts.

- The data is free, so quotes can be about 15 minutes delayed and Yahoo sometimes rate-limits for a minute. Caching (2 minutes for prices, 7 to 15 minutes for news and fundamentals) keeps this rare. For real-time quotes you can later swap `data.py` to a paid feed such as Polygon, Tradier or Finnhub.
- ETFs such as SPY have no earnings or valuation models, so they show "Not enough data" for valuation. Their direction and options data still work.
- Certainty comes from a transparent rules-based model, not a back-tested probability. Treat it as a research aid, not financial advice.
