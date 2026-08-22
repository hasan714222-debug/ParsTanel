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

function register_local_interface($host, $iface, $details) {
    $reg = get_local_registry();
    if (!isset($reg[$host])) {
        $reg[$host] = ['host' => $host, 'interfaces' => []];
    }
    if (!isset($reg[$host]['interfaces'])) {
        $reg[$host]['interfaces'] = [];
    }
    
    $existing = $reg[$host]['interfaces'][$iface] ?? [];
    
    // ۱. سوپاپ قطعی عدم کاهش ترافیک مصرفی
    $existing_used = floatval($existing['used_gb'] ?? 0.0);
    $incoming_used = isset($details['used_gb']) ? floatval($details['used_gb']) : 0.0;
    $details['used_gb'] = max($existing_used, $incoming_used);

    // ۲. محافظت از سقف حجم تخصیص‌یافته
    $existing_limit = floatval($existing['data_limit_gb'] ?? 0.0);
    $incoming_limit = isset($details['data_limit_gb']) ? floatval($details['data_limit_gb']) : 0.0;
    if ($incoming_limit <= 0 && $existing_limit > 0) {
        $details['data_limit_gb'] = $existing_limit;
    } elseif ($incoming_limit > 0) {
        $details['data_limit_gb'] = $incoming_limit;
    } else {
        $details['data_limit_gb'] = $existing_limit > 0 ? $existing_limit : 100.0;
    }

    // ۳. محاسبه خودکار حجم باقی‌مانده
    if ($iface === 'wg0' || $details['data_limit_gb'] <= 0) {
        $details['rem_gb'] = 0.0;
    } else {
        $details['rem_gb'] = round(max(0.0, $details['data_limit_gb'] - $details['used_gb']), 2);
    }

    // ۴. قفل نام کاربری
    $invalid_usernames = ['بدون نماینده (پیش‌فرض)', 'N/A', '', null];
    $incoming_user = trim($details['username'] ?? '');
    if (in_array($incoming_user, $invalid_usernames, true)) {
        if (!empty($existing['username']) && !in_array($existing['username'], $invalid_usernames, true)) {
            $details['username'] = $existing['username'];
        } else {
            $details['username'] = $iface === 'wg0' ? 'Pars (مدیر کل)' : "Reseller_{$iface}";
        }
    }

    // ۵. قفل کلمه عبور
    if (empty($details['password_plain']) || $details['password_plain'] === 'N/A') {
        if (!empty($existing['password_plain']) && $existing['password_plain'] !== 'N/A') {
            $details['password_plain'] = $existing['password_plain'];
        }
    }
    if (empty($details['password_hash']) && !empty($existing['password_hash'])) {
        $details['password_hash'] = $existing['password_hash'];
    }

    // ۶. پورت و ساب‌نت
    if ((empty($details['port']) || $details['port'] === 'N/A') && !empty($existing['port'])) {
        $details['port'] = $existing['port'];
    }
    if ((empty($details['subnet_ip']) || $details['subnet_ip'] === 'N/A') && !empty($existing['subnet_ip'])) {
        $details['subnet_ip'] = $existing['subnet_ip'];
    }

    // ۷. وضعیت
    if (empty($details['status'])) {
        $details['status'] = $existing['status'] ?? 'active';
    }
    if (isset($existing['disabled_at']) && !isset($details['disabled_at'])) {
        $details['disabled_at'] = $existing['disabled_at'];
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
    echo json_encode(['status' => 'success', 'data' => $list], JSON_UNESCAPED_UNICODE);
    exit;
}

$target_ip = trim($input['server_ip'] ?? '');
if (empty($target_ip)) {
    die(json_encode(['status' => 'error', 'message' => 'server_ip is required.'], JSON_UNESCAPED_UNICODE));
}

$ssh = connect_to_server($target_ip);
if (!$ssh) {
    die(json_encode([
        'status'  => 'error', 
        'message' => "Cannot connect to server {$target_ip} via SSH. Check credentials or firewall."
    ], JSON_UNESCAPED_UNICODE));
}

// -------------------------------------------------------------
// 👥 دریافت لیست نمایندگان
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

    cur.execute("SELECT interface_name, username, password_plain, data_limit_gb, port, status, deleted_traffic FROM sub_panels")
    for r in cur.fetchall():
        iface, user, pw, limit, port, status, del_traf = r
        del_traf = del_traf or 0

        cur.execute("SELECT SUM(used) FROM peers WHERE config=?", (f"{iface}.conf",))
        live_used = cur.fetchone()[0] or 0

        vault_t = universal_vault.get(iface, 0)
        vault_traffic = max(del_traf, vault_t)
        total_bytes = live_used + vault_traffic

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
    total_global_bytes = live + del_total
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
    echo json_encode(['status' => 'success', 'data' => json_decode($out, true)], JSON_UNESCAPED_UNICODE);
    exit;
}

