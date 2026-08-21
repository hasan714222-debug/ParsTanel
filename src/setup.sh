
uninstall_panel_clean() {
    echo -e "\033[1;31m[WARNING] Uninstalling Wireguard Panel and purging all zombie data...\033[0m"
    systemctl stop wireguard-panel 2>/dev/null || true
    systemctl disable wireguard-panel 2>/dev/null || true

    rm -f /etc/wireguard/db_backup.sqlite3 /etc/wireguard/db.sqlite3
    rm -f /home/irandnss/public_html/git/github_workspace/base/src/db.sqlite3*
    rm -f /home/irandnss/public_html/git/github_workspace/base/src/db.json
    rm -f /home/irandnss/public_html/git/github_workspace/base/src/short_links.json
    rm -f /home/irandnss/public_html/git/github_workspace/base/src/short_links_decrypted.json
    rm -f /home/irandnss/public_html/git/github_workspace/base/src/endip.json
    rm -rf /home/irandnss/public_html/git/github_workspace/base/src/backups/*

    for conf_file in /etc/wireguard/*.conf; do
        if [ -f "$conf_file" ]; then
            python3 -c "
import sys
try:
    with open('$conf_file', 'r') as f: txt = f.read()
    iface_part = txt.split('[Peer]')[0].strip() + '
'
    with open('$conf_file', 'w') as f: f.write(iface_part)
except Exception: pass
"
        fi
    done

    echo -e "\033[1;32m[SUCCESS] Wireguard Panel uninstalled and all ghost peer records cleanly removed.\033[0m"
}



update_panel_safe() {
    echo -e "\033[1;34m[INFO] Updating Wireguard Panel (Zero Data Loss Mode)...\033[0m"
    BK_TMP="/tmp/wg_panel_update_safe_$(date +%s)"
    mkdir -p "$BK_TMP"
    
    cp -f "$PANEL_DIR/src/db.sqlite3"* "$BK_TMP/" 2>/dev/null || true
    cp -f "$PANEL_DIR/src/config.yaml" "$BK_TMP/" 2>/dev/null || true
    cp -f "$PANEL_DIR/src/secret.key" "$BK_TMP/" 2>/dev/null || true
    cp -f "$PANEL_DIR/src/short_links.json" "$BK_TMP/" 2>/dev/null || true
    cp -f "$PANEL_DIR/src/short_links_decrypted.json" "$BK_TMP/" 2>/dev/null || true
    cp -f "$PANEL_DIR/src/endip.json" "$BK_TMP/" 2>/dev/null || true
    cp -f /etc/wireguard/db_backup.sqlite3 "$BK_TMP/" 2>/dev/null || true

    if [ -d "$PANEL_DIR/.git" ]; then
        git -C "$PANEL_DIR" fetch --all >/dev/null 2>&1
        git -C "$PANEL_DIR" reset --hard origin/main >/dev/null 2>&1
    fi

    mkdir -p "$PANEL_DIR/src"
    [ -f "$BK_TMP/db.sqlite3" ] && cp -f "$BK_TMP/db.sqlite3"* "$PANEL_DIR/src/"
    [ -f "$BK_TMP/config.yaml" ] && cp -f "$BK_TMP/config.yaml" "$PANEL_DIR/src/"
    [ -f "$BK_TMP/secret.key" ] && cp -f "$BK_TMP/secret.key" "$PANEL_DIR/src/"
    [ -f "$BK_TMP/short_links.json" ] && cp -f "$BK_TMP/short_links.json" "$PANEL_DIR/src/"
    [ -f "$BK_TMP/short_links_decrypted.json" ] && cp -f "$BK_TMP/short_links_decrypted.json" "$PANEL_DIR/src/"
    [ -f "$BK_TMP/endip.json" ] && cp -f "$BK_TMP/endip.json" "$PANEL_DIR/src/"
    [ -f "$BK_TMP/db_backup.sqlite3" ] && cp -f "$BK_TMP/db_backup.sqlite3" /etc/wireguard/db_backup.sqlite3 2>/dev/null || true
    
    rm -rf "$BK_TMP"
    systemctl restart wireguard-panel 2>/dev/null || true
    echo -e "\033[1;32m[SUCCESS] Wireguard Panel updated with 100% data preservation![0m"
}



# --- [STEP 84: OFFLINE UPDATE FALLBACK FOR MENU OPTION 7] ---
update_panel_offline_or_online() {
    echo -e "\033[1;36m[INFO] Updating Wireguard Panel & Telegram Bot...\033[0m"
    UPDATED=false
    if timeout 10s git fetch --all >/dev/null 2>&1 && timeout 15s git reset --hard origin/main >/dev/null 2>&1; then
        echo -e "\033[1;32m[ONLINE] Panel updated successfully from GitHub!\033[0m"
        UPDATED=true
    else
        echo -e "\033[1;33m[OFFLINE FALLBACK] GitHub unreachable. Checking local ZIP archives in /root/...\033[0m"
        ZIP_FILE=$(ls /root/*wireguard*.zip /root/*panel*.zip /root/wireguard-panel-main.zip 2>/dev/null | head -n 1)
        if [ -n "$ZIP_FILE" ] && [ -f "$ZIP_FILE" ]; then
            echo -e "\033[1;32m[OFFLINE] Unpacking $ZIP_FILE for offline update...\033[0m"
            mkdir -p /tmp/wg_update_tmp
            unzip -o -q "$ZIP_FILE" -d /tmp/wg_update_tmp
            SETUP_LOC=$(find /tmp/wg_update_tmp -name "setup.sh" -type f | head -n 1)
            if [ -n "$SETUP_LOC" ]; then
                SRC_DIR_TMP=$(dirname "$SETUP_LOC")
                PANEL_ROOT_TMP=$(dirname "$SRC_DIR_TMP")
                cp -r "$PANEL_ROOT_TMP"/* /home/irandnss/public_html/git/github_workspace/base/ 2>/dev/null
                echo -e "\033[1;32m[OFFLINE] Panel updated from local archive successfully!\033[0m"
                UPDATED=true
            fi
            rm -rf /tmp/wg_update_tmp
        fi
    fi

    if [ "$UPDATED" = true ]; then
        systemctl restart wireguard-panel 2>/dev/null || true
        echo -e "\033[1;32m[SUCCESS] Wireguard Panel service restarted successfully.\033[0m"
    else
        echo -e "\033[1;31m[ERROR] Failed to update online and no valid local archive found in /root/\033[0m"
    fi
}


# Auto-repair iptables if broken in Linux
if ! iptables -L -n >/dev/null 2>&1; then
    rm -f /usr/sbin/iptables /usr/sbin/iptables-save /usr/sbin/iptables-restore /sbin/iptables 2>/dev/null
    ln -sf /usr/sbin/xtables-legacy-multi /usr/sbin/iptables
    ln -sf /usr/sbin/xtables-legacy-multi /usr/sbin/iptables-save
    ln -sf /usr/sbin/xtables-legacy-multi /usr/sbin/iptables-restore
    ln -sf /usr/sbin/xtables-legacy-multi /sbin/iptables 2>/dev/null || true
fi

#!/bin/bash

SCRIPT_DIR=$(dirname "$(realpath "$0")")

RED='\033[0;31m'
GREEN='\033[1;92m'
YELLOW='\033[1;33m'
BLUE='\033[96m'
CYAN='\033[0;36m'
NC='\033[0m' 
INFO="\033[96m"      
SUCCESS="\033[1;92m"    
WARNING="\e[33m"   
ERROR="\e[31m"      

OFFLINE_ZIP="/root/wireguard-panel-offline.zip"
CONFIG_YAML="$SCRIPT_DIR/config.yaml"
PERSISTENT_CFG="/etc/wireguard/panel_config_backup.yaml"
PERSISTENT_DB="/etc/wireguard/db_backup.sqlite3"

logo=$(cat << "EOF"
  ____                  _____                    
 |  _ \ __ _ _ __ ___  |__  /___  _ __   ___     
 | |_) / _` | \'__/ __|   / // _ \| '_ \ / _ \    
 |  __/ (_| | |  \__ \  / /| (_) | | | |  __/    
 |_|   \__,_|_|  |___/ /____\___/|_| |_|\___|    Author: github.com/ParsZone
EOF
)

update_panel_or_bot() {
    echo -e "${INFO}[INFO] Starting System Update (Panel & Telegram Bot)...${NC}"
    PANEL_DIR="/home/irandnss/public_html/git/github_workspace/base"
    [ ! -d "$PANEL_DIR" ] && PANEL_DIR="/home/irandnss/public_html/git/github_workspace/base"
    
    TEMP_BACKUP="/tmp/wg_panel_update_backup"
    mkdir -p "$TEMP_BACKUP"

    # Backup & Preserve Database, Configurations, Keys, and Sublinks
    [ -f "$PANEL_DIR/src/db.sqlite3" ] && cp "$PANEL_DIR/src/db.sqlite3" "$TEMP_BACKUP/"
    [ -f "$PANEL_DIR/src/db.json" ] && cp "$PANEL_DIR/src/db.json" "$TEMP_BACKUP/"
    [ -f "$PANEL_DIR/src/config.yaml" ] && cp "$PANEL_DIR/src/config.yaml" "$TEMP_BACKUP/"
    [ -f "$PANEL_DIR/src/short_links.json" ] && cp "$PANEL_DIR/src/short_links.json" "$TEMP_BACKUP/"
    [ -f "$PANEL_DIR/src/secret.key" ] && cp "$PANEL_DIR/src/secret.key" "$TEMP_BACKUP/" 2>/dev/null
    [ -d "$PANEL_DIR/src/db" ] && cp -r "$PANEL_DIR/src/db" "$TEMP_BACKUP/"

    echo -e "${INFO}[INFO] Pulling latest updates from GitHub...${NC}"
    if [ -d "$PANEL_DIR/.git" ]; then
        cd "$PANEL_DIR" || exit
        git fetch --all >/dev/null 2>&1
        git reset --hard origin/main >/dev/null 2>&1
    else
        rm -rf /tmp/wg_panel_latest
        git clone "https://${GH_TOKEN}@github.com/hasan714222-debug/wireguard-panel.git" /tmp/wg_panel_latest >/dev/null 2>&1
        if [ -d "/tmp/wg_panel_latest/src" ]; then
            cp -r /tmp/wg_panel_latest/* "$PANEL_DIR/" 2>/dev/null
            rm -rf /tmp/wg_panel_latest
        fi
    fi

    # Restore Preserved Data
    [ -f "$TEMP_BACKUP/db.sqlite3" ] && cp "$TEMP_BACKUP/db.sqlite3" "$PANEL_DIR/src/"
    [ -f "$TEMP_BACKUP/db.json" ] && cp "$TEMP_BACKUP/db.json" "$PANEL_DIR/src/"
    [ -f "$TEMP_BACKUP/config.yaml" ] && cp "$TEMP_BACKUP/config.yaml" "$PANEL_DIR/src/"
    [ -f "$TEMP_BACKUP/short_links.json" ] && cp "$TEMP_BACKUP/short_links.json" "$PANEL_DIR/src/"
    [ -f "$TEMP_BACKUP/secret.key" ] && cp "$TEMP_BACKUP/secret.key" "$PANEL_DIR/src/" 2>/dev/null
    [ -d "$TEMP_BACKUP/db" ] && cp -r "$TEMP_BACKUP/db"/* "$PANEL_DIR/src/db/" 2>/dev/null
    rm -rf "$TEMP_BACKUP"

    echo -e "${INFO}[INFO] Restarting Panel and Telegram Bot services...${NC}"
    systemctl daemon-reload
    systemctl restart wireguard-panel.service 2>/dev/null || systemctl restart wireguard-panel 2>/dev/null || true
    systemctl restart telegram-bot-fa.service 2>/dev/null || true
    systemctl restart telegram-bot-en.service 2>/dev/null || true

    echo -e "${SUCCESS}[SUCCESS] Panel and Telegram Bot updated successfully! All user data and configurations preserved.${NC}"
}

ensure_pars_admin_exists() {
    local db_file="$SCRIPT_DIR/db.sqlite3"
    local py_bin = "python3"
    if [ ! -f "$py_bin" ]; then py_bin=$(which python3); fi

    mkdir -p "$SCRIPT_DIR"
    mkdir -p /etc/wireguard

    "$py_bin" -c "
import sqlite3
db_p = '$db_file'
try:
    try:
        from werkzeug.security import generate_password_hash
        h_p = generate_password_hash('Pars')
    except Exception:
        import hashlib, os
        salt = os.urandom(16).hex()
        h_p = 'pbkdf2:sha256:100000$' + salt + '$' + hashlib.pbkdf2_hmac('sha256', b'Pars', salt.encode('utf-8'), 100000).hex()

    conn = sqlite3.connect(db_p, timeout=10.0)
    cur = conn.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, password_plain TEXT)')
    
    cur.execute('PRAGMA table_info(users)')
    cols = [c[1] for c in cur.fetchall()]
    if 'password_plain' not in cols:
        try: cur.execute('ALTER TABLE users ADD COLUMN password_plain TEXT')
        except: pass

    cur.execute('SELECT id FROM users WHERE username=\'Pars\'')
    if not cur.fetchone():
        cur.execute('INSERT OR REPLACE INTO users (id, username, password_hash, password_plain) VALUES (1, \'Pars\', ?, \'Pars\')', (h_p,))
        print('✔ Master Admin Pars/Pars created successfully.')
    conn.commit()
    conn.close()
except Exception as e:
    print('Admin init error:', e)
" 2>/dev/null || true

    if [ -f "$db_file" ]; then
        cp "$db_file" /etc/wireguard/db_backup.sqlite3 2>/dev/null || true
    fi
}

display_logo() {
    echo -e "$logo"
}

get_configured_port() {
    local port=""
    if [ -f "$CONFIG_YAML" ]; then
        port=$(grep 'port:' "$CONFIG_YAML" 2>/dev/null | head -n 1 | awk '{print $2}' | tr -d '"' | tr -d "'")
    fi
    if [ -z "$port" ] && [ -f "$PERSISTENT_CFG" ]; then
        port=$(grep 'port:' "$PERSISTENT_CFG" 2>/dev/null | head -n 1 | awk '{print $2}' | tr -d '"' | tr -d "'")
    fi
    echo "${port:-5000}"
}

install_panel_url_tool() {
    sed -i '/alias panel-url=/d' ~/.bashrc 2>/dev/null || true
    cat << 'EOF' > /usr/local/bin/panel-url
#!/bin/bash
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

CFG="/home/irandnss/public_html/git/github_workspace/base/src/config.yaml"
if [ ! -f "$CFG" ]; then
    CFG="/etc/wireguard/panel_config_backup.yaml"
fi

if [ ! -f "$CFG" ]; then
    echo "❌ Config file not found. Please setup panel first."
    exit 1
fi

PORT=$(grep 'port:' "$CFG" 2>/dev/null | head -n 1 | awk '{print $2}' | tr -d '"' | tr -d "'")
PORT=${PORT:-5000}
TLS=$(grep 'tls:' "$CFG" 2>/dev/null | head -n 1 | awk '{print $2}')
IP=$(curl -s -m 3 https://api.ipify.org || hostname -I | awk '{print $1}')

IS_RUNNING=false
if systemctl is-active --quiet wireguard-panel.service 2>/dev/null; then
    IS_RUNNING=true
elif ss -tulpn 2>/dev/null | grep -q ":$PORT "; then
    IS_RUNNING=true
elif netstat -tulpn 2>/dev/null | grep -q ":$PORT "; then
    IS_RUNNING=true
elif pgrep -f "app.py" >/dev/null 2>&1; then
    IS_RUNNING=true
fi

if [ "$IS_RUNNING" = false ]; then
    systemctl restart wireguard-panel.service 2>/dev/null || true
    sleep 2
    if systemctl is-active --quiet wireguard-panel.service 2>/dev/null || ss -tulpn 2>/dev/null | grep -q ":$PORT "; then
        IS_RUNNING=true
    fi
fi

if [ "$IS_RUNNING" = true ]; then
    STATUS_STR="\033[1;92m🟢 Online (Active)\033[0m"
else
    STATUS_STR="\033[1;31m🔴 Offline (Inactive)\033[0m"
fi

if [ "$TLS" == "true" ]; then
    CERT=$(grep 'cert_path:' "$CFG" 2>/dev/null | head -n 1 | awk '{print $2}' | tr -d '"' | tr -d "'")
    DOMAIN=$(echo "$CERT" | awk -F'/' '{print $(NF-1)}')
    if [ -n "$DOMAIN" ]; then
        URL="https://${DOMAIN}:${PORT}"
    else
        URL="https://${IP}:${PORT}"
    fi
else
    URL="http://${IP}:${PORT}"
fi

echo -e "\033[96m==========================================\033[0m"
echo -e "📡 Service Status: ${STATUS_STR}"
echo -e "🌐 Live Panel URL: \033[1;33m${URL}\033[0m"
echo -e "\033[96m==========================================\033[0m"
EOF
    chmod +x /usr/local/bin/panel-url 2>/dev/null || true
}

restore_persistent_config() {
    if [ ! -f "$CONFIG_YAML" ] && [ -f "$PERSISTENT_CFG" ]; then
        mkdir -p "$SCRIPT_DIR"
        cp "$PERSISTENT_CFG" "$CONFIG_YAML" 2>/dev/null || true
    fi
    if [ ! -f "$SCRIPT_DIR/db.sqlite3" ] && [ -f "$PERSISTENT_DB" ]; then
        mkdir -p "$SCRIPT_DIR"
        cp "$PERSISTENT_DB" "$SCRIPT_DIR/db.sqlite3" 2>/dev/null || true
    fi
}

sync_persistent_config() {
    if [ -f "$CONFIG_YAML" ]; then
        mkdir -p /etc/wireguard
        cp "$CONFIG_YAML" "$PERSISTENT_CFG" 2>/dev/null || true
    fi
    if [ -f "$SCRIPT_DIR/db.sqlite3" ]; then
        mkdir -p /etc/wireguard
        cp "$SCRIPT_DIR/db.sqlite3" "$PERSISTENT_DB" 2>/dev/null || true
    fi
}

restore_persistent_config

is_panel_installed() {
    if [ -f "/etc/systemd/system/wireguard-panel.service" ] || [ -f "$CONFIG_YAML" ] || [ -f "$PERSISTENT_CFG" ]; then
        return 0
    else
        return 1
    fi
}

is_panel_service_running() {
    local check_port=$(get_configured_port)
    STATUS=$(systemctl is-active wireguard-panel.service 2>/dev/null)
    if [ "$STATUS" == "active" ] || [ "$STATUS" == "activating" ]; then
        return 0
    elif ss -tulpn 2>/dev/null | grep -q ":${check_port} "; then
        return 0
    elif netstat -tulpn 2>/dev/null | grep -q ":${check_port} "; then
        return 0
    elif pgrep -f "app.py" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

ensure_zip_tools() {
    if ! command -v unzip &>/dev/null || ! command -v zip &>/dev/null; then
        echo -e "${INFO}[INFO] Installing extraction tools (zip/unzip)...${NC}"
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y -qq zip unzip >/dev/null 2>&1
    fi
}

create_offline_zip_package() {
    echo -e "${INFO}[INFO]${YELLOW} Creating offline installation package: ${OFFLINE_ZIP} ...${NC}"
    rm -f "${OFFLINE_ZIP}"
    if [ -d "$SCRIPT_DIR/venv" ]; then
        zip -r -q "${OFFLINE_ZIP}" "$SCRIPT_DIR/venv" /var/cache/apt/archives/*.deb 2>/dev/null || true
        if [ -f "${OFFLINE_ZIP}" ]; then
            echo -e "${SUCCESS}✅ Offline package created at ${OFFLINE_ZIP}${NC}\n"
        fi
    fi
}

extract_and_install_from_zip() {
    if [ -f "$OFFLINE_ZIP" ]; then
        echo -e "\n${INFO}[INFO]${YELLOW} Extracting offline package from ${OFFLINE_ZIP} ...${NC}"
        TMP_EXTRACT="/tmp/wg_offline_extract"
        rm -rf "${TMP_EXTRACT}"
        mkdir -p "${TMP_EXTRACT}"

        unzip -o -q "${OFFLINE_ZIP}" -d "${TMP_EXTRACT}"

        if [ -d "${TMP_EXTRACT}/var/cache/apt/archives" ]; then
            dpkg -i ${TMP_EXTRACT}/var/cache/apt/archives/*.deb >/dev/null 2>&1 || apt-get install -f -y >/dev/null 2>&1
        fi

        FOUND_VENV=$(find "${TMP_EXTRACT}" -maxdepth 3 -type d -name "venv" | head -n 1)
        if [ -n "$FOUND_VENV" ]; then
            rm -rf "$SCRIPT_DIR/venv"
            cp -r "$FOUND_VENV" "$SCRIPT_DIR/"
        fi

        rm -rf "${TMP_EXTRACT}"
        ensure_venv_exists
        echo -e "${SUCCESS}[SUCCESS] Installed from offline package successfully.${NC}\n"
    fi
}

install_requirements() {
    echo -e "\033[92m ^ ^\033[0m"
    echo -e "\033[92m(\033[91mO,O\033[92m)\033[0m"
    echo -e "\033[92m(   ) \033[92mRequirements\033[0m"
    echo -e '\033[92m "-"\033[93m══════════════════════════════════\033[0m'

    echo -e "${INFO}[INFO]${YELLOW}Installing required Stuff...${NC}"
    echo -e '\033[93m══════════════════════════════════\033[0m'

    sudo rm -f /etc/apt/sources.list.d/*manageit* /etc/apt/sources.list.d/*docker* 2>/dev/null || true
    sudo apt update && sudo apt install -y python3 python3-pip python3-venv git redis nftables iptables wireguard-tools iproute2 \
        fonts-dejavu certbot curl software-properties-common wget zip unzip || {
        echo -e "${ERROR}Installation failed. Ensure you are using root privileges.${NC}"
        exit 1
    }

    echo -e "${INFO}[INFO]${YELLOW}Starting Redis server...${NC}"
    sudo systemctl enable redis-server.service
    sudo systemctl start redis-server.service || {
        echo -e "${ERROR}Couldn't start Redis server. Please check system logs.${NC}"
        exit 1
    }

    echo -e "${SUCCESS}[SUCCESS]All required stuff have been installed successfully.${NC}"
}

ensure_venv_exists() {
    if [ ! -f "$SCRIPT_DIR/python3" ]; then
        echo -e "${INFO}[INFO] Creating Python virtual environment at $SCRIPT_DIR/venv ...${NC}"
        python3 -m venv --system-site-packages "$SCRIPT_DIR/venv" 2>/dev/null || python3 -m venv "$SCRIPT_DIR/venv"
        source "$SCRIPT_DIR/venv/bin/activate" 2>/dev/null || true
        pip install --upgrade pip -q 2>/dev/null || true
        pip install Flask gunicorn pyyaml flask-session Flask-Limiter Flask-Bcrypt Flask-Caching requests SQLAlchemy werkzeug jinja2 python-dotenv python-telegram-bot aiohttp matplotlib qrcode jsonschema psutil pynacl apscheduler redis fasteners pexpect cryptography pillow arabic-reshaper python-bidi pytz jdatetime -q 2>/dev/null || true
        deactivate 2>/dev/null || true
    fi
}

setup_virtualenv() {
    echo -e "\033[92m ^ ^\033[0m"
    echo -e "\033[92m(\033[91mO,O\033[92m)\033[0m"
    echo -e "\033[92m(   ) \033[92mVirtual env Setup\033[0m"
    echo -e '\033[92m "-"\033[93m══════════════════════════════════\033[0m'
    echo -e "${INFO}[INFO]${YELLOW}Setting up Virtual Env...${NC}"

    PYTHON_BIN=$(which python3)
    if [ -z "$PYTHON_BIN" ]; then
        echo -e "${ERROR}Python3 is not installed or not in PATH. install Python3.${NC}"
        exit 1
    fi

    echo -e "${INFO}[INFO]${YELLOW}Creating virtual env...${NC}"
    "$PYTHON_BIN" -m venv "$SCRIPT_DIR/venv" || {
        echo -e "${ERROR}Couldn't create virtual env.${NC}"
        exit 1
    }

    source "$SCRIPT_DIR/venv/bin/activate"
    pip install --upgrade pip

    pip install \
        python-dotenv \
        python-telegram-bot \
        aiohttp \
        matplotlib \
        qrcode \
        "python-telegram-bot[job-queue]" \
        pyyaml \
        flask-session \
        Flask \
        SQLAlchemy \
        Flask-Limiter \
        Flask-Bcrypt \
        Flask-Caching \
        jsonschema \
        psutil \
        requests \
        pynacl \
        apscheduler \
        redis \
        werkzeug \
        jinja2 \
        fasteners \
        gunicorn \
        pexpect \
        cryptography \
        Pillow \
        arabic-reshaper \
        python-bidi \
        pytz \
        jdatetime || {
            echo -e "${ERROR}Couldn't install Python requirements.${NC}"
            deactivate
            exit 1
        }

    sudo apt-get install -y libsystemd-dev
    deactivate
    echo -e "${SUCCESS}[SUCCESS]Virtual env set up successfully.${NC}"
}

wireguard_detailed_stats() {
    echo -e "${CYAN}Wireguard Detailed Status:${NC}"
    echo -e "${YELLOW}═════════════════════════════════════════════════════════════════════${NC}"

    INTERFACE_FOUND=false
    for interface in /etc/wireguard/*.conf; do
        [ -e "$interface" ] || continue
        INTERFACE_FOUND=true

        INTERFACE_NAME=$(basename "$interface" .conf)

        IP_ADDRESS=$(grep '^Address' "$interface" | awk '{print $3}')
        PORT=$(grep '^ListenPort' "$interface" | awk '{print $3}')
        MTU=$(grep '^MTU' "$interface" | awk '{print $3}')

        if wg show "$INTERFACE_NAME" >/dev/null 2>&1; then
            echo -e "${SUCCESS}Interface: ${CYAN}$INTERFACE_NAME${NC} ${SUCCESS}(Status: Running)${NC}"
        else
            echo -e "${WARNING}Interface: ${CYAN}$INTERFACE_NAME${NC} ${WARNING}(Status: Inactive)${NC}"
        fi

        echo -e "  ${GREEN}IP Address: ${CYAN}${IP_ADDRESS:-Not Assigned}${NC}"
        echo -e "  ${GREEN}Port: ${CYAN}${PORT:-Not Defined}${NC}"
        echo -e "  ${GREEN}MTU: ${CYAN}${MTU:-Default}${NC}"
        echo -e "${YELLOW}─────────────────────────────────────────────────────────────────────${NC}"
    done

    if [ "$INTERFACE_FOUND" = false ]; then
        echo -e "${ERROR}No Wireguard interfaces found! check your configuration.${NC}"
    else
        echo -e "${INFO}[INFO]${YELLOW}All interfaces have been checked.${NC}"
    fi

    echo -e "${YELLOW}═════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}Press Enter to return to the menu...${NC}" && read
}

display_menu() {
    restore_persistent_config
    display_logo
    echo -e "${CYAN}╔═════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║      ${YELLOW}███████████████${NC}        ${BLUE}Main Menu${NC}        ${YELLOW}███████████████ ${CYAN}       ║${NC}"
    echo -e "${CYAN}╚═════════════════════════════════════════════════════════════════════╝${NC}"

    echo -e "${CYAN}╔═══════════════════════════ ${YELLOW}System Status${CYAN} ═══════════════════════════╗${NC}"

    INTERFACE_FOUND=false
    for interface in /etc/wireguard/*.conf; do
        [ -e "$interface" ] || continue
        INTERFACE_FOUND=true
        break
    done

    if [ "$INTERFACE_FOUND" = true ]; then
        echo -e "  ${GREEN}✔ Wireguard is active!${NC}"
    else
        echo -e "  ${RED}✖ Wireguard is not active!${NC}"
    fi

    if is_panel_service_running; then
        echo -e "  ${GREEN}✔ Wireguard Panel service is active!${NC}"
    else
        echo -e "  ${RED}✖ Wireguard Panel service is inactive!${NC}"
    fi

    echo -e "${CYAN}╚═════════════════════════════════════════════════════════════════════╝${NC}"

    if [ -f "$CONFIG_YAML" ]; then
        FLASK_PORT=$(grep 'port:' "$CONFIG_YAML" -A 5 | grep 'port:' | awk '{print $2}')
        FLASK_PORT=${FLASK_PORT:-5000}
        FLASK_TLS=$(grep 'tls:' "$CONFIG_YAML" -A 5 | grep 'tls:' | awk '{print $2}')
        FLASK_URL=""

        PUBLIC_IPV4_ADDRESS=$(curl -s -4 https://icanhazip.com || hostname -I | awk '{print $1}')

        echo -e "${CYAN}╔═════════════════════════ ${YELLOW}Flask Information${CYAN} ═════════════════════════╗${NC}"
        if [ "$FLASK_TLS" == "true" ]; then
            SUBDOMAIN=$(grep 'cert_path:' "$CONFIG_YAML" | awk -F'/' '{print $(NF-1)}')
            FLASK_URL="${SUBDOMAIN}:${FLASK_PORT}"
            echo -e "  ${GREEN}✔ Flask is running with TLS enabled!${NC}"
            echo -e "  ${CYAN}Homepage: ${NC}https://${YELLOW}${FLASK_URL}${NC}"
        else
            if [ ! -z "$PUBLIC_IPV4_ADDRESS" ]; then
                echo -e "  ${YELLOW}✔ Flask is running without TLS!${NC}"
                echo -e "  ${CYAN}Homepage: ${YELLOW}${PUBLIC_IPV4_ADDRESS}:${FLASK_PORT}${NC}"
            else
                echo -e "  ${RED}✖ No public IP address found for Flask!${NC}"
            fi
        fi
        echo -e "${CYAN}╚═════════════════════════════════════════════════════════════════════╝${NC}"
    else
        echo -e "${RED}✖ Flask config not found! Please set up Flask & Gunicorn first.${NC}"
    fi

    echo -e "${CYAN}═════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN} Options:${NC}"
    echo -e "${NC}  0)${CYAN} View Detailed Wireguard Status${NC}"
    echo -e "${NC}  s)${GREEN} Show Logs${NC}"
    echo -e "${NC}  1)${BLUE} Create${YELLOW}/${GREEN}Reset${BLUE} Flask & Gunicorn Configs${NC}"
    echo -e "${NC}  2)${GREEN} Create Wireguard Interface${NC}"
    echo -e "${NC}  3)${BLUE} Set up Permissions & Re-activate Service${NC}"
    echo -e "${NC}  4)${YELLOW} Set up Wireguard Panel as a Service${NC}"
    echo -e "${NC}  5)${RED} Uninstall${NC}"
    echo -e "${NC}  6)${YELLOW} RESET Username & Password${NC}" 
    echo -e "${NC}  7)${CYAN} Update Panel & Telegram Bot${NC}"
    echo -e "${NC}  q)${RED} Exit${NC}"
    echo -e "${CYAN}═════════════════════════════════════════════════════════════════════${NC}"
}

reset_credentials() {
    echo -e "${CYAN}===========================================${NC}"
    echo -e "${YELLOW}       User Credentials Management          ${NC}"
    echo -e "${CYAN}===========================================${NC}"

    ensure_pars_admin_exists

    DB_FILE="$SCRIPT_DIR/db.sqlite3"
    PY_BIN="$SCRIPT_DIR/python3"
    if [ ! -f "$PY_BIN" ]; then
        PY_BIN=$(which python3)
    fi

    echo -e "${CYAN}Existing Users in Database:${NC}"
    USER_LIST=$("$PY_BIN" -c "
import sqlite3
try:
    conn = sqlite3.connect('$DB_FILE', timeout=5.0)
    cur = conn.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, password_plain TEXT)')
    cur.execute('SELECT id, username FROM users ORDER BY id ASC')
    rows = cur.fetchall()
    conn.close()
    for r in rows:
        is_master = ' (Master Admin)' if r[0] == 1 or r[1] == 'Pars' else ''
        print(f'{r[0]}) {r[1]}{is_master}')
except Exception as e:
    print(f'Error listing users: {e}')
")

    if [ -z "$USER_LIST" ]; then
        ensure_pars_admin_exists
        USER_LIST="1) Pars (Master Admin)"
    fi

    echo -e "$USER_LIST"
    echo -e "${CYAN}-------------------------------------------${NC}"

    read -p "$(echo -e "${YELLOW}Select User ID or enter Username to edit [default: 1 (Pars)]: ${NC}")" SELECTED_USER
    SELECTED_USER=${SELECTED_USER:-1}

    read -p "$(echo -e "${YELLOW}Enter ${GREEN}new username${YELLOW} (leave empty to keep current): ${NC}")" NEW_USERNAME
    read -s -p "$(echo -e "${YELLOW}Enter ${GREEN}new password${YELLOW}: ${NC}")" NEW_PASSWORD
    echo ""
    read -s -p "$(echo -e "${YELLOW}Confirm ${GREEN}new password${YELLOW}: ${NC}")" CONFIRM_PASSWORD
    echo ""

    if [ -z "$NEW_PASSWORD" ]; then
        echo -e "${RED}✘ Password cannot be empty. Aborting.${NC}"
        return 1
    fi

    if [ "$NEW_PASSWORD" != "$CONFIRM_PASSWORD" ]; then
        echo -e "${RED}✘ Passwords do not match. Aborting.${NC}"
        return 1
    fi

    "$PY_BIN" -c "
import sqlite3
try:
    try:
        from werkzeug.security import generate_password_hash
        hashed_p = generate_password_hash('$NEW_PASSWORD')
    except:
        import hashlib, os
        salt = os.urandom(16).hex()
        hashed_p = 'pbkdf2:sha256:100000$' + salt + '$' + hashlib.pbkdf2_hmac('sha256', '$NEW_PASSWORD'.encode('utf-8'), salt.encode('utf-8'), 100000).hex()

    db_p = '$DB_FILE'
    target = '$SELECTED_USER'
    new_u = '$NEW_USERNAME'.strip()
    
    conn = sqlite3.connect(db_p, timeout=10.0)
    cur = conn.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, password_plain TEXT)')
    
    if target.isdigit():
        cur.execute('SELECT id, username FROM users WHERE id=?', (int(target),))
    else:
        cur.execute('SELECT id, username FROM users WHERE username=?', (target,))
    
    row = cur.fetchone()
    if not row:
        target_id = int(target) if target.isdigit() else 1
        final_u = new_u if new_u else ('Pars' if target_id == 1 else 'admin')
        cur.execute('INSERT OR REPLACE INTO users (id, username, password_hash, password_plain) VALUES (?, ?, ?, ?)', (target_id, final_u, hashed_p, '$NEW_PASSWORD'))
        print(f'✔ Created user {final_u} (ID: {target_id}).')
    else:
        uid, old_u = row[0], row[1]
        final_u = new_u if new_u else old_u
        cur.execute('UPDATE users SET username=?, password_hash=?, password_plain=? WHERE id=?', (final_u, hashed_p, '$NEW_PASSWORD', uid))
        print(f'✔ Updated user {final_u} (ID: {uid}).')

    conn.commit()
    conn.close()
except Exception as e:
    print(f'DB Update Error: {e}')
"
    sync_persistent_config
    if systemctl is-active --quiet wireguard-panel.service 2>/dev/null; then
        sudo systemctl restart wireguard-panel.service 2>/dev/null || true
    fi
    echo -e "${SUCCESS}✔ User credentials updated successfully.${NC}"
    echo -e "${CYAN}Press Enter to return to main menu...${NC}"
    read
}

select_stuff() {
    case $1 in
        0) wireguard_detailed_stats ;;
        s|S) show_logs ;;
        1) create_config ;;
        2) wireguardconf ;;
        3) setup_permissions ;;
        4) wireguard_panel ;;
        5)
            echo -e "[1;33m[WARNING] Are you sure you want to uninstall Wireguard Panel? [y/N]: [0m"
            read -r confirm_uninstall
            if [[ "$confirm_uninstall" =~ ^[Yy]$ ]]; then
                echo -e "[1;33m[INFO] Stopping and disabling services...[0m"
                systemctl stop wireguard-panel 2>/dev/null || true
                systemctl disable wireguard-panel 2>/dev/null || true
                rm -f /etc/systemd/system/wireguard-panel.service 2>/dev/null || true
                systemctl daemon-reload 2>/dev/null || true
                
                echo -e "[1;33m[INFO] Purging peer records and cleaning interface configurations...[0m"
                python3 - << 'EOF'
import os, glob, sqlite3

wg_dir = "/etc/wireguard"
if os.path.exists(wg_dir):
    for conf_file in glob.glob(os.path.join(wg_dir, "*.conf")):
        if not os.path.isfile(conf_file):
            continue
        try:
            with open(conf_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "[Peer]" in content:
                interface_part = content.split("[Peer]")[0].strip() + chr(10)
                with open(conf_file, "w", encoding="utf-8") as f:
                    f.write(interface_part)
        except Exception as e:
            print("Notice cleaning " + str(conf_file) + ": " + str(e))

db_paths = [
    "/home/irandnss/public_html/git/github_workspace/base/src/db.sqlite3",
    "/home/irandnss/public_html/git/github_workspace/base/db.sqlite3",
    "/etc/wireguard/db.sqlite3",
    "/etc/wireguard/db_backup.sqlite3"
]

for db_p in db_paths:
    if os.path.exists(db_p):
        try:
            conn = sqlite3.connect(db_p, timeout=10.0)
            cur = conn.cursor()
            cur.execute("DELETE FROM peers")
            cur.execute("DELETE FROM peer_synced_edges")
            cur.execute("DELETE FROM short_links")
            conn.commit()
            conn.close()
        except Exception:
            pass
EOF
                echo -e "[1;32m[SUCCESS] Wireguard Panel uninstalled and all ghost peer records cleanly removed.[0m"
            else
                echo -e "[1;36m[INFO] Uninstallation cancelled.[0m"
            fi
            ;;
6) reset_credentials ;;
        7) update_panel_safe ;;
q|Q) echo -e "${GREEN}Exiting...${NC}" && exit 0 ;;
        *) echo -e "${RED}Wrong choice. Please choose a valid option.${NC}" ;;
    esac
}

show_logs() {
    echo -e "${CYAN}═════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}Log Options${YELLOW} (Press q to exit logs view):${NC}"
    echo -e "${NC}  1)${CYAN} Show Service Logs (Wireguard Panel)${NC}"
    echo -e "${NC}  2)${YELLOW} Show Flask Logs (Last 30 Lines)${NC}"
    echo -e "${NC}  b)${RED} Back to Main Menu${NC}"
    echo -e "${CYAN}═════════════════════════════════════════════════════════════════════${NC}"

    read -rp "Choose an option: " log_choice

    case $log_choice in
        1) show_service_logs ;;  
        2) show_flask_logs ;;   
        b|B) return ;;  
        *) echo -e "${RED}Choice is not valid. Returning to the main menu...${NC}" ;;
    esac
}

show_service_logs() {
    echo -e "${INFO}[INFO]Displaying Wireguard Panel service logs...${NC}"
    journalctl -u wireguard-panel.service --no-pager -n 50 | less
}

show_flask_logs() {
    LOG_FILE="$SCRIPT_DIR/wireguard.log"

    if [ -f "$LOG_FILE" ]; then
        echo -e "${CYAN}Last 30 lines of Flask logs from ${YELLOW}$LOG_FILE${CYAN}:${NC}"
        tail -n 30 "$LOG_FILE" | less
    else
        echo -e "${RED}Error: Log file not found at ${YELLOW}$LOG_FILE${RED}.${NC}"
    fi
}

uninstall_mnu() {
    echo -e '\033[93m══════════════════════════════════════════════════\033[0m'
    echo -e "${CYAN}Uninstallation initiated${NC}"
    echo -e '\033[93m══════════════════════════════════════════════════\033[0m'

    echo -e "${WARNING}[WARNING]:${NC} This will completely delete the Wireguard panel, all configs, databases, and persistent backups."
    echo -e "${YELLOW}──────────────────────────────────────────────────────────────────────${NC}"
    echo -ne "${CYAN}Do you want to continue? ${GREEN}[yes]${NC}/${RED}[no]${NC}: "
    read -r CONFIRM
    if [[ "$CONFIRM" != "yes" && "$CONFIRM" != "y" ]]; then
        echo -e "${CYAN}Uninstallation aborted.${NC}"
        return
    fi

    WIREGUARD_DIR="/etc/wireguard"
    SYSTEMD_SERVICE="/etc/systemd/system/wireguard-panel.service"
    PANEL_DIR="/home/irandnss/public_html/git/github_workspace/base"

    rm -f "$PERSISTENT_CFG" "$PERSISTENT_DB" /etc/wireguard/db_backup.json 2>/dev/null || true

    if [ -f "$SYSTEMD_SERVICE" ]; then
        sudo systemctl stop wireguard-panel.service 2>/dev/null || true
        sudo systemctl disable wireguard-panel.service 2>/dev/null || true
        sudo rm -f "$SYSTEMD_SERVICE"
        sudo systemctl daemon-reload
    fi

    sudo rm -rf "$PANEL_DIR"
    sudo rm -rf "$WIREGUARD_DIR"
    sudo rm -f "$OFFLINE_ZIP" 2>/dev/null || true

    echo -e "\n${YELLOW}Complete Uninstallation Successful! All panel files, backups, and configs deleted.${NC}"
    echo -e "${CYAN}Press Enter to exit...${NC}" && read
}

setup_permissions() {
    local target_port=$(get_configured_port)
    echo -e "${INFO}[INFO] Setting permissions & re-activating panel service on port ${target_port}...${NC}"
    
    chmod -R 755 "$SCRIPT_DIR" 2>/dev/null || true
    chmod 644 "$SCRIPT_DIR"/*.py 2>/dev/null || true
    chmod 644 "$SCRIPT_DIR"/config.yaml 2>/dev/null || true
    chmod 600 /etc/wireguard/*.conf 2>/dev/null || true
    chmod -R 755 /etc/letsencrypt/live/ 2>/dev/null || true
    chmod -R 755 /etc/letsencrypt/archive/ 2>/dev/null || true
    chmod 644 /etc/letsencrypt/archive/*/* 2>/dev/null || true
    chmod 666 "$SCRIPT_DIR/db.sqlite3" 2>/dev/null || true

    sudo ufw allow ${target_port}/tcp 2>/dev/null || true
    sudo iptables -I INPUT -p tcp --dport ${target_port} -j ACCEPT 2>/dev/null || true

    fuser -k -9 ${target_port}/tcp 2>/dev/null || true
    pkill -9 -f "app.py" 2>/dev/null || true
    killall -9 gunicorn 2>/dev/null || true
    rm -f "$SCRIPT_DIR/jobs.sqlite"* /tmp/*.lock 2>/dev/null || true

    ensure_venv_exists

    EXEC_PY="$SCRIPT_DIR/python3"
    if [ ! -f "$EXEC_PY" ]; then EXEC_PY=$(which python3); fi

    sudo systemctl daemon-reload 2>/dev/null || true
    sudo systemctl reset-failed wireguard-panel.service 2>/dev/null || true
    sudo systemctl enable wireguard-panel.service 2>/dev/null || true
    sudo systemctl restart wireguard-panel.service 2>/dev/null || true

    sync_persistent_config
    install_panel_url_tool 2>/dev/null || true
    sleep 3

    if ! is_panel_service_running; then
        nohup "$EXEC_PY" "$SCRIPT_DIR/app.py" > /tmp/panel_direct.log 2>&1 &
        sleep 2
    fi

    echo -e "${SUCCESS}[SUCCESS] Permissions set and Wireguard Panel service successfully re-activated!${NC}"
    echo -e "${CYAN}Press Enter to continue...${NC}" && read
}

setup_tls() {
    echo -e '\033[93m══════════════════════════════════\033[0m'
    echo -ne "${YELLOW}Do you want to ${GREEN}enable TLS${YELLOW}? ${GREEN}[yes]${NC}/${RED}[no]${NC}: "

    while true; do
        read -e ENABLE_TLS
        ENABLE_TLS=$(echo "$ENABLE_TLS" | tr '[:upper:]' '[:lower:]')  
        
        if [[ "$ENABLE_TLS" == "yes" || "$ENABLE_TLS" == "no" ]]; then
            echo -e "${INFO}[INFO] TLS enabled: ${GREEN}$ENABLE_TLS${NC}" 
            break
        else
            echo -ne "${RED}Wrong input. Please type ${GREEN}yes${RED} or ${RED}no${NC}: "
        fi
    done

    if [ "$ENABLE_TLS" = "yes" ]; then
        while true; do
            echo -ne "${YELLOW}Enter your ${GREEN}Sub-domain name${YELLOW}:${NC} "
            read -e DOMAIN_NAME
            if [ -n "$DOMAIN_NAME" ]; then
                echo -e "${INFO}[INFO] Sub-domain set to: ${GREEN}$DOMAIN_NAME${NC}" 
                break
            else
                echo -e "${RED}Sub-domain name cannot be empty. Please try again.${NC}"
            fi
        done

        while true; do
            echo -ne "${YELLOW}Enter your ${GREEN}Email address${YELLOW}:${NC} "
            read -e EMAIL
            if [[ "$EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
                echo -e "${INFO}[INFO] Email set to: ${GREEN}$EMAIL${NC}" 
                break
            else
                echo -e "${RED}Wrong email address. Please enter a valid email.${NC}"
            fi
        done

        echo -e "${INFO}[INFO]${YELLOW} Requesting a TLS certificate from Let's Encrypt...${NC}"
        systemctl stop nginx 2>/dev/null || true
        fuser -k 80/tcp 2>/dev/null || true

        if sudo certbot certonly --standalone --non-interactive --keep-until-expiring --agree-tos --email "$EMAIL" -d "$DOMAIN_NAME" 2>&1; then
            CERT_PATH="/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem"
            KEY_PATH="/etc/letsencrypt/live/$DOMAIN_NAME/privkey.pem"
            chmod -R 755 /etc/letsencrypt/live/ 2>/dev/null || true
            chmod -R 755 /etc/letsencrypt/archive/ 2>/dev/null || true

            echo -e "${SUCCESS}[SUCCESS] TLS certificate successfully obtained for ${GREEN}$DOMAIN_NAME${NC}."

            if [ ! -f "$CONFIG_YAML" ]; then
                cat <<EOF > "$CONFIG_YAML"
tls: false
cert_path: ""
key_path: ""
EOF
            fi

            sed -i "s|tls: false|tls: true|g" "$CONFIG_YAML"
            sed -i "s|cert_path: \"\"|cert_path: \"$CERT_PATH\"|g" "$CONFIG_YAML"
            sed -i "s|key_path: \"\"|key_path: \"$KEY_PATH\"|g" "$CONFIG_YAML"

            echo -e "${SUCCESS}[SUCCESS] TLS configuration successfully added to config.yaml.${NC}"
        else
            echo -e "${RED}[ERROR] Failed to obtain TLS certificate.${NC}"
        fi
    else
        echo -e "${CYAN}[INFO] Skipping TLS setup.${NC}"
    fi
}

show_flask_info() {
    FLASK_PORT=$(grep -i 'port' "$CONFIG_YAML" 2>/dev/null | awk '{print $2}')
    FLASK_PORT=${FLASK_PORT:-5000}
    TLS_ENABLED=$(grep -i 'tls' "$CONFIG_YAML" 2>/dev/null | awk '{print $2}')
    CERT_PATH=$(grep -i 'cert_path' "$CONFIG_YAML" 2>/dev/null | awk '{print $2}')
    FLASK_PUBLIC_IP=$(curl -s -4 https://icanhazip.com || hostname -I | awk '{print $1}') 

    if [ "$TLS_ENABLED" == "true" ]; then
        SUBDOMAIN=$(echo "$CERT_PATH" | awk -F'/' '{print $(NF-1)}')  

       echo -e "\033[93m══════════════════════════════════\033[0m"
       echo -e "${GREEN}🎉 TLS is enabled! 🎉${NC}"
       echo -e "${CYAN}You can access your Flask app at:${NC}"
       echo -e "${BLUE}https://${SUBDOMAIN}:${FLASK_PORT}${NC}"
       echo -e "\033[93m══════════════════════════════════\033[0m"
    else
        echo -e "\033[93m══════════════════════════════════\033[0m"
        echo -e "${GREEN}🔥 Flask is running without TLS! 🔥${NC}"
        echo -e "${CYAN}You can access your Flask app at:${NC}"
        echo -e "${BLUE}${FLASK_PUBLIC_IP}:${FLASK_PORT}${NC}"
        echo -e "\033[93m══════════════════════════════════\033[0m"
    fi
}

wireguardconf() {
    echo -e "\n${BLUE}[INFO]=== Wireguard Installation and Configuration ===${NC}\n"

    if ! command -v wg &>/dev/null; then
        apt-get update -y && apt-get install -y wireguard
    fi

    while true; do
        echo -ne "${YELLOW}Enter Wireguard interface name (example wg0):${NC} "
        read -e WG_NAME
        if [ -n "$WG_NAME" ]; then break; fi
    done

    local WG_CONFIG="/etc/wireguard/${WG_NAME}.conf"
    local SERVER_INTERFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
    [ -z "${SERVER_INTERFACE}" ] && SERVER_INTERFACE="eth0"

    # Preserving existing config if already present
    if [ -f "${WG_CONFIG}" ]; then
        echo -e "${INFO}[INFO] Existing configuration found for ${WG_NAME}. Preserving interface settings & peers...${NC}"
        systemctl restart "wg-quick@${WG_NAME}" 2>/dev/null || wg-quick up "${WG_NAME}" 2>/dev/null || true
        echo -e "${SUCCESS}Wireguard interface ${WG_NAME} refreshed successfully!${NC}"
        echo -e "${CYAN}Press Enter to continue...${NC}" && read -r
        return
    fi

    local PRIVATE_KEY=$(wg genkey)

    while true; do
        echo -ne "${YELLOW}Enter Wireguard private IP (example 10.0.0.1/16):${NC} "
        read -e WG_ADDRESS
        if [[ "$WG_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then break; fi
    done

    while true; do
        echo -ne "${YELLOW}Enter Wireguard listen port (example 20850):${NC} "
        read -e WG_PORT
        if [[ "$WG_PORT" =~ ^[0-9]+$ ]]; then break; fi
    done

    while true; do
        echo -ne "${YELLOW}Enter MTU size (example 1420):${NC} "
        read -e MTU
        if [[ "$MTU" =~ ^[0-9]+$ ]]; then break; fi
    done

    sudo mkdir -p /etc/wireguard

    cat <<EOL > "${WG_CONFIG}"
[Interface]
Address = ${WG_ADDRESS}
ListenPort = ${WG_PORT}
PrivateKey = ${PRIVATE_KEY}
MTU = ${MTU}

PostUp = iptables -I INPUT -p udp --dport ${WG_PORT} -j ACCEPT
PostUp = iptables -I FORWARD -i ${SERVER_INTERFACE} -o ${WG_NAME} -j ACCEPT; iptables -I FORWARD -i ${WG_NAME} -j ACCEPT; iptables -t nat -A POSTROUTING -o ${SERVER_INTERFACE} -j MASQUERADE
PostDown = iptables -D INPUT -p udp --dport ${WG_PORT} -j ACCEPT
PostDown = iptables -D FORWARD -i ${SERVER_INTERFACE} -o ${WG_NAME} -j ACCEPT; iptables -D FORWARD -i ${WG_NAME} -j ACCEPT; iptables -t nat -D POSTROUTING -o ${SERVER_INTERFACE} -j MASQUERADE
EOL

    chmod 600 "${WG_CONFIG}"
    systemctl daemon-reload
    systemctl enable "wg-quick@${WG_NAME}" 2>/dev/null || true
    systemctl restart "wg-quick@${WG_NAME}" 2>/dev/null || wg-quick up "${WG_NAME}"

    echo -e "\n${GREEN}Wireguard interface ${WG_NAME} created & activated successfully!${NC}"
    echo -e "${CYAN}Press Enter to continue...${NC}" && read -r
}

create_config() {
    echo -e "${INFO}[INFO] Creating or updating Enterprise Flask & Gunicorn setup (Preserving database & peers)...${NC}"

    RECOMMENDED_WORKERS=$(nproc 2>/dev/null)
    RECOMMENDED_WORKERS=${RECOMMENDED_WORKERS:-2}
    AUTO_SECRET=$(openssl rand -hex 16 2>/dev/null || echo "dov")

    read -e -p "Enter Flask port [default: 5000]: " FLASK_PORT
    FLASK_PORT=${FLASK_PORT:-5000}

    read -e -p "Enable Flask debug mode? [yes/no] [default: no]: " FLASK_DEBUG
    FLASK_DEBUG=${FLASK_DEBUG:-no}
    FLASK_DEBUG=$(echo "$FLASK_DEBUG" | grep -iq "^y" && echo "true" || echo "false")

    read -e -p "Enter Gunicorn workers [default: ${RECOMMENDED_WORKERS}]: " GUNICORN_WORKERS
    GUNICORN_WORKERS=${GUNICORN_WORKERS:-$RECOMMENDED_WORKERS}

    read -e -p "Enter Gunicorn threads per worker [default: 2]: " GUNICORN_THREADS
    GUNICORN_THREADS=${GUNICORN_THREADS:-2}

    read -e -p "Enter Gunicorn timeout in seconds [default: 120]: " GUNICORN_TIMEOUT
    GUNICORN_TIMEOUT=${GUNICORN_TIMEOUT:-120}

    read -e -p "Enter Gunicorn log level [default: info]: " GUNICORN_LOGLEVEL
    GUNICORN_LOGLEVEL=${GUNICORN_LOGLEVEL:-info}

    read -e -p "Enter Flask secret key [default: dov]: " FLASK_SECRET_KEY
    FLASK_SECRET_KEY=${FLASK_SECRET_KEY:-$AUTO_SECRET}

    setup_tls

    cat <<EOL >"$CONFIG_YAML"
flask:
  port: $FLASK_PORT
  tls: $([ "$ENABLE_TLS" = "yes" ] && echo "true" || echo "false")
  cert_path: "$CERT_PATH"
  key_path: "$KEY_PATH"
  secret_key: "$FLASK_SECRET_KEY"
  debug: $FLASK_DEBUG

gunicorn:
  workers: $GUNICORN_WORKERS
  threads: $GUNICORN_THREADS
  loglevel: "$GUNICORN_LOGLEVEL"
  timeout: $GUNICORN_TIMEOUT

wireguard:
  config_dir: "/etc/wireguard"
EOL

    sync_persistent_config
    wireguard_panel
}

wireguard_panel() {
    APP_FILE="$SCRIPT_DIR/app.py"
    VENV_DIR="$SCRIPT_DIR/venv"
    SERVICE_FILE="/etc/systemd/system/wireguard-panel.service"

    ensure_venv_exists

    EXEC_PY="$VENV_DIR/bin/python3"
    if [ ! -f "$EXEC_PY" ]; then EXEC_PY=$(which python3); fi

    local target_port=$(get_configured_port)

    echo -e "${INFO}[INFO] Freeing port ${target_port}, cleaning lock files, and starting Systemd service...${NC}"
    
    sudo ufw allow ${target_port}/tcp 2>/dev/null || true
    sudo iptables -I INPUT -p tcp --dport ${target_port} -j ACCEPT 2>/dev/null || true

    rm -f "$SCRIPT_DIR/jobs.sqlite"* /tmp/*.lock 2>/dev/null || true

    chmod -R 755 /etc/letsencrypt/live/ 2>/dev/null || true
    chmod -R 755 /etc/letsencrypt/archive/ 2>/dev/null || true
    chmod 644 /etc/letsencrypt/archive/*/* 2>/dev/null || true

    sudo systemctl stop wireguard-panel.service 2>/dev/null || true
    fuser -k -9 ${target_port}/tcp 2>/dev/null || true
    pkill -9 -f "app.py" 2>/dev/null || true
    killall -9 gunicorn 2>/dev/null || true

    sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=Wireguard Panel
After=network.target redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=$EXEC_PY $APP_FILE
Restart=always
RestartSec=2
KillMode=mixed
Environment=PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOL

    sudo chmod 644 "$SERVICE_FILE"
    sudo systemctl daemon-reload
    sudo systemctl reset-failed wireguard-panel.service 2>/dev/null || true
    sudo systemctl enable wireguard-panel.service
    sudo systemctl restart wireguard-panel.service
    sync_persistent_config
    
    install_panel_url_tool 2>/dev/null || true
    sleep 3

    if ! is_panel_service_running; then
        nohup "$EXEC_PY" "$APP_FILE" > /tmp/panel_direct.log 2>&1 &
        sleep 2
    fi

    show_flask_info
    echo -e "${CYAN}Press Enter to continue...${NC}" && read
}

