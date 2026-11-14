"""Resolve the asset in short follow-up questions without making up tickers."""
import re

ASSETS = {
    "gold": {"symbols": ("GC=F", "GLD", "DX-Y.NYB", "HG=F"),
             "fred": ("DFII10", "T10YIE", "T5YIE", "T5YIFR", "DGS10", "T10Y3M",
                      "M2SL", "WALCL", "RRPONTSYD", "BAMLH0A0HYM2", "THREEFYTP10",
                      "FDHBFIN", "IRLTLT01JPM156N", "IRLTLT01USM156N")},
    "spx": {"symbols": ("^GSPC", "SPY", "DX-Y.NYB"),
            "fred": ("DFII10", "DGS10", "T10Y2Y", "T10Y3M", "NFCI", "M2SL",
                     "BAMLH0A0HYM2", "THREEFYTP10", "IRLTLT01JPM156N", "IRLTLT01USM156N")},
    "silver": {"symbols": ("SI=F", "SLV", "DX-Y.NYB"),
               "fred": ("DFII10", "T10YIE", "T5YIFR", "DGS10", "M2SL", "BAMLH0A0HYM2")},
    "oil": {"symbols": ("CL=F", "USO", "DX-Y.NYB"),
            "fred": ("T10YIE", "T10Y2Y", "T10Y3M", "NFCI", "DGS10")},
    "brent": {"symbols": ("BZ=F", "DX-Y.NYB"),
              "fred": ("T10YIE", "T10Y2Y", "T10Y3M", "NFCI", "DGS10")},
    "btc": {"symbols": ("BTC-USD", "DX-Y.NYB"),
            "fred": ("DFII10", "T10Y3M", "NFCI", "M2SL", "WALCL", "RRPONTSYD")},
    "dollar": {"symbols": ("DX-Y.NYB", "JPY=X"),
               "fred": ("DFII10", "T10YIE", "T10Y2Y", "T10Y3M", "DGS10",
                        "IRLTLT01JPM156N", "IRLTLT01USM156N")},
}

PATTERNS = (
    ("gold", r"gold|xau|gld\b|gc=f"),
    ("spx", r"s&p\s*500|s&p|spx\b|sp500\b|s&p500|\^gspc|spy\b"),
    ("silver", r"g[üu]m[üu][şs]|silver|slv\b|si=f"),
    ("brent", r"brent\b|bz=f"),
    ("oil", r"petrol|oil\b|wti\b|uso\b|cl=f"),
    ("btc", r"bitcoin|btc\b|kripto|btc-usd"),
    ("dollar", r"dolar endeks|dxy\b|usd/jpy|usd/cnh"),
)

KNOWN_TICKERS = {"AAPL", "MSFT", "NVDA", "TSLA", "AMD", "AMZN", "GOOGL", "META",
                 "SPY", "QQQ", "GLD", "SLV", "USO", "TLT", "HYG", "EEM"}


# "X'in altında/altına/altından" means "below X", not gold; other forms of "altın" are gold.
_GOLD_WORD = re.compile(r"\balt[ıi]n(\w*)")
_BELOW_SUFFIXES = {"a", "da", "dan", "daki"}
_GENITIVE = re.compile(r"[ıiuü]n$")
_NOT_GENITIVE = {"bugün", "dün", "yarın", "için"}


def _mentions_gold(lower_text):
    for match in _GOLD_WORD.finditer(lower_text):
        if match.group(1) not in _BELOW_SUFFIXES:
            return True
        previous = lower_text[:match.start()].split()
        word = previous[-1].strip(",.;:!?") if previous else ""
        if not word or word in _NOT_GENITIVE or not _GENITIVE.search(word):
            return True
    return False


def explicit_focus(text):
    text = str(text or "")
    upper = text.upper()
    cashtags = re.findall(r"\$([A-Z][A-Z0-9.^=-]{0,11})\b", upper)
    if cashtags:
        return cashtags[-1]
    lower = text.lower()
    for asset, pattern in PATTERNS:
        if re.search(pattern, lower) or (asset == "gold" and _mentions_gold(lower)):
            return asset
    tickers = re.findall(r"\b[A-Z]{2,5}\b", text)
    for ticker in tickers:
        if ticker in KNOWN_TICKERS:
            return ticker
    return None


def resolve_focus(current_text, history=()):
    """Current explicit asset wins; ambiguous follow-ups inherit latest prior user asset."""
    current = explicit_focus(current_text)
    if current:
        return current
    for turn in reversed(history):
        if isinstance(turn, dict) and turn.get("role") == "user":
            previous = explicit_focus(turn.get("content", ""))
            if previous:
                return previous
    return None


def symbols_for_focus(focus):
    if focus in ASSETS:
        return ASSETS[focus]["symbols"]
    if focus:
        return (focus,)
    return ("^GSPC", "GC=F", "BTC-USD")


def fred_for_focus(focus):
    if focus in ASSETS:
        return ASSETS[focus]["fred"]
    return ("DFII10", "T10YIE", "T10Y2Y", "T10Y3M", "DGS10", "NFCI", "M2SL")


# Stationary level indicators whose own-history percentile is meaningful.
LEVEL_SYMBOLS = {
    "gold": ("^VIX", "^GVZ", "^TNX", "DX-Y.NYB"),
    "silver": ("^GVZ", "^TNX", "DX-Y.NYB"),
    "spx": ("^VIX", "^VVIX", "^SKEW", "^MOVE", "^TNX"),
    "oil": ("^OVX", "^VIX", "DX-Y.NYB"),
    "brent": ("^OVX", "^VIX", "DX-Y.NYB"),
    "btc": ("^VIX", "^MOVE", "DX-Y.NYB"),
    "dollar": ("DX-Y.NYB", "^TNX", "^MOVE"),
}
# Rate/spread FRED series only; trending stocks (M2, Fed balance sheet) are excluded.
FRED_LEVEL_SERIES = {"DFII10", "T10YIE", "T5YIE", "T5YIFR", "DGS10", "T10Y3M", "T10Y2Y",
                     "NFCI", "BAMLH0A0HYM2", "THREEFYTP10"}


def levels_for_focus(focus):
    return LEVEL_SYMBOLS.get(focus, ("^VIX", "^TNX", "DX-Y.NYB"))
