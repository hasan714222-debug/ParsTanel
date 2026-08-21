# --- [SUPREME UNIFIED WIREGUARD CLUSTER & BOT ENGINE - 100% CLEAN] ---
import os, sys, sqlite3, subprocess, json, re, base64, requests, urllib.parse, urllib.request, urllib.error, threading, time, math, traceback, zipfile, shutil
from flask import Response, request, jsonify, render_template, make_response, session, redirect

_last_sync_times = {}
_sync_lock = threading.Lock()
_edge_sessions = {}
_aggregator_started = False
_bot_worker_thread = None
_bot_worker_running = False
_time_worker_running = False
_user_steps = {}

def get_resolved_dir(): return os.path.dirname(os.path.abspath(__file__))

def get_resolved_cfg_path():
    cur_d = get_resolved_dir()
    p = os.path.join(cur_d, "telegram_bot_config.json")
    if not os.path.exists(p):
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"t": "", "c": "", "status": "off"}, f, indent=4)
        except: pass
    return p

def get_resolved_db_path():
    candidates = [
        os.path.join(get_resolved_dir(), "db.sqlite3"),
        "/home/irandnss/public_html/git/github_workspace/base/src/db.sqlite3",
        "/etc/wireguard/db.sqlite3"
    ]
    for c in candidates:
        if os.path.exists(c): return c
    return candidates[0]

def get_resolved_links_path():
    candidates = [
        os.path.join(get_resolved_dir(), "short_links.json"),
        "/home/irandnss/public_html/git/github_workspace/base/src/short_links.json"
    ]
    for c in candidates:
        if os.path.exists(c): return c
    return candidates[0]

