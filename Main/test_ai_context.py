"""Exercise the real AI context builder without importing the Kivy UI on the host."""
import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from analysis_focus import fred_for_focus, resolve_focus
import context_features
from market_feed import MARKET_DYNAMICS, YAHOO_MACROS


def context_methods():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    screen = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AIScreen")
    methods = [node for node in screen.body if isinstance(node, ast.FunctionDef)
               and node.name in ("_build_context_summary", "_format_trend_context")]
    module = ast.Module(body=methods, type_ignores=[])
    namespace = {"datetime": datetime, "timezone": timezone, "YAHOO_MACROS": YAHOO_MACROS,
                 "MARKET_DYNAMICS": MARKET_DYNAMICS,
                 "fred_for_focus": fred_for_focus, "resolve_focus": resolve_focus}
    namespace.update({name: getattr(context_features, name) for name in dir(context_features)
                      if not name.startswith("_")})
    exec(compile(ast.fix_missing_locations(module), "main.py", "exec"), namespace)
    return namespace


class ContextTests(unittest.TestCase):
    def test_fiscal_and_external_data_reach_gold_ai_context(self):
        ns = context_methods()
        class State:
            last_market_data = {
                "fetched_at": "2026-11-13T12:00:00+00:00",
                "fred_metrics": [{
                    "id": "Faiz Ödemesi / Vergi Geliri", "name": "Faiz Ödemesi / Vergi Geliri",
                    "value": 33.5, "unit": "%", "date": "2026-04-01", "source": "FRED türevi",
                    "notes": "aynı çeyrek", "stale": False
                }],
                "external_metrics": [{
                    "id": "GPR_CLASSIC", "name": "Classic GPR", "value": 150.5,
                    "unit": "index", "date": "2026-10-01", "source": "Iacoviello",
                    "notes": "monthly", "stale": False
                }]
            }
        ns["AppState"] = State
        class Screen:
            chat_history = [{"role": "user", "content": "Altın ne olur?"}]
            _format_trend_context = ns["_format_trend_context"]
            _build_context_summary = ns["_build_context_summary"]
        text = Screen()._build_context_summary("Uzun vadede ne olur?")
        self.assertIn("Faiz Ödemesi / Vergi Geliri", text)
        self.assertIn("Classic GPR: 150.500", text)
        self.assertIn("2026-10-01", text)

    def test_flip_and_daily_dynamics_reach_context(self):
        ns = context_methods()
        class State:
            last_market_data = {
                "fetched_at": "2026-11-13T12:00:00+00:00",
                "junk_stress": ("-0.42%", "red"),
                "btc_momentum": ("+1.10% (Pozitif)", "green"),
                "cu_au": ("+0.50% günlük (oran 0.001100; USD/lb ÷ USD/ons)", "green"),
                "multi_gex_cards": [{"name": "Gold ETF (GLD)", "spot_str": "300.00", "horizons": [
                    {"label": "20.11.2026", "put_w": "290.00", "call_w": "310.00",
                     "flip_lvl": "298.50", "gex_str": "+1.0M (tahmini)"}]}],
            }
        ns["AppState"] = State
        class Screen:
            chat_history = []
            _format_trend_context = ns["_format_trend_context"]
            _build_context_summary = ns["_build_context_summary"]
        gold = Screen()._build_context_summary("Altın ne olur?")
        self.assertIn("Flip=298.50", gold)
        self.assertIn("put duvarı spota göre -3.33%", gold)
        self.assertIn("spot flip'in üstünde", gold)
        self.assertIn("Bakır/altın vadeli oranı günlük değişimi: +0.50%", gold)
        self.assertNotIn("BTC günlük", gold)
        general = Screen()._build_context_summary("Piyasa nasıl?")
        for text in ("HYG/TLT ETF oranı günlük değişimi (kredi riski iştahı vekili): -0.42%",
                     "BTC günlük değişimi (Yahoo son iki günlük bar): +1.10%", "Bakır/altın"):
            self.assertIn(text, general)

    def test_new_dynamics_reach_matching_focus_only(self):
        ns = context_methods()
        class State:
            last_market_data = {
                "fetched_at": "2026-11-13T12:00:00+00:00",
                "crack_321": ("44.46 USD/varil (-1.60 günlük)", "white"),
                "breadth_rsp_spy": ("+0.56% günlük (oran 0.2932)", "green"),
            }
        ns["AppState"] = State
        class Screen:
            chat_history = []
            _format_trend_context = ns["_format_trend_context"]
            _build_context_summary = ns["_build_context_summary"]
        oil = Screen()._build_context_summary("Petrol ne olur?")
        self.assertIn("3-2-1 Crack Spread (USD/varil): 44.46 USD/varil", oil)
        self.assertIn("Rafineri marjı vekili", oil)
        self.assertNotIn("RSP/SPY", oil)
        spx = Screen()._build_context_summary("S&P 500 ne olur?")
        self.assertIn("RSP/SPY Oranı Günlük Değişimi (Piyasa Genişliği): +0.56%", spx)
        self.assertNotIn("Crack", spx)

    def test_external_focus_calendar_headlines_and_vol_gap(self):
        ns = context_methods()
        class State:
            last_market_data = {
                "fetched_at": "2026-11-13T12:00:00+00:00",
                "macro_observations": {"^GVZ": {"value": 25.0, "timestamp": 0}},
                "calendar_week": ["2026-11-13 1:30pm PPI m/m, önceki 1.3%"],
                "headlines": [{"source": "Fed", "time": "2026-11-13 19:00 UTC", "title": "Fed holds rates"}],
                "external_metrics": [
                    {"id": "COT_GOLD", "name": "Altın COT", "value": 37.5, "unit": "endeks", "date": "2026-11-03",
                     "source": "CFTC", "notes": "", "focus": ("gold",)},
                    {"id": "COT_BTC", "name": "Bitcoin COT", "value": 99.0, "unit": "endeks", "date": "2026-11-03",
                     "source": "CFTC", "notes": "", "focus": ("btc",)},
                    {"id": "FOMC_NEXT", "name": "Sonraki FOMC", "value": 25, "unit": "gün", "date": "2026-11-14",
                     "source": "Fed", "notes": "", "focus": None},
                ],
            }
        ns["AppState"] = State
        class Screen:
            chat_history = []
            _format_trend_context = ns["_format_trend_context"]
            _build_context_summary = ns["_build_context_summary"]
        trend = [{"symbol": "GC=F", "latest_close": 3886.3, "observation_date": "2026-11-13",
                  "observation_count": 300, "volatility_20d_pct": 20.0,
                  "sma": {"200": {"value": 3500.0}}}]
        gold = Screen()._build_context_summary("Altın ne olur?", "gold", trend,
                                               cross_lines=["Göreli seviye — VIX 18.000: son 1y içinde persentil %62"])
        self.assertIn("yön sinyali değildir", gold)
        self.assertIn("Altın COT: 37.500", gold)
        self.assertNotIn("Bitcoin COT", gold)
        self.assertIn("Sonraki FOMC", gold)
        self.assertIn("GVZ 25.00 − 20 günlük gerçekleşen %20.00 = +5.00", gold)
        self.assertIn("SMA200'ün +11.04% üstünde", gold)
        self.assertNotIn("bar SMA", gold)
        self.assertIn("PPI m/m", gold)
        self.assertIn("Fed holds rates", gold)


if __name__ == "__main__":
    unittest.main()