// -------------------------------------------------------------
// 👥 دریافت لیست کلاینت‌های متصل به اینترفیس
// -------------------------------------------------------------
if ($action === 'get_peers') {
    $iface = trim($input['interface'] ?? 'wg0');
    $py_peers = <<<PYTHON
import sqlite3, json
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
cfg_name = "{$iface}.conf" if not "{$iface}".endswith('.conf') else "{$iface}"
peers = []
try:
    conn = sqlite3.connect(db_path, timeout=10.0)
    cur = conn.cursor()
    cur.execute("SELECT peer_name, peer_ip, public_key, [limit], used, remaining_time, monitor_blocked, expiry_blocked, token FROM peers WHERE config=?", (cfg_name,))
    for r in cur.fetchall():
        peers.append({
            "peer_name": r[0], "peer_ip": r[1], "public_key": r[2],
            "limit": r[3], "used_bytes": r[4], "remaining_time_minutes": r[5],
            "is_blocked": bool(r[6] or r[7]), "token": r[8]
        })
    conn.close()
    print(json.dumps(peers))
except Exception as e:
    print(json.dumps({"error": str(e)}))
PYTHON;
    $out = exec_py($ssh, $py_bin, $py_peers);
    echo json_encode(['status' => 'success', 'data' => json_decode($out, true)], JSON_UNESCAPED_UNICODE);
    exit;
}

