import os, sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

# Your own figures saved from the dashboard (data/settings.json) never reach a
# test: config reads this path instead, an empty folder's.
_TMP = tempfile.mkdtemp(prefix="sovereign-tests-")
os.environ.setdefault("SOVEREIGN_SETTINGS_PATH", os.path.join(_TMP, "settings.json"))
# ... nor the market rates last read from the ECB (data/market_rates.json).
os.environ.setdefault("SOVEREIGN_MARKET_RATES_PATH", os.path.join(_TMP, "market_rates.json"))
