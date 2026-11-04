#!/bin/bash
# Restart this folder's dashboard. Only the Streamlit this script started is
# stopped — its PID is kept in logs/streamlit.pid — not every Streamlit app on
# the machine, as `pkill -f "streamlit run"` used to.
cd "$(dirname "$0")" || exit 1
PIDFILE=logs/streamlit.pid
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    # A PID can be reused after a reboot: only stop it if it is still Streamlit.
    if ps -p "$PID" -o command= 2>/dev/null | grep -q "streamlit run"; then
        kill "$PID"
        sleep 1
    fi
fi
mkdir -p logs
echo $$ > "$PIDFILE"
# exec keeps this PID, so the file names the Streamlit process itself.
# 127.0.0.1: this computer only, as "Start Sovereign.command" and Docker
# (docker-compose.yml) do it. Streamlit on its own listens on every network,
# so anyone on the same Wi-Fi could open the dashboard and press its buttons.
exec streamlit run app.py --server.address 127.0.0.1