// -------------------------------------------------------------
// ⚙️ عملیات‌های نمایندگان (Reseller Actions: Toggle, Delete, Extend, ...)
// -------------------------------------------------------------
if ($action === 'reseller_action' || $action === 'delete_reseller' || $action === 'toggle_reseller') {
    $iface = trim($input['interface'] ?? $input['iface'] ?? $input['interface_name'] ?? $input['username'] ?? $input['t_iface'] ?? '');
    $iface = str_replace('.conf', '', $iface);
    
    if ($action === 'delete_reseller') {
        $task = 'delete';
    } elseif ($action === 'toggle_reseller') {
        $task = 'toggle';
    } else {
        $task = trim($input['task'] ?? '');
    }
    
    $value = trim((string)($input['value'] ?? $input['t_status'] ?? ''));

    if ($task !== 'create' && (empty($iface) || empty($task))) {
        die(json_encode(['status' => 'error', 'message' => 'interface and task are required.'], JSON_UNESCAPED_UNICODE));
    }

    if ($task === 'delete' && $iface === 'wg0') {
        die(json_encode(['status' => 'error', 'message' => 'Cannot delete main server interface (wg0).'], JSON_UNESCAPED_UNICODE));
    }

    $py_action = "";

    // ۱. ایجاد نماینده جدید (Create)
    if ($task === 'create') {
        $username = trim($input['username'] ?? '');
        $password = trim($input['password'] ?? '');
        $limit_gb = floatval($input['limit_gb'] ?? ($value ?: 100));

        if (empty($username) || empty($password) || $limit_gb <= 0) {
            die(json_encode(['status' => 'error', 'message' => 'username, password and positive limit_gb are required.'], JSON_UNESCAPED_UNICODE));
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
    cur.execute("SELECT id FROM sub_panels WHERE username=?", (username,))
    if cur.fetchone():
        print("ERROR_DUPLICATE_USERNAME")
        sys.exit(0)

    used_interfaces, used_ports, used_subnets = set(), set(), set()
    if os.path.exists('/etc/wireguard'):
        for f in os.listdir('/etc/wireguard'):
            if f.endswith('.conf'):
                used_interfaces.add(f.replace('.conf', '').lower())
                try:
                    txt = open(os.path.join('/etc/wireguard', f), 'r').read()
                    m1 = re.search(r'ListenPort\s*=\s*(\d+)', txt, re.IGNORECASE)
                    if m1: used_ports.add(int(m1.group(1)))
                    m2 = re.search(r'Address\s*=\s*10\.0\.(\d+)\.', txt, re.IGNORECASE)
                    if m2: used_subnets.add(int(m2.group(1)))
                except: pass

    try:
        for row in cur.execute('SELECT interface_name, port FROM sub_panels').fetchall():
            if row[0]: used_interfaces.add(row[0].lower())
            if row[1]: used_ports.add(int(row[1]))
    except: pass

    iface = 'wg1'
    for i in range(1, 1001):
        cand = f"wg{i}"
        if cand not in used_interfaces:
            iface = cand
            break

    port = 51821
    while port in used_ports: port += 1

    sub_idx = 10
    while sub_idx in used_subnets: sub_idx += 5
    new_subnet = f"10.0.{sub_idx}.1/24"

    priv_key = subprocess.check_output("wg genkey", shell=True, text=True).strip()
    conf_path = f"/etc/wireguard/{iface}.conf"
    main_nic = subprocess.getoutput("ip route | grep default | awk '{print $5}' | head -n1").strip()

    conf = f"[Interface]\\nAddress = {new_subnet}\\nSaveConfig = false\\nListenPort = {port}\\nPrivateKey = {priv_key}\\n"
    if main_nic:
        conf += f"PostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -A FORWARD -o {iface} -j ACCEPT; iptables -I FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -A POSTROUTING -o {main_nic} -j MASQUERADE\\n"
        conf += f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -D FORWARD -o {iface} -j ACCEPT; iptables -D FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -D POSTROUTING -o {main_nic} -j MASQUERADE\\n"

    with open(conf_path, 'w', encoding='utf-8') as f: f.write(conf)

    hashed_pw = generate_password_hash(password)
    cur.execute("INSERT INTO sub_panels (interface_name, username, password_hash, data_limit_gb, port, created_at, status, password_plain) VALUES (?, ?, ?, ?, ?, datetime('now'), 'active', ?)", (iface, username, hashed_pw, limit_gb, port, password))
    conn.commit()

    subprocess.run(f"systemctl enable wg-quick@{iface}; systemctl start wg-quick@{iface}; wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
    print(f"SUCCESS_CREATED|{iface}|{port}|{new_subnet}")

    cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
    edges = cur.fetchall()
    if edges:
        for s_ip, s_port, s_user, s_pass in edges:
            edge_script = f'''import os, subprocess, sqlite3
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
if not os.path.exists("/etc/wireguard/{iface}.conf"):
    open("/etc/wireguard/{iface}.conf", "w").write("""{conf}""")
conn_e = sqlite3.connect(db_path, timeout=10.0)
cur_e = conn_e.cursor()
cur_e.execute("CREATE TABLE IF NOT EXISTS sub_panels (id INTEGER PRIMARY KEY AUTOINCREMENT, interface_name TEXT UNIQUE, username TEXT UNIQUE, password_hash TEXT, data_limit_gb REAL, port INTEGER, created_at TEXT, status TEXT, disabled_at TEXT, password_plain TEXT, deleted_traffic INTEGER DEFAULT 0)")
cur_e.execute("INSERT OR IGNORE INTO sub_panels (interface_name, username, password_hash, data_limit_gb, port, created_at, status, password_plain) VALUES (?, ?, ?, ?, ?, datetime('now'), 'active', ?)", ("{iface}", "{username}", "{hashed_pw}", {limit_gb}, {port}, "{password}"))
conn_e.commit()
conn_e.close()
subprocess.run("systemctl enable wg-quick@{iface}; systemctl start wg-quick@{iface}; wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
'''
            enc = base64.b64encode(edge_script.encode('utf-8')).decode('utf-8')
            cmd = f"echo '{enc}' | base64 -d > /tmp/ae.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/ae.py && rm -f /tmp/ae.py"
            subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=3 {s_user}@{s_ip} \"{cmd}\"", shell=True, stderr=subprocess.DEVNULL)

    conn.close()
except Exception as e: 
    print("Error: " + str(e))
PYTHON;
    }

    // ۲. تغییر نام کاربری (Change Username)
    elseif ($task === 'change_username') {
        $new_username = trim($value);
        if (empty($new_username)) {
            die(json_encode(['status' => 'error', 'message' => 'New username cannot be empty.'], JSON_UNESCAPED_UNICODE));
        }

        $py_action = <<<PYTHON
import sqlite3, sys, subprocess
target_iface = "{$iface}"
new_user = "{$new_username}"
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("SELECT interface_name FROM sub_panels WHERE interface_name=? OR username=?", (target_iface, target_iface))
    row = cur.fetchone()
    iface = row[0] if row else target_iface

    cur.execute("SELECT id FROM sub_panels WHERE username=? AND interface_name!=?", (new_user, iface))
    if cur.fetchone():
        print("ERROR_DUPLICATE_USERNAME")
        sys.exit(0)

    cur.execute("UPDATE sub_panels SET username=? WHERE interface_name=?", (new_user, iface))
    conn.commit()

    try:
        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
        for s_ip, s_port, s_user, s_pass in cur.fetchall():
            cmd = f"sqlite3 {db_path} \\\"UPDATE sub_panels SET username='{new_user}' WHERE interface_name='{iface}';\\\""
            subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=3 {s_user}@{s_ip} \"{cmd}\"", shell=True, stderr=subprocess.DEVNULL)
    except: pass

    conn.close()
    print("SUCCESS")
except Exception as e:
    print("Error: " + str(e))
PYTHON;
    }

    // ۳. تغییر کلمه عبور (Change Password)
    elseif ($task === 'change_pw') {
        $new_pw = trim($value);
        if (empty($new_pw)) {
            die(json_encode(['status' => 'error', 'message' => 'New password cannot be empty.'], JSON_UNESCAPED_UNICODE));
        }

        $py_action = <<<PYTHON
import sqlite3, subprocess
from werkzeug.security import generate_password_hash

target_iface = "{$iface}"
new_pw = "{$new_pw}"
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    hashed_pw = generate_password_hash(new_pw)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("SELECT interface_name FROM sub_panels WHERE interface_name=? OR username=?", (target_iface, target_iface))
    row = cur.fetchone()
    iface = row[0] if row else target_iface

    if iface == 'wg0':
        cur.execute("UPDATE users SET password_hash=?, password_plain=?", (hashed_pw, new_pw))
    else:
        cur.execute("UPDATE sub_panels SET password_hash=?, password_plain=? WHERE interface_name=?", (hashed_pw, new_pw, iface))
    conn.commit()

    try:
        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
        for s_ip, s_port, s_user, s_pass in cur.fetchall():
            cmd = f"sqlite3 {db_path} \\\"UPDATE sub_panels SET password_hash='{hashed_pw}', password_plain='{new_pw}' WHERE interface_name='{iface}';\\\""
            subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=3 {s_user}@{s_ip} \"{cmd}\"", shell=True, stderr=subprocess.DEVNULL)
    except: pass

    conn.close()
    print("SUCCESS")
except Exception as e:
    print("Error: " + str(e))
PYTHON;
    }

    // ۴. تمدید و افزایش حجم (Extend)
    elseif ($task === 'extend') {
        $add_gb = floatval($value);
        if ($add_gb <= 0) {
            die(json_encode(['status' => 'error', 'message' => 'value must be a positive number.'], JSON_UNESCAPED_UNICODE));
        }

        $py_action = <<<PYTHON
import sqlite3, subprocess, base64
target_iface = "{$iface}"
add_gb = {$add_gb}
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("SELECT interface_name, username, password_hash, data_limit_gb, port, password_plain, deleted_traffic FROM sub_panels WHERE interface_name=? OR username=?", (target_iface, target_iface))
    row = cur.fetchone()
    if not row:
        print("ERROR_RESELLER_NOT_FOUND")
    else:
        iface = row[0]
        cur.execute("UPDATE sub_panels SET data_limit_gb = data_limit_gb + ?, status='active', disabled_at=NULL WHERE interface_name=?", (add_gb, iface))
        conn.commit()
        subprocess.run(f"systemctl start wg-quick@{iface}; wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)

        u, pw_h, n_lim, p, pw_p, del_t = row[1], row[2], row[3] + add_gb, row[4], row[5], row[6]
        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
        for s_ip, s_port, s_user, s_pass in cur.fetchall():
            edge_script = f'''import sqlite3, subprocess
conn = sqlite3.connect("{db_path}", timeout=10.0); cur = conn.cursor()
cur.execute("INSERT OR REPLACE INTO sub_panels (interface_name, username, password_hash, data_limit_gb, port, status, disabled_at, password_plain, deleted_traffic) VALUES (?, ?, ?, ?, ?, 'active', NULL, ?, ?)",
            ('{iface}', '{u}', '{pw_h}', {n_lim}, {p}, '{pw_p}', {del_t or 0}))
conn.commit(); conn.close()
subprocess.run("systemctl start wg-quick@{iface}; wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
'''
            enc = base64.b64encode(edge_script.encode('utf-8')).decode('utf-8')
            cmd = f"echo '{enc}' | base64 -d > /tmp/sync_ext.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_ext.py && rm -f /tmp/sync_ext.py"
            subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=3 {s_user}@{s_ip} \"{cmd}\"", shell=True, stderr=subprocess.DEVNULL)

        print("SUCCESS")
    conn.close()
except Exception as e:
    print("Error: " + str(e))
PYTHON;
    }

    // ۵. کسر حجم (Deduct)
    elseif ($task === 'deduct') {
        $sub_gb = floatval($value);
        if ($sub_gb <= 0) {
            die(json_encode(['status' => 'error', 'message' => 'value must be a positive number.'], JSON_UNESCAPED_UNICODE));
        }

        $py_action = <<<PYTHON
import sqlite3, subprocess, datetime, base64
target_iface = "{$iface}"
sub_gb = {$sub_gb}
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
now = datetime.datetime.now()

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("SELECT interface_name, username, password_hash, data_limit_gb, port, password_plain, deleted_traffic FROM sub_panels WHERE interface_name=? OR username=?", (target_iface, target_iface))
    row = cur.fetchone()
    if not row:
        print("ERROR_RESELLER_NOT_FOUND")
    else:
        iface = row[0]
        cur.execute("UPDATE sub_panels SET data_limit_gb = MAX(0.0, data_limit_gb - ?) WHERE interface_name=?", (sub_gb, iface))
        conn.commit()

        u, pw_h, old_lim, p, pw_p, del_t = row[1], row[2], row[3], row[4], row[5], row[6]
        new_lim = max(0.0, old_lim - sub_gb)

        cur.execute("SELECT SUM(used) FROM peers WHERE config=?", (f"{iface}.conf",))
        live_used = cur.fetchone()[0] or 0
        total_used_gb = (live_used + (del_t or 0)) / 1073741824.0

        status = 'active'
        disabled_at_str = 'NULL'
        if total_used_gb >= new_lim:
            status = 'disabled'
            disabled_at_str = now.strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("UPDATE sub_panels SET status='disabled', disabled_at=? WHERE interface_name=?", (disabled_at_str, iface))
            conn.commit()
            subprocess.run(f"systemctl stop wg-quick@{iface}; wg-quick down {iface}", shell=True, stderr=subprocess.DEVNULL)

        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
        for s_ip, s_port, s_user, s_pass in cur.fetchall():
            edge_script = f'''import sqlite3, subprocess
conn = sqlite3.connect("{db_path}", timeout=10.0); cur = conn.cursor()
cur.execute("INSERT OR REPLACE INTO sub_panels (interface_name, username, password_hash, data_limit_gb, port, status, disabled_at, password_plain, deleted_traffic) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ('{iface}', '{u}', '{pw_h}', {new_lim}, {p}, '{status}', {f"'{disabled_at_str}'" if status == 'disabled' else 'None'}, '{pw_p}', {del_t or 0}))
conn.commit(); conn.close()
if '{status}' == 'disabled':
    subprocess.run("systemctl stop wg-quick@{iface}; wg-quick down {iface}", shell=True, stderr=subprocess.DEVNULL)
else:
    subprocess.run("systemctl start wg-quick@{iface}; wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
'''
            enc = base64.b64encode(edge_script.encode('utf-8')).decode('utf-8')
            cmd = f"echo '{enc}' | base64 -d > /tmp/sync_ded.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_ded.py && rm -f /tmp/sync_ded.py"
            subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=3 {s_user}@{s_ip} \"{cmd}\"", shell=True, stderr=subprocess.DEVNULL)

        print("SUCCESS")
    conn.close()
