#!/bin/sh
# Start the dashboard or the scheduler as the unprivileged user "sovereign".
#
# The container starts as root only for this: the folders the app writes —
# the database volume, logs/ and backups/ — may be root's, from an image
# before this one or from Docker creating a bind-mounted folder on a Linux
# host. They are handed to "sovereign" (only what isn't its already), then
# root is dropped for good and the command runs as "sovereign".
set -e

if [ "$(id -u)" = "0" ]; then
    for dir in /app/data /app/logs /app/backups; do
        mkdir -p "$dir"
        # A bind mount that refuses chown (some Docker Desktop setups) is
        # writable by everyone anyway: carry on.
        find "$dir" ! -user sovereign -exec chown sovereign:sovereign {} + 2>/dev/null || true
    done
    # setpriv keeps the environment (the settings and keys from .env), HOME
    # included: left as /root, Streamlit reads /root/.streamlit and stops.
    export HOME=/home/sovereign USER=sovereign
    exec setpriv --reuid=sovereign --regid=sovereign --init-groups -- "$@"
fi

exec "$@"
