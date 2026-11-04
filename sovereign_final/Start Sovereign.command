#!/bin/bash
# ══════════════════════════════════════════════════════
#  Sovereign RE Dashboard — macOS start, without Docker
#  Double-click this file in Finder. The first start sets everything up
#  (a few minutes); later starts take seconds. Keep the Terminal window it
#  opens: closing it (or Ctrl+C in it) stops the dashboard.
# ══════════════════════════════════════════════════════

cd "$(dirname "$0")" || exit 1

URL="http://localhost:8501"
VENV=".venv"

fail() {
    echo
    echo "❌ $1"
    echo
    read -r -p "Press Enter to close this window."
    exit 1
}

open_browser() {
    if [ -d "/Applications/Google Chrome.app" ] || [ -d "$HOME/Applications/Google Chrome.app" ]; then
        open -a "Google Chrome" "$URL"
    else
        open "$URL"
    fi
}

# Started already (a second double-click): just show it.
if curl -fs -o /dev/null "$URL/_stcore/health"; then
    echo "The dashboard is already running — opening $URL"
    open_browser
    exit 0
fi

# The dashboard's libraries install on Python 3.11–3.14. 3.15 is too new:
# Streamlit needs a pyarrow that has no 3.15 build, so the install fails.
supported() {
    "$1" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) else 1)' 2>/dev/null
}

find_python() {
    for v in 3.13 3.12 3.14 3.11; do
        for p in "python$v" \
                 "/Library/Frameworks/Python.framework/Versions/$v/bin/python$v" \
                 "/opt/homebrew/bin/python$v" "/usr/local/bin/python$v"; do
            if command -v "$p" >/dev/null 2>&1 && supported "$p"; then
                echo "$p"
                return 0
            fi
        done
    done
    return 1
}

# A .venv made with an unsupported Python (3.15, say) can never install the
# requirements: start it again. It only holds installed libraries.
if [ -x "$VENV/bin/python" ] && ! supported "$VENV/bin/python"; then
    echo "The .venv folder was made with $("$VENV/bin/python" --version 2>&1), which can't run the dashboard — setting it up again."
    rm -rf "$VENV"
fi

if [ ! -x "$VENV/bin/python" ]; then
    PY=$(find_python) || fail "No Python 3.11–3.14 found. Install Python 3.13 from
   https://www.python.org/downloads/macos/ (the macOS 64-bit universal2 installer
   under a 3.13.x release — not 3.15, which is too new), then double-click this
   file again."
    echo "Setting up with $("$PY" --version) — the first start takes a few minutes…"
    "$PY" -m venv "$VENV" || fail "Couldn't create the .venv folder."
fi

# Install the libraries on the first start, and again whenever
# requirements.txt changes (a newer download of the project).
WANT=$(shasum -a 256 requirements.txt | cut -d' ' -f1)
HAVE=$(cat "$VENV/.requirements.sha256" 2>/dev/null)
if [ "$WANT" != "$HAVE" ]; then
    echo "Installing the dashboard's libraries…"
    "$VENV/bin/python" -m pip install --upgrade pip --quiet
    "$VENV/bin/python" -m pip install -r requirements.txt \
        || fail "Installing the libraries failed — see the messages above."
    # The browser the nehnutelnosti scraper (and 🔎 FILL MISSING DETAILS) drives.
    echo "Installing the scrapers' browser (Chromium)…"
    "$VENV/bin/python" -m playwright install chromium \
        || fail "Installing Chromium failed — see the messages above."
    echo "$WANT" > "$VENV/.requirements.sha256"
fi

# Open the page once the dashboard answers.
(
    for _ in $(seq 1 60); do
        if curl -fs -o /dev/null "$URL/_stcore/health"; then
            open_browser
            exit 0
        fi
        sleep 1
    done
) &

echo
echo "Starting the dashboard at $URL — leave this window open while you use it."
echo
# headless: the page above opens it in Chrome, not Streamlit in the default
# browser, and Streamlit asks no first-run questions.
# 127.0.0.1: this Mac only, as Docker does it (docker-compose.yml). Streamlit
# on its own listens on every network, so anyone on the same Wi-Fi could open
# the dashboard and press its buttons. See "Who can open it" in README.md.
exec "$VENV/bin/python" -m streamlit run app.py --server.headless true \
    --server.address 127.0.0.1
