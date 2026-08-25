<?php
/* ========================================================================= */
/* نام فایل: index.php                                                       */
/* نقش: داشبورد متمرکز مدیریت سرورها، نمایندگان، پایش ترافیک و بکاپ وایرگارد  */
/* ========================================================================= */

ob_start();
if (session_status() === PHP_SESSION_NONE) {
    session_start();
}
ini_set('display_errors', 0);
ini_set('display_startup_errors', 0);
error_reporting(E_ALL);
set_time_limit(900);

// کنترل خطاهای سیستم
register_shutdown_function(function() {
    $e = error_get_last();
    if ($e !== NULL && in_array($e['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR])) {
        echo "<div style='background:#12050b; border:1px solid #ff3366; color:#ff3366; padding:25px; font-family:monospace; direction:ltr; text-align:left; margin:20px; border-radius:12px; box-shadow: 0 0 25px rgba(255,51,102,0.3);'>";
        echo "<h3 style='margin-top:0;'><i class='fas fa-triangle-exclamation'></i> SYSTEM FATAL ERROR</h3>";
        echo "<b>Message:</b> " . htmlspecialchars($e['message']) . "<br>";
        echo "<b>File:</b> " . htmlspecialchars($e['file']) . " : <b>Line</b> " . $e['line'] . "</div>";
    }
});

// ---------------------------------------------------------
// لایه امنیتی احراز هویت مدیریت پنل
// ---------------------------------------------------------
$master_pass_file = __DIR__ . '/.master_pass.php';
function get_panel_master_pass() {
    global $master_pass_file;
    if (file_exists($master_pass_file)) {
        $raw = @file_get_contents($master_pass_file);
        $pass = str_replace('<?php die(); ?>', '', $raw);
        if (!empty(trim($pass))) return trim($pass);
    }
    return 'Pars'; // کلمه عبور پیش‌فرض
}

define('PANEL_MASTER_USER', 'Pars');
define('PANEL_MASTER_PASS', get_panel_master_pass());
$auth_ips_file = __DIR__ . '/.auth_ips.json';

// هندلر تغییر رمز عبور مدیر پنل
if (isset($_POST['action']) && $_POST['action'] === 'change_master_panel_password') {
    if (isset($_SESSION['panel_master_auth']) && $_SESSION['panel_master_auth'] === true) {
        $new_m_pass = trim($_POST['new_master_pass'] ?? '');
        if (!empty($new_m_pass)) {
            file_put_contents($master_pass_file, '<?php die(); ?>' . $new_m_pass);
            $reseller_log = "کلمه عبور اصلی مدیریت پنل با موفقیت تغییر یافت.";
        }
    }
}

$authorized_ips = [];
if (file_exists($auth_ips_file)) {
    $authorized_ips = json_decode(file_get_contents($auth_ips_file), true) ?: [];
}

$client_ip = $_SERVER['REMOTE_ADDR'] ?? '';
$is_panel_authenticated = false;

if (isset($_SESSION['panel_master_auth']) && $_SESSION['panel_master_auth'] === true) {
    $is_panel_authenticated = true;
} elseif (!empty($client_ip) && in_array($client_ip, $authorized_ips)) {
    $_SESSION['panel_master_auth'] = true;
    $is_panel_authenticated = true;
}

// بررسی فرم لاگین اصلی پنل
$master_login_err = "";
if (isset($_POST['action']) && $_POST['action'] === 'master_login') {
    $m_u = trim($_POST['m_user'] ?? '');
    $m_p = trim($_POST['m_pass'] ?? '');
    if ($m_u === PANEL_MASTER_USER && $m_p === PANEL_MASTER_PASS) {
        $_SESSION['panel_master_auth'] = true;
        $is_panel_authenticated = true;
        if (!empty($client_ip) && !in_array($client_ip, $authorized_ips)) {
            $authorized_ips[] = $client_ip;
            file_put_contents($auth_ips_file, json_encode($authorized_ips));
        }
        header("Location: ?");
        exit;
    } else {
        $master_login_err = "نام کاربری یا کلمه عبور پنل نادرست است.";
    }
}

// خروج از مدیریت پنل
if (isset($_GET['action']) && $_GET['action'] === 'master_logout') {
    if (($key = array_search($client_ip, $authorized_ips)) !== false) {
        unset($authorized_ips[$key]);
        file_put_contents($auth_ips_file, json_encode(array_values($authorized_ips)));
    }
    unset($_SESSION['panel_master_auth']);
    session_destroy();
    header("Location: ?");
    exit;
}

// ---------------------------------------------------------
// ماژول پایگاه داده محلی سرورها و نمایندگان (JSON Database)
// ---------------------------------------------------------
$registry_file = __DIR__ . '/local_servers_registry.json';

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
    
    // ۱. سوپاپ قطعی عدم کاهش ترافیک مصرفی (Monotonic Non-Decreasing Traffic)
    $existing_used = floatval($existing['used_gb'] ?? 0.0);
    $incoming_used = isset($details['used_gb']) ? floatval($details['used_gb']) : 0.0;
    
    // ترافیک مصرفی همیشه برابر با حداکثر مقدار ثبت‌شده خواهد بود
    $details['used_gb'] = max($existing_used, $incoming_used);

    // ۲. محافظت از سقف حجم تخصیص‌یافته به نماینده (Data Limit GB)
    $existing_limit = floatval($existing['data_limit_gb'] ?? 0.0);
    $incoming_limit = isset($details['data_limit_gb']) ? floatval($details['data_limit_gb']) : 0.0;
    
    if ($incoming_limit <= 0 && $existing_limit > 0) {
        $details['data_limit_gb'] = $existing_limit;
    } elseif ($incoming_limit > 0) {
        $details['data_limit_gb'] = $incoming_limit;
    } else {
        $details['data_limit_gb'] = $existing_limit > 0 ? $existing_limit : 100.0;
    }

    // ۳. محاسبه دقیق و خودکار حجم باقی‌مانده (Remaining GB)
    if ($iface === 'wg0' || $details['data_limit_gb'] <= 0) {
        $details['rem_gb'] = 0.0; // اینترفیس اصلی سقف ندارد
    } else {
        $details['rem_gb'] = round(max(0.0, $details['data_limit_gb'] - $details['used_gb']), 2);
    }

    // ۴. قفل امنیتی نام کاربری (جلوگیری از تبدیل به مقادیر پیش‌فرض/خالی)
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
    if (empty($details['password_hash'])) {
        if (!empty($existing['password_hash'])) {
            $details['password_hash'] = $existing['password_hash'];
        }
    }

    // ۶. حفظ مشخصات شبکه (پورت و ساب‌نت)
    if (empty($details['port']) || $details['port'] === 'N/A' || intval($details['port']) <= 0) {
        if (!empty($existing['port']) && $existing['port'] !== 'N/A') {
            $details['port'] = $existing['port'];
        }
    }
    if (empty($details['subnet_ip']) || $details['subnet_ip'] === 'N/A') {
        if (!empty($existing['subnet_ip']) && $existing['subnet_ip'] !== 'N/A') {
            $details['subnet_ip'] = $existing['subnet_ip'];
        }
    }

    // ۷. حفظ وضعیت فعال/تعلیق و زمان تعلیق
    if (empty($details['status'])) {
        $details['status'] = $existing['status'] ?? 'active';
    }
    if (isset($existing['disabled_at']) && !isset($details['disabled_at'])) {
        $details['disabled_at'] = $existing['disabled_at'];
    }

    // ۸. ادغام امن داده‌ها و ذخیره در دیتابیس محلی
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

$p_dir = '/usr/local/bin/Wireguard-panel/src';
$d_path = $p_dir . '/db.sqlite3';
$py_bin = $p_dir . '/venv/bin/python3';
if (!file_exists($py_bin)) { $py_bin = 'python3'; }

$protocol = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off' || $_SERVER['SERVER_PORT'] == 443) ? "https://" : "http://";
$detected_webhook_url = $protocol . ($_SERVER['HTTP_HOST'] ?? 'localhost') . ($_SERVER['REQUEST_URI'] ?? '');
$detected_webhook_url = strtok($detected_webhook_url, '?');

// انجین اجرای اسکریپت‌های پایتون روی سرور
function exec_py($ssh, $py_bin, $script_code, $args = "") {
    if (!$ssh) {
        return "اتصال فعال با سرور برقرار نیست.";
    }
    $cmd_file = "/tmp/exec_cmd_" . time() . "_" . rand(1000, 9999) . ".py";
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
    return "خطای ارتباطی در اجرای اسکریپت روی سرور.";
}

function write_remote_file($ssh, $remote_path, $content) {
    $sftp = @ssh2_sftp($ssh);
    if ($sftp) {
        $sftp_path = "ssh2.sftp://" . intval($sftp) . $remote_path;
        $fh = @fopen($sftp_path, 'w');
        if ($fh) {
            @fwrite($fh, $content);
            @fclose($fh);
            return true;
        }
    }
    $b64 = base64_encode($content);
    $st = @ssh2_exec($ssh, "echo '{$b64}' | base64 -d > " . escapeshellarg($remote_path));
    if ($st) {
        stream_set_blocking($st, true);
        stream_get_contents($st);
        fclose($st);
        return true;
    }
    return false;
}

// فرآیند همگام‌سازی و پایش ترافیک
function run_traffic_sync($conn, $py_bin, $host) {
    $local_resellers_file = __DIR__ . '/resellers_rescue_backup.json';
    $local_peers_file = __DIR__ . '/peers_backup.json';

    $res_data = file_exists($local_resellers_file) ? file_get_contents($local_resellers_file) : "[]";
    $peer_data = file_exists($local_peers_file) ? file_get_contents($local_peers_file) : "[]";

    if (empty(trim($res_data))) { $res_data = "[]"; }
    if (empty(trim($peer_data))) { $peer_data = "[]"; }

    write_remote_file($conn, '/tmp/sync_resellers.json', $res_data);
    write_remote_file($conn, '/tmp/sync_peers.json', $peer_data);

$py_cron_code = <<<'PYTHON'
import sys, os, sqlite3, json, subprocess, datetime, base64, re
sys.stdout.reconfigure(line_buffering=True)

res_file = '/tmp/sync_resellers.json'
peer_file = '/tmp/sync_peers.json'

backup_map = {}
if os.path.exists(res_file):
    try:
        items = json.load(open(res_file, 'r', encoding='utf-8'))
        for item in items:
            iface = item.get('interface_name')
            if iface: backup_map[iface] = item
    except Exception as e:
        sys.stderr.write(f"Res decoding err: {e}\n")

peers_backup_map = {}
if os.path.exists(peer_file):
    try:
        items = json.load(open(peer_file, 'r', encoding='utf-8'))
        for item in items:
            pub = item.get('public_key')
            if pub: peers_backup_map[pub] = item
    except Exception as e:
        sys.stderr.write(f"Peers decoding err: {e}\n")

db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
if not os.path.exists(db_path):
    print("ERR_DB_MISSING")
    sys.exit(0)

conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()

now = datetime.datetime.now()

print("شروع فرآیند همگام‌سازی دوره‌ای و پایش ترافیک...")

try:
    cur.execute("SELECT interface_name, username, password_hash, password_plain, data_limit_gb, port, status, disabled_at FROM sub_panels")
    db_resellers = cur.fetchall()
except Exception as e_db:
    sys.exit(0)

edges = []
try:
    cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
    edges = cur.fetchall()
except: pass

updated_resellers = []
for row in db_resellers:
    iface, username, password_hash, password_plain, data_limit_gb, port, status, disabled_at_str = row
    if not iface: continue
    
    cur.execute("SELECT SUM(used) FROM peers WHERE config=?", (f"{iface}.conf",))
    live_used = cur.fetchone()[0] or 0
    try:
        cur.execute("SELECT deleted_traffic FROM sub_panels WHERE interface_name=?", (iface,))
        row_del = cur.fetchone()
        del_traffic = row_del[0] if (row_del and row_del[0]) else 0
    except:
        del_traffic = 0
        
    total_bytes = live_used + del_traffic
    used_gb = round(total_bytes / 1073741824.0, 4)
    current_bytes = total_bytes

    subnet_ip = "10.0.10.1/24"
    private_key = ""
    public_key = ""

    if iface in backup_map:
        item = backup_map[iface]
        subnet_ip = item.get('subnet_ip', subnet_ip)
        private_key = item.get('private_key', '')
        public_key = item.get('public_key', '')
    else:
        conf_path = f"/etc/wireguard/{iface}.conf"
        if os.path.exists(conf_path):
            try:
                content = open(conf_path).read()
                m_priv = re.search(r'PrivateKey\s*=\s*([^\s]+)', content, re.IGNORECASE)
                if m_priv: private_key = m_priv.group(1).strip()
                m_addr = re.search(r'Address\s*=\s*([^\s]+)', content, re.IGNORECASE)
                if m_addr: subnet_ip = m_addr.group(1).strip()
            except: pass
        if private_key:
            try:
                public_key = subprocess.check_output(f"echo '{private_key}' | wg pubkey", shell=True, text=True).strip()
            except: pass
    
    limit_val = float(data_limit_gb) if data_limit_gb else 0.0
    remaining_gb = 999999.0 if limit_val <= 0.0 else (limit_val - used_gb)

    if limit_val > 0.0 and remaining_gb <= 0 and status == 'active':
        status = 'disabled'
        disabled_at_str = now.strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(f"systemctl stop wg-quick@{iface}; wg-quick down {iface}", shell=True, stderr=subprocess.DEVNULL)
        cur.execute("UPDATE sub_panels SET status='disabled', disabled_at=? WHERE interface_name=?", (disabled_at_str, iface))
        conn.commit()
        print(f"نماینده {iface} به علت اتمام حجم معلق گردید.")
        for s_ip, s_port, s_user, s_pass in edges:
            edge_cmd = f"sqlite3 /usr/local/bin/Wireguard-panel/src/db.sqlite3 \\\"UPDATE sub_panels SET status='disabled', disabled_at='{disabled_at_str}' WHERE interface_name='{iface}';\\\"; systemctl stop wg-quick@{iface}; wg-quick down {iface}"
            subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no {s_user}@{s_ip} '{edge_cmd}'", shell=True, stderr=subprocess.DEVNULL)

    elif remaining_gb > 0 and status == 'disabled' and disabled_at_str:
        status = 'active'
        disabled_at_str = None
        subprocess.run(f"systemctl start wg-quick@{iface}; wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
        cur.execute("UPDATE sub_panels SET status='active', disabled_at=NULL WHERE interface_name=?", (iface,))
        conn.commit()
        print(f"نماینده {iface} مجدداً فعال شد.")
        for s_ip, s_port, s_user, s_pass in edges:
            edge_cmd = f"sqlite3 /usr/local/bin/Wireguard-panel/src/db.sqlite3 \\\"UPDATE sub_panels SET status='active', disabled_at=NULL WHERE interface_name='{iface}';\\\"; systemctl start wg-quick@{iface}; wg-quick up {iface}"
            subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no {s_user}@{s_ip} '{edge_cmd}'", shell=True, stderr=subprocess.DEVNULL)

    is_deleted = False
    if status in ['disabled', 'suspended'] and disabled_at_str:
        try:
            suspended_time = datetime.datetime.strptime(disabled_at_str, "%Y-%m-%d %H:%M:%S")
            diff = now - suspended_time
            if (diff.total_seconds() / 3600.0) >= 100:
                subprocess.run(f"wg-quick down {iface}", shell=True, stderr=subprocess.DEVNULL)
                subprocess.run(f"systemctl disable wg-quick@{iface}", shell=True, stderr=subprocess.DEVNULL)
                if os.path.exists(f"/etc/wireguard/{iface}.conf"):
                    os.remove(f"/etc/wireguard/{iface}.conf")
                cur.execute("DELETE FROM sub_panels WHERE interface_name=?", (iface,))
                cur.execute("DELETE FROM peers WHERE config=?", (f"{iface}.conf",))
                conn.commit()
                print(f"نماینده {iface} پس از ۱۰۰ ساعت به طور کامل پاکسازی شد.")
                for s_ip, s_port, s_user, s_pass in edges:
                    edge_cmd = f"systemctl stop wg-quick@{iface}; systemctl disable wg-quick@{iface}; rm -f /etc/wireguard/{iface}.conf"
                    subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no {s_user}@{s_ip} '{edge_cmd}'", shell=True, stderr=subprocess.DEVNULL)
                is_deleted = True
        except: pass

    if not is_deleted:
        cur.execute("UPDATE sub_panels SET status=?, disabled_at=? WHERE interface_name=?", (status, disabled_at_str, iface))
        conn.commit()
        updated_resellers.append({
            "interface_name": iface,
            "username": username,
            "password_hash": password_hash,
            "password_plain": password_plain,
            "data_limit_gb": data_limit_gb,
            "used_gb": used_gb,
            "port": port,
            "subnet_ip": subnet_ip,
            "private_key": private_key,
            "public_key": public_key,
            "status": status,
            "disabled_at": disabled_at_str,
            "last_sys_bytes": current_bytes
        })

updated_peers = []
try:
    cur.execute("SELECT peer_name, peer_ip, public_key, [limit], used, remaining_time, monitor_blocked, expiry_blocked, token, config FROM peers")
    for p in cur.fetchall():
        updated_peers.append({
            "peer_name": p[0], "peer_ip": p[1], "public_key": p[2], "limit": p[3], "used": p[4],
            "remaining_time": p[5], "monitor_blocked": p[6], "expiry_blocked": p[7], "token": p[8], "config": p[9]
        })
except: pass

conn.close()

for path in [res_file, peer_file]:
    if os.path.exists(path):
        os.remove(path)

print("فرآیند پایش تجمعی ترافیک با موفقیت به اتمام رسید.")
print("[RESELLERS_DATA]" + json.dumps(updated_resellers))
print("[PEERS_DATA]" + json.dumps(updated_peers))
PYTHON;
    $stdout = exec_py($conn, $py_bin, $py_cron_code);

    $resellers_json = ""; $peers_json = "";
    if (preg_match('/\[RESELLERS_DATA\](.*)/', $stdout, $matches)) {
        $resellers_json = trim($matches[1]);
    }
    if (preg_match('/\[PEERS_DATA\](.*)/', $stdout, $matches)) {
        $peers_json = trim($matches[1]);
    }

    if (!empty($resellers_json) && $resellers_json !== 'null') {
        file_put_contents($local_resellers_file, $resellers_json);
        
        $decoded_resellers = json_decode($resellers_json, true) ?: [];
        foreach ($decoded_resellers as $res) {
            register_local_interface($host, $res['interface_name'], [
                'interface_name' => $res['interface_name'],
                'username' => $res['username'],
                'password_plain' => $res['password_plain'] ?? '',
                'data_limit_gb' => $res['data_limit_gb'],
                'used_gb' => $res['used_gb'],
                'port' => $res['port'],
                'subnet_ip' => $res['subnet_ip'],
                'status' => $res['status']
            ]);
        }
    }
    if (!empty($peers_json) && $peers_json !== 'null') {
        file_put_contents($local_peers_file, $peers_json);
    }
    return $stdout;
}

// وب‌هوک ربات تلگرام
$webhook_input = file_get_contents('php://input');
$update = @json_decode($webhook_input, true);
if (is_array($update) && isset($update['update_id'])) {
    if (isset($update['message']['text'])) {
        $chat_id = $update['message']['chat']['id'];
        $text = trim($update['message']['text']);
        $config_raw = @file_get_contents("{$p_dir}/telegram_bot_config.json");
        if ($config_raw) {
            $conf = json_decode($config_raw, true);
            $bot_token = $conf['t'] ?? '';
            if (!empty($bot_token) && $text === '/start') {
                $reply = "ربات پایش هوشمند فعال است. پشتیبان‌ها هر ۶ ساعت ارسال خواهند شد.";
                @file_get_contents("https://api.telegram.org/bot{$bot_token}/sendMessage?chat_id={$chat_id}&text=" . urlencode($reply));
            }
        }
    }
    exit;
}

// ---------------------------------------------------------
// سیستم مدیریت سرورهای ذخیره شده (Fast Login Vault)
// ---------------------------------------------------------
$saved_masters_file = __DIR__ . '/.saved_masters.php';

function get_saved_masters() {
    global $saved_masters_file;
    if (file_exists($saved_masters_file)) {
        $raw = file_get_contents($saved_masters_file);
        $json = str_replace('<?php die(); ?>', '', $raw);
        return json_decode($json, true) ?: [];
    }
    return [];
}

function save_master_server($h, $p, $u, $pw) {
    global $saved_masters_file;
    $servers = get_saved_masters();
    $servers[$h] = [
        'h' => $h, 
        'p' => intval($p), 
        'u' => $u, 
        'pw' => base64_encode($pw)
    ];
    file_put_contents($saved_masters_file, '<?php die(); ?>' . json_encode($servers));
}

function remove_saved_master($h) {
    global $saved_masters_file;
    $servers = get_saved_masters();
    if (isset($servers[$h])) {
        unset($servers[$h]);
        file_put_contents($saved_masters_file, '<?php die(); ?>' . json_encode($servers));
    }
}

// ورود سریع
if ($is_panel_authenticated && isset($_POST['action']) && $_POST['action'] == 'fast_login') {
    $fast_h = $_POST['fast_host'] ?? '';
    $servers = get_saved_masters();
    if (isset($servers[$fast_h])) {
        $_SESSION['sh'] = $servers[$fast_h]['h'];
        $_SESSION['sp'] = $servers[$fast_h]['p'];
        $_SESSION['su'] = $servers[$fast_h]['u'];
        $_SESSION['spw'] = base64_decode($servers[$fast_h]['pw']);
        
        $secure_config = [
            'h' => $_SESSION['sh'], 'p' => $_SESSION['sp'],
            'u' => $_SESSION['su'], 'pw' => $_SESSION['spw']
        ];
        file_put_contents(__DIR__ . '/.ssh_config.php', '<?php die(); ?>' . json_encode($secure_config));
    }
    header("Location: ?");
    exit;
}

// حذف سرور ذخیره شده
if ($is_panel_authenticated && isset($_POST['action']) && $_POST['action'] == 'delete_saved_master') {
    $del_h = $_POST['del_host'] ?? '';
    remove_saved_master($del_h);
    header("Location: ?");
    exit;
}

$err = ""; 
$in = false;
$conn = null;

$h = $_SESSION['sh'] ?? '';
$p = $_SESSION['sp'] ?? 22;
$u = $_SESSION['su'] ?? '';
$pw = $_SESSION['spw'] ?? '';

if (empty($h) && file_exists(__DIR__ . '/.ssh_config.php')) {
    $raw = @file_get_contents(__DIR__ . '/.ssh_config.php');
    if ($raw) {
        $json = str_replace('<?php die(); ?>', '', $raw);
        $secure_config = json_decode($json, true);
        if (is_array($secure_config) && !empty($secure_config['h'])) {
            $_SESSION['sh'] = $h = $secure_config['h'];
            $_SESSION['sp'] = $p = intval($secure_config['p'] ?? 22);
            $_SESSION['su'] = $u = $secure_config['u'] ?? 'root';
            $_SESSION['spw'] = $pw = $secure_config['pw'] ?? '';
        }
    }
}

if ($is_panel_authenticated && isset($_POST['action']) && $_POST['action'] == 'login') {
    $_SESSION['sh'] = trim($_POST['host'] ?? '');
    $_SESSION['sp'] = intval($_POST['port'] ?? 22);
    $_SESSION['su'] = trim($_POST['username'] ?? '');
    $_SESSION['spw'] = $_POST['password'] ?? '';
    
    $secure_config = [
        'h' => $_SESSION['sh'], 'p' => $_SESSION['sp'],
        'u' => $_SESSION['su'], 'pw' => $_SESSION['spw']
    ];
    file_put_contents(__DIR__ . '/.ssh_config.php', '<?php die(); ?>' . json_encode($secure_config));
    
    if (isset($_POST['rem']) && $_POST['rem'] == 'yes') {
        save_master_server($_SESSION['sh'], $_SESSION['sp'], $_SESSION['su'], $_SESSION['spw']);
    }
    
    header("Location: ?");
    exit;
}

if (isset($_GET['action']) && $_GET['action'] == 'logout') {
    unset($_SESSION['sh']);
    unset($_SESSION['sp']);
    unset($_SESSION['su']);
    unset($_SESSION['spw']);
    @unlink(__DIR__ . '/.ssh_config.php');
    header("Location: ?");
    exit;
}

if (isset($_POST['action']) && $_POST['action'] === 'keep_alive') {
    $_SESSION['last_active'] = time();
    die('OK');
}

if ($is_panel_authenticated && !empty($h) && !empty($u) && !empty($pw)) {
    if (!function_exists('ssh2_connect')) {
        $err = "افزونه SSH2 روی هاست شما نصب نیست.";
    } else {
        $conn = @ssh2_connect($h, $p);
        if (!$conn) {
            $err = "امکان اتصال به سرور مبدا وجود ندارد.";
        } else {
            if (!@ssh2_auth_password($conn, $u, $pw)) {
                $err = "اطلاعات ورود سرور مبدا اشتباه است.";
            } else {
                $in = true;
                $reg = get_local_registry();
                if (!isset($reg[$h])) {
                    $reg[$h] = ['host' => $h, 'interfaces' => []];
                    save_local_registry($reg);
                }
            }
        }
    }
}

// ---------------------------------------------------------
// هندلر پردازش آپلود و استخراج مستقیم بکاپ فیزیکی
// ---------------------------------------------------------
if ($in && isset($_FILES['backup_file'])) {
    $file = $_FILES['backup_file'];
    if ($file['error'] === UPLOAD_ERR_OK) {
        $tmp_local = __DIR__ . '/manual_temp_backup.zip';
        if (move_uploaded_file($file['tmp_name'], $tmp_local)) {
            $sftp = @ssh2_sftp($conn);
            if ($sftp) {
                $remote_zip = '/tmp/uploaded_manual_backup.zip';
                $src = fopen($tmp_local, 'r');
                $dest = fopen("ssh2.sftp://" . intval($sftp) . $remote_zip, 'w');
                if ($src && $dest) {
                    stream_copy_to_stream($src, $dest);
                    fclose($src); fclose($dest);
                    unlink($tmp_local);
                    
                    $py_restore = <<<'PYTHON'
import os, sys, zipfile, shutil, subprocess

zip_path = '/tmp/uploaded_manual_backup.zip'
target_dir = '/usr/local/bin/Wireguard-panel/src'
wg_dir = '/etc/wireguard'
extract_tmp = '/tmp/manual_backup_extract'

print("شروع فرآیند بازیابی بک‌آپ فیزیکی...")

if not os.path.exists(zip_path):
    print("خطا: فایل بک‌آپ بر روی سرور ریموت لینوکس یافت نشد.")
    sys.exit(1)

if os.path.exists(extract_tmp):
    shutil.rmtree(extract_tmp)
os.makedirs(extract_tmp, exist_ok=True)

try:
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(extract_tmp)

    for root, dirs, files in os.walk(extract_tmp):
        for f in files:
            full_p = os.path.join(root, f)
            if f == 'db.sqlite3':
                shutil.copy2(full_p, os.path.join(target_dir, 'db.sqlite3'))
            elif f == 'config.yaml':
                shutil.copy2(full_p, os.path.join(target_dir, 'config.yaml'))
            elif f == 'short_links.json':
                shutil.copy2(full_p, os.path.join(target_dir, 'short_links.json'))

    wg_source_dir = None
    for root, dirs, files in os.walk(extract_tmp):
        if os.path.basename(root) in ['wireguard', 'etc/wireguard']:
            wg_source_dir = root
            break
            
    if wg_source_dir:
        for f in os.listdir(wg_source_dir):
            if f.endswith('.conf'):
                shutil.copy2(os.path.join(wg_source_dir, f), os.path.join(wg_dir, f))
    else:
        for root, dirs, files in os.walk(extract_tmp):
            for f in files:
                if f.endswith('.conf') and 'wg0.conf' not in f:
                    shutil.copy2(os.path.join(root, f), os.path.join(wg_dir, f))

    subprocess.run("systemctl restart wireguard-panel", shell=True)
    print("فرآیند بازیابی بک‌آپ با موفقیت به پایان رسید.")
    
    shutil.rmtree(extract_tmp)
    os.remove(zip_path)
except Exception as e:
    print(f"خطا در استخراج و بازیابی: {e}")
PYTHON;
                    $reseller_log = exec_py($conn, $py_bin, $py_restore);
                    $sync_out = run_traffic_sync($conn, $py_bin, $h);
                    $reseller_log .= "\n[LOCAL SYNC PROCESS]\n" . $sync_out;
                }
            }
        }
    }
}

$h_v = $_COOKIE['rh'] ?? '';
$p_v = $_COOKIE['rp'] ?? '22';
$u_v = $_COOKIE['ru'] ?? 'root';
$pw_v = $_COOKIE['rpw'] ?? '';
function fb($b) {
    if (!is_numeric($b) || $b <= 0) return '۰ مگابایت';
    if ($b >= 1073741824) return number_format($b / 1073741824, 2) . ' گیگابایت';
    if ($b >= 1048576) return number_format($b / 1048576, 2) . ' مگابایت';
    return number_format($b / 1024, 2) . ' کیلوبایت';
}

$t_logs = "";
$detailed_migration_log = ""; 
$sync_log = ""; 
$gaming_log = "";
$reseller_log = "";
$b_on = false;
$s_tok = "";
$s_cid = "";

if ($in) {
    $sc = @ssh2_exec($conn, "ps aux | grep 'telegram_bot_poll.py' | grep -v grep");
    if ($sc) {
        stream_set_blocking($sc, true);
        if (trim(stream_get_contents($sc)) !== "") {
            $b_on = true;
        }
        fclose($sc);
    }

    $sc2 = @ssh2_exec($conn, "cat {$p_dir}/telegram_bot_config.json 2>/dev/null");
    if ($sc2) {
        stream_set_blocking($sc2, true);
        $cj = trim(stream_get_contents($sc2));
        fclose($sc2);
        if (!empty($cj)) {
            $cd = json_decode($cj, true);
            if ($cd) {
                $s_tok = $cd['t'] ?? '';
                $s_cid = $cd['c'] ?? '';
            }
        }
    }
}

if ($in && isset($_POST['action'])) {
    $act = $_POST['action'];

    // ۱. حذف کامل نماینده (Delete Reseller)
    if ($act == 'delete_reseller') {
        $del_iface = trim($_POST['del_iface'] ?? '');
        if (!empty($del_iface) && $del_iface != 'wg0') {
            $py_delete = <<<'PYTHON'
import sqlite3, subprocess, os, sys
sys.stdout.reconfigure(line_buffering=True)
iface = "###IFACE###"
cfg_file = f"{iface}.conf"
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

print(f"شروع عملیات حذف فیزیکی نماینده {iface}...")
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
try:
    subprocess.run(f"wg-quick down {iface} 2>/dev/null", shell=True)
    subprocess.run(f"systemctl stop wg-quick@{iface} 2>/dev/null", shell=True)
    subprocess.run(f"systemctl disable wg-quick@{iface} 2>/dev/null", shell=True)
    if os.path.exists(f"/etc/wireguard/{cfg_file}"): 
        os.remove(f"/etc/wireguard/{cfg_file}")
    
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

    # 📌 همگام‌سازی و حذف قطعی از تمام Nodeها
    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_reseller_state_to_edges(iface, "delete", wait=True)
    except Exception as ex_sync:
        print(f"Sync delete notice: {ex_sync}")

    print(f"نماینده {iface} و کلیه کلاینت‌های آن در Master و Nodeها پاکسازی شدند.")
except Exception as e: 
    print(f"خطا در حذف نماینده: {e}")
PYTHON;
            
            $py_delete = str_replace('###IFACE###', $del_iface, $py_delete);
            $reseller_log = exec_py($conn, $py_bin, $py_delete);
            remove_local_interface($h, $del_iface);
            @ssh2_exec($conn, "systemctl restart wireguard-panel");
            $sync_out = run_traffic_sync($conn, $py_bin, $h);
            $reseller_log .= "\n[LOCAL SYNC PROCESS]\n" . $sync_out;
        }
    }

    // ۲. تمدید / افزایش حجم نماینده (Extend Reseller)
    if ($act == 'extend_reseller') {
        $ext_iface = trim($_POST['ext_iface'] ?? '');
        $ext_add_gb = intval($_POST['ext_add_gb'] ?? 100);
        if (!empty($ext_iface) && $ext_add_gb > 0) {
            $py_extend = <<<PYTHON
import sqlite3, subprocess, os, sys
sys.stdout.reconfigure(line_buffering=True)
iface = "{$ext_iface}"
add_gb = {$ext_add_gb}
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

print(f"شروع عملیات تمدید ترافیک {iface}...")
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
try:
    cur.execute("UPDATE sub_panels SET data_limit_gb = data_limit_gb + ?, status='active', disabled_at=NULL, alert_80_sent=0, alert_100_sent=0 WHERE interface_name=?", (add_gb, iface))
    conn.commit()
    conn.close()
    
    subprocess.run(f"systemctl start wg-quick@{iface}; wg-quick up {iface} 2>/dev/null", shell=True, stderr=subprocess.DEVNULL)
    
    # 📌 اعمال تمدید و فعال‌سازی اینترفیس در Node
    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_reseller_state_to_edges(iface, "extend", wait=True)
    except Exception as ex_sync:
        print(f"Sync extend notice: {ex_sync}")

    print(f"ترافیک نماینده {iface} به میزان {add_gb}GB افزایش یافت و در Nodeها فعال شد.")
except Exception as e: 
    print(f"خطا در تمدید: {e}")
PYTHON;
            $reseller_log = exec_py($conn, $py_bin, $py_extend);
            $sync_out = run_traffic_sync($conn, $py_bin, $h);
            $reseller_log .= "\n[LOCAL SYNC PROCESS]\n" . $sync_out;
        }
    }

    // ۳. کسر حجم نماینده (Deduct Reseller) به همراه بررسی اتوماتیک سقف مصرف
    if ($act == 'deduct_reseller') {
        $deduct_iface = trim($_POST['deduct_iface'] ?? '');
        $deduct_sub_gb = intval($_POST['deduct_sub_gb'] ?? 10);
        if (!empty($deduct_iface) && $deduct_sub_gb > 0) {
            $py_deduct = <<<PYTHON
import sqlite3, subprocess, os, sys, datetime
sys.stdout.reconfigure(line_buffering=True)
iface = "{$deduct_iface}"
sub_gb = {$deduct_sub_gb}
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
try:
    cur.execute("UPDATE sub_panels SET data_limit_gb = MAX(0.0, data_limit_gb - ?) WHERE interface_name=?", (sub_gb, iface))
    
    # بررسی عبور مصرف از سقف جدید
    cur.execute("SELECT data_limit_gb, deleted_traffic FROM sub_panels WHERE interface_name=?", (iface,))
    row_sp = cur.fetchone()
    limit_val = float(row_sp[0] or 0.0)
    del_val = int(row_sp[1] or 0)

    cur.execute("SELECT SUM(used) FROM peers WHERE config=? OR config=?", (f"{iface}.conf", iface))
    live_used = cur.fetchone()[0] or 0
    total_used_gb = (live_used + del_val) / 1073741824.0

    if total_used_gb >= limit_val:
        cur.execute("UPDATE sub_panels SET status='disabled', disabled_at=? WHERE interface_name=?", (now_str, iface))
        subprocess.run(f"systemctl stop wg-quick@{iface}; wg-quick down {iface} 2>/dev/null", shell=True, stderr=subprocess.DEVNULL)
        print(f"مصرف نماینده ({total_used_gb:.2f}GB) از سقف جدید ({limit_val:.2f}GB) فراتر رفت؛ سرویس مسدود شد.")

    conn.commit()
    conn.close()

    # 📌 اعمال کسر حجم و تطبیق وضعیت کارت شبکه در Node
    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_reseller_state_to_edges(iface, "edit", wait=True)
    except Exception as ex_sync:
        print(f"Sync deduct notice: {ex_sync}")

    print("کسر ترافیک اعمال و وضعیت نماینده در Node همگام‌سازی شد.")
except Exception as e: 
    print(f"خطا در کسر حجم: {e}")
PYTHON;
            $reseller_log = exec_py($conn, $py_bin, $py_deduct);
            $sync_out = run_traffic_sync($conn, $py_bin, $h);
            $reseller_log .= "\n[LOCAL SYNC PROCESS]\n" . $sync_out;
        }
    }

    // ۴. تعلیق / فعال‌سازی نماینده (Toggle Reseller)
    if ($act == 'toggle_reseller') {
        $t_iface = trim($_POST['t_iface'] ?? '');
        $t_status = trim($_POST['t_status'] ?? 'active');
        if (!empty($t_iface)) {
            $py_update_status = <<<PYTHON
import sys, sqlite3, datetime, os, subprocess
sys.stdout.reconfigure(line_buffering=True)
iface = "{$t_iface}"
status = "{$t_status}"
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
try:
    if status == 'active':
        subprocess.run(f"systemctl stop wg-quick@{iface}; wg-quick down {iface} 2>/dev/null", shell=True, stderr=subprocess.DEVNULL)
        cur.execute("UPDATE sub_panels SET status='suspended', disabled_at=? WHERE interface_name=?", (now_str, iface))
        print(f"اینترفیس {iface} در Master متوقف و معلق گردید.")
    else:
        cur.execute("UPDATE sub_panels SET status='active', disabled_at=NULL, alert_100_sent=0 WHERE interface_name=?", (iface,))
        subprocess.run(f"systemctl start wg-quick@{iface}; wg-quick up {iface} 2>/dev/null", shell=True, stderr=subprocess.DEVNULL)
        print(f"اینترفیس {iface} در Master فعال و روشن گردید.")
    
    conn.commit()
    conn.close()

    # 📌 کنترل بلادرنگ کارت شبکه و وضعیت در Node متناسب با Master
    try:
        import v100_master_edge_sync
        v100_master_edge_sync.sync_reseller_state_to_edges(iface, "toggle", wait=True)
    except Exception as ex_sync:
        print(f"Sync toggle notice: {ex_sync}")

except Exception as e: 
    print(f"خطا در تغییر وضعیت: {e}")
PYTHON;
            $reseller_log = exec_py($conn, $py_bin, $py_update_status);
            $sync_out = run_traffic_sync($conn, $py_bin, $h);
            $reseller_log .= "\n[LOCAL SYNC PROCESS]\n" . $sync_out;
        }
    }

    // ۵. تغییر نام کاربری نماینده (Change Username)
    if ($act == 'change_reseller_username') {
        $cp_iface = trim($_POST['cp_iface'] ?? '');
        $new_username = trim($_POST['new_username'] ?? '');
        
        if (!empty($cp_iface) && !empty($new_username)) {
            $py_change_username = <<<PYTHON
import sys, sqlite3, os
sys.stdout.reconfigure(line_buffering=True)
iface = "{$cp_iface}"
new_user = "{$new_username}"
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
try:
    if iface == 'wg0':
        cur.execute("SELECT id FROM users WHERE username=?", (new_user,))
        if cur.fetchone():
            print("خطا: این نام کاربری قبلاً در ادمین ثبت شده است.")
            sys.exit(0)
        cur.execute("UPDATE users SET username=?", (new_user,))
        print(f"نام کاربری مدیرکل به '{new_user}' تغییر یافت.")
    else:
        cur.execute("SELECT interface_name FROM sub_panels WHERE username=? AND interface_name != ?", (new_user, iface))
        if cur.fetchone():
            print("خطا: این نام کاربری قبلاً رزرو شده است.")
            sys.exit(0)
        cur.execute("UPDATE sub_panels SET username=? WHERE interface_name=?", (new_user, iface))
        print(f"نام کاربری نماینده {iface} به '{new_user}' تغییر یافت.")
        
    conn.commit()
    conn.close()

    # 📌 همگام‌سازی نام کاربری جدید روی همان اینترفیس در Node
    if iface != 'wg0':
        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_reseller_state_to_edges(iface, "edit", wait=True)
        except Exception as ex_sync:
            print(f"Sync username notice: {ex_sync}")

except Exception as e: 
    print(f"خطا در تغییر نام کاربری: {e}")
PYTHON;
            $reseller_log = exec_py($conn, $py_bin, $py_change_username);
            register_local_interface($h, $cp_iface, ['username' => $new_username]);
            $sync_out = run_traffic_sync($conn, $py_bin, $h);
            $reseller_log .= "\n[LOCAL SYNC PROCESS]\n" . $sync_out;
        }
    }

    // ۶. تغییر رمز عبور نماینده یا ادمین (Change Password)
    if ($act == 'change_reseller_pw') {
        $cp_iface = trim($_POST['cp_iface'] ?? ''); 
        $cp_user = trim($_POST['cp_user'] ?? ''); 
        $cp_pass1 = trim($_POST['cp_pass1'] ?? ''); 
        $cp_pass2 = trim($_POST['cp_pass2'] ?? '');
        
        if ($cp_pass1 !== $cp_pass2) {
            $reseller_log = "خطا: تکرار کلمه عبور همخوانی ندارد.";
        } else {
            $py_changepw = <<<PYTHON
import sys, sqlite3, os
sys.stdout.reconfigure(line_buffering=True)
from werkzeug.security import generate_password_hash
iface = "{$cp_iface}"
user = "{$cp_user}"
new_pw = "{$cp_pass1}"
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
try:
    hashed = generate_password_hash(new_pw)
    if iface == 'wg0':
        cur.execute("UPDATE users SET password_hash=?, password_plain=?", (hashed, new_pw))
        print("کلمه عبور ادمین اصلی پنل تغییر یافت.")
    else:
        cur.execute("UPDATE sub_panels SET password_hash=?, password_plain=? WHERE interface_name=?", (hashed, new_pw, iface))
        print(f"کلمه عبور نماینده {iface} با موفقیت تغییر یافت.")
        
    conn.commit()
    conn.close()

    # 📌 همگام‌سازی کلمه عبور جدید (هش و متن ساده) روی همان اینترفیس در Node
    if iface != 'wg0':
        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_reseller_state_to_edges(iface, "edit", wait=True)
        except Exception as ex_sync:
            print(f"Sync password notice: {ex_sync}")

except Exception as e: 
    print(f"خطا در تغییر رمز عبور: {e}")
PYTHON;
            $reseller_log = exec_py($conn, $py_bin, $py_changepw);
            register_local_interface($h, $cp_iface, [
                'username' => $cp_user,
                'password_plain' => $cp_pass1
            ]);
            $sync_out = run_traffic_sync($conn, $py_bin, $h);
            $reseller_log .= "\n[LOCAL SYNC PROCESS]\n" . $sync_out;
        }
    }

if ($act == 'create_reseller') {
        $r_iface = trim($_POST['r_iface'] ?? ''); 
        $r_limit = intval($_POST['r_limit'] ?? 100);
        $r_user  = trim($_POST['r_user'] ?? ''); 
        $r_pass  = trim($_POST['r_pass'] ?? '');
        
        $py_reseller_creator = <<<PYTHON
import sys, sqlite3, subprocess, re, json, base64, os
sys.stdout.reconfigure(line_buffering=True)
from werkzeug.security import generate_password_hash

iface = "{$r_iface}".lower().strip()
limit_gb = {$r_limit}
username = "{$r_user}".strip()
password = "{$r_pass}".strip()
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    
    # ۱. بررسی تکراری نبودن نام کاربری یا اینترفیس
    cur.execute("CREATE TABLE IF NOT EXISTS sub_panels (id INTEGER PRIMARY KEY AUTOINCREMENT, interface_name TEXT UNIQUE, username TEXT UNIQUE, password_hash TEXT, data_limit_gb REAL, port INTEGER, created_at TEXT, status TEXT, disabled_at TEXT, password_plain TEXT, deleted_traffic INTEGER DEFAULT 0, alert_80_sent INTEGER DEFAULT 0, alert_100_sent INTEGER DEFAULT 0, telegram_chat_id TEXT DEFAULT '', telegram_bot_token TEXT DEFAULT '', telegram_bot_status TEXT DEFAULT 'off', bot_base_url TEXT DEFAULT '');")
    cur.execute("SELECT id FROM sub_panels WHERE username=? OR interface_name=?", (username, iface))
    if cur.fetchone():
        print("خطا: این نام کاربری یا اینترفیس قبلاً تعریف شده است.")
        sys.exit(0)

    # ۲. استخراج شماره N و محاسبه دقیق ساب‌نت و پورت
    m_num = re.search(r'\d+', iface)
    iface_num = int(m_num.group(0)) if m_num else 1
    iface = f"wg{iface_num}"
    new_subnet = f"10.{iface_num}.0.1/16"
    port = 51820 + iface_num

    # ۳. تولید کلید اختصاصی و فایل کانفیگ روی سرور مستر
    priv_key = subprocess.check_output("wg genkey", shell=True, text=True).strip()
    conf_path = f"/etc/wireguard/{iface}.conf"
    main_nic = subprocess.getoutput("ip route | grep default | awk '{print $5}' | head -n1").strip() or "eth0"
    
    conf = (
        f"[Interface]\\n"
        f"Address = {new_subnet}\\n"
        f"SaveConfig = false\\n"
        f"ListenPort = {port}\\n"
        f"PrivateKey = {priv_key}\\n"
        f"PostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -A FORWARD -o {iface} -j ACCEPT; iptables -I FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -A POSTROUTING -o {main_nic} -j MASQUERADE\\n"
        f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -D FORWARD -o {iface} -j ACCEPT; iptables -D FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -D POSTROUTING -o {main_nic} -j MASQUERADE\\n"
    )
        
    with open(conf_path, 'w', encoding='utf-8') as f: 
        f.write(conf)

    # ۴. ذخیره در دیتابیس مستر
    hashed_pw = generate_password_hash(password)
    cur.execute("""
        INSERT INTO sub_panels (
            interface_name, username, password_hash, data_limit_gb, port, 
            created_at, status, password_plain
        ) VALUES (?, ?, ?, ?, ?, datetime('now'), 'active', ?)
    """, (iface, username, hashed_pw, limit_gb, port, password))
    conn.commit()
    
    # ۵. راه‌اندازی کارت شبکه در مستر
    subprocess.run("systemctl daemon-reload", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"systemctl enable wg-quick@{iface}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"systemctl restart wg-quick@{iface}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
    
    print(f"[RESELLER_ADDED_META]{iface}|{username}|{password}|{limit_gb}|{port}|{new_subnet}")

    # ۶. بررسی، ساخت خودکار کلید مجزا، انطباق ساب‌نت و راه‌اندازی در تمام نودها (Edge)
    cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
    edges = cur.fetchall()
    conn.close()

    if edges:
        if os.system("which sshpass >/dev/null 2>&1") != 0:
            os.system("apt-get update -y && apt-get install -y sshpass")
            
        for s_ip, s_port, s_user, s_pass in edges:
            edge_script = f'''import os, subprocess, sqlite3, re

iface = "{iface}"
target_subnet = "{new_subnet}"
target_port = {port}
conf_path = f"/etc/wireguard/{{iface}}.conf"

needs_rebuild = False

if not os.path.exists(conf_path):
    needs_rebuild = True
    priv = subprocess.getoutput("wg genkey").strip()
    nic = subprocess.getoutput("ip route | grep default | awk '{{print $5}}' | head -n1").strip() or "eth0"
    c = (
        f"[Interface]\\n"
        f"PrivateKey = {{priv}}\\n"
        f"ListenPort = {{target_port}}\\n"
        f"Address = {{target_subnet}}\\n"
        f"SaveConfig = false\\n"
        f"PostUp = iptables -A FORWARD -i {{iface}} -j ACCEPT; iptables -t nat -A POSTROUTING -o {{nic}} -j MASQUERADE\\n"
        f"PostDown = iptables -D FORWARD -i {{iface}} -j ACCEPT; iptables -t nat -D POSTROUTING -o {{nic}} -j MASQUERADE\\n"
    )
    with open(conf_path, "w", encoding="utf-8") as cf:
        cf.write(c)
else:
    try:
        with open(conf_path, "r", encoding="utf-8", errors="ignore") as cf:
            txt = cf.read()
        m_addr = re.search(r'(?i)Address\\s*=\\s*([^\\n]+)', txt)
        m_p = re.search(r'(?i)ListenPort\\s*=\\s*(\\d+)', txt)
        if (not m_addr or m_addr.group(1).strip() != target_subnet) or (not m_p or int(m_p.group(1).strip()) != target_port):
            needs_rebuild = True
            txt = re.sub(r'(?i)Address\\s*=\\s*[^\\n]+', f'Address = {{target_subnet}}', txt)
            txt = re.sub(r'(?i)ListenPort\\s*=\\s*\\d+', f'ListenPort = {{target_port}}', txt)
            with open(conf_path, "w", encoding="utf-8") as cf:
                cf.write(txt)
    except Exception:
        pass

db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
os.makedirs(os.path.dirname(db_path), exist_ok=True)
conn_e = sqlite3.connect(db_path, timeout=10.0)
cur_e = conn_e.cursor()
cur_e.execute("CREATE TABLE IF NOT EXISTS sub_panels (id INTEGER PRIMARY KEY AUTOINCREMENT, interface_name TEXT UNIQUE, username TEXT UNIQUE, password_hash TEXT, data_limit_gb REAL, port INTEGER, created_at TEXT, status TEXT, disabled_at TEXT, password_plain TEXT, deleted_traffic INTEGER DEFAULT 0);")
cur_e.execute("""
    INSERT OR REPLACE INTO sub_panels (
        interface_name, username, password_hash, data_limit_gb, port, created_at, status, password_plain, deleted_traffic
    ) VALUES (?, ?, ?, ?, ?, datetime('now'), 'active', ?, 0)
""", ("{iface}", "{username}", "{hashed_pw}", {limit_gb}, {port}, "{password}"))
conn_e.commit()
conn_e.close()

subprocess.run("systemctl daemon-reload", shell=True, stderr=subprocess.DEVNULL)
subprocess.run(f"systemctl enable wg-quick@{{iface}}", shell=True, stderr=subprocess.DEVNULL)
if needs_rebuild:
    subprocess.run(f"wg-quick down {{iface}} 2>/dev/null", shell=True)
subprocess.run(f"systemctl restart wg-quick@{{iface}}", shell=True, stderr=subprocess.DEVNULL)
subprocess.run(f"wg-quick up {{iface}} 2>/dev/null", shell=True)
'''
            enc = base64.b64encode(edge_script.encode('utf-8')).decode('utf-8')
            cmd = f"echo '{enc}' | base64 -d > /tmp/ae.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/ae.py && rm -f /tmp/ae.py"
            subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port or 22} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{cmd}\"", shell=True)
            
    print("نماینده با موفقیت ایجاد و روی تمام نودها همگام‌سازی شد.")
except Exception as e: 
    print(f"خطا: {e}")
finally: 
    if 'conn' in locals() and conn:
        try: conn.close()
        except: pass
PYTHON;

        $reseller_log = exec_py($conn, $py_bin, $py_reseller_creator);
        
        if (preg_match('/\[RESELLER_ADDED_META\](.*)/', $reseller_log, $matches)) {
            $meta = explode('|', trim($matches[1]));
            if (count($meta) >= 6) {
                register_local_interface($h, $meta[0], [
                    'interface_name' => $meta[0],
                    'username'       => $meta[1],
                    'password_plain' => $meta[2],
                    'data_limit_gb'  => floatval($meta[3]),
                    'port'           => intval($meta[4]),
                    'subnet_ip'      => $meta[5],
                    'used_gb'        => 0.0,
                    'status'         => 'active'
                ]);
            }
        }
        $sync_out = run_traffic_sync($conn, $py_bin, $h);
        $reseller_log .= "\n[LOCAL SYNC PROCESS]\n" . $sync_out;
        $_POST['action'] = 'audit_resellers';
    }
    // ممیزی نمایندگان
    if ($act == 'audit_resellers') {
        $reg = get_local_registry();
        $server_data = $reg[$h] ?? ['interfaces' => []];
        $local_rescue_interfaces = [];
        
        foreach ($server_data['interfaces'] as $iface => $det) {
            $local_rescue_interfaces[] = $det;
        }

        write_remote_file($conn, '/tmp/audit_rescue.json', json_encode($local_rescue_interfaces));

        $py_audit = <<<'PYTHON'
import sys, os, sqlite3, json, subprocess, base64, re, secrets
sys.stdout.reconfigure(line_buffering=True)
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
rescue_file = '/tmp/audit_rescue.json'
py_bin_path = "/usr/local/bin/Wireguard-panel/src/venv/bin/python3"
links_path = "/usr/local/bin/Wireguard-panel/src/short_links.json"

rescue_list = []
if os.path.exists(rescue_file):
    try: rescue_list = json.load(open(rescue_file, 'r', encoding='utf-8'))
    except Exception as e: pass

print("شروع ممیزی عمیق و بازیابی پایداری...")

if not os.path.exists(db_path):
    print("خطا: دیتابیس پنل یافت نشد.")
    sys.exit(1)

subprocess.run("rm -rf /tmp/master_*.json /tmp/*.py", shell=True, stderr=subprocess.DEVNULL)

conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
recovered_logs = []
synced_resellers_for_ui = []

try:
    cur.execute('''CREATE TABLE IF NOT EXISTS sub_panels (
        id INTEGER PRIMARY KEY AUTOINCREMENT, interface_name TEXT UNIQUE, username TEXT UNIQUE,
        password_hash TEXT, data_limit_gb REAL, port INTEGER, created_at TEXT, status TEXT,
        disabled_at TEXT, password_plain TEXT, deleted_traffic INTEGER DEFAULT 0
    )''')
    cur.execute("CREATE TABLE IF NOT EXISTS peer_synced_edges (peer_name TEXT, server_ip TEXT, config TEXT, edge_ip TEXT, UNIQUE(peer_name, server_ip, config))")

    cur.execute("PRAGMA table_info(peer_synced_edges)")
    cols = [col[1] for col in cur.fetchall()]
    if "edge_ip" not in cols:
        try: cur.execute("ALTER TABLE peer_synced_edges ADD COLUMN edge_ip TEXT")
        except: pass
    conn.commit()

    main_nic = subprocess.getoutput("ip route | grep default | awk '{print $5}' | head -n1").strip()
    used_subs = set()
    if os.path.exists('/etc/wireguard'):
        for f in os.listdir('/etc/wireguard'):
            if f.endswith('.conf'):
                try:
                    txt = open(f"/etc/wireguard/{f}", 'r').read()
                    m = re.search(r"Address\s*=\s*(10\.0\.\d+)\.", txt, re.IGNORECASE)
                    if m: used_subs.add(int(m.group(1)))
                except: pass

    for conf_file in os.listdir('/etc/wireguard'):
        if conf_file.endswith('.conf') and conf_file != 'wg0.conf':
            c_path = os.path.join('/etc/wireguard', conf_file)
            iface = conf_file.replace('.conf', '')
            with open(c_path, 'r') as f: txt = f.read()
            
            if main_nic and "RELATED,ESTABLISHED" not in txt:
                txt = re.sub(r'(?im)^PostUp\s*=.*$', '', txt)
                txt = re.sub(r'(?im)^PostDown\s*=.*$', '', txt)
                parts = txt.split('[Peer]', 1)
                i_sec = parts[0].strip()
                p_sec = "\n[Peer]" + parts[1] if len(parts) > 1 else ""
                
                postup = f"PostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -A FORWARD -o {iface} -j ACCEPT; iptables -I FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -A POSTROUTING -o {main_nic} -j MASQUERADE"
                postdown = f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -D FORWARD -o {iface} -j ACCEPT; iptables -D FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -D POSTROUTING -o {main_nic} -j MASQUERADE"
                
                with open(c_path, 'w') as f: f.write(f"{i_sec}\n{postup}\n{postdown}\n{p_sec}")
                subprocess.run(f"wg-quick down {iface}; wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
                recovered_logs.append(f"پایدارسازی فایروال اینترفیس {iface}")

    from werkzeug.security import generate_password_hash
    for r_item in rescue_list:
        try:
            iface = r_item.get('interface_name')
            if not iface or iface == 'wg0': continue
            
            cur.execute("SELECT username, password_plain, data_limit_gb, port, status FROM sub_panels WHERE interface_name=?", (iface,))
            db_row = cur.fetchone()
            
            req_username = r_item.get('username')
            req_password = r_item.get('password_plain')
            
            if db_row:
                if not req_username or req_username in ['بدون نماینده (پیش‌فرض)', 'N/A', '']:
                    req_username = db_row[0]
                if not req_password or req_password in ['N/A', '']:
                    req_password = db_row[1]
            
            if not req_username or req_username in ['بدون نماینده (پیش‌فرض)', 'N/A', '']:
                req_username = f"Reseller_{iface}"
            if not req_password or req_password in ['N/A', '']:
                req_password = "Pars123@"
                
            final_username = req_username
            final_password = req_password
            
            cur.execute("SELECT interface_name FROM sub_panels WHERE username=? AND interface_name != ?", (final_username, iface))
            conflict = cur.fetchone()
            if conflict:
                final_username = f"{final_username}_{iface}"
                
            hashed_pw = generate_password_hash(final_password)
            
            data_limit = r_item.get('data_limit_gb', 100)
            port = r_item.get('port', 51821)
            status = r_item.get('status', 'active')
            subnet_ip = r_item.get('subnet_ip')
            
            if not db_row:
                cur.execute("INSERT INTO sub_panels (interface_name, username, password_hash, data_limit_gb, port, created_at, status, password_plain) VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?)",
                            (iface, final_username, hashed_pw, data_limit, port, status, final_password))
                recovered_logs.append(f"احیای نماینده {iface} در دیتابیس")
            else:
                cur.execute("UPDATE sub_panels SET username=?, password_hash=?, password_plain=?, data_limit_gb=?, status=? WHERE interface_name=?", 
                            (final_username, hashed_pw, final_password, data_limit, status, iface))
            conn.commit()
            conf_path = f"/etc/wireguard/{iface}.conf"
            if not os.path.exists(conf_path):
                priv_key = subprocess.check_output("wg genkey", shell=True, text=True).strip()
                if not subnet_ip:
                    subnet_idx = 10
                    while subnet_idx in used_subs: subnet_idx += 5
                    used_subs.add(subnet_idx)
                    subnet_ip = f"10.0.{subnet_idx}.1/24"
                
                conf = f"[Interface]\nAddress = {subnet_ip}\nSaveConfig = false\nListenPort = {port}\nPrivateKey = {priv_key}\n"
                if main_nic:
                    conf += f"PostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -A FORWARD -o {iface} -j ACCEPT; iptables -I FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -A POSTROUTING -o {main_nic} -j MASQUERADE\n"
                    conf += f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -D FORWARD -o {iface} -j ACCEPT; iptables -D FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -D POSTROUTING -o {main_nic} -j MASQUERADE\n"
                with open(conf_path, 'w', encoding='utf-8') as f: f.write(conf)
                subprocess.run(f"systemctl enable wg-quick@{iface}; systemctl restart wg-quick@{iface}", shell=True, stderr=subprocess.DEVNULL)
                recovered_logs.append(f"تولید فایل {iface}.conf")
        except Exception as ex_r:
            recovered_logs.append(f"اخطار در نماینده {r_item.get('interface_name', 'Unknown')}: {ex_r}")

    print("ممیزی با موفقیت به پایان رسید.")
finally:
    try:
        cur.execute("SELECT interface_name, username, password_plain, data_limit_gb, port, status FROM sub_panels")
        for row in cur.fetchall():
            sub_ip = "N/A"
            try:
                txt = open(f"/etc/wireguard/{row[0]}.conf", 'r').read()
                m = re.search(r"Address\s*=\s*([^\s]+)", txt, re.IGNORECASE)
                if m: sub_ip = m.group(1).strip()
            except: pass
            
            synced_resellers_for_ui.append({
                "interface_name": row[0],
                "username": row[1] if row[1] else "N/A",
                "password_plain": row[2] if row[2] else "N/A",
                "data_limit_gb": row[3],
                "port": row[4],
                "status": row[5],
                "subnet_ip": sub_ip
            })
    except: pass
    
    if 'conn' in locals() and conn:
        conn.close()

if os.path.exists(rescue_file): os.remove(rescue_file)

if recovered_logs: 
    for item in recovered_logs: print(f" - {item}")

print("[SYNCED_DB_DATA]" + json.dumps(synced_resellers_for_ui))
PYTHON;
        $raw_out = exec_py($conn, $py_bin, $py_audit);
        
        if (preg_match('/\[SYNCED_DB_DATA\](.*)/', $raw_out, $matches)) {
            $db_data_json = trim($matches[1]);
            $db_data = json_decode($db_data_json, true);
            if (is_array($db_data) && !empty($db_data)) { 
                foreach ($db_data as $r) {
                    register_local_interface($h, $r['interface_name'], [
                        'interface_name' => $r['interface_name'],
                        'username' => $r['username'],
                        'password_plain' => $r['password_plain'],
                        'data_limit_gb' => floatval($r['data_limit_gb']),
                        'port' => intval($r['port']),
                        'subnet_ip' => $r['subnet_ip'],
                        'status' => $r['status']
                    ]);
                }
            }
            $reseller_log .= "\n" . preg_replace('/\[SYNCED_DB_DATA\].*/', '', $raw_out);
        } else {
            $reseller_log .= "\n" . $raw_out;
        }
    }

    // پاکسازی شبکه
    if ($act == 'sync_ips') {
        $py_deep_cleanup = <<<'PYTHON'
import sys, os, sqlite3, subprocess, re
sys.stdout.reconfigure(line_buffering=True)

db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
wg_config_dir = '/etc/wireguard'

print("شروع فرآیند پاکسازی شبکه و احیای روت‌های ترافیک...")

if not os.path.exists(db_path):
    print("خطا: دیتابیس یافت نشد.")
    sys.exit(1)

conn = sqlite3.connect(db_path, timeout=30.0)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

try:
    cur.execute("SELECT peer_ip, COUNT(*) as c FROM peers GROUP BY peer_ip HAVING c > 1")
    dup_ips = cur.fetchall()
    for row in dup_ips:
        ip = row['peer_ip']
        if not ip: continue
        cur.execute("SELECT id, public_key, config FROM peers WHERE peer_ip=? ORDER BY id ASC", (ip,))
        group = cur.fetchall()
        master = group[0]
        for dup in group[1:]:
            cur.execute("DELETE FROM peers WHERE id=?", (dup['id'],))
            conn.commit()
            iface = dup['config'].replace(".conf", "")
            if os.path.exists(f"/sys/class/net/{iface}"):
                subprocess.run(f"wg set {iface} peer {dup['public_key']} remove", shell=True, stderr=subprocess.DEVNULL)

    routes_all = subprocess.getoutput("ip route show table all")
    for line in routes_all.splitlines():
        if "blackhole" in line:
            parts = line.split()
            if len(parts) >= 2:
                target_ip = parts[1]
                subprocess.run(f"ip route del blackhole {target_ip}", shell=True, stderr=subprocess.DEVNULL)
                subprocess.run(f"ip route del {target_ip} blackhole", shell=True, stderr=subprocess.DEVNULL)

    print("عملیات رفع تداخل و بازسازی روت‌ها با موفقیت انجام شد.")
except Exception as e:
    print(f"خطا: {e}")
finally:
    conn.close()
PYTHON;
        $sync_log = exec_py($conn, $py_bin, $py_deep_cleanup);
    }

    // بهینه‌سازی گیمینگ
    if ($act == 'optimize_gaming') {
        $sh_gaming = <<<'SHELL'
#!/bin/bash
echo "شروع اعمال پیکربندی پینگ مینیمال و بهینه‌سازی شبکه..."

modprobe tcp_bbr 2>/dev/null || true
cat > /etc/sysctl.d/99-gaming-optimizer.conf << EOF
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

echo "تنظیمات کاهش پینگ و پایدارسازی با موفقیت اعمال گردید."
SHELL;
        $gaming_log = exec_py($conn, "/bin/bash", $sh_gaming);
    }

    // انتقال سرور لبه
    if ($act == 'migrate_edge') {
        $old_ip = trim($_POST['old_edge_ip'] ?? ''); $old_pass = trim($_POST['old_edge_pass'] ?? '');
        $new_ip = trim($_POST['new_edge_ip'] ?? ''); $new_pass = trim($_POST['new_edge_pass'] ?? '');
        if (!empty($old_ip) && !empty($new_ip)) {
            $edge_migration_script = <<<PYTHON
import sys, subprocess
sys.stdout.reconfigure(line_buffering=True)
try:
    print("شروع فاز انتقال فیزیکی سرور لبه...")
    subprocess.run("sshpass -p '{$old_pass}' ssh -o StrictHostKeyChecking=no root@{$old_ip} 'systemctl stop wireguard-panel; wg-quick down wg0'", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run("sshpass -p '{$old_pass}' scp -r root@{$old_ip}:/etc/wireguard/ /tmp/wireguard_backup", shell=True)
    subprocess.run("sshpass -p '{$new_pass}' scp -r /tmp/wireguard_backup root@{$new_ip}:/etc/wireguard/", shell=True)
    subprocess.run("sshpass -p '{$new_pass}' ssh -o StrictHostKeyChecking=no root@{$new_ip} 'systemctl daemon-reload && systemctl enable wg-quick@wg0 && systemctl start wg-quick@wg0'", shell=True)
    print("گره لبه با موفقیت انتقال یافت.")
except Exception as e: print(f"خطا: {e}")
PYTHON;
            $detailed_migration_log = exec_py($conn, $py_bin, $edge_migration_script);
        }
    }
}

// ---------------------------------------------------------
// مدیریت ربات تلگرام
// ---------------------------------------------------------
if ($in && isset($_POST['bot_action'])) {
    $ba = $_POST['bot_action'];
    $bt = trim($_POST['bot_token'] ?? '');
    $bc = trim($_POST['chat_id'] ?? '');

    if ($ba == 'toggle') {
        $st = $_POST['status_toggle'] ?? 'off';
        if ($st == 'on') {
            if (empty($bt) || empty($bc)) {
                $t_logs = "خطا: توکن و چت‌آیدی الزامی است.";
            } else {
                $sftp = @ssh2_sftp($conn);
                if ($sftp) {
                    @file_put_contents("ssh2.sftp://" . intval($sftp) . "{$p_dir}/telegram_bot_config.json", json_encode(["t" => $bt, "c" => $bc]));
                    
                    $py_code = <<<'PYTHON'
import os, sys, json, zipfile, urllib.request, datetime, time, subprocess

with open('/usr/local/bin/Wireguard-panel/src/telegram_bot_config.json') as f:
    c = json.load(f)
T = c.get('t')
C = c.get('c')
P = '/usr/local/bin/Wireguard-panel/src'

def smsg(t, kb=None):
    try:
        data = {'chat_id': C, 'text': t, 'parse_mode': 'HTML'}
        if kb: data['reply_markup'] = kb
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{T}/sendMessage",
            data=json.dumps(data).encode(),
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req)
    except:
        pass

def sdoc(dp, cap):
    b = '---bndry'
    try:
        with open(dp, 'rb') as f:
            fc = f.read()
        body = (
            f"--{b}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{C}\r\n".encode() +
            f"--{b}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{cap}\r\n".encode() +
            f"--{b}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{os.path.basename(dp)}\"\r\nContent-Type: application/zip\r\n\r\n".encode() +
            fc +
            f"\r\n--{b}--\r\n".encode()
        )
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{T}/sendDocument",
            data=body,
            method='POST',
            headers={'Content-Type': f'multipart/form-data; boundary={b}'}
        )
        urllib.request.urlopen(req)
    except:
        pass

def mb():
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = f"/tmp/b_{ts}.zip"
    with zipfile.ZipFile(bp, 'w', zipfile.ZIP_DEFLATED) as zf:
        for p, n in [(f"{P}/db.sqlite3", 'db.sqlite3'), (f"{P}/config.yaml", 'config.yaml'), (f"{P}/short_links.json", 'short_links.json')]:
            if os.path.exists(p):
                zf.write(p, n)
        for rd, ad in [(f"{P}/db", 'db'), ('/etc/wireguard', 'wireguard')]:
            if os.path.exists(rd):
                for rt, _, fs in os.walk(rd):
                    for f in fs:
                        full_p = os.path.join(rt, f)
                        zf.write(full_p, os.path.join(ad, os.path.relpath(full_p, rd)))
    return bp

def fmt(b):
    if b >= 1073741824: return f"{b/1073741824:.2f} GB"
    if b >= 1048576: return f"{b/1048576:.2f} MB"
    return f"{b/1024:.2f} KB"

def gs():
    try:
        with open('/proc/stat') as f:
            l1 = list(map(int, f.readline().split()[1:]))
        time.sleep(0.5)
        with open('/proc/stat') as f:
            l2 = list(map(int, f.readline().split()[1:]))
        t1, t2 = sum(l1), sum(l2)
        cpu = round(100*(1-(l2[3]-l1[3])/(t2-t1)), 1) if t2 > t1 else 0
    except:
        cpu = 0
    
    try:
        with open('/proc/meminfo') as f:
            md = {p[0]: int(p[1].split()[0])*1024 for p in [line.split(':') for line in f if len(line.split(':'))==2]}
        mem_used = md['MemTotal'] - md['MemFree'] - md['Buffers'] - md['Cached']
        mem_pct = f"{fmt(mem_used)} / {fmt(md['MemTotal'])} ({mem_used/md['MemTotal']*100:.1f}%)"
    except:
        mem_pct = "N/A"
    
    return f"CPU: {cpu}% | Memory: {mem_pct}"

kb = {'inline_keyboard': [[{'text': 'آمار سرور', 'callback_data': 's'}, {'text': 'بکاپ فوری سرور', 'callback_data': 'b'}]]}
smsg("ربات پایش و بکاپ هوشمند وایرگارد فعال شد.", kb)
o, lb = 0, time.time()

while True:
    if time.time() - lb > 21600:
        bp = mb()
        sdoc(bp, "بکاپ خودکار ۶ ساعته سیستم")
        if os.path.exists(bp): os.remove(bp)
        lb = time.time()
    try:
        req = urllib.request.urlopen(f"https://api.telegram.org/bot{T}/getUpdates?timeout=20&offset={o}", timeout=25)
        for u in json.loads(req.read().decode()).get('result', []):
            o = u['update_id'] + 1
            if u.get('message', {}).get('text') == '/start':
                smsg("مرکز مدیریت هوشمند آنلاین است.", kb)
            elif 'callback_query' in u:
                d = u['callback_query'].get('data')
                if d == 's':
                    smsg(gs(), kb)
                elif d == 'b':
                    smsg("در حال ایجاد فایل پشتیبان...")
                    bp = mb()
                    sdoc(bp, "فایل پشتیبان دستی")
                    if os.path.exists(bp): os.remove(bp)
    except:
        time.sleep(3)
PYTHON;
                    @file_put_contents("ssh2.sftp://" . intval($sftp) . "{$p_dir}/telegram_bot_poll.py", $py_code);
                    $k1 = @ssh2_exec($conn, "pkill -f 'telegram_bot_poll.py'"); if ($k1) { stream_set_blocking($k1, true); fclose($k1); }
                    $k2 = @ssh2_exec($conn, "nohup {$py_bin} {$p_dir}/telegram_bot_poll.py > /dev/null 2>&1 &"); if ($k2) { stream_set_blocking($k2, true); fclose($k2); }
                    $t_logs = "ربات پایش با موفقیت فعال گردید.";
                    $b_on = true;
                    $s_tok = $bt;
                    $s_cid = $bc;
                }
            }
        } else {
            $k1 = @ssh2_exec($conn, "pkill -f 'telegram_bot_poll.py'"); if ($k1) { stream_set_blocking($k1, true); fclose($k1); }
            $t_logs = "ربات تلگرام غیرفعال شد.";
            $b_on = false;
        }
    }

    if ($ba == 'test_send') {
        if (empty($s_tok) || empty($s_cid)) {
            $t_logs = "خطا: ابتدا توکن و چت‌آیدی را ذخیره کنید.";
        } else {
            $py_test = "import urllib.request, urllib.parse, json; urllib.request.urlopen(urllib.request.Request('https://api.telegram.org/bot{$s_tok}/sendMessage', data=json.dumps({'chat_id':'{$s_cid}','text':'پیام تست ارتباط ربات با موفقیت برقرار شد.'}).encode(), headers={'Content-Type':'application/json'}))";
            $s = @ssh2_exec($conn, "{$py_bin} -c " . escapeshellarg($py_test) . " 2>&1");
            if ($s) {
                stream_set_blocking($s, true);
                $res_content = trim(stream_get_contents($s));
                $t_logs = "نتیجه تست:\n" . ($res_content ?: "پیام تست ارسال گردید.");
                fclose($s);
            }
        }
    }

    if ($ba == 'set_webhook') {
        if (empty($s_tok)) {
            $t_logs = "خطا: ابتدا توکن ربات را وارد و ذخیره کنید.";
        } else {
            $api_url = "https://api.telegram.org/bot{$s_tok}/setWebhook?url=" . urlencode($detected_webhook_url);
            $res = @file_get_contents($api_url);
            $t_logs = "نتیجه وب‌هوک:\n" . ($res ? $res : "ارتباط با سرور تلگرام برقرار نشد.");
        }
    }
}

// ارسال متریک‌ها به تلگرام
if ($in && isset($_POST['get_metrics'])) {
    if (empty($s_tok) || empty($s_cid)) {
        $t_logs = "خطا: ابتدا توکن و چت‌آیدی را در بخش ربات ذخیره کنید.";
    } else {
        $py_metrics = <<<'PYTHON'
import os, sys, subprocess, urllib.request, urllib.parse, json

token = sys.argv[1]
chat_id = sys.argv[2]
interface = 'wg0'

def fmt(b):
    if b >= 1073741824: return f'{b / 1073741824:.2f} GB'
    if b >= 1048576: return f'{b / 1048576:.2f} MB'
    return f'{b / 1024:.2f} KB'

def get_wg():
    try:
        out = subprocess.check_output(['wg', 'show', interface, 'transfer'], text=True)
        rx, tx = 0, 0
        for line in out.splitlines():
            p = line.split('\t')
            if len(p) >= 3:
                rx += int(p[1])
                tx += int(p[2])
        return rx, tx
    except:
        return 0, 0

try:
    import time
    with open('/proc/stat') as f: l1 = list(map(int, f.readline().split()[1:]))
    time.sleep(0.5)
    with open('/proc/stat') as f: l2 = list(map(int, f.readline().split()[1:]))
    t1, t2 = sum(l1), sum(l2)
    cpu = round(100*(1-(l2[3]-l1[3])/(t2-t1)),1) if t2>t1 else 0
except:
    cpu = "N/A"

try:
    with open('/proc/meminfo') as f:
        md = {p[0]: int(p[1].split()[0])*1024 for p in (l.split(':') for l in f if ':' in l)}
    mt, ma = md.get('MemTotal', 1), md.get('MemAvailable', 0)
    mu = mt - ma
    ram_str = f"کل: {fmt(mt)} | مصرفی: {fmt(mu)} ({round(mu/mt*100,1)}%)"
except:
    ram_str = "N/A"

try:
    st = os.statvfs('/')
    dt = st.f_blocks * st.f_frsize
    df = st.f_bfree * st.f_frsize
    du = dt - df
    disk_str = f"کل: {fmt(dt)} | مصرفی: {fmt(du)} ({round((du/dt)*100,1)}%)"
except:
    disk_str = "N/A"

rx, tx = get_wg()
msg = '<b>آمار منابع سرور</b>\n\n'
msg += f'<b>CPU:</b> {cpu}%\n\n'
msg += f'<b>RAM:</b>\n• {ram_str}\n\n'
msg += f'<b>Disk:</b>\n• {disk_str}\n\n'
msg += f'<b>Network ({interface}):</b>\n• دانلود: {fmt(rx)}\n• آپلود: {fmt(tx)}\n• کل مصرف: {fmt(rx+tx)}'

url = f'https://api.telegram.org/bot{token}/sendMessage'
data = urllib.parse.urlencode({'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'}).encode()
try:
    urllib.request.urlopen(url, data=data)
    print('آمار سرور به تلگرام ارسال شد.')
except Exception as e:
    print(f'خطا در ارسال آمار: {e}')
PYTHON;

        $cmd = "{$py_bin} -c " . escapeshellarg($py_metrics) . " " . escapeshellarg($s_tok) . " " . escapeshellarg($s_cid);
        $s = @ssh2_exec($conn, $cmd);
        if ($s) {
            stream_set_blocking($s, true);
            $t_logs = trim(stream_get_contents($s));
            fclose($s);
        }
    }
}

// مهاجرت سرور
if ($in && isset($_POST['migrate_server'])) {
    $m_host = trim($_POST['m_host'] ?? '');
    $m_port = intval($_POST['m_port'] ?? 22);
    $m_user = trim($_POST['m_user'] ?? '');
    $m_pass = trim($_POST['m_pass'] ?? '');

    if (empty($m_host) || empty($m_user) || empty($m_pass)) {
        $detailed_migration_log = "لطفاً تمام فیلدهای سرور مقصد را پر کنید.";
    } else {
        $detailed_migration_log .= "[INFO] شروع عملیات انتقال سرور به سرور...\n";
        
        $py_backup = <<<'PYTHON'
import os, zipfile, datetime
P = '/usr/local/bin/Wireguard-panel/src'
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
bp = f"/tmp/live_backup_{ts}.zip"
with zipfile.ZipFile(bp, 'w', zipfile.ZIP_DEFLATED) as zf:
    paths = [
        (f"{P}/db.sqlite3", 'db/db.sqlite3'),
        (f"{P}/config.yaml", 'config.yaml'),
        (f"{P}/short_links.json", 'links/short_links.json')
    ]
    for real_path, arc_name in paths:
        if os.path.exists(real_path):
            zf.write(real_path, arc_name)
    
    dirs = [
        (f"{P}/db", 'db'),
        ('/etc/wireguard', 'wireguard')
    ]
    for real_dir, arc_dir in dirs:
        if os.path.exists(real_dir):
            for root, _, files in os.walk(real_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    zf.write(fp, os.path.join(arc_dir, os.path.relpath(fp, real_dir)))
print(bp)
PYTHON;

        $sc_b = @ssh2_exec($conn, "{$py_bin} -c " . escapeshellarg($py_backup));
        if ($sc_b) {
            stream_set_blocking($sc_b, true);
            $backup_path = trim(stream_get_contents($sc_b));
            fclose($sc_b);
        } else {
            $backup_path = "";
        }

        if (!empty($backup_path) && strpos($backup_path, '.zip') !== false) {
            $detailed_migration_log .= "[INFO] فایل بکاپ ساخته شد.\n";
            $sftp_src = @ssh2_sftp($conn);
            $backup_data = @file_get_contents("ssh2.sftp://" . intval($sftp_src) . $backup_path);
            
            $conn_dest = @ssh2_connect($m_host, $m_port);
            if ($conn_dest && @ssh2_auth_password($conn_dest, $m_user, $m_pass)) {
                $detailed_migration_log .= "[INFO] اتصال به سرور مقصد ({$m_host}) برقرار شد.\n";
                $sftp_dest = @ssh2_sftp($conn_dest);
                $remote_dest_zip = "/tmp/uploaded_migration.zip";
                
                if (@file_put_contents("ssh2.sftp://" . intval($sftp_dest) . $remote_dest_zip, $backup_data)) {
                    $detailed_migration_log .= "[INFO] بکاپ با موفقیت ارسال شد.\n[INFO] شروع استخراج در سرور مقصد...\n\n";
                    
                    $py_mig = <<<'PYTHON'
import os, sys, sqlite3, json, subprocess, zipfile, shutil

zip_path = '/tmp/uploaded_migration.zip'
ddb = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
pdr = '/usr/local/bin/Wireguard-panel/src'
wg_dir = '/etc/wireguard'

if not os.path.exists(ddb): 
    print('[FATAL] دیتابیس مقصد یافت نشد.')
    exit(1)

dc = sqlite3.connect(ddb)
dc.row_factory = sqlite3.Row
dcu = dc.cursor()

dcu.execute("PRAGMA table_info(peers)")
existing_cols = {row[1] for row in dcu.fetchall()}

dcu.execute('SELECT peer_name, peer_ip, public_key FROM peers')
ex = dcu.fetchall()
en = {r['peer_name'].lower() for r in ex}
ei = {r['peer_ip'] for r in ex}
ek = {r['public_key'] for r in ex}

imp = []
temp_dir = '/tmp/wg_rest_temp_extract'
os.makedirs(temp_dir, exist_ok=True)

with zipfile.ZipFile(zip_path, 'r') as zf:
    zf.extractall(temp_dir)
    files_in_zip = zf.namelist()

    db_found = False
    for f in files_in_zip:
        if f.endswith('db.sqlite3'):
            db_found = True
            extr_db = os.path.join(temp_dir, f)
            sc = sqlite3.connect(extr_db)
            sc.row_factory = sqlite3.Row
            try: imp = [dict(r) for r in sc.cursor().execute('SELECT * FROM peers').fetchall()]
            except: pass
            finally: sc.close()
            break
            
    if not db_found or not imp:
        for f in files_in_zip:
            if f.endswith('.json') and 'short_links' not in f:
                try:
                    with open(os.path.join(temp_dir, f), 'r') as jf:
                        d = json.load(jf)
                        if isinstance(d, list): imp.extend(d)
                except: pass

ac, sc_c = 0, 0
lip = set()
try:
    sh_ip = subprocess.check_output("ip -o addr show | grep -v 'wg' | grep -v 'lo'", shell=True, text=True)
    for line in sh_ip.splitlines():
        parts = line.split()
        for p in parts:
            if '/' in p and not p.startswith('inet6'): lip.add(p.split('/')[0])
except: pass

for p in imp:
    pn, pi, pk, pc = p.get('peer_name'), p.get('peer_ip'), p.get('public_key'), p.get('config', 'wg0.conf')
    if not pn or not pi or not pk: continue
    if pi in lip: continue

    dcu.execute("SELECT id FROM peers WHERE LOWER(peer_name)=? OR peer_ip=? OR public_key=?", (pn.lower(), pi, pk))
    if dcu.fetchall():
        dcu.execute("DELETE FROM peers WHERE LOWER(peer_name)=? OR peer_ip=? OR public_key=?", (pn.lower(), pi, pk))
        sc_c += 1

    try:
        ej = json.dumps(p.get('expiry_time', {})) if isinstance(p.get('expiry_time'), dict) else p.get('expiry_time_json')
        
        col_mapping = {
            "peer_name": pn, "peer_ip": pi, "public_key": pk, "limit": p.get('limit'), "used": p.get('used', 0),
            "remaining": p.get('remaining', 0), "config": pc, "expiry_time_json": ej, "first_usage": 1 if p.get('first_usage') else 0,
            "expiry_blocked": 1 if p.get('expiry_blocked') else 0, "monitor_blocked": 1 if p.get('monitor_blocked', 0) else 0,
            "last_received_bytes": p.get('last_received_bytes', 0), "last_sent_bytes": p.get('last_sent_bytes', 0),
            "remaining_time": p.get('remaining_time', 0), "private_key": p.get('private_key'), "dns": p.get('dns'),
            "mtu": p.get('mtu', 1280), "persistent_keepalive": p.get('persistent_keepalive', 25), "allowed_ips": p.get('allowed_ips', '0.0.0.0/0, ::/0'),
            "token": p.get('token')
        }
        
        insert_cols = [col for col in col_mapping if col in existing_cols]
        insert_cols_escaped = [f"[{col}]" if col == "limit" else col for col in insert_cols]
        placeholders = ", ".join(["?"] * len(insert_cols))
        
        query = f"INSERT INTO peers ({', '.join(insert_cols_escaped)}) VALUES ({placeholders})"
        values = tuple(col_mapping[col] for col in insert_cols)
        
        dcu.execute(query, values)
        ac += 1
    except Exception as e: pass

dc.commit()

dcu.execute("SELECT DISTINCT config FROM peers")
cfs = [r['config'] for r in dcu.fetchall()]
for c in cfs:
    cp = os.path.join(wg_dir, c)
    if not os.path.exists(cp): continue
    
    with open(cp, 'r') as f: lines = f.readlines()
    il = []
    for l in lines:
        if l.strip() == '[Peer]': break
        il.append(l)
        
    dcu.execute("SELECT peer_name, public_key, peer_ip, persistent_keepalive FROM peers WHERE config=? AND expiry_blocked=0 AND monitor_blocked=0", (c,))
    ps = dcu.fetchall()
    
    with open(cp, 'w') as f:
        f.writelines(il)
        for p in ps:
            f.write(f"\n[Peer]\n# {p['peer_name']}\nPublicKey = {p['public_key']}\nAllowedIPs = {p['peer_ip']}/32\nPersistentKeepalive = {p['persistent_keepalive']}\n")
    
    intf = c.replace('.conf', '')
    subprocess.run(f"wg-quick down {intf} >/dev/null 2>&1; wg-quick up {intf} >/dev/null 2>&1", shell=True)
    
    for p in ps:
        subprocess.run(['ip', 'route', 'replace', f"{p['peer_ip']}/32", 'dev', intf], capture_output=True)

import glob
links_files = glob.glob(temp_dir + '/**/short_links.json', recursive=True)
if links_files:
    sl_s = links_files[0]
    sl_d = os.path.join(pdr, 'short_links.json')
    if os.path.exists(sl_s) and os.path.exists(sl_d):
        try:
            with open(sl_s, 'r') as sf, open(sl_d, 'r') as df: m = {**json.load(df), **json.load(sf)}
            with open(sl_d, 'w') as df: json.dump(m, df, indent=4)
        except: pass

dc.close()
shutil.rmtree(temp_dir)
print(f'\nعملیات مهاجرت پایان یافت. اضافه شده: {ac} | جایگزین شده: {sc_c}')
PYTHON;

                    $cmd_file = "/tmp/run_migration.py";
                    @file_put_contents("ssh2.sftp://" . intval($sftp_dest) . $cmd_file, $py_mig);
                    $cmds = [
                        "{$py_bin} {$cmd_file}",
                        "systemctl restart wireguard-panel",
                        "rm -f {$remote_dest_zip} {$cmd_file}"
                    ];
                    foreach ($cmds as $c) {
                        $st = @ssh2_exec($conn_dest, $c);
                        if ($st) {
                            stream_set_blocking($st, true);
                            $detailed_migration_log .= stream_get_contents($st) . "\n";
                            fclose($st);
                        }
                    }
                } else {
                    $detailed_migration_log .= "خطا در ارسال فایل بکاپ به سرور مقصد.\n";
                }
            } else {
                $detailed_migration_log .= "خطا در اتصال به سرور مقصد.\n";
            }
            @ssh2_exec($conn, "rm -f {$backup_path}");
        } else {
            $detailed_migration_log .= "خطا در تولید بکاپ از سرور مبدا.";
        }
    }
}

// سیستم همگام‌سازی زنده پس‌زمینه
if ($in && isset($_POST['action']) && $_POST['action'] === 'live_sync') {
    $_SESSION['last_active'] = time(); 
    session_write_close();

    $py_resellers_live = <<<'PYTHON'
import sqlite3, os, re
try:
    db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
    registered_panels = {}
    universal_vault = {}
    admin_deleted = 0

    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path, timeout=5.0)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sub_panels'")
        if cur.fetchone():
            cur.execute("SELECT interface_name, data_limit_gb, deleted_traffic FROM sub_panels")
            for r in cur.fetchall():
                registered_panels[r[0]] = {"l": float(r[1]) if r[1] is not None else 100.0, "del_traf": int(r[2]) if r[2] else 0}
        
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='interface_vault'")
        if cur.fetchone():
            cur.execute("SELECT interface_name, vault_bytes FROM interface_vault")
            for iv_name, iv_bytes in cur.fetchall(): universal_vault[iv_name] = iv_bytes or 0
                
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='global_deleted_traffic'")
        if cur.fetchone():
            row_del = cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1").fetchone()
            admin_deleted = row_del[0] if row_del else 0
        conn.close()

    all_confs = [f.replace('.conf','') for f in os.listdir('/etc/wireguard') if f.endswith('.conf')] if os.path.exists('/etc/wireguard') else []
    if 'wg0' not in all_confs: all_confs.append('wg0')

    conn_db = sqlite3.connect(db_path, timeout=5.0); cur_db = conn_db.cursor()
    for name in sorted(list(set(all_confs))):
        cur_db.execute("SELECT SUM(used) FROM peers WHERE config=?", (f"{name}.conf",))
        live_used = cur_db.fetchone()[0] or 0
        
        vault_traffic = 0
        if name == 'wg0':
            vault_traffic = admin_deleted + universal_vault.get('wg0', 0)
        else:
            del_t = registered_panels.get(name, {}).get('del_traf', 0)
            vault_t = universal_vault.get(name, 0)
            vault_traffic = max(del_t, vault_t)

        used_gb = (live_used + vault_traffic) / 1073741824.0

        if name == 'wg0':
            all_live = cur_db.execute("SELECT SUM(used) FROM peers").fetchone()[0] or 0
            all_del_subs = cur_db.execute("SELECT SUM(deleted_traffic) FROM sub_panels").fetchone()[0] or 0
            all_vaults = cur_db.execute("SELECT SUM(vault_bytes) FROM interface_vault").fetchone()[0] or 0
            tot_gb = (all_live + admin_deleted + all_del_subs + all_vaults) / 1073741824.0
            print(f"wg0|{used_gb:.2f}|0|{tot_gb:.2f}")
        elif name in registered_panels:
            rem = max(0, registered_panels[name]['l'] - used_gb)
            print(f"{name}|{used_gb:.2f}|{rem:.2f}|0")
    conn_db.close()
except: pass
PYTHON;

    $stdout = "";
    if (file_exists($py_bin) || $in) {
        $stdout = exec_py($conn, $py_bin, $py_resellers_live);
    }
    
    $json_data = [];
    if (!empty($stdout) && strpos($stdout, 'Error') === false) {
        $lines = explode("\n", trim($stdout));
        foreach ($lines as $line) {
            $rd = explode("|", trim($line));
            if (count($rd) >= 4) {
                $json_data[$rd[0]] = [
                    'used' => $rd[1],
                    'rem' => $rd[2],
                    'total' => $rd[3]
                ];
            }
        }
    }
    
    if (ob_get_length()) ob_clean();
    header('Content-Type: application/json');
    echo json_encode($json_data);
    exit;
}
?>
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>CYBER-CORE // DataCenter Control Center</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/misc/UI/webfont/Vazirmatn-UI-Wght.woff2" rel="stylesheet" type="text/css">
<style>
/* --- 🚀 ULTRA GAMING CYBERPUNK HUD THEME --- */
:root {
    --bg-main: #06070a;
    --bg-glass: rgba(13, 16, 23, 0.75);
    --border-glass: rgba(0, 242, 255, 0.15);
    --border-glow: rgba(0, 242, 255, 0.4);
    --neon-cyan: #00f2ff;
    --neon-green: #00ffaa;
    --neon-purple: #bc13fe;
    --neon-amber: #ffaa00;
    --neon-red: #ff3366;
    --text-primary: #e6edf3;
    --text-muted: #8b949e;
    --font-mono: 'Consolas', 'JetBrains Mono', 'Courier New', monospace;
}

* { box-sizing: border-box; }
body {
    background: var(--bg-main);
    background-image: 
        radial-gradient(circle at 10% 20%, rgba(188, 19, 254, 0.06), transparent 35%),
        radial-gradient(circle at 90% 80%, rgba(0, 242, 255, 0.05), transparent 35%),
        linear-gradient(rgba(0,0,0,0.5) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,0,0,0.5) 1px, transparent 1px);
    background-size: 100% 100%, 100% 100%, 24px 24px, 24px 24px;
    color: var(--text-primary);
    font-family: 'Vazirmatn', Tahoma, sans-serif;
    margin: 0;
    padding: 16px;
    line-height: 1.6;
    min-height: 100vh;
}

/* اسکرول‌بار اختصاصی گیمینگ */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #08090d; }
::-webkit-scrollbar-thumb { background: rgba(0, 242, 255, 0.2); border-radius: 4px; border: 1px solid var(--border-glass); }
::-webkit-scrollbar-thumb:hover { background: var(--neon-cyan); box-shadow: 0 0 10px var(--neon-cyan); }

.container { max-width: 1200px; margin: 0 auto; }

/* کارت‌های شیشه‌ای های‌تک */
.card {
    background: var(--bg-glass);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--border-glass);
    border-radius: 14px;
    padding: 24px;
    margin-bottom: 24px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.7), inset 0 0 1px 1px rgba(255,255,255,0.05);
    position: relative;
    overflow: hidden;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, transparent, var(--neon-cyan), transparent);
    opacity: 0.3;
}
.card:hover {
    border-color: var(--border-glow);
    box-shadow: 0 12px 35px rgba(0, 242, 255, 0.1), inset 0 0 20px rgba(0, 242, 255, 0.03);
}

