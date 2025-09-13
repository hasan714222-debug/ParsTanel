#!/bin/bash
set -euo pipefail

LOCK="/var/lock/wireguard-panel-install.lock"
exec 9>"$LOCK"; flock -n 9 || { echo "Another install is running. Exit."; exit 0; }

INSTALL_DIR="/usr/local/bin/Wireguard-panel"
REPO_SSH="git@github.com:hasan714222-debug/wireguard-panel.git"

BLUE="\033[1;34m"; RED="\033[1;31m"; GREEN="\033[1;32m"; NC="\033[0m"

echo -e "${BLUE}[+] Installing dependencies...${NC}"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y && sudo apt-get install -y git
elif command -v yum >/dev/null 2>&1; then
  sudo yum install -y git
else
  echo -e "${RED}Unsupported package manager. Please install git manually.${NC}"
  exit 1
fi

echo -e "${BLUE}[+] Fetching repository...${NC}"
if [ -d "$INSTALL_DIR/.git" ]; then
  sudo git -C "$INSTALL_DIR" fetch --all --prune
  sudo git -C "$INSTALL_DIR" checkout main
  sudo git -C "$INSTALL_DIR" reset --hard origin/main
else
  sudo rm -rf "$INSTALL_DIR"
  sudo git clone "$REPO_SSH" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR/src"

sudo chmod 755 setup.sh
sudo sed -i 's/\r$//' setup.sh

echo -e "${BLUE}[+] Running setup.sh...${NC}"

if [ -t 0 ]; then
  sudo bash ./setup.sh
else
  sudo bash -ic "./setup.sh"
fi

echo -e "${GREEN}[✔] Installation completed successfully!${NC}"