ensure_zip_tools

RUN_INSTALL=false

clean_panel_app_only() {
    local current_p=$(get_configured_port)
    echo -e "${INFO}[INFO] Re-configuring panel services (preserving all database records, users, and WireGuard interfaces)...${NC}"
    
    systemctl stop wireguard-panel.service 2>/dev/null || true

    # Preserve DB & Configurations
    mkdir -p "$SCRIPT_DIR/backup_restore"
    [ -f "$SCRIPT_DIR/db.sqlite3" ] && cp "$SCRIPT_DIR/db.sqlite3" "$SCRIPT_DIR/backup_restore/"
    [ -f "$PERSISTENT_DB" ] && cp "$PERSISTENT_DB" "$SCRIPT_DIR/backup_restore/"
    [ -f "$CONFIG_YAML" ] && cp "$CONFIG_YAML" "$SCRIPT_DIR/backup_restore/"

    fuser -k -9 ${current_p}/tcp 2>/dev/null || true
    pkill -9 -f "app.py" 2>/dev/null || true
    killall -9 gunicorn 2>/dev/null || true

    # Restore DB & Configurations if missing
    [ ! -f "$SCRIPT_DIR/db.sqlite3" ] && [ -f "$SCRIPT_DIR/backup_restore/db.sqlite3" ] && cp "$SCRIPT_DIR/backup_restore/db.sqlite3" "$SCRIPT_DIR/"
    [ ! -f "$PERSISTENT_DB" ] && [ -f "$SCRIPT_DIR/backup_restore/db_backup.sqlite3" ] && cp "$SCRIPT_DIR/backup_restore/db_backup.sqlite3" "$PERSISTENT_DB"

    rm -rf "$SCRIPT_DIR/backup_restore"
}

