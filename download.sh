#!/bin/bash
set -e

INSTALL_DIR="/usr/local/bin/Wireguard-panel"
REPO_SSH="git@github.com:hasan714222-debug/wireguard-panel.git"

RED="\033[1;31m"
GREEN="\033[1;32m"
BLUE="\033[1;34m"
NC="\033[0m"

echo -e "${BLUE}[+] Installing dependencies...${NC}"
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y git
elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y git
else
    echo -e "${RED}Unsupported package manager. Please install git manually.${NC}"
    exit 1
fi

echo -e "${BLUE}[+] Cloning Wireguard-panel repository...${NC}"
sudo rm -rf "$INSTALL_DIR"
sudo mkdir -p "$INSTALL_DIR"
sudo git clone "$REPO_SSH" "$INSTALL_DIR"

echo -e "${BLUE}[+] Running setup.sh ...${NC}"
cd "$INSTALL_DIR/src"
sudo bash setup.sh

echo -e "${GREEN}[✔] Installation completed successfully!${NC}"
