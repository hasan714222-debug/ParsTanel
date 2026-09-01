<?php
/* ========================================================================= */
/* نام فایل: api_bot.php                                                     */
/* نقش: وب‌سرویس RESTful و Backend جامع مدیریت پنل، ربات، نمایندگان و کلاینت‌ها */
/* ========================================================================= */

ob_start();
header('Content-Type: application/json; charset=utf-8');

// 🛡️ مدیریت خطاهای مرگبار و خروجی ساختاریافته JSON
register_shutdown_function(function() {
    $e = error_get_last();
    if ($e !== NULL && in_array($e['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR])) {
        if (ob_get_length()) ob_clean();
        echo json_encode([
            'status'  => 'error',
            'success' => false,
            'ok'      => false,
            'message' => 'Fatal Error: ' . $e['message'],
            'file'    => basename($e['file']),
            'line'    => $e['line']
        ], JSON_UNESCAPED_UNICODE);
    }
});

// 🔒 کلید احراز هویت امنیتی
$API_KEY = "@Hasan89732900"; 

$raw_input = file_get_contents('php://input');
$input = @json_decode($raw_input, true) ?: $_POST;

if (!is_array($input) || !isset($input['api_key']) || !hash_equals($API_KEY, (string)$input['api_key'])) {
    http_response_code(401);
    die(json_encode([
        'status'  => 'error', 
        'success' => false,
        'ok'      => false,
        'message' => 'Unauthenticated: Invalid or Missing API Key.'
    ], JSON_UNESCAPED_UNICODE));
}

$action             = $input['action'] ?? '';
$saved_masters_file = __DIR__ . '/.saved_masters.php';
$registry_file      = __DIR__ . '/local_servers_registry.json';
$p_dir              = '/usr/local/bin/Wireguard-panel/src';
$py_bin             = $p_dir . '/venv/bin/python3';
if (!file_exists($py_bin)) { $py_bin = 'python3'; }

// -------------------------------------------------------------
// 📂 توابع پایگاه داده محلی (Local Registry) با قفل عدم کاهش ترافیک
// -------------------------------------------------------------
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

function register_local_interface($host, $iface, $details, $force_limit = false) {
    $reg = get_local_registry();
    if (!isset($reg[$host])) {
        $reg[$host] = ['host' => $host, 'interfaces' => []];
    }
    if (!isset($reg[$host]['interfaces'])) {
        $reg[$host]['interfaces'] = [];
    }
    
    $existing = $reg[$host]['interfaces'][$iface] ?? [];
    
    // ۱. سوپاپ عدم کاهش اشتباه ترافیک مصرفی (مگر در حالت صفر کردن ترافیک)
    $existing_used = floatval($existing['used_gb'] ?? 0.0);
    $incoming_used = isset($details['used_gb']) ? floatval($details['used_gb']) : 0.0;
    
    if (isset($details['reset_used']) && $details['reset_used'] === true) {
        $details['used_gb'] = 0.0;
    } else {
        $details['used_gb'] = max($existing_used, $incoming_used);
    }

    // ۲. مدیریت سقف حجم تخصیص‌یافته (Data Limit GB) با قابلیت پذیرش کسر حجم
    $existing_limit = floatval($existing['data_limit_gb'] ?? 0.0);
    $incoming_limit = isset($details['data_limit_gb']) ? floatval($details['data_limit_gb']) : 0.0;

    if ($force_limit) {
        // در صورت اجبار (کسر حجم، شارژ یا تغییر مستقیم)، مقدار ورودی مستقیماً اعمال می‌شود
        $details['data_limit_gb'] = max(0.0, $incoming_limit);
    } else {
        if ($incoming_limit <= 0 && $existing_limit > 0) {
            $details['data_limit_gb'] = $existing_limit;
        } elseif ($incoming_limit > 0) {
            $details['data_limit_gb'] = $incoming_limit;
        } else {
            $details['data_limit_gb'] = $existing_limit > 0 ? $existing_limit : 100.0;
        }
    }

    // ۳. محاسبه دقیق و خودکار حجم باقی‌مانده (Remaining GB)
    if ($iface === 'wg0' || $details['data_limit_gb'] <= 0) {
        $details['rem_gb'] = 0.0;
    } else {
        $details['rem_gb'] = round(max(0.0, $details['data_limit_gb'] - $details['used_gb']), 2);
    }

    // ۴. قفل امنیتی نام کاربری (جلوگیری از خالی شدن یا درج مقادیر نامعتبر)
    $invalid_usernames = ['بدون نماینده (پیش‌فرض)', 'N/A', '', null];
    $incoming_user = trim($details['username'] ?? '');
    if (in_array($incoming_user, $invalid_usernames, true)) {
        if (!empty($existing['username']) && !in_array($existing['username'], $invalid_usernames, true)) {
            $details['username'] = $existing['username'];
        } else {
            $details['username'] = $iface === 'wg0' ? 'Pars (مدیر کل)' : "Reseller_{$iface}";
        }
    }

    // ۵. قفل امنیتی کلمه عبور و هش
    if (empty($details['password_plain']) || $details['password_plain'] === 'N/A') {
        if (!empty($existing['password_plain']) && $existing['password_plain'] !== 'N/A') {
            $details['password_plain'] = $existing['password_plain'];
        }
    }
    if (empty($details['password_hash']) && !empty($existing['password_hash'])) {
        $details['password_hash'] = $existing['password_hash'];
    }

    // ۶. پورت و ساب‌نت استاندارد 10.N.0.1/16
    preg_match('/\d+/', $iface, $m);
    $iface_num = isset($m[0]) ? intval($m[0]) : 0;
    $default_subnet = "10.{$iface_num}.0.1/16";
    $default_port = 51820 + $iface_num;

    $details['port'] = (!empty($details['port']) && intval($details['port']) > 0) ? intval($details['port']) : ($existing['port'] ?? $default_port);
    $details['subnet_ip'] = (!empty($details['subnet_ip']) && $details['subnet_ip'] !== 'N/A') ? $details['subnet_ip'] : ($existing['subnet_ip'] ?? $default_subnet);

    // ۷. وضعیت فعال/تعلیق
    if (empty($details['status'])) {
        $details['status'] = $existing['status'] ?? 'active';
    }
    if (isset($existing['disabled_at']) && !isset($details['disabled_at'])) {
        $details['disabled_at'] = $existing['disabled_at'];
    }

    // ۸. ادغام امن و ذخیره در فایل JSON لوکال
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
    if (!$ssh) {
        return "ERROR_NO_SSH_CONNECTION";
    }
    $cmd_file = "/tmp/api_cmd_" . time() . "_" . rand(1000, 9999) . ".py";
    $sftp = @ssh2_sftp($ssh);
    $written = false;
    
    if ($sftp) {
        $sftp_path = "ssh2.sftp://" . intval($sftp) . $cmd_file;
        $fh = @fopen($sftp_path, 'w');
        if ($fh) {
            @fwrite($fh, $script_code);
            @fclose($fh);
            $written = true;
        }
    }
    if (!$written) {
        $b64_code = base64_encode($script_code);
        $exec_cmd = "echo '{$b64_code}' | base64 -d > {$cmd_file} && {$py_bin} {$cmd_file} {$args} 2>&1; rm -f {$cmd_file}";
        $st = @ssh2_exec($ssh, $exec_cmd);
    } else {
        $st = @ssh2_exec($ssh, "{$py_bin} {$cmd_file} {$args} 2>&1; rm -f {$cmd_file}");
    }
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

// -------------------------------------------------------------
// 🌐 دریافت لیست سرورها
// -------------------------------------------------------------
if ($action === 'get_servers') {
    $servers = get_saved_masters();
    $list = [];
    foreach ($servers as $ip => $data) {
        $list[] = [
            'ip'   => $ip, 
            'port' => $data['p'], 
            'user' => $data['u']
        ];
    }
    echo json_encode(['status' => 'success', 'success' => true, 'ok' => true, 'data' => $list], JSON_UNESCAPED_UNICODE);
    exit;
}

$target_ip = trim($input['server_ip'] ?? '');
if (empty($target_ip)) {
    die(json_encode(['status' => 'error', 'success' => false, 'ok' => false, 'message' => 'server_ip is required.'], JSON_UNESCAPED_UNICODE));
}

$ssh = connect_to_server($target_ip);
if (!$ssh) {
    die(json_encode([
        'status'  => 'error', 
        'success' => false,
        'ok'      => false,
        'message' => "Cannot connect to server {$target_ip} via SSH. Check credentials or firewall."
    ], JSON_UNESCAPED_UNICODE));
}

// -------------------------------------------------------------
// 🩺 بررسی سلامت، انطباق ساب‌نت و ترمیم کلاستر
// -------------------------------------------------------------
if ($action === 'audit_cluster_full') {
    $py_health_check = <<<'PYTHON'
import sqlite3, subprocess, os, re, json

db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
conn = sqlite3.connect(db_path, timeout=10.0)
cur = conn.cursor()

logs = []

needed_tools = ['wg', 'wg-quick', 'iptables', 'sshpass']
for tool in needed_tools:
    if subprocess.getoutput(f"which {tool}").strip() == "":
        os.system(f"apt-get update -qq && apt-get install -y -qq {tool}")
        logs.append(f"پکیج مفقود {tool} روی مستر نصب گردید.")

cur.execute("SELECT server_ip, ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
edges = cur.fetchall()

cur.execute("SELECT interface_name, port, data_limit_gb, username, password_hash, password_plain, status, deleted_traffic FROM sub_panels")
sub_panels = cur.fetchall()

for iface_row in sub_panels:
    iface = iface_row[0]
    m_num = re.search(r'\d+', iface)
    num = int(m_num.group(0)) if m_num else 1
    expected_subnet = f"10.{num}.0.1/16"
    expected_port = 51820 + num

    conf_p = f"/etc/wireguard/{iface}.conf"
    if os.path.exists(conf_p):
        txt = open(conf_p, 'r', encoding='utf-8', errors='ignore').read()
        m_addr = re.search(r'(?i)Address\s*=\s*([^\n]+)', txt)
        m_port = re.search(r'(?i)ListenPort\s*=\s*(\d+)', txt)
        
        cur_addr = m_addr.group(1).strip() if m_addr else ""
        cur_port = int(m_port.group(1).strip()) if m_port else 0
        
        if cur_addr != expected_subnet or cur_port != expected_port:
            txt = re.sub(r'(?i)Address\s*=\s*[^\n]+', f'Address = {expected_subnet}', txt)
            txt = re.sub(r'(?i)ListenPort\s*=\s*\d+', f'ListenPort = {expected_port}', txt)
            with open(conf_p, 'w', encoding='utf-8') as f:
                f.write(txt)
            subprocess.run(f"wg-quick down {iface} 2>/dev/null; wg-quick up {iface} 2>/dev/null", shell=True)
            logs.append(f"ساب‌نت اینترفیس {iface} روی مستر به {expected_subnet} و پورت به {expected_port} تصحیح شد.")

    for srv_ip, s_ip, s_port, s_user, s_pass in edges:
        cmd_node = f"""
which wg-quick >/dev/null || apt-get install -y wireguard wireguard-tools
if [ ! -f /etc/wireguard/{iface}.conf ]; then
    priv=$(wg genkey)
    nic=$(ip route | grep default | awk '{{print $5}}' | head -n1)
    [ -z "$nic" ] && nic="eth0"
    echo -e "[Interface]\\nPrivateKey = $priv\\nListenPort = {expected_port}\\nAddress = {expected_subnet}\\nSaveConfig = false\\nPostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -t nat -A POSTROUTING -o $nic -j MASQUERADE\\nPostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -t nat -D POSTROUTING -o $nic -j MASQUERADE" > /etc/wireguard/{iface}.conf
    systemctl enable wg-quick@{iface} && systemctl start wg-quick@{iface}
else
    sed -i -E 's/(Address\s*=\s*).*/\\1{expected_subnet}/gI' /etc/wireguard/{iface}.conf
    sed -i -E 's/(ListenPort\s*=\s*).*/\\1{expected_port}/gI' /etc/wireguard/{iface}.conf
    systemctl restart wg-quick@{iface}
fi
sqlite3 /usr/local/bin/Wireguard-panel/src/db.sqlite3 "CREATE TABLE IF NOT EXISTS sub_panels (id INTEGER PRIMARY KEY AUTOINCREMENT, interface_name TEXT UNIQUE, username TEXT UNIQUE, password_hash TEXT, data_limit_gb REAL, port INTEGER, created_at TEXT, status TEXT, disabled_at TEXT, password_plain TEXT, deleted_traffic INTEGER DEFAULT 0);"
sqlite3 /usr/local/bin/Wireguard-panel/src/db.sqlite3 "INSERT OR REPLACE INTO sub_panels (interface_name, username, password_hash, data_limit_gb, port, status, password_plain, deleted_traffic) VALUES ('{iface}', '{iface_row[3]}', '{iface_row[4]}', {iface_row[2]}, {expected_port}, '{iface_row[6]}', '{iface_row[5]}', {iface_row[7] or 0});"
"""
        subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port or 22} -o StrictHostKeyChecking=no {s_user}@{s_ip} '{cmd_node}'", shell=True, stderr=subprocess.DEVNULL)

conn.close()
print(json.dumps({"status": "success", "logs": logs}))
PYTHON;

    $out = exec_py($ssh, $py_bin, $py_health_check);
    echo json_encode(['status' => 'success', 'data' => json_decode($out, true)], JSON_UNESCAPED_UNICODE);
    exit;
}

// -------------------------------------------------------------
// 👥 دریافت لیست نمایندگان و پایش ترافیک
// -------------------------------------------------------------
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
        for iv_name, iv_bytes in cur.fetchall():
            universal_vault[iv_name] = iv_bytes or 0
    except: pass

    cur.execute("PRAGMA table_info(sub_panels)")
    cols = [c[1] for c in cur.fetchall()]
    bot_token_col = "telegram_bot_token" if "telegram_bot_token" in cols else "''"
    chat_id_col = "telegram_chat_id" if "telegram_chat_id" in cols else "''"
    bot_status_col = "telegram_bot_status" if "telegram_bot_status" in cols else "'off'"
    bot_url_col = "bot_base_url" if "bot_base_url" in cols else "''"

    cur.execute(f"SELECT id, interface_name, username, password_plain, data_limit_gb, port, status, deleted_traffic, {bot_token_col}, {chat_id_col}, {bot_status_col}, {bot_url_col} FROM sub_panels")
    for r in cur.fetchall():
        r_id, iface, user, pw, limit, port, status, del_traf, b_tok, c_id, b_stat, b_url = r
        del_traf = del_traf or 0

        cur.execute("SELECT SUM(used) FROM peers WHERE config=? OR config=?", (f"{iface}.conf", iface))
        live_used = cur.fetchone()[0] or 0

        vault_t = universal_vault.get(iface, 0)
        vault_traffic = max(del_traf, vault_t)
        total_bytes = live_used + vault_traffic

        used_gb = round(total_bytes / 1073741824.0, 2)
        limit_val = float(limit) if limit else 100.0
        rem_gb = round(max(0.0, limit_val - used_gb), 2)

        m_num = re.search(r'\d+', iface)
        num = int(m_num.group(0)) if m_num else 0
        subnet = f"10.{num}.0.1/16"

        conf_path = f"/etc/wireguard/{iface}.conf"
        if os.path.exists(conf_path):
            try:
                txt = open(conf_path, 'r', encoding='utf-8').read()
                m = re.search(r'Address\s*=\s*([^\s]+)', txt, re.IGNORECASE)
                if m: subnet = m.group(1).strip()
            except: pass

        resellers.append({
            "id": r_id, "interface": iface, "username": user, "password": pw,
            "limit_gb": limit_val, "used_gb": used_gb, "rem_gb": rem_gb,
            "status": status, "port": port, "subnet": subnet,
            "bot_token": b_tok, "chat_id": c_id, "bot_status": b_stat, "bot_url": b_url
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
    
    echo json_encode(['status' => 'success', 'success' => true, 'ok' => true, 'data' => $decoded], JSON_UNESCAPED_UNICODE);
    exit;
}

// -------------------------------------------------------------
// 📊 دریافت وضعیت منابع سرور (Metrics)
// -------------------------------------------------------------
if ($action === 'get_metrics') {
    $py_metrics = <<<'PYTHON'
import os, sys, subprocess, json, time, sqlite3

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
    dt = st.f_blocks * st.f_frsize
    df = st.f_bfree * st.f_frsize
    du = dt - df
    disk_data = {'total': fmt(dt), 'used': fmt(du), 'percent': round((du / dt) * 100, 1)}
except: pass

total_global_bytes = 0
try:
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=5.0)
    cur = conn.cursor()
    cur.execute("SELECT SUM(used) FROM peers")
    live = cur.fetchone()[0] or 0
    cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1")
    del_g = cur.fetchone()
    del_total = del_g[0] if del_g else 0
    
    vault_all = 0
    cur.execute("SELECT SUM(vault_bytes) FROM interface_vault")
    row_v = cur.fetchone()
    if row_v and row_v[0]: vault_all = row_v[0]

    total_global_bytes = live + max(del_total, vault_all)
    conn.close()
except: pass

print(json.dumps({
    'cpu_percent': cpu,
    'ram': ram_data,
    'disk': disk_data,
    'total_traffic_all_time': fmt(total_global_bytes)
}))
PYTHON;
    $out = exec_py($ssh, $py_bin, $py_metrics);
    echo json_encode(['status' => 'success', 'success' => true, 'ok' => true, 'data' => json_decode($out, true)], JSON_UNESCAPED_UNICODE);
    exit;
}

// -------------------------------------------------------------
// 👥 دریافت لیست کلاینت‌های متصل به یک اینترفیس
// -------------------------------------------------------------
if ($action === 'get_peers') {
    $iface = trim($input['interface'] ?? 'wg0');
    $py_peers = <<<PYTHON
import sqlite3, json
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
cfg_name = "{$iface}.conf" if not "{$iface}".endswith('.conf') else "{$iface}"
iface_raw = cfg_name.replace('.conf', '')
peers = []
try:
    conn = sqlite3.connect(db_path, timeout=10.0)
    cur = conn.cursor()
    cur.execute("SELECT peer_name, peer_ip, public_key, [limit], used, remaining_time, monitor_blocked, expiry_blocked, token, config FROM peers WHERE config=? OR config=?", (cfg_name, iface_raw))
    for r in cur.fetchall():
        peers.append({
            "peer_name": r[0], "peer_ip": r[1], "public_key": r[2],
            "limit": r[3], "used_bytes": r[4], "remaining_time_minutes": r[5],
            "is_blocked": bool(r[6] or r[7]), "token": r[8], "config": r[9]
        })
    conn.close()
    print(json.dumps(peers))
except Exception as e:
    print(json.dumps({"error": str(e)}))
PYTHON;
    $out = exec_py($ssh, $py_bin, $py_peers);
    echo json_encode(['status' => 'success', 'success' => true, 'ok' => true, 'data' => json_decode($out, true)], JSON_UNESCAPED_UNICODE);
    exit;
}

// -------------------------------------------------------------
// 👤 مدیریت و عملیات کلاینت‌ها (Client Peer Actions)
// -------------------------------------------------------------
if ($action === 'peer_action') {
    $task      = trim($input['task'] ?? '');
    $peer_name = trim($input['peer_name'] ?? '');
    $iface     = trim($input['interface'] ?? 'wg0');
    $cfg_name  = !str_ends_with($iface, '.conf') ? "{$iface}.conf" : $iface;
    $iface_raw = str_replace('.conf', '', $cfg_name);

    if (empty($task)) {
        die(json_encode(['status' => 'error', 'success' => false, 'ok' => false, 'message' => 'task is required.'], JSON_UNESCAPED_UNICODE));
    }

    $py_peer_cmd = "";

   if ($task === 'create') {
        $peer_name  = trim($input['peer_name'] ?? '');
        $limit_str  = trim($input['limit'] ?? '50GiB');
        $days       = intval($input['days'] ?? 30);
        $first_u    = !empty($input['first_usage']) ? 1 : 0;

        if (empty($peer_name)) {
            die(json_encode(['status' => 'error', 'success' => false, 'ok' => false, 'message' => 'peer_name is required.'], JSON_UNESCAPED_UNICODE));
        }

        $py_peer_cmd = <<<PYTHON
import os, sys, sqlite3, subprocess, re, json, secrets, time
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
cfg_name = "{$cfg_name}"
iface = "{$iface_raw}"
peer_name = "{$peer_name}"
raw_limit = "{$limit_str}"
days = {$days}
first_u = {$first_u}

# تبدیل هوشمند حجم
def parse_smart_limit(val):
    s = str(val).strip().replace('/', '.')
    m = re.match(r"^([0-9\.]+)\s*(T|TB|TIB|G|GB|GIB|M|MB|MIB|K|KB|KIB|B)?$", s, re.I)
    if m:
        num = float(m.group(1))
        unit = (m.group(2) or "GiB").upper()
    else:
        num = 50.0
        unit = "GIB"
    if "M" in unit:
        return f"{int(num)}MiB", int(num * 1048576)
    elif "T" in unit:
        return f"{int(num)}TB", int(num * (1024**4))
    else:
        # گیگابایت (اعشاری یا صحیح)
        return f"{num:g}GiB", int(num * 1073741824)

# تاریخ جلالی
def to_jalali_ts(ts):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 335]
    t = time.gmtime(int(ts) + 12600)
    gy, gm, gd = t.tm_year, t.tm_mon, t.tm_mday
    jy = 0 if gy <= 1600 else 979
    gy -= 621 if gy <= 1600 else 1600
    gy2 = gy + 1 if gm > 2 else gy
    days_cnt = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days_cnt // 12053); days_cnt %= 12053
    jy += 4 * (days_cnt // 1461); days_cnt %= 1461
    jy += (days_cnt - 1) // 365
    if days_cnt > 365: days_cnt = (days_cnt - 1) % 365
    jm = 1 + (days_cnt // 31) if days_cnt < 186 else 7 + ((days_cnt - 186) // 30)
    jd = 1 + (days_cnt % 31 if days_cnt < 186 else (days_cnt - 186) % 30)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {t.tm_hour:02d}:{t.tm_min:02d}"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("SELECT id FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, cfg_name, iface))
    if cur.fetchone():
        print("ERROR_DUPLICATE_PEER")
        sys.exit(0)

    m_num = re.search(r'\d+', iface)
    num = int(m_num.group(0)) if m_num else 0
    base_prefix = f"10.{num}"

    cur.execute("SELECT peer_ip FROM peers WHERE config=? OR config=?", (cfg_name, iface))
    used_ips = set(r[0] for r in cur.fetchall() if r[0])
    
    free_ip = None
    free_oct3 = 0
    free_oct4 = 2
    for oct3 in range(0, 255):
        for oct4 in range(2, 255):
            cand = f"{base_prefix}.{oct3}.{oct4}"
            if cand not in used_ips and cand != f"{base_prefix}.0.1":
                free_ip = cand
                free_oct3 = oct3
                free_oct4 = oct4
                break
        if free_ip: break
    if not free_ip: free_ip = f"{base_prefix}.0.2"

    limit_str, limit_bytes = parse_smart_limit(raw_limit)
    priv_k = subprocess.getoutput("wg genkey").strip()
    pub_k = subprocess.getoutput(f"echo '{priv_k}' | wg pubkey").strip()
    token = secrets.token_urlsafe(16)
    rem_minutes = days * 1440
    exp_json = json.dumps({"months": 0, "days": days, "hours": 0, "minutes": 0})
    now_ts = int(time.time())
    jalali_created = to_jalali_ts(now_ts)

    cur.execute("""
        INSERT INTO peers (
            peer_name, peer_ip, public_key, [limit], used, remaining, remaining_time, config, 
            expiry_time_json, first_usage, expiry_blocked, monitor_blocked, private_key, 
            dns, mtu, persistent_keepalive, allowed_ips, token, initial_duration, created_at, 
            created_at_gregorian, created_at_jalali
        ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, 0, 0, ?, '1.1.1.1', 1420, 25, '0.0.0.0/0, ::/0', ?, ?, ?, datetime('now'), ?)
    """, (peer_name, free_ip, pub_k, limit_str, limit_bytes, rem_minutes, cfg_name, exp_json, first_u, priv_k, token, rem_minutes, now_ts, jalali_created))

    cur.execute("CREATE TABLE IF NOT EXISTS short_links (short_id TEXT PRIMARY KEY, long_link TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token, f"/peer-details?peer_name={peer_name}&config_file={cfg_name}&token={token}"))
    cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token[:8], f"/peer-details?peer_name={peer_name}&config_file={cfg_name}&token={token}"))
    
    # اضافه کردن کاربر به اینترفیس‌های پیشرفته (در صورت وجود)
    try:
        cur.execute("SELECT interface_name FROM advanced_services WHERE status=1")
        adv_rows = cur.fetchall()
        for adv_r in adv_rows:
            adv_if = adv_r[0]
            m_a = re.search(r'\d+', adv_if)
            num_a = int(m_a.group(0)) if m_a else 10
            adv_peer_ip = f"10.{num_a}.{free_oct3}.{free_oct4}"
            subprocess.run(f"wg set {adv_if} peer {pub_k} allowed-ips {adv_peer_ip}/32", shell=True, stderr=subprocess.DEVNULL)
            subprocess.run(f"wg-quick save {adv_if}", shell=True, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    conn.commit()
    conn.close()

    # فعال‌سازی روی اینترفیس محلی اصلی
    subprocess.run(f"wg set {iface} peer {pub_k} allowed-ips {free_ip}/32", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"wg-quick save {iface}", shell=True, stderr=subprocess.DEVNULL)

    # همگام‌سازی با نودهای کلاستر
    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_action_to_edges("create", peer_name, cfg_name, {
            "first_usage": (first_u == 1),
            "private_key": priv_k,
            "public_key": pub_k,
            "limit": limit_str,
            "remaining_time": rem_minutes
        })
    except Exception: pass

    print(f"SUCCESS_CREATED|{token}|{free_ip}|{pub_k}")
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

    elseif ($task === 'edit') {
        $limit_str = trim($input['limit'] ?? '');
        $days      = intval($input['days'] ?? 0);
        $py_peer_cmd = <<<PYTHON
import sqlite3, json
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
cfg_name = "{$cfg_name}"
iface = "{$iface_raw}"
peer_name = "{$peer_name}"
limit_str = "{$limit_str}"
days = {$days}

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    extra_data = {}
    if limit_str:
        cur.execute("UPDATE peers SET [limit]=?, monitor_blocked=0 WHERE peer_name=? AND (config=? OR config=?)", (limit_str, peer_name, cfg_name, iface))
        extra_data["limit"] = limit_str
    if days > 0:
        rem_min = days * 1440
        exp_json = json.dumps({"months": 0, "days": days, "hours": 0, "minutes": 0})
        cur.execute("UPDATE peers SET remaining_time=?, expiry_time_json=?, expiry_blocked=0 WHERE peer_name=? AND (config=? OR config=?)", (rem_min, exp_json, peer_name, cfg_name, iface))
        extra_data["remaining_time"] = rem_min
    conn.commit()
    conn.close()

    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_action_to_edges("edit", peer_name, cfg_name, extra_data)
    except Exception: pass

    print("SUCCESS")
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

    elseif ($task === 'toggle') {
        $py_peer_cmd = <<<PYTHON
import sqlite3, subprocess
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
cfg_name = "{$cfg_name}"
iface = "{$iface_raw}"
peer_name = "{$peer_name}"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("SELECT monitor_blocked, expiry_blocked, peer_ip, public_key, config FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, cfg_name, iface))
    row = cur.fetchone()
    if row:
        m_blk, e_blk, pip, pub, cfg_target = row
        real_iface = cfg_target.replace('.conf', '') if cfg_target else iface
        is_blk = bool(m_blk or e_blk)
        new_blk = 0 if is_blk else 1
        cur.execute("UPDATE peers SET monitor_blocked=?, expiry_blocked=? WHERE peer_name=? AND (config=? OR config=?)", (new_blk, new_blk, peer_name, cfg_name, iface))
        conn.commit()
        if new_blk == 1:
            if pip: subprocess.run(f"ip route add blackhole {pip}", shell=True, stderr=subprocess.DEVNULL)
            if pub: subprocess.run(f"wg set {real_iface} peer {pub} remove", shell=True, stderr=subprocess.DEVNULL)
        else:
            if pip: subprocess.run(f"ip route del blackhole {pip}", shell=True, stderr=subprocess.DEVNULL)
            if pub and pip: subprocess.run(f"wg set {real_iface} peer {pub} allowed-ips {pip}/32", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run(f"wg-quick save {real_iface}", shell=True, stderr=subprocess.DEVNULL)

        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_action_to_edges("toggle", peer_name, cfg_name, {"blocked": bool(new_blk)})
        except Exception: pass

        print("SUCCESS")
    else:
        print("ERROR_PEER_NOT_FOUND")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

    elseif ($task === 'reset_traffic') {
        $py_peer_cmd = <<<PYTHON
import sqlite3
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
cfg_name = "{$cfg_name}"
iface = "{$iface_raw}"
peer_name = "{$peer_name}"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("SELECT used, config, initial_duration, public_key, peer_ip FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, cfg_name, iface))
    row = cur.fetchone()
    if row:
        used_b = int(row[0] or 0)
        target_cfg = row[1] if row[1] else cfg_name
        real_iface = target_cfg.replace('.conf', '')
        init_d = int(row[2] or 43200)
        if init_d <= 0: init_d = 43200
        pub = row[3]
        pip = row[4]
        
        if used_b > 0:
            import sqlite_backend
            sqlite_backend.record_deleted_traffic_atomic(real_iface, used_b)
        
        cur.execute("UPDATE peers SET used=0, local_used=0, last_received_bytes=0, last_sent_bytes=0, remaining_time=?, expiry_blocked=0, monitor_blocked=0 WHERE peer_name=? AND (config=? OR config=?)", (init_d, peer_name, cfg_name, iface))
        cur.execute("UPDATE peer_synced_edges SET node_used=0, last_bytes=0 WHERE peer_name=? AND config=?", (peer_name, target_cfg))
        conn.commit()

        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_action_to_edges("reset", peer_name, target_cfg)
        except Exception: pass

    print("SUCCESS")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

    elseif ($task === 'delete') {
        $py_peer_cmd = <<<PYTHON
import sqlite3, subprocess, os
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
cfg_name = "{$cfg_name}"
iface = "{$iface_raw}"
peer_name = "{$peer_name}"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("SELECT public_key, peer_ip, config, used FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, cfg_name, iface))
    row = cur.fetchone()
    if row:
        pub = row[0]
        pip = row[1]
        target_cfg = row[2] if row[2] else cfg_name
        real_iface = target_cfg.replace('.conf', '')
        used_b = int(row[3] or 0)

        # ۱. واریز ترافیک مصرفی کاربر به صندوق دائمی سرور
        if used_b > 0:
            import sqlite_backend
            sqlite_backend.record_deleted_traffic_atomic(real_iface, used_b)

        # ۲. حذف کلاینت از کرنل وایرگارد و حذف روت بلک‌هول
        if pub:
            subprocess.run(f"wg set {real_iface} peer {pub} remove", shell=True, stderr=subprocess.DEVNULL)
        if pip:
            subprocess.run(f"ip route del blackhole {pip}/32 2>/dev/null", shell=True)

        # ۳. حذف رکوردهای کلاینت از دیتابیس
        cur.execute("DELETE FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, cfg_name, iface))
        cur.execute("DELETE FROM services WHERE email=?", (peer_name,))
        cur.execute("DELETE FROM short_links WHERE long_link LIKE ?", (f"%{peer_name}%",))
        cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=?", (peer_name,))
        conn.commit()

        # ۴. همگام‌سازی حذف با نودهای کلاستر و ذخیره فایل کانفیگ
        subprocess.run(f"wg-quick save {real_iface}", shell=True, stderr=subprocess.DEVNULL)
        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_action_to_edges("delete", peer_name, target_cfg)
        except Exception: pass

    print("SUCCESS")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }
    if (!empty($py_peer_cmd)) {
        $res = exec_py($ssh, $py_bin, $py_peer_cmd);
        $is_success = (strpos($res, 'SUCCESS') !== false);
        echo json_encode([
            'status'          => $is_success ? 'success' : 'error',
            'success'         => $is_success,
            'ok'              => $is_success,
            'message'         => $is_success ? "Peer task '{$task}' executed successfully." : "Failed to execute peer task.",
            'server_response' => $res
        ], JSON_UNESCAPED_UNICODE);
    } else {
        echo json_encode(['status' => 'error', 'success' => false, 'ok' => false, 'message' => 'Invalid peer task.'], JSON_UNESCAPED_UNICODE);
    }
    exit;
}

// -------------------------------------------------------------
// ⚡ بهینه‌سازی و پاکسازی شبکه
// -------------------------------------------------------------
if ($action === 'optimize_gaming') {
    $sh_gaming = <<<'SHELL'
#!/bin/bash
modprobe tcp_bbr 2>/dev/null || true
cat > /etc/sysctl.d/99-latency-optimizer.conf << EOF
net.core.default_qdisc=cake
net.ipv4.tcp_congestion_control=bbr
net.core.rmem_max=67108864
net.core.wmem_max=67108864
net.ipv4.tcp_rmem=4096 87380 67108864
net.ipv4.tcp_wmem=4096 65536 67108864
net.core.netdev_max_backlog=15000
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_fin_timeout=15
net.ipv4.tcp_keepalive_time=600
net.ipv4.tcp_tw_reuse=1
EOF
sysctl -e --system >/dev/null 2>&1 || true
INTERFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
if [ -n "$INTERFACE" ]; then
    tc qdisc replace dev "$INTERFACE" root cake besteffort double-ack bandwidth 1gbit 2>/dev/null || \
    tc qdisc replace dev "$INTERFACE" root fq_codel limit 10240 target 5ms interval 100ms 2>/dev/null || true
fi
iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN -o wg+ -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
echo "SUCCESS_OPTIMIZED"
SHELL;
    $res = exec_py($ssh, "/bin/bash", $sh_gaming);
    echo json_encode(['status' => 'success', 'success' => true, 'ok' => true, 'message' => 'Gaming optimizations applied.', 'output' => $res], JSON_UNESCAPED_UNICODE);
    exit;
}

if ($action === 'sync_ips') {
    $py_cleanup = <<<'PYTHON'
import sqlite3, subprocess, os
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
try:
    conn = sqlite3.connect(db_path, timeout=10.0)
    cur = conn.cursor()
    cur.execute("SELECT peer_ip, COUNT(*) FROM peers GROUP BY peer_ip HAVING COUNT(*) > 1")
    for r in cur.fetchall():
        ip = r[0]
        if not ip: continue
        cur.execute("SELECT id, public_key, config FROM peers WHERE peer_ip=? ORDER BY id ASC", (ip,))
        rows = cur.fetchall()
        for dup in rows[1:]:
            cur.execute("DELETE FROM peers WHERE id=?", (dup[0],))
            conn.commit()
            iface = dup[2].replace(".conf", "")
            subprocess.run(f"wg set {iface} peer {dup[1]} remove", shell=True, stderr=subprocess.DEVNULL)
    conn.close()
    
    routes = subprocess.getoutput("ip route show table all")
    for line in routes.splitlines():
        if "blackhole" in line:
            parts = line.split()
            if len(parts) >= 2:
                subprocess.run(f"ip route del blackhole {parts[1]}", shell=True, stderr=subprocess.DEVNULL)
    print("SUCCESS_CLEANED")
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    $res = exec_py($ssh, $py_bin, $py_cleanup);
    echo json_encode(['status' => 'success', 'success' => true, 'ok' => true, 'message' => 'Network cleaned successfully.', 'output' => $res], JSON_UNESCAPED_UNICODE);
    exit;
}
// -------------------------------------------------------------
// ⚙️ عملیات‌های نمایندگان (Reseller Actions) - هماهنگی جامع با Node
// -------------------------------------------------------------
if ($action === 'reseller_action') {
    $iface = trim($input['interface'] ?? '');
    $task  = trim($input['task'] ?? '');     
    $value = trim((string)($input['value'] ?? ''));     

    if ($task !== 'create' && (empty($iface) || empty($task))) {
        die(json_encode([
            'status'  => 'error', 
            'success' => false, 
            'ok'      => false, 
            'message' => 'interface and task are required.'
        ], JSON_UNESCAPED_UNICODE));
    }

    $py_action = "";

    // ۱. ایجاد نماینده جدید (Create Reseller) با ساخت/ویرایش درجا در Node
    if ($task === 'create') {
        $username = trim($input['username'] ?? '');
        $password = trim($input['password'] ?? '');
        $limit_gb = floatval($input['limit_gb'] ?? ($value ?: 100));

        if (empty($username) || empty($password) || $limit_gb <= 0) {
            die(json_encode([
                'status'  => 'error', 
                'success' => false, 
                'ok'      => false, 
                'message' => 'username, password and positive limit_gb are required.'
            ], JSON_UNESCAPED_UNICODE));
        }

        $py_action = <<<PYTHON
import sys, sqlite3, subprocess, re, json, base64, os
sys.stdout.reconfigure(line_buffering=True)
from werkzeug.security import generate_password_hash

username = "{$username}"
password = "{$password}"
limit_gb = {$limit_gb}
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sub_panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT, interface_name TEXT UNIQUE, username TEXT UNIQUE, 
            password_hash TEXT, data_limit_gb REAL, port INTEGER, created_at TEXT, status TEXT, 
            disabled_at TEXT, password_plain TEXT, deleted_traffic INTEGER DEFAULT 0, 
            alert_80_sent INTEGER DEFAULT 0, alert_100_sent INTEGER DEFAULT 0, 
            telegram_chat_id TEXT DEFAULT '', telegram_bot_token TEXT DEFAULT '', 
            telegram_bot_status TEXT DEFAULT 'off', bot_base_url TEXT DEFAULT ''
        )
    """)
    cur.execute("PRAGMA table_info(sub_panels)")
    cols = [c[1] for c in cur.fetchall()]
    for col_n, col_d in [("bot_base_url", "TEXT DEFAULT ''"), ("telegram_bot_token", "TEXT DEFAULT ''"), ("telegram_chat_id", "TEXT DEFAULT ''"), ("telegram_bot_status", "TEXT DEFAULT 'off'")]:
        if col_n not in cols:
            try: cur.execute(f"ALTER TABLE sub_panels ADD COLUMN {col_n} {col_d}")
            except: pass
    conn.commit()

    cur.execute("SELECT id FROM sub_panels WHERE username=?", (username,))
    if cur.fetchone():
        print("ERROR_DUPLICATE_USERNAME")
        sys.exit(0)

    used_interfaces = set()
    if os.path.exists('/etc/wireguard'):
        for f in os.listdir('/etc/wireguard'):
            if f.endswith('.conf'):
                used_interfaces.add(f.replace('.conf', '').lower())

    try:
        for row in cur.execute('SELECT interface_name FROM sub_panels').fetchall():
            if row[0]: used_interfaces.add(row[0].lower())
    except: pass

    iface_num = 1
    while f"wg{iface_num}" in used_interfaces:
        iface_num += 1

    iface = f"wg{iface_num}"
    port = 51820 + iface_num
    new_subnet = f"10.{iface_num}.0.1/16"

    priv_key = subprocess.check_output("wg genkey", shell=True, text=True).strip()
    conf_path = f"/etc/wireguard/{iface}.conf"
    main_nic = subprocess.getoutput("ip route | grep default | awk '{print $5}' | head -n1").strip() or "eth0"

    conf = f"[Interface]\\nAddress = {new_subnet}\\nSaveConfig = false\\nListenPort = {port}\\nPrivateKey = {priv_key}\\n"
    if main_nic:
        conf += f"PostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -t nat -A POSTROUTING -o {main_nic} -j MASQUERADE\\n"
        conf += f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -t nat -D POSTROUTING -o {main_nic} -j MASQUERADE\\n"

    with open(conf_path, 'w', encoding='utf-8') as f: f.write(conf)

    hashed_pw = generate_password_hash(password)
    cur.execute("""
        INSERT INTO sub_panels (
            interface_name, username, password_hash, data_limit_gb, port, 
            created_at, status, password_plain, telegram_bot_status, bot_base_url
        ) VALUES (?, ?, ?, ?, ?, datetime('now'), 'active', ?, 'off', '')
    """, (iface, username, hashed_pw, limit_gb, port, password))
    conn.commit()
    conn.close()

    subprocess.run("systemctl daemon-reload", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"systemctl enable wg-quick@{iface}; systemctl start wg-quick@{iface}; wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)

    # 📌 همگام‌سازی تضمینی و بلادرنگ اینترفیس متناظر در Node
    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_reseller_state_to_edges(iface, "create", wait=True)
    except Exception as e_sync:
        pass

    print(f"SUCCESS_CREATED|{iface}|{port}|{new_subnet}")
except Exception as e: 
    print("Error: " + str(e))
PYTHON;
    }

    // ۲. تغییر نام کاربری (Change Username)
    elseif ($task === 'change_username') {
        $new_username = trim($value);
        if (empty($new_username)) {
            die(json_encode(['status' => 'error', 'success' => false, 'ok' => false, 'message' => 'New username cannot be empty.'], JSON_UNESCAPED_UNICODE));
        }

        $py_action = <<<PYTHON
import sqlite3, sys
iface = "{$iface}"
new_user = "{$new_username}"
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    if iface == 'wg0':
        cur.execute("SELECT id FROM users WHERE username=?", (new_user,))
        if cur.fetchone():
            print("ERROR_DUPLICATE_USERNAME")
            sys.exit(0)
        cur.execute("UPDATE users SET username=?", (new_user,))
    else:
        cur.execute("SELECT id FROM sub_panels WHERE username=? AND interface_name!=?", (new_user, iface))
        if cur.fetchone():
            print("ERROR_DUPLICATE_USERNAME")
            sys.exit(0)
        cur.execute("UPDATE sub_panels SET username=? WHERE interface_name=?", (new_user, iface))
    conn.commit()
    conn.close()

    if iface != 'wg0':
        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_reseller_state_to_edges(iface, "edit", wait=True)
        except Exception: pass

    print("SUCCESS")
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

    // ۳. تغییر کلمه عبور (Change Password)
    elseif ($task === 'change_pw') {
        $new_pw = trim($value);
        if (empty($new_pw)) {
            die(json_encode(['status' => 'error', 'success' => false, 'ok' => false, 'message' => 'New password cannot be empty.'], JSON_UNESCAPED_UNICODE));
        }

        $py_action = <<<PYTHON
import sqlite3
from werkzeug.security import generate_password_hash

iface = "{$iface}"
new_pw = "{$new_pw}"
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    hashed_pw = generate_password_hash(new_pw)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    if iface == 'wg0':
        cur.execute("UPDATE users SET password_hash=?, password_plain=?", (hashed_pw, new_pw))
    else:
        cur.execute("UPDATE sub_panels SET password_hash=?, password_plain=? WHERE interface_name=?", (hashed_pw, new_pw, iface))
    conn.commit()
    conn.close()

    if iface != 'wg0':
        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_reseller_state_to_edges(iface, "edit", wait=True)
        except Exception: pass

    print("SUCCESS")
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

    // ۴. افزایش حجم (Extend)
    elseif ($task === 'extend') {
        $add_gb = floatval($value);
        if ($add_gb <= 0) {
            die(json_encode(['status' => 'error', 'success' => false, 'ok' => false, 'message' => 'value must be a positive number.'], JSON_UNESCAPED_UNICODE));
        }

        $py_action = <<<PYTHON
import sqlite3, subprocess
iface = "{$iface}"
add_gb = {$add_gb}
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("UPDATE sub_panels SET data_limit_gb = data_limit_gb + ?, status='active', disabled_at=NULL, alert_80_sent=0, alert_100_sent=0 WHERE interface_name=?", (add_gb, iface))
    conn.commit()
    conn.close()

    subprocess.run(f"systemctl start wg-quick@{iface}; wg-quick up {iface} 2>/dev/null", shell=True, stderr=subprocess.DEVNULL)

    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_reseller_state_to_edges(iface, "extend", wait=True)
    except Exception: pass

    print("SUCCESS")
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

// ۵. کسر حجم (Deduct) به همراه بررسی خودکار سقف مصرف و انعکاس در دیتابیس محلی
    elseif ($task === 'deduct') {
        $sub_gb = floatval($value);
        if ($sub_gb <= 0) {
            die(json_encode([
                'status'  => 'error', 
                'success' => false, 
                'ok'      => false, 
                'message' => 'مقدار کسر حجم باید یک عدد مثبت باشد.'
            ], JSON_UNESCAPED_UNICODE));
        }

        $py_action = <<<PYTHON
import sqlite3, subprocess, datetime, sys
iface = "{$iface}"
sub_gb = {$sub_gb}
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    
    # ۱. کسر قطعی سقف حجم در دیتابیس
    cur.execute("UPDATE sub_panels SET data_limit_gb = MAX(0.0, data_limit_gb - ?) WHERE interface_name=?", (sub_gb, iface))
    
    # ۲. استعلام سقف جدید و مصرف کل نماینده (ترافیک زنده + ترافیک کاربران حذف‌شده)
    cur.execute("SELECT data_limit_gb, deleted_traffic FROM sub_panels WHERE interface_name=?", (iface,))
    row_sp = cur.fetchone()
    limit_val = float(row_sp[0] or 0.0)
    del_val = int(row_sp[1] or 0)

    cur.execute("SELECT SUM(used) FROM peers WHERE config=? OR config=?", (f"{iface}.conf", iface))
    live_used = cur.fetchone()[0] or 0
    total_used_gb = round((live_used + del_val) / 1073741824.0, 2)

    # ۳. بررسی عبور از سقف مجاز جدید و مسدودسازی آنی کارت شبکه در صورت اتمام حجم
    new_status = 'active'
    if total_used_gb >= limit_val:
        new_status = 'disabled'
        cur.execute("UPDATE sub_panels SET status='disabled', disabled_at=? WHERE interface_name=?", (now_str, iface))
        subprocess.run(f"systemctl stop wg-quick@{iface} 2>/dev/null; wg-quick down {iface} 2>/dev/null", shell=True, stderr=subprocess.DEVNULL)

    conn.commit()
    conn.close()

    # ۴. همگام‌سازی وضعیت در Nodeها
    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_reseller_state_to_edges(iface, "edit", wait=True)
    except Exception:
        pass

    # بازگرداندن متادیتا به PHP جهت به‌روزرسانی رجیستری محلی
    print(f"SUCCESS_DEDUCTED|{limit_val}|{total_used_gb}|{new_status}")
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

    // ۶. تغییر وضعیت تعلیق/فعال (Toggle)
    elseif ($task === 'toggle') {
        $status = (strtolower($value) === 'active') ? 'active' : 'suspended';
        $py_action = <<<PYTHON
import sqlite3, subprocess, datetime
iface = "{$iface}"
status = "{$status}"
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    if status == 'active':
        cur.execute("UPDATE sub_panels SET status='active', disabled_at=NULL, alert_100_sent=0 WHERE interface_name=?", (iface,))
        subprocess.run(f"systemctl start wg-quick@{iface}; wg-quick up {iface} 2>/dev/null", shell=True, stderr=subprocess.DEVNULL)
    else:
        cur.execute("UPDATE sub_panels SET status='suspended', disabled_at=? WHERE interface_name=?", (now_str, iface))
        subprocess.run(f"systemctl stop wg-quick@{iface}; wg-quick down {iface} 2>/dev/null", shell=True, stderr=subprocess.DEVNULL)
    conn.commit()
    conn.close()

    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_reseller_state_to_edges(iface, "toggle", wait=True)
    except Exception: pass

    print("SUCCESS")
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

    // ۷. حذف کامل نماینده (Delete Reseller) و شستشوی همزمان در Master و Node
    elseif ($task === 'delete') {
        $py_action = <<<PYTHON
import sqlite3, subprocess, os
iface = "{$iface}"
cfg_file = f"{iface}.conf"
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    subprocess.run(f"wg-quick down {iface} 2>/dev/null", shell=True)
    subprocess.run(f"systemctl stop wg-quick@{iface} 2>/dev/null", shell=True)
    subprocess.run(f"systemctl disable wg-quick@{iface} 2>/dev/null", shell=True)
    if os.path.exists(f"/etc/wireguard/{cfg_file}"):
        os.remove(f"/etc/wireguard/{cfg_file}")

    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()

    cur.execute("SELECT id, deleted_traffic FROM sub_panels WHERE interface_name=?", (iface,))
    sub_row = cur.fetchone()
    reseller_id = sub_row[0] if sub_row else None
    del_traffic = int(sub_row[1] or 0) if sub_row else 0

    cur.execute("SELECT SUM(used) FROM peers WHERE config=? OR config=?", (cfg_file, iface))
    r_live = cur.fetchone()
    live_used = int(r_live[0] or 0) if r_live and r_live[0] else 0

    total_interface_traffic = live_used + del_traffic
    if total_interface_traffic > 0:
        import sqlite_backend
        sqlite_backend.record_deleted_traffic_atomic("wg0", total_interface_traffic)

    cur.execute("SELECT token FROM peers WHERE config=? OR config=?", (cfg_file, iface))
    for t_row in cur.fetchall():
        tok = t_row[0]
        if tok:
            try: cur.execute("DELETE FROM short_links WHERE short_id=? OR short_id=?", (tok, tok[:8]))
            except: pass

    cur.execute("DELETE FROM peers WHERE config=? OR config=?", (cfg_file, iface))
    cur.execute("DELETE FROM peer_synced_edges WHERE config=? OR config=?", (cfg_file, iface))
    
    if reseller_id:
        try:
            cur.execute("DELETE FROM templates WHERE user_id=?", (reseller_id,))
            cur.execute("DELETE FROM services WHERE user_id=?", (reseller_id,))
        except: pass

    cur.execute("DELETE FROM sub_panels WHERE interface_name=?", (iface,))
    try: cur.execute("DELETE FROM historical_interface_traffic WHERE interface_name=?", (iface,))
    except: pass
    try: cur.execute("DELETE FROM interface_vault WHERE interface_name=?", (iface,))
    except: pass
    try: cur.execute("DELETE FROM client_settings WHERE interface_name=?", (iface,))
    except: pass

    conn.commit()
    conn.close()

    # 📌 پاکسازی کامل و تضمینی اینترفیس و دیتابیس در تمام Nodeها
    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_reseller_state_to_edges(iface, "delete", wait=True)
    except Exception: pass
    
    print("SUCCESS")
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

    if (!empty($py_action)) {
        $res = exec_py($ssh, $py_bin, $py_action);
        $is_success = (strpos($res, 'SUCCESS') !== false);
        
        if ($is_success) {
            if ($task === 'delete') {
                remove_local_interface($target_ip, $iface);
            } elseif ($task === 'create' && preg_match('/SUCCESS_CREATED\|([^|]+)\|([^|]+)\|([^|]+)/', $res, $m)) {
                register_local_interface($target_ip, $m[1], [
                    'interface_name' => $m[1],
                    'username'       => $username,
                    'password_plain' => $password,
                    'data_limit_gb'  => $limit_gb,
                    'port'           => intval($m[2]),
                    'subnet_ip'      => $m[3],
                    'used_gb'        => 0.0,
                    'status'         => 'active'
                ], true);
            } elseif ($task === 'deduct' && preg_match('/SUCCESS_DEDUCTED\|([^|]+)\|([^|]+)\|([^|]+)/', $res, $m)) {
                // ثبت قطعی سقف جدید و حجم مصرفی در local_servers_registry.json
                register_local_interface($target_ip, $iface, [
                    'data_limit_gb'  => floatval($m[1]),
                    'used_gb'        => floatval($m[2]),
                    'status'         => trim($m[3])
                ], true); // مقدار true اجازه بازنویسی و کاهش سقف را می‌دهد
            } elseif ($task === 'extend') {
                // به‌روزرسانی پس از شارژ حجم
                $reg = get_local_registry();
                $cur_lim = floatval($reg[$target_ip]['interfaces'][$iface]['data_limit_gb'] ?? 0);
                register_local_interface($target_ip, $iface, [
                    'data_limit_gb' => $cur_lim + floatval($value),
                    'status'        => 'active'
                ], true);
            }
        }

        echo json_encode([
            'status'          => $is_success ? 'success' : 'error',
            'success'         => $is_success,
            'ok'              => $is_success,
            'message'         => $is_success ? "عملیات '{$task}' با موفقیت انجام و اعمال گردید." : "خطا در اجرای عملیات.",
            'server_response' => $res
        ], JSON_UNESCAPED_UNICODE);
    } else {
        echo json_encode(['status' => 'error', 'success' => false, 'ok' => false, 'message' => 'Invalid or unsupported task.'], JSON_UNESCAPED_UNICODE);
    }
    exit;
}
echo json_encode(['status' => 'error', 'success' => false, 'ok' => false, 'message' => 'Invalid action.'], JSON_UNESCAPED_UNICODE);
?>