if is_panel_installed; then
    display_logo
    echo -e "${WARNING}⚠️ Wireguard Panel is already installed on this server!${NC}"
    echo -ne "${YELLOW}Do you want to re-configure or update the panel? ${GREEN}[y]${NC}/${RED}[N]${NC}: "
    read -r CONFIRM_REINSTALL
    CONFIRM_REINSTALL=$(echo "$CONFIRM_REINSTALL" | tr '[:upper:]' '[:lower:]')

    if [[ "$CONFIRM_REINSTALL" == "y" || "$CONFIRM_REINSTALL" == "yes" ]]; then
        RUN_INSTALL=true
        clean_panel_app_only
    else
        echo -e "\n${INFO}[INFO] Re-configuration skipped. Preserving existing data and loading main menu...${NC}\n"
    fi
else
    RUN_INSTALL=true
fi

if [ "$RUN_INSTALL" = true ]; then
    if [ -f "$OFFLINE_ZIP" ]; then
        display_logo
        echo -e "${INFO}📦 Offline ZIP package found (${OFFLINE_ZIP}).${NC}"
        echo -e " ${GREEN}1)${CYAN} Use existing offline ZIP package (Fast, No Download)${NC}"
        echo -e " ${GREEN}2)${CYAN} Fresh Install from Internet & Recreate ZIP package${NC}"
        echo -ne "${YELLOW}Choose an option [1-2]: ${NC}"
        read -r ZIP_MODE

        if [ "$ZIP_MODE" == "1" ]; then
            extract_and_install_from_zip
        else
            install_requirements
            setup_virtualenv
            create_offline_zip_package
        fi
    else
        display_logo
        echo -e "${INFO}[INFO] Initializing fresh installation from Internet...${NC}"
        install_requirements
        setup_virtualenv
        create_offline_zip_package
    fi
fi

sync_persistent_config
install_panel_url_tool 2>/dev/null || true

while true; do
    display_menu
    echo -ne "${NC}Choose an option [0-7]: ${NC}"
    read -r USER_CHOICE
    select_stuff "$USER_CHOICE"
done
