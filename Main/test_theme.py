import unittest

import theme


class PaletteTests(unittest.TestCase):
    def test_same_keys(self):
        self.assertEqual(set(theme.LIGHT), set(theme.DARK))

    def test_values_map_back_to_one_token(self):
        # resolve() maps a stored colour back to its token, so a hex value may
        # only ever mean one token across both palettes.
        owners = {}
        for palette in (theme.LIGHT, theme.DARK):
            for token, value in palette.items():
                owners.setdefault(value.upper(), set()).add(token)
        clashes = {value: tokens for value, tokens in owners.items() if len(tokens) > 1}
        self.assertEqual(clashes, {})

    def test_resolve_switches_palette(self):
        try:
            theme.apply('light', dark=False)
            self.assertEqual(theme.resolve(theme.DARK['label']), theme.LIGHT['label'])
            self.assertEqual(theme.resolve('#57D4A0'), theme.LIGHT['green'])  # old cached colour
            theme.apply('dark', dark=True)
            self.assertEqual(theme.resolve(theme.LIGHT['on_accent']), theme.DARK['on_accent'])
            self.assertEqual(theme.resolve('#123456'), '#123456')
        finally:
            theme.apply('light', dark=False)

    def test_registered_names_follow_theme(self):
        namespace = {}
        theme.register(namespace)
        theme.apply('dark', dark=True)
        self.assertEqual(namespace['WHITE'], theme.DARK['label'])
        theme.apply('light', dark=False)
        self.assertEqual(namespace['WHITE'], theme.LIGHT['label'])


if __name__ == '__main__':
    unittest.main()
