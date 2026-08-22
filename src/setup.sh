#!/bin/bash
# =============================================================================
# نام فایل: setup.sh
# نقش: نصب، مدیریت، بهینه‌سازی و راه‌اندازی WireGuard Panel + PHP Master Control Hub
# پورت کنترل‌سنتر و API: 6000
# =============================================================================

export LANG=C.UTF-8
export LC_ALL=C.UTF-8

SCRIPT_DIR=$(dirname "$(realpath "$0")")
PANEL_DIR="/usr/local/bin/Wireguard-panel"
HUB_DIR="$SCRIPT_DIR/hub"
HUB_PORT=6000
HUB_CREDENTIALS="/etc/wireguard/hub_credentials.json"
PERSISTENT_CFG="/etc/wireguard/panel_config_backup.yaml"
PERSISTENT_DB="/etc/wireguard/db_backup.sqlite3"
CONFIG_YAML="$SCRIPT_DIR/config.yaml"
OFFLINE_ZIP="/root/wireguard-panel-offline.zip"

RED='\033[0;31m'
GREEN='\033[1;92m'
YELLOW='\033[1;33m'
BLUE='\033[96m'
CYAN='\033[0;36m'
NC='\033[0m' 
INFO="\033[96m"      
SUCCESS="\033[1;92m"    
WARNING="\033[1;33m"   
ERROR="\033[0;31m"      

# خودکارسازی ترمیم iptables در صورت شکستگی لینک‌ها
if ! iptables -L -n >/dev/null 2>&1; then
    rm -f /usr/sbin/iptables /usr/sbin/iptables-save /usr/sbin/iptables-restore /sbin/iptables 2>/dev/null
    ln -sf /usr/sbin/xtables-legacy-multi /usr/sbin/iptables
    ln -sf /usr/sbin/xtables-legacy-multi /usr/sbin/iptables-save
    ln -sf /usr/sbin/xtables-legacy-multi /usr/sbin/iptables-restore
    ln -sf /usr/sbin/xtables-legacy-multi /sbin/iptables 2>/dev/null || true
fi