h2 {
    color: #fff;
    font-size: 1.25rem;
    font-weight: 800;
    margin-top: 0;
    padding-bottom: 12px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    display: flex;
    align-items: center;
    gap: 12px;
    letter-spacing: 0.5px;
}
h2 i { color: var(--neon-cyan); text-shadow: 0 0 12px var(--neon-cyan); font-size: 1.15rem; }
h3 { color: var(--neon-cyan); font-size: 1.05rem; }

.form-group { margin-bottom: 18px; }
label { display: block; margin-bottom: 8px; font-size: 13px; color: var(--text-muted); font-weight: 600; }
input[type="text"], input[type="password"], input[type="number"], select {
    width: 100%;
    padding: 12px 14px;
    background: rgba(4, 5, 8, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #fff;
    border-radius: 8px;
    font-family: inherit;
    font-size: 14px;
    transition: 0.25s ease;
}
input:focus, select:focus {
    border-color: var(--neon-cyan);
    box-shadow: 0 0 15px rgba(0, 242, 255, 0.25);
    outline: none;
    background: rgba(0,0,0,0.9);
}

/* تقویت دکمه‌های کنترلی با استایل گیمینگ */
.btn {
    background: rgba(0, 242, 255, 0.08);
    border: 1px solid var(--neon-cyan);
    color: var(--neon-cyan);
    padding: 11px 18px;
    border-radius: 8px;
    cursor: pointer;
    font-weight: 700;
    font-size: 13px;
    font-family: inherit;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    text-decoration: none;
    text-shadow: 0 0 8px rgba(0,242,255,0.4);
    letter-spacing: 0.3px;
    position: relative;
    user-select: none;
}
.btn:hover {
    background: var(--neon-cyan);
    color: #000;
    box-shadow: 0 0 20px rgba(0, 242, 255, 0.6);
    transform: translateY(-2px);
    text-shadow: none;
}
.btn:active { transform: translateY(0); }

.btn-primary {
    background: linear-gradient(135deg, var(--neon-amber) 0%, #ff6600 100%);
    color: #050608;
    border: none;
    text-shadow: none;
    box-shadow: 0 4px 15px rgba(255, 170, 0, 0.3);
}
.btn-primary:hover {
    background: linear-gradient(135deg, #ffbb22 0%, #ff7711 100%);
    color: #000;
    box-shadow: 0 0 25px rgba(255, 170, 0, 0.6);
}

.btn-danger {
    background: rgba(255, 51, 102, 0.1);
    border-color: var(--neon-red);
    color: var(--neon-red);
    text-shadow: 0 0 8px rgba(255,51,102,0.4);
}
.btn-danger:hover {
    background: var(--neon-red);
    color: #fff;
    box-shadow: 0 0 20px rgba(255, 51, 102, 0.6);
    text-shadow: none;
}

.btn-info {
    background: rgba(0, 242, 255, 0.12);
    border-color: var(--neon-cyan);
    color: var(--neon-cyan);
}
.btn-info:hover {
    background: var(--neon-cyan);
    color: #000;
    box-shadow: 0 0 20px rgba(0, 242, 255, 0.6);
}

.btn-gaming {
    background: linear-gradient(135deg, #130cb7 0%, var(--neon-purple) 100%);
    color: #fff;
    border: 1px solid rgba(188, 19, 254, 0.4);
    box-shadow: 0 4px 18px rgba(188, 19, 254, 0.3);
}
.btn-gaming:hover {
    background: linear-gradient(135deg, #221bd9 0%, #d422ff 100%);
    box-shadow: 0 0 25px rgba(188, 19, 254, 0.6);
    color: #fff;
}

/* ترمینال و لاگ‌ها */
.term-wrapper {
    background: #040507;
    border: 1px solid rgba(0, 242, 255, 0.2);
    border-radius: 10px;
    padding: 16px;
    position: relative;
    margin-top: 15px;
}
.term-wrapper::before {
    content: "HUD_CONSOLE // STREAM";
    position: absolute;
    top: -9px; left: 18px;
    background: #040507;
    padding: 0 8px;
    font-size: 9px;
    font-family: var(--font-mono);
    color: var(--neon-cyan);
    font-weight: bold;
    letter-spacing: 1.5px;
}
.term {
    font-family: var(--font-mono);
    font-size: 12.5px;
    color: var(--neon-green);
    max-height: 280px;
    overflow-y: auto;
    direction: ltr;
    text-align: left;
    white-space: pre-wrap;
    word-break: break-all;
    line-height: 1.5;
}

/* جداول های‌تک */
.table-wrapper {
    overflow-x: auto;
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.08);
}
table { width: 100%; border-collapse: collapse; background: rgba(0,0,0,0.3); }
th, td { padding: 14px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.04); font-size: 13.5px; }
th { background: rgba(18, 22, 32, 0.85); color: var(--neon-cyan); font-weight: 700; letter-spacing: 0.5px; }
tr:hover td { background: rgba(0, 242, 255, 0.03); }

/* مدال‌ها و بج‌ها */
.badge {
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.badge-active { background: rgba(0,255,170,0.12); color: var(--neon-green); border: 1px solid rgba(0,255,170,0.3); }
.badge-inactive { background: rgba(255,51,102,0.12); color: var(--neon-red); border: 1px solid rgba(255,51,102,0.3); }

/* کارت‌های نمایندگان */
.reseller-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 18px; }
.reseller-card {
    background: rgba(10, 13, 20, 0.85);
    border: 1px solid var(--border-glass);
    border-radius: 12px;
    padding: 18px;
    display: flex;
    flex-direction: column;
    transition: all 0.3s ease;
}
.reseller-card:hover {
    border-color: var(--neon-amber);
    transform: translateY(-4px);
    box-shadow: 0 10px 25px rgba(255,170,0,0.15);
}

/* تب‌ها و منوها */
.tab-container { display: flex; gap: 8px; margin-bottom: 18px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px; }
.tab-btn { background: transparent; border: 1px solid transparent; color: var(--text-muted); padding: 9px 18px; border-radius: 8px; cursor: pointer; font-weight: 700; font-family: inherit; font-size: 13px; }
.tab-btn.active { background: rgba(0, 242, 255, 0.12); border-color: var(--neon-cyan); color: var(--neon-cyan); }

.download-dropdown { position: relative; display: inline-block; }
.floating-dl-menu {
    display: none;
    position: absolute;
    background: #0a0d14;
    border: 1px solid var(--border-glass);
    border-radius: 8px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.8);
    z-index: 1000;
    min-width: 190px;
    left: 0; top: 100%; margin-top: 6px;
    overflow: hidden;
}
.floating-dl-menu a, .floating-dl-menu button {
    display: flex; align-items: center; gap: 10px; width: 100%; padding: 10px 14px;
    background: none; border: none; color: #d0d7de; text-align: right;
    font-family: inherit; font-size: 12.5px; cursor: pointer; text-decoration: none; transition: 0.2s;
}
.floating-dl-menu a:hover, .floating-dl-menu button:hover { background: rgba(0, 242, 255, 0.15); color: var(--neon-cyan); }

/* پاپ‌آپ‌ها و مودال‌ها */
.qr-modal, .swal-overlay {
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(3, 4, 7, 0.88);
    backdrop-filter: blur(10px);
    z-index: 9999;
    display: none;
    justify-content: center;
    align-items: center;
}
.qr-box, .swal-box {
    background: #090c12;
    border: 1px solid var(--neon-cyan);
    border-radius: 14px;
    padding: 26px;
    text-align: center;
    box-shadow: 0 0 35px rgba(0, 242, 255, 0.2);
    max-width: 380px;
    width: 90%;
}
.swal-overlay.active { display: flex; }

/* پروگرس بار */
.progress-container { width: 100%; height: 10px; background: rgba(0,0,0,0.6); border-radius: 8px; overflow: hidden; margin-top: 14px; border: 1px solid rgba(255,255,255,0.08); }
.progress-bar { height: 100%; width: 0%; transition: width 0.3s ease; }

/* واکنش‌گرایی موبایل و ویندوز */
@media (max-width: 768px) {
    body { padding: 10px; }
    .card { padding: 16px; border-radius: 10px; }
    th, td { padding: 10px 6px; font-size: 12px; }
    .reseller-grid { grid-template-columns: 1fr; }
    h2 { font-size: 1.1rem; }
    .btn { padding: 9px 12px; font-size: 12px; }
}
</style>
</head>
<body>

<form id="actionForm" method="POST" style="display:none;">
    <input type="hidden" name="action" id="actionForm_action">
    <input type="hidden" name="ext_iface" id="actionForm_ext_iface">
    <input type="hidden" name="ext_add_gb" id="actionForm_ext_add_gb">
    <input type="hidden" name="deduct_iface" id="actionForm_deduct_iface">
    <input type="hidden" name="deduct_sub_gb" id="actionForm_deduct_sub_gb">
    <input type="hidden" name="cp_iface" id="actionForm_cp_iface">
    <input type="hidden" name="cp_user" id="actionForm_cp_user">
    <input type="hidden" name="cp_pass1" id="actionForm_cp_pass1">
    <input type="hidden" name="cp_pass2" id="actionForm_cp_pass2">
    <input type="hidden" name="new_username" id="actionForm_new_username">
</form>

<div class="qr-modal" id="qrCodeModal" onclick="closeQrCodeModal()">
    <div class="qr-box" onclick="event.stopPropagation()">
        <h3 style="margin-top:0; color:var(--neon-green);"><i class="fas fa-qrcode"></i> اسکن QR کانفیگ</h3>
        <div style="background:#fff; padding:12px; border-radius:10px; display:inline-block; margin: 15px 0;">
            <img id="qrCodeImg" src="" alt="QR Code" style="width:200px; height:200px; display:block;">
        </div>
        <button class="btn btn-danger" style="width:100%;" onclick="closeQrCodeModal()"><i class="fas fa-times"></i> بستن</button>
    </div>
</div>

<div class="swal-overlay" id="customAlert">
    <div class="swal-box">
        <i class="fas fa-circle-info" style="font-size: 38px; color: var(--neon-cyan); margin-bottom: 14px;"></i>
        <h3 style="margin-top:0; color:#fff;" id="alertTitle">پیام سیستم</h3>
        <p style="color:var(--text-muted); font-size: 13.5px;" id="alertMessage"></p>
        <button class="btn btn-primary" style="width:100%; margin-top:15px;" onclick="document.getElementById('customAlert').classList.remove('active')">متوجه شدم</button>
    </div>
</div>

<div class="swal-overlay" id="customPrompt">
    <div class="swal-box">
        <h3 style="margin-top:0; color:var(--neon-cyan);" id="promptTitle">ورود اطلاعات</h3>
        <p style="color: var(--text-muted); font-size: 13px;" id="promptMessage"></p>
        <input type="text" id="promptInput" style="margin: 15px 0; width:100%; text-align:center;">
        <div style="display: flex; gap: 10px;">
            <button class="btn btn-primary" style="flex:1;" id="promptOk"><i class="fas fa-check"></i> تایید</button>
            <button class="btn btn-danger" style="flex:1;" onclick="closePrompt()"><i class="fas fa-times"></i> لغو</button>
        </div>
    </div>
</div>

<script>
function showAlert(title, msg) { document.getElementById('alertTitle').innerText = title; document.getElementById('alertMessage').innerText = msg; document.getElementById('customAlert').classList.add('active'); }
function showPrompt(title, msg, defaultVal, callback) { 
    document.getElementById('promptTitle').innerText = title; 
    document.getElementById('promptMessage').innerText = msg; 
    document.getElementById('promptInput').value = defaultVal || ''; 
    document.getElementById('customPrompt').classList.add('active'); 
    
    let oldBtn = document.getElementById('promptOk');
    let newBtn = oldBtn.cloneNode(true);
    oldBtn.parentNode.replaceChild(newBtn, oldBtn);
    
    newBtn.addEventListener('click', () => { 
        let val = document.getElementById('promptInput').value; 
        closePrompt(); 
        if(callback) { setTimeout(() => callback(val), 300); }
    });
}
function closePrompt() { document.getElementById('customPrompt').classList.remove('active'); }

function promptExtend(iface) {
    showPrompt("شارژ حجم", "حجم ترافیک افزایشی (گیگابایت) را وارد کنید:", "100", (val) => {
        let parsed = parseInt(val);
        if(!isNaN(parsed) && parsed > 0) {
            document.getElementById('actionForm_action').value = 'extend_reseller';
            document.getElementById('actionForm_ext_iface').value = iface;
            document.getElementById('actionForm_ext_add_gb').value = parsed;
            document.getElementById('actionForm').submit();
        } else showAlert("خطا", "مقدار وارد شده باید عدد مثبت باشد.");
    });
}

function promptDeduct(iface) {
    showPrompt("کسر حجم", "حجم ترافیک کسر شونده (گیگابایت) را وارد کنید:", "10", (val) => {
        let parsed = parseInt(val);
        if(!isNaN(parsed) && parsed > 0) {
            document.getElementById('actionForm_action').value = 'deduct_reseller';
            document.getElementById('actionForm_deduct_iface').value = iface;
            document.getElementById('actionForm_deduct_sub_gb').value = parsed;
            document.getElementById('actionForm').submit();
        } else showAlert("خطا", "مقدار وارد شده باید عدد مثبت باشد.");
    });
}

function promptPass(iface, user) {
    showPrompt("تغییر رمز عبور", "رمز عبور جدید را وارد کنید:", "", (p1) => {
        if(!p1) return;
        setTimeout(() => {
            showPrompt("تایید رمز عبور", "رمز عبور را مجدداً وارد کنید:", "", (p2) => {
                if(p1 === p2) {
                    document.getElementById('actionForm_action').value = 'change_reseller_pw';
                    document.getElementById('actionForm_cp_iface').value = iface;
                    document.getElementById('actionForm_cp_user').value = user;
                    document.getElementById('actionForm_cp_pass1').value = p1;
                    document.getElementById('actionForm_cp_pass2').value = p2;
                    document.getElementById('actionForm').submit();
                } else showAlert("خطا", "رمز عبور با تکرار آن تطابق ندارد.");
            });
        }, 300);
    });
}

function promptAdminPass(userStr) {
    let u = userStr.split(" ")[0];
    showPrompt("تغییر مشخصات مدیرکل", "نام کاربری جدید مدیرکل را وارد کنید:", u, (newUser) => { if(!newUser) return; promptPass('wg0', newUser); });
}

function promptMasterPanelPass() {
    showPrompt("تغییر رمز ورود پنل وب", "کلمه عبور جدید پنل را وارد کنید:", "", (newPass) => {
        if(!newPass || newPass.trim() === "") return;
        let form = document.createElement('form');
        form.method = 'POST';
        form.innerHTML = `<input type="hidden" name="action" value="change_master_panel_password"><input type="hidden" name="new_master_pass" value="${newPass}">`;
        document.body.appendChild(form);
        form.submit();
    });
}

function promptUsername(iface, oldUser) {
    showPrompt("تغییر نام کاربری نماینده", "نام کاربری جدید را وارد کنید (انگلیسی):", oldUser, (newUser) => {
        if(!newUser) return;
        newUser = newUser.trim();
        if(newUser === "") { showAlert("خطا", "نام کاربری نمی‌تواند خالی باشد."); return; }
        document.getElementById('actionForm_action').value = 'change_reseller_username';
        document.getElementById('actionForm_cp_iface').value = iface;
        document.getElementById('actionForm_new_username').value = newUser;
        document.getElementById('actionForm').submit();
    });
}
</script>

<div class="container">

<!-- 1. لایه لاگین اصلی پنل -->
<?php if (!$is_panel_authenticated): ?>
<div class="card" style="max-width: 440px; margin: 80px auto; border-color: var(--neon-cyan);">
    <h2><i class="fas fa-shield-halved"></i> ورود به مدیریت مرکزی</h2>
    <p style="color:var(--text-muted); font-size:13px; margin-bottom:20px;">اطلاعات احراز هویت مدیریت را وارد نمایید.</p>
    <?php if (!empty($master_login_err)): ?><div class="err" style="color:var(--neon-red); font-size:13px; margin-bottom:15px;"><i class="fas fa-circle-exclamation"></i> <?php echo htmlspecialchars($master_login_err); ?></div><?php endif; ?>
    <form method="POST">
        <input type="hidden" name="action" value="master_login">
        <div class="form-group"><label><i class="fas fa-user-shield"></i> نام کاربری (Username):</label><input type="text" name="m_user" required placeholder="User"></div>
        <div class="form-group"><label><i class="fas fa-key"></i> رمز عبور (Password):</label><input type="password" name="m_pass" required placeholder="Pass"></div>
        <button type="submit" class="btn btn-info" style="width:100%; padding:13px; font-size:15px;"><i class="fas fa-right-to-bracket"></i> تایید و ثبت نشست</button>
    </form>
</div>

<!-- 2. لایه ورود به سرور ریموت لینوکس -->
<?php elseif (!$in): ?>

<?php $saved_servers = get_saved_masters(); ?>
<?php if (!empty($saved_servers)): ?>
<div class="card" style="max-width: 480px; margin: 20px auto 30px auto; border-color: var(--neon-purple);">
    <h3 style="margin-top:0; margin-bottom: 16px; color:var(--neon-purple); display:flex; justify-content:space-between; align-items:center;">
        <span><i class="fas fa-server"></i> صندوق سرورهای ذخیره‌شده</span>
        <span class="badge badge-active" style="background:rgba(188,19,254,0.12); color:var(--neon-purple); border-color:var(--neon-purple);"><?php echo count($saved_servers); ?> سرور</span>
    </h3>
    
    <div style="display:flex; flex-direction:column; gap:10px;">
        <?php foreach($saved_servers as $shost => $sdata): ?>
        <div style="display:flex; align-items:stretch; gap:8px; background: rgba(0,0,0,0.5); padding: 8px 12px; border-radius: 8px; border: 1px solid rgba(188,19,254,0.2);">
            <form method="POST" style="margin:0; flex-grow:1;">
                <input type="hidden" name="action" value="fast_login">
                <input type="hidden" name="fast_host" value="<?php echo htmlspecialchars($shost); ?>">
                <button type="submit" class="btn" style="width:100%; height:100%; padding:8px; display:flex; justify-content:space-between; align-items:center; background:transparent; border:none; color:var(--text-primary); cursor:pointer;">
                    <div style="display:flex; align-items:center; gap:12px; text-align:right;">
                        <i class="fas fa-network-wired" style="color:var(--neon-cyan); font-size:18px;"></i>
                        <div>
                            <div style="font-family:var(--font-mono); font-weight:700; color:#fff;"><?php echo htmlspecialchars($shost); ?></div>
                            <div style="font-size:11px; color:var(--text-muted);"><i class="fas fa-user"></i> <?php echo htmlspecialchars($sdata['u']); ?> &nbsp;|&nbsp; <i class="fas fa-plug"></i> <?php echo htmlspecialchars($sdata['p']); ?></div>
                        </div>
                    </div>
                    <i class="fas fa-arrow-right-to-bracket" style="color:var(--neon-green); font-size:16px;"></i>
                </button>
            </form>
            <form method="POST" style="margin:0; display:flex;" onsubmit="return confirm('آیا از حذف این سرور اطمینان دارید؟');">
                <input type="hidden" name="action" value="delete_saved_master">
                <input type="hidden" name="del_host" value="<?php echo htmlspecialchars($shost); ?>">
                <button type="submit" class="btn btn-danger" style="padding:0 12px; border-radius:6px;"><i class="fas fa-trash-can"></i></button>
            </form>
        </div>
        <?php endforeach; ?>
    </div>
</div>
<?php endif; ?>

<div class="card" style="max-width: 480px; margin: <?php echo empty($saved_servers) ? '80px' : '0'; ?> auto;">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <h2><i class="fas fa-terminal"></i> اتصال به سرور ریموت SSH</h2>
        <a href="?action=master_logout" class="btn btn-danger" style="padding: 5px 10px; font-size: 11px;"><i class="fas fa-power-off"></i> خروج</a>
    </div>
    <p style="color:var(--text-muted); font-size:13px; margin-bottom:20px;">اطلاعات دسترسی لینوکس را وارد کنید.</p>
    <?php if (!empty($err)): ?><div class="err" style="color:var(--neon-red); font-size:13px; margin-bottom:15px; background:rgba(255,51,102,0.1); padding:10px; border-radius:8px; border:1px solid rgba(255,51,102,0.3);"><i class="fas fa-triangle-exclamation"></i> <?php echo htmlspecialchars($err); ?></div><?php endif; ?>
    
    <form method="POST">
        <input type="hidden" name="action" value="login">
        <div class="form-group"><label><i class="fas fa-globe"></i> Host (IP):</label><input type="text" name="host" value="<?php echo htmlspecialchars($h_v ?? ''); ?>" required placeholder="192.168.1.1"></div>
        <div class="form-group"><label><i class="fas fa-network-wired"></i> Port:</label><input type="number" name="port" value="<?php echo htmlspecialchars($p_v ?? '22'); ?>" required></div>
        <div class="form-group"><label><i class="fas fa-user"></i> Username:</label><input type="text" name="username" value="<?php echo htmlspecialchars($u_v ?? 'root'); ?>" required></div>
        <div class="form-group"><label><i class="fas fa-lock"></i> Password:</label><input type="password" name="password" required autocomplete="off"></div>
        <div class="form-group">
            <label style="display:flex; align-items:center; gap:10px; cursor:pointer; background: rgba(0,242,255,0.05); padding: 10px; border-radius: 8px; border: 1px dashed rgba(0,242,255,0.2);">
                <input type="checkbox" name="rem" value="yes" checked style="width: 16px; height: 16px; accent-color: var(--neon-cyan); margin:0;"> 
                <span style="color:#fff;">ذخیره سرور در صندوق Fast Login</span>
            </label>
        </div>
        <button type="submit" class="btn btn-primary" style="width:100%; padding:13px; font-size:15px;"><i class="fas fa-link"></i> اتصال و پردازش دیتاسنتر</button>
    </form>
</div>
<?php else: ?>

<!-- پنل اصلی داشبورد -->
<div class="card" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; padding: 16px 24px;">
    <div>
        <h2 style="border:none; margin:0; padding:0; font-size:17px;">
            <i class="fas fa-server"></i> سرور متصل: <span style="color:var(--neon-cyan); font-family:var(--font-mono);"><?php echo htmlspecialchars($h); ?></span>
        </h2>
    </div>
    <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <a href="test_diagnostic.php" class="btn btn-info"><i class="fas fa-images"></i> تصاویر و قالب</a>
        <form method="POST" style="margin:0;"><input type="hidden" name="action" value="optimize_gaming"><button type="submit" class="btn btn-gaming"><i class="fas fa-bolt"></i> بهینه‌سازی پینگ</button></form>
        <form method="POST" style="margin:0;"><input type="hidden" name="action" value="sync_ips"><button type="submit" class="btn" style="border-color:var(--neon-purple); color:var(--neon-purple);"><i class="fas fa-broom"></i> پاکسازی شبکه</button></form>
        <a href="?action=logout" class="btn" style="border-color: var(--neon-amber); color: var(--neon-amber);"><i class="fas fa-arrow-right-from-bracket"></i> تغییر سرور</a>
        <a href="?action=master_logout" class="btn btn-danger"><i class="fas fa-power-off"></i> خروج نهایی</a>
    </div>
</div>

<?php if(!empty($sync_log) || !empty($gaming_log) || !empty($reseller_log) || !empty($detailed_migration_log)): ?>
<div class="card term-wrapper">
    <div class="term">
        <?php 
            if(!empty($sync_log)) echo htmlspecialchars($sync_log) . "\n";
            if(!empty($gaming_log)) echo htmlspecialchars($gaming_log) . "\n";
            if(!empty($reseller_log)) echo htmlspecialchars($reseller_log) . "\n";
            if(!empty($detailed_migration_log)) echo htmlspecialchars($detailed_migration_log) . "\n";
        ?>
    </div>
</div>
<?php endif; ?>

<div class="card">
    <h2><i class="fas fa-users-gear"></i> نمای کلی کاربران شبکه</h2>
    <?php
    $py_db = "import sqlite3\ntry:\n for r in sqlite3.connect('{$d_path}', timeout=30.0).cursor().execute('SELECT peer_name, peer_ip, public_key, [limit], used, remaining_time, monitor_blocked, expiry_blocked, token FROM peers').fetchall(): print(f\"{r[0]}|{r[1]}|{r[2]}|{r[3]}|{r[4]}|{r[5]}|{r[6]}|{r[7]}|{r[8]}\")\nexcept Exception as e: print(f'error:{e}')\n";
    $s = @ssh2_exec($conn, "{$py_bin} -c " . escapeshellarg($py_db));
    if ($s) {
        stream_set_blocking($s, true);
        $out = trim(stream_get_contents($s));
        fclose($s);
    } else {
        $out = "";
    }

    if (empty($out) || strpos($out, 'error:') === 0) { 
        echo "<p style='color:var(--text-muted); text-align:center;'>هیچ کاربری در دیتابیس یافت نشد.</p>"; 
    } else {
        $l = array_filter(explode("\n", $out));
        $tp = ceil(count($l) / 10);
        $cp = max(1, min($tp, (int)($_GET['page'] ?? 1)));
        $pg = array_slice($l, ($cp - 1) * 10, 10);
        
        echo "<div class='table-wrapper'><table>";
        echo "<tr><th>نام کاربر</th><th>آی‌پی اختصاصی</th><th>حجم کل</th><th>مصرف شده</th><th>وضعیت</th><th>مدیریت</th></tr>";
        foreach ($pg as $ln) {
            $c = explode("|", $ln);
            if (count($c) >= 6) {
                $rem = intval($c[5]);
                $m_blk = intval($c[6] ?? 0);
                $e_blk = intval($c[7] ?? 0);
                $token = htmlspecialchars($c[8] ?? '');
                
                if ($m_blk || $e_blk || $rem <= 0) {
                    $status = "<span class='badge badge-inactive'><i class='fas fa-circle-xmark'></i> منقضی / مسدود</span>";
                } else {
                    $status = "<span class='badge badge-active'><i class='fas fa-circle-check'></i> فعال ({$rem} دقیقه)</span>";
                }
                
                echo "<tr>
                        <td><strong>" . htmlspecialchars($c[0]) . "</strong></td>
                        <td style='font-family:var(--font-mono);'>" . htmlspecialchars($c[1]) . "</td>
                        <td>" . htmlspecialchars($c[3]) . "</td>
                        <td style='color:var(--neon-amber); font-weight:bold;'>" . fb($c[4]) . "</td>
                        <td>{$status}</td>
                        <td>
                            <div class='download-dropdown'>
                                <button class='btn btn-info' onclick='toggleFloatingMenu(event, \"{$token}\")' style='padding: 6px 12px; font-size:12px;'>
                                    <i class='fas fa-bars'></i> دریافت کانفیگ
                                </button>
                                <div class='floating-dl-menu' id='menu-{$token}'>
                                    <a href='http://{$h}:5000/api/download-peer-config?token={$token}' target='_blank'>
                                        <i class='fas fa-file-arrow-down' style='color:var(--neon-cyan);'></i> دانلود فایل .conf
                                    </a>
                                    <button onclick='copySubLink(\"{$token}\")'>
                                        <i class='fas fa-copy' style='color:var(--neon-amber);'></i> کپی ساب‌لینک
                                    </button>
                                    <button onclick='showQrCodeModal(\"{$token}\")'>
                                        <i class='fas fa-qrcode' style='color:var(--neon-green);'></i> نمایش کد QR
                                    </button>
                                </div>
                            </div>
                        </td>
                      </tr>";
            }
        }
        echo "</table></div>";
        
        if ($tp > 1) {
            echo "<div style='display:flex; flex-direction:column; gap:10px; margin-top:18px; direction:ltr; align-items:center;'>";
            $pages = range(1, $tp);
            $chunks = array_chunk($pages, 16);
            foreach ($chunks as $chunk) {
                echo "<div style='display:flex; gap:4px; flex-wrap:wrap; justify-content:center;'>";
                foreach ($chunk as $i) {
                    $cls = ($i == $cp) ? "btn btn-primary" : "btn";
                    echo "<a href='?page={$i}' class='{$cls}' style='padding:4px 9px; min-width:30px; text-align:center;'>{$i}</a>";
                }
                echo "</div>";
            }
            echo "</div>";
        }
    }
    ?>
</div>

<div class="card">
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; margin-bottom:15px; gap:10px;">
        <h2><i class="fas fa-network-wired"></i> پورتال نمایندگان و کارت‌های شبکه</h2>
        <div style="display:flex; gap:8px;">
            <form method="POST" style="margin:0;"><input type="hidden" name="action" value="audit_resellers"><button type="submit" class="btn" style="border-color:var(--neon-green); color:var(--neon-green);"><i class="fas fa-screwdriver-wrench"></i> ممیزی و احیای نمایندگان</button></form>
            <div style="position:relative;">
                <input type="text" id="resellerSearch" onkeyup="filterResellers()" placeholder="جستجوی اینترفیس..." style="width:200px; padding-right:12px; border-radius:20px;">
            </div>
        </div>
    </div>
    
    <div class="reseller-grid" id="resellerGrid">
<?php
$py_resellers = <<<'PYTHON'
import sqlite3, os, re, json, sys
try:
    db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
    confs_dir = '/etc/wireguard'
    registered_panels = {}

    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path, timeout=5.0)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sub_panels'")
        if cur.fetchone():
            cur.execute("SELECT interface_name, username, data_limit_gb, port, status, password_plain, deleted_traffic FROM sub_panels")
            for r in cur.fetchall():
                registered_panels[r[0]] = {
                    "u": r[1] if r[1] else "N/A", "l": float(r[2]) if r[2] is not None else 100.0, 
                    "p": r[3] if r[3] else "N/A", "s": r[4] if r[4] else "active", "pw": r[5] if r[5] else "N/A",
                    "del_traf": int(r[6]) if r[6] else 0
                }
        
        universal_vault = {}
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='interface_vault'")
        if cur.fetchone():
            cur.execute("SELECT interface_name, vault_bytes FROM interface_vault")
            for iv_name, iv_bytes in cur.fetchall():
                universal_vault[iv_name] = iv_bytes or 0
                
        admin_deleted = 0
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='global_deleted_traffic'")
        if cur.fetchone():
            cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1")
            row_del = cur.fetchone()
            admin_deleted = row_del[0] if row_del else 0
            
        conn.close()

    all_confs = []
    if os.path.exists(confs_dir):
        all_confs = [f.replace('.conf','') for f in os.listdir(confs_dir) if f.endswith('.conf')]
    if 'wg0' not in all_confs: all_confs.append('wg0')

    conn_db = sqlite3.connect(db_path, timeout=10.0)
    cur_db = conn_db.cursor()

    for name in sorted(list(set(all_confs))):
        port = "51820"
        subnet_ip = "10.0.10.1/24"
        conf_file_path = f"/etc/wireguard/{name}.conf"
        if os.path.exists(conf_file_path):
            with open(conf_file_path, "r", encoding="utf-8") as cf:
                content = cf.read()
                port_match = re.search(r"ListenPort\s*=\s*(\d+)", content, re.IGNORECASE)
                if port_match: port = port_match.group(1)
                subnet_match = re.search(r"Address\s*=\s*([^\s]+)", content, re.IGNORECASE)
                if subnet_match: subnet_ip = subnet_match.group(1).strip()

        cur_db.execute("SELECT SUM(used) FROM peers WHERE config=?", (f"{name}.conf",))
        live_used = cur_db.fetchone()[0] or 0

        vault_traffic = 0
        if name == 'wg0':
            vault_traffic = admin_deleted + universal_vault.get('wg0', 0)
        else:
            del_t = registered_panels[name]['del_traf'] if name in registered_panels else 0
            vault_t = universal_vault.get(name, 0)
            vault_traffic = max(del_t, vault_t)

        total_bytes = live_used + vault_traffic
        used_gb = total_bytes / 1073741824.0

        is_act = "active" if os.path.exists(f"/sys/class/net/{name}") else "disabled"

        if name == 'wg0':
            adm_u, adm_p = "Pars", "Pars"
            row = cur_db.execute("SELECT username, password_plain FROM users LIMIT 1").fetchone()
            if row: adm_u, adm_p = row[0], row[1] or "Pars"
            
            cur_db.execute("SELECT SUM(used) FROM peers")
            all_live = cur_db.fetchone()[0] or 0
            cur_db.execute("SELECT SUM(deleted_traffic) FROM sub_panels")
            all_del_subs = cur_db.fetchone()[0] or 0
            cur_db.execute("SELECT SUM(vault_bytes) FROM interface_vault")
            all_vaults = cur_db.fetchone()[0] or 0
            
            tot_bytes_global = all_live + admin_deleted + all_del_subs + all_vaults
            tot_gb = tot_bytes_global / 1073741824.0
            
            print(f"wg0|{adm_u} (مدیر کل)|INF|{used_gb:.2f}|INF|{port}|{is_act}|{adm_p}|{tot_gb:.2f}|{subnet_ip}")
        elif name in registered_panels:
            p = registered_panels[name]
            real_status = p['s']
            rem = max(0, p['l'] - used_gb)
            print(f"{name}|{p['u']}|{p['l']:.2f}|{used_gb:.2f}|{rem:.2f}|{port}|{real_status}|{p['pw']}|0|{subnet_ip}")
        else:
            rem = max(0, 100.0 - used_gb)
            print(f"{name}|بدون نماینده (پیش‌فرض)|100.00|{used_gb:.2f}|{rem:.2f}|{port}|{is_act}|N/A|0|{subnet_ip}")
            
    conn_db.close()
except Exception as e:
    print(f"Error: {e}")
PYTHON;
    $sr = @ssh2_exec($conn, "{$py_bin} -c " . escapeshellarg($py_resellers) . " 2>&1");
    $r_data = "";
    if ($sr) {
        stream_set_blocking($sr, true);
        while ($line = fgets($sr)) { $r_data .= $line; }
        fclose($sr);
        $r_data = trim($r_data);
    }
    $server_interfaces = [];

    if (!empty($r_data) && strpos($r_data, 'Error:') === false) {
        foreach (explode("\n", $r_data) as $rl) {
            $rd = explode("|", trim($rl));
            if (count($rd) >= 10) {
                $iface_name = trim($rd[0]);
                $server_interfaces[] = $iface_name;
                
                $status_code = trim($rd[6]);
                if ($status_code === 'active') {
                    $badge = "<span class='badge badge-active'><i class='fas fa-circle-check'></i> فعال</span>";
                } elseif ($status_code === 'suspended') {
                    $badge = "<span class='badge badge-inactive' style='color:var(--neon-amber); border-color:var(--neon-amber);'><i class='fas fa-pause'></i> تعلیق دستی</span>";
                } else {
                    $badge = "<span class='badge badge-inactive'><i class='fas fa-ban'></i> تعلیق حجم</span>";
                }
                
                register_local_interface($h, $rd[0], [
                    'interface_name' => $rd[0],
                    'username' => $rd[1],
                    'password_plain' => $rd[7],
                    'data_limit_gb' => ($rd[2] === 'INF') ? 0 : floatval($rd[2]),
                    'port' => intval($rd[5]),
                    'subnet_ip' => $rd[9],
                    'used_gb' => floatval($rd[3]),
                    'status' => $status_code
                ]);
                ?>
                <div class="reseller-card r-item" data-search="<?= strtolower($rd[0].' '.$rd[1]) ?>">
                  <div style="display:flex; justify-content:space-between; margin-bottom:12px; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:8px;">
                     <h3 style="margin:0; font-size:15px;"><i class="fas fa-ethernet"></i> <?= htmlspecialchars($rd[0]) ?></h3>
                     <?= $badge ?>
                 </div>
                <div style="font-size:12.5px; color:var(--text-muted); line-height:1.7; flex-grow:1;">
                        <div style="display:flex; justify-content:space-between;"><span><i class="fas fa-user"></i> کاربری:</span> <span style="color:#fff;"><?= htmlspecialchars($rd[1]) ?></span></div>
                        <div style="display:flex; justify-content:space-between;"><span><i class="fas fa-key"></i> رمز عبور:</span> 
                            <div><span id="pw-<?= $rd[0] ?>" data-pw="<?= htmlspecialchars($rd[7]) ?>">••••••••</span> <i class="fas fa-eye" onclick="togglePw('<?= $rd[0] ?>')" style="cursor:pointer; color:var(--neon-cyan); margin-right:5px;"></i></div>
                        </div>
                        <div style="display:flex; justify-content:space-between;"><span><i class="fas fa-plug"></i> پورت:</span> <span style="color:var(--neon-cyan); font-family:var(--font-mono);"><?= htmlspecialchars($rd[5]) ?></span></div>
                        <div style="display:flex; justify-content:space-between;"><span><i class="fas fa-diagram-project"></i> ساب‌نت:</span> <span style="color:var(--neon-purple); font-family:var(--font-mono);"><?= htmlspecialchars($rd[9]) ?></span></div>
                        <?php if ($rd[0] === 'wg0'): ?>
                            <div style="display:flex; justify-content:space-between;"><span><i class="fas fa-chart-pie"></i> مصرف تجمیعی کل:</span> <span id="total-<?= $rd[0] ?>" style="color:var(--neon-green); font-family:var(--font-mono);"><?= htmlspecialchars($rd[8] ?? '0.00') ?> GB</span></div>
                        <?php endif; ?>
                        <div style="display:flex; justify-content:space-between;"><span><i class="fas fa-database"></i> حجم مجاز:</span> <span style="color:#fff;"><?= htmlspecialchars($rd[2]) ?> GB</span></div>
                        <div style="display:flex; justify-content:space-between;"><span><i class="fas fa-arrow-trend-up"></i> مصرف‌شده:</span> <span id="used-<?= $rd[0] ?>" style="color:var(--neon-amber); font-weight:bold;"><?= htmlspecialchars($rd[3]) ?> GB</span></div>
                        <div style="display:flex; justify-content:space-between;"><span><i class="fas fa-hourglass-half"></i> باقی‌مانده:</span> <span id="rem-<?= $rd[0] ?>" style="color:var(--neon-green); font-weight:bold;"><?= htmlspecialchars($rd[4]) ?> GB</span></div>
                  </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:14px;">
                        <?php if ($rd[0] !== 'wg0'): ?>
                            <form method="POST" style="margin:0;">
                                <input type="hidden" name="action" value="toggle_reseller"><input type="hidden" name="t_iface" value="<?= $rd[0] ?>"><input type="hidden" name="t_status" value="<?= $rd[6] ?>">
                                <button class="btn <?= ($status_code === 'active') ? 'btn-danger' : 'btn-info' ?>" style="width:100%; padding:7px; font-size:11.5px;"><?= ($status_code === 'active') ? '<i class="fas fa-pause"></i> تعلیق' : '<i class="fas fa-play"></i> فعال' ?></button>
                            </form>
                            <div style="display:flex; gap:4px;">
                                <button onclick="promptExtend('<?= $rd[0] ?>')" class="btn" style="flex:1; padding:7px 2px; font-size:11px; border-color:var(--neon-green); color:var(--neon-green);"><i class="fas fa-plus"></i> شارژ</button>
                                <button onclick="promptDeduct('<?= $rd[0] ?>')" class="btn btn-danger" style="flex:1; padding:7px 2px; font-size:11px;"><i class="fas fa-minus"></i> کسر</button>
                            </div>
                            
                            <div style="display:flex; gap:4px;">
                                <button onclick="promptUsername('<?= $rd[0] ?>', '<?= $rd[1] ?>')" class="btn" style="flex:1; padding:7px 2px; font-size:11px; border-color:var(--neon-cyan); color:var(--neon-cyan);"><i class="fas fa-user-pen"></i> یوزر</button>
                                <button onclick="promptPass('<?= $rd[0] ?>', '<?= $rd[1] ?>')" class="btn" style="flex:1; padding:7px 2px; font-size:11px; border-color:var(--neon-cyan); color:var(--neon-cyan);"><i class="fas fa-key"></i> رمز</button>
                            </div>
                            
                            <form method="POST" style="margin:0;" onsubmit="return confirm('حذف کامل اینترفیس <?= $rd[0] ?>؟');">
                                <input type="hidden" name="action" value="delete_reseller"><input type="hidden" name="del_iface" value="<?= $rd[0] ?>">
                                <button class="btn btn-danger" style="width:100%; padding:7px; font-size:11.5px;"><i class="fas fa-trash-can"></i> حذف</button>
                            </form>
                        <?php else: ?>
                            <button onclick="promptAdminPass('<?= $rd[1] ?>')" class="btn" style="width:100%; padding:8px; font-size:11.5px; border-color:var(--neon-amber); color:var(--neon-amber);"><i class="fas fa-user-shield"></i> تغییر مشخصات WireGuard</button>
                            <button onclick="promptMasterPanelPass()" class="btn btn-info" style="width:100%; padding:8px; font-size:11.5px;"><i class="fas fa-lock"></i> تغییر رمز پنل</button>
                        <?php endif; ?>
                    </div>
                </div>
                <?php
            }
        }
    }
    ?>
    </div>

    <div style="margin-top: 24px; background: rgba(0, 242, 255, 0.04); padding: 20px; border-radius: 10px; border: 1px dashed var(--border-glass);">
        <h3 style="margin-top:0;"><i class="fas fa-square-plus"></i> ساخت اینترفیس نماینده جدید</h3>
        <form method="POST" style="display:flex; flex-wrap:wrap; gap:12px; align-items:flex-end;">
            <input type="hidden" name="action" value="create_reseller">
            <div style="flex:1; min-width:130px;"><label>کارت شبکه (مثال: wg1):</label><input type="text" name="r_iface" required placeholder="wg1"></div>
            <div style="flex:1; min-width:130px;"><label>سقف حجم (GB):</label><input type="number" name="r_limit" required value="100" min="1"></div>
            <div style="flex:1; min-width:130px;"><label>نام کاربری:</label><input type="text" name="r_user" required placeholder="حروف انگلیسی"></div>
            <div style="flex:1; min-width:130px;"><label>رمز عبور:</label><input type="password" name="r_pass" required placeholder="کلمه عبور امن"></div>
            <div style="flex:1; min-width:180px;"><button type="submit" class="btn btn-primary" style="width:100%; padding:12px;"><i class="fas fa-wand-magic-sparkles"></i> استقرار نماینده</button></div>
        </form>
    </div>
</div>

<div class="card">
    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.08); margin-bottom:14px; padding-bottom:10px;">
        <h2><i class="fas fa-microchip"></i> دیتابیس پایدار و مانیتورینگ محلی</h2>
        <span class="badge badge-active" style="border-color:var(--neon-cyan); color:var(--neon-cyan);"><i class="fas fa-shield-check"></i> Local Vault</span>
    </div>
    <div class="table-wrapper">
        <table>
            <tr><th>سرور</th><th>اینترفیس</th><th>کاربر</th><th>حجم مجاز</th><th>ترافیک مصرفی</th><th>ساب‌نت</th><th>پورت</th></tr>
            <?php
            $local_reg = get_local_registry();
            if (empty($local_reg)) {
                echo "<tr><td colspan='7' style='color:var(--text-muted);'>داده‌ای ثبت نشده است.</td></tr>";
            } else {
                foreach ($local_reg as $srv_ip => $srv_meta) {
                    $ifaces = $srv_meta['interfaces'] ?? [];
                    if (empty($ifaces)) {
                        echo "<tr><td style='font-family:var(--font-mono);'>" . htmlspecialchars($srv_ip) . "</td><td colspan='6' style='color:var(--text-muted);'>خالی</td></tr>";
                    } else {
                        foreach ($ifaces as $inf_name => $inf_det) {
                            $lim = (isset($inf_det['data_limit_gb']) && $inf_det['data_limit_gb'] > 0) ? htmlspecialchars($inf_det['data_limit_gb']) . ' GB' : 'بدون سقف (INF)';
                            echo "<tr>
                                <td style='font-family:var(--font-mono); color:var(--neon-cyan);'>" . htmlspecialchars($srv_ip) . "</td>
                                <td><span class='badge badge-active'>" . htmlspecialchars($inf_name) . "</span></td>
                                <td>" . htmlspecialchars($inf_det['username'] ?? 'N/A') . "</td>
                                <td>{$lim}</td>
                                <td style='color:var(--neon-amber); font-weight:bold;'>" . htmlspecialchars(number_format($inf_det['used_gb'] ?? 0, 2)) . " GB</td>
                                <td style='font-family:var(--font-mono); color:var(--neon-purple);'>" . htmlspecialchars($inf_det['subnet_ip'] ?? 'N/A') . "</td>
                                <td style='font-family:var(--font-mono); color:var(--neon-green);'>" . htmlspecialchars($inf_det['port'] ?? 'N/A') . "</td>
                            </tr>";
                        }
                    }
                }
            }
            ?>
        </table>
    </div>
