import sys, os, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["OI_CACHE_DIR"] = "/tmp/oi_test_cache"
import fake_market; fake_market.install()
import universe, scanner, engine
for k in ["S&P 500", "Nasdaq-100"]:
    print(k, len(universe.load(universe.UNIVERSES[k])))
u = universe.combined(["S&P 500", "Nasdaq-100"]); print("combined", len(u), u.head(3).to_dict("records"))
sc = scanner.Scanner(); sc.configure(["S&P 500", "Nasdaq-100"], ["NVDA", "PLTR"], 10)
t0 = time.time(); sc.start()
while sc.fundamentals_loaded() < len(sc.uni) and time.time() - t0 < 240:
    time.sleep(3)
print("scan", sc.progress(), round(time.time() - t0), "s")
df = sc.table(0.0425)
print(df.shape); print(df["Valuation"].value_counts().to_dict()); print(df["Direction"].value_counts().to_dict())
print(df[["Ticker","Price","Day %","Fair value gap %","Direction","Certainty %","Next earnings"]].head(4))

from streamlit.testing.v1 import AppTest
at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=300)
at.run()
print("scanner view exceptions:", [e.value for e in at.exception], "md:", len(at.markdown), "df:", len(at.dataframe))
for v in ["My watchlist", "Look up a company"]:
    at.segmented_control(key="view").set_value(v).run()
    print(v, "exceptions:", [e.value for e in at.exception], "df:", len(at.dataframe), "tabs:", len(at.tabs))
at.text_input(key="lookup").input("AMD").run()
print("lookup exceptions:", [e.value for e in at.exception], "tabs:", len(at.tabs))