logo=$(cat << "EOF"
  ____                  _____                    
 |  _ \ __ _ _ __ ___  |__  /___  _ __   ___     
 | |_) / _` | '__/ __|   / // _ \| '_ \ / _ \    
 |  __/ (_| | |  \__ \  / /| (_) | | | |  __/    
 |_|   \__,_|_|  |___/ /____\___/|_| |_|\___|    Author: github.com/ParsZone
EOF
)

display_logo() {
    echo -e "$logo"
}

get_public_ip() {
    curl -s -4 -m 3 https://icanhazip.com || curl -s -4 -m 3 https://api.ipify.org || hostname -I | awk '{print $1}'
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

ensure_zip_tools() {
    if ! command -v unzip &>/dev/null || ! command -v zip &>/dev/null; then
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y -qq zip unzip >/dev/null 2>&1
    fi
}

ensure_pars_admin_exists() {
    local db_file="$SCRIPT_DIR/db.sqlite3"
    local py_bin="$SCRIPT_DIR/venv/bin/python3"
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

install_panel_url_tool() {
    sed -i '/alias panel-url=/d' ~/.bashrc 2>/dev/null || true
    cat << 'EOF' > /usr/local/bin/panel-url
#!/bin/bash
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
CFG="/usr/local/bin/Wireguard-panel/src/config.yaml"
[ ! -f "$CFG" ] && CFG="/etc/wireguard/panel_config_backup.yaml"
if [ ! -f "$CFG" ]; then
    echo "❌ Config file not found. Please setup panel first."
    exit 1
fi
PORT=$(grep 'port:' "$CFG" 2>/dev/null | head -n 1 | awk '{print $2}' | tr -d '"' | tr -d "'")
PORT=${PORT:-5000}
TLS=$(grep 'tls:' "$CFG" 2>/dev/null | head -n 1 | awk '{print $2}')
IP=$(curl -s -4 -m 3 https://icanhazip.com || hostname -I | awk '{print $1}')
IS_RUNNING=false
if systemctl is-active --quiet wireguard-panel.service 2>/dev/null; then
    IS_RUNNING=true
elif ss -tulpn 2>/dev/null | grep -q ":$PORT "; then
    IS_RUNNING=true
fi
if [ "$IS_RUNNING" = true ]; then
    STATUS_STR="\033[1;92m🟢 Online (Active)\033[0m"
else
    STATUS_STR="\033[1;31m🔴 Offline (Inactive)\033[0m"
fi
if [ "$TLS" == "true" ]; then
    CERT=$(grep 'cert_path:' "$CFG" 2>/dev/null | head -n 1 | awk '{print $2}' | tr -d '"' | tr -d "'")
    DOMAIN=$(echo "$CERT" | awk -F'/' '{print $(NF-1)}')
    [ -n "$DOMAIN" ] && URL="https://${DOMAIN}:${PORT}" || URL="https://${IP}:${PORT}"
else
    URL="http://${IP}:${PORT}"
fi
echo -e "\033[96m==========================================\033[0m"
echo -e "📡 Service Status : ${STATUS_STR}"
echo -e "🌐 Flask Panel URL: \033[1;33m${URL}\033[0m"
if [ -f "/etc/wireguard/hub_credentials.json" ]; then
    HUB_URL=$(grep '"index_url"' /etc/wireguard/hub_credentials.json | awk -F'"' '{print $4}')
    API_URL=$(grep '"api_url"' /etc/wireguard/hub_credentials.json | awk -F'"' '{print $4}')
    API_KEY=$(grep '"api_key"' /etc/wireguard/hub_credentials.json | awk -F'"' '{print $4}')
    echo -e "💻 PHP Control Hub: \033[1;32m${HUB_URL}\033[0m"
    echo -e "🤖 Bot API URL    : \033[1;36m${API_URL}\033[0m"
    echo -e "🔑 Hub API Key    : \033[1;33m${API_KEY}\033[0m"
fi
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

is_panel_installed() {
    [ -f "/etc/systemd/system/wireguard-panel.service" ] || [ -f "$CONFIG_YAML" ] || [ -f "$PERSISTENT_CFG" ]
}

is_panel_service_running() {
    local check_port=$(get_configured_port)
    STATUS=$(systemctl is-active wireguard-panel.service 2>/dev/null)
    if [ "$STATUS" == "active" ] || [ "$STATUS" == "activating" ]; then
        return 0
    elif ss -tulpn 2>/dev/null | grep -q ":${check_port} "; then
        return 0
    elif pgrep -f "app.py" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

ensure_venv_exists() {
    if [ ! -f "$SCRIPT_DIR/venv/bin/python3" ]; then
        echo -e "${INFO}[INFO] Creating Python virtual environment at $SCRIPT_DIR/venv ...${NC}"
        python3 -m venv --system-site-packages "$SCRIPT_DIR/venv" 2>/dev/null || python3 -m venv "$SCRIPT_DIR/venv"
        source "$SCRIPT_DIR/venv/bin/activate" 2>/dev/null || true
        pip install --upgrade pip -q 2>/dev/null || true
        pip install Flask gunicorn pyyaml flask-session Flask-Limiter Flask-Bcrypt Flask-Caching requests SQLAlchemy werkzeug jinja2 python-dotenv python-telegram-bot aiohttp matplotlib qrcode jsonschema psutil pynacl apscheduler redis fasteners pexpect cryptography pillow arabic-reshaper python-bidi pytz jdatetime -q 2>/dev/null || true
        deactivate 2>/dev/null || true
    fi
}

install_requirements() {
    echo -e "${INFO}[INFO] Installing required packages & PHP backend extensions...${NC}"
    sudo rm -f /etc/apt/sources.list.d/*manageit* /etc/apt/sources.list.d/*docker* 2>/dev/null || true
    sudo apt update -y && sudo apt install -y python3 python3-pip python3-venv git redis-server nftables iptables wireguard-tools iproute2 \
        fonts-dejavu certbot curl software-properties-common wget zip unzip \
        php-cli php-ssh2 php-sqlite3 php-curl php-zip php-mbstring sshpass || {
        echo -e "${ERROR}Installation failed. Ensure you are using root privileges.${NC}"
        exit 1
    }
    sudo systemctl enable redis-server.service 2>/dev/null || true
    sudo systemctl start redis-server.service 2>/dev/null || true
    echo -e "${SUCCESS}[SUCCESS] All requirements and PHP extensions installed.${NC}"
}

setup_virtualenv() {
    echo -e "${INFO}[INFO] Setting up Python Virtual Environment...${NC}"
    ensure_venv_exists
    echo -e "${SUCCESS}[SUCCESS] Virtual environment ready.${NC}"
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

# =============================================================================
# ماژول اختصاصی استقرار کامل PHP Control Center & API Bot روی پورت 6000
# =============================================================================
deploy_php_control_hub() {
    local target_ip=$(get_public_ip)
    local hub_port=$HUB_PORT
    local api_key="@Hasan89732900"

    echo -e "\n${INFO}[INFO] Deploying PHP Control Hub & Bot API Endpoint on port ${hub_port}...${NC}"
    mkdir -p "$HUB_DIR"
    mkdir -p /etc/wireguard

    # بازیابی API_KEY قبلی در صورت وجود
    if [ -f "$HUB_CREDENTIALS" ]; then
        saved_key=$(grep '"api_key"' "$HUB_CREDENTIALS" | awk -F'"' '{print $4}')
        [ -n "$saved_key" ] && api_key="$saved_key"
    fi

    # ایجاد خودکار api_bot.php در صورت عدم وجود
    if [ ! -f "$HUB_DIR/api_bot.php" ] || [ ! -s "$HUB_DIR/api_bot.php" ]; then
        cat << 'EOF' > "$HUB_DIR/api_bot.php"
<?php
ob_start();
header('Content-Type: application/json; charset=utf-8');

register_shutdown_function(function() {
    $e = error_get_last();
    if ($e !== NULL && in_array($e['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR])) {
        if (ob_get_length()) ob_clean();
        echo json_encode([
            'status'  => 'error',
            'message' => 'Fatal Error: ' . $e['message'],
            'file'    => basename($e['file']),
            'line'    => $e['line']
        ], JSON_UNESCAPED_UNICODE);
    }
});

$API_KEY = "__BOT_API_KEY__"; 

$raw_input = file_get_contents('php://input');
$input = @json_decode($raw_input, true);

if (!is_array($input) || !isset($input['api_key']) || !hash_equals($API_KEY, (string)$input['api_key'])) {
    http_response_code(401);
    die(json_encode([
        'status'  => 'error', 
        'message' => 'Unauthenticated: Invalid or Missing API Key.'
    ], JSON_UNESCAPED_UNICODE));
}

$action             = $input['action'] ?? '';
$saved_masters_file = __DIR__ . '/.saved_masters.php';
$registry_file      = __DIR__ . '/local_servers_registry.json';
$p_dir              = '/usr/local/bin/Wireguard-panel/src';
$py_bin             = $p_dir . '/venv/bin/python3';
if (!file_exists($py_bin)) { $py_bin = 'python3'; }

function get_local_registry() {
    global $registry_file;
    if (file_exists($registry_file)) {
        return json_decode(file_get_contents($registry_file), true) ?: [];
    }
    return [];
}

function save_local_registry($data) {
    global $registry_file;
    file_put_contents($registry_file, json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
}

function register_local_interface($host, $iface, $details) {
    $reg = get_local_registry();
    if (!isset($reg[$host])) { $reg[$host] = ['host' => $host, 'interfaces' => []]; }
    if (!isset($reg[$host]['interfaces'])) { $reg[$host]['interfaces'] = []; }
    $existing = $reg[$host]['interfaces'][$iface] ?? [];
    if (isset($existing['used_gb']) && isset($details['used_gb'])) {
        if ($details['used_gb'] < $existing['used_gb']) { $details['used_gb'] = $existing['used_gb']; }
    }
    $reg[$host]['interfaces'][$iface] = array_merge($existing, $details);
    save_local_registry($reg);
}

function remove_local_interface($host, $iface) {
    $reg = get_local_registry();
    if (isset($reg[$host]['interfaces'][$iface])) {
        unset($reg[$host]['interfaces'][$iface]);
        save_local_registry($reg);
    }
}

function get_saved_masters() {
    global $saved_masters_file;
    if (file_exists($saved_masters_file)) {
        $raw = file_get_contents($saved_masters_file);
        return json_decode(str_replace('<?php die(); ?>', '', $raw), true) ?: [];   
    }
    return [];
}

function exec_py($ssh, $py_bin, $script_code, $args = "") {
    if (!$ssh) return "ERROR_NO_SSH_CONNECTION";
    $cmd_file = "/tmp/api_cmd_" . time() . "_" . rand(1000, 9999) . ".py";
    $b64_code = base64_encode($script_code);
    $exec_cmd = "echo '{$b64_code}' | base64 -d > {$cmd_file} && {$py_bin} {$cmd_file} {$args} 2>&1; rm -f {$cmd_file}";
    $st = @ssh2_exec($ssh, $exec_cmd);
    if ($st) {
        stream_set_blocking($st, true);
        $out = "";
        while ($line = fgets($st)) { $out .= $line; }
        fclose($st);
        return trim($out);
    }
    return "ERROR_SSH_EXECUTION_FAILED";
}

function connect_to_server($ip) {
    $servers = get_saved_masters();
    if (!isset($servers[$ip])) return false;
    $s = $servers[$ip];
    $conn = @ssh2_connect($s['h'], $s['p']);
    if ($conn && @ssh2_auth_password($conn, $s['u'], base64_decode($s['pw']))) {
        return $conn;
    }
    return false;
}

if ($action === 'get_servers') {
    $servers = get_saved_masters();
    $list = [];
    foreach ($servers as $ip => $data) {
        $list[] = ['ip' => $ip, 'port' => $data['p'], 'user' => $data['u']];
    }
    echo json_encode(['status' => 'success', 'data' => $list], JSON_UNESCAPED_UNICODE);
    exit;
}

$target_ip = trim($input['server_ip'] ?? '');
if (empty($target_ip)) {
    die(json_encode(['status' => 'error', 'message' => 'server_ip is required.'], JSON_UNESCAPED_UNICODE));
}

$ssh = connect_to_server($target_ip);
if (!$ssh) {
    die(json_encode(['status' => 'error', 'message' => "Cannot connect to server {$target_ip} via SSH."], JSON_UNESCAPED_UNICODE));
}

if ($action === 'get_resellers') {
    $py_code = <<<'PYTHON'
import sqlite3, os, json, re
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
resellers = []
try:
    conn = sqlite3.connect(db_path, timeout=10.0)
    cur = conn.cursor()
    universal_vault = {}
    try:
        cur.execute("SELECT interface_name, vault_bytes FROM interface_vault")
        for iv_name, iv_bytes in cur.fetchall(): universal_vault[iv_name] = iv_bytes or 0
    except: pass
    cur.execute("SELECT interface_name, username, password_plain, data_limit_gb, port, status, deleted_traffic FROM sub_panels")
    for r in cur.fetchall():
        iface, user, pw, limit, port, status, del_traf = r
        del_traf = del_traf or 0
        cur.execute("SELECT SUM(used) FROM peers WHERE config=?", (f"{iface}.conf",))
        live_used = cur.fetchone()[0] or 0
        vault_t = universal_vault.get(iface, 0)
        total_bytes = live_used + max(del_traf, vault_t)
        used_gb = round(total_bytes / 1073741824.0, 2)
        limit_val = float(limit) if limit else 100.0
        rem_gb = round(max(0.0, limit_val - used_gb), 2)
        subnet = "10.0.10.1/24"
        conf_path = f"/etc/wireguard/{iface}.conf"
        if os.path.exists(conf_path):
            try:
                txt = open(conf_path, 'r', encoding='utf-8').read()
                m = re.search(r'Address\s*=\s*([^\s]+)', txt, re.IGNORECASE)
                if m: subnet = m.group(1).strip()
            except: pass
        resellers.append({
            "interface": iface, "username": user, "password": pw,
            "limit_gb": limit_val, "used_gb": used_gb, "rem_gb": rem_gb,
            "status": status, "port": port, "subnet": subnet
        })
    conn.close()
    print(json.dumps(resellers))
except Exception as e:
    print(json.dumps({"error": str(e)}))
PYTHON;
    $out = exec_py($ssh, $py_bin, $py_code);
    $decoded = json_decode($out, true);
    if (is_array($decoded) && !isset($decoded['error'])) {
        foreach ($decoded as $r) {
            register_local_interface($target_ip, $r['interface'], [
                'interface_name' => $r['interface'],
                'username'       => $r['username'],
                'password_plain' => $r['password'],
                'data_limit_gb'  => $r['limit_gb'],
                'used_gb'        => $r['used_gb'],
                'port'           => $r['port'],
                'subnet_ip'      => $r['subnet'],
                'status'         => $r['status']
            ]);
        }
    }
    echo json_encode(['status' => 'success', 'data' => $decoded], JSON_UNESCAPED_UNICODE);
    exit;
}

if ($action === 'get_metrics') {
    $py_metrics = <<<'PYTHON'
import os, sys, subprocess, json, time
def fmt(b):
    if b >= 1073741824: return f"{b/1073741824:.2f} GB"
    if b >= 1048576: return f"{b/1048576:.2f} MB"
    return f"{b/1024:.2f} KB"
cpu = 0
try:
    with open('/proc/stat') as f: l1 = list(map(int, f.readline().split()[1:]))
    time.sleep(0.3)
    with open('/proc/stat') as f: l2 = list(map(int, f.readline().split()[1:]))
    t1, t2 = sum(l1), sum(l2)
    cpu = round(100 * (1 - (l2[3] - l1[3]) / (t2 - t1)), 1) if t2 > t1 else 0
except: pass
ram_data = {}
try:
    with open('/proc/meminfo') as f:
        md = {p[0]: int(p[1].split()[0]) * 1024 for p in (l.split(':') for l in f if ':' in l)}
    mt, ma = md.get('MemTotal', 1), md.get('MemAvailable', 0)
    mu = mt - ma
    ram_data = {'total': fmt(mt), 'used': fmt(mu), 'percent': round((mu / mt) * 100, 1)}
except: pass
disk_data = {}
try:
    st = os.statvfs('/')
    dt, df = st.f_blocks * st.f_frsize, st.f_bfree * st.f_frsize
    du = dt - df
    disk_data = {'total': fmt(dt), 'used': fmt(du), 'percent': round((du / dt) * 100, 1)}
except: pass
wg_transfer = {'rx': '0 KB', 'tx': '0 KB', 'total': '0 KB'}
try:
    out = subprocess.check_output(['wg', 'show', 'all', 'transfer'], text=True)
    rx, tx = 0, 0
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 3:
            rx += int(p[1])
            tx += int(p[2])
    wg_transfer = {'rx': fmt(rx), 'tx': fmt(tx), 'total': fmt(rx + tx)}
except: pass
print(json.dumps({'cpu_percent': cpu, 'ram': ram_data, 'disk': disk_data, 'wireguard_transfer': wg_transfer}))
PYTHON;
    $out = exec_py($ssh, $py_bin, $py_metrics);
    echo json_encode(['status' => 'success', 'data' => json_decode($out, true)], JSON_UNESCAPED_UNICODE);
    exit;
}

echo json_encode(['status' => 'error', 'message' => 'Action handler executed.'], JSON_UNESCAPED_UNICODE);
?>
EOF
        sed -i "s|__BOT_API_KEY__|$api_key|g" "$HUB_DIR/api_bot.php"
    fi

    # کپی فایل index.php در صورت وجود در سورس
    if [ -f "$SCRIPT_DIR/index.php" ]; then
        cp -f "$SCRIPT_DIR/index.php" "$HUB_DIR/index.php"
    elif [ -f "$PANEL_DIR/index.php" ]; then
        cp -f "$PANEL_DIR/index.php" "$HUB_DIR/index.php"
    fi

    # ایجاد سرویس دائمی Systemd برای وب‌سرور PHP روی پورت 6000
    cat << EOF > /etc/systemd/system/wireguard-php-hub.service
[Unit]
Description=WireGuard PHP Control Hub & Bot API (Port ${hub_port})
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$HUB_DIR
ExecStart=/usr/bin/php -S 0.0.0.0:${hub_port} -t $HUB_DIR
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable wireguard-php-hub.service 2>/dev/null || true
    systemctl restart wireguard-php-hub.service 2>/dev/null || true

    # ذخیره دائمی مشخصات در /etc/wireguard
    local index_url="http://${target_ip}:${hub_port}/index.php"
    local api_url="http://${target_ip}:${hub_port}/api_bot.php"

    cat << EOF > "$HUB_CREDENTIALS"
{
  "index_url": "${index_url}",
  "api_url": "${api_url}",
  "api_key": "${api_key}",
  "port": ${hub_port},
  "default_user": "Pars",
  "default_pass": "Pars"
}
EOF
    chmod 600 "$HUB_CREDENTIALS"
    cp -f "$HUB_CREDENTIALS" "$SCRIPT_DIR/hub_credentials.json" 2>/dev/null || true

    echo -e "${SUCCESS}✔ PHP Hub & Bot API successfully deployed on port ${hub_port}.${NC}"
}

# =============================================================================
# گزینه ۳: اعمال دسترسی‌ها، فعال‌سازی سرویس‌ها و استقرار کامل PHP Hub
# =============================================================================
setup_permissions() {
    local target_port=$(get_configured_port)
    echo -e "${INFO}[INFO] Setting permissions, deploying PHP Hub (Port ${HUB_PORT}) & re-activating services...${NC}"
    
    install_requirements
    ensure_venv_exists
    
    chmod -R 755 "$SCRIPT_DIR" 2>/dev/null || true
    chmod 644 "$SCRIPT_DIR"/*.py 2>/dev/null || true
    chmod 644 "$SCRIPT_DIR"/config.yaml 2>/dev/null || true
    chmod 600 /etc/wireguard/*.conf 2>/dev/null || true
    chmod -R 755 /etc/letsencrypt/live/ 2>/dev/null || true
    chmod -R 755 /etc/letsencrypt/archive/ 2>/dev/null || true
    chmod 644 /etc/letsencrypt/archive/*/* 2>/dev/null || true
    chmod 666 "$SCRIPT_DIR/db.sqlite3" 2>/dev/null || true
    
    sudo ufw allow ${target_port}/tcp 2>/dev/null || true
    sudo ufw allow ${HUB_PORT}/tcp 2>/dev/null || true
    sudo iptables -I INPUT -p tcp --dport ${target_port} -j ACCEPT 2>/dev/null || true
    sudo iptables -I INPUT -p tcp --dport ${HUB_PORT} -j ACCEPT 2>/dev/null || true
    
    fuser -k -9 ${target_port}/tcp 2>/dev/null || true
    pkill -9 -f "app.py" 2>/dev/null || true
    killall -9 gunicorn 2>/dev/null || true
    rm -f "$SCRIPT_DIR/jobs.sqlite"* /tmp/*.lock 2>/dev/null || true

    # استقرار کامل Control Center و Bot API روی پورت 6000
    deploy_php_control_hub

    # راه‌اندازی سرویس اصلی پایتون
    EXEC_PY="$SCRIPT_DIR/venv/bin/python3"
    [ ! -f "$EXEC_PY" ] && EXEC_PY=$(which python3)

    sudo systemctl daemon-reload 2>/dev/null || true
    sudo systemctl reset-failed wireguard-panel.service 2>/dev/null || true
    sudo systemctl enable wireguard-panel.service 2>/dev/null || true
    sudo systemctl restart wireguard-panel.service 2>/dev/null || true
    
    sync_persistent_config
    install_panel_url_tool 2>/dev/null || true
    sleep 3

    echo -e "${SUCCESS}[SUCCESS] Permissions set and all services (Wireguard, Flask, PHP Hub on port ${HUB_PORT}) successfully active!${NC}\n"
    
    if [ -f "$HUB_CREDENTIALS" ]; then
        local p_idx=$(grep '"index_url"' "$HUB_CREDENTIALS" | awk -F'"' '{print $4}')
        local p_api=$(grep '"api_url"' "$HUB_CREDENTIALS" | awk -F'"' '{print $4}')
        local p_key=$(grep '"api_key"' "$HUB_CREDENTIALS" | awk -F'"' '{print $4}')
        echo -e "${CYAN}╔═══════════════════════════ Control Center & API ══════════════════════════╗${NC}"
        echo -e "  ${GREEN}✔ Control Center URL :${YELLOW} ${p_idx}${NC}"
        echo -e "  ${GREEN}✔ Bot API Endpoint   :${YELLOW} ${p_api}${NC}"
        echo -e "  ${GREEN}✔ Bot API Key        :${YELLOW} ${p_key}${NC}"
        echo -e "  ${GREEN}✔ Default Login      :${CYAN} Pars / Pars${NC}"
        echo -e "${CYAN}╚════════════════════════════════════════════════════════════════════════════╝${NC}"
    fi

    echo -e "\n${CYAN}Press Enter to return to main menu...${NC}" && read
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
    
    # کادر اطلاعات Flask
    if [ -f "$CONFIG_YAML" ]; then
        FLASK_PORT=$(grep 'port:' "$CONFIG_YAML" -A 5 | grep 'port:' | awk '{print $2}')
        FLASK_PORT=${FLASK_PORT:-5000}
        FLASK_TLS=$(grep 'tls:' "$CONFIG_YAML" -A 5 | grep 'tls:' | awk '{print $2}')
        PUBLIC_IPV4_ADDRESS=$(get_public_ip)
        echo -e "${CYAN}╔═════════════════════════ ${YELLOW}Flask Information${CYAN} ═════════════════════════╗${NC}"
        if [ "$FLASK_TLS" == "true" ]; then
            SUBDOMAIN=$(grep 'cert_path:' "$CONFIG_YAML" | awk -F'/' '{print $(NF-1)}')
            echo -e "  ${GREEN}✔ Flask is running with TLS enabled!${NC}"
            echo -e "  ${CYAN}Homepage: ${NC}https://${YELLOW}${SUBDOMAIN}:${FLASK_PORT}${NC}"
        else
            echo -e "  ${YELLOW}✔ Flask is running without TLS!${NC}"
            echo -e "  ${CYAN}Homepage: ${YELLOW}${PUBLIC_IPV4_ADDRESS}:${FLASK_PORT}${NC}"
        fi
        echo -e "${CYAN}╚═════════════════════════════════════════════════════════════════════╝${NC}"
    fi

    # کادر دائمی Control Center و API Bot روی پورت 6000
    if [ -f "$HUB_CREDENTIALS" ]; then
        local p_idx=$(grep '"index_url"' "$HUB_CREDENTIALS" | awk -F'"' '{print $4}')
        local p_api=$(grep '"api_url"' "$HUB_CREDENTIALS" | awk -F'"' '{print $4}')
        local p_key=$(grep '"api_key"' "$HUB_CREDENTIALS" | awk -F'"' '{print $4}')
        echo -e "${CYAN}╔════════════════════ ${YELLOW}Control Center (PHP & Bot API)${CYAN} ═════════════════╗${NC}"
        if systemctl is-active --quiet wireguard-php-hub.service 2>/dev/null; then
            echo -e "  ${GREEN}✔ PHP Hub Service is active (Port ${HUB_PORT})!${NC}"
        else
            echo -e "  ${RED}✖ PHP Hub Service is inactive!${NC}"
        fi
        echo -e "  ${CYAN}Control Center : ${YELLOW}${p_idx}${NC}"
        echo -e "  ${CYAN}API Bot URL    : ${YELLOW}${p_api}${NC}"
        echo -e "  ${CYAN}API Key        : ${YELLOW}${p_key}${NC}"
        echo -e "  ${CYAN}Default Login  : ${GREEN}Pars / Pars${NC}"
        echo -e "${CYAN}╚═════════════════════════════════════════════════════════════════════╝${NC}"
    fi

    echo -e "${CYAN}═════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN} Options:${NC}"
    echo -e "${NC}  0)${CYAN} View Detailed Wireguard Status${NC}"
    echo -e "${NC}  s)${GREEN} Show Logs${NC}"
    echo -e "${NC}  1)${BLUE} Create${YELLOW}/${GREEN}Reset${BLUE} Flask & Gunicorn Configs${NC}"
    echo -e "${NC}  2)${GREEN} Create Wireguard Interface${NC}"
    echo -e "${NC}  3)${BLUE} Set up Permissions & Deploy PHP Hub (Port ${HUB_PORT})${NC}"
    echo -e "${NC}  4)${YELLOW} Set up Wireguard Panel as a Service${NC}"
    echo -e "${NC}  5)${RED} Uninstall${NC}"
    echo -e "${NC}  6)${YELLOW} RESET Username & Password${NC}" 
    echo -e "${NC}  7)${CYAN} Update Panel & Telegram Bot${NC}"
    echo -e "${NC}  q)${RED} Exit${NC}"
    echo -e "${CYAN}═════════════════════════════════════════════════════════════════════${NC}"
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
        echo -e "${ERROR}No Wireguard interfaces found! Check your configuration.${NC}"
    fi
    echo -e "${CYAN}Press Enter to return to the menu...${NC}" && read
}

show_logs() {
    echo -e "${CYAN}═════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}Log Options:${NC}"
    echo -e "${NC}  1)${CYAN} Show Service Logs (Wireguard Panel)${NC}"
    echo -e "${NC}  2)${YELLOW} Show Flask Logs (Last 30 Lines)${NC}"
    echo -e "${NC}  3)${BLUE} Show PHP Control Hub Logs (Port ${HUB_PORT})${NC}"
    echo -e "${NC}  b)${RED} Back to Main Menu${NC}"
    echo -e "${CYAN}═════════════════════════════════════════════════════════════════════${NC}"
    read -rp "Choose an option: " log_choice
    case $log_choice in
        1) journalctl -u wireguard-panel.service --no-pager -n 50 | less ;;  
        2) 
           LOG_FILE="$SCRIPT_DIR/wireguard.log"
           [ -f "$LOG_FILE" ] && tail -n 30 "$LOG_FILE" | less || echo -e "${RED}Log file not found.${NC}"
           ;;
        3) journalctl -u wireguard-php-hub.service --no-pager -n 50 | less ;;
        *) return ;;
    esac
}

wireguardconf() {
    echo -e "\n${BLUE}[INFO]=== Wireguard Installation and Configuration ===${NC}\n"
    if ! command -v wg &>/dev/null; then
        apt-get update -y && apt-get install -y wireguard wireguard-tools
    fi
    while true; do
        echo -ne "${YELLOW}Enter Wireguard interface name (example: wg0):${NC} "
        read -e WG_NAME
        if [ -n "$WG_NAME" ]; then break; fi
    done
    local WG_CONFIG="/etc/wireguard/${WG_NAME}.conf"
    local SERVER_INTERFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
    [ -z "${SERVER_INTERFACE}" ] && SERVER_INTERFACE="eth0"
    if [ -f "${WG_CONFIG}" ]; then
        echo -e "${INFO}[INFO] Existing configuration found for ${WG_NAME}. Refreshing service...${NC}"
        systemctl restart "wg-quick@${WG_NAME}" 2>/dev/null || wg-quick up "${WG_NAME}" 2>/dev/null || true
        echo -e "${SUCCESS}Wireguard interface ${WG_NAME} refreshed successfully!${NC}"
        echo -e "${CYAN}Press Enter to continue...${NC}" && read -r
        return
    fi
    local PRIVATE_KEY=$(wg genkey)
    while true; do
        echo -ne "${YELLOW}Enter Wireguard private IP (example: 10.0.0.1/16):${NC} "
        read -e WG_ADDRESS
        if [[ "$WG_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then break; fi
    done
    while true; do
        echo -ne "${YELLOW}Enter Wireguard listen port (example: 51820):${NC} "
        read -e WG_PORT
        if [[ "$WG_PORT" =~ ^[0-9]+$ ]]; then break; fi
    done
    while true; do
        echo -ne "${YELLOW}Enter MTU size (example: 1420):${NC} "
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
    echo -e "${INFO}[INFO] Creating or updating Flask & Gunicorn setup...${NC}"
    RECOMMENDED_WORKERS=4
    AUTO_SECRET=$(openssl rand -hex 16 2>/dev/null || echo "azumiisinyourarea")
    read -e -p "Enter Flask port [default: 5000]: " FLASK_PORT
    FLASK_PORT=${FLASK_PORT:-5000}
    read -e -p "Enable Flask debug mode? [yes/no] [default: no]: " FLASK_DEBUG
    FLASK_DEBUG=$(echo "$FLASK_DEBUG" | grep -iq "^y" && echo "true" || echo "false")
    read -e -p "Enter Gunicorn workers [default: ${RECOMMENDED_WORKERS}]: " GUNICORN_WORKERS
    GUNICORN_WORKERS=${GUNICORN_WORKERS:-$RECOMMENDED_WORKERS}
    read -e -p "Enter Gunicorn threads per worker [default: 4]: " GUNICORN_THREADS
    GUNICORN_THREADS=${GUNICORN_THREADS:-4}
    read -e -p "Enter Gunicorn timeout in seconds [default: 120]: " GUNICORN_TIMEOUT
    GUNICORN_TIMEOUT=${GUNICORN_TIMEOUT:-120}

    cat <<EOL >"$CONFIG_YAML"
flask:
  port: $FLASK_PORT
  tls: false
  cert_path: ""
  key_path: ""
  secret_key: "$AUTO_SECRET"
  debug: $FLASK_DEBUG
gunicorn:
  workers: $GUNICORN_WORKERS
  threads: $GUNICORN_THREADS
  loglevel: "info"
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
    [ ! -f "$EXEC_PY" ] && EXEC_PY=$(which python3)

    local target_port=$(get_configured_port)
    echo -e "${INFO}[INFO] Starting Systemd service on port ${target_port}...${NC}"
    sudo ufw allow ${target_port}/tcp 2>/dev/null || true
    sudo iptables -I INPUT -p tcp --dport ${target_port} -j ACCEPT 2>/dev/null || true
    
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
    sudo systemctl enable wireguard-panel.service
    sudo systemctl restart wireguard-panel.service
    sync_persistent_config
    install_panel_url_tool 2>/dev/null || true
    deploy_php_control_hub
    sleep 2
    echo -e "${SUCCESS}[SUCCESS] Wireguard Panel is up and running.${NC}"
    echo -e "${CYAN}Press Enter to continue...${NC}" && read
}

reset_credentials() {
    echo -e "${CYAN}===========================================${NC}"
    echo -e "${YELLOW}       User Credentials Management          ${NC}"
    echo -e "${CYAN}===========================================${NC}"
    ensure_pars_admin_exists
    DB_FILE="$SCRIPT_DIR/db.sqlite3"
    PY_BIN="$SCRIPT_DIR/venv/bin/python3"
    [ ! -f "$PY_BIN" ] && PY_BIN=$(which python3)

    read -p "$(echo -e "${YELLOW}Enter ${GREEN}Username${YELLOW} to edit/create [default: Pars]: ${NC}")" NEW_USERNAME
    NEW_USERNAME=${NEW_USERNAME:-Pars}
    read -s -p "$(echo -e "${YELLOW}Enter ${GREEN}new password${YELLOW}: ${NC}")" NEW_PASSWORD
    echo ""
    read -s -p "$(echo -e "${YELLOW}Confirm ${GREEN}new password${YELLOW}: ${NC}")" CONFIRM_PASSWORD
    echo ""
    if [ -z "$NEW_PASSWORD" ] || [ "$NEW_PASSWORD" != "$CONFIRM_PASSWORD" ]; then
        echo -e "${RED}✘ Passwords do not match or empty.${NC}"
        return 1
    fi
    "$PY_BIN" -c "
import sqlite3
from werkzeug.security import generate_password_hash
db_p = '$DB_FILE'
hashed = generate_password_hash('$NEW_PASSWORD')
conn = sqlite3.connect(db_p, timeout=10.0)
cur = conn.cursor()
cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, password_plain TEXT)')
cur.execute('INSERT OR REPLACE INTO users (id, username, password_hash, password_plain) VALUES (1, \'$NEW_USERNAME\', ?, \'$NEW_PASSWORD\')', (hashed,))
conn.commit()
conn.close()
print('✔ Password updated successfully.')
"
    sync_persistent_config
    systemctl restart wireguard-panel.service 2>/dev/null || true
    echo -e "${SUCCESS}✔ User credentials updated.${NC}"
    echo -e "${CYAN}Press Enter to return to main menu...${NC}" && read
}

update_panel_safe() {
    echo -e "${INFO}[INFO] Updating Wireguard Panel and Hub files (Zero Data Loss Mode)...${NC}"
    BK_TMP="/tmp/wg_panel_update_safe_$(date +%s)"
    mkdir -p "$BK_TMP"
    cp -f "$SCRIPT_DIR/db.sqlite3"* "$BK_TMP/" 2>/dev/null || true
    cp -f "$SCRIPT_DIR/config.yaml" "$BK_TMP/" 2>/dev/null || true
    cp -f "$SCRIPT_DIR/secret.key" "$BK_TMP/" 2>/dev/null || true
    cp -f "$SCRIPT_DIR/short_links.json" "$BK_TMP/" 2>/dev/null || true
    cp -f "$SCRIPT_DIR/short_links_decrypted.json" "$BK_TMP/" 2>/dev/null || true
    cp -f "$SCRIPT_DIR/endip.json" "$BK_TMP/" 2>/dev/null || true
    cp -f /etc/wireguard/db_backup.sqlite3 "$BK_TMP/" 2>/dev/null || true
    
    if [ -d "$PANEL_DIR/.git" ]; then
        git -C "$PANEL_DIR" fetch --all >/dev/null 2>&1
        git -C "$PANEL_DIR" reset --hard origin/main >/dev/null 2>&1
    fi
    
    [ -f "$BK_TMP/db.sqlite3" ] && cp -f "$BK_TMP/db.sqlite3"* "$SCRIPT_DIR/"
    [ -f "$BK_TMP/config.yaml" ] && cp -f "$BK_TMP/config.yaml" "$SCRIPT_DIR/"
    [ -f "$BK_TMP/secret.key" ] && cp -f "$BK_TMP/secret.key" "$SCRIPT_DIR/"
    [ -f "$BK_TMP/short_links.json" ] && cp -f "$BK_TMP/short_links.json" "$SCRIPT_DIR/"
    [ -f "$BK_TMP/short_links_decrypted.json" ] && cp -f "$BK_TMP/short_links_decrypted.json" "$SCRIPT_DIR/"
    [ -f "$BK_TMP/endip.json" ] && cp -f "$BK_TMP/endip.json" "$SCRIPT_DIR/"
    [ -f "$BK_TMP/db_backup.sqlite3" ] && cp -f "$BK_TMP/db_backup.sqlite3" /etc/wireguard/db_backup.sqlite3 2>/dev/null || true
    rm -rf "$BK_TMP"
    
    deploy_php_control_hub
    systemctl restart wireguard-panel.service 2>/dev/null || true
    echo -e "${SUCCESS}[SUCCESS] Panel updated successfully with 100% data preservation!${NC}"
    echo -e "${CYAN}Press Enter to continue...${NC}" && read
}

uninstall_panel_clean() {
    echo -e "\033[1;31m[WARNING] Uninstalling Wireguard Panel and purging all zombie data...\033[0m"
    systemctl stop wireguard-panel.service wireguard-php-hub.service 2>/dev/null || true
    systemctl disable wireguard-panel.service wireguard-php-hub.service 2>/dev/null || true
    rm -f /etc/systemd/system/wireguard-panel.service /etc/systemd/system/wireguard-php-hub.service 2>/dev/null || true
    systemctl daemon-reload 2>/dev/null || true

    rm -f /etc/wireguard/db_backup.sqlite3 /etc/wireguard/db.sqlite3
    rm -f "$SCRIPT_DIR/db.sqlite3"* "$SCRIPT_DIR/short_links.json" "$SCRIPT_DIR/endip.json" "$HUB_CREDENTIALS"

    for conf_file in /etc/wireguard/*.conf; do
        if [ -f "$conf_file" ]; then
            python3 -c "
import sys
try:
    with open('$conf_file', 'r') as f: txt = f.read()
    iface_part = txt.split('[Peer]')[0].strip() + '\n'
    with open('$conf_file', 'w') as f: f.write(iface_part)
except Exception: pass
"
        fi
    done
    echo -e "\033[1;32m[SUCCESS] Wireguard Panel uninstalled and all ghost peer records cleanly removed.\033[0m"
}

uninstall_mnu() {
    echo -e "${WARNING}[WARNING]: This will completely delete the Wireguard panel, all configs, and databases.${NC}"
    echo -ne "${CYAN}Do you want to continue? ${GREEN}[yes]${NC}/${RED}[no]${NC}: "
    read -r CONFIRM
    if [[ "$CONFIRM" != "yes" && "$CONFIRM" != "y" ]]; then
        echo -e "${CYAN}Uninstallation aborted.${NC}"
        return
    fi
    uninstall_panel_clean
    rm -rf "$PANEL_DIR" /etc/wireguard "$HUB_CREDENTIALS" 2>/dev/null || true
    echo -e "${SUCCESS}Complete Uninstallation Successful!${NC}"
    exit 0
}

select_stuff() {
    case $1 in
        0) wireguard_detailed_stats ;;
        s|S) show_logs ;;
        1) create_config ;;
        2) wireguardconf ;;
        3) setup_permissions ;;
        4) wireguard_panel ;;
        5) uninstall_mnu ;;
        6) reset_credentials ;;
        7) update_panel_safe ;;
        q|Q) echo -e "${GREEN}Exiting...${NC}" && exit 0 ;;
        *) echo -e "${RED}Wrong choice. Please choose a valid option.${NC}" ;;
    esac
}

ensure_zip_tools
restore_persistent_config

# مرحله آماده‌سازی و راه‌اندازی اولیه
if ! is_panel_installed; then
    display_logo
    echo -e "${INFO}[INFO] Initializing fresh installation...${NC}"
    install_requirements
    setup_virtualenv
    ensure_pars_admin_exists
fi

sync_persistent_config
install_panel_url_tool 2>/dev/null || true

while true; do
    display_menu
    echo -ne "${NC}Choose an option [0-7]: ${NC}"
    read -r USER_CHOICE
    select_stuff "$USER_CHOICE"
done