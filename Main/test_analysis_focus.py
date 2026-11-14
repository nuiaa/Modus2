import unittest
from analysis_focus import resolve_focus, symbols_for_focus, fred_for_focus


class FocusTests(unittest.TestCase):
    def test_followup_inherits_gold(self):
        history = [{"role": "user", "content": "Altında ne bekliyorsun?"},
                   {"role": "assistant", "content": "Altında iki senaryo var."}]
        self.assertEqual(resolve_focus("Uzun vadede ne olur?", history), "gold")
        self.assertIn("GC=F", symbols_for_focus("gold"))
        self.assertIn("DFII10", fred_for_focus("gold"))

    def test_explicit_new_asset_overrides_old_gold(self):
        history = [{"role": "user", "content": "Altında ne bekliyorsun?"}]
        self.assertEqual(resolve_focus("S&P 500 için trend nedir?", history), "spx")
        self.assertIn("^GSPC", symbols_for_focus("spx"))

    def test_explicit_cashtag(self):
        self.assertEqual(resolve_focus("$AAPL geçen yıla göre nasıl?"), "AAPL")
        self.assertEqual(symbols_for_focus("AAPL"), ("AAPL",))

    def test_below_is_not_gold(self):
        self.assertEqual(resolve_focus("NVDA 50 günlük ortalamanın altında mı?"), "NVDA")
        self.assertIsNone(resolve_focus("Fiyat desteğin altına indi mi?"))
        self.assertEqual(resolve_focus("Altın 4000 doların altına iner mi?"), "gold")
        self.assertEqual(resolve_focus("^GSPC ne durumda?"), "spx")


if __name__ == "__main__":
    unittest.main()