except Exception as e:
    print("Error: " + str(e))
PYTHON;
    }

    // ۶. خاموش و روشن کردن هوشمند نماینده (Smart Flip Toggle) 🎯 [اصلاح کامل و بدون نقص]
    elseif ($task === 'toggle') {
        $py_action = <<<PYTHON
import sqlite3, subprocess, datetime, base64
target_iface = "{$iface}".strip()
val_param = "{$value}".strip().lower()
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("SELECT interface_name, status FROM sub_panels WHERE interface_name=? OR username=?", (target_iface, target_iface))
    row = cur.fetchone()
    if not row:
        print("ERROR_RESELLER_NOT_FOUND")
    else:
        iface = row[0]
        cur_status = row[1] or 'active'

        # ۱. تعیین وضعیت هدف بر اساس ورودی یا سوئیچ معکوس وضعیت فعلی
        if val_param in ['active', 'on', 'enable', 'start', '1', 'true']:
            new_status = 'active'
        elif val_param in ['suspended', 'disabled', 'off', 'disable', 'stop', '0', 'false']:
            new_status = 'suspended'
        elif val_param == cur_status:
            # اگر وضعیت فعلی فرستاده شده بود یعنی قصد سوئیچ دارد
            new_status = 'suspended' if cur_status == 'active' else 'active'
        else:
            # در صورت ارسال toggle یا خالی بودن، معکوس کن
            new_status = 'suspended' if cur_status == 'active' else 'active'

        # ۲. اعمال روی کرنل و سیستم‌دی سرور اصلی
        if new_status == 'active':
            subprocess.run(f"systemctl daemon-reload; systemctl enable wg-quick@{iface}; systemctl start wg-quick@{iface}; wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
            cur.execute("UPDATE sub_panels SET status='active', disabled_at=NULL WHERE interface_name=?", (iface,))
        else:
            subprocess.run(f"systemctl stop wg-quick@{iface}; systemctl disable wg-quick@{iface}; wg-quick down {iface}", shell=True, stderr=subprocess.DEVNULL)
            cur.execute("UPDATE sub_panels SET status='suspended', disabled_at=? WHERE interface_name=?", (now_str, iface))
        conn.commit()

        # ۳. همگام‌سازی امن روی سرورهای لبه
        try:
            cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
            edges = cur.fetchall()
            for s_ip, s_port, s_user, s_pass in edges:
                if new_status == 'active':
                    edge_py = f"import sqlite3, subprocess; conn = sqlite3.connect('{db_path}'); conn.execute(\\\"UPDATE sub_panels SET status='active', disabled_at=NULL WHERE interface_name='{iface}'\\\"); conn.commit(); conn.close(); subprocess.run('systemctl enable wg-quick@{iface}; systemctl start wg-quick@{iface}; wg-quick up {iface}', shell=True)"
                else:
                    edge_py = f"import sqlite3, subprocess; conn = sqlite3.connect('{db_path}'); conn.execute(\\\"UPDATE sub_panels SET status='suspended', disabled_at='{now_str}' WHERE interface_name='{iface}'\\\"); conn.commit(); conn.close(); subprocess.run('systemctl stop wg-quick@{iface}; systemctl disable wg-quick@{iface}; wg-quick down {iface}', shell=True)"
                
                enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
                cmd = f"echo '{enc}' | base64 -d > /tmp/toggle_edge.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/toggle_edge.py && rm -f /tmp/toggle_edge.py"
                subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=3 {s_user}@{s_ip} \"{cmd}\"", shell=True, stderr=subprocess.DEVNULL)
        except Exception:
            pass

        print(f"SUCCESS|{iface}|{new_status}")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    }

    // ۷. حذف کامل و بدون خطای نماینده (Delete Reseller) 🎯 [اصلاح کامل و تست‌شده]
    elseif ($task === 'delete') {
        $py_action = <<<PYTHON
import sqlite3, subprocess, os, sys

target_iface = "{$iface}".strip()
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()

    # پیدا کردن نام واقعی کارت شبکه
    cur.execute("SELECT interface_name FROM sub_panels WHERE interface_name=? OR username=?", (target_iface, target_iface))
    row = cur.fetchone()
    if row:
        iface = row[0]
    else:
        iface = target_iface

    # ۱. توقف سرویس و پاکسازی فایل کانفیگ در سرور اصلی
    subprocess.run(f"wg-quick down {iface}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"systemctl stop wg-quick@{iface}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"systemctl disable wg-quick@{iface}", shell=True, stderr=subprocess.DEVNULL)
    
    conf_path = f"/etc/wireguard/{iface}.conf"
    if os.path.exists(conf_path):
        os.remove(conf_path)

    # ۲. پاکسازی کامل رکوردهای نماینده از پایگاه‌داده
    cur.execute("DELETE FROM sub_panels WHERE interface_name=?", (iface,))
    cur.execute("DELETE FROM peers WHERE config=?", (f"{iface}.conf",))
    cur.execute("DELETE FROM historical_interface_traffic WHERE interface_name=?", (iface,))
    cur.execute("DELETE FROM interface_vault WHERE interface_name=?", (iface,))
    cur.execute("DELETE FROM peer_synced_edges WHERE config=?", (f"{iface}.conf",))
    conn.commit()

    # ۳. حذف هماهنگ روی تمام سرورهای لبه (Edge Servers)
    try:
        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
        edges = cur.fetchall()
        for s_ip, s_port, s_user, s_pass in edges:
            edge_cmd = f"systemctl stop wg-quick@{iface}; systemctl disable wg-quick@{iface}; rm -f /etc/wireguard/{iface}.conf; sqlite3 {db_path} \\\"DELETE FROM sub_panels WHERE interface_name='{iface}'; DELETE FROM peers WHERE config='{iface}.conf';\\\""
            subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=4 {s_user}@{s_ip} \"{edge_cmd}\"", shell=True, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    conn.close()

    # ۴. ریستارت سرویس پنل
    subprocess.run("systemctl restart wireguard-panel", shell=True, stderr=subprocess.DEVNULL)
    print(f"SUCCESS|{iface}")

except Exception as e:
    print(f"Error: {str(e)}")
PYTHON;
    }

    // اجرای نهایی عملیات
    if (!empty($py_action)) {
        $res = exec_py($ssh, $py_bin, $py_action);
        $is_success = (strpos($res, 'SUCCESS') !== false);
        
        if ($is_success) {
            if ($task === 'delete') {
                remove_local_interface($target_ip, $iface);
            } elseif ($task === 'toggle' && preg_match('/SUCCESS\|([^|]+)\|([^|]+)/', $res, $m)) {
                register_local_interface($target_ip, $m[1], ['status' => $m[2]]);
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
                ]);
            }
        }

        echo json_encode([
            'status'          => $is_success ? 'success' : 'error',
            'message'         => $is_success ? "Task '{$task}' on '{$iface}' executed successfully." : "Execution failed or returned warning.",
            'server_response' => $res
        ], JSON_UNESCAPED_UNICODE);
    } else {
        echo json_encode(['status' => 'error', 'message' => 'Invalid or unsupported task.'], JSON_UNESCAPED_UNICODE);
    }
    exit;
}

echo json_encode(['status' => 'error', 'message' => 'Invalid action.'], JSON_UNESCAPED_UNICODE);
?>