</div>

<div class="card">
    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.08); margin-bottom:14px; padding-bottom:10px;">
        <h2><i class="fas fa-robot"></i> ربات تلگرام و پایش هوشمند</h2>
        <?php if ($b_on): ?><span class="badge badge-active"><i class="fas fa-circle-check"></i> وضعیت: روشن</span><?php else: ?><span class="badge badge-inactive"><i class="fas fa-circle-xmark"></i> وضعیت: خاموش</span><?php endif; ?>
    </div>
    <form method="POST">
        <div class="form-group"><label>توکن ربات (Bot Token):</label><input type="text" name="bot_token" value="<?php echo htmlspecialchars($s_tok); ?>" required></div>
        <div class="form-group"><label>Chat ID ادمین:</label><input type="text" name="chat_id" value="<?php echo htmlspecialchars($s_cid); ?>" required></div>
        <div class="form-group"><label>وضعیت ارسال خودکار هر ۶ ساعت:</label>
            <select name="status_toggle">
                <option value="on" <?php echo $b_on ? 'selected' : ''; ?>>روشن</option>
                <option value="off" <?php echo !$b_on ? 'selected' : ''; ?>>خاموش</option>
            </select>
        </div>
        <div style="display: flex; gap: 8px; margin-top: 15px; flex-wrap: wrap;">
            <button type="submit" name="bot_action" value="toggle" class="btn" style="flex: 2; min-width:180px;"><i class="fas fa-floppy-disk"></i> ذخیره و اعمال وضعیت</button>
            <button type="submit" name="bot_action" value="test_send" class="btn btn-info" style="flex: 1; min-width:120px;"><i class="fas fa-paper-plane"></i> تست پیام</button>
            <button type="submit" name="bot_action" value="set_webhook" class="btn" style="flex: 1; min-width:120px; border-color:var(--neon-purple); color:var(--neon-purple);"><i class="fas fa-globe"></i> وب‌هوک</button>
        </div>
    </form>
    <form method="POST" action="" style="margin-top:10px;">
        <button type="submit" name="get_metrics" value="1" class="btn btn-gaming" style="width: 100%;"><i class="fas fa-chart-simple"></i> دریافت فوری منابع سرور در تلگرام</button>
    </form>
    <?php if (!empty($t_logs)): ?><div class="term" style="margin-top: 15px;"><?php echo htmlspecialchars($t_logs); ?></div><?php endif; ?>
