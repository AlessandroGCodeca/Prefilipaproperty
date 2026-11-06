"""python -m database — create or migrate data/sovereign.db."""

import logging

from database import init_db

logging.basicConfig(level=logging.INFO, format="%(message)s")
init_db()
