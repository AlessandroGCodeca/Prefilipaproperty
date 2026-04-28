#!/bin/bash
# Kill any running Streamlit and start fresh
pkill -f "streamlit run" 2>/dev/null
sleep 1
cd "$(dirname "$0")"
streamlit run app.py