</div>

<div class="card">
    <div class="tab-container">
        <button class="tab-btn active" onclick="switchTab('master_tab')"><i class="fas fa-hard-drive"></i> انتقال سرور مادر و بازیابی بک‌آپ</button>
        <button class="tab-btn" onclick="switchTab('edge_tab')"><i class="fas fa-satellite-dish"></i> انتقال سرور لبه (Edge)</button>
    </div>

    <div id="master_tab" class="tab-content">
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); gap:18px;">
            <div class="card" style="margin-bottom:0; border:none; padding:0; background:transparent;">
                <h2><i class="fas fa-file-zipper"></i> بازیابی بک‌آپ دستی (.zip)</h2>
                <form id="uf" enctype="multipart/form-data" method="POST" action="">
                    <div class="form-group"><input type="file" name="backup_file" id="bf" accept=".zip" required style="padding:8px; background:rgba(255,255,255,0.05); border:1px dashed var(--text-muted);"></div>
                    <button type="button" id="ubtn" class="btn" style="width:100%;"><i class="fas fa-cloud-arrow-up"></i> آپلود و بازیابی کامل</button>
                </form>
                <div id="pra" style="display:none; margin-top:14px;">
                    <div class="progress-container"><div class="progress-bar" id="nf" style="background:var(--neon-green); box-shadow: 0 0 10px var(--neon-green);"></div></div>
                    <div style="text-align:center; font-size:12px; margin-top:5px; color:var(--neon-green);" id="pt">0%</div>
                </div>
            </div>

            <div class="card" style="margin-bottom:0; border:none; padding:0; background:transparent;">
                <h2><i class="fas fa-arrows-split-up-and-left"></i> انتقال سرور به سرور (Migration)</h2>
                <form id="mf" method="POST">
                    <input type="hidden" name="migrate_server" value="1">
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
                        <div class="form-group" style="margin-bottom:8px;"><input type="text" name="m_host" required placeholder="IP مقصد"></div>
                        <div class="form-group" style="margin-bottom:8px;"><input type="number" name="m_port" value="22" required placeholder="Port"></div>
                        <div class="form-group" style="margin-bottom:0;"><input type="text" name="m_user" value="root" required placeholder="User"></div>
                        <div class="form-group" style="margin-bottom:0;"><input type="password" name="m_pass" required placeholder="Password"></div>
                    </div>
                    <button type="button" id="mbtn" class="btn btn-primary" style="width:100%; margin-top:14px;"><i class="fas fa-jet-fighter"></i> شروع انتقال زنده به مقصد</button>
                </form>
                <div id="mra" style="display:none; margin-top:14px;">
                    <div class="progress-container"><div class="progress-bar" id="mnf" style="background:var(--neon-amber); box-shadow: 0 0 10px var(--neon-amber);"></div></div>
                    <div style="text-align:center; font-size:12px; margin-top:5px; color:var(--neon-amber);" id="mpt">در حال انتقال داده‌ها...</div>
                </div>
            </div>
        </div>
    </div>

    <div id="edge_tab" class="tab-content" style="display:none;">
        <h2><i class="fas fa-satellite-dish"></i> انتقال سرور لبه به لبه (Edge-to-Edge)</h2>
        <p style="font-size:13px; color:var(--text-muted);">اطلاعات فرزند مبدا و مقصد را وارد نمایید تا کانفیگ‌ها و ترافیک منتقل شوند.</p>
        <form method="POST">
            <input type="hidden" name="action" value="migrate_edge">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                <div class="card" style="margin-bottom:0; background:rgba(0,0,0,0.3); padding:16px;">
                    <h3 style="margin-top:0; font-size:14px; color:var(--neon-red);"><i class="fas fa-location-crosshairs"></i> لبه مبدا (قدیمی)</h3>
                    <div class="form-group"><input type="text" name="old_edge_ip" placeholder="IP مبدا" required></div>
                    <div class="form-group" style="margin-bottom:0;"><input type="password" name="old_edge_pass" placeholder="Password مبدا" required></div>
                </div>
                <div class="card" style="margin-bottom:0; background:rgba(0,0,0,0.3); padding:16px;">
                    <h3 style="margin-top:0; font-size:14px; color:var(--neon-green);"><i class="fas fa-rocket"></i> لبه مقصد (جدید)</h3>
                    <div class="form-group"><input type="text" name="new_edge_ip" placeholder="IP مقصد" required></div>
                    <div class="form-group" style="margin-bottom:0;"><input type="password" name="new_edge_pass" placeholder="Password مقصد" required></div>
                </div>
            </div>
            <button type="submit" class="btn btn-primary" style="width:100%; margin-top:16px;"><i class="fas fa-rotate"></i> شروع انتقال سرور فرزند</button>
        </form>
    </div>