def get_db_conn():
    p = get_resolved_db_path()
    conn = sqlite3.connect(p, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def load_bot_config_persistent():
    cfg_p = get_resolved_cfg_path()
    etc_p = "/etc/wireguard/telegram_bot_config.json"
    if os.path.exists(cfg_p):
        try:
            data = json.load(open(cfg_p, "r", encoding="utf-8"))
            if data.get("t"): return data
        except: pass
    if os.path.exists(etc_p):
        try:
            data = json.load(open(etc_p, "r", encoding="utf-8"))
            if data.get("t"):
                try: json.dump(data, open(cfg_p, "w", encoding="utf-8"), indent=4)
                except: pass
                return data
        except: pass
    try:
        conn = get_db_conn(); cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS system_config (key_name TEXT PRIMARY KEY, value_text TEXT)")
        row = cur.execute("SELECT value_text FROM system_config WHERE key_name='telegram_bot_config'").fetchone()
        conn.close()
        if row and row[0]:
            data = json.loads(row[0])
            try: json.dump(data, open(cfg_p, "w", encoding="utf-8"), indent=4)
            except: pass
            return data
    except: pass
    return {"t": "", "c": "", "status": "off"}

def get_bot_active_token(): return load_bot_config_persistent().get("t", "").strip()
def get_bot_admin_chat_id(): return load_bot_config_persistent().get("c", "").strip()
def get_bot_status_str(): return load_bot_config_persistent().get("status", "off")

def is_strictly_valid_wg_key(key_str):
    if not key_str or not isinstance(key_str, str) or len(key_str.strip()) != 44: return False
    try:
        decoded = base64.b64decode(key_str.strip().encode("ascii"))
        return len(decoded) == 32
    except: return False

def credit_to_vault_permanently(peer_name, config_file):
    try:
        conn = get_db_conn(); cur = conn.cursor()
        clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
        iface = clean_cfg.replace(".conf", "")
        cur.execute("SELECT used FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
        row = cur.fetchone()
        if row and row["used"] and int(row["used"]) > 0:
            used_val = int(row["used"])
            if iface == "wg0":
                cur.execute("UPDATE global_deleted_traffic SET total = total + ? WHERE id=1", (used_val,))
            else:
                cur.execute("UPDATE sub_panels SET deleted_traffic = deleted_traffic + ? WHERE interface_name=?", (used_val, iface))
            conn.commit()
        conn.close()
    except Exception: pass

def get_edge_authenticated_session(panel_url, username, password):
    norm_url = panel_url.rstrip("/")
    s = _edge_sessions.get(norm_url)
    if not s:
        s = requests.Session(); s.verify = False
        _edge_sessions[norm_url] = s
    try:
        if s.get(norm_url + "/api/user-info", timeout=4).status_code == 200: return s
    except Exception: pass
    try:
        if s.post(norm_url + "/api/login", json={"username": username, "password": password}, timeout=6).status_code == 200: return s
    except Exception: pass
    return s

def find_truly_free_ip_on_edge(session, panel_url, config_file):
    norm_url = panel_url.rstrip("/")
    used_ips = set()
    try:
        r = session.get(norm_url + "/api/peers?config=" + str(config_file) + "&fetch_all=true", timeout=6)
        if r.status_code == 200:
            for p in r.json().get("peers", []):
                ip = p.get("peer_ip")
                if ip: used_ips.add(ip.strip())
    except Exception: pass
    base_prefix = "10.0.0"
    try:
        d = session.get(norm_url + "/api/wireguard-details?config=" + str(config_file), timeout=6)
        if d.status_code == 200:
            ip_str = d.json().get("ip", "10.0.0.1")
            m = re.search(r"([0-9]+\.[0-9]+\.[0-9]+)\.", ip_str)
            if m: base_prefix = m.group(1)
    except Exception: pass
    for oct4 in range(2, 254):
        candidate = base_prefix + "." + str(oct4)
        if candidate not in used_ips: return candidate
    return base_prefix + ".2"

def sync_action_to_edges(action, peer_name, config_file="wg0.conf", extra_data=None, wait=False):
    clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
    iface = clean_cfg.replace(".conf", "")
    with _sync_lock:
        now_time = time.time()
        sync_key = str(action) + "_" + str(peer_name) + "_" + str(clean_cfg)
        if sync_key in _last_sync_times and (now_time - _last_sync_times[sync_key]) < 0.4: return
        _last_sync_times[sync_key] = now_time

    def do_sync():
        time.sleep(0.05)
        try:
            conn = get_db_conn(); cur = conn.cursor()
            cur.execute("SELECT panel_url, panel_user, panel_pass, server_ip, ssh_ip FROM edge_servers")
            edges = cur.fetchall()
            if not edges: conn.close(); return
            cur.execute("SELECT [limit], used, remaining_time, private_key, public_key, peer_ip, dns, mtu, persistent_keepalive, allowed_ips, monitor_blocked, expiry_blocked FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
            peer_row = cur.fetchone()
            limit, used, rem_time, priv, pub, master_ip, dns, mtu, keepalive, allowed_ips, m_blk, e_blk = "1GiB", 0, 1440, "", "", "10.0.0.2", "1.1.1.1", 1420, 25, "0.0.0.0/0, ::/0", 0, 0
            if peer_row:
                pd = dict(peer_row)
                limit = pd.get("limit") or "1GiB"
                used = pd.get("used") or 0
                rem_time = pd.get("remaining_time") or 1440
                priv = pd.get("private_key") or ""
                pub = pd.get("public_key") or ""
                master_ip = pd.get("peer_ip") or "10.0.0.2"
                dns = pd.get("dns") or "1.1.1.1"
                mtu = pd.get("mtu") or 1420
                keepalive = pd.get("persistent_keepalive") or 25
                allowed_ips = pd.get("allowed_ips") or "0.0.0.0/0, ::/0"
                m_blk = pd.get("monitor_blocked") or 0
                e_blk = pd.get("expiry_blocked") or 0
            if extra_data and isinstance(extra_data, dict):
                if extra_data.get("limit"): limit = extra_data["limit"]
                if extra_data.get("remaining_time") is not None: rem_time = int(extra_data["remaining_time"])
                if extra_data.get("used") is not None: used = int(extra_data["used"])
                if extra_data.get("public_key"): pub = extra_data["public_key"]
                if extra_data.get("peer_ip"): master_ip = extra_data["peer_ip"]
                if "blocked" in extra_data:
                    m_blk = 1 if extra_data["blocked"] else 0
                    e_blk = 1 if extra_data["blocked"] else 0
            is_blocked = bool(m_blk or e_blk)
            expiry_days = max(1, int(rem_time // 1440))
            for panel_url, panel_user, panel_pass, srv_ip, s_ip in edges:
                if not panel_url or not panel_user or not panel_pass: continue
                norm_url = panel_url.rstrip("/")
                session = get_edge_authenticated_session(panel_url, panel_user, panel_pass)
                if action == "delete":
                    try: session.post(norm_url + "/api/delete-peer", json={"peerName": peer_name, "configFile": clean_cfg}, timeout=8)
                    except: pass
                    cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=? AND config=?", (peer_name, clean_cfg))
                elif action == "create":
                    try: session.post(norm_url + "/api/delete-peer", json={"peerName": peer_name, "configFile": clean_cfg}, timeout=4)
                    except: pass
                    edge_ip = find_truly_free_ip_on_edge(session, norm_url, clean_cfg)
                    create_payload = {"peerName": peer_name, "peerIp": edge_ip, "dataLimit": limit, "configFile": clean_cfg, "dns": dns, "expiryDays": expiry_days, "firstUsage": False, "mtu": mtu, "persistentKeepalive": keepalive, "allowedIps": allowed_ips}
                    try:
                        res = session.post(norm_url + "/api/create-peer", json=create_payload, timeout=10)
                        if res.status_code == 200:
                            edge_actual_priv = priv
                            edge_actual_pub = pub
                            try:
                                p_inf = session.get(norm_url + "/api/get-peer-info?peerName=" + str(peer_name) + "&configFile=" + str(clean_cfg), timeout=5).json().get("peerInfo", {})
                                if p_inf.get("private_key"): edge_actual_priv = p_inf["private_key"]
                                if p_inf.get("public_key"): edge_actual_pub = p_inf["public_key"]
                            except: pass
                            cur.execute("INSERT OR REPLACE INTO peer_synced_edges (peer_name, server_ip, config, edge_ip, edge_priv_key, edge_pub_key, node_used) VALUES (?, ?, ?, ?, ?, ?, 0)", (peer_name, srv_ip, clean_cfg, edge_ip, edge_actual_priv, edge_actual_pub))
                    except: pass
                elif action == "edit":
                    try: session.post(norm_url + "/api/edit-peer", json={"peerName": peer_name, "configFile": clean_cfg, "dataLimit": limit, "dns": dns, "expiryDays": expiry_days}, timeout=8)
                    except: pass
                elif action == "toggle":
                    try: session.post(norm_url + "/api/toggle-peer", json={"peerName": peer_name, "blocked": is_blocked, "config": clean_cfg}, timeout=8)
                    except: pass
                elif action == "reset":
                    try:
                        session.post(norm_url + "/api/reset-traffic", json={"peerName": peer_name, "config": clean_cfg}, timeout=6)
                        session.post(norm_url + "/api/reset-expiry", json={"peerName": peer_name, "config": clean_cfg}, timeout=6)
                        cur.execute("UPDATE peer_synced_edges SET node_used=0 WHERE peer_name=? AND config=?", (peer_name, clean_cfg))
                        cur.execute("UPDATE peers SET local_used=0, used=0 WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
                    except: pass
            conn.commit(); conn.close()
        except: pass
    if wait: do_sync()
    else: threading.Thread(target=do_sync, daemon=True).start()

def reconcile_db_and_conf_files():
    try:
        conn = get_db_conn(); cur = conn.cursor()
        cur.execute("SELECT peer_name, public_key, peer_ip, config, persistent_keepalive, monitor_blocked, expiry_blocked FROM peers WHERE public_key IS NOT NULL AND public_key != ''")
        db_peers = [dict(r) for r in cur.fetchall()]
        conn.close()
        db_peers_by_cfg = {}
        for p in db_peers:
            cfg = p.get("config", "wg0.conf")
            if not str(cfg).endswith(".conf"): cfg = str(cfg) + ".conf"
            db_peers_by_cfg.setdefault(cfg, []).append(p)
        wg_dir = "/etc/wireguard"
        if not os.path.exists(wg_dir): return
        for f_name in os.listdir(wg_dir):
            if not f_name.endswith(".conf"): continue
            f_path = os.path.join(wg_dir, f_name)
            iface = f_name.replace(".conf", "")
            target_db_peers = db_peers_by_cfg.get(f_name, [])
            target_db_pubs = {p["public_key"]: p for p in target_db_peers if p.get("public_key") and is_strictly_valid_wg_key(p.get("public_key"))}
            try:
                with open(f_path, "r", encoding="utf-8", errors="ignore") as f: txt = f.read()
                blocks = txt.split("[Peer]")
                iface_header = blocks[0].strip()
                clean_blocks = []
                conf_pubs = set()
                for b in blocks[1:]:
                    pub_m = re.search(r"PublicKey\s*=\s*([^\s]+)", b)
                    if pub_m:
                        pub = pub_m.group(1).strip()
                        if pub in target_db_pubs:
                            conf_pubs.add(pub)
                            clean_blocks.append(b.strip())
                        else:
                            subprocess.run("wg set " + iface + " peer " + pub + " remove", shell=True, stderr=subprocess.DEVNULL)
                for pub, p_obj in target_db_pubs.items():
                    if pub not in conf_pubs:
                        p_name = p_obj.get("peer_name", "User")
                        p_ip = p_obj.get("peer_ip", "10.0.0.2")
                        keep = p_obj.get("persistent_keepalive", 25)
                        clean_blocks.append("# " + str(p_name) + chr(10) + "PublicKey = " + str(pub) + chr(10) + "AllowedIPs = " + str(p_ip) + "/32" + chr(10) + "PersistentKeepalive = " + str(keep))
                        if not (p_obj.get("monitor_blocked") or p_obj.get("expiry_blocked")):
                            subprocess.run("wg set " + iface + " peer " + pub + " allowed-ips " + p_ip + "/32", shell=True, stderr=subprocess.DEVNULL)
                new_conf_txt = iface_header + chr(10)
                for cb in clean_blocks: new_conf_txt += chr(10) + "[Peer]" + chr(10) + cb + chr(10)
                with open(f_path, "w", encoding="utf-8") as f: f.write(new_conf_txt.strip() + chr(10))
            except: pass
    except: pass

def ensure_edge_table_columns():
    try:
        conn = get_db_conn(); cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS peer_synced_edges (peer_name TEXT, server_ip TEXT, config TEXT, edge_ip TEXT, edge_priv_key TEXT DEFAULT '', edge_pub_key TEXT DEFAULT '', node_used INTEGER DEFAULT 0, last_bytes INTEGER DEFAULT 0, UNIQUE(peer_name, server_ip, config))")
        cur.execute("PRAGMA table_info(peer_synced_edges)")
        cols = [c[1] for c in cur.fetchall()]
        for col_name, col_def in [("node_used", "INTEGER DEFAULT 0"), ("edge_ip", "TEXT DEFAULT ''"), ("edge_priv_key", "TEXT DEFAULT ''"), ("edge_pub_key", "TEXT DEFAULT ''"), ("last_bytes", "INTEGER DEFAULT 0")] :
            if col_name not in cols:
                try: cur.execute("ALTER TABLE peer_synced_edges ADD COLUMN " + col_name + " " + col_def)
                except: pass
        conn.commit(); conn.close()
    except: pass

def run_cluster_traffic_aggregation_pass():
    ensure_edge_table_columns()
    try:
        conn = get_db_conn(); cur = conn.cursor()
        cur.execute("SELECT server_ip, panel_url, panel_user, panel_pass, ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
        edges = cur.fetchall()
        for srv_ip, panel_url, panel_user, panel_pass, s_ip, s_port, s_user, s_pass in edges:
            edge_traffic_map = {}
            if s_ip and s_pass and s_user:
                try:
                    cmd_ssh = "sshpass -p '" + str(s_pass) + "' ssh -p " + str(s_port or 22) + " -o StrictHostKeyChecking=no -o ConnectTimeout=5 " + str(s_user) + "@" + str(s_ip) + " 'wg show all transfer 2>/dev/null'"
                    proc = subprocess.run(cmd_ssh, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=8)
                    if proc.returncode == 0 and proc.stdout.strip():
                        for line in proc.stdout.strip().splitlines():
                            parts = line.split()
                            if len(parts) >= 4:
                                p_pub = parts[1].strip()
                                rx_b = int(parts[2]) if parts[2].isdigit() else 0
                                tx_b = int(parts[3]) if parts[3].isdigit() else 0
                                edge_traffic_map[p_pub] = rx_b + tx_b
                except Exception: pass
            if not edge_traffic_map and panel_url and panel_user and panel_pass:
                try:
                    norm_url = panel_url.rstrip("/")
                    session = get_edge_authenticated_session(panel_url, panel_user, panel_pass)
                    for iface_f in ["wg0.conf", "wg1.conf", "wg2.conf", "wg3.conf", "wg4.conf"]:
                        r = session.get(norm_url + "/api/peers?config=" + iface_f + "&fetch_all=true", timeout=5)
                        if r.status_code == 200:
                            for ep in r.json().get("peers", []):
                                p_name = ep.get("peer_name")
                                ep_used = int(ep.get("used") or 0)
                                ep_pub = ep.get("public_key") or ""
                                ep_ip = ep.get("peer_ip") or ""
                                if p_name:
                                    cur.execute("INSERT OR REPLACE INTO peer_synced_edges (peer_name, server_ip, config, edge_ip, edge_pub_key, node_used) VALUES (?, ?, ?, ?, ?, ?)", (p_name, srv_ip, iface_f, ep_ip, ep_pub, ep_used))
                except Exception: pass
            if edge_traffic_map:
                for pub, bytes_val in edge_traffic_map.items():
                    cur.execute("UPDATE peer_synced_edges SET node_used = ? WHERE (edge_pub_key = ? OR peer_name IN (SELECT peer_name FROM peers WHERE public_key=?)) AND (server_ip=? OR server_ip=?)", (bytes_val, pub, pub, srv_ip, s_ip))
        try:
            wg_local_out = subprocess.check_output("wg show all transfer 2>/dev/null", shell=True, universal_newlines=True, stderr=subprocess.DEVNULL)
            for line in wg_local_out.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    p_pub = parts[1].strip()
                    rx_b = int(parts[2]) if parts[2].isdigit() else 0
                    tx_b = int(parts[3]) if parts[3].isdigit() else 0
                    cur.execute("UPDATE peers SET local_used = ? WHERE public_key=?", (rx_b + tx_b, p_pub))
        except Exception: pass
        cur.execute("SELECT id, peer_name, config, [limit], local_used, monitor_blocked, public_key, peer_ip, used, first_usage, remaining_time, initial_duration FROM peers")
        master_peers = [dict(r) for r in cur.fetchall()]
        for mp in master_peers:
            pid = mp["id"]
            p_name = mp["peer_name"]
            cfg_clean = mp["config"] if str(mp["config"]).endswith(".conf") else str(mp["config"]) + ".conf"
            local_b = int(mp.get("local_used") or 0)
            cur.execute("SELECT SUM(node_used) FROM peer_synced_edges WHERE peer_name=? AND (config=? OR config=?)", (p_name, cfg_clean, cfg_clean.replace(".conf", "")))
            r_sum = cur.fetchone()
            edge_sum = int(r_sum[0] or 0) if r_sum and r_sum[0] is not None else 0
            final_total_used = local_b + edge_sum
            cur.execute("UPDATE peers SET used = ? WHERE id = ?", (final_total_used, pid))
            f_raw = str(mp.get("first_usage", "0")).strip().lower()
            is_first_u = (f_raw in ["1", "true", "yes", "calc_first_conn"])
            if is_first_u and final_total_used > 1024:
                cur.execute("UPDATE peers SET first_usage='0' WHERE id=?", (pid,))
            limit_str = mp.get("limit") or "0MiB"
            limit_bytes = float(limit_str.replace("GiB", "")) * 1073741824.0 if "GiB" in limit_str else (float(limit_str.replace("MiB", "")) * 1048576.0 if "MiB" in limit_str else 0)
            if limit_bytes > 0 and final_total_used >= limit_bytes and not mp.get("monitor_blocked"):
                cur.execute("UPDATE peers SET monitor_blocked=1, expiry_blocked=1 WHERE id=?", (pid,))
                if mp.get("peer_ip"): subprocess.run("ip route add blackhole " + str(mp["peer_ip"]), shell=True, stderr=subprocess.DEVNULL)
                if mp.get("public_key"): subprocess.run("wg set " + cfg_clean.replace(".conf","") + " peer " + str(mp["public_key"]) + " remove", shell=True, stderr=subprocess.DEVNULL)
                for s_ip_b, p_url_b, u_b, pw_b, _, _, _, _ in edges:
                    try: get_edge_authenticated_session(p_url_b, u_b, pw_b).post(p_url_b.rstrip("/") + "/api/toggle-peer", json={"peerName": p_name, "blocked": True, "config": cfg_clean}, timeout=5)
                    except: pass
        conn.commit(); conn.close()
    except Exception as e:
        bot_write_log("Aggregation pass error: " + str(e), "ERROR")

def start_cluster_traffic_aggregator():
    global _aggregator_started
    if _aggregator_started: return
    _aggregator_started = True
    def daemon_loop():
        time.sleep(3)
        while True:
            run_cluster_traffic_aggregation_pass()
            time.sleep(10)
    threading.Thread(target=daemon_loop, daemon=True).start()

start_cluster_traffic_aggregator()

def format_precise_duration_fa(total_minutes):
    mins = int(total_minutes or 0)
    if mins <= 0: return "۰ دقیقه"
    days = mins // 1440
    hours = (mins % 1440) // 60
    rem_mins = mins % 60
    parts = []
    if days > 0: parts.append(str(days) + " روز")
    if hours > 0: parts.append(str(hours) + " ساعت")
    if rem_mins > 0 and days == 0: parts.append(str(rem_mins) + " دقیقه")
    return " و ".join(parts) if parts else "کمتر از یک دقیقه"

def universal_sublink_renderer(short_id):
    short_id = str(short_id).strip()
    peer_name = None
    config_file = "wg0.conf"
    conn = get_db_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT long_link FROM short_links WHERE short_id = ?", (short_id,))
        row = cur.fetchone()
        if row and row["long_link"]:
            long_link = row["long_link"]
            p_m = re.search(r"peer_name=([^&]+)", long_link) or re.search(r"peerName=([^&]+)", long_link)
            c_m = re.search(r"config_file=([^&]+)", long_link) or re.search(r"configFile=([^&]+)", long_link) or re.search(r"config=([^&]+)", long_link)
            if p_m: peer_name = urllib.parse.unquote(p_m.group(1))
            if c_m: config_file = urllib.parse.unquote(c_m.group(1))
    except: pass
    if not peer_name:
        try:
            cur.execute("SELECT peer_name, config, token FROM peers WHERE peer_name = ? OR token = ? OR token LIKE ?", (short_id, short_id, str(short_id) + "%"))
            p_row = cur.fetchone()
            if p_row:
                peer_name = p_row["peer_name"]
                config_file = p_row["config"]
        except: pass
    clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
    iface = clean_cfg.replace(".conf", "")
    peer_row = None
    if peer_name:
        try:
            cur.execute("SELECT * FROM peers WHERE peer_name = ? AND (config = ? OR config = ?)", (peer_name, clean_cfg, iface))
            peer_row = cur.fetchone()
        except: pass
    if not peer_row:
        conn.close()
        display_name = peer_name or short_id
        rendered = render_template("status.html", peer_name=display_name, used_percent=100.0, time_percent=100.0, limit_str="۰ گیگابایت", used_str_fa="اشتراک حذف شده", rem_minutes=0, time_str_fa="منقضی و حذف شده", total_days="پایان اشتراک", location_html="<span class='flag-item'>🚫</span>", download_configs=[], short_id=short_id, status_text="<span style='display:flex; align-items:center; gap:5px;'><i class='fas fa-times-circle' style='color:#ff4757; font-size:16px;'></i> اشتراک شما پایان یافته و حذف شده است</span>", status_class="st-offline", cache_buster=int(time.time()))
        resp = make_response(rendered)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp
    p_dict = dict(peer_row)
    limit_str = str(p_dict.get("limit") or "50GiB")
    used_bytes = int(p_dict.get("used") or 0)
    rem_minutes = int(p_dict.get("remaining_time") or 0)
    init_duration = int(p_dict.get("initial_duration") or 0)
    expiry_json_str = str(p_dict.get("expiry_time_json") or "")
    total_min = 0
    if init_duration > 0: total_min = init_duration
    elif expiry_json_str and str(expiry_json_str).strip() not in ["None", "{}", ""]:
        try:
            exp_json = json.loads(str(expiry_json_str))
            m = int(exp_json.get("months", 0))
            d = int(exp_json.get("days", 0))
            h = int(exp_json.get("hours", 0))
            mn = int(exp_json.get("minutes", 0))
            total_min = (m * 30 * 1440) + (d * 1440) + (h * 60) + mn
        except: pass
    if total_min <= 0 and rem_minutes > 0: total_min = max(1440, math.ceil(rem_minutes / 1440.0) * 1440)
    if rem_minutes > total_min: total_min = rem_minutes
    total_days = format_precise_duration_fa(total_min)
    f_raw = str(p_dict.get("first_usage", "0")).strip().lower()
    is_waiting_first_conn = (f_raw in ["1", "true", "yes", "calc_first_conn"])
    has_traffic = (used_bytes > 1024)
    if is_waiting_first_conn and not has_traffic:
        try:
            cur.execute("SELECT SUM(node_used) FROM peer_synced_edges WHERE peer_name=?", (peer_name,))
            r_edge = cur.fetchone()
            if r_edge and r_edge[0] and int(r_edge[0]) > 1024: has_traffic = True
        except: pass
    limit_bytes = 1073741824.0
    if "GiB" in limit_str: limit_bytes = float(limit_str.replace("GiB", "")) * 1073741824.0
    elif "MiB" in limit_str: limit_bytes = float(limit_str.replace("MiB", "")) * 1048576.0
    used_percent = min(100.0, round((used_bytes / limit_bytes) * 100, 1)) if limit_bytes > 0 else 0.0
    if used_bytes >= 1073741824: used_str_fa = f"{used_bytes / 1073741824.0:.2f} گیگابایت"
    elif used_bytes >= 1048576: used_str_fa = f"{used_bytes / 1048576.0:.2f} مگابایت"
    else: used_str_fa = f"{used_bytes / 1024.0:.2f} کیلوبایت"
    limit_str_fa = limit_str.replace("GiB", " گیگابایت").replace("MiB", " مگابایت")
    is_time_exhausted = (rem_minutes <= 0)
    is_volume_exhausted = (limit_bytes > 0 and used_bytes >= limit_bytes)
    if is_time_exhausted or is_volume_exhausted:
        status_text = "<span style='display:flex; align-items:center; gap:5px;'><i class='fas fa-times-circle' style='color:#ff4757; font-size:16px;'></i> منقضی شده</span>"
        status_class = "st-offline"
        time_percent = 100.0
        time_str_fa = "منقضی شده"
    elif is_waiting_first_conn and not has_traffic:
        status_text = "<span style='display:flex; align-items:center; gap:5px;'><i class='fas fa-hourglass-half' style='color:#ffd700; font-size:16px;'></i> در انتظار اتصال</span>"
        status_class = "st-onhold"
        time_percent = 0.0
        used_percent = 0.0
        used_str_fa = "۰ بایت (در انتظار اتصال)"
        time_str_fa = "در انتظار اولین اتصال"
    else:
        elapsed_min = max(0, total_min - rem_minutes)
        time_percent = min(100.0, max(0.0, float(round((elapsed_min / float(total_min)) * 100.0, 1))))
        time_str_fa = format_precise_duration_fa(rem_minutes)
        status_text = "<span style='display:flex; align-items:center; gap:5px;'><i class='fas fa-check-circle' style='color:#00ffc3; font-size:16px;'></i> فعال</span>"
        status_class = "st-online"
    master_name = "سرور اصلی"
    master_flag = "🇩🇪"
    master_suffix = ""
    try:
        cur.execute("SELECT server_name, file_suffix FROM master_settings LIMIT 1")
        m_row = cur.fetchone()
        if m_row:
            if m_row["server_name"]: master_name = m_row["server_name"].strip()
            if m_row["file_suffix"]: master_suffix = m_row["file_suffix"].strip()
    except: pass
    all_edge_servers = []
    try:
        cur.execute("SELECT id, server_ip, flag, location, server_name, file_suffix FROM edge_servers")
        all_edge_servers = [dict(r) for r in cur.fetchall()]
    except: pass
    active_flags = [master_flag]
    for ef in all_edge_servers: active_flags.append(ef.get("flag") or "🌍")
    location_html = " ".join(["<span class='flag-item'>" + str(fl) + "</span>" for fl in set(active_flags)])
    download_configs = []
    dns_v = p_dict.get("dns") or "1.1.1.1"
    mtu_v = p_dict.get("mtu") or 1420
    keep_v = p_dict.get("persistent_keepalive") or 25
    allow_v = p_dict.get("allowed_ips") or "0.0.0.0/0, ::/0"
    download_configs.append({"server_label": "<i class='fas fa-server'></i> " + str(master_name) + " " + str(master_flag), "plan_name": "", "description": "اتصال مستقیم به شبکه سرور اصلی", "file_name": str(peer_name) + str(master_suffix) + ".conf", "suffix": "main_master", "mtu": mtu_v, "dns": dns_v, "keepalive": keep_v, "allowed_ips": allow_v})
    for ef in all_edge_servers:
        e_ip = ef.get("server_ip") or "edge"
        e_name = ef.get("server_name") or ("سرور " + str(ef.get("location", "لبه")))
        e_flag = ef.get("flag") or "🌍"
        e_suffix = ef.get("file_suffix") or ""
        download_configs.append({"server_label": "<i class='fas fa-satellite-dish'></i> " + str(e_name) + " " + str(e_flag), "plan_name": "", "description": "اتصال پایدار از طریق سرور " + str(e_name), "file_name": str(peer_name) + str(e_suffix) + ".conf", "suffix": "main_" + str(e_ip), "mtu": mtu_v, "dns": dns_v, "keepalive": keep_v, "allowed_ips": allow_v})
    conn.close()
    rendered = render_template("status.html", peer_name=peer_name, used_percent=used_percent, time_percent=time_percent, limit_str=limit_str_fa, used_str_fa=used_str_fa, rem_minutes=rem_minutes, time_str_fa=time_str_fa, total_days=total_days, location_html=location_html, download_configs=download_configs, short_id=short_id, status_text=status_text, status_class=status_class, cache_buster=int(time.time()))
    resp = make_response(rendered)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

def short_download_config_native(short_id, suffix_key):
    try:
        short_id = str(short_id).strip()
        suffix_key = str(suffix_key).strip()
        conn = get_db_conn(); cur = conn.cursor()
        peer_name = None
        config_file = "wg0.conf"
        try:
            cur.execute("SELECT long_link FROM short_links WHERE short_id=?", (short_id,))
            row = cur.fetchone()
            if row and row["long_link"]:
                long_link = row["long_link"]
                p_m = re.search(r"peer_name=([^&]+)", long_link) or re.search(r"peerName=([^&]+)", long_link)
                c_m = re.search(r"config_file=([^&]+)", long_link) or re.search(r"configFile=([^&]+)", long_link) or re.search(r"config=([^&]+)", long_link)
                if p_m: peer_name = urllib.parse.unquote(p_m.group(1))
                if c_m: config_file = urllib.parse.unquote(c_m.group(1))
        except: pass
        if not peer_name:
            cur.execute("SELECT peer_name, config FROM peers WHERE token=? OR peer_name=?", (short_id, short_id))
            p_row = cur.fetchone()
            if p_row:
                peer_name = p_row["peer_name"]
                config_file = p_row["config"]
        clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
        iface = clean_cfg.replace(".conf", "")
        if not peer_name:
            conn.close()
            return "Error: Peer not found or deleted", 404
        target_server = suffix_key.split("_", 1)[1] if "_" in suffix_key else "master"
        conf_content = None
        server_suffix = ""
        if target_server.lower() == "master":
            cur.execute("SELECT private_key, peer_ip, dns, mtu, persistent_keepalive, allowed_ips FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
            peer_rec = cur.fetchone()
            if not peer_rec:
                conn.close()
                return "Error: Peer record missing", 404
            p_dict = dict(peer_rec)
            client_priv_key = p_dict.get("private_key") or "YOUR_PRIVATE_KEY"
            client_ip = p_dict.get("peer_ip") or "10.0.0.2"
            mtu = p_dict.get("mtu") or 1420
            dns = p_dict.get("dns") or "1.1.1.1, 1.0.0.1"
            keepalive = p_dict.get("persistent_keepalive") or 25
            allowed_ips = p_dict.get("allowed_ips") or "0.0.0.0/0, ::/0"
            server_ip = "127.0.0.1"
            try:
                cur.execute("SELECT endpoint_domain, file_suffix FROM master_settings LIMIT 1")
                m_row = cur.fetchone()
                if m_row:
                    if m_row["endpoint_domain"]: server_ip = m_row["endpoint_domain"].strip()
                    if m_row["file_suffix"]: server_suffix = m_row["file_suffix"].strip()
            except: pass
            server_pub_key = ""
            listen_port = 51820
            master_conf_path = "/etc/wireguard/" + str(clean_cfg)
            if os.path.exists(master_conf_path):
                try:
                    with open(master_conf_path, "r", encoding="utf-8", errors="ignore") as f: cf_text = f.read()
                    port_match = re.search(r"ListenPort\s*=\s*(\d+)", cf_text, re.IGNORECASE)
                    if port_match: listen_port = int(port_match.group(1))
                    priv_match = re.search(r"PrivateKey\s*=\s*(.*)", cf_text, re.IGNORECASE)
                    if priv_match:
                        s_priv = priv_match.group(1).strip()
                        proc = subprocess.run(["wg", "pubkey"], input=s_priv, universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        if proc.returncode == 0 and proc.stdout.strip(): server_pub_key = proc.stdout.strip()
                except: pass
            conf_content = "[Interface]" + chr(10) + "PrivateKey = " + str(client_priv_key) + chr(10) + "Address = " + str(client_ip) + "/32" + chr(10) + "DNS = " + str(dns) + chr(10) + "MTU = " + str(mtu) + chr(10) + chr(10) + "[Peer]" + chr(10) + "PublicKey = " + str(server_pub_key) + chr(10) + "Endpoint = " + str(server_ip) + ":" + str(listen_port) + chr(10) + "AllowedIPs = " + str(allowed_ips) + chr(10) + "PersistentKeepalive = " + str(keepalive) + chr(10)
        else:
            cur.execute("SELECT server_ip, panel_url, panel_user, panel_pass, ssh_ip, file_suffix FROM edge_servers")
            all_edges = cur.fetchall()
            edge_row = None
            for e_r in all_edges:
                e_dict_t = dict(e_r)
                e_ip = e_dict_t.get("server_ip") or ""
                e_url = e_dict_t.get("panel_url") or ""
                e_ssh = e_dict_t.get("ssh_ip") or ""
                if target_server.lower() in e_ip.lower() or target_server.lower() in e_url.lower() or target_server.lower() in e_ssh.lower() or e_ip.lower() in target_server.lower():
                    edge_row = e_r; break
            if not edge_row and all_edges: edge_row = all_edges[0]
            if edge_row:
                e_dict = dict(edge_row)
                if e_dict.get("file_suffix"): server_suffix = e_dict["file_suffix"].strip()
                edge_domain = e_dict.get("server_ip") or "127.0.0.1"
                panel_url = e_dict.get("panel_url")
                panel_user = e_dict.get("panel_user")
                panel_pass = e_dict.get("panel_pass")
                cur.execute("SELECT private_key, peer_ip FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
                client_p_row = cur.fetchone()
                edge_client_ip = ""
                edge_client_priv = ""
                try:
                    cur.execute("SELECT edge_ip, edge_priv_key FROM peer_synced_edges WHERE peer_name=? AND (server_ip=? OR server_ip=?) AND config=?", (peer_name, e_dict.get("server_ip"), e_dict.get("ssh_ip"), clean_cfg))
                    se_row = cur.fetchone()
                    if se_row:
                        if se_row["edge_ip"]: edge_client_ip = se_row["edge_ip"]
                        if se_row["edge_priv_key"]: edge_client_priv = se_row["edge_priv_key"]
                except: pass
                if panel_url and panel_user and panel_pass:
                    try:
                        session = get_edge_authenticated_session(panel_url, panel_user, panel_pass)
                        norm_url = panel_url.rstrip("/")
                        edge_pub_key = ""
                        edge_port = 8080
                        det_res = session.get(norm_url + "/api/wireguard-details?config=" + str(clean_cfg), timeout=6)
                        if det_res.status_code == 200:
                            d_json = det_res.json()
                            edge_pub_key = d_json.get("public_key") or ""
                            edge_port = int(d_json.get("port") or 8080)
                        if not edge_client_priv or not edge_client_ip:
                            p_info_res = session.get(norm_url + "/api/get-peer-info?peerName=" + str(peer_name) + "&configFile=" + str(clean_cfg), timeout=6)
                            if p_info_res.status_code == 200:
                                p_data = p_info_res.json().get("peerInfo", {})
                                if p_data.get("private_key"): edge_client_priv = p_data["private_key"]
                                if p_data.get("peer_ip"): edge_client_ip = p_data["peer_ip"]
                        final_client_ip = edge_client_ip or "10.0.0.2"
                        if final_client_ip.endswith(".1") or final_client_ip.endswith(".0"):
                            final_client_ip = final_client_ip.rsplit(".", 1)[0] + ".2"
                        final_priv_key = edge_client_priv or (client_p_row["private_key"] if client_p_row else "YOUR_PRIVATE_KEY")
                        conf_content = "[Interface]" + chr(10) + "PrivateKey = " + str(final_priv_key) + chr(10) + "Address = " + str(final_client_ip) + "/32" + chr(10) + "DNS = 1.1.1.1, 1.0.0.1" + chr(10) + "MTU = 1280" + chr(10) + chr(10) + "[Peer]" + chr(10) + "PublicKey = " + str(edge_pub_key) + chr(10) + "Endpoint = " + str(edge_domain) + ":" + str(edge_port) + chr(10) + "AllowedIPs = 0.0.0.0/0, ::/0" + chr(10) + "PersistentKeepalive = 25" + chr(10)
                    except: pass
        conn.close()
        if not conf_content: return "❌ Error: Could not retrieve configuration for the requested Edge server", 500
        filename = str(peer_name) + str(server_suffix) + ".conf"
        return Response(conf_content, mimetype="application/octet-stream", headers={"Content-Disposition": "attachment; filename=\"" + str(filename) + "\"", "Cache-Control": "no-cache, no-store, must-revalidate"})
    except Exception as e:
        return "❌ Error generating config file: " + str(e), 500

def parse_volume_input_to_wg_limit(val_str):
    s = str(val_str).strip().upper()
    m = re.match(r"^([0-9\.]+)\s*(G|GB|GIB|M|MB|MIB|K|KB|KIB)?$", s)
    if not m:
        try: num = float(s)
        except: num = 1.0
        unit = "GB"
    else:
        num = float(m.group(1))
        unit = m.group(2) or "GB"
    if "M" in unit:
        mib = int(round(num))
        return str(max(1, mib)) + "MiB", max(1, mib) * 1048576, max(1, mib) / 1024.0
    elif "K" in unit:
        kib = int(round(num))
        return str(kib) + "KiB", kib * 1024, kib / (1024.0 * 1024.0)
    else:
        if num < 1.0:
            mib = int(round(num * 1024))
            return str(max(1, mib)) + "MiB", max(1, mib) * 1048576, num
        else:
            return (str(int(num)) + "GiB" if num == int(num) else f"{num:g}GiB"), int(num * 1073741824), num

def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 335]
    jy = 0 if gy <= 1600 else 979
    gy -= 621 if gy <= 1600 else 1600
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053); days %= 12053
    jy += 4 * (days // 1461); days %= 1461
    jy += (days - 1) // 365
    if days > 365: days = (days - 1) % 365
    jm = 1 + (days // 31) if days < 186 else 7 + ((days - 186) // 30)
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return jy, jm, jd

def format_jalali_date(timestamp):
    if not timestamp or int(timestamp) < 1000000: timestamp = int(time.time())
    t = time.gmtime(int(timestamp) + 12600)
    jy, jm, jd = gregorian_to_jalali(t.tm_year, t.tm_mon, t.tm_mday)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {t.tm_hour:02d}:{t.tm_min:02d}"

def bytes_to_readable(b):
    val = float(b or 0)
    if val <= 0: return "0 بایت"
    units = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"]
    i = int(math.floor(math.log(val, 1024))) if val > 0 else 0
    return f"{val / (1024 ** min(i, len(units)-1)):.2f} {units[min(i, len(units)-1)]}"

def get_peer_sublink_url(peer_name, config_file="wg0.conf"):
    conn = get_db_conn(); cur = conn.cursor()
    cur.execute("SELECT token FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, config_file, config_file.replace(".conf","")))
    row = cur.fetchone()
    token = row[0] if row and row[0] else ""
    domain = "89.44.198.67"
    try:
        m_row = cur.execute("SELECT endpoint_domain FROM master_settings LIMIT 1").fetchone()
        if m_row and m_row[0]: domain = m_row[0].strip()
    except: pass
    if not token or str(token).strip() in ["", "None"]:
        import secrets
        token = secrets.token_urlsafe(16)
        cur.execute("UPDATE peers SET token=? WHERE peer_name=?", (token, peer_name))
        cur.execute("CREATE TABLE IF NOT EXISTS short_links (short_id TEXT PRIMARY KEY, long_link TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token, "/api/status?peer_name=" + str(peer_name) + "&config_file=" + str(config_file)))
        conn.commit()
    conn.close()
    return "http://" + str(domain) + ":5000/s/" + str(token)

def get_peer_creation_date_jalali(peer_name):
    conn = get_db_conn(); cur = conn.cursor()
    ts = None
    try:
        r = cur.execute("SELECT created_at FROM peers WHERE peer_name=?", (peer_name,)).fetchone()
        if r and r[0] and int(r[0]) > 1000000: ts = int(r[0])
    except: pass
    if not ts: ts = int(time.time())
    conn.close()
    return format_jalali_date(ts)

def create_peer_native(peer_name, vol_str, days, first_usage=False, dns="1.1.1.1", mtu=1420, keepalive=25):
    conn = get_db_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM peers WHERE peer_name=?", (peer_name,))
    if cur.fetchone(): conn.close(); return False, "نام کلاینت '" + str(peer_name) + "' تکراری است."
    cur.execute("SELECT peer_ip FROM peers WHERE config='wg0.conf' OR config='wg0'")
    used_ips = set(r[0] for r in cur.fetchall() if r[0])
    base_prefix = "10.0.0"
    free_ip = None
    for oct4 in range(2, 254):
        cand = base_prefix + "." + str(oct4)
        if cand not in used_ips: free_ip = cand; break
    if not free_ip: free_ip = base_prefix + ".245"
    priv_k = subprocess.getoutput("wg genkey").strip()
    pub_k = subprocess.getoutput("echo '" + str(priv_k) + "' | wg pubkey").strip()
    if not priv_k or not pub_k: conn.close(); return False, "خطا در تولید کلیدها."
    lim_str, lim_bytes, _ = parse_volume_input_to_wg_limit(vol_str)
    rem_minutes = int(days * 1440)
    init_duration = rem_minutes
    exp_json_str = json.dumps({"months": 0, "days": int(days), "hours": 0, "minutes": 0})
    now_ts = int(time.time())
    first_u_val = 1 if first_usage else 0
    import secrets
    token = secrets.token_urlsafe(16)
    try:
        cur.execute("PRAGMA table_info(peers)")
        cols = [c[1] for c in cur.fetchall()]
        if "created_at" not in cols: cur.execute("ALTER TABLE peers ADD COLUMN created_at INTEGER")
        if "initial_duration" not in cols: cur.execute("ALTER TABLE peers ADD COLUMN initial_duration INTEGER DEFAULT 0")
    except: pass
    cur.execute("INSERT OR REPLACE INTO peers (peer_name, peer_ip, public_key, [limit], used, remaining_time, config, expiry_time_json, first_usage, expiry_blocked, monitor_blocked, private_key, dns, mtu, persistent_keepalive, allowed_ips, token, created_at, initial_duration) VALUES (?, ?, ?, ?, 0, ?, 'wg0.conf', ?, ?, 0, 0, ?, ?, ?, ?, '0.0.0.0/0, ::/0', ?, ?, ?)",
                (peer_name, free_ip, pub_k, lim_str, rem_minutes, exp_json_str, first_u_val, priv_k, dns, mtu, keepalive, token, now_ts, init_duration))
    cur.execute("CREATE TABLE IF NOT EXISTS short_links (short_id TEXT PRIMARY KEY, long_link TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token, "/api/status?peer_name=" + str(peer_name) + "&config_file=wg0.conf"))
    cur.execute("CREATE TABLE IF NOT EXISTS services (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, email TEXT, sub_id TEXT, plan_name TEXT, purchase_date INTEGER, vol REAL, days INTEGER, first_usage INTEGER)")
    sub_url = "http://89.44.198.67:5000/s/" + str(token)
    cur.execute("INSERT INTO services (user_id, email, sub_id, plan_name, purchase_date, vol, days, first_usage) VALUES (0, ?, ?, ?, ?, ?, ?, ?)",
                (peer_name, sub_url, "دستی (" + str(lim_str) + " - " + str(days) + "روز)", now_ts, float(lim_bytes / (1024**3)), days, first_u_val))
    conn.commit(); conn.close()
    reconcile_db_and_conf_files()
    subprocess.run("wg set wg0 peer " + str(pub_k) + " allowed-ips " + str(free_ip) + "/32", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run("wg-quick save wg0", shell=True, stderr=subprocess.DEVNULL)
    sync_action_to_edges("create", peer_name, "wg0.conf")
    return True, {"peer_name": peer_name, "peer_ip": free_ip, "public_key": pub_k, "limit_str": lim_str, "days": days, "sub_url": sub_url, "token": token}

def tg_send_message(chat_id, text, reply_markup=None, token=None):
    token = token or get_bot_active_token()
    if not token or not chat_id: return None
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + str(token) + "/sendMessage", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp: return json.loads(resp.read().decode("utf-8"))
    except: return None

def tg_edit_message(chat_id, message_id, text, reply_markup=None, token=None):
    token = token or get_bot_active_token()
    if not token or not chat_id or not message_id: return None
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + str(token) + "/editMessageText", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp: return json.loads(resp.read().decode("utf-8"))
    except: return None

def tg_answer_callback(callback_query_id, text="", alert=False, token=None):
    token = token or get_bot_active_token()
    if not token or not callback_query_id: return
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + str(token) + "/answerCallbackQuery", data=json.dumps({"callback_query_id": callback_query_id, "text": text, "show_alert": alert}).encode("utf-8"), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except: pass

def tg_delete_message(chat_id, message_id, token=None):
    token = token or get_bot_active_token()
    if not token or not chat_id or not message_id: return
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + str(token) + "/deleteMessage", data=json.dumps({"chat_id": chat_id, "message_id": message_id}).encode("utf-8"), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except: pass

def tg_send_document(chat_id, filename, file_content, caption="", token=None):
    token = token or get_bot_active_token()
    if not token or not chat_id: return None
    try:
        requests.post("https://api.telegram.org/bot" + str(token) + "/sendDocument", data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}, files={"document": (filename, file_content.encode("utf-8"), "text/plain")}, timeout=12)
    except: pass

def get_main_reply_keyboard():
    return {"keyboard": [[{"text": "➕ ساخت کاربر جدید"}, {"text": "👥 مدیریت کاربران"}], [{"text": "📊 آمار پنل من"}, {"text": "🧹 بررسی غیرفعال‌ها"}]], "resize_keyboard": True}

def extract_wireguard_configs_from_sub(sub_url, peer_name):
    configs = []
    if sub_url and sub_url.startswith("http"):
        try:
            r = requests.get(sub_url, timeout=8, headers={"User-Agent": "v2rayNG/1.8.5"})
            if r.status_code == 200:
                content = r.text
                base_host = str(urllib.parse.urlparse(sub_url).scheme) + "://" + str(urllib.parse.urlparse(sub_url).netloc)
                if '<div class="conf-item">' in content:
                    for card in content.split('<div class="conf-item">')[1:]:
                        m_href = re.search(r'href="([^"]*?/download/[^"]*?)"', card, re.I)
                        if m_href:
                            dl_url = m_href.group(1)
                            if not dl_url.startswith("http"): dl_url = base_host + "/" + dl_url.lstrip("/")
                            dl_res = requests.get(dl_url, timeout=6)
                            if dl_res.status_code == 200 and "[Interface]" in dl_res.text:
                                loc_name = "سرور اصلی"
                                m_title = re.search(r'<b[^>]*>(.*?)</b>', card, re.S)
                                if m_title: loc_name = re.sub(r'<[^>]+>', '', m_title.group(1)).strip()
                                configs.append({"name": str(peer_name) + ".conf", "emoji": "🌐", "location_name": loc_name, "description": "اتصال مستقیم", "content": dl_res.text.strip()})
        except: pass
    if not configs:
        try:
            r_raw = requests.get("http://127.0.0.1:5000/api/download-peer-config?peerName=" + str(peer_name) + "&config=wg0.conf", timeout=6)
            if r_raw.status_code == 200 and "[Interface]" in r_raw.text:
                configs.append({"name": str(peer_name) + ".conf", "emoji": "🌐", "location_name": "سرور اصلی", "description": "کانفیگ وایرگارد", "content": r_raw.text.strip()})
        except: pass
    return configs

def toggle_peer_direct(peer_name, config_file="wg0.conf"):
    clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
    iface = clean_cfg.replace(".conf", "")
    conn = get_db_conn(); cur = conn.cursor()
    cur.execute("SELECT monitor_blocked, expiry_blocked, peer_ip, public_key FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
    p_row = cur.fetchone()
    if not p_row: conn.close(); return False, "کاربر یافت نشد"
    blk = bool(p_row[0] or p_row[1])
    new_blk = 0 if blk else 1
    cur.execute("UPDATE peers SET monitor_blocked=?, expiry_blocked=? WHERE peer_name=? AND (config=? OR config=?)", (new_blk, new_blk, peer_name, clean_cfg, iface))
    conn.commit(); conn.close()
    p_ip, pub_k = p_row[2], p_row[3]
    if new_blk == 1:
        if p_ip: subprocess.run("ip route add blackhole " + str(p_ip), shell=True, stderr=subprocess.DEVNULL)
        if pub_k: subprocess.run("wg set " + str(iface) + " peer " + str(pub_k) + " remove", shell=True, stderr=subprocess.DEVNULL)
    else:
        if p_ip: subprocess.run("ip route del blackhole " + str(p_ip), shell=True, stderr=subprocess.DEVNULL)
        if pub_k and p_ip: subprocess.run("wg set " + str(iface) + " peer " + str(pub_k) + " allowed-ips " + str(p_ip) + "/32", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run("wg-quick save " + str(iface), shell=True, stderr=subprocess.DEVNULL)
    sync_action_to_edges("toggle", peer_name, clean_cfg, {"blocked": bool(new_blk)})
    return True, ("غیرفعال 🔴" if new_blk else "فعال 🟢")

def edit_peer_days_direct(peer_name, days_diff, config_file="wg0.conf"):
    clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
    iface = clean_cfg.replace(".conf", "")
    conn = get_db_conn(); cur = conn.cursor()
    cur.execute("SELECT remaining_time FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
    p_row = cur.fetchone()
    if not p_row: conn.close(); return False
    new_rem = max(0, int(p_row[0] or 0) + int(days_diff * 1440))
    cur.execute("UPDATE peers SET remaining_time=? WHERE peer_name=? AND (config=? OR config=?)", (new_rem, peer_name, clean_cfg, iface))
    conn.commit(); conn.close()
    sync_action_to_edges("edit", peer_name, clean_cfg, {"remaining_time": new_rem})
    return True

def edit_peer_volume_direct(peer_name, gb_diff, config_file="wg0.conf"):
    clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
    iface = clean_cfg.replace(".conf", "")
    conn = get_db_conn(); cur = conn.cursor()
    cur.execute("SELECT [limit] FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
    p_row = cur.fetchone()
    if not p_row: conn.close(); return False
    _, current_bytes, _ = parse_volume_input_to_wg_limit(str(p_row[0] or "1GiB"))
    new_bytes = max(0, current_bytes + int(gb_diff * 1073741824))
    new_lim_str, _, _ = parse_volume_input_to_wg_limit(new_bytes / 1073741824.0)
    cur.execute("UPDATE peers SET [limit]=? WHERE peer_name=? AND (config=? OR config=?)", (new_lim_str, peer_name, clean_cfg, iface))
    conn.commit(); conn.close()
    sync_action_to_edges("edit", peer_name, clean_cfg, {"limit": new_lim_str})
    return True

def show_templates_list_tg(chat_id, user_id=0, message_id=None, token=None):
    conn = get_db_conn(); cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0, name TEXT NOT NULL, vol TEXT NOT NULL, days INTEGER NOT NULL, first_usage INTEGER DEFAULT 1)")
    tpls = [dict(r) for r in cur.execute("SELECT * FROM templates WHERE user_id=? OR user_id=0 ORDER BY user_id DESC, id ASC", (user_id,)).fetchall()]
    conn.close()
    msg = "📋 <b>الگوهای آماده ساخت کلاینت:</b>\n\nجهت ساخت کاربر با الگوی مورد نظر، آن را انتخاب کنید:"
    kb = []
    for t in tpls:
        calc_txt = "⏳ اتصال" if (int(t.get("first_usage") or 0) == 1) else "⚡ فوری"
        lim_str = t.get("vol", "50GiB")
        days = t.get("days", 30)
        t_id = t["id"]
        is_mine = "⭐ " if (t.get("user_id") and t.get("user_id") == user_id) else "📦 "
        kb.append([{"text": is_mine + str(t["name"]) + " (" + str(lim_str) + " | " + str(days) + "روز | " + str(calc_txt) + ")", "callback_data": "tpl_view_" + str(t_id)}])
    kb.append([{"text": "➕ ساخت الگوی اختصاصی جدید", "callback_data": "tpl_add"}])
    kb.append([{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "start_action"}])
    if message_id: tg_edit_message(chat_id, message_id, msg, {"inline_keyboard": kb}, token)
    else: tg_send_message(chat_id, msg, {"inline_keyboard": kb}, token)

def show_users_list_tg(chat_id, user_id, page=1, search_query=None, message_id=None, token=None):
    per_page = 12
    offset = (page - 1) * per_page
    conn = get_db_conn(); cur = conn.cursor()
    if search_query:
        sq = "%" + str(search_query) + "%"
        total = cur.execute("SELECT COUNT(*) FROM peers WHERE peer_name LIKE ?", (sq,)).fetchone()[0] or 0
        peers = [dict(r) for r in cur.execute("SELECT peer_name, monitor_blocked, expiry_blocked FROM peers WHERE peer_name LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?", (sq, per_page, offset)).fetchall()]
    else:
        total = cur.execute("SELECT COUNT(*) FROM peers").fetchone()[0] or 0
        peers = [dict(r) for r in cur.execute("SELECT peer_name, monitor_blocked, expiry_blocked FROM peers ORDER BY id DESC LIMIT ? OFFSET ?", (per_page, offset)).fetchall()]
    conn.close()
    total_pages = max(1, math.ceil(total / per_page))
    if not peers:
        msg = ("🔍 کاربری مطابق با <code>" + str(search_query) + "</code> یافت نشد.") if search_query else "👥 هیچ کاربری در پنل ثبت نشده است."
        if message_id: tg_edit_message(chat_id, message_id, msg, None, token)
        else: tg_send_message(chat_id, msg, get_main_reply_keyboard(), token)
        return
    kb = []
    current_row = []
    for p in peers:
        name = p["peer_name"]
        icon = "🔴" if (p.get("monitor_blocked") or p.get("expiry_blocked")) else "🟢"
        current_row.append({"text": str(icon) + " " + str(name), "callback_data": "mg_det_" + str(name) + "_" + str(page)})
        if len(current_row) == 3: kb.append(current_row); current_row = []
    if current_row: kb.append(current_row)
    nav_row = []
    if page > 1: nav_row.append({"text": "◀️ قبلی", "callback_data": "mg_list_" + str(page-1)})
    nav_row.append({"text": "🔍 جستجو", "callback_data": "mg_search"})
    if page < total_pages: nav_row.append({"text": "بعدی ▶️", "callback_data": "mg_list_" + str(page+1)})
    kb.append(nav_row)
    search_txt = ("\n🔍 <i>نتایج جستجو برای:</i> <code>" + str(search_query) + "</code>") if search_query else ""
    msg = "👥 <b>مدیریت کاربران (۳ ستونه):</b>" + str(search_txt) + "\n📑 صفحه <b>" + str(page) + "</b> از <b>" + str(total_pages) + "</b> (کل: " + str(total) + " کاربر):"
    if message_id: tg_edit_message(chat_id, message_id, msg, {"inline_keyboard": kb}, token)
    else: tg_send_message(chat_id, msg, {"inline_keyboard": kb}, token)

def show_detailed_user_tg(chat_id, peer_name, page=1, message_id=None, token=None):
    conn = get_db_conn(); cur = conn.cursor()
    p_row = cur.execute("SELECT * FROM peers WHERE peer_name=?", (peer_name,)).fetchone()
    conn.close()
    if not p_row:
        if message_id: tg_edit_message(chat_id, message_id, "❌ کاربر یافت نشد یا حذف شده است.", None, token)
        else: tg_send_message(chat_id, "❌ کاربر یافت نشد.", token=token)
        return
    pd = dict(p_row)
    used_bytes = int(pd.get("used") or 0)
    used_str = bytes_to_readable(used_bytes)
    lim_str = pd.get("limit") or "نامحدود"
    rem_minutes = int(pd.get("remaining_time") or 0)
    init_d = int(pd.get("initial_duration") or 0)
    if init_d <= 0: init_d = max(1440, rem_minutes)
    total_plan_str = format_precise_duration_fa(init_d)
    is_online_now = False
    try:
        iface = pd.get("config", "wg0.conf").replace(".conf", "")
        pub = pd.get("public_key")
        if pub:
            out_hs = subprocess.getoutput("wg show " + str(iface) + " latest-handshakes")
            for line in out_hs.splitlines():
                if pub in line:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        hs_ts = int(parts[1])
                        if (time.time() - hs_ts) < 180 and hs_ts > 0: is_online_now = True
    except: pass
    f_raw = str(pd.get("first_usage", "0")).strip().lower()
    is_first_u = (f_raw in ["1", "true", "yes", "calc_first_conn"])
    has_traffic = (used_bytes > 1024)
    blk = bool(pd.get("monitor_blocked") or pd.get("expiry_blocked"))
    if blk or rem_minutes <= 0:
        st_text = "🔴 مسدود / منقضی شده"
        rem_str = "منقضی شده"
    elif is_first_u and not has_traffic:
        st_text = "🟡 در انتظار اولین اتصال (زمان شروع نشده)"
        rem_str = "در انتظار اتصال (کل: " + str(total_plan_str) + ")"
    elif is_online_now:
        st_text = "🟢 متصل و آنلاین (شروع شده)"
        rem_str = format_precise_duration_fa(rem_minutes)
    else:
        st_text = "🟢 فعال / آفلاین (شروع شده)"
        rem_str = format_precise_duration_fa(rem_minutes)
    date_str = get_peer_creation_date_jalali(peer_name)
    sub_url = get_peer_sublink_url(peer_name, pd.get("config", "wg0.conf"))
    msg = "👤 <b>جزئیات کلاینت:</b> <code>" + str(peer_name) + "</code>\n\n📊 <b>حجم کل پلن:</b> <code>" + str(lim_str) + "</code>\n📉 <b>حجم مصرفی:</b> <code>" + str(used_str) + "</code>\n⏳ <b>کل اعتبار اولیه:</b> <code>" + str(total_plan_str) + "</code>\n⏱ <b>زمان باقی‌مانده:</b> <b>" + str(rem_str) + "</b>\n🚦 <b>وضعیت حساب:</b> <b>" + str(st_text) + "</b>\n🌐 <b>آی‌پی کلاینت:</b> <code>" + str(pd.get("peer_ip", "10.0.0.2")) + "</code>\n📅 <b>تاریخ و ساعت ساخت:</b> <code>" + str(date_str) + "</code>\n\n🔗 <b>لینک ساب‌اسکریپشن:</b>\n<code>" + str(sub_url) + "</code>"
    kb = [
        [{"text": "📥 دریافت کانفیگ", "callback_data": "extwg_" + str(peer_name)}, {"text": "📷 دریافت کد QR", "callback_data": "sendqr_" + str(peer_name)}],
        [{"text": "🔄 ریست مصرف حجم", "callback_data": "mg_act_rstvol_" + str(peer_name) + "_" + str(page)}, {"text": "🔘 فعال / غیرفعال", "callback_data": "mg_act_toggle_" + str(peer_name) + "_" + str(page)}],
        [{"text": "➕ افزایش زمان", "callback_data": "mg_act_time_" + str(peer_name) + "_" + str(page)}, {"text": "➖ کاهش زمان", "callback_data": "mg_act_dectime_" + str(peer_name) + "_" + str(page)}],
        [{"text": "➕ افزایش حجم", "callback_data": "mg_act_vol_" + str(peer_name) + "_" + str(page)}, {"text": "➖ کاهش حجم", "callback_data": "mg_act_decvol_" + str(peer_name) + "_" + str(page)}],
        [{"text": "🗑 حذف دائم کلاینت", "callback_data": "mg_act_del_" + str(peer_name) + "_" + str(page)}],
        [{"text": "🔙 بازگشت به لیست", "callback_data": "mg_list_" + str(page)}]
    ]
    if message_id: tg_edit_message(chat_id, message_id, msg, {"inline_keyboard": kb}, token)
    else: tg_send_message(chat_id, msg, {"inline_keyboard": kb}, token)

def send_peer_qr_image_tg(chat_id, peer_name, token=None):
    token = token or get_bot_active_token()
    if not token or not chat_id: return
    try:
        sub_url = get_peer_sublink_url(peer_name, "wg0.conf")
        cfgs = extract_wireguard_configs_from_sub(sub_url, peer_name)
        raw_conf = cfgs[0]["content"] if cfgs else None
        if not raw_conf: raw_conf = subprocess.getoutput("wg genkey")
        import qrcode, io
        qr = qrcode.QRCode(box_size=10, border=3)
        qr.add_data(raw_conf)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        requests.post("https://api.telegram.org/bot" + str(token) + "/sendPhoto", data={"chat_id": chat_id, "caption": "📷 <b>کد QR اتصال کلاینت:</b> <code>" + str(peer_name) + "</code>", "parse_mode": "HTML"}, files={"photo": (str(peer_name) + ".png", buf.getvalue(), "image/png")}, timeout=15)
    except Exception as e:
        bot_write_log("QR Send Error: " + str(e), "ERROR")
        tg_send_message(chat_id, "❌ خطا در ساخت QR Code: " + str(e), token=token)

def process_telegram_update(update, token):
    msg = update.get("message") or update.get("callback_query", {}).get("message")
    cb = update.get("callback_query")
    from_user = update.get("message", {}).get("from") or update.get("callback_query", {}).get("from") or {}
    user_id = from_user.get("id")
    chat_id = msg.get("chat", {}).get("id") if msg else user_id
    message_id = msg.get("message_id") if msg else None
    text = update.get("message", {}).get("text", "").strip()
    cb_data = cb.get("data") if cb else None
    if not user_id or not chat_id: return
    is_allowed, block_reason = check_reseller_access_and_quota(user_id, chat_id, token)
    if not is_allowed:
        if cb: tg_answer_callback(cb.get("id"), "دسترسی مسدود است!", alert=True, token=token)
        tg_send_message(chat_id, block_reason, {"remove_keyboard": True}, token=token)
        return
    if cb: tg_answer_callback(cb.get("id"), token=token)
    if text == "/start":
        _user_steps[user_id] = {"step": "idle"}
        welcome = "🤖 <b>به ربات مدیریت هوشمند وایرگارد خوش آمدید!</b>\n\n✅ اتصال شما تایید شد. لطفاً گزینه مورد نظر را انتخاب کنید:"
        tg_send_message(chat_id, welcome, get_main_reply_keyboard(), token)
        return
    if text == "📊 آمار پنل من":
        _user_steps[user_id] = {"step": "idle"}
        try:
            conn = get_db_conn(); cur = conn.cursor()
            total_p = cur.execute("SELECT COUNT(*) FROM peers").fetchone()[0] or 0
            blocked_p = cur.execute("SELECT COUNT(*) FROM peers WHERE monitor_blocked=1 OR expiry_blocked=1").fetchone()[0] or 0
            active_p = max(0, total_p - blocked_p)
            used_gb = (cur.execute("SELECT SUM(used) FROM peers").fetchone()[0] or 0) / (1024 * 1024 * 1024)
            conn.close()
            m_stat = subprocess.getoutput("free -m | grep Mem | awk '{print $3, $2}'").split()
            ram_info = str(m_stat[0]) + "MB / " + str(m_stat[1]) + "MB" if len(m_stat) >= 2 else "نامشخص"
            cpu_usage = subprocess.getoutput("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")
            now_time = format_jalali_date(time.time())
            report = "📊 <b>آمار جامع پنل شما</b>\n\n🏷 <b>نوع پنل:</b> 🛡 WireGuard (اصلی)\n⚙️ <b>اینترفیس:</b> <code>wg0</code>\n👥 <b>کل کاربران:</b> <code>" + str(total_p) + " نفر</code>\n🟢 <b>کاربران فعال:</b> <code>" + str(active_p) + " نفر</code>\n🔴 <b>کاربران مسدود/منقضی:</b> <code>" + str(blocked_p) + " نفر</code>\n📈 <b>مجموع مصرف:</b> <code>" + f"{used_gb:.2f}" + " گیگابایت</code>\n🖥 <b>سرور:</b> CPU: <code>" + str(cpu_usage) + "%</code> | RAM: <code>" + str(ram_info) + "</code>\n🚦 <b>وضعیت:</b> ✅ فعال\n🕒 <b>زمان:</b> <code>" + str(now_time) + "</code>"
            tg_send_message(chat_id, report, get_main_reply_keyboard(), token)
        except Exception as e:
            bot_write_log("Stats Error: " + str(e), "ERROR")
            tg_send_message(chat_id, "❌ خطا: " + str(e), get_main_reply_keyboard(), token)
        return
    if text == "➕ ساخت کاربر جدید":
        _user_steps[user_id] = {"step": "idle"}
        kb = {"inline_keyboard": [[{"text": "🛠 ساخت دستی", "callback_data": "create_manual"}, {"text": "📋 الگو های قبل", "callback_data": "create_template"}]]}
        tg_send_message(chat_id, "✨ نحوه ساخت کاربر را انتخاب کنید:", kb, token)
        return
    if text == "👥 مدیریت کاربران":
        _user_steps[user_id] = {"step": "idle"}
        show_users_list_tg(chat_id, user_id, 1, token=token)
        return
    if text == "🧹 بررسی غیرفعال‌ها":
        _user_steps[user_id] = {"step": "idle"}
        kb = {"inline_keyboard": [[{"text": "بله، کاملاً مطمئنم ✅", "callback_data": "bulk_del_inactive_yes"}, {"text": "خیر، انصراف ❌", "callback_data": "bulk_del_inactive_no"}]]}
        tg_send_message(chat_id, "⚠️ <b>آیا مطمئن هستید که می‌خواهید تمام کاربران غیرفعال/منقضی را حذف کنید؟</b>", kb, token)
        return
    state = _user_steps.get(user_id, {})
    step = state.get("step")
    if step == "wait_search_query":
        q = text.strip()
        show_users_list_tg(chat_id, user_id, 1, search_query=q, message_id=state.get("orig_msg_id"), token=token)
        tg_delete_message(chat_id, message_id, token)
        _user_steps[user_id] = {"step": "idle"}
        return
    if step == "wait_manual_prefix":
        prefix = re.sub(r"[^a-zA-Z0-9_]", "", text)
        state["prefix"] = prefix; state["step"] = "wait_manual_volume"
        tg_delete_message(chat_id, message_id, token)
        if state.get("orig_msg_id"): tg_edit_message(chat_id, state["orig_msg_id"], "✍️ پیشوند: <code>" + str(prefix) + "</code>\n\n📊 <b>حجم اشتراک چقدر باشد؟</b> (مثال: 0.5 یا 50):", None, token)
        return
    if step == "wait_manual_volume":
        lim_str, bytes_val, num_val = parse_volume_input_to_wg_limit(text)
        state["vol_str"] = lim_str; state["vol_num"] = num_val; state["step"] = "wait_manual_days"
        tg_delete_message(chat_id, message_id, token)
        if state.get("orig_msg_id"): tg_edit_message(chat_id, state["orig_msg_id"], "📊 حجم: <code>" + str(lim_str) + "</code>\n\n⏳ <b>زمان اشتراک چند روز باشد؟</b> (مثلاً 30):", None, token)
        return
    if step == "wait_manual_days":
        try: days = float(text)
        except: days = 30.0
        state["days"] = int(round(days)); state["step"] = "wait_manual_calc"
        tg_delete_message(chat_id, message_id, token)
        kb = {"inline_keyboard": [[{"text": "⏱ در اولین اتصال", "callback_data": "calc_first_conn"}, {"text": "⚡ همین الان", "callback_data": "calc_now"}]]}
        if state.get("orig_msg_id"): tg_edit_message(chat_id, state["orig_msg_id"], "⏳ زمان: <code>" + str(state["days"]) + " روز</code>\n\n⚙️ <b>نحوه محاسبه زمان چگونه باشد؟</b>", kb, token)
        return
    if step == "wait_manual_bulk_count":
        try: count = int(text)
        except: count = 5
        count = min(50, max(1, count))
        tg_delete_message(chat_id, message_id, token)
        if state.get("orig_msg_id"): tg_edit_message(chat_id, state["orig_msg_id"], "⏳ در حال ساخت <b>" + str(count) + "</b> کاربر جدید در پنل...", None, token)
        succ = 0
        for i in range(1, count + 1):
            email = str(state["prefix"]) + "_" + str(time.time_ns()%100000)
            first_u = (state.get("first_usage") == "calc_first_conn")
            ok, res_obj = create_peer_native(email, state["vol_str"], state["days"], first_usage=first_u)
            if ok:
                succ += 1
                sub_l = res_obj["sub_url"]
                card = "🎁 <b>کاربر شماره " + str(i) + " با موفقیت ساخته شد!</b>\n\n👤 نام: <code>" + str(email) + "</code>\n📊 حجم: <code>" + str(state["vol_str"]) + "</code>\n⏳ زمان: <code>" + str(state["days"]) + " روز</code>\n🔗 لینک:\n<code>" + str(sub_l) + "</code>"
                tg_send_message(chat_id, card, {"inline_keyboard": [[{"text": "📥 استخراج کانفیگ", "callback_data": "extwg_" + str(email)}]]}, token)
        tg_send_message(chat_id, "🏁 ساخت گروهی به پایان رسید.\n✅ تعداد موفق: <b>" + str(succ) + "</b> از <b>" + str(count) + "</b>", get_main_reply_keyboard(), token)
        _user_steps[user_id] = {"step": "idle"}
        return
    if step in ["wait_user_time", "wait_user_dectime"]:
        try: days = float(text)
        except: days = 0.0
        p_name = state.get("target_user")
        page = state.get("page", 1)
        tg_delete_message(chat_id, message_id, token)
        if p_name and days > 0:
            diff = days if step == "wait_user_time" else -days
            edit_peer_days_direct(p_name, diff, "wg0.conf")
            txt_res = "✅ مقدار <b>" + f"{days:g}" + " روز</b> با موفقیت " + ("اضافه" if diff > 0 else "کسر") + " شد."
            tg_send_message(chat_id, txt_res, token=token)
        show_detailed_user_tg(chat_id, p_name, page, message_id=state.get("orig_msg_id"), token=token)
        _user_steps[user_id] = {"step": "idle"}
        return
    if step in ["wait_user_vol", "wait_user_decvol"]:
        _, _, num_val = parse_volume_input_to_wg_limit(text)
        p_name = state.get("target_user")
        page = state.get("page", 1)
        tg_delete_message(chat_id, message_id, token)
        if p_name and num_val > 0:
            diff = num_val if step == "wait_user_vol" else -num_val
            edit_peer_volume_direct(p_name, diff, "wg0.conf")
            txt_res = "✅ مقدار <b>" + f"{num_val:g}" + " گیگابایت</b> با موفقیت " + ("اضافه" if diff > 0 else "کسر") + " شد."
            tg_send_message(chat_id, txt_res, token=token)
        show_detailed_user_tg(chat_id, p_name, page, message_id=state.get("orig_msg_id"), token=token)
        _user_steps[user_id] = {"step": "idle"}
        return
    if step == "wait_tpl_name":
        state["tpl_name"] = text.strip()
        state["step"] = "wait_tpl_vol"
        tg_delete_message(chat_id, message_id, token)
        if state.get("orig_msg_id"): tg_edit_message(chat_id, state["orig_msg_id"], "🏷 نام الگو: <b>" + str(text) + "</b>\n\n📊 <b>حجم الگو چقدر باشد؟</b> (مثلاً 50 یا 50GB):", None, token)
        return
    if step == "wait_tpl_vol":
        lim_str, bytes_val, num_val = parse_volume_input_to_wg_limit(text)
        state["vol_str"] = lim_str; state["vol_num"] = num_val; state["step"] = "wait_tpl_days"
        tg_delete_message(chat_id, message_id, token)
        if state.get("orig_msg_id"): tg_edit_message(chat_id, state["orig_msg_id"], "📊 حجم الگو: <code>" + str(lim_str) + "</code>\n\n⏳ <b>زمان الگو چند روز باشد؟</b>:", None, token)
        return
    if step == "wait_tpl_days":
        try: days = int(text)
        except: days = 30
        state["days"] = days
        tg_delete_message(chat_id, message_id, token)
        kb = {"inline_keyboard": [[{"text": "⏱ در اولین اتصال", "callback_data": "tplcalc_first_conn"}, {"text": "⚡ همین الان", "callback_data": "tplcalc_now"}]]}
        if state.get("orig_msg_id"): tg_edit_message(chat_id, state["orig_msg_id"], "⏳ زمان: <code>" + str(days) + " روز</code>\n\n⚙️ <b>نحوه محاسبه زمان الگو چگونه باشد؟</b>", kb, token)
        return
    if step in ["wait_tpl_prefix_single", "wait_tpl_prefix_bulk"]:
        prefix = re.sub(r"[^a-zA-Z0-9_]", "", text)
        qtype = "single" if "single" in step else "bulk"
        tpl_id = state.get("tpl_id")
        tg_delete_message(chat_id, message_id, token)
        if qtype == "single":
            conn = get_db_conn(); cur = conn.cursor()
            tpl = cur.execute("SELECT * FROM templates WHERE id=?", (tpl_id,)).fetchone()
            conn.close()
            if tpl:
                email = str(prefix) + "_" + str(time.time_ns()%100000)
                first_u = (int(tpl["first_usage"] or 0) == 1)
                lim_str, _, _ = parse_volume_input_to_wg_limit(tpl["vol"])
                ok, res_obj = create_peer_native(email, lim_str, tpl["days"], first_usage=first_u)
                if ok:
                    sub_l = res_obj["sub_url"]
                    calc_txt = "در اولین اتصال" if first_u else "همین الان"
                    card = "✅ <b>سرویس الگو ساخته شد!</b>\n\n📦 الگو: <b>" + str(tpl["name"]) + "</b>\n👤 نام: <code>" + str(email) + "</code>\n📊 حجم: <code>" + str(lim_str) + "</code>\n⏳ زمان: <code>" + str(tpl["days"]) + " روز</code>\n⏱ شروع: <code>" + str(calc_txt) + "</code>\n🔗 لینک:\n<code>" + str(sub_l) + "</code>"
                    tg_send_message(chat_id, card, {"inline_keyboard": [[{"text": "📥 استخراج کانفیگ", "callback_data": "extwg_" + str(email)}]]}, token)
            _user_steps[user_id] = {"step": "idle"}
        else:
            state["prefix"] = prefix; state["step"] = "wait_tpl_bulk_count"
            tg_send_message(chat_id, "🔢 تعداد اکانت‌هایی که می‌خواهید با این الگو ساخته شود را وارد کنید (مثلاً 5):", token=token)
        return
    if step == "wait_tpl_bulk_count":
        try: count = int(text)
        except: count = 5
        count = min(50, max(1, count))
        tpl_id = state.get("tpl_id")
        prefix = state.get("prefix", "user")
        tg_delete_message(chat_id, message_id, token)
        conn = get_db_conn(); cur = conn.cursor()
        tpl = cur.execute("SELECT * FROM templates WHERE id=?", (tpl_id,)).fetchone()
        conn.close()
        if tpl:
            tg_send_message(chat_id, "⏳ در حال ساخت <b>" + str(count) + "</b> کاربر الگو...", token=token)
            succ = 0
            first_u = (int(tpl["first_usage"] or 0) == 1)
            lim_str, _, _ = parse_volume_input_to_wg_limit(tpl["vol"])
            for i in range(1, count + 1):
                email = str(prefix) + "_" + str(time.time_ns()%100000)
                ok, res_obj = create_peer_native(email, lim_str, tpl["days"], first_usage=first_u)
                if ok:
                    succ += 1
                    sub_l = res_obj["sub_url"]
                    card = "🎁 <b>کاربر شماره " + str(i) + " (الگو):</b>\n👤 نام: <code>" + str(email) + "</code>\n📊 حجم: <code>" + str(lim_str) + "</code>\n⏳ زمان: <code>" + str(tpl["days"]) + " روز</code>\n🔗 لینک:\n<code>" + str(sub_l) + "</code>"
                    tg_send_message(chat_id, card, {"inline_keyboard": [[{"text": "📥 استخراج کانفیگ", "callback_data": "extwg_" + str(email)}]]}, token)
            tg_send_message(chat_id, "🏁 ساخت گروهی به پایان رسید.\n✅ تعداد موفق: <b>" + str(succ) + "</b> از <b>" + str(count) + "</b>", get_main_reply_keyboard(), token)
        _user_steps[user_id] = {"step": "idle"}
        return
    if cb_data:
        cb_id = cb.get("id")
        if cb_data.startswith("mg_list_"):
            page = int(cb_data.replace("mg_list_", ""))
            show_users_list_tg(chat_id, user_id, page, message_id=message_id, token=token)
            return
        if cb_data == "mg_search":
            _user_steps[user_id] = {"step": "wait_search_query", "orig_msg_id": message_id}
            tg_edit_message(chat_id, message_id, "🔍 <b>نام یا پیشوند کلاینت را ارسال فرمایید:</b>", None, token)
            return
        if cb_data.startswith("mg_det_"):
            raw_payload = cb_data.replace("mg_det_", "")
            parts = raw_payload.rsplit("_", 1)
            p_name = parts[0]
            page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            show_detailed_user_tg(chat_id, p_name, page, message_id=message_id, token=token)
            return
        if cb_data == "create_manual":
            kb = {"inline_keyboard": [[{"text": "👤 تکی", "callback_data": "man_type_single"}, {"text": "👥 دست جمعی", "callback_data": "man_type_bulk"}]]}
            tg_edit_message(chat_id, message_id, "نوع ساخت اشتراک دستی را انتخاب کنید:", kb, token)
            return
        if cb_data in ["man_type_single", "man_type_bulk"]:
            _user_steps[user_id] = {"step": "wait_manual_prefix", "qty_type": "single" if cb_data == "man_type_single" else "bulk", "orig_msg_id": message_id}
            tg_edit_message(chat_id, message_id, "✍️ لطفاً <b>نام اشتراک (پیشوند)</b> را انگلیسی وارد کنید:", None, token)
            return
        if cb_data in ["calc_first_conn", "calc_now"]:
            state["first_usage"] = cb_data
            if state.get("qty_type") == "single":
                tg_edit_message(chat_id, message_id, "⏳ در حال ساخت کلاینت...", None, token)
                email = str(state["prefix"]) + "_" + str(time.time_ns()%100000)
                first_u = (cb_data == "calc_first_conn")
                ok, res_obj = create_peer_native(email, state["vol_str"], state["days"], first_usage=first_u)
                if ok:
                    sub_l = res_obj["sub_url"]
                    calc_txt = "در اولین اتصال" if first_u else "همین الان"
                    card = "✅ <b>سرویس با موفقیت ساخته شد!</b>\n\n👤 نام: <code>" + str(email) + "</code>\n📊 حجم: <code>" + str(state["vol_str"]) + "</code>\n⏳ زمان: <code>" + str(state["days"]) + " روز</code>\n⏱ شروع: <code>" + str(calc_txt) + "</code>\n🔗 لینک:\n<code>" + str(sub_l) + "</code>"
                    tg_edit_message(chat_id, message_id, card, {"inline_keyboard": [[{"text": "📥 استخراج کانفیگ", "callback_data": "extwg_" + str(email)}]]}, token)
                else: tg_edit_message(chat_id, message_id, "❌ خطا: " + str(res_obj), None, token)
                _user_steps[user_id] = {"step": "idle"}
            else:
                state["step"] = "wait_manual_bulk_count"
                tg_edit_message(chat_id, message_id, "🔢 تعداد اکانت‌هایی که می‌خواهید ساخته شود را وارد کنید (مثلاً 5):", None, token)
            return
        if cb_data == "create_template":
            show_templates_list_tg(chat_id, user_id=user_id, message_id=message_id, token=token)
            return
        if cb_data == "start_action":
            welcome = "🤖 <b>به ربات مدیریت هوشمند وایرگارد خوش آمدید!</b>\n\n✅ اتصال شما تایید شد. لطفاً گزینه مورد نظر را انتخاب کنید:"
            tg_edit_message(chat_id, message_id, welcome, None, token)
            return
        if cb_data == "tpl_add":
            _user_steps[user_id] = {"step": "wait_tpl_name", "orig_msg_id": message_id}
            tg_edit_message(chat_id, message_id, "🏷 <b>نام الگوی جدید را وارد کنید:</b>\n(مثلاً: ۱ ماهه ۵۰ گیگ)", None, token)
            return
        if cb_data in ["tplcalc_first_conn", "tplcalc_now"]:
            first_u = 1 if cb_data == "tplcalc_first_conn" else 0
            tpl_name = state.get("tpl_name", "الگوی من")
            vol_str = state.get("vol_str", "50GiB")
            days_val = int(state.get("days", 30))
            conn = get_db_conn(); cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0, name TEXT NOT NULL, vol TEXT NOT NULL, days INTEGER NOT NULL, first_usage INTEGER DEFAULT 1)")
            cur.execute("INSERT INTO templates (user_id, name, vol, days, first_usage) VALUES (?, ?, ?, ?, ?)", (user_id, tpl_name, vol_str, days_val, first_u))
            conn.commit(); conn.close()
            tg_answer_callback(cb_id, "✅ الگوی '" + str(tpl_name) + "' با موفقیت ذخیره شد!", alert=True, token=token)
            _user_steps[user_id] = {"step": "idle"}
            show_templates_list_tg(chat_id, user_id=user_id, message_id=message_id, token=token)
            return
        if cb_data.startswith("tpl_view_"):
            tpl_id = int(cb_data.replace("tpl_view_", ""))
            conn = get_db_conn(); cur = conn.cursor()
            tpl = cur.execute("SELECT * FROM templates WHERE id=?", (tpl_id,)).fetchone()
            conn.close()
            if tpl:
                calc_txt = "در اولین اتصال" if (int(tpl["first_usage"] or 0) == 1) else "همین الان"
                msg_tpl = "📦 <b>الگو:</b> " + str(tpl["name"]) + "\n📊 حجم: <code>" + str(tpl["vol"]) + "</code>\n⏳ زمان: <code>" + str(tpl["days"]) + " روز</code>\n⏱ نحوه محاسبه: <code>" + str(calc_txt) + "</code>\n\nعملیات مورد نظر را انتخاب کنید:"
                kb_tpl = [
                    [{"text": "👤 ساخت ۱ کاربر تکی", "callback_data": "tplrun_single_" + str(tpl_id)}, {"text": "👥 ساخت گروهی", "callback_data": "tplrun_bulk_" + str(tpl_id)}],
                    [{"text": "🗑 حذف این الگو", "callback_data": "tpldel_" + str(tpl_id)}],
                    [{"text": "🔙 بازگشت به لیست الگوها", "callback_data": "create_template"}]
                ]
                tg_edit_message(chat_id, message_id, msg_tpl, {"inline_keyboard": kb_tpl}, token)
            return
        if cb_data.startswith("tplrun_"):
            parts = cb_data.replace("tplrun_", "").split("_")
            qtype, tpl_id = parts[0], int(parts[1])
            _user_steps[user_id] = {"step": "wait_tpl_prefix_" + str(qtype), "tpl_id": tpl_id, "orig_msg_id": message_id}
            tg_edit_message(chat_id, message_id, "✍️ <b>نام اشتراک (پیشوند)</b> را انگلیسی وارد کنید:", None, token)
            return
        if cb_data.startswith("tpldel_"):
            tpl_id = int(cb_data.replace("tpldel_", ""))
            conn = get_db_conn(); cur = conn.cursor()
            cur.execute("DELETE FROM templates WHERE id=?", (tpl_id,))
            conn.commit(); conn.close()
            tg_answer_callback(cb_id, "🗑 الگو حذف شد.", alert=True, token=token)
            show_templates_list_tg(chat_id, user_id=user_id, message_id=message_id, token=token)
            return
        if cb_data.startswith("sendqr_"):
            p_name = cb_data.replace("sendqr_", "")
            tg_answer_callback(cb_id, "📷 در حال ساخت QR Code...", token=token)
            send_peer_qr_image_tg(chat_id, p_name, token=token)
            return
        if cb_data.startswith("extwg_"):
            p_name = cb_data.replace("extwg_", "")
            tg_answer_callback(cb_id, "📥 دریافت کانفیگ‌ها...", token=token)
            try:
                sub_url = get_peer_sublink_url(p_name, "wg0.conf")
                cfgs = extract_wireguard_configs_from_sub(sub_url, p_name)
                if cfgs:
                    for c_obj in cfgs:
                        cap = "⚙️ <b>نام فایل:</b> <code>" + str(c_obj["name"]) + "</code>\n📍 <b>موقعیت:</b> " + str(c_obj.get("emoji","🌐")) + " " + str(c_obj.get("location_name","اصلی"))
                        tg_send_document(chat_id, c_obj["name"], c_obj["content"], caption=cap, token=token)
                else: tg_send_message(chat_id, "❌ امکان دریافت کانفیگ برای " + str(p_name) + " وجود ندارد.", token=token)
            except Exception as e:
                bot_write_log("Export Error: " + str(e), "ERROR")
                tg_send_message(chat_id, "❌ خطا: " + str(e), token=token)
            return
        if cb_data.startswith("mg_act_rstvol_"):
            parts = cb_data.replace("mg_act_rstvol_", "").split("_")
            p_name, page = parts[0], int(parts[1]) if len(parts) > 1 else 1
            credit_to_vault_permanently(p_name, "wg0.conf")
            conn = get_db_conn(); cur = conn.cursor()
            cur.execute("UPDATE peers SET local_used=0, used=0 WHERE peer_name=?", (p_name,))
            cur.execute("UPDATE peer_synced_edges SET node_used=0 WHERE peer_name=?", (p_name,))
            conn.commit(); conn.close()
            sync_action_to_edges("reset", p_name, "wg0.conf")
            tg_answer_callback(cb_id, "🔄 ترافیک مصرفی " + str(p_name) + " صفر شد.", alert=True, token=token)
            show_detailed_user_tg(chat_id, p_name, page, message_id=message_id, token=token)
            return
        if cb_data.startswith("mg_act_"):
            raw_act = cb_data.replace("mg_act_", "")
            for act_prefix in ["dectime_", "decvol_", "toggle_", "time_", "vol_", "del_"]:
                if raw_act.startswith(act_prefix):
                    action = act_prefix.rstrip("_")
                    rem_str = raw_act[len(act_prefix):]
                    parts = rem_str.rsplit("_", 1)
                    p_name = parts[0]
                    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                    break
            if action == "del":
                kb = {"inline_keyboard": [[{"text": "بله، حذف شود ✅", "callback_data": "mg_confirm_del_" + str(p_name) + "_" + str(page)}], [{"text": "خیر ❌", "callback_data": "mg_det_" + str(p_name) + "_" + str(page)}]]}
                tg_edit_message(chat_id, message_id, "⚠️ <b>آیا مطمئن هستید که می‌خواهید کاربر <code>" + str(p_name) + "</code> را حذف کنید؟</b>", kb, token)
                return
            if action == "toggle":
                ok, st_msg = toggle_peer_direct(p_name, "wg0.conf")
                show_detailed_user_tg(chat_id, p_name, page, message_id=message_id, token=token)
                return
            if action in ["time", "dectime", "vol", "decvol"]:
                _user_steps[user_id] = {"step": "wait_user_" + str(action), "target_user": p_name, "page": page, "orig_msg_id": message_id}
                txt_lbl = "زمان (به روز)" if "time" in action else "حجم (به گیگابایت)"
                tg_edit_message(chat_id, message_id, "✍️ مقدار <b>" + str(txt_lbl) + "</b> مورد نظر برای <code>" + str(p_name) + "</code> را ارسال کنید:\n(مثلاً 5 برای روز یا 2 برای گیگابایت)", None, token)
                return
        if cb_data.startswith("mg_confirm_del_"):
            parts = cb_data.replace("mg_confirm_del_", "").split("_")
            p_name, page = parts[0], int(parts[1]) if len(parts) > 1 else 1
            try:
                conn = get_db_conn(); cur = conn.cursor()
                r = cur.execute("SELECT public_key, peer_ip, config FROM peers WHERE peer_name=?", (p_name,))
                r = cur.fetchone()
                cfg_f = "wg0.conf"
                if r:
                    pub_k, p_ip = r[0], r[1]
                    cfg_f = r[2] if len(r) > 2 and r[2] else "wg0.conf"
                    iface = cfg_f.replace(".conf", "")
                    if pub_k: subprocess.run("wg set " + str(iface) + " peer " + str(pub_k) + " remove", shell=True, stderr=subprocess.DEVNULL)
                    if p_ip: subprocess.run("ip route del blackhole " + str(p_ip), shell=True, stderr=subprocess.DEVNULL)
                cur.execute("DELETE FROM peers WHERE peer_name=?", (p_name,))
                cur.execute("DELETE FROM services WHERE email=?", (p_name,))
                cur.execute("DELETE FROM short_links WHERE long_link LIKE ?", ("%" + str(p_name) + "%",))
                cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=?", (p_name,))
                conn.commit(); conn.close()
                reconcile_db_and_conf_files()
                sync_action_to_edges("delete", p_name, cfg_f)
                bot_write_log("Peer '" + str(p_name) + "' successfully deleted", "INFO")
                tg_send_message(chat_id, "🗑 کاربر <code>" + str(p_name) + "</code> با موفقیت کامل حذف شد.", token=token)
            except Exception as ex_del:
                bot_write_log("Delete error: " + str(ex_del), "ERROR")
                tg_send_message(chat_id, "❌ خطا در حذف: " + str(ex_del), token=token)
            show_users_list_tg(chat_id, user_id, page, message_id=message_id, token=token)
            return
        if cb_data == "bulk_del_inactive_yes":
            conn = get_db_conn(); cur = conn.cursor()
            del_list = [r[0] for r in cur.execute("SELECT peer_name FROM peers WHERE monitor_blocked=1 OR expiry_blocked=1").fetchall()]
            for d_name in del_list:
                cur.execute("DELETE FROM peers WHERE peer_name=?", (d_name,))
                cur.execute("DELETE FROM services WHERE email=?", (d_name,))
                cur.execute("DELETE FROM short_links WHERE long_link LIKE ?", ("%" + str(d_name) + "%",))
                cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=?", (d_name,))
                sync_action_to_edges("delete", d_name, "wg0.conf")
            conn.commit(); conn.close()
            reconcile_db_and_conf_files()
            tg_edit_message(chat_id, message_id, "✅ پاکسازی تکمیل شد. تعداد <b>" + str(len(del_list)) + "</b> کاربر غیرفعال حذف شدند.", None, token)
            return
        if cb_data == "bulk_del_inactive_no":
            tg_edit_message(chat_id, message_id, "☑️ عملیات پاکسازی لغو شد.", None, token)
            return

def start_bot_polling_daemon():
    global _bot_worker_thread, _bot_worker_running
    if _bot_worker_running: return
    _bot_worker_running = True
    def polling_loop():
        time.sleep(2)
        offset = 0
        while _bot_worker_running:
            try:
                token = get_bot_active_token()
                status = get_bot_status_str()
                if not token or status != "on":
                    time.sleep(6); continue
                url = "https://api.telegram.org/bot" + str(token) + "/getUpdates?offset=" + str(offset) + "&timeout=15"
                with urllib.request.urlopen(urllib.request.Request(url), timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("ok"):
                        for update in data.get("result", []):
                            offset = update["update_id"] + 1
                            process_telegram_update(update, token)
            except: time.sleep(3)
    _bot_worker_thread = threading.Thread(target=polling_loop, daemon=True)
    _bot_worker_thread.start()

def stop_bot_polling_daemon():
    global _bot_worker_running
    _bot_worker_running = False

if get_bot_status_str() == "on": start_bot_polling_daemon()

def check_and_send_reseller_alerts():
    try:
        conn = get_db_conn(); cur = conn.cursor()
        resellers = [dict(r) for r in cur.execute("SELECT interface_name, username, data_limit_gb, status FROM sub_panels").fetchall()]
        admin_chat = get_bot_admin_chat_id()
        bot_token = get_bot_active_token()
        for r in resellers:
            iface = r["interface_name"]
            uname = r["username"]
            limit_gb = float(r.get("data_limit_gb") or 0)
            status = r.get("status", "active")
            used_b = cur.execute("SELECT SUM(used) FROM peers WHERE config=? OR config=?", (iface + ".conf", iface)).fetchone()[0] or 0
            used_gb = used_b / (1024 * 1024 * 1024)
            if admin_chat and limit_gb > 0:
                if (used_gb / limit_gb) >= 0.80 and (used_gb / limit_gb) < 1.0:
                    tg_send_message(admin_chat, "⚠️ <b>هشدار ۸۰٪ مصرف (" + str(iface) + "):</b>\nنماینده <code>" + str(uname) + "</code> بیش از ۸۰٪ حجم خود را مصرف کرده است.\nمصرف: " + f"{used_gb:.2f}" + "GB / " + str(limit_gb) + "GB", token=bot_token)
                elif status != "active" or used_gb >= limit_gb:
                    tg_send_message(admin_chat, "🚨 <b>اخطار قطع سرویس (" + str(iface) + "):</b>\nاینترفیس <code>" + str(iface) + "</code> به دلیل اتمام ترافیک خاموش شد.", token=bot_token)
        conn.close()
    except: pass

def start_bot_alert_daemon():
    def alert_loop():
        time.sleep(15)
        while True:
            check_and_send_reseller_alerts()
            time.sleep(30)
    threading.Thread(target=alert_loop, daemon=True).start()

start_bot_alert_daemon()

def bot_write_log(message, level="INFO"):
    cur_d = get_resolved_dir()
    log_file = os.path.join(cur_d, "bot_debug.log")
    log_entry = "[" + time.strftime("%Y-%m-%d %H:%M:%S") + "] [" + str(level) + "] " + str(message) + "\n"
    try:
        with open(log_file, "a", encoding="utf-8") as f: f.write(log_entry)
    except: pass

def check_reseller_access_and_quota(user_id, chat_id, token):
    admin_chat = get_bot_admin_chat_id()
    if str(chat_id).strip() == str(admin_chat).strip(): return True, ""
    try:
        conn = get_db_conn(); cur = conn.cursor()
        cur.execute("SELECT interface_name, username, data_limit_gb, status, deleted_traffic FROM sub_panels WHERE username=? OR interface_name=?", (str(user_id), str(user_id)))
        row = cur.fetchone()
        if row:
            iface = row["interface_name"]
            uname = row["username"]
            limit_gb = float(row["data_limit_gb"] or 0)
            status = str(row["status"] or "active").lower()
            del_traffic = int(row["deleted_traffic"] or 0)
            if status != "active":
                conn.close()
                return False, "🚫 <b>دسترسی نمایندگی (" + str(uname) + ") مسدود است!</b>\n\nاینترفیس <code>" + str(iface) + "</code> غیرفعال شده است."
            if limit_gb > 0:
                cur.execute("SELECT SUM(used) FROM peers WHERE config=? OR config=?", (iface + ".conf", iface))
                used_sum = cur.fetchone()[0] or 0
                total_used_bytes = del_traffic + used_sum
                if total_used_bytes >= (limit_gb * 1073741824):
                    conn.close()
                    used_gb_str = f"{total_used_bytes / (1024**3):.2f} GB"
                    return False, "🚨 <b>سقف ترافیک نمایندگی به پایان رسیده است!</b>\n\nمصرف شما: <code>" + str(used_gb_str) + "</code> از <code>" + str(limit_gb) + " GB</code>"
        conn.close()
    except: pass
    return True, ""

def run_accurate_time_countdown():
    ensure_edge_table_columns()
    try:
        conn = get_db_conn(); cur = conn.cursor()
        cur.execute("SELECT id, peer_name, config, remaining_time, first_usage, used, peer_ip, public_key FROM peers WHERE monitor_blocked=0 AND expiry_blocked=0")
        active_peers = [dict(r) for r in cur.fetchall()]
        for p in active_peers:
            pid = p["id"]
            p_name = p["peer_name"]
            cfg = p.get("config", "wg0.conf")
            rem = int(p.get("remaining_time") or 0)
            used_b = int(p.get("used") or 0)
            f_raw = str(p.get("first_usage", "0")).strip().lower()
            is_first_u = (f_raw in ["1", "true", "yes", "calc_first_conn"])
            has_traffic = (used_b > 1024)
            if is_first_u and not has_traffic:
                try:
                    cur.execute("SELECT SUM(node_used) FROM peer_synced_edges WHERE peer_name=?", (p_name,))
                    r_edge = cur.fetchone()
                    if r_edge and r_edge[0] and int(r_edge[0]) > 1024: has_traffic = True
                except: pass
            if is_first_u and has_traffic:
                cur.execute("UPDATE peers SET first_usage='0' WHERE id=?", (pid,))
                is_first_u = False
            if is_first_u: continue
            new_rem = max(0, rem - 1)
            if new_rem <= 0:
                cur.execute("UPDATE peers SET remaining_time=0, monitor_blocked=1, expiry_blocked=1 WHERE id=?", (pid,))
                if p.get("peer_ip"): subprocess.run("ip route add blackhole " + str(p["peer_ip"]), shell=True, stderr=subprocess.DEVNULL)
                if p.get("public_key"):
                    iface = cfg.replace(".conf", "") if str(cfg).endswith(".conf") else str(cfg)
                    subprocess.run("wg set " + str(iface) + " peer " + str(p["public_key"]) + " remove", shell=True, stderr=subprocess.DEVNULL)
                sync_action_to_edges("toggle", p_name, cfg, {"blocked": True})
            else:
                cur.execute("UPDATE peers SET remaining_time=? WHERE id=?", (new_rem, pid))
        conn.commit(); conn.close()
    except Exception as ex_t:
        bot_write_log("Countdown worker error: " + str(ex_t), "ERROR")

def start_time_worker_loop():
    global _time_worker_running
    if _time_worker_running: return
    _time_worker_running = True
    def loop():
        time.sleep(5)
        while True:
            run_accurate_time_countdown()
            time.sleep(60)
    threading.Thread(target=loop, daemon=True).start()

start_time_worker_loop()

def bind_v100_hooks(app_instance):
    globals()["sync_single_peer_action_to_edges"] = sync_action_to_edges
    globals()["credit_to_vault_permanently"] = credit_to_vault_permanently
    globals()["reconcile_db_and_conf_files"] = reconcile_db_and_conf_files
    try:
        app_instance.view_functions["short_redirect"] = universal_sublink_renderer
        app_instance.view_functions["short_download_config"] = short_download_config_native
    except: pass