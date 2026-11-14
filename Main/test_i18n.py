import ast
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

import i18n
from alarm_logic import evaluate_alarm

HERE = Path(__file__).parent
PLACEHOLDER = re.compile(r"\{\w+\}")


def code_tr_literals():
    """First arguments of tr(...) calls written as string literals in app modules."""
    found = set()
    for name in ("main.py", "alarm_logic.py", "service.py"):
        tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.keys = json.loads((HERE / "locales" / "keys.json").read_text(encoding="utf-8"))

    def tearDown(self):
        i18n.set_language("tr")

    def test_every_language_has_a_complete_aligned_catalog(self):
        for code in i18n.CODES:
            if code == i18n.SOURCE:
                continue
            values = json.loads((HERE / "locales" / f"{code}.json").read_text(encoding="utf-8"))
            self.assertEqual(len(values), len(self.keys), code)
            for key, value in zip(self.keys, values):
                self.assertTrue(value.strip(), (code, key))
                self.assertEqual(set(PLACEHOLDER.findall(key)), set(PLACEHOLDER.findall(value)), (code, key))

    def test_keys_are_unique(self):
        self.assertEqual(len(self.keys), len(set(self.keys)))

    def test_every_tr_literal_in_code_is_translatable(self):
        missing = sorted(code_tr_literals() - set(self.keys))
        self.assertEqual(missing, [])


class LookupTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("tr")

    def test_source_language_is_identity(self):
        i18n.set_language("tr")
        self.assertEqual(i18n.tr("Güncel: {value}", value="5"), "Güncel: 5")
        self.assertEqual(i18n.trd("Veri yok"), "Veri yok")

    def test_translation_with_placeholders(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("Güncellendi {time}", time="10:00"), "Updated 10:00")
        self.assertEqual(i18n.tr("Bilinmeyen metin"), "Bilinmeyen metin")

    def test_data_strings_translate_whole_and_by_fragment(self):
        i18n.set_language("en")
        self.assertEqual(i18n.trd("Altın Vadeli (USD/ons)"), "Gold Futures (USD/oz)")
        self.assertEqual(i18n.trd("+0.42% (Pozitif)"), "+0.42% (Positive)")
        self.assertEqual(i18n.trd("+1,234.0M (tahmini)"), "+1,234.0M (estimate)")
        self.assertEqual(i18n.trd("12.5 milyon varil"), "12.5 million barrels")
        # Fragments only replace whole words: "günlük" must not match inside other words.
        self.assertEqual(i18n.trd("Günlükçü"), "Günlükçü")

    def test_missing_language_entry_falls_back_to_english(self):
        i18n.set_language("de")
        self.assertEqual(i18n.tr("Bilinmeyen metin"), "Bilinmeyen metin")
        self.assertEqual(i18n.tr("Alarmlar"), "Alarme")

    def test_alarm_notifications_follow_the_language(self):
        i18n.set_language("en")
        hit, title, message = evaluate_alarm(
            {"symbol": "Altın Vadeli (USD/ons)", "cond_type": "crossing", "target_value": 100,
             "last_seen_value": 99}, 101)
        self.assertTrue(hit)
        self.assertEqual(title, "ALARM: Gold Futures (USD/oz) CROSSED (100.00)")
        self.assertIn("Current: 101.00", message)

    def test_language_preference_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "language.json")
            i18n.save_language("ja", path)
            self.assertEqual(i18n.load_language(path), "ja")
            i18n.save_language("xx", path)
            self.assertEqual(i18n.load_language(path), "ja")

    def test_ai_language_name(self):
        self.assertEqual(i18n.ai_language_name("ar"), "Arabic")
        self.assertEqual(i18n.ai_language_name("zh"), "Simplified Chinese")


if __name__ == "__main__":
    unittest.main()