</div>

<?php endif; ?>
</div>

<script>
function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).style.display = 'block';
    if(event && event.currentTarget) {
        event.currentTarget.classList.add('active');
    }
}

function toggleFloatingMenu(e, token) {
    e.preventDefault(); e.stopPropagation();
    document.querySelectorAll('.floating-dl-menu').forEach(m => { if (m.id !== 'menu-' + token) m.style.display = 'none'; });
    const menu = document.getElementById('menu-' + token);
    if (menu) { menu.style.display = (menu.style.display === 'block') ? 'none' : 'block'; }
}

document.addEventListener('click', function() { document.querySelectorAll('.floating-dl-menu').forEach(m => m.style.display = 'none'); });

function copySubLink(token) {
    const link = `http://<?php echo htmlspecialchars($h); ?>:5000/s/${token}`;
    navigator.clipboard.writeText(link).then(() => { showAlert("انجام شد", "لینک اشتراک کپی شد."); }).catch(err => { showAlert("خطا", "عدم امکان کپی لینک."); });
}

function showQrCodeModal(token) {
    document.getElementById('qrCodeImg').src = `http://<?php echo htmlspecialchars($h); ?>:5000/api/qr-code?token=${token}`;
    document.getElementById('qrCodeModal').style.display = 'flex';
}
function closeQrCodeModal() { document.getElementById('qrCodeModal').style.display = 'none'; }

