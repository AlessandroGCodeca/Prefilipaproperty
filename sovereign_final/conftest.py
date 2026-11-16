import os, sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

# Your own figures saved from the dashboard (data/settings.json) never reach a
# test: config reads this path instead, an empty folder's.
os.environ.setdefault("SOVEREIGN_SETTINGS_PATH",
                      os.path.join(tempfile.mkdtemp(prefix="sovereign-tests-"), "settings.json"))
