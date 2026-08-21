#!/bin/bash
# =========================================================================
# WireGuard Panel - One-Click Git Update & Auto-Migration Script
# =========================================================================
set -e

echo "=== [1/4] Updating source code from GitHub ==="
git pull origin main

echo "=== [2/4] Setting execution permissions ==="
find . -type f -name "*.sh" -exec chmod +x {} + 2>/dev/null || true
find . -type d -path "*/telegram/telegram*" -exec rm -rf {} + 2>/dev/null || true

echo "=== [3/4] Running automated SQLite schema migration ==="
/usr/local/bin/Wireguard-panel/src/venv/bin/python3 -c "
import os, sys
base_dir = os.path.abspath('src')
sys.path.insert(0, base_dir)
from sqlite_backend import init_sqlite
init_sqlite(base_dir)
print('✔ Database schema successfully migrated to latest version.')
"

echo "=== [4/4] Restarting WireGuard Panel service ==="
systemctl daemon-reload
systemctl restart wireguard-panel

echo "========================================================="
echo "🎉 Update & Auto-Migration completed successfully! (100% OK)"
echo "========================================================="