function filterResellers() {
    let input = document.getElementById('resellerSearch').value.toLowerCase();
    let cards = document.querySelectorAll('.r-item');
    cards.forEach(c => { c.style.display = c.getAttribute('data-search').includes(input) ? "flex" : "none"; });
}

function togglePw(id) {
    let span = document.getElementById('pw-'+id);
    if(span.innerText === '••••••••') { 
        span.innerText = span.getAttribute('data-pw'); 
        span.style.color = '#fff'; 
    } else { 
        span.innerText = '••••••••'; 
        span.style.color = 'var(--text-muted)'; 
    }
}

// موتور لایو سینک ترافیک در پس‌زمینه
async function startLiveSyncEngine() {
    const isConnected = "<?php echo $in ? 'true' : 'false'; ?>";
    if (isConnected !== 'true') return;

    setInterval(async () => {
        try {
            let formData = new FormData();
            formData.append('action', 'live_sync');
            let response = await fetch('', { method: 'POST', body: formData });
            if (response.ok) {
                let data = await response.json();
                for (let iface in data) {
                    let usedEl = document.getElementById('used-' + iface);
                    let remEl = document.getElementById('rem-' + iface);
                    let totalEl = document.getElementById('total-' + iface);
                    
                    if (usedEl && data[iface].used !== undefined) { usedEl.innerText = data[iface].used + ' GB'; }
                    if (remEl && data[iface].rem !== undefined) { remEl.innerText = data[iface].rem + ' GB'; }
                    if (totalEl && data[iface].total !== undefined && iface === 'wg0') { totalEl.innerText = data[iface].total + ' GB'; }
                }
            }
        } catch (e) {}
    }, 10000);
}

