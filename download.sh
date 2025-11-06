#!/bin/bash
set -euo pipefail

INSTALL_DIR="/usr/local/bin/Wireguard-panel"
REPO="git@github.com:hasan714222-debug/wireguard-panel.git"

BLUE="\033[1;34m"; GREEN="\033[1;32m"; RED="\033[1;31m"; NC="\033[0m"


if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y git
elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y git
else
    exit 1
fi

sudo rm -rf "$INSTALL_DIR"
sudo git clone "$REPO" "$INSTALL_DIR"

cd "$INSTALL_DIR/src"
sudo chmod +x setup.sh
sudo bash setup.sh