document.addEventListener('DOMContentLoaded', () => {
    startLiveSyncEngine();
});

document.getElementById('uf')?.addEventListener('submit', function(e) { e.preventDefault(); });
document.getElementById('ubtn')?.addEventListener('click', function() {
    if (!document.getElementById('bf').files.length) { showAlert('خطا','فایل بک‌آ‌پ را انتخاب کنید.'); return; }
    const f = document.getElementById('uf'), x = new XMLHttpRequest(), nf = document.getElementById('nf'), pt = document.getElementById('pt');
    document.getElementById('pra').style.display = 'block';
    x.upload.addEventListener('progress', e => { 
        if (e.lengthComputable) { 
            let p = Math.round((e.loaded / e.total) * 100); 
            nf.style.width = p + '%'; 
            pt.innerText = p + '%'; 
        }
    });
    x.addEventListener('load', () => { 
        nf.style.width = '100%'; 
        pt.innerText = 'انتقال انجام شد!'; 
        setTimeout(() => { f.submit(); }, 400); 
    });
    x.open('POST', '', true); 
    x.send(new FormData(f));
});

document.getElementById('mbtn')?.addEventListener('click', function() {
    const f = document.getElementById('mf'); 
    let v = true;
    f.querySelectorAll('input').forEach(i => { if(i.required && !i.value) v = false; });
    if (!v) { showAlert('خطا','اطلاعات سرور مقصد ناقص است.'); return; }
    const nf = document.getElementById('mnf'), pt = document.getElementById('mpt');
    document.getElementById('mra').style.display = 'block';
    let p = 0; 
    const intv = setInterval(() => { 
        p += 5; 
        if (p > 90) p = 90; 
        nf.style.width = p + '%'; 
        pt.innerText = p + '% کپی داده‌ها...'; 
    }, 400);
    const xhr = new XMLHttpRequest();
    xhr.addEventListener('load', () => { 
        clearInterval(intv); 
        nf.style.width = '100%'; 
        pt.innerText = 'انتقال انجام شد!'; 
        setTimeout(() => { 
            document.open(); 
            document.write(xhr.responseText); 
            document.close(); 
        }, 800); 
    });
    xhr.open('POST', '', true); 
    xhr.send(new FormData(f));
});
</script>
</body>
</html>