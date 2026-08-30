# ========================================================================= #
# نام فایل: v100_master_edge_sync.py                                        #
# نقش: موتور یکپارچه همگام‌ساز کلاستر، ربات تلگرام چندکاربره و رندر ساب‌لینک #
# ========================================================================= #

import os
import sys
import sqlite3
import subprocess
import json
import re
import base64
import requests
import urllib.parse
import urllib.request
import urllib.error
import threading
import time
import math
import secrets
import html         # <-- اضافه شد جهت فرار از تگ‌های HTML در تلگرام
import traceback    # <-- اضافه شد جهت لاگ‌گیری استک خطاها
from flask import Response, request, jsonify, render_template, make_response, session, redirect

_last_sync_times = {}
_sync_lock = threading.Lock()
_edge_sessions = {}
_aggregator_started = False
_bot_worker_running = False
_time_worker_running = False
_active_polling_threads = {}
_user_steps = {}

_cached_public_ip = None
_cached_public_ip_time = 0

# -------------------------------------------------------------------------
# 📂 توابع کمکی و استخراج مسیرهای امن سیستم
# -------------------------------------------------------------------------
def get_resolved_dir():
    return os.path.dirname(os.path.abspath(__file__))

def get_resolved_cfg_path():
    cur_d = get_resolved_dir()
    p = os.path.join(cur_d, "telegram_bot_config.json")
    if not os.path.exists(p):
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"t": "", "c": "", "status": "off"}, f, indent=4)
        except Exception:
            pass
    return p

def ensure_edge_interface(s_ip, s_port, s_user, s_pass, cfg_name):
    """تضمین وجود و آماده‌سازی فایل کانفیگ اینترفیس روی نود لبه"""
    clean_iface, num, target_subnet, target_port = get_interface_network_params(cfg_name)
    script = f'''import os, subprocess, re

iface = "{clean_iface}"
conf_path = f"/etc/wireguard/{clean_iface}.conf"
target_subnet = "{target_subnet}"
target_port = {target_port}

if not os.path.exists(conf_path):
    priv = subprocess.getoutput("wg genkey").strip()
    nic = subprocess.getoutput("ip route | grep default | awk '{{print $5}}' | head -n1").strip() or "eth0"
    conf_data = (
        f"[Interface]\\n"
        f"PrivateKey = {{priv}}\\n"
        f"ListenPort = {{target_port}}\\n"
        f"Address = {{target_subnet}}\\n"
        f"SaveConfig = false\\n"
        f"PostUp = iptables -A FORWARD -i {{iface}} -j ACCEPT; iptables -t nat -A POSTROUTING -o {{nic}} -j MASQUERADE\\n"
        f"PostDown = iptables -D FORWARD -i {{iface}} -j ACCEPT; iptables -t nat -D POSTROUTING -o {{nic}} -j MASQUERADE\\n"
    )
    with open(conf_path, "w", encoding="utf-8") as f:
        f.write(conf_data)
    subprocess.run("systemctl daemon-reload", shell=True, stderr=subprocess.DEVNULL)
'''
    enc = base64.b64encode(script.encode('utf-8')).decode('utf-8')
    cmd = f"echo '{enc}' | base64 -d > /tmp/ensure_iface.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/ensure_iface.py && rm -f /tmp/ensure_iface.py"
    subprocess.run(
        f"sshpass -p '{s_pass}' ssh -p {s_port or 22} -o StrictHostKeyChecking=no -o ConnectTimeout=4 {s_user}@{s_ip} \"{cmd}\"",
        shell=True, stderr=subprocess.DEVNULL
    )

def get_resolved_db_path():
    candidates = [
        os.path.join(get_resolved_dir(), "db.sqlite3"),
        "/usr/local/bin/Wireguard-panel/src/db.sqlite3",
        "/etc/wireguard/db.sqlite3"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]

from sqlite_backend import _db_lock

def get_db_conn():
    p = get_resolved_db_path()
    conn = sqlite3.connect(p, timeout=60.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row
    return conn

# -------------------------------------------------------------------------
# 🤖 تنظیمات و احراز هویت تلگرام
# -------------------------------------------------------------------------
def load_bot_config_persistent():
    cfg_p = get_resolved_cfg_path()
    etc_p = "/etc/wireguard/telegram_bot_config.json"
    if os.path.exists(cfg_p):
        try:
            data = json.load(open(cfg_p, "r", encoding="utf-8"))
            if data.get("t"):
                return data
        except Exception:
            pass
    if os.path.exists(etc_p):
        try:
            data = json.load(open(etc_p, "r", encoding="utf-8"))
            if data.get("t"):
                try:
                    json.dump(data, open(cfg_p, "w", encoding="utf-8"), indent=4)
                except Exception:
                    pass
                return data
        except Exception:
            pass
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS system_config (key_name TEXT PRIMARY KEY, value_text TEXT)")
        row = cur.execute("SELECT value_text FROM system_config WHERE key_name='telegram_bot_config'").fetchone()
        conn.close()
        if row and row[0]:
            data = json.loads(row[0])
            try:
                json.dump(data, open(cfg_p, "w", encoding="utf-8"), indent=4)
            except Exception:
                pass
            return data
    except Exception:
        pass
    return {"t": "", "c": "", "status": "off"}

def get_bot_active_token():
    return load_bot_config_persistent().get("t", "").strip()

def get_bot_admin_chat_id():
    return load_bot_config_persistent().get("c", "").strip()

def get_bot_status_str():
    return load_bot_config_persistent().get("status", "off")

def get_all_active_bot_tokens():
    tokens = set()
    master_tok = get_bot_active_token()
    if master_tok:
        tokens.add(master_tok)
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(sub_panels)")
        cols = [c[1] for c in cur.fetchall()]
        if "telegram_bot_token" in cols:
            rows = cur.execute("SELECT telegram_bot_token FROM sub_panels WHERE status='active' AND telegram_bot_token IS NOT NULL AND telegram_bot_token != ''").fetchall()
            for r in rows:
                if r[0] and r[0].strip():
                    tokens.add(r[0].strip())
        conn.close()
    except Exception:
        pass
    return list(tokens)

def clean_html_tags(raw_html):
    """حذف تگ‌های HTML برای ایجاد متون تمیز در کپشن تلگرام"""
    if not raw_html:
        return ""
    clean = re.sub(r'<[^>]+>', '', str(raw_html))
    return html.unescape(clean).strip()

def get_peer_all_subscription_configs(peer_name, config_file="wg0.conf"):
    """
    استخراج و ساخت تمام فایل‌های کانفیگ با مشخصات دقیق و یکسان با صفحه ساب‌لینک:
    - نام فایل (با پسوند پلن مثلاً user1-Gaming.conf)
    - عنوان پلن و سرور (همراه با پرچم)
    - توضیحات اختصاصی پلن
    - محتوای دقیق کانفیگ وایرگارد بر اساس سرور مبدا یا سرور لبه (Edge)
    """
    clean_cfg = config_file if str(config_file).endswith(".conf") else f"{config_file}.conf"
    iface = clean_cfg.replace(".conf", "")
    
    conn = get_db_conn()
    cur = conn.cursor()
    
    # واکشی اطلاعات کلاینت
    cur.execute("SELECT * FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
    peer_rec = cur.fetchone()
    if not peer_rec:
        cur.execute("SELECT * FROM peers WHERE peer_name=?", (peer_name,))
        peer_rec = cur.fetchone()
        
    if not peer_rec:
        conn.close()
        return []
        
    p_dict = dict(peer_rec)
    client_priv_key = p_dict.get("private_key") or ""
    client_ip = p_dict.get("peer_ip") or "10.0.0.2"
    base_mtu = p_dict.get("mtu") or 1420
    base_dns = p_dict.get("dns") or "1.1.1.1, 1.0.0.1"
    base_keepalive = p_dict.get("persistent_keepalive") or 25
    base_allowed_ips = p_dict.get("allowed_ips") or "0.0.0.0/0, ::/0"

    # بررسی حالت ویژه (Special Mode)
    special_mode = 1
    try:
        cur.execute("SELECT special_mode FROM client_settings WHERE interface_name = ?", (iface,))
        sm_row = cur.fetchone()
        if sm_row and sm_row[0] is not None:
            special_mode = int(sm_row[0])
    except Exception:
        pass

    # اطلاعات سرور اصلی
    master_name = "سرور اصلی"
    master_flag = get_master_flag_and_location()
    master_suffix = ""
    master_endpoint = ""
    try:
        cur.execute("SELECT endpoint_domain, ssh_ip, server_name, file_suffix FROM master_settings LIMIT 1")
        m_row = cur.fetchone()
        if m_row:
            if m_row["server_name"]: master_name = m_row["server_name"].strip()
            if m_row["file_suffix"]: master_suffix = m_row["file_suffix"].strip()
            if m_row["endpoint_domain"]: master_endpoint = m_row["endpoint_domain"].strip()
            elif m_row["ssh_ip"]: master_endpoint = m_row["ssh_ip"].strip()
    except Exception:
        pass

    if not master_endpoint:
        master_endpoint = get_server_public_ip_cached()

    # پورت و کلید سرور اصلی
    master_listen_port = 51820
    master_pub_key = ""
    master_conf_path = f"/etc/wireguard/{clean_cfg}"
    if os.path.exists(master_conf_path):
        try:
            with open(master_conf_path, "r", encoding="utf-8", errors="ignore") as f:
                cf_text = f.read()
            p_m = re.search(r"ListenPort\s*=\s*(\d+)", cf_text, re.I)
            if p_m: master_listen_port = int(p_m.group(1))
            pr_m = re.search(r"PrivateKey\s*=\s*(.*)", cf_text, re.I)
            if pr_m:
                s_priv = pr_m.group(1).strip()
                proc = subprocess.run(["wg", "pubkey"], input=s_priv, universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if proc.returncode == 0 and proc.stdout.strip():
                    master_pub_key = proc.stdout.strip()
        except Exception:
            pass

    # سرورهای لبه (Edge)
    all_edge_servers = []
    try:
        cur.execute("SELECT id, server_ip, flag, location, server_name, file_suffix, panel_url, panel_user, panel_pass FROM edge_servers")
        all_edge_servers = [dict(r) for r in cur.fetchall()]
    except Exception:
        pass

    synced_edge_ips = set()
    try:
        cur.execute("SELECT server_ip FROM peer_synced_edges WHERE peer_name = ? AND (config = ? OR config = ?)", (peer_name, clean_cfg, iface))
        for s_row in cur.fetchall():
            if s_row["server_ip"]:
                synced_edge_ips.add(s_row["server_ip"].strip())
    except Exception:
        pass

    configs_list = []

    # 📌 حالت ۱: اگر پلن‌های ویژه (Special Mode) فعال باشند
    if special_mode == 1:
        try:
            cur.execute("SELECT id, plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers FROM subscription_plans")
            plans = [dict(r) for r in cur.fetchall()]

            for p_row in plans:
                p_name = p_row["plan_name"]
                p_desc = p_row.get("description") or ""
                p_suf = p_row.get("suffix") or ""
                plan_mtu = p_row.get("mtu") or base_mtu
                plan_dns = p_row.get("dns") or base_dns
                plan_keepalive = p_row.get("keepalive") or base_keepalive
                plan_allowed = p_row.get("allowed_ips") or base_allowed_ips
                
                try:
                    active_s = json.loads(p_row["active_servers"]) if p_row["active_servers"] else ["master"]
                except Exception:
                    active_s = ["master"]

                for srv_ip in active_s:
                    if srv_ip != "master" and srv_ip not in synced_edge_ips:
                        continue

                    # ساخت کانفیگ برای سرور اصلی
                    if srv_ip == "master":
                        s_label = f"🌐 {p_name} | {master_name} {master_flag}"
                        f_name = f"{peer_name}{p_suf}.conf"
                        
                        conf_text = f"""[Interface]
PrivateKey = {client_priv_key}
Address = {client_ip}/32
DNS = {plan_dns}
MTU = {plan_mtu}

[Peer]
PublicKey = {master_pub_key}
Endpoint = {master_endpoint}:{master_listen_port}
AllowedIPs = {plan_allowed}
PersistentKeepalive = {plan_keepalive}
"""
                        configs_list.append({
                            "file_name": f_name,
                            "server_label": s_label,
                            "description": p_desc,
                            "content": conf_text.strip()
                        })
                    else:
                        # ساخت کانفیگ برای سرور لبه (Edge)
                        e_info = next((e for e in all_edge_servers if e.get("server_ip") == srv_ip), None)
                        e_name = e_info.get("server_name") if e_info else f"سرور {e_info.get('location', 'لبه') if e_info else 'لبه'}"
                        e_fl = e_info.get("flag") if e_info else "🌍"
                        s_label = f"🛰 {p_name} | {e_name} {e_fl}"
                        f_name = f"{peer_name}{p_suf}.conf"

                        edge_client_ip = client_ip
                        edge_client_priv = client_priv_key
                        
                        cur.execute(
                            "SELECT edge_ip, edge_priv_key FROM peer_synced_edges WHERE peer_name=? AND (server_ip=? OR server_ip IN (SELECT ssh_ip FROM edge_servers WHERE server_ip=?)) AND (config=? OR config=?)",
                            (peer_name, srv_ip, srv_ip, clean_cfg, iface)
                        )
                        sync_row = cur.fetchone()
                        if sync_row:
                            if sync_row["edge_ip"] and sync_row["edge_ip"].strip():
                                edge_client_ip = sync_row["edge_ip"].strip()
                            if sync_row["edge_priv_key"] and len(sync_row["edge_priv_key"].strip()) == 44:
                                edge_client_priv = sync_row["edge_priv_key"].strip()

                        edge_endpoint = srv_ip
                        edge_port = 51820
                        edge_pub = ""
                        
                        if e_info and e_info.get("panel_url") and e_info.get("panel_user") and e_info.get("panel_pass"):
                            try:
                                session_edge = get_edge_authenticated_session(e_info["panel_url"], e_info["panel_user"], e_info["panel_pass"])
                                norm_url = e_info["panel_url"].rstrip("/")
                                det_res = session_edge.get(f"{norm_url}/api/wireguard-details?config={clean_cfg}", timeout=4)
                                if det_res.status_code == 200:
                                    d_json = det_res.json()
                                    edge_pub = d_json.get("public_key") or ""
                                    edge_port = int(d_json.get("port") or 51820)
                            except Exception:
                                pass

                        conf_text = f"""[Interface]
PrivateKey = {edge_client_priv}
Address = {edge_client_ip}/32
DNS = {plan_dns}
MTU = {plan_mtu}

[Peer]
PublicKey = {edge_pub}
Endpoint = {edge_endpoint}:{edge_port}
AllowedIPs = {plan_allowed}
PersistentKeepalive = {plan_keepalive}
"""
                        configs_list.append({
                            "file_name": f_name,
                            "server_label": s_label,
                            "description": p_desc,
                            "content": conf_text.strip()
                        })
        except Exception:
            pass

    # 📌 حالت ۲: اگر پلن ویژه‌ای تعریف نشده باشد (حالت استاندارد)
    if not configs_list or special_mode == 0:
        configs_list = []
        # سرور اصلی
        f_name_master = f"{peer_name}{master_suffix}.conf"
        conf_master = f"""[Interface]
PrivateKey = {client_priv_key}
Address = {client_ip}/32
DNS = {base_dns}
MTU = {base_mtu}

[Peer]
PublicKey = {master_pub_key}
Endpoint = {master_endpoint}:{master_listen_port}
AllowedIPs = {base_allowed_ips}
PersistentKeepalive = {base_keepalive}
"""
        configs_list.append({
            "file_name": f_name_master,
            "server_label": f"🌐 {master_name} {master_flag}",
            "description": "اتصال مستقیم به شبکه سرور اصلی",
            "content": conf_master.strip()
        })

        # سرورهای لبه
        for ef in all_edge_servers:
            e_ip = (ef.get("server_ip") or "").strip()
            if e_ip not in synced_edge_ips:
                continue

            e_name = ef.get("server_name") or f"سرور {ef.get('location', 'لبه')}"
            e_flag = ef.get("flag") or "🌍"
            e_suffix = ef.get("file_suffix") or ""
            f_name_edge = f"{peer_name}{e_suffix}.conf"

            edge_client_ip = client_ip
            edge_client_priv = client_priv_key
            cur.execute(
                "SELECT edge_ip, edge_priv_key FROM peer_synced_edges WHERE peer_name=? AND (server_ip=? OR server_ip IN (SELECT ssh_ip FROM edge_servers WHERE server_ip=?)) AND (config=? OR config=?)",
                (peer_name, e_ip, e_ip, clean_cfg, iface)
            )
            sync_row = cur.fetchone()
            if sync_row:
                if sync_row["edge_ip"] and sync_row["edge_ip"].strip():
                    edge_client_ip = sync_row["edge_ip"].strip()
                if sync_row["edge_priv_key"] and len(sync_row["edge_priv_key"].strip()) == 44:
                    edge_client_priv = sync_row["edge_priv_key"].strip()

            edge_pub = ""
            edge_port = 51820
            if ef.get("panel_url") and ef.get("panel_user") and ef.get("panel_pass"):
                try:
                    session_edge = get_edge_authenticated_session(ef["panel_url"], ef["panel_user"], ef["panel_pass"])
                    norm_url = ef["panel_url"].rstrip("/")
                    det_res = session_edge.get(f"{norm_url}/api/wireguard-details?config={clean_cfg}", timeout=4)
                    if det_res.status_code == 200:
                        d_json = det_res.json()
                        edge_pub = d_json.get("public_key") or ""
                        edge_port = int(d_json.get("port") or 51820)
                except Exception:
                    pass

            conf_edge = f"""[Interface]
PrivateKey = {edge_client_priv}
Address = {edge_client_ip}/32
DNS = {base_dns}
MTU = {base_mtu}

[Peer]
PublicKey = {edge_pub}
Endpoint = {e_ip}:{edge_port}
AllowedIPs = {base_allowed_ips}
PersistentKeepalive = {base_keepalive}
"""
            configs_list.append({
                "file_name": f_name_edge,
                "server_label": f"🛰 {e_name} {e_flag}",
                "description": f"اتصال پایدار از طریق سرور {e_name}",
                "content": conf_edge.strip()
            })

    conn.close()
    return configs_list

def parse_volume_input_to_wg_limit(val_input, unit_input="GiB"):
    if not val_input or str(val_input).strip() == "":
        return "50GiB", 50 * 1073741824, 50.0

    s = str(val_input).strip()
    for p, a, e in zip("۰۱۲۳۴۵۶۷۸۹", "٠١٢٣٤٥٦٧٨٩", "0123456789"):
        s = s.replace(p, e).replace(a, e)

    has_fraction = ('/' in s) or ('.' in s) or (',' in s) or ('٫' in s) or ('؍' in s)
    s_clean = s.replace('/', '.').replace('٫', '.').replace('؍', '.').replace(',', '.')

    m = re.match(r"^([0-9\.]+)\s*(T|TB|TIB|G|GB|GIB|M|MB|MIB|K|KB|KIB|B)?$", s_clean, re.IGNORECASE)
    if m:
        num_str = m.group(1)
        unit = (m.group(2) or str(unit_input or "GiB")).upper()
    else:
        num_str = "".join(ch for ch in s_clean if ch.isdigit() or ch == '.')
        unit = str(unit_input or "GiB").upper()

    try:
        num = float(num_str) if num_str else 1.0
    except ValueError:
        num = 1.0

    if has_fraction or (num != int(num)):
        bytes_val = int(num * 1073741824)
        wg_limit_str = f"{num:g}GiB"
        gb_val = num
    else:
        num_int = int(num)
        if "M" in unit:
            bytes_val = num_int * 1048576
            wg_limit_str = f"{num_int}MiB"
            gb_val = num_int / 1024.0
        elif "K" in unit:
            bytes_val = num_int * 1024
            wg_limit_str = f"{num_int}KiB"
            gb_val = num_int / (1024.0 * 1024.0)
        elif "T" in unit:
            bytes_val = num_int * (1024**4)
            wg_limit_str = f"{num_int}TB"
            gb_val = float(num_int * 1024)
        else:
            bytes_val = num_int * 1073741824
            wg_limit_str = f"{num_int}GiB"
            gb_val = float(num_int)

    return wg_limit_str, bytes_val, gb_val

def get_user_auth(chat_id, user_id=None):
    admin_chat = get_bot_admin_chat_id()
    if str(chat_id).strip() == str(admin_chat).strip() or (user_id and str(user_id).strip() == str(admin_chat).strip()):
        return {
            "role": "admin",
            "interface": "wg0",
            "all_interfaces": True,
            "reseller_id": 0,
            "username": "مدیر کل"
        }
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(sub_panels)")
        cols = [c[1] for c in cur.fetchall()]
        has_tg_chat = "telegram_chat_id" in cols
        
        query = "SELECT id, interface_name, username, status, data_limit_gb, deleted_traffic FROM sub_panels WHERE "
        if has_tg_chat:
            query += "(telegram_chat_id=? OR username=?)"
            params = (str(chat_id), str(user_id or chat_id))
        else:
            query += "username=?"
            params = (str(user_id or chat_id),)
            
        row = cur.execute(query, params).fetchone()
        
        if row:
            iface = row["interface_name"]
            
            # ۱. استعلام دقیق ترافیک مصرفی نماینده (ترافیک زنده + ترافیک کاربران حذف‌شده)
            cur.execute("SELECT SUM(used) FROM peers WHERE config=? OR config=?", (f"{iface}.conf", iface))
            live_used = cur.fetchone()[0] or 0
            del_traffic = int(row["deleted_traffic"] or 0)
            
            # ۲. بررسی صندوق اینترفیس (interface_vault) جهت جلوگیری از نشت آمار
            vault_bytes = 0
            try:
                cur.execute("SELECT vault_bytes FROM interface_vault WHERE interface_name=?", (iface,))
                v_row = cur.fetchone()
                if v_row and v_row[0]:
                    vault_bytes = int(v_row[0])
            except Exception:
                pass
                
            total_used_bytes = live_used + max(del_traffic, vault_bytes)
            total_used_gb = total_used_bytes / (1024.0 ** 3)
            limit_gb = float(row["data_limit_gb"] or 0.0)

            conn.close()

            # ۳. بررسی دقیق وضعیت قطع سرویس و تفکیک اتمام حجم از تعلیق دستی
            if row["status"] == 'disabled' or (limit_gb > 0 and total_used_gb >= limit_gb):
                return {
                    "role": "blocked",
                    "reason": (
                        f"🚨 <b>پنل نمایندگی شما به دلیل اتمام سقف ترافیک مسدود شده است!</b>\n\n"
                        f"⚙️ اینترفیس: <code>{iface}</code>\n"
                        f"📊 ترافیک مصرفی: <code>{total_used_gb:.2f} گیگابایت</code>\n"
                        f"📦 سقف مجاز: <code>{limit_gb:.2f} گیگابایت</code>\n\n"
                        f"⚠️ لطفاً جهت تمدید اعتبار و شارژ حجم با مدیرکل تماس بگیرید."
                    )
                }
            elif row["status"] == 'suspended':
                return {
                    "role": "blocked",
                    "reason": f"⏸ <b>پنل نمایندگی شما ({iface}) توسط مدیریت موقتاً معلق شده است.</b>"
                }

            return {
                "role": "client",
                "interface": row["interface_name"],
                "all_interfaces": False,
                "reseller_id": row["id"],
                "username": row["username"]
            }
            
        conn.close()
    except Exception:
        pass

    return {"role": "unauthorized", "reason": "❌ شما مجاز به استفاده از این ربات نیستید."}

_sync_job_status = {
    "running": False,
    "progress": 0,
    "logs": [],
    "last_result": None
}
_sync_job_lock = threading.Lock()

def get_server_public_ip_cached():
    global _cached_public_ip, _cached_public_ip_time
    now = time.time()
    if _cached_public_ip and (now - _cached_public_ip_time < 300):
        return _cached_public_ip
    for url in ["https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"]:
        try:
            res = requests.get(url, timeout=3)
            if res.status_code == 200:
                ip = res.text.strip()
                if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip) and not ip.startswith("127."):
                    _cached_public_ip = ip
                    _cached_public_ip_time = now
                    return ip
        except Exception:
            pass
    try:
        out = subprocess.getoutput("hostname -I").strip()
        for ip in out.split():
            if not ip.startswith("127.") and not ip.startswith("10.0."):
                _cached_public_ip = ip
                _cached_public_ip_time = now
                return ip
    except Exception:
        pass
    return "127.0.0.1"

def get_panel_base_url():
    port = 5000
    is_tls = False
    config_yaml_path = os.path.join(get_resolved_dir(), "config.yaml")
    if os.path.exists(config_yaml_path):
        try:
            import yaml
            with open(config_yaml_path, "r", encoding="utf-8") as yf:
                cfg = yaml.safe_load(yf) or {}
            port = cfg.get("flask", {}).get("port") or cfg.get("server", {}).get("port") or 5000
            is_tls = cfg.get("flask", {}).get("tls", False)
        except Exception:
            pass

    scheme = "https" if is_tls else "http"

    # ۱. اولویت اول: بررسی دامنه اختصاصی ساب‌لینک سرور اصلی
    try:
        with _db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(master_settings)")
            cols = [c[1] for c in cur.fetchall()]
            if "sub_domain" in cols:
                row_ms = cur.execute("SELECT sub_domain FROM master_settings LIMIT 1").fetchone()
                if row_ms and row_ms[0] and str(row_ms[0]).strip():
                    custom_sub_dom = str(row_ms[0]).strip().rstrip("/")
                    if not custom_sub_dom.startswith("http://") and not custom_sub_dom.startswith("https://"):
                        custom_sub_dom = f"{scheme}://{custom_sub_dom}"
                    conn.close()
                    return custom_sub_dom
            conn.close()
    except Exception:
        pass

    # ۲. اولویت دوم: در صورت خالی بودن، استفاده از دامنه/آی‌پی پیش‌فرض پنل
    bot_cfg = load_bot_config_persistent()
    if bot_cfg.get("panel_url") and str(bot_cfg["panel_url"]).startswith("http"):
        return bot_cfg["panel_url"].rstrip("/")

    try:
        with _db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            row_p = cur.execute("SELECT value_text FROM system_config WHERE key_name='panel_url'").fetchone()
            if row_p and row_p[0] and str(row_p[0]).startswith("http"):
                conn.close()
                return str(row_p[0]).strip().rstrip("/")
            conn.close()
    except Exception:
        pass

    server_ip = get_server_public_ip_cached()
    port_str = f":{port}" if port and port not in [80, 443] else ""
    return f"{scheme}://{server_ip}{port_str}".rstrip("/")

def get_peer_sublink_url(peer_name, config_file="wg0.conf", custom_base_url=None):
    clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
    iface = clean_cfg.replace(".conf", "")
    token = ""

    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT token, config FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
            row = cur.fetchone()
            token = row["token"] if row and row["token"] else ""

            if not token or str(token).strip() in ["", "None"]:
                token = secrets.token_urlsafe(16)
                cur.execute("UPDATE peers SET token=? WHERE peer_name=?", (token, peer_name))
                cur.execute("CREATE TABLE IF NOT EXISTS short_links (short_id TEXT PRIMARY KEY, long_link TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
                cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token, f"/peer-details?peer_name={peer_name}&config_file={clean_cfg}&token={token}"))
                cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token[:8], f"/peer-details?peer_name={peer_name}&config_file={clean_cfg}&token={token}"))
                conn.commit()
        finally:
            conn.close()

    base_url = custom_base_url or get_panel_base_url()
    return f"{base_url.rstrip('/')}/s/{token}"

def send_peer_qr_image_tg(chat_id, peer_name, token=None, custom_base_url=None):
    token = token or get_bot_active_token()
    if not token or not chat_id:
        return
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        r = cur.execute("SELECT config FROM peers WHERE peer_name=?", (peer_name,)).fetchone()
        conn.close()
        cfg_name = r[0] if r and r[0] else "wg0.conf"
        
        # ساخت QR مستقیماً از روی لینک ساب‌اسکریپشن جهت رفع ارور سرریز نسخه QR
        sub_url = get_peer_sublink_url(peer_name, cfg_name, custom_base_url)
        
        import qrcode, io
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2
        )
        qr.add_data(sub_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        
        caption = f"📷 <b>کد QR لینک اشتراک:</b> <code>{peer_name}</code>\n\n🔗 <code>{sub_url}</code>"
        requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": (f"{peer_name}_qr.png", buf.getvalue(), "image/png")},
            timeout=15
        )
    except Exception as e:
        bot_write_log("QR Send Error: " + str(e), "ERROR")
        tg_send_message(chat_id, "❌ خطا در ساخت QR Code: " + str(e), token=token)

def toggle_peer_direct(peer_name, config_file=None):
    conn = get_db_conn()
    cur = conn.cursor()
    
    if config_file:
        clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
        iface = clean_cfg.replace(".conf", "")
        cur.execute("SELECT monitor_blocked, expiry_blocked, peer_ip, public_key, config FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
    else:
        cur.execute("SELECT monitor_blocked, expiry_blocked, peer_ip, public_key, config FROM peers WHERE peer_name=?", (peer_name,))
        
    p_row = cur.fetchone()
    if not p_row:
        conn.close()
        return False, "کاربر یافت نشد"
        
    cfg_target = p_row["config"] or "wg0.conf"
    iface = cfg_target.replace(".conf", "")
    blk = bool(p_row["monitor_blocked"] or p_row["expiry_blocked"])
    new_blk = 0 if blk else 1
    
    cur.execute("UPDATE peers SET monitor_blocked=?, expiry_blocked=? WHERE peer_name=? AND config=?", (new_blk, new_blk, peer_name, cfg_target))
    conn.commit()
    conn.close()
    
    p_ip, pub_k = p_row["peer_ip"], p_row["public_key"]
    if new_blk == 1:
        if p_ip: subprocess.run(f"ip route add blackhole {p_ip}", shell=True, stderr=subprocess.DEVNULL)
        if pub_k: subprocess.run(f"wg set {iface} peer {pub_k} remove", shell=True, stderr=subprocess.DEVNULL)
    else:
        if p_ip: subprocess.run(f"ip route del blackhole {p_ip}", shell=True, stderr=subprocess.DEVNULL)
        if pub_k and p_ip: subprocess.run(f"wg set {iface} peer {pub_k} allowed-ips {p_ip}/32", shell=True, stderr=subprocess.DEVNULL)
        
    subprocess.run(f"wg-quick save {iface}", shell=True, stderr=subprocess.DEVNULL)
    sync_action_to_edges("toggle", peer_name, cfg_target, {"blocked": bool(new_blk)})
    return True, ("غیرفعال 🔴" if new_blk else "فعال 🟢")

def edit_peer_days_direct(peer_name, days_diff, config_file=None):
    conn = get_db_conn()
    cur = conn.cursor()
    
    if config_file:
        clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
        cur.execute("SELECT remaining_time, config FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, clean_cfg.replace(".conf","")))
    else:
        cur.execute("SELECT remaining_time, config FROM peers WHERE peer_name=?", (peer_name,))
        
    p_row = cur.fetchone()
    if not p_row:
        conn.close()
        return False
        
    cfg_target = p_row["config"]
    new_rem = max(0, int(p_row["remaining_time"] or 0) + int(days_diff * 1440))
    cur.execute("UPDATE peers SET remaining_time=?, expiry_blocked=0 WHERE peer_name=? AND config=?", (new_rem, peer_name, cfg_target))
    conn.commit()
    conn.close()
    sync_action_to_edges("edit", peer_name, cfg_target, {"remaining_time": new_rem})
    return True

def edit_peer_volume_direct(peer_name, gb_diff, config_file=None):
    conn = get_db_conn()
    cur = conn.cursor()
    
    if config_file:
        clean_cfg = config_file if str(config_file).endswith(".conf") else str(config_file) + ".conf"
        cur.execute("SELECT [limit], used, config FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, clean_cfg.replace(".conf","")))
    else:
        cur.execute("SELECT [limit], used, config FROM peers WHERE peer_name=?", (peer_name,))
        
    p_row = cur.fetchone()
    if not p_row:
        conn.close()
        return False
        
    cfg_target = p_row["config"]
    _, current_bytes, _ = parse_volume_input_to_wg_limit(str(p_row["limit"] or "1GiB"))
    new_bytes = max(0, current_bytes + int(gb_diff * 1073741824))
    new_lim_str, _, _ = parse_volume_input_to_wg_limit(new_bytes / 1073741824.0)
    
    cur.execute("UPDATE peers SET [limit]=?, monitor_blocked=0 WHERE peer_name=? AND config=?", (new_lim_str, peer_name, cfg_target))
    conn.commit()
    conn.close()
    sync_action_to_edges("edit", peer_name, cfg_target, {"limit": new_lim_str})
    return True
def get_master_flag_and_location():
    master_flag = "🇩🇪"
    try:
        target_ip = get_server_public_ip_cached()
        if target_ip and re.match(r'^\d{1,3}(\.\d{1,3}){3}$', target_ip):
            geo_res = requests.get(f"http://ip-api.com/json/{target_ip}", timeout=3).json()
            country_code = geo_res.get("countryCode", "DE")
            master_flag = "".join(chr(127397 + ord(c)) for c in country_code.upper())
    except Exception:
        master_flag = "🇩🇪"
    return master_flag

def is_strictly_valid_wg_key(key_str):
    if not key_str or not isinstance(key_str, str) or len(key_str.strip()) != 44:
        return False
    try:
        decoded = base64.b64decode(key_str.strip().encode("ascii"))
        return len(decoded) == 32
    except Exception:
        return False

def credit_to_vault_permanently(peer_name, config_file):
    try:
        conn = get_db_conn()
        cur = conn.cursor()
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
    except Exception:
        pass

def auto_heal_and_recover_ghosts_live():
    # 📌 احیای کلاینت‌ها فقط روی مستر فعال باشد
    try:
        from sqlite_backend import get_server_role
        if get_server_role() == "node":
            return
    except Exception:
        pass

    try:
        db_p = get_resolved_db_path()
        wg_dir = "/etc/wireguard"
        if not os.path.exists(wg_dir) or not os.path.exists(db_p):
            return
        
        conn = get_db_conn()
        cur = conn.cursor()
        
        # استخراج تمامی کلیدهای عمومی ثبت‌شده در دیتابیس
        cur.execute("SELECT public_key FROM peers WHERE public_key IS NOT NULL AND public_key != '';")
        known_pubs = set(r[0] for r in cur.fetchall() if r[0])
        
        new_recovered = 0
        for conf_file in os.listdir(wg_dir):
            if not conf_file.endswith('.conf'):
                continue

            # 🚫 نادیده گرفتن فایل‌های تانل پروکسی خارجی (جلوگیری از ساخت کلاینت فیک)
            if conf_file.startswith('tun_') or conf_file.startswith('proxy'):
                continue

            conf_path = os.path.join(wg_dir, conf_file)
            try:
                with open(conf_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            except Exception:
                continue
            
            c_pub, c_ip, c_name, in_p = None, "", "", False
            for line in lines + ["[Peer]"]:
                sl = line.strip()
                if sl.startswith("[") or sl == "[Peer]":
                    if in_p and c_pub and c_pub not in known_pubs:
                        if not c_name:
                            c_name = f"User_{c_ip.split('.')[-1] if '.' in c_ip else secrets.token_hex(2)}"
                        
                        # جلوگیری از نام تکراری
                        cur.execute("SELECT id FROM peers WHERE peer_name = ? AND config = ?", (c_name, conf_file))
                        if cur.fetchone():
                            c_name = f"{c_name}_{secrets.token_hex(2)}"
                        
                        tok = secrets.token_urlsafe(16)

                        # 🎯 اصلاح اساسی: حجم 0GiB یعنی نامحدود (بدون سقف ۵۰ گیگ کاذب)
                        default_limit = "0GiB"
                        
                        cur.execute("""
                            INSERT INTO peers (
                                peer_name, peer_ip, public_key, [limit], used, remaining, remaining_time, 
                                config, token, first_usage, expiry_blocked, monitor_blocked, 
                                created_at, created_at_gregorian, initial_duration
                            )
                            VALUES (?, ?, ?, ?, 0, 0, 43200, ?, ?, 0, 0, 0, ?, datetime('now'), 43200)
                        """, (c_name, c_ip, c_pub, default_limit, conf_file, tok, int(time.time())))
                        
                        cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", 
                                    (tok, f"/peer-details?peer_name={c_name}&config_file={conf_file}&token={tok}"))
                        cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", 
                                    (tok[:8], f"/peer-details?peer_name={c_name}&config_file={conf_file}&token={tok}"))
                        
                        known_pubs.add(c_pub)
                        new_recovered += 1

                    in_p = (sl == "[Peer]")
                    c_pub, c_ip, c_name = None, "", ""
                elif in_p:
                    if sl.startswith("#"):
                        c_name = sl.lstrip("#").strip()
                    elif sl.startswith("PublicKey"):
                        c_pub = sl.split('=', 1)[1].strip()
                    elif sl.startswith("AllowedIPs"):
                        c_ip = sl.split('=', 1)[1].strip().split('/')[0]
        
        # اصلاح توکن‌های خالی قبلی
        cur.execute("SELECT id, peer_name, config FROM peers WHERE token IS NULL OR token = '';")
        for no_tok in cur.fetchall():
            t_gen = secrets.token_urlsafe(16)
            cur.execute("UPDATE peers SET token = ? WHERE id = ?", (t_gen, no_tok["id"]))
            cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", 
                        (t_gen, f"/peer-details?peer_name={no_tok['peer_name']}&config_file={no_tok['config']}&token={t_gen}"))

        if new_recovered > 0:
            conn.commit()
        conn.close()
    except Exception:
        pass

def start_anti_ghost_healer_daemon():
    def healer_loop():
        time.sleep(2)
        while True:
            auto_heal_and_recover_ghosts_live()
            time.sleep(30)
    threading.Thread(target=healer_loop, daemon=True).start()

try:
    start_anti_ghost_healer_daemon()
except Exception:
    pass

# -------------------------------------------------------------------------
# 🔄 همگام‌سازی با سرورهای لبه (Edge Clustering)
# -------------------------------------------------------------------------
def get_edge_authenticated_session(panel_url, username, password):
    norm_url = panel_url.rstrip("/")
    s = _edge_sessions.get(norm_url)
    if not s:
        s = requests.Session()
        s.verify = False
        _edge_sessions[norm_url] = s
    try:
        if s.get(norm_url + "/api/user-info", timeout=4).status_code == 200:
            return s
    except Exception:
        pass
    try:
        if s.post(norm_url + "/api/login", json={"username": username, "password": password}, timeout=6).status_code == 200:
            return s
    except Exception:
        pass
    return s

def find_truly_free_ip_on_edge(session, panel_url, config_file):
    norm_url = panel_url.rstrip("/")
    used_ips = set()
    try:
        r = session.get(norm_url + "/api/peers?config=" + str(config_file) + "&fetch_all=true", timeout=6)
        if r.status_code == 200:
            for p in r.json().get("peers", []):
                ip = p.get("peer_ip")
                if ip:
                    used_ips.add(ip.strip())
    except Exception:
        pass
    base_prefix = "10.0.0"
    try:
        d = session.get(norm_url + "/api/wireguard-details?config=" + str(config_file), timeout=6)
        if d.status_code == 200:
            ip_str = d.json().get("ip", "10.0.0.1")
            m = re.search(r"([0-9]+\.[0-9]+\.[0-9]+)\.", ip_str)
            if m:
                base_prefix = m.group(1)
    except Exception:
        pass
    for oct4 in range(2, 254):
        candidate = base_prefix + "." + str(oct4)
        if candidate not in used_ips:
            return candidate
    return base_prefix + ".2"
def reconcile_db_and_conf_files():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT peer_name, public_key, peer_ip, config, persistent_keepalive, monitor_blocked, expiry_blocked FROM peers WHERE public_key IS NOT NULL AND public_key != ''")
        db_peers = [dict(r) for r in cur.fetchall()]
        conn.close()
        db_peers_by_cfg = {}
        for p in db_peers:
            cfg = p.get("config", "wg0.conf")
            if not str(cfg).endswith(".conf"):
                cfg = str(cfg) + ".conf"
            db_peers_by_cfg.setdefault(cfg, []).append(p)
        wg_dir = "/etc/wireguard"
        if not os.path.exists(wg_dir):
            return
        for f_name in os.listdir(wg_dir):
            if not f_name.endswith(".conf"):
                continue
            f_path = os.path.join(wg_dir, f_name)
            iface = f_name.replace(".conf", "")
            target_db_peers = db_peers_by_cfg.get(f_name, [])
            target_db_pubs = {p["public_key"]: p for p in target_db_peers if p.get("public_key") and is_strictly_valid_wg_key(p.get("public_key"))}
            try:
                with open(f_path, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
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
                for cb in clean_blocks:
                    new_conf_txt += chr(10) + "[Peer]" + chr(10) + cb + chr(10)
                with open(f_path, "w", encoding="utf-8") as f:
                    f.write(new_conf_txt.strip() + chr(10))
            except Exception:
                pass
    except Exception:
        pass

def ensure_edge_table_columns():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS peer_synced_edges (peer_name TEXT, server_ip TEXT, config TEXT, edge_ip TEXT, edge_priv_key TEXT DEFAULT '', edge_pub_key TEXT DEFAULT '', node_used INTEGER DEFAULT 0, last_bytes INTEGER DEFAULT 0, UNIQUE(peer_name, server_ip, config))")
        cur.execute("PRAGMA table_info(peer_synced_edges)")
        cols = [c[1] for c in cur.fetchall()]
        for col_name, col_def in [("node_used", "INTEGER DEFAULT 0"), ("edge_ip", "TEXT DEFAULT ''"), ("edge_priv_key", "TEXT DEFAULT ''"), ("edge_pub_key", "TEXT DEFAULT ''"), ("last_bytes", "INTEGER DEFAULT 0")]:
            if col_name not in cols:
                try:
                    cur.execute("ALTER TABLE peer_synced_edges ADD COLUMN " + col_name + " " + col_def)
                except Exception:
                    pass
        conn.commit()
        conn.close()
    except Exception:
        pass

def convert_to_bytes(limit_val):
    if not limit_val: return 0
    if isinstance(limit_val, (int, float)): return int(limit_val)
    s = str(limit_val).strip().upper()
    m = re.match(r"^([0-9\.]+)\s*(T|TB|TIB|G|GB|GIB|M|MB|MIB|K|KB|KIB|B)?$", s)
    if not m: return 0
    size = float(m.group(1))
    unit = m.group(2) or "GIB"
    mapping = {
        "B": 1, "K": 1024, "KB": 1024, "KIB": 1024,
        "M": 1024**2, "MB": 1024**2, "MIB": 1024**2,
        "G": 1024**3, "GB": 1024**3, "GIB": 1024**3,
        "T": 1024**4, "TB": 1024**4, "TIB": 1024**4
    }
    return int(size * mapping.get(unit, 1024**3))

def run_cluster_traffic_aggregation_pass():
    """
    موتور پایش و تجمیع اتمیک و ضدتداخل ترافیک کلاستر (Master <-> All Edge Nodes + SSH Remote Panel):
    - در سرور Node: ترافیک محلی تمامی کارت‌های شبکه و تانل‌های پروکسی (wg0 + adv* + tun_* + proxy) را به‌صورت زنده محاسبه و در دیتابیس لوکال ثبت می‌کند.
    - در سرور Master: علاوه بر ترافیک محلی، همگام‌سازی کلاستر، احیا و پالایش سخت‌گیرانه wg0 سرور SSH و تجمیع ترافیک را انجام می‌دهد.
    """
    ensure_edge_table_columns()
    
    # ۰. تضمین وجود جدول ردیاب دلتای اینترفیس‌های محلی و پروکسی‌ها
    with _db_lock:
        conn_init = get_db_conn()
        conn_init.execute("""
            CREATE TABLE IF NOT EXISTS peer_interface_traffic (
                interface_name TEXT,
                public_key TEXT,
                last_raw_bytes INTEGER DEFAULT 0,
                PRIMARY KEY (interface_name, public_key)
            );
        """)
        conn_init.commit()
        conn_init.close()

    # ۱. خواندن ترافیک خام کرنل از تمامی اینترفیس‌های WireGuard و پروکسی‌ها (wg0 + adv* + tun_* + proxy)
    local_interface_raw_records = []
    try:
        wg_local_out = subprocess.check_output("wg show all transfer 2>/dev/null", shell=True, universal_newlines=True, stderr=subprocess.DEVNULL)
        for line in wg_local_out.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                if_n = parts[0].strip()
                p_pub = parts[1].strip()
                rx_b = int(parts[2]) if parts[2].isdigit() else 0
                tx_b = int(parts[3]) if parts[3].isdigit() else 0
                local_interface_raw_records.append((if_n, p_pub, rx_b + tx_b))
    except Exception:
        pass

    # ۲. محاسبه دلتای مصرفی و به‌روزرسانی ترافیک در دیتابیس محلی (هم برای Master و هم برای Node)
    try:
        with _db_lock:
            conn = get_db_conn()
            cur = conn.cursor()

            for if_n, p_pub, current_raw in local_interface_raw_records:
                cur.execute(
                    "SELECT last_raw_bytes FROM peer_interface_traffic WHERE interface_name=? AND public_key=?",
                    (if_n, p_pub)
                )
                row_tr = cur.fetchone()
                last_raw = int(row_tr["last_raw_bytes"] or 0) if row_tr else 0

                delta_local = 0
                if last_raw == 0 and current_raw > 0:
                    delta_local = 0  # تثبیت نقطه صفر برای جلوگیری از پرش ناگهانی
                elif current_raw < last_raw:
                    delta_local = current_raw  # ریست یا ریبوت کارت شبکه
                else:
                    delta_local = current_raw - last_raw

                cur.execute("""
                    INSERT INTO peer_interface_traffic (interface_name, public_key, last_raw_bytes)
                    VALUES (?, ?, ?)
                    ON CONFLICT(interface_name, public_key) DO UPDATE SET last_raw_bytes=excluded.last_raw_bytes
                """, (if_n, p_pub, current_raw))

                if delta_local > 0:
                    cur.execute(
                        "UPDATE peers SET used = used + ?, local_used = local_used + ? WHERE public_key=?",
                        (delta_local, delta_local, p_pub)
                    )

            conn.commit()

            # 📌 گارد نود: اگر سرور در نقش Node باشد، بعد از ثبت دقیق ترافیک پروکسی و کارت‌های محلی خارج می‌شود
            try:
                from sqlite_backend import get_server_role
                if get_server_role() == "node":
                    conn.close()
                    return
            except Exception:
                pass

            # =========================================================================
            # ادامه وظایف اختصاصی سرور مستر (Clustering & Advanced SSH Management)
            # =========================================================================
            
            # الف: استخراج تمام اینترفیس‌های فعال
            cur.execute("SELECT interface_name FROM advanced_services WHERE status=1")
            active_adv_ifaces = [r[0] for r in cur.fetchall()]
            all_system_ifaces = set(active_adv_ifaces + ["wg0"])

            # ب: دریافت ترافیک نودهای کلاستر استاندارد (Edge Servers)
            cur.execute("SELECT server_ip, ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
            edges = [dict(r) for r in cur.fetchall()]

            edge_delta_updates = []
            for edge in edges:
                srv_ip = edge.get("server_ip") or ""
                s_ip = edge.get("ssh_ip") or srv_ip
                s_port = edge.get("ssh_port") or 22
                s_user = edge.get("ssh_user") or "root"
                s_pass = edge.get("ssh_pass") or ""

                edge_traffic_map = {}
                if s_ip and s_pass and s_user:
                    try:
                        cmd_ssh = f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=3 {s_user}@{s_ip} 'wg show all transfer 2>/dev/null'"
                        proc = subprocess.run(cmd_ssh, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=5)
                        if proc.returncode == 0 and proc.stdout.strip():
                            for line in proc.stdout.strip().splitlines():
                                parts = line.split()
                                if len(parts) >= 4:
                                    p_pub = parts[1].strip()
                                    rx_b = int(parts[2]) if parts[2].isdigit() else 0
                                    tx_b = int(parts[3]) if parts[3].isdigit() else 0
                                    edge_traffic_map[p_pub] = edge_traffic_map.get(p_pub, 0) + (rx_b + tx_b)
                    except Exception:
                        pass

                if edge_traffic_map:
                    edge_delta_updates.append((srv_ip, s_ip, edge_traffic_map))

            for srv_ip, s_ip, traffic_map in edge_delta_updates:
                for pub, current_raw_edge in traffic_map.items():
                    cur.execute(
                        "SELECT node_used, last_bytes FROM peer_synced_edges WHERE (edge_pub_key = ? OR peer_name IN (SELECT peer_name FROM peers WHERE public_key=?)) AND (server_ip=? OR server_ip=?)",
                        (pub, pub, srv_ip, s_ip)
                    )
                    row_sync = cur.fetchone()
                    if row_sync:
                        old_node_used = int(row_sync["node_used"] or 0)
                        last_raw_edge = int(row_sync["last_bytes"] or 0)

                        delta_edge = 0
                        if last_raw_edge == 0 and current_raw_edge > 0 and old_node_used == 0:
                            delta_edge = 0
                        elif current_raw_edge < last_raw_edge:
                            delta_edge = current_raw_edge
                        else:
                            delta_edge = current_raw_edge - last_raw_edge

                        new_node_used = old_node_used + max(0, delta_edge)
                        cur.execute(
                            "UPDATE peer_synced_edges SET node_used = ?, last_bytes = ? WHERE (edge_pub_key = ? OR peer_name IN (SELECT peer_name FROM peers WHERE public_key=?)) AND (server_ip=? OR server_ip=?)",
                            (new_node_used, current_raw_edge, pub, pub, srv_ip, s_ip)
                        )
                        if delta_edge > 0:
                            cur.execute("UPDATE peers SET used = used + ? WHERE public_key=?", (delta_edge, pub))

# =========================================================================
            # 🌐 هـ: موتور دوره‌ای احیا (با حفظ حجم و زمان)، قطع در انقضا و پالایش wg0 در SSH
            # =========================================================================
            try:
                cur.execute("SELECT * FROM advanced_ssh_settings WHERE mode='ssh' LIMIT 1")
                ssh_setting = cur.fetchone()
                if ssh_setting and ssh_setting["server_ip"] and ssh_setting["server_pass"]:
                    ssh_ip = ssh_setting["server_ip"].strip()
                    ssh_port = int(ssh_setting["server_port"] or 22)
                    ssh_user = ssh_setting["server_user"] or "root"
                    ssh_pass = ssh_setting["server_pass"]

                    # ۱. استخراج کلاینت‌های پیشرفته مجاز مستر (با ترافیک مصرفی و زمان دقیق)
                    cur.execute("""
                        SELECT id, peer_name, peer_ip, public_key, private_key, [limit], used, remaining_time, 
                               first_usage, monitor_blocked, expiry_blocked, token, is_advanced, config 
                        FROM peers 
                        WHERE (is_advanced = 2 OR is_advanced = 1 OR config = 'ssh_remote') 
                          AND public_key IS NOT NULL AND public_key != ''
                    """)
                    master_adv_peers = [dict(r) for r in cur.fetchall()]
                    master_adv_json = json.dumps(master_adv_peers, ensure_ascii=False)

                    # ۲. اسکریپت بومی پایتون جهت اجرا داخل سرور SSH
                    remote_runner_py = f'''# -*- coding: utf-8 -*-
import sqlite3, subprocess, os, json, re

def parse_bytes(val):
    if not val: return 0
    s = str(val).strip().upper()
    m = re.match(r"^([0-9\.]+)\s*(T|TB|TIB|G|GB|GIB|M|MB|MIB|K|KB|KIB|B)?$", s)
    if not m: return 0
    size = float(m.group(1))
    unit = m.group(2) or "GIB"
    mapping = {{"B": 1, "K": 1024, "KB": 1024, "M": 1024**2, "MB": 1024**2, "G": 1024**3, "GB": 1024**3, "T": 1024**4, "TB": 1024**4}}
    return int(size * mapping.get(unit, 1024**3))

master_peers = json.loads({repr(master_adv_json)})
master_names = set(p["peer_name"].strip() for p in master_peers if p.get("peer_name"))
master_by_name = {{p["peer_name"].strip(): p for p in master_peers if p.get("peer_name")}}

db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
conn = sqlite3.connect(db_path, timeout=30.0)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS peers (id INTEGER PRIMARY KEY AUTOINCREMENT, peer_name TEXT, peer_ip TEXT, public_key TEXT UNIQUE, [limit] TEXT, used INTEGER DEFAULT 0, remaining INTEGER DEFAULT 0, config TEXT DEFAULT 'wg0.conf', expiry_time_json TEXT DEFAULT '{{}}', first_usage INTEGER DEFAULT 0, expiry_blocked INTEGER DEFAULT 0, monitor_blocked INTEGER DEFAULT 0, last_received_bytes INTEGER DEFAULT 0, last_sent_bytes INTEGER DEFAULT 0, remaining_time INTEGER DEFAULT 0, private_key TEXT, dns TEXT DEFAULT '1.1.1.1', mtu INTEGER DEFAULT 1280, persistent_keepalive INTEGER DEFAULT 25, allowed_ips TEXT DEFAULT '0.0.0.0/0, ::/0', token TEXT, created_at_gregorian TEXT, created_at_jalali TEXT, first_connected_gregorian TEXT, first_connected_jalali TEXT, local_used INTEGER DEFAULT 0, initial_duration INTEGER DEFAULT 0, created_at INTEGER)")

cur.execute("SELECT peer_name, public_key, peer_ip, used, remaining_time FROM peers WHERE config='wg0.conf' OR config='wg0'")
ssh_peers = [dict(r) for r in cur.fetchall()]
ssh_names = set(p["peer_name"].strip() for p in ssh_peers if p.get("peer_name"))

# ۱. 🧹 حذف خودکار هر کاربری در wg0 سرور SSH که در مستر ثبت نشده باشد
for r_name in (ssh_names - master_names):
    cur.execute("SELECT public_key, peer_ip FROM peers WHERE peer_name=?", (r_name,))
    for pub, ip in cur.fetchall():
        if pub: subprocess.run(f"wg set wg0 peer {{pub}} remove", shell=True, stderr=subprocess.DEVNULL)
        if ip: subprocess.run(f"ip route del blackhole {{ip}}", shell=True, stderr=subprocess.DEVNULL)
    
    cur.execute("DELETE FROM peers WHERE peer_name=?", (r_name,))
    cur.execute("DELETE FROM services WHERE email=?", (r_name,))
    cur.execute("DELETE FROM short_links WHERE long_link LIKE ?", (f"%{{r_name}}%",))

# ۲. 🚀 احیا، تزریق ترافیک/زمان و مدیریت قطع در انقضا برای کلاینت‌ها روی wg0 سرور SSH
for m_name, mp in master_by_name.items():
    pub = mp.get("public_key") or ""
    priv = mp.get("private_key") or ""
    ip = mp.get("peer_ip") or "10.0.0.2"
    lim = mp.get("limit") or "50GiB"
    lim_bytes = parse_bytes(lim)
    m_used = int(mp.get("used") or 0)
    rem_t = int(mp.get("remaining_time") or 43200)
    tok = mp.get("token") or ""
    m_blk = int(mp.get("monitor_blocked") or 0)
    e_blk = int(mp.get("expiry_blocked") or 0)
    
    # 📌 تشخیص وضعیت قطعی مسدودی به خاطر اتمام حجم، زمان یا قطع دستی
    is_blocked = bool(m_blk or e_blk or rem_t <= 0 or (lim_bytes > 0 and m_used >= lim_bytes))

    if m_name not in ssh_names:
        # 🎯 احیا با ترافیک مصرفی دقیق و زمان باقیمانده (عدم ریست شدن)
        cur.execute("""
            INSERT OR REPLACE INTO peers (
                peer_name, peer_ip, public_key, private_key, [limit], used, remaining_time, 
                config, token, first_usage, expiry_blocked, monitor_blocked, dns, mtu, persistent_keepalive, allowed_ips
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'wg0.conf', ?, 0, ?, ?, '1.1.1.1', 1420, 25, '0.0.0.0/0, ::/0')
        """, (m_name, ip, pub, priv, lim, m_used, rem_t, tok, 1 if is_blocked else 0, 1 if is_blocked else 0))
        
        if is_blocked:
            if pub: subprocess.run(f"wg set wg0 peer {{pub}} remove", shell=True, stderr=subprocess.DEVNULL)
            if ip: subprocess.run(f"ip route add blackhole {{ip}}", shell=True, stderr=subprocess.DEVNULL)
        else:
            if pub and ip:
                subprocess.run(f"wg set wg0 peer {{pub}} allowed-ips {{ip}}/32", shell=True, stderr=subprocess.DEVNULL)
                subprocess.run(f"ip route del blackhole {{ip}}", shell=True, stderr=subprocess.DEVNULL)
    else:
        # کلاینت وجود دارد -> به‌روزرسانی زمان، سقف و اعمال قطع دسترسی در صورت اتمام اعتبار
        cur.execute("""
            UPDATE peers SET 
                remaining_time=?, [limit]=?, monitor_blocked=?, expiry_blocked=? 
            WHERE peer_name=?
        """, (rem_t, lim, 1 if is_blocked else 0, 1 if is_blocked else 0, m_name))
        
        if is_blocked:
            # 🔴 قطع قطعی در کرنل نود SSH
            if pub: subprocess.run(f"wg set wg0 peer {{pub}} remove", shell=True, stderr=subprocess.DEVNULL)
            if ip: subprocess.run(f"ip route add blackhole {{ip}}", shell=True, stderr=subprocess.DEVNULL)
        else:
            # 🟢 اتصال مجدد در صورت فعال بودن
            if pub and ip:
                subprocess.run(f"wg set wg0 peer {{pub}} allowed-ips {{ip}}/32", shell=True, stderr=subprocess.DEVNULL)
                subprocess.run(f"ip route del blackhole {{ip}}", shell=True, stderr=subprocess.DEVNULL)

conn.commit()
subprocess.run("wg-quick save wg0 2>/dev/null", shell=True)

# ۳. استخراج مستقیم ترافیک زنده از تمام اینترفیس‌های کرنل نود SSH
wg_transfer_raw = subprocess.getoutput("wg show all transfer 2>/dev/null")
kernel_traffic = {{}}
for line in wg_transfer_raw.splitlines():
    parts = line.split()
    if len(parts) >= 4:
        p_pub, rx, tx = parts[1], int(parts[2]), int(parts[3])
        kernel_traffic[p_pub] = kernel_traffic.get(p_pub, 0) + (rx + tx)
    elif len(parts) == 3:
        p_pub, rx, tx = parts[0], int(parts[1]), int(parts[2])
        kernel_traffic[p_pub] = kernel_traffic.get(p_pub, 0) + (rx + tx)

cur.execute("SELECT peer_name, public_key, used FROM peers WHERE config='wg0.conf' OR config='wg0'")
final_ssh_peers = []
for r in cur.fetchall():
    p_name = r["peer_name"]
    p_pub = r["public_key"]
    db_used = int(r["used"] or 0)
    live_used = max(db_used, kernel_traffic.get(p_pub, 0))
    if live_used > db_used:
        cur.execute("UPDATE peers SET used=? WHERE peer_name=?", (live_used, p_name))
    final_ssh_peers.append({{"peer_name": p_name, "used": live_used}})

conn.commit()
conn.close()

print("[SSH_DIRECT_OUTPUT]" + json.dumps({{"final_peers": final_ssh_peers}}))
'''
                    # ۳. ارسال و اجرای اسکریپت با sshpass
                    enc_script = base64.b64encode(remote_runner_py.encode('utf-8')).decode('utf-8')
                    cmd_ssh = f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no -o ConnectTimeout=6 {ssh_user}@{ssh_ip} \"echo '{enc_script}' | base64 -d > /tmp/ssh_periodic_sync.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/ssh_periodic_sync.py && rm -f /tmp/ssh_periodic_sync.py\""

                    proc_ssh = subprocess.run(cmd_ssh, shell=True, capture_output=True, text=True, timeout=18)
                    if "[SSH_DIRECT_OUTPUT]" in proc_ssh.stdout:
                        out_json_str = proc_ssh.stdout.split("[SSH_DIRECT_OUTPUT]")[1].strip()
                        out_data = json.loads(out_json_str)
                        for fp in out_data.get("final_peers", []):
                            cur.execute(
                                "UPDATE peers SET used=? WHERE peer_name=? AND (is_advanced=2 OR is_advanced=1 OR config='ssh_remote')",
                                (fp["used"], fp["peer_name"])
                            )
            except Exception as ex_ssh:
                bot_write_log(f"SSH Native Periodic Sync Error: {ex_ssh}", "WARNING")

            # د: بررسی اتمام حجم و زمان انقضا برای تمامی کلاینت‌های مستر
            cur.execute("""
                SELECT id, peer_name, config, [limit], used, monitor_blocked, expiry_blocked, 
                       public_key, peer_ip, first_usage, remaining_time, is_advanced 
                FROM peers WHERE public_key IS NOT NULL AND public_key != ''
            """)
            master_peers = [dict(r) for r in cur.fetchall()]

            peers_to_push_to_nodes = []
            for mp in master_peers:
                pid = mp["id"]
                p_name = mp["peer_name"]
                pub = (mp["public_key"] or "").strip()
                cfg_clean = mp["config"] if str(mp["config"]).endswith(".conf") else f"{mp['config']}.conf"
                
                final_total_used = int(mp.get("used") or 0)
                limit_str = mp.get("limit") or "0MiB"
                limit_bytes = convert_to_bytes(limit_str)
                remaining_bytes = max(0, limit_bytes - final_total_used) if limit_bytes > 0 else 0
                rem_time = int(mp.get("remaining_time") or 43200)

                # شروع زمان پس از اولین تبادل داده واقعی
                f_raw = str(mp.get("first_usage", "0")).strip().lower()
                is_first_u = (f_raw in ["1", "true", "yes", "on", "calc_first_conn"])
                if is_first_u and final_total_used > 1024:
                    cur.execute("UPDATE peers SET first_usage=0 WHERE id=?", (pid,))

                # مسدودسازی در صورت اتمام حجم یا زمان
                is_blocked = False
                if (limit_bytes > 0 and final_total_used >= limit_bytes) or rem_time <= 0:
                    is_blocked = True
                    if not mp.get("monitor_blocked"):
                        cur.execute("UPDATE peers SET monitor_blocked=1, expiry_blocked=1 WHERE id=?", (pid,))
                        if mp.get("peer_ip"):
                            subprocess.run(f"ip route add blackhole {mp['peer_ip']}", shell=True, stderr=subprocess.DEVNULL)
                        for cur_iface in all_system_ifaces:
                            if pub:
                                subprocess.run(f"wg set {cur_iface} peer {pub} remove", shell=True, stderr=subprocess.DEVNULL)

                cur.execute("UPDATE peers SET remaining = ? WHERE id = ?", (remaining_bytes, pid))

                if mp.get("is_advanced") != 2 and mp.get("config") != "ssh_remote":
                    peers_to_push_to_nodes.append({
                        "peer_name": p_name,
                        "config": cfg_clean,
                        "limit": limit_str,
                        "used": final_total_used,
                        "remaining": remaining_bytes,
                        "remaining_time": rem_time,
                        "blocked": 1 if (is_blocked or mp.get("expiry_blocked")) else 0
                    })

            conn.commit()
            conn.close()

    except Exception as e:
        bot_write_log(f"Database update error in aggregation: {e}", "ERROR")

    # هـ: پوشِ وضعیت کلاینت‌های استاندارد به سرورهای لبه
    if edges and peers_to_push_to_nodes:
        batch_traffic_json = json.dumps(peers_to_push_to_nodes)
        
        node_push_script = f'''import sqlite3, json, subprocess, os

peers_data = json.loads({repr(batch_traffic_json)})
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

try:
    conn = sqlite3.connect(db_path, timeout=20.0)
    cur = conn.cursor()
    
    for p in peers_data:
        p_name = p.get("peer_name")
        cfg = p.get("config") or "wg0.conf"
        clean_cfg = cfg if cfg.endswith(".conf") else f"{{cfg}}.conf"
        iface = clean_cfg.replace(".conf", "")
        
        used_b = int(p.get("used") or 0)
        rem_b = int(p.get("remaining") or 0)
        lim_str = p.get("limit") or "0GiB"
        rem_time = int(p.get("remaining_time") or 43200)
        is_blk = int(p.get("blocked") or 0)
        
        cur.execute("""
            UPDATE peers SET 
                used=?, remaining=?, [limit]=?, remaining_time=?, 
                monitor_blocked=?, expiry_blocked=?
            WHERE peer_name=? AND (config=? OR config=?)
        """, (used_b, rem_b, lim_str, rem_time, is_blk, is_blk, p_name, clean_cfg, iface))

        if is_blk == 1:
            cur.execute("SELECT public_key, peer_ip FROM peers WHERE peer_name=? AND (config=? OR config=?)", (p_name, clean_cfg, iface))
            r_blk = cur.fetchone()
            if r_blk and r_blk[0]:
                subprocess.run(f"wg set {{iface}} peer {{r_blk[0]}} remove", shell=True, stderr=subprocess.DEVNULL)
                if r_blk[1]: subprocess.run(f"ip route add blackhole {{r_blk[1]}}", shell=True, stderr=subprocess.DEVNULL)
        else:
            cur.execute("SELECT public_key, peer_ip FROM peers WHERE peer_name=? AND (config=? OR config=?)", (p_name, clean_cfg, iface))
            r_act = cur.fetchone()
            if r_act and r_act[0] and r_act[1]:
                subprocess.run(f"wg set {{iface}} peer {{r_act[0]}} allowed-ips {{r_act[1]}}/32", shell=True, stderr=subprocess.DEVNULL)
                subprocess.run(f"ip route del blackhole {{r_act[1]}}", shell=True, stderr=subprocess.DEVNULL)

    conn.commit()
    conn.close()
except Exception:
    pass
'''
        enc = base64.b64encode(node_push_script.encode('utf-8')).decode('utf-8')
        remote_cmd = f"echo '{enc}' | base64 -d > /tmp/push_node_traffic.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/push_node_traffic.py && rm -f /tmp/push_node_traffic.py"

        for edge in edges:
            s_ip = edge.get("ssh_ip") or edge.get("server_ip")
            s_port = edge.get("ssh_port") or 22
            s_user = edge.get("ssh_user") or "root"
            s_pass = edge.get("ssh_pass")

            if s_ip and s_pass and s_user:
                try:
                    subprocess.run(
                        f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=4 {s_user}@{s_ip} \"{remote_cmd}\"",
                        shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=6
                    )
                except Exception:
                    pass

def start_cluster_traffic_aggregator():
    global _aggregator_started
    if _aggregator_started:
        return
    _aggregator_started = True
    def daemon_loop():
        time.sleep(3)
        while True:
            try:
                run_cluster_traffic_aggregation_pass()
            except Exception as e:
                bot_write_log(f"Traffic daemon loop notice: {e}", "WARNING")
            time.sleep(10)
    threading.Thread(target=daemon_loop, daemon=True).start()

start_cluster_traffic_aggregator()
# -------------------------------------------------------------------------
# ⏱️ شمارش معکوس زمان و تاریخ شمسی
# -------------------------------------------------------------------------
def format_precise_duration_fa(total_minutes):
    mins = int(total_minutes or 0)
    if mins <= 0:
        return "۰ دقیقه"
    days = mins // 1440
    hours = (mins % 1440) // 60
    rem_mins = mins % 60
    parts = []
    if days > 0:
        parts.append(str(days) + " روز")
    if hours > 0:
        parts.append(str(hours) + " ساعت")
    if rem_mins > 0 and days == 0:
        parts.append(str(rem_mins) + " دقیقه")
    return " و ".join(parts) if parts else "کمتر از یک دقیقه"

def get_peer_status_icon(peer_dict):
    used_bytes = int(peer_dict.get("used") or 0)
    rem_minutes = int(peer_dict.get("remaining_time") or 0)
    limit_str = str(peer_dict.get("limit") or "0MiB")
    
    limit_bytes = 0.0
    if "GiB" in limit_str:
        limit_bytes = float(limit_str.replace("GiB", "")) * 1073741824.0
    elif "MiB" in limit_str:
        limit_bytes = float(limit_str.replace("MiB", "")) * 1048576.0
        
    is_blocked = bool(peer_dict.get("monitor_blocked") or peer_dict.get("expiry_blocked"))
    f_raw = str(peer_dict.get("first_usage", "0")).strip().lower()
    is_waiting_first_conn = (f_raw in ["1", "true", "yes", "calc_first_conn"])
    has_traffic = (used_bytes > 1024)
    
    if is_blocked or rem_minutes <= 0 or (limit_bytes > 0 and used_bytes >= limit_bytes):
        return "🔴"
    elif is_waiting_first_conn and not has_traffic:
        return "🟡"
    else:
        return "🟢"

def get_interface_network_params(iface_name: str):
    """استخراج شماره اینترفیس و پارامترهای استاندارد شبکه"""
    clean_iface = str(iface_name).replace(".conf", "").strip()
    m_num = re.search(r'\d+', clean_iface)
    num = int(m_num.group(0)) if m_num else 0
    subnet = f"10.{num}.0.1/16"
    port = 51820 + num
    return clean_iface, num, subnet, port

def reconcile_all_resellers_to_nodes():
    # 📌 اگر سرور نود است، فوراً خارج شو
    try:
        from sqlite_backend import get_server_role
        if get_server_role() == "node":
            return
    except Exception:
        pass
    try:
        # ۱. استعلام وضعیت روشن/خاموش بودن wg0 در Master
        out_wg0 = subprocess.run(["ip", "link", "show", "wg0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        master_wg0_active = (out_wg0.returncode == 0 and ("state UP" in out_wg0.stdout or "state UNKNOWN" in out_wg0.stdout))

        with _db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT server_ip, ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
            edges = cur.fetchall()
            if not edges:
                conn.close()
                return

            # استخراج لیست نمایندگان
            cur.execute("""
                SELECT interface_name, username, password_hash, password_plain, data_limit_gb, port, status, disabled_at, deleted_traffic 
                FROM sub_panels
            """)
            master_resellers = [dict(r) for r in cur.fetchall()]

            # 📌 استخراج صندوق ترافیک کل حذف‌شده و صندوق اینترفیس‌ها از Master
            cur.execute("CREATE TABLE IF NOT EXISTS global_deleted_traffic (id INTEGER PRIMARY KEY, total INTEGER DEFAULT 0)")
            row_g = cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1").fetchone()
            master_global_deleted = int(row_g[0] or 0) if row_g else 0

            cur.execute("CREATE TABLE IF NOT EXISTS interface_vault (interface_name TEXT PRIMARY KEY, vault_bytes INTEGER DEFAULT 0)")
            master_vaults = {r[0]: int(r[1] or 0) for r in cur.execute("SELECT interface_name, vault_bytes FROM interface_vault").fetchall()}

            # استخراج ترافیک کل تجمیعی کلاینت‌ها
            cur.execute("SELECT peer_name, config, used, remaining, [limit] FROM peers WHERE public_key IS NOT NULL AND public_key != ''")
            master_peers_traffic = [dict(r) for r in cur.fetchall()]

            conn.close()

        master_resellers_json = json.dumps(master_resellers)
        master_vaults_json = json.dumps(master_vaults)
        master_peers_traffic_json = json.dumps(master_peers_traffic)

        batch_script = f'''import sqlite3, subprocess, os, json, re

master_data = json.loads({repr(master_resellers_json)})
master_vaults = json.loads({repr(master_vaults_json)})
master_peers_traffic = json.loads({repr(master_peers_traffic_json)})
master_global_deleted = {master_global_deleted}

master_ifaces = set(r["interface_name"] for r in master_data)
master_ifaces.add("wg0")
db_p = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

# ۰. تضمین وجود و همگام‌سازی وضعیت دقیق wg0 در Node
wg0_conf_p = "/etc/wireguard/wg0.conf"
if not os.path.exists(wg0_conf_p):
    priv = subprocess.getoutput("wg genkey").strip()
    nic = subprocess.getoutput("ip route | grep default | awk '{{print $5}}' | head -n1").strip() or "eth0"
    c_wg0 = (
        f"[Interface]\\n"
        f"PrivateKey = {{priv}}\\n"
        f"ListenPort = 51820\\n"
        f"Address = 10.0.0.1/16\\n"
        f"SaveConfig = false\\n"
        f"PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o {{nic}} -j MASQUERADE\\n"
        f"PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o {{nic}} -j MASQUERADE\\n"
    )
    with open(wg0_conf_p, "w", encoding="utf-8") as f:
        f.write(c_wg0)

subprocess.run("systemctl daemon-reload", shell=True, stderr=subprocess.DEVNULL)
if {1 if master_wg0_active else 0} == 1:
    subprocess.run("systemctl enable wg-quick@wg0", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run("systemctl start wg-quick@wg0", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run("wg-quick up wg0 2>/dev/null", shell=True)
else:
    subprocess.run("systemctl stop wg-quick@wg0 2>/dev/null", shell=True)
    subprocess.run("wg-quick down wg0 2>/dev/null", shell=True)

if os.path.exists(db_p):
    conn = sqlite3.connect(db_p, timeout=20.0)
    cur = conn.cursor()

    # 📌 همگام‌سازی صندوق ترافیک کل حذف‌شده (global_deleted_traffic) در دیتابیس Node
    cur.execute("CREATE TABLE IF NOT EXISTS global_deleted_traffic (id INTEGER PRIMARY KEY, total INTEGER DEFAULT 0)")
    cur.execute("INSERT OR REPLACE INTO global_deleted_traffic (id, total) VALUES (1, ?)", (master_global_deleted,))

    # 📌 همگام‌سازی صندوق ترافیک اینترفیس‌ها (interface_vault) در دیتابیس Node
    cur.execute("CREATE TABLE IF NOT EXISTS interface_vault (interface_name TEXT PRIMARY KEY, vault_bytes INTEGER DEFAULT 0)")
    for iface_v_name, v_bytes in master_vaults.items():
        cur.execute("INSERT OR REPLACE INTO interface_vault (interface_name, vault_bytes) VALUES (?, ?)", (iface_v_name, v_bytes))

    # 📌 تطبیق ترافیک مصرفی کل کلاینت‌ها در دیتابیس Node
    for p_tr in master_peers_traffic:
        cur.execute(
            "UPDATE peers SET used=?, remaining=? WHERE peer_name=? AND (config=? OR config=?)",
            (p_tr["used"], p_tr["remaining"], p_tr["peer_name"], p_tr["config"], p_tr["config"].replace(".conf",""))
        )

    # پاکسازی اینترفیس‌های معلق (غیر از wg0)
    cur.execute("CREATE TABLE IF NOT EXISTS sub_panels (id INTEGER PRIMARY KEY AUTOINCREMENT, interface_name TEXT UNIQUE, username TEXT UNIQUE, password_hash TEXT, data_limit_gb REAL, port INTEGER, created_at TEXT, status TEXT, disabled_at TEXT, password_plain TEXT, deleted_traffic INTEGER DEFAULT 0)")
    cur.execute("SELECT interface_name FROM sub_panels")
    node_ifaces = set(r[0] for r in cur.fetchall() if r[0])
    
    for stale_iface in (node_ifaces - master_ifaces):
        if stale_iface == "wg0": continue
        subprocess.run(f"wg-quick down {{stale_iface}} 2>/dev/null", shell=True)
        subprocess.run(f"systemctl stop wg-quick@{{stale_iface}} 2>/dev/null", shell=True)
        subprocess.run(f"systemctl disable wg-quick@{{stale_iface}} 2>/dev/null", shell=True)
        if os.path.exists(f"/etc/wireguard/{{stale_iface}}.conf"):
            os.remove(f"/etc/wireguard/{{stale_iface}}.conf")
        cur.execute("DELETE FROM sub_panels WHERE interface_name=?", (stale_iface,))
        cur.execute("DELETE FROM peers WHERE config=? OR config=?", (f"{{stale_iface}}.conf", stale_iface))
    conn.commit()
    conn.close()

# بروزرسانی نمایندگان در Node
for r in master_data:
    iface = r["interface_name"]
    cfg = f"{{iface}}.conf"
    m_num = re.search(r'\\d+', iface)
    num = int(m_num.group(0)) if m_num else 0
    target_subnet = f"10.{{num}}.0.1/16"
    target_port = int(r["port"] or (51820 + num))
    status = r["status"] or "active"
    conf_path = f"/etc/wireguard/{{cfg}}"
    
    needs_restart = False
    if not os.path.exists(conf_path):
        priv = subprocess.getoutput("wg genkey").strip()
        nic = subprocess.getoutput("ip route | grep default | awk '{{print $5}}' | head -n1").strip() or "eth0"
        conf_data = f"[Interface]\\nPrivateKey = {{priv}}\\nListenPort = {{target_port}}\\nAddress = {{target_subnet}}\\nSaveConfig = false\\nPostUp = iptables -A FORWARD -i {{iface}} -j ACCEPT; iptables -t nat -A POSTROUTING -o {{nic}} -j MASQUERADE\\nPostDown = iptables -D FORWARD -i {{iface}} -j ACCEPT; iptables -t nat -D POSTROUTING -o {{nic}} -j MASQUERADE\\n"
        with open(conf_path, "w", encoding="utf-8") as f:
            f.write(conf_data)
        needs_restart = True
    else:
        try:
            with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            m_addr = re.search(r'(?i)Address\\s*=\\s*([^\\n]+)', txt)
            cur_addr = m_addr.group(1).strip() if m_addr else ""
            m_p = re.search(r'(?i)ListenPort\\s*=\\s*(\\d+)', txt)
            cur_p = int(m_p.group(1).strip()) if m_p else 0
            if cur_addr != target_subnet or cur_p != target_port:
                needs_restart = True
                txt = re.sub(r'(?i)Address\\s*=\\s*[^\\n]+', f'Address = {{target_subnet}}', txt)
                txt = re.sub(r'(?i)ListenPort\\s*=\\s*\\d+', f'ListenPort = {{target_port}}', txt)
                with open(conf_path, "w", encoding="utf-8") as f:
                    f.write(txt)
        except Exception:
            pass

    if os.path.exists(db_p):
        conn = sqlite3.connect(db_p, timeout=20.0)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sub_panels (interface_name, username, password_hash, password_plain, data_limit_gb, port, status, disabled_at, deleted_traffic)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(interface_name) DO UPDATE SET
                username=excluded.username,
                password_hash=excluded.password_hash,
                password_plain=excluded.password_plain,
                data_limit_gb=excluded.data_limit_gb,
                port=excluded.port,
                status=excluded.status,
                disabled_at=excluded.disabled_at,
                deleted_traffic=excluded.deleted_traffic
        """, (iface, r["username"], r["password_hash"], r["password_plain"], float(r["data_limit_gb"] or 100), target_port, status, r["disabled_at"], int(r.get("deleted_traffic") or 0)))
        conn.commit()
        conn.close()

    if status == 'active':
        subprocess.run(f"systemctl enable wg-quick@{{iface}}", shell=True, stderr=subprocess.DEVNULL)
        if needs_restart:
            subprocess.run(f"wg-quick down {{iface}} 2>/dev/null", shell=True)
        subprocess.run(f"systemctl start wg-quick@{{iface}}", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run(f"wg-quick up {{iface}} 2>/dev/null", shell=True)
    else:
        subprocess.run(f"systemctl stop wg-quick@{{iface}} 2>/dev/null", shell=True)
        subprocess.run(f"wg-quick down {{iface}} 2>/dev/null", shell=True)
'''
        enc = base64.b64encode(batch_script.encode('utf-8')).decode('utf-8')
        remote_cmd = f"echo '{enc}' | base64 -d > /tmp/reconcile_res.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/reconcile_res.py && rm -f /tmp/reconcile_res.py"

        for _, s_ip, s_port, s_user, s_pass in edges:
            if s_ip and s_pass and s_user:
                subprocess.run(
                    f"sshpass -p '{s_pass}' ssh -p {s_port or 22} -o StrictHostKeyChecking=no -o ConnectTimeout=4 {s_user}@{s_ip} \"{remote_cmd}\"",
                    shell=True, stderr=subprocess.DEVNULL
                )
    except Exception as e:
        bot_write_log(f"Reconcile Resellers Daemon Notice: {e}", "WARNING")

def start_reseller_continuous_sync_daemon():
    """راه‌اندازی ترد پس‌زمینه برای تطبیق مداوم هر ۱۵ ثانیه (فقط روی مستر)"""
    def loop():
        time.sleep(5)
        while True:
            from sqlite_backend import get_server_role
            if get_server_role() == "master":
                reconcile_all_resellers_to_nodes()
            time.sleep(15)
    threading.Thread(target=loop, daemon=True).start()

# اجرای خودکار دیمن با لود شدن ماژول
start_reseller_continuous_sync_daemon()

# ========================================================================= #
# 🔄 همگام‌سازی فوری وضعیت اینترفیس‌ها و نمایندگان بین Master و Node        #
# ========================================================================= #

def sync_reseller_state_to_edges(iface_name: str, action: str = "sync", wait: bool = False):
    """
    همگام‌سازی فوری وضعیت فعال/تعلیق نماینده بین مستر و نودها بدون خطای NameError
    """
    clean_iface, num, target_subnet, target_port = get_interface_network_params(iface_name)
    cfg_name = f"{clean_iface}.conf"

    def do_sync():
        try:
            with _db_lock:
                conn = get_db_conn()
                cur = conn.cursor()
                cur.execute("SELECT server_ip, ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
                edges = cur.fetchall()
                if not edges:
                    conn.close()
                    return

                cur.execute(
                    "SELECT username, password_hash, password_plain, data_limit_gb, port, status, disabled_at, deleted_traffic FROM sub_panels WHERE interface_name=?",
                    (clean_iface,)
                )
                r_row = cur.fetchone()
                conn.close()

            # در صورت حذف کامل نماینده
            if action == "delete" or not r_row:
                delete_script = f'''import sqlite3, subprocess, os
iface = "{clean_iface}"
cfg = "{cfg_name}"
db_p = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

subprocess.run(f"wg-quick down {{iface}} 2>/dev/null", shell=True)
subprocess.run(f"systemctl stop wg-quick@{{iface}} 2>/dev/null", shell=True)
subprocess.run(f"systemctl disable wg-quick@{{iface}} 2>/dev/null", shell=True)
if os.path.exists(f"/etc/wireguard/{{cfg}}"):
    os.remove(f"/etc/wireguard/{{cfg}}")

if os.path.exists(db_p):
    conn = sqlite3.connect(db_p, timeout=20.0)
    cur = conn.cursor()
    cur.execute("DELETE FROM sub_panels WHERE interface_name=?", (iface,))
    cur.execute("DELETE FROM peers WHERE config=? OR config=?", (cfg, iface))
    conn.commit()
    conn.close()
'''
                enc = base64.b64encode(delete_script.encode('utf-8')).decode('utf-8')
                del_cmd = f"echo '{enc}' | base64 -d > /tmp/del_res.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/del_res.py && rm -f /tmp/del_res.py"
                for _, s_ip, s_port, s_user, s_pass in edges:
                    if s_ip and s_pass and s_user:
                        subprocess.run(
                            f"sshpass -p '{s_pass}' ssh -p {s_port or 22} -o StrictHostKeyChecking=no -o ConnectTimeout=5 {s_user}@{s_ip} \"{del_cmd}\"",
                            shell=True, stderr=subprocess.DEVNULL
                        )
                return

            username = r_row["username"] or f"Reseller_{clean_iface}"
            pw_hash = r_row["password_hash"] or ""
            pw_plain = r_row["password_plain"] or ""
            limit_gb = float(r_row["data_limit_gb"] or 100.0)
            status = r_row["status"] or "active"
            disabled_at = r_row["disabled_at"]
            del_traffic = int(r_row["deleted_traffic"] or 0)
            actual_port = int(r_row["port"] or target_port)

            reseller_sync_script = f'''import sqlite3, subprocess, os

iface = "{clean_iface}"
cfg = "{cfg_name}"
username = "{username}"
pw_hash = "{pw_hash}"
pw_plain = "{pw_plain}"
limit_gb = {limit_gb}
port = {actual_port}
status = "{status}"
disabled_at = {repr(disabled_at)}
del_traffic = {del_traffic}
db_p = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"

if os.path.exists(db_p):
    conn = sqlite3.connect(db_p, timeout=20.0)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sub_panels (interface_name, username, password_hash, password_plain, data_limit_gb, port, status, disabled_at, deleted_traffic)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(interface_name) DO UPDATE SET
            username=excluded.username,
            password_hash=excluded.password_hash,
            password_plain=excluded.password_plain,
            data_limit_gb=excluded.data_limit_gb,
            port=excluded.port,
            status=excluded.status,
            disabled_at=excluded.disabled_at,
            deleted_traffic=excluded.deleted_traffic
    """, (iface, username, pw_hash, pw_plain, limit_gb, port, status, disabled_at, del_traffic))
    conn.commit()
    conn.close()

# قطع یا وصل فوری و بدون خطای کارت شبکه در نود
subprocess.run("systemctl daemon-reload", shell=True, stderr=subprocess.DEVNULL)
if status == 'active':
    subprocess.run(f"systemctl enable wg-quick@{{iface}}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"wg-quick down {{iface}} 2>/dev/null", shell=True)
    subprocess.run(f"systemctl restart wg-quick@{{iface}}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"wg-quick up {{iface}} 2>/dev/null", shell=True)
else:
    subprocess.run(f"systemctl stop wg-quick@{{iface}} 2>/dev/null", shell=True)
    subprocess.run(f"wg-quick down {{iface}} 2>/dev/null", shell=True)
'''
            enc = base64.b64encode(reseller_sync_script.encode('utf-8')).decode('utf-8')
            remote_cmd = f"echo '{enc}' | base64 -d > /tmp/sync_res.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_res.py && rm -f /tmp/sync_res.py"

            for _, s_ip, s_port, s_user, s_pass in edges:
                if s_ip and s_pass and s_user:
                    try:
                        ensure_edge_interface(s_ip, s_port, s_user, s_pass, cfg_name)
                    except Exception:
                        pass
                    subprocess.run(
                        f"sshpass -p '{s_pass}' ssh -p {s_port or 22} -o StrictHostKeyChecking=no -o ConnectTimeout=5 {s_user}@{s_ip} \"{remote_cmd}\"",
                        shell=True, stderr=subprocess.DEVNULL
                    )

        except Exception as e:
            bot_write_log(f"Error in sync_reseller_state_to_edges: {e}", "ERROR")

    if wait:
        do_sync()
    else:
        threading.Thread(target=do_sync, daemon=True).start()


def sync_interface_state_to_edges(iface_name: str, is_active: bool, wait: bool = False):
    """
    همگام‌سازی فوری وضعیت فعال/غیرفعال بودن هر اینترفیس (به‌ویژه wg0) از Master به Nodeها:
    - wg0 را همیشه در Node حفظ کرده و هرگز اجازه حذف آن را نمی‌دهد.
    - در صورت روشن شدن در Master -> در Node نیز ابتدا down و سپس up می‌شود تا خطای File exists ندهد.
    - در صورت خاموش شدن در Master -> در Node نیز خاموش (wg-quick down) می‌شود.
    """
    clean_iface = str(iface_name).replace(".conf", "").strip()

    def do_sync():
        try:
            with _db_lock:
                conn = get_db_conn()
                cur = conn.cursor()
                cur.execute("SELECT server_ip, ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
                edges = cur.fetchall()
                conn.close()

            if not edges:
                return

            status_script = f'''import subprocess, os

iface = "{clean_iface}"
cfg_path = f"/etc/wireguard/{{iface}}.conf"

# 📌 تضمین قطعی وجود همیشگی wg0 در Node
if iface == "wg0" and not os.path.exists(cfg_path):
    priv = subprocess.getoutput("wg genkey").strip()
    nic = subprocess.getoutput("ip route | grep default | awk '{{print $5}}' | head -n1").strip() or "eth0"
    conf_data = (
        f"[Interface]\\n"
        f"PrivateKey = {{priv}}\\n"
        f"ListenPort = 51820\\n"
        f"Address = 10.0.0.1/16\\n"
        f"SaveConfig = false\\n"
        f"PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o {{nic}} -j MASQUERADE\\n"
        f"PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o {{nic}} -j MASQUERADE\\n"
    )
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(conf_data)

# اعمال وضعیت فعال / غیرفعال به صورت ضدخطا
subprocess.run("systemctl daemon-reload", shell=True, stderr=subprocess.DEVNULL)
if {1 if is_active else 0} == 1:
    subprocess.run(f"systemctl enable wg-quick@{{iface}}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"wg-quick down {{iface}} 2>/dev/null", shell=True)
    subprocess.run(f"systemctl restart wg-quick@{{iface}}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"wg-quick up {{iface}} 2>/dev/null", shell=True)
else:
    subprocess.run(f"systemctl stop wg-quick@{{iface}} 2>/dev/null", shell=True)
    subprocess.run(f"wg-quick down {{iface}} 2>/dev/null", shell=True)

print("SUCCESS_IFACE_TOGGLE")
'''
            enc = base64.b64encode(status_script.encode('utf-8')).decode('utf-8')
            remote_cmd = f"echo '{enc}' | base64 -d > /tmp/toggle_iface.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/toggle_iface.py && rm -f /tmp/toggle_iface.py"

            for _, s_ip, s_port, s_user, s_pass in edges:
                if s_ip and s_pass and s_user:
                    subprocess.run(
                        f"sshpass -p '{s_pass}' ssh -p {s_port or 22} -o StrictHostKeyChecking=no -o ConnectTimeout=4 {s_user}@{s_ip} \"{remote_cmd}\"",
                        shell=True, stderr=subprocess.DEVNULL
                    )
        except Exception as e:
            bot_write_log(f"Error syncing interface state for {clean_iface}: {e}", "ERROR")

    if wait:
        do_sync()
    else:
        threading.Thread(target=do_sync, daemon=True).start()

def find_truly_free_ip_on_edge_v16(session, panel_url, config_file):
    """
    پیدا کردن آی‌پی آزاد در نود بر اساس فضای ساب‌نت 10.N.0.1/16 (بیش از ۶۵ هزار آی‌پی)
    """
    clean_iface, num, target_subnet, _ = get_interface_network_params(config_file)
    base_prefix = f"10.{num}"
    used_ips = set()

    norm_url = panel_url.rstrip("/")
    try:
        r = session.get(f"{norm_url}/api/peers?config={clean_iface}.conf&fetch_all=true", timeout=5)
        if r.status_code == 200:
            for p in r.json().get("peers", []):
                ip = p.get("peer_ip")
                if ip:
                    used_ips.add(ip.strip())
    except Exception:
        pass

    # جستجوی آی‌پی آزاد در کل ساب‌نت /16 (10.N.0.2 تا 10.N.254.254)
    for oct3 in range(0, 255):
        for oct4 in range(2, 255):
            candidate = f"{base_prefix}.{oct3}.{oct4}"
            if candidate not in used_ips and candidate != f"{base_prefix}.0.1":
                return candidate

    return f"{base_prefix}.0.2"


def sync_action_to_edges(action, peer_name, config_file="wg0.conf", extra_data=None, wait=False):
    """
    موتور همگام‌ساز اتمیک، سریع و ایمن تمام تغییرات کلاینت با نودها و سرور SSH پیشرفته
    - دارای گارد ضد لوپ در سطح نودها
    - ارسال ایزوله کلاینت‌های پیشرفته به wg0 سرور SSH
    - هدرهای ضد تایم‌اوت سوکت
    """
    # 📌 ۱. گارد ضد لوپ: اگر این سرور نود/فرزند باشد، هرگز سینک به عقب انجام نمی‌دهد
    try:
        from sqlite_backend import get_server_role
        if get_server_role() == "node":
            return
    except Exception:
        pass

    clean_iface, num, target_subnet, target_port = get_interface_network_params(config_file)
    clean_cfg = f"{clean_iface}.conf"

    with _sync_lock:
        now_time = time.time()
        sync_key = f"{action}_{peer_name}_{clean_cfg}"
        if sync_key in _last_sync_times and (now_time - _last_sync_times[sync_key]) < 0.4:
            return
        _last_sync_times[sync_key] = now_time

    def do_sync():
        time.sleep(0.05)
        try:
            edges = []
            ssh_active_row = None
            is_peer_ssh_remote = False

            with _db_lock:
                conn = get_db_conn()
                cur = conn.cursor()
                
                # استخراج نودهای معمولی کلاستر
                cur.execute("SELECT panel_url, panel_user, panel_pass, server_ip, ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
                edges = [dict(r) for r in cur.fetchall()]

                # استخراج اطلاعات پنل SSH ریموت
                try:
                    cur.execute("SELECT * FROM advanced_ssh_settings WHERE mode='ssh' LIMIT 1")
                    r_ssh = cur.fetchone()
                    if r_ssh:
                        ssh_active_row = dict(r_ssh)
                except Exception:
                    pass

                # استخراج اطلاعات کامل کلاینت از مستر
                cur.execute(
                    "SELECT [limit], used, remaining_time, private_key, public_key, peer_ip, dns, mtu, persistent_keepalive, allowed_ips, monitor_blocked, expiry_blocked, first_usage, is_advanced, config, token "
                    "FROM peers WHERE peer_name=? AND (config=? OR config=? OR config='ssh_remote')", 
                    (peer_name, clean_cfg, clean_iface)
                )
                peer_row = cur.fetchone()
                
                limit, used, rem_time, priv, pub, master_ip, dns, mtu, keepalive, allowed_ips, m_blk, e_blk, is_first_u_val, tok = (
                    "1GiB", 0, 1440, "", "", f"10.{num}.0.2", "1.1.1.1", 1420, 25, "0.0.0.0/0, ::/0", 0, 0, 0, secrets.token_urlsafe(16)
                )

                if peer_row:
                    pd = dict(peer_row)
                    limit = pd.get("limit") or "1GiB"
                    used = pd.get("used") or 0
                    rem_time = pd.get("remaining_time") or 1440
                    priv = pd.get("private_key") or ""
                    pub = pd.get("public_key") or ""
                    master_ip = pd.get("peer_ip") or f"10.{num}.0.2"
                    dns = pd.get("dns") or "1.1.1.1"
                    mtu = pd.get("mtu") or 1420
                    keepalive = pd.get("persistent_keepalive") or 25
                    allowed_ips = pd.get("allowed_ips") or "0.0.0.0/0, ::/0"
                    m_blk = pd.get("monitor_blocked") or 0
                    e_blk = pd.get("expiry_blocked") or 0
                    is_peer_ssh_remote = (int(pd.get("is_advanced") or 0) in [1, 2] or pd.get("config") == "ssh_remote")
                    tok = pd.get("token") or secrets.token_urlsafe(16)
                    
                    f_raw = str(pd.get("first_usage", "0")).strip().lower()
                    is_first_u_val = 1 if (f_raw in ["1", "true", "yes", "on", "calc_first_conn"]) else 0

                if extra_data and isinstance(extra_data, dict):
                    if extra_data.get("limit"): limit = extra_data["limit"]
                    if extra_data.get("remaining_time") is not None: rem_time = int(extra_data["remaining_time"])
                    if extra_data.get("used") is not None: used = int(extra_data["used"])
                    if extra_data.get("private_key"): priv = extra_data["private_key"]
                    if extra_data.get("public_key"): pub = extra_data["public_key"]
                    if extra_data.get("peer_ip"): master_ip = extra_data["peer_ip"]
                    if extra_data.get("token"): tok = extra_data["token"]
                    if "first_usage" in extra_data:
                        is_first_u_val = 1 if bool(extra_data["first_usage"]) else 0
                    if "blocked" in extra_data:
                        m_blk = 1 if extra_data["blocked"] else 0
                        e_blk = 1 if extra_data["blocked"] else 0

                is_blocked = bool(m_blk or e_blk)
                expiry_days = max(1, int(rem_time // 1440))
                is_first_u_bool = bool(is_first_u_val == 1)

                conn.close()

            # =========================================================================
            # 🌐 ۱. همگام‌سازی مستقیم و ایزوله با wg0 سرور SSH پیشرفته
            # =========================================================================
            if ssh_active_row and ssh_active_row.get("panel_url") and is_peer_ssh_remote:
                try:
                    rem_p_url = ssh_active_row["panel_url"].rstrip("/")
                    p_user = ssh_active_row["panel_user"]
                    p_pass = ssh_active_row["panel_pass"]

                    s_act = requests.Session()
                    s_act.verify = False
                    s_act.headers.update({"Accept-Encoding": "identity", "User-Agent": "MasterActionSync/1.0"})
                    
                    # لاگین به پنل ریموت SSH
                    if s_act.post(f"{rem_p_url}/api/login", json={"username": p_user, "password": p_pass}, timeout=5).status_code == 200:
                        target_remote_cfg = "wg0.conf"

                        if action == "delete":
                            s_act.post(
                                f"{rem_p_url}/api/delete-peer", 
                                json={"peerName": peer_name, "configFile": target_remote_cfg, "admin_user": p_user, "admin_pass": p_pass}, 
                                timeout=6
                            )
                        elif action == "toggle":
                            s_act.post(
                                f"{rem_p_url}/api/toggle-peer", 
                                json={"peerName": peer_name, "blocked": is_blocked, "config": target_remote_cfg, "admin_user": p_user, "admin_pass": p_pass}, 
                                timeout=6
                            )
                        elif action == "reset":
                            s_act.post(
                                f"{rem_p_url}/api/reset-traffic", 
                                json={"peerName": peer_name, "config": target_remote_cfg, "admin_user": p_user, "admin_pass": p_pass}, 
                                timeout=6
                            )
                            s_act.post(
                                f"{rem_p_url}/api/reset-expiry", 
                                json={"peerName": peer_name, "config": target_remote_cfg, "admin_user": p_user, "admin_pass": p_pass}, 
                                timeout=6
                            )
                        elif action == "edit":
                            s_act.post(
                                f"{rem_p_url}/api/edit-peer", 
                                json={"peerName": peer_name, "configFile": target_remote_cfg, "dataLimit": limit, "dns": dns, "expiryDays": expiry_days, "admin_user": p_user, "admin_pass": p_pass}, 
                                timeout=6
                            )
                        elif action == "create":
                            create_payload_ssh = {
                                "admin_user": p_user,
                                "admin_pass": p_pass,
                                "peerName": peer_name,
                                "dataLimit": limit,
                                "expiryDays": expiry_days,
                                "firstUsage": is_first_u_bool,
                                "private_key": priv,
                                "public_key": pub,
                                "token": tok,
                                "configFile": target_remote_cfg
                            }
                            res_c = s_act.post(f"{rem_p_url}/api/create-advanced-peer", json=create_payload_ssh, timeout=7)
                            if res_c.status_code != 200:
                                s_act.post(f"{rem_p_url}/api/create-peer", json=create_payload_ssh, timeout=7)
                except Exception as ex_ssh_sync:
                    bot_write_log(f"SSH Panel Action Sync Error ({action} - {peer_name}): {ex_ssh_sync}", "WARNING")

            # =========================================================================
            # 🛰 ۲. همگام‌سازی کلاینت‌های معمولی با سرورهای لبه (Edge Nodes)
            # =========================================================================
            if not edges or is_peer_ssh_remote:
                return

            for edge in edges:
                panel_url = edge.get("panel_url")
                panel_user = edge.get("panel_user")
                panel_pass = edge.get("panel_pass")
                srv_ip = edge.get("server_ip")
                s_ip = edge.get("ssh_ip") or srv_ip
                s_port = edge.get("ssh_port") or 22
                s_user = edge.get("ssh_user") or "root"
                s_pass = edge.get("ssh_pass")

                if not panel_url or not panel_user or not panel_pass:
                    continue
                
                norm_url = panel_url.rstrip("/")
                session = get_edge_authenticated_session(panel_url, panel_user, panel_pass)

                # اطمینان از وجود اینترفیس روی نود
                if s_ip and s_pass and s_user:
                    try:
                        ensure_edge_interface(s_ip, s_port, s_user, s_pass, clean_cfg)
                    except Exception:
                        pass

                if action == "delete":
                    try:
                        session.post(f"{norm_url}/api/delete-peer", json={"peerName": peer_name, "configFile": clean_cfg}, timeout=8)
                    except Exception:
                        pass
                    with _db_lock:
                        conn_del = get_db_conn()
                        conn_del.execute("DELETE FROM peer_synced_edges WHERE peer_name=? AND config=?", (peer_name, clean_cfg))
                        conn_del.commit()
                        conn_del.close()

                elif action == "create":
                    try:
                        session.post(f"{norm_url}/api/delete-peer", json={"peerName": peer_name, "configFile": clean_cfg}, timeout=4)
                    except Exception:
                        pass

                    edge_ip = find_truly_free_ip_on_edge_v16(session, norm_url, clean_cfg)
                    
                    create_payload = {
                        "peerName": peer_name,
                        "peerIp": edge_ip,
                        "dataLimit": limit,
                        "configFile": clean_cfg,
                        "dns": dns,
                        "expiryDays": expiry_days,
                        "firstUsage": is_first_u_bool,
                        "first_usage": is_first_u_bool,
                        "mtu": mtu,
                        "persistentKeepalive": keepalive,
                        "allowedIps": allowed_ips,
                        "private_key": priv,
                        "public_key": pub
                    }
                    try:
                        res = session.post(f"{norm_url}/api/create-peer", json=create_payload, timeout=10)
                        if res.status_code == 200:
                            with _db_lock:
                                conn_ins = get_db_conn()
                                conn_ins.execute(
                                    "INSERT OR REPLACE INTO peer_synced_edges (peer_name, server_ip, config, edge_ip, edge_priv_key, edge_pub_key, node_used, last_bytes) "
                                    "VALUES (?, ?, ?, ?, ?, ?, 0, 0)", 
                                    (peer_name, srv_ip, clean_cfg, edge_ip, priv, pub)
                                )
                                conn_ins.commit()
                                conn_ins.close()
                    except Exception as ex_cr:
                        bot_write_log(f"Edge create error ({srv_ip}): {ex_cr}", "ERROR")

                elif action == "edit":
                    try:
                        session.post(f"{norm_url}/api/edit-peer", json={"peerName": peer_name, "configFile": clean_cfg, "dataLimit": limit, "dns": dns, "expiryDays": expiry_days}, timeout=8)
                    except Exception:
                        pass

                elif action == "toggle":
                    try:
                        session.post(f"{norm_url}/api/toggle-peer", json={"peerName": peer_name, "blocked": is_blocked, "config": clean_cfg}, timeout=8)
                    except Exception:
                        pass

                elif action == "reset":
                    try:
                        session.post(f"{norm_url}/api/reset-traffic", json={"peerName": peer_name, "config": clean_cfg}, timeout=6)
                        session.post(f"{norm_url}/api/reset-expiry", json={"peerName": peer_name, "config": clean_cfg}, timeout=6)
                        with _db_lock:
                            conn_rst = get_db_conn()
                            conn_rst.execute("UPDATE peer_synced_edges SET node_used=0, last_bytes=0 WHERE peer_name=? AND config=?", (peer_name, clean_cfg))
                            conn_rst.execute("UPDATE peers SET local_used=0, used=0 WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, clean_iface))
                            conn_rst.commit()
                            conn_rst.close()
                    except Exception:
                        pass

        except Exception as ex_global:
            bot_write_log(f"Global sync_action_to_edges error: {ex_global}", "ERROR")

    if wait:
        do_sync()
    else:
        threading.Thread(target=do_sync, daemon=True).start()

# =========================================================================
# 🔗 توابع تولید لینک استاندارد و تشخیص هوشمند نوع درخواست
# =========================================================================
def generate_wireguard_uri(private_key, server_pub_key, endpoint_host, endpoint_port, peer_ip, dns="1.1.1.1, 8.8.8.8", mtu=1280, allowed_ips="0.0.0.0/0, ::/0", tag_name="WireGuard"):
    """تولید URI استاندارد wireguard:// سازگار با V2Box, Happ, Sing-box, NekoBox"""
    clean_ip = str(peer_ip).strip()
    if "/" not in clean_ip:
        clean_ip = f"{clean_ip}/32"

    enc_priv = urllib.parse.quote(str(private_key).strip(), safe='')
    enc_pub = urllib.parse.quote(str(server_pub_key).strip(), safe='')
    enc_addr = urllib.parse.quote(clean_ip, safe='')
    enc_allowed = urllib.parse.quote(str(allowed_ips).strip(), safe='')
    enc_dns = urllib.parse.quote(str(dns).strip(), safe='')
    enc_tag = urllib.parse.quote(str(tag_name).strip(), safe='')

    return (
        f"wireguard://{enc_priv}@{endpoint_host.strip()}:{endpoint_port}/"
        f"?publickey={enc_pub}&address={enc_addr}&mtu={mtu}&allowedips={enc_allowed}&dns={enc_dns}#{enc_tag}"
    )

def is_vpn_client_request(req):
    """تشخیص اینکه آیا درخواست از طرف نرم‌افزار VPN/آنالایزر است یا مرورگر وب"""
    ua = req.headers.get("User-Agent", "").lower()
    accept = req.headers.get("Accept", "").lower()
    
    # پارامترهای اجباری تست در آدرس
    if req.args.get("format") in ["raw", "base64", "sub", "uri"] or req.args.get("sub") == "1":
        return True

    # امضای نرم‌افزارهای VPN
    vpn_agents = [
        "v2box", "happ", "sing-box", "v2ray", "v2rayng", "clash", "nekobox", 
        "streisand", "shadowrocket", "quantumult", "surfboard", "loon", 
        "wireguard", "curl", "wget", "go-http-client", "okhttp", "dart", "postman", "analyzer"
    ]
    
    if any(agent in ua for agent in vpn_agents):
        return True

    # اگر کاربر مرورگر معمولی نیست و درخواست text/plain یا */* دارد
    if "text/html" not in accept and ("*/*" in accept or "text/plain" in accept):
        if not any(b in ua for b in ["mozilla", "chrome", "safari", "edge", "firefox", "opera"]):
            return True

    return False
def universal_sublink_renderer(short_id):
    short_id = str(short_id).strip()
    peer_name = None
    config_file = "wg0.conf"
    conn = get_db_conn()
    cur = conn.cursor()

    # ۱. استعلام لینک بلند از جدول short_links
    try:
        cur.execute("SELECT long_link FROM short_links WHERE short_id = ?", (short_id,))
        row = cur.fetchone()
        if row and row["long_link"]:
            long_link = row["long_link"]
            p_m = re.search(r"peer_name=([^&]+)", long_link) or re.search(r"peerName=([^&]+)", long_link)
            c_m = re.search(r"config_file=([^&]+)", long_link) or re.search(r"configFile=([^&]+)", long_link) or re.search(r"config=([^&]+)", long_link)
            if p_m: peer_name = urllib.parse.unquote(p_m.group(1))
            if c_m: config_file = urllib.parse.unquote(c_m.group(1))
    except Exception:
        pass

    # ۲. در صورت نیافتن، جستجوی مستقیم در جدول peers با توکن یا نام کلاینت
    if not peer_name:
        try:
            cur.execute(
                "SELECT peer_name, config, token FROM peers WHERE token = ? OR token LIKE ? OR ? LIKE (token || '%') OR peer_name = ?", 
                (short_id, f"{short_id}%", short_id, short_id)
            )
            p_row = cur.fetchone()
            if p_row:
                peer_name = p_row["peer_name"]
                config_file = p_row["config"]
        except Exception:
            pass

    clean_cfg = config_file if str(config_file).endswith(".conf") else f"{config_file}.conf"
    iface = clean_cfg.replace(".conf", "")
    peer_row = None

    if peer_name:
        try:
            cur.execute("SELECT * FROM peers WHERE peer_name = ? AND (config = ? OR config = ?)", (peer_name, clean_cfg, iface))
            peer_row = cur.fetchone()
            if not peer_row:
                cur.execute("SELECT * FROM peers WHERE peer_name = ?", (peer_name,))
                peer_row = cur.fetchone()
        except Exception:
            pass

    # ۳. در صورت نبودن کاربر در دیتابیس (منقضی و پاک‌شده)
    if not peer_row:
        conn.close()
        display_name = peer_name or short_id
        if is_vpn_client_request(request):
            return Response("Subscription Expired or Not Found", status=404, mimetype="text/plain; charset=utf-8")

        rendered = render_template(
            "status.html",
            peer_name=display_name,
            used_percent=100.0,
            time_percent=100.0,
            limit_str="۰ گیگابایت",
            used_str_fa="اشتراک حذف شده",
            rem_minutes=0,
            time_str_fa="منقضی و حذف شده",
            total_days="پایان اشتراک",
            location_html="<span class='flag-item'>🚫</span>",
            download_configs=[],
            short_id=short_id,
            status_text="<span style='display:flex; align-items:center; gap:5px;'><i class='fas fa-times-circle' style='color:#ff4757; font-size:16px;'></i> اشتراک شما پایان یافته و حذف شده است</span>",
            status_class="st-offline",
            cache_buster=int(time.time())
        )
        resp = make_response(rendered)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    p_dict = dict(peer_row)
    is_ssh_remote = (int(p_dict.get("is_advanced") or 0) == 2 or str(p_dict.get("config")) == "ssh_remote")

    # استخراج مقادیر ترافیک و زمان برای هدر اشتراک
    limit_str = str(p_dict.get("limit") or "50GiB")
    used_bytes = int(p_dict.get("used") or 0)
    rem_minutes = int(p_dict.get("remaining_time") or 0)
    init_duration = int(p_dict.get("initial_duration") or 0)
    expiry_json_str = str(p_dict.get("expiry_time_json") or "")

    limit_bytes = convert_to_bytes(limit_str)
    expire_ts = int(time.time()) + (rem_minutes * 60) if rem_minutes > 0 else int(time.time())

    # استخراج لینک پشتیبانی و متن اعلان سرور از master_settings
    support_url = ""
    announcement_text = ""
    try:
        cur.execute("PRAGMA table_info(master_settings)")
        cols = [c[1] for c in cur.fetchall()]
        if "support_url" in cols and "announcement_text" in cols:
            row_s = cur.execute("SELECT support_url, announcement_text FROM master_settings LIMIT 1").fetchone()
            if row_s:
                support_url = (row_s["support_url"] or "").strip()
                announcement_text = (row_s["announcement_text"] or "").strip()
    except Exception:
        pass

    # =========================================================================
    # 🔵 ۴. سناریوی کلاینت پیشرفته ساخته‌شده در پنل SSH ریموت (is_advanced == 2)
    # =========================================================================
    if is_ssh_remote:
        cur.execute("SELECT * FROM advanced_ssh_settings LIMIT 1")
        ssh_cfg = cur.fetchone()
        if ssh_cfg and ssh_cfg["panel_url"]:
            remote_panel_url = ssh_cfg["panel_url"].rstrip("/")
            tok = p_dict.get("token") or short_id

            # الف) اگر درخواست از اپلیکیشن VPN باشد (V2Box / Happ / Sing-box)
            if is_vpn_client_request(request):
                try:
                    s_r = requests.Session()
                    s_r.verify = False
                    r_sub = s_r.get(f"{remote_panel_url}/s/{tok}?format=raw", timeout=6, headers={"User-Agent": "V2Box"})
                    if r_sub.status_code != 200 or not r_sub.text.strip():
                        r_sub = s_r.get(f"{remote_panel_url}/s/{peer_name}?format=raw", timeout=6, headers={"User-Agent": "V2Box"})
                    
                    if r_sub.status_code == 200 and r_sub.text.strip():
                        conn.close()
                        resp = Response(r_sub.text.strip(), mimetype="text/plain; charset=utf-8")
                        resp.headers["Content-Disposition"] = f'attachment; filename="{peer_name}"'
                        resp.headers["profile-update-interval"] = "12"
                        resp.headers["profile-title"] = f"base64:{base64.b64encode(peer_name.encode('utf-8')).decode('utf-8')}"
                        resp.headers["subscription-userinfo"] = f"upload=0; download={used_bytes}; total={limit_bytes}; expire={expire_ts}"
                        resp.headers["profile-web-page-url"] = f"{request.host_url.rstrip('/')}/s/{short_id}"
                        
                        if support_url:
                            resp.headers["support-url"] = support_url
                        if announcement_text:
                            resp.headers["announce"] = f"base64:{base64.b64encode(announcement_text.encode('utf-8')).decode('utf-8')}"

                        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                        return resp
                except Exception:
                    pass

            # ب) دریافت مستقیم و پروکسی صفحه ساب‌لینک از سرور SSH برای مرورگر (با شرط اصلاح‌شده)
            try:
                s_r = requests.Session()
                s_r.verify = False
                remote_sub_resp = s_r.get(
                    f"{remote_panel_url}/s/{tok}", 
                    timeout=6, 
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                if remote_sub_resp.status_code != 200 or "اشتراک شما پایان یافته" in remote_sub_resp.text:
                    remote_sub_resp = s_r.get(
                        f"{remote_panel_url}/s/{peer_name}", 
                        timeout=6, 
                        headers={"User-Agent": "Mozilla/5.0"}
                    )

                if remote_sub_resp.status_code == 200 and ("<html" in remote_sub_resp.text.lower() or "<!doctype" in remote_sub_resp.text.lower()) and "اشتراک شما پایان یافته" not in remote_sub_resp.text:
                    conn.close()
                    resp = make_response(remote_sub_resp.text)
                    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                    return resp
            except Exception:
                pass

            # ج) فال‌بک ۱۰۰٪ پایدار: لاگین به پنل SSH و ساخت لیست کانفیگ‌ها بر اساس سرور ریموت
            try:
                s_r = requests.Session()
                s_r.verify = False
                s_r.post(f"{remote_panel_url}/api/login", json={"username": ssh_cfg["panel_user"], "password": ssh_cfg["panel_pass"]}, timeout=5)
                
                download_configs = []
                active_flags = []
                uri_list = []

                # ۱. بررسی پلن‌های پیشرفته سرور SSH
                adv_res = s_r.get(f"{remote_panel_url}/api/advanced-services", timeout=5)
                if adv_res.status_code == 200 and len(adv_res.json()) > 0:
                    adv_list = adv_res.json()
                    for adv in adv_list:
                        if adv.get("status") == 1:
                            flag_emoji = adv.get('flag') or "🌐"
                            active_flags.append(flag_emoji)
                            p_name = adv.get('name') or "سرویس پیشرفته"
                            p_desc = adv.get('description') or f"اتصال پروکسی {p_name}"
                            p_suf = adv.get('suffix') or ""
                            adv_domain = adv.get("domain") or ssh_cfg["server_ip"] or "127.0.0.1"
                            adv_port = adv.get("port") or 51830

                            download_configs.append({
                                "server_label": f"<i class='fas fa-shield-halved'></i> {p_name} {flag_emoji}",
                                "plan_name": p_name,
                                "description": p_desc,
                                "file_name": f"{peer_name}{p_suf}.conf",
                                "suffix": f"adv_{adv['id']}",
                                "mtu": adv.get('mtu') or 1420,
                                "dns": adv.get('dns') or "1.1.1.1, 1.0.0.1",
                                "keepalive": adv.get('persistent_keepalive') or 25,
                                "allowed_ips": adv.get('allowed_ips') or "0.0.0.0/0, ::/0"
                            })

                            if adv.get("public_key") and p_dict.get("private_key"):
                                wg_uri = generate_wireguard_uri(
                                    private_key=p_dict["private_key"],
                                    server_pub_key=adv["public_key"],
                                    endpoint_host=adv_domain,
                                    endpoint_port=adv_port,
                                    peer_ip=p_dict.get("peer_ip", "10.0.0.2/32"),
                                    dns=adv.get('dns') or "1.1.1.1, 8.8.8.8",
                                    mtu=adv.get('mtu') or 1280,
                                    allowed_ips=adv.get('allowed_ips') or "0.0.0.0/0, ::/0",
                                    tag_name=f"{p_name} {flag_emoji}"
                                )
                                uri_list.append(wg_uri)

                # ۲. اگر سرویس پیشرفته‌ای تعریف نشده بود، استفاده از کارت اصلی wg0 سرور SSH
                if not download_configs:
                    rem_server_ip = ssh_cfg["server_ip"] or "127.0.0.1"
                    rem_port = 51820
                    rem_pub_key = ""
                    det_res = s_r.get(f"{remote_panel_url}/api/wireguard-details?config=wg0.conf", timeout=5)
                    if det_res.status_code == 200:
                        d_json = det_res.json()
                        rem_port = int(d_json.get("port") or 51820)
                        rem_pub_key = d_json.get("public_key") or ""
                        if d_json.get("ip") and not ssh_cfg["server_ip"]:
                            rem_server_ip = d_json.get("ip")

                    active_flags.append("🌐")
                    download_configs.append({
                        "server_label": "<i class='fas fa-server'></i> سرور اختصاصی SSH 🌐",
                        "plan_name": "سرور پیشرفته",
                        "description": "اتصال مستقیم به سرور پیشرفته SSH",
                        "file_name": f"{peer_name}.conf",
                        "suffix": "main_master",
                        "mtu": 1420,
                        "dns": "1.1.1.1, 1.0.0.1",
                        "keepalive": 25,
                        "allowed_ips": "0.0.0.0/0, ::/0"
                    })

                    if rem_pub_key and p_dict.get("private_key"):
                        uri_list.append(generate_wireguard_uri(
                            private_key=p_dict["private_key"],
                            server_pub_key=rem_pub_key,
                            endpoint_host=rem_server_ip,
                            endpoint_port=rem_port,
                            peer_ip=p_dict.get("peer_ip", "10.0.0.2/32"),
                            dns="1.1.1.1, 8.8.8.8",
                            mtu=1420,
                            allowed_ips="0.0.0.0/0, ::/0",
                            tag_name=f"سرور پیشرفته SSH 🌐"
                        ))

                conn.close()

                # اگر درخواست از سمت نرم‌افزارهای VPN بود:
                if is_vpn_client_request(request) and uri_list:
                    plain_sub = "\n".join(uri_list)
                    b64_sub = base64.b64encode(plain_sub.encode("utf-8")).decode("utf-8")
                    resp = Response(b64_sub, mimetype="text/plain; charset=utf-8")
                    resp.headers["Content-Disposition"] = f'attachment; filename="{peer_name}"'
                    resp.headers["profile-update-interval"] = "12"
                    resp.headers["profile-title"] = f"base64:{base64.b64encode(peer_name.encode('utf-8')).decode('utf-8')}"
                    resp.headers["subscription-userinfo"] = f"upload=0; download={used_bytes}; total={limit_bytes}; expire={expire_ts}"
                    resp.headers["profile-web-page-url"] = f"{request.host_url.rstrip('/')}/s/{short_id}"
                    
                    if support_url:
                        resp.headers["support-url"] = support_url
                    if announcement_text:
                        resp.headers["announce"] = f"base64:{base64.b64encode(announcement_text.encode('utf-8')).decode('utf-8')}"

                    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                    return resp

                # رندر صفحه HTML با مشخصات سرور SSH
                total_min = init_duration if init_duration > 0 else (rem_minutes if rem_minutes > 0 else 43200)
                used_percent = min(100.0, round((used_bytes / limit_bytes) * 100, 1)) if limit_bytes > 0 else 0.0
                rendered = render_template(
                    "status.html",
                    peer_name=peer_name,
                    used_percent=used_percent,
                    time_percent=min(100.0, max(0.0, round(((total_min - rem_minutes) / float(total_min)) * 100.0, 1))) if total_min > 0 else 0.0,
                    limit_str=limit_str.replace("GiB", " گیگابایت").replace("MiB", " مگابایت"),
                    used_str_fa=bytes_to_readable(used_bytes),
                    rem_minutes=rem_minutes,
                    time_str_fa=format_precise_duration_fa(rem_minutes),
                    total_days=format_precise_duration_fa(total_min),
                    location_html=" ".join([f"<span class='flag-item'>{fl}</span>" for fl in set(active_flags)]) if active_flags else "<span class='flag-item'>🌐</span>",
                    download_configs=download_configs,
                    short_id=short_id,
                    status_text="<span style='display:flex; align-items:center; gap:5px;'><i class='fas fa-check-circle' style='color:#00ffc3; font-size:16px;'></i> فعال</span>",
                    status_class="st-online",
                    cache_buster=int(time.time())
                )
                resp = make_response(rendered)
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                return resp
            except Exception as e:
                bot_write_log(f"SSH Sublink Fallback Error: {e}", "ERROR")

    # =========================================================================
    # 🟣 ۵. سناریوی کلاینت‌های پلنی محلی مستر یا حالت عادی
    # =========================================================================
    total_min = 0
    if init_duration > 0:
        total_min = init_duration
    elif expiry_json_str and str(expiry_json_str).strip() not in ["None", "{}", ""]:
        try:
            exp_json = json.loads(str(expiry_json_str))
            m = int(exp_json.get("months", 0))
            d = int(exp_json.get("days", 0))
            h = int(exp_json.get("hours", 0))
            mn = int(exp_json.get("minutes", 0))
            total_min = (m * 30 * 1440) + (d * 1440) + (h * 60) + mn
        except Exception:
            pass
    if total_min <= 0 and rem_minutes > 0:
        total_min = max(1440, math.ceil(rem_minutes / 1440.0) * 1440)
    if rem_minutes > total_min:
        total_min = rem_minutes
    total_days = format_precise_duration_fa(total_min)
    f_raw = str(p_dict.get("first_usage", "0")).strip().lower()
    is_waiting_first_conn = (f_raw in ["1", "true", "yes", "calc_first_conn"])
    has_traffic = (used_bytes > 1024)

    used_percent = min(100.0, round((used_bytes / limit_bytes) * 100, 1)) if limit_bytes > 0 else 0.0
    if used_bytes >= 1073741824:
        used_str_fa = f"{used_bytes / 1073741824.0:.2f} گیگابایت"
    elif used_bytes >= 1048576:
        used_str_fa = f"{used_bytes / 1048576.0:.2f} مگابایت"
    else:
        used_str_fa = f"{used_bytes / 1024.0:.2f} کیلوبایت"
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

    is_peer_advanced = (int(p_dict.get("is_advanced") or 0) == 1)
    download_configs = []
    location_html = ""
    uri_list = []

    # ۶. الف) حالت پلنی پیشرفته لوکال
    if is_peer_advanced:
        try:
            cur.execute("SELECT * FROM advanced_services WHERE status=1 ORDER BY id ASC")
            adv_list = [dict(r) for r in cur.fetchall()]
            if adv_list:
                active_flags = []
                p_parts = p_dict.get("peer_ip", "10.0.0.2").strip().split("/")[0].split(".")
                oct3 = p_parts[2] if len(p_parts) >= 4 else "0"
                oct4 = p_parts[3] if len(p_parts) >= 4 else "2"

                for adv in adv_list:
                    flag_emoji = adv.get('flag') or "🌐"
                    active_flags.append(flag_emoji)
                    p_name = adv.get('name') or "سرویس پیشرفته"
                    p_desc = adv.get('description') or f"اتصال پروکسی {p_name}"
                    p_suf = adv.get('suffix') or ""
                    adv_iface = adv["interface_name"]
                    adv_domain = adv["domain"]
                    adv_port = adv["port"]

                    m_num = re.search(r'\d+', adv_iface)
                    num = int(m_num.group(0)) if m_num else 10
                    client_adv_ip = f"10.{num}.{oct3}.{oct4}"

                    download_configs.append({
                        "server_label": f"<i class='fas fa-shield-halved'></i> {p_name} {flag_emoji}",
                        "plan_name": p_name,
                        "description": p_desc,
                        "file_name": f"{peer_name}{p_suf}.conf",
                        "suffix": f"adv_{adv['id']}",
                        "mtu": adv.get('mtu') or 1420,
                        "dns": adv.get('dns') or "1.1.1.1, 1.0.0.1",
                        "keepalive": adv.get('persistent_keepalive') or 25,
                        "allowed_ips": adv.get('allowed_ips') or "0.0.0.0/0, ::/0"
                    })

                    # استخراج کلید عمومی کارت adv
                    server_pub_key = ""
                    conf_path = f"/etc/wireguard/{adv_iface}.conf"
                    if os.path.exists(conf_path):
                        try:
                            with open(conf_path, "r", encoding="utf-8", errors="ignore") as cf:
                                c_txt = cf.read()
                            pr_m = re.search(r"(?i)PrivateKey\s*=\s*([^\n\r]+)", c_txt)
                            if pr_m:
                                priv_raw = pr_m.group(1).strip()
                                proc = subprocess.run(["wg", "pubkey"], input=f"{priv_raw}\n", universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                                if proc.returncode == 0 and proc.stdout.strip():
                                    server_pub_key = proc.stdout.strip()
                        except Exception:
                            pass

                    if server_pub_key and p_dict.get("private_key"):
                        wg_uri = generate_wireguard_uri(
                            private_key=p_dict["private_key"],
                            server_pub_key=server_pub_key,
                            endpoint_host=adv_domain,
                            endpoint_port=adv_port,
                            peer_ip=client_adv_ip,
                            dns=adv.get('dns') or "1.1.1.1, 8.8.8.8",
                            mtu=adv.get('mtu') or 1280,
                            allowed_ips=adv.get('allowed_ips') or "0.0.0.0/0, ::/0",
                            tag_name=f"{p_name} {flag_emoji}"
                        )
                        uri_list.append(wg_uri)

                location_html = " ".join([f"<span class='flag-item'>{fl}</span>" for fl in set(active_flags)])
        except Exception:
            pass

    # ۷. ب) حالت پیش‌فرض سرور اصلی و نودهای لبه
    if not download_configs:
        special_mode = 1
        try:
            cur.execute("SELECT special_mode FROM client_settings WHERE interface_name = ?", (iface,))
            sm_row = cur.fetchone()
            if sm_row and sm_row[0] is not None:
                special_mode = int(sm_row[0])
        except Exception:
            pass

        master_name = "سرور اصلی"
        master_flag = get_master_flag_and_location() if 'get_master_flag_and_location' in globals() else "🇩🇪"
        master_suffix = ""
        master_endpoint = ""
        try:
            cur.execute("SELECT endpoint_domain, ssh_ip, server_name, file_suffix FROM master_settings LIMIT 1")
            m_row = cur.fetchone()
            if m_row:
                if m_row["server_name"]: master_name = m_row["server_name"].strip()
                if m_row["file_suffix"]: master_suffix = m_row["file_suffix"].strip()
                if m_row["endpoint_domain"]: master_endpoint = m_row["endpoint_domain"].strip()
                elif m_row["ssh_ip"]: master_endpoint = m_row["ssh_ip"].strip()
        except Exception:
            pass

        if not master_endpoint:
            master_endpoint = get_server_public_ip_cached()

        master_listen_port = 51820
        master_pub_key = ""
        master_conf_path = f"/etc/wireguard/{clean_cfg}"
        if os.path.exists(master_conf_path):
            try:
                with open(master_conf_path, "r", encoding="utf-8", errors="ignore") as f:
                    cf_text = f.read()
                p_m = re.search(r"ListenPort\s*=\s*(\d+)", cf_text, re.I)
                if p_m: master_listen_port = int(p_m.group(1))
                pr_m = re.search(r"PrivateKey\s*=\s*([^\n\r]+)", cf_text, re.I)
                if pr_m:
                    s_priv = pr_m.group(1).strip()
                    proc = subprocess.run(["wg", "pubkey"], input=f"{s_priv}\n", universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if proc.returncode == 0 and proc.stdout.strip():
                        master_pub_key = proc.stdout.strip()
            except Exception:
                pass

        all_edge_servers = []
        try:
            cur.execute("SELECT id, server_ip, flag, location, server_name, file_suffix, panel_url, panel_user, panel_pass FROM edge_servers")
            all_edge_servers = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

        synced_edge_ips = set()
        try:
            cur.execute(
                "SELECT server_ip FROM peer_synced_edges WHERE peer_name = ? AND (config = ? OR config = ?)",
                (peer_name, clean_cfg, iface)
            )
            for s_row in cur.fetchall():
                if s_row["server_ip"]:
                    synced_edge_ips.add(s_row["server_ip"].strip())
        except Exception:
            pass

        active_flags = [master_flag]
        for ef in all_edge_servers:
            srv_ip = (ef.get("server_ip") or "").strip()
            if srv_ip in synced_edge_ips:
                active_flags.append(ef.get("flag") or "🌍")
        location_html = " ".join([f"<span class='flag-item'>{fl}</span>" for fl in set(active_flags)])

        if special_mode == 1:
            try:
                cur.execute("SELECT id, plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers FROM subscription_plans")
                plans = [dict(r) for r in cur.fetchall()]
                for p_row in plans:
                    p_id = p_row["id"]
                    p_name = p_row["plan_name"]
                    p_desc = p_row.get("description") or ""
                    p_suf = p_row.get("suffix") or ""
                    p_mtu = p_row.get("mtu") or 1420
                    p_dns = p_row.get("dns") or "1.1.1.1"
                    p_keep = p_row.get("keepalive") or 25
                    p_allow = p_row.get("allowed_ips") or "0.0.0.0/0, ::/0"

                    try:
                        active_s = json.loads(p_row["active_servers"]) if p_row["active_servers"] else ["master"]
                    except Exception:
                        active_s = ["master"]

                    for srv_ip in active_s:
                        if srv_ip != "master" and srv_ip not in synced_edge_ips:
                            continue
                        if srv_ip == "master":
                            s_label = f"<i class='fas fa-server'></i> {p_name} | {master_name} {master_flag}"
                            tag_clean = f"{p_name} {master_flag}"
                            if master_pub_key and p_dict.get("private_key"):
                                wg_uri = generate_wireguard_uri(
                                    private_key=p_dict["private_key"],
                                    server_pub_key=master_pub_key,
                                    endpoint_host=master_endpoint,
                                    endpoint_port=master_listen_port,
                                    peer_ip=p_dict.get("peer_ip", "10.0.0.2/32"),
                                    dns=p_dns,
                                    mtu=p_mtu,
                                    allowed_ips=p_allow,
                                    tag_name=tag_clean
                                )
                                uri_list.append(wg_uri)
                        else:
                            e_info = next((e for e in all_edge_servers if e.get("server_ip") == srv_ip), None)
                            e_label = e_info.get("server_name") if e_info else "سرور لبه"
                            e_fl = e_info.get("flag") if e_info else "🌍"
                            s_label = f"<i class='fas fa-satellite-dish'></i> {p_name} | {e_label} {e_fl}"
                            tag_clean = f"{p_name} {e_fl}"

                            # دریافت کلید عمومی نود
                            edge_pub = ""
                            edge_port = 51820
                            edge_client_ip = p_dict.get("peer_ip", "10.0.0.2")
                            edge_client_priv = p_dict.get("private_key") or ""

                            cur.execute(
                                "SELECT edge_ip, edge_priv_key FROM peer_synced_edges WHERE peer_name=? AND (server_ip=? OR server_ip IN (SELECT ssh_ip FROM edge_servers WHERE server_ip=?)) AND (config=? OR config=?)",
                                (peer_name, srv_ip, srv_ip, clean_cfg, iface)
                            )
                            sync_row = cur.fetchone()
                            if sync_row:
                                if sync_row["edge_ip"]: edge_client_ip = sync_row["edge_ip"].strip()
                                if sync_row["edge_priv_key"]: edge_client_priv = sync_row["edge_priv_key"].strip()

                            if e_info and e_info.get("panel_url") and e_info.get("panel_user") and e_info.get("panel_pass"):
                                try:
                                    session_edge = get_edge_authenticated_session(e_info["panel_url"], e_info["panel_user"], e_info["panel_pass"])
                                    norm_url = e_info["panel_url"].rstrip("/")
                                    det_res = session_edge.get(f"{norm_url}/api/wireguard-details?config={clean_cfg}", timeout=4)
                                    if det_res.status_code == 200:
                                        d_json = det_res.json()
                                        edge_pub = d_json.get("public_key") or ""
                                        edge_port = int(d_json.get("port") or 51820)
                                except Exception:
                                    pass

                            if edge_pub and edge_client_priv:
                                wg_uri = generate_wireguard_uri(
                                    private_key=edge_client_priv,
                                    server_pub_key=edge_pub,
                                    endpoint_host=srv_ip,
                                    endpoint_port=edge_port,
                                    peer_ip=edge_client_ip,
                                    dns=p_dns,
                                    mtu=p_mtu,
                                    allowed_ips=p_allow,
                                    tag_name=tag_clean
                                )
                                uri_list.append(wg_uri)

                        download_configs.append({
                            "server_label": s_label,
                            "plan_name": p_name,
                            "description": p_desc,
                            "file_name": f"{peer_name}{p_suf}.conf",
                            "suffix": f"{p_id}_{srv_ip}",
                            "mtu": p_mtu,
                            "dns": p_dns,
                            "keepalive": p_keep,
                            "allowed_ips": p_allow
                        })
            except Exception:
                pass

        if not download_configs or special_mode == 0:
            download_configs = []
            dns_v = p_dict.get("dns") or "1.1.1.1"
            mtu_v = p_dict.get("mtu") or 1420
            keep_v = p_dict.get("persistent_keepalive") or 25
            allow_v = p_dict.get("allowed_ips") or "0.0.0.0/0, ::/0"

            download_configs.append({
                "server_label": f"<i class='fas fa-server'></i> {master_name} {master_flag}",
                "plan_name": "",
                "description": "اتصال مستقیم به شبکه سرور اصلی",
                "file_name": f"{peer_name}{master_suffix}.conf",
                "suffix": "main_master",
                "mtu": mtu_v,
                "dns": dns_v,
                "keepalive": keep_v,
                "allowed_ips": allow_v
            })

            if master_pub_key and p_dict.get("private_key"):
                uri_list.append(generate_wireguard_uri(
                    private_key=p_dict["private_key"],
                    server_pub_key=master_pub_key,
                    endpoint_host=master_endpoint,
                    endpoint_port=master_listen_port,
                    peer_ip=p_dict.get("peer_ip", "10.0.0.2/32"),
                    dns=dns_v,
                    mtu=mtu_v,
                    allowed_ips=allow_v,
                    tag_name=f"{master_name} {master_flag}"
                ))

            for ef in all_edge_servers:
                e_ip = (ef.get("server_ip") or "").strip()
                if e_ip not in synced_edge_ips:
                    continue
                e_name = ef.get("server_name") or f"سرور {ef.get('location', 'لبه')}"
                e_flag = ef.get("flag") or "🌍"
                e_suffix = ef.get("file_suffix") or ""
                download_configs.append({
                    "server_label": f"<i class='fas fa-satellite-dish'></i> {e_name} {e_flag}",
                    "plan_name": "",
                    "description": f"اتصال پایدار از طریق سرور {e_name}",
                    "file_name": f"{peer_name}{e_suffix}.conf",
                    "suffix": f"main_{e_ip}",
                    "mtu": mtu_v,
                    "dns": dns_v,
                    "keepalive": keep_v,
                    "allowed_ips": allow_v
                })

    conn.close()

    # =========================================================================
    # ⚡ بازگشت خروجی استاندارد برای نرم‌افزارهای VPN (V2Box, Happ, Sing-box)
    # =========================================================================
    if is_vpn_client_request(request):
        if not uri_list:
            if p_dict.get("private_key"):
                server_pub = obtain_public_key_conf(clean_cfg) if 'obtain_public_key_conf' in globals() else ""
                s_ip = get_server_public_ip_cached()
                uri_list.append(generate_wireguard_uri(
                    private_key=p_dict["private_key"],
                    server_pub_key=server_pub,
                    endpoint_host=s_ip,
                    endpoint_port=51820,
                    peer_ip=p_dict.get("peer_ip", "10.0.0.2/32"),
                    tag_name=peer_name
                ))

        plain_sub_body = "\n".join(uri_list)
        b64_sub_body = base64.b64encode(plain_sub_body.encode("utf-8")).decode("utf-8")

        resp = Response(b64_sub_body, mimetype="text/plain; charset=utf-8")
        resp.headers["Content-Disposition"] = f'attachment; filename="{peer_name}"'
        resp.headers["profile-update-interval"] = "12"
        resp.headers["profile-title"] = f"base64:{base64.b64encode(peer_name.encode('utf-8')).decode('utf-8')}"
        resp.headers["subscription-userinfo"] = f"upload=0; download={used_bytes}; total={limit_bytes}; expire={expire_ts}"
        resp.headers["profile-web-page-url"] = f"{request.host_url.rstrip('/')}/s/{short_id}"
        
        # 🎯 هدرهای اختصاصی تلگرام و متن اطلاعیه Happ / V2Box
        if support_url:
            resp.headers["support-url"] = support_url
        if announcement_text:
            enc_ann = base64.b64encode(announcement_text.encode('utf-8')).decode('utf-8')
            resp.headers["announce"] = f"base64:{enc_ann}"

        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    # ==============================================================
    # 🌐 بازگشت صفحه HTML برای مرورگر
    # ==============================================================
    rendered = render_template(
        "status.html",
        peer_name=peer_name,
        used_percent=used_percent,
        time_percent=time_percent,
        limit_str=limit_str_fa,
        used_str_fa=used_str_fa,
        rem_minutes=rem_minutes,
        time_str_fa=time_str_fa,
        total_days=total_days,
        location_html=location_html,
        download_configs=download_configs,
        short_id=short_id,
        status_text=status_text,
        status_class=status_class,
        cache_buster=int(time.time())
    )
    resp = make_response(rendered)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

# ========================================================================= #
# 📥 دانلود مستقیم، پایدار و بدون خطای فایل‌های کانفیگ سرور SSH و مستر
# ========================================================================= #

def short_download_config_native(short_id, suffix_key):
    short_id = str(short_id).strip()
    suffix_key = str(suffix_key).strip()

    peer_name = None
    config_file = "wg0.conf"
    p_dict = None

    # ۱. استخراج اطلاعات کاربر از دیتابیس در بلوک ایمن با قفل همزمانی
    try:
        with _db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            try:
                # الف) بررسی جدول short_links
                cur.execute("SELECT long_link FROM short_links WHERE short_id = ?", (short_id,))
                row = cur.fetchone()
                if row and row["long_link"]:
                    long_link = row["long_link"]
                    p_m = re.search(r"peer_name=([^&]+)", long_link) or re.search(r"peerName=([^&]+)", long_link)
                    if p_m: peer_name = urllib.parse.unquote(p_m.group(1))

                # ب) بررسی مستقیم جدول peers با توکن یا نام کلاینت
                if not peer_name:
                    cur.execute(
                        "SELECT peer_name, config FROM peers WHERE token=? OR token LIKE ? OR ? LIKE (token || '%') OR peer_name=?", 
                        (short_id, f"{short_id}%", short_id, short_id)
                    )
                    p_row = cur.fetchone()
                    if p_row:
                        peer_name = p_row["peer_name"]
                        config_file = p_row["config"] or "wg0.conf"

                if not peer_name:
                    cur.execute("SELECT peer_name, config FROM peers WHERE peer_name = ?", (short_id,))
                    p_row = cur.fetchone()
                    if p_row:
                        peer_name = p_row["peer_name"]
                        config_file = p_row["config"] or "wg0.conf"

                if not peer_name:
                    return "Error: Peer not found in database", 404

                cur.execute("SELECT * FROM peers WHERE peer_name=?", (peer_name,))
                peer_rec = cur.fetchone()
                if not peer_rec:
                    return "Error: Peer record missing", 404

                p_dict = dict(peer_rec)
            finally:
                conn.close()
    except Exception as e:
        return f"Database Error: {e}", 500

    # 📌 مقداردهی قطعی، سراسری و ضد خطای متغیرهای پایه
    config_file = p_dict.get("config") or config_file or "wg0.conf"
    clean_cfg = config_file if str(config_file).endswith(".conf") else f"{config_file}.conf"
    iface = clean_cfg.replace(".conf", "")

    client_priv_key = p_dict.get("private_key") or ""
    client_ip = p_dict.get("peer_ip") or "10.0.0.2"
    base_dns = p_dict.get("dns") or "1.1.1.1, 1.0.0.1"
    base_mtu = p_dict.get("mtu") or 1420
    base_keepalive = p_dict.get("persistent_keepalive") or 25
    base_allowed_ips = p_dict.get("allowed_ips") or "0.0.0.0/0, ::/0"

    # =========================================================================
    # 🔵 ۱. پردازش دانلود فایل کانفیگ برای کلاینت ساخته‌شده روی سرور SSH ریموت
    # =========================================================================
    if int(p_dict.get("is_advanced") or 0) == 2 or str(p_dict.get("config")) == "ssh_remote":
        try:
            with _db_lock:
                conn = get_db_conn()
                cur = conn.cursor()
                cur.execute("SELECT panel_url, panel_user, panel_pass, server_ip FROM advanced_ssh_settings LIMIT 1")
                row_ssh = cur.fetchone()
                conn.close()

            if row_ssh and row_ssh["panel_url"]:
                p_url = row_ssh["panel_url"].rstrip("/")
                p_user = row_ssh["panel_user"]
                p_pass = row_ssh["panel_pass"]
                tok = p_dict.get("token") or short_id

                s_r = requests.Session()
                s_r.verify = False

                # 🔹 تلاش ۱: دانلود مستقیم فایل از سرور SSH با توکن
                try:
                    r1 = s_r.get(f"{p_url}/s/{tok}/download/{suffix_key}", timeout=4, headers={"User-Agent": "Mozilla/5.0"})
                    if r1.status_code == 200 and "[Interface]" in r1.text:
                        return Response(
                            r1.content,
                            mimetype="application/octet-stream",
                            headers={
                                "Content-Disposition": r1.headers.get("Content-Disposition", f'attachment; filename="{peer_name}.conf"'),
                                "Cache-Control": "no-cache, no-store, must-revalidate"
                            }
                        )
                except Exception:
                    pass

                # 🔹 تلاش ۲: دانلود با نام کاربر
                try:
                    r2 = s_r.get(f"{p_url}/s/{peer_name}/download/{suffix_key}", timeout=4, headers={"User-Agent": "Mozilla/5.0"})
                    if r2.status_code == 200 and "[Interface]" in r2.text:
                        return Response(
                            r2.content,
                            mimetype="application/octet-stream",
                            headers={
                                "Content-Disposition": r2.headers.get("Content-Disposition", f'attachment; filename="{peer_name}.conf"'),
                                "Cache-Control": "no-cache, no-store, must-revalidate"
                            }
                        )
                except Exception:
                    pass

                # 🔹 تلاش ۳ و ۴ (تولید مستقیم و ۱۰۰٪ تضمینی کانفیگ سرور SSH بدون ارور):
                try:
                    s_r.post(f"{p_url}/api/login", json={"username": p_user, "password": p_pass}, timeout=4)
                    adv_res = s_r.get(f"{p_url}/api/advanced-services", timeout=4)
                    
                    if adv_res.status_code == 200:
                        adv_list = adv_res.json()
                        adv_target = None
                        if suffix_key.startswith("adv_"):
                            adv_id = int(suffix_key.replace("adv_", ""))
                            adv_target = next((x for x in adv_list if int(x.get("id") or 0) == adv_id), None)
                        if not adv_target and adv_list:
                            adv_target = adv_list[0]

                        if adv_target:
                            adv_iface = adv_target.get("interface_name") or "adv10"
                            adv_domain = adv_target.get("domain") or row_ssh["server_ip"] or "127.0.0.1"
                            adv_port = adv_target.get("port") or 51830
                            adv_suffix = adv_target.get("suffix") or ""

                            # استخراج کلید عمومی کارت شبکه سرور SSH
                            wg_det = s_r.get(f"{p_url}/api/wireguard-details?config={adv_iface}.conf", timeout=4)
                            server_pub_key = (wg_det.json().get("public_key") if wg_det.status_code == 200 else "") or ""

                            p_parts = client_ip.strip().split("/")[0].split(".")
                            oct3 = p_parts[2] if len(p_parts) >= 4 else "0"
                            oct4 = p_parts[3] if len(p_parts) >= 4 else "2"
                            m_num = re.search(r'\d+', adv_iface)
                            num = int(m_num.group(0)) if m_num else 10
                            client_adv_ip = f"10.{num}.{oct3}.{oct4}"

                            conf_content = f"""[Interface]
PrivateKey = {client_priv_key}
Address = {client_adv_ip}/32
DNS = {adv_target.get('dns') or base_dns}
MTU = {adv_target.get('mtu') or base_mtu}

[Peer]
PublicKey = {server_pub_key}
Endpoint = {adv_domain}:{adv_port}
AllowedIPs = {adv_target.get('allowed_ips') or base_allowed_ips}
PersistentKeepalive = {adv_target.get('persistent_keepalive') or base_keepalive}
"""
                            return Response(
                                conf_content.strip() + "\n",
                                mimetype="application/octet-stream",
                                headers={
                                    "Content-Disposition": f'attachment; filename="{peer_name}{adv_suffix}.conf"',
                                    "Cache-Control": "no-cache, no-store, must-revalidate"
                                }
                            )
                except Exception:
                    pass

                return redirect(f"{p_url}/s/{tok}/download/{suffix_key}")
        except Exception:
            pass

    # =========================================================================
    # 🚀 ۲. پردازش دانلود برای سرویس‌های پیشرفته پروکسی لوکال مستر (adv_<id>)
    # =========================================================================
    if suffix_key.startswith("adv_"):
        try:
            adv_id = int(suffix_key.replace("adv_", ""))
            with _db_lock:
                conn = get_db_conn()
                cur = conn.cursor()
                try:
                    cur.execute("SELECT * FROM advanced_services WHERE id=?", (adv_id,))
                    adv_row = cur.fetchone()
                finally:
                    conn.close()

            if not adv_row:
                return "Error: Advanced service not found", 404

            adv_d = dict(adv_row)
            adv_iface = adv_d["interface_name"]
            adv_domain = adv_d["domain"]
            adv_port = adv_d["port"]
            adv_suffix = adv_d.get("suffix") or ""

            p_ip_parts = client_ip.strip().split("/")[0].split(".")
            oct3 = p_ip_parts[2] if len(p_ip_parts) >= 4 else "0"
            oct4 = p_ip_parts[3] if len(p_ip_parts) >= 4 else "2"
            m_num = re.search(r'\d+', adv_iface)
            num = int(m_num.group(0)) if m_num else 10
            client_adv_ip = f"10.{num}.{oct3}.{oct4}"

            server_pub_key = ""
            conf_path = f"/etc/wireguard/{adv_iface}.conf"
            if os.path.exists(conf_path):
                try:
                    with open(conf_path, "r", encoding="utf-8", errors="ignore") as cf:
                        c_txt = cf.read()
                    pr_m = re.search(r"(?i)PrivateKey\s*=\s*([^\n\r]+)", c_txt)
                    if pr_m:
                        priv_raw = pr_m.group(1).strip()
                        proc = subprocess.run(["wg", "pubkey"], input=f"{priv_raw}\n", universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        if proc.returncode == 0 and proc.stdout.strip():
                            server_pub_key = proc.stdout.strip()
                except Exception:
                    pass

            if not server_pub_key:
                priv_new = subprocess.getoutput("wg genkey").strip()
                server_pub_key = subprocess.getoutput(f"echo '{priv_new}' | wg pubkey").strip()
                with open(conf_path, "w", encoding="utf-8") as cf:
                    cf.write(f"[Interface]\nPrivateKey = {priv_new}\nListenPort = {adv_port}\nAddress = 10.{num}.0.1/16\n")
                subprocess.run(f"wg-quick down {adv_iface} 2>/dev/null; wg-quick up {adv_iface} 2>/dev/null", shell=True)

            conf_content = f"""[Interface]
PrivateKey = {client_priv_key}
Address = {client_adv_ip}/32
DNS = {adv_d.get('dns') or base_dns}
MTU = {adv_d.get('mtu') or base_mtu}

[Peer]
PublicKey = {server_pub_key}
Endpoint = {adv_domain}:{adv_port}
AllowedIPs = {adv_d.get('allowed_ips') or base_allowed_ips}
PersistentKeepalive = {adv_d.get('persistent_keepalive') or base_keepalive}
"""
            return Response(
                conf_content.strip() + "\n",
                mimetype="application/octet-stream",
                headers={
                    "Content-Disposition": f'attachment; filename="{peer_name}{adv_suffix}.conf"',
                    "Cache-Control": "no-cache, no-store, must-revalidate"
                }
            )
        except Exception as ex_adv:
            return f"Error generating advanced config: {ex_adv}", 500

    # =========================================================================
    # 🌐 ۳. پردازش دانلود استاندارد (پلن‌های ساب، سرور اصلی و سرورهای لبه)
    # =========================================================================
    try:
        plan_id = suffix_key.split("_")[0] if "_" in suffix_key else "main"
        target_server = suffix_key.split("_", 1)[1] if "_" in suffix_key else "master"

        filename = f"{peer_name}.conf"

        with _db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            try:
                if plan_id != "main" and plan_id.isdigit():
                    cur.execute("SELECT suffix, mtu, dns, keepalive, allowed_ips FROM subscription_plans WHERE id=?", (int(plan_id),))
                    plan_row = cur.fetchone()
                    if plan_row:
                        p_suf = plan_row["suffix"] or ""
                        filename = f"{peer_name}{p_suf}.conf"
                        if plan_row["mtu"]: base_mtu = plan_row["mtu"]
                        if plan_row["dns"]: base_dns = plan_row["dns"]
                        if plan_row["keepalive"]: base_keepalive = plan_row["keepalive"]
                        if plan_row["allowed_ips"]: base_allowed_ips = plan_row["allowed_ips"]

                server_ip = "127.0.0.1"
                server_pub_key = ""
                listen_port = 51820

                if target_server.lower() == "master":
                    cur.execute("SELECT endpoint_domain, ssh_ip FROM master_settings LIMIT 1")
                    m_row = cur.fetchone()
                    if m_row and m_row["endpoint_domain"]:
                        server_ip = m_row["endpoint_domain"].strip()
                    elif m_row and m_row["ssh_ip"]:
                        server_ip = m_row["ssh_ip"].strip()
                    else:
                        server_ip = get_server_public_ip_cached()

                    master_conf_path = f"/etc/wireguard/{clean_cfg}"
                    if os.path.exists(master_conf_path):
                        try:
                            with open(master_conf_path, "r", encoding="utf-8", errors="ignore") as f:
                                cf_text = f.read()
                            port_match = re.search(r"ListenPort\s*=\s*(\d+)", cf_text, re.IGNORECASE)
                            if port_match: listen_port = int(port_match.group(1))
                            priv_match = re.search(r"PrivateKey\s*=\s*([^\n\r]+)", cf_text, re.IGNORECASE)
                            if priv_match:
                                s_priv = priv_match.group(1).strip()
                                proc = subprocess.run(["wg", "pubkey"], input=f"{s_priv}\n", universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                                if proc.returncode == 0 and proc.stdout.strip():
                                    server_pub_key = proc.stdout.strip()
                        except Exception:
                            pass
                else:
                    cur.execute(
                        "SELECT edge_ip, edge_priv_key FROM peer_synced_edges WHERE peer_name=? AND (server_ip=? OR server_ip IN (SELECT ssh_ip FROM edge_servers WHERE server_ip=?)) AND (config=? OR config=?)",
                        (peer_name, target_server, target_server, clean_cfg, iface)
                    )
                    sync_row = cur.fetchone()
                    if sync_row:
                        if sync_row["edge_ip"] and sync_row["edge_ip"].strip():
                            client_ip = sync_row["edge_ip"].strip()
                        if sync_row["edge_priv_key"] and len(sync_row["edge_priv_key"].strip()) == 44:
                            client_priv_key = sync_row["edge_priv_key"].strip()

                    cur.execute("SELECT server_ip, panel_url, panel_user, panel_pass, ssh_ip FROM edge_servers WHERE server_ip=?", (target_server,))
                    edge_row = cur.fetchone()
                    if edge_row:
                        e_dict = dict(edge_row)
                        server_ip = e_dict.get("server_ip") or "127.0.0.1"
                        panel_url = e_dict.get("panel_url")
                        panel_user = e_dict.get("panel_user")
                        panel_pass = e_dict.get("panel_pass")
                        if panel_url and panel_user and panel_pass:
                            try:
                                session_edge = get_edge_authenticated_session(panel_url, panel_user, panel_pass)
                                norm_url = panel_url.rstrip("/")
                                det_res = session_edge.get(f"{norm_url}/api/wireguard-details?config={clean_cfg}", timeout=4)
                                if det_res.status_code == 200:
                                    d_json = det_res.json()
                                    server_pub_key = d_json.get("public_key") or ""
                                    listen_port = int(d_json.get("port") or 51820)
                            except Exception:
                                pass
            finally:
                conn.close()

        conf_content = f"""[Interface]
PrivateKey = {client_priv_key}
Address = {client_ip}/32
DNS = {base_dns}
MTU = {base_mtu}

[Peer]
PublicKey = {server_pub_key}
Endpoint = {server_ip}:{listen_port}
AllowedIPs = {base_allowed_ips}
PersistentKeepalive = {base_keepalive}
"""
        return Response(
            conf_content.strip() + "\n",
            mimetype="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache, no-store, must-revalidate"
            }
        )

    except Exception as e:
        return f"Error generating config: {e}", 500

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
    if not timestamp or int(timestamp) < 1000000:
        timestamp = int(time.time())
    t = time.gmtime(int(timestamp) + 12600)
    jy, jm, jd = gregorian_to_jalali(t.tm_year, t.tm_mon, t.tm_mday)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {t.tm_hour:02d}:{t.tm_min:02d}"

def bytes_to_readable(b):
    val = float(b or 0)
    if val <= 0:
        return "0 بایت"
    units = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"]
    i = int(math.floor(math.log(val, 1024))) if val > 0 else 0
    return f"{val / (1024 ** min(i, len(units)-1)):.2f} {units[min(i, len(units)-1)]}"

def get_peer_creation_date_jalali(peer_name):
    conn = get_db_conn()
    cur = conn.cursor()
    created_str = ""
    try:
        r = cur.execute("SELECT created_at_jalali, created_at FROM peers WHERE peer_name=?", (peer_name,)).fetchone()
        if r:
            if r["created_at_jalali"] and str(r["created_at_jalali"]).strip() not in ["", "None"]:
                created_str = str(r["created_at_jalali"]).strip()
            elif r["created_at"] and int(r["created_at"]) > 1000000:
                created_str = format_jalali_date(int(r["created_at"]))
    except Exception:
        pass
    conn.close()
    return created_str or format_jalali_date(int(time.time()))
def create_peer_native_scoped(peer_name, vol_str, days, auth_info, first_usage=False, dns="1.1.1.1", mtu=1420, keepalive=25, custom_base_url=None):
    cfg_file = "wg0.conf" if auth_info["all_interfaces"] else f"{auth_info['interface']}.conf"
    iface = cfg_file.replace(".conf", "")

    priv_k = subprocess.getoutput("wg genkey").strip()
    pub_k = subprocess.getoutput(f"echo '{priv_k}' | wg pubkey").strip()
    if not priv_k or not pub_k:
        return False, "خطا در تولید کلیدهای WireGuard."

    lim_str, lim_bytes, _ = parse_volume_input_to_wg_limit(vol_str)
    rem_minutes = int(days * 1440)
    init_duration = rem_minutes
    exp_json_str = json.dumps({"months": 0, "days": int(days), "hours": 0, "minutes": 0})
    now_ts = int(time.time())
    jalali_created = format_jalali_date(now_ts)
    first_u_val = 1 if first_usage else 0
    token = secrets.token_urlsafe(16)
    
    # ساخت لینک ساب بدون باز کردن اتصال تودرتوی دیتابیس
    base_url = custom_base_url or get_panel_base_url()
    sub_url = f"{base_url.rstrip('/')}/s/{token}"

    conf_path = f"/etc/wireguard/{cfg_file}"
    base_prefix = "10.0.0"
    if os.path.exists(conf_path):
        try:
            txt = open(conf_path, 'r', encoding='utf-8').read()
            m = re.search(r"Address\s*=\s*([0-9]+\.[0-9]+\.[0-9]+)\.", txt, re.IGNORECASE)
            if m:
                base_prefix = m.group(1).strip()
        except Exception:
            pass

    # تمام عملیات دیتابیس در یک بلوک امن با قفل نخ و بستن قطعی کانکشن انجام می‌شود
    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT id FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, cfg_file, iface))
            if cur.fetchone():
                return False, f"نام کلاینت '{peer_name}' در اینترفیس {iface} تکراری است."

            cur.execute("SELECT peer_ip FROM peers WHERE config=? OR config=?", (cfg_file, iface))
            used_ips = set(r[0] for r in cur.fetchall() if r[0])
            
            free_ip = None
            for oct4 in range(2, 254):
                cand = f"{base_prefix}.{oct4}"
                if cand not in used_ips:
                    free_ip = cand
                    break
            if not free_ip:
                free_ip = f"{base_prefix}.245"

            cur.execute("PRAGMA table_info(peers)")
            cols = [c[1] for c in cur.fetchall()]
            if "created_at" not in cols:
                cur.execute("ALTER TABLE peers ADD COLUMN created_at INTEGER")
            if "created_at_jalali" not in cols:
                cur.execute("ALTER TABLE peers ADD COLUMN created_at_jalali TEXT")
            if "initial_duration" not in cols:
                cur.execute("ALTER TABLE peers ADD COLUMN initial_duration INTEGER DEFAULT 0")

            cur.execute(
                "INSERT OR REPLACE INTO peers (peer_name, peer_ip, public_key, [limit], used, remaining_time, config, expiry_time_json, first_usage, expiry_blocked, monitor_blocked, private_key, dns, mtu, persistent_keepalive, allowed_ips, token, created_at, created_at_jalali, initial_duration) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, '0.0.0.0/0, ::/0', ?, ?, ?, ?)",
                (peer_name, free_ip, pub_k, lim_str, rem_minutes, cfg_file, exp_json_str, first_u_val, priv_k, dns, mtu, keepalive, token, now_ts, jalali_created, init_duration)
            )
            
            cur.execute("CREATE TABLE IF NOT EXISTS short_links (short_id TEXT PRIMARY KEY, long_link TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token, f"/peer-details?peer_name={peer_name}&config_file={cfg_file}&token={token}"))
            cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token[:8], f"/peer-details?peer_name={peer_name}&config_file={cfg_file}&token={token}"))

            cur.execute("CREATE TABLE IF NOT EXISTS services (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, email TEXT, sub_id TEXT, plan_name TEXT, purchase_date INTEGER, vol REAL, days INTEGER, first_usage INTEGER)")
            cur.execute(
                "INSERT INTO services (user_id, email, sub_id, plan_name, purchase_date, vol, days, first_usage) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (auth_info.get("reseller_id", 0), peer_name, sub_url, f"دستی ({lim_str} - {days}روز)", now_ts, float(lim_bytes / (1024**3)), days, first_u_val)
            )
            conn.commit()
        finally:
            conn.close()

    # عملیات سیستمی و همگام‌سازی بعد از آزاد شدن دیتابیس انجام می‌پذیرد
    reconcile_db_and_conf_files()
    subprocess.run(f"wg set {iface} peer {pub_k} allowed-ips {free_ip}/32", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"wg-quick save {iface}", shell=True, stderr=subprocess.DEVNULL)
    sync_action_to_edges("create", peer_name, cfg_file)

    return True, {
        "peer_name": peer_name,
        "peer_ip": free_ip,
        "public_key": pub_k,
        "limit_str": lim_str,
        "days": days,
        "sub_url": sub_url,
        "token": token
    }

def tg_send_message(chat_id, text, reply_markup=None, token=None):
    token = token or get_bot_active_token()
    if not token or not chat_id:
        return None
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + str(token) + "/sendMessage", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def tg_edit_message(chat_id, message_id, text, reply_markup=None, token=None):
    token = token or get_bot_active_token()
    if not token or not chat_id or not message_id:
        return None
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + str(token) + "/editMessageText", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def tg_answer_callback(callback_query_id, text="", alert=False, token=None):
    token = token or get_bot_active_token()
    if not token or not callback_query_id:
        return
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + str(token) + "/answerCallbackQuery", data=json.dumps({"callback_query_id": callback_query_id, "text": text, "show_alert": alert}).encode("utf-8"), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def tg_delete_message(chat_id, message_id, token=None):
    token = token or get_bot_active_token()
    if not token or not chat_id or not message_id:
        return
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + str(token) + "/deleteMessage", data=json.dumps({"chat_id": chat_id, "message_id": message_id}).encode("utf-8"), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def tg_send_document(chat_id, filename, file_content, caption="", token=None):
    token = token or get_bot_active_token()
    if not token or not chat_id:
        return None
    try:
        requests.post("https://api.telegram.org/bot" + str(token) + "/sendDocument", data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}, files={"document": (filename, file_content.encode("utf-8"), "text/plain")}, timeout=12)
    except Exception:
        pass

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
                            if not dl_url.startswith("http"):
                                dl_url = base_host + "/" + dl_url.lstrip("/")
                            dl_res = requests.get(dl_url, timeout=6)
                            if dl_res.status_code == 200 and "[Interface]" in dl_res.text:
                                loc_name = "سرور اصلی"
                                m_title = re.search(r'<b[^>]*>(.*?)</b>', card, re.S)
                                if m_title:
                                    loc_name = re.sub(r'<[^>]+>', '', m_title.group(1)).strip()
                                configs.append({"name": str(peer_name) + ".conf", "emoji": "🌐", "location_name": loc_name, "description": "اتصال مستقیم", "content": dl_res.text.strip()})
        except Exception:
            pass
    if not configs:
        try:
            r_raw = requests.get("http://127.0.0.1:5000/api/download-peer-config?peerName=" + str(peer_name) + "&config=wg0.conf", timeout=6)
            if r_raw.status_code == 200 and "[Interface]" in r_raw.text:
                configs.append({"name": str(peer_name) + ".conf", "emoji": "🌐", "location_name": "سرور اصلی", "description": "کانفیگ وایرگارد", "content": r_raw.text.strip()})
        except Exception:
            pass
    return configs

def show_templates_list_tg(chat_id, user_id=0, message_id=None, token=None):
    auth = get_user_auth(chat_id, user_id)
    reseller_id = auth.get("reseller_id", 0)

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0, name TEXT NOT NULL, vol TEXT NOT NULL, days INTEGER NOT NULL, first_usage INTEGER DEFAULT 1)")
    
    tpls = [dict(r) for r in cur.execute("SELECT * FROM templates WHERE user_id=? OR user_id=0 ORDER BY user_id DESC, id ASC", (reseller_id,)).fetchall()]
    conn.close()
    
    msg = "📋 <b>الگوهای آماده ساخت کلاینت:</b>\n\nجهت ساخت کاربر با الگوی مورد نظر، آن را انتخاب کنید:"
    kb = []
    for t in tpls:
        calc_txt = "⏳ در اولین اتصال" if (int(t.get("first_usage") or 0) == 1) else "⚡ همین الان"
        lim_str = t.get("vol", "50GiB")
        days = t.get("days", 30)
        t_id = t["id"]
        is_mine = "⭐ " if (t.get("user_id") and t.get("user_id") == reseller_id) else "📦 "
        kb.append([{"text": f"{is_mine}{t['name']} ({lim_str} | {days} روز | {calc_txt})", "callback_data": f"tpl_view_{t_id}"}])
    
    kb.append([{"text": "➕ ساخت الگوی اختصاصی جدید", "callback_data": "tpl_add"}])
    kb.append([{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "start_action"}])
    if message_id:
        tg_edit_message(chat_id, message_id, msg, {"inline_keyboard": kb}, token)
    else:
        tg_send_message(chat_id, msg, {"inline_keyboard": kb}, token)

def show_users_list_tg(chat_id, user_id, page=1, search_query=None, message_id=None, token=None):
    auth = get_user_auth(chat_id, user_id)
    if auth["role"] not in ["admin", "client"]:
        tg_send_message(chat_id, auth.get("reason", "عدم دسترسی"), token=token)
        return

    per_page = 12
    offset = (page - 1) * per_page
    conn = get_db_conn()
    cur = conn.cursor()

    where_clauses = []
    params = []

    if not auth["all_interfaces"]:
        target_cfg = f"{auth['interface']}.conf"
        where_clauses.append("(config = ? OR config = ?)")
        params.extend([target_cfg, auth["interface"]])

    if search_query:
        where_clauses.append("peer_name LIKE ?")
        params.append(f"%{search_query}%")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    cur.execute(f"SELECT COUNT(*) FROM peers {where_sql}", params)
    total = cur.fetchone()[0] or 0

    query_params = list(params) + [per_page, offset]
    cur.execute(
        f"SELECT peer_name, peer_ip, public_key, [limit], used, remaining_time, monitor_blocked, expiry_blocked, first_usage, config FROM peers {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
        query_params
    )
    peers = [dict(r) for r in cur.fetchall()]
    conn.close()

    total_pages = max(1, math.ceil(total / per_page))
    if not peers:
        msg = f"🔍 کاربری با جستجوی <code>{search_query}</code> یافت نشد." if search_query else "👥 هیچ کاربری در این بخش ثبت نشده است."
        if message_id:
            tg_edit_message(chat_id, message_id, msg, None, token)
        else:
            tg_send_message(chat_id, msg, get_main_reply_keyboard(), token)
        return

    kb = []
    current_row = []
    for p in peers:
        name = p["peer_name"]
        icon = get_peer_status_icon(p)
        current_row.append({"text": f"{icon} {name}", "callback_data": f"mg_det_{name}_{page}"})
        if len(current_row) == 3:
            kb.append(current_row)
            current_row = []
    if current_row:
        kb.append(current_row)

    nav_row = []
    if page > 1:
        nav_row.append({"text": "◀️ قبلی", "callback_data": f"mg_list_{page-1}"})
    nav_row.append({"text": "🔍 جستجو", "callback_data": "mg_search"})
    if page < total_pages:
        nav_row.append({"text": "بعدی ▶️", "callback_data": f"mg_list_{page+1}"})
    kb.append(nav_row)

    search_txt = f"\n🔍 <i>نتایج جستجو برای:</i> <code>{search_query}</code>" if search_query else ""
    iface_tag = "همه اینترفیس‌ها" if auth["all_interfaces"] else f"کارت {auth['interface']}"
    msg = f"👥 <b>مدیریت کاربران ({iface_tag}):</b>{search_txt}\n📑 صفحه <b>{page}</b> از <b>{total_pages}</b> (کل: {total} کاربر)\nراهنما: 🟢 فعال | 🟡 در انتظار اتصال | 🔴 مسدود یا منقضی"

    if message_id:
        tg_edit_message(chat_id, message_id, msg, {"inline_keyboard": kb}, token)
    else:
        tg_send_message(chat_id, msg, {"inline_keyboard": kb}, token)

def show_detailed_user_tg(chat_id, peer_name, page=1, message_id=None, token=None):
    auth = get_user_auth(chat_id)
    conn = get_db_conn()
    cur = conn.cursor()
    
    if auth["all_interfaces"]:
        p_row = cur.execute("SELECT * FROM peers WHERE peer_name=?", (peer_name,)).fetchone()
    else:
        cfg = f"{auth['interface']}.conf"
        p_row = cur.execute("SELECT * FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, cfg, auth["interface"])).fetchone()
        
    conn.close()
    if not p_row:
        if message_id:
            tg_edit_message(chat_id, message_id, "❌ کاربر یافت نشد یا دسترسی به آن ندارید.", None, token)
        else:
            tg_send_message(chat_id, "❌ کاربر یافت نشد.", token=token)
        return

    pd = dict(p_row)
    used_bytes = int(pd.get("used") or 0)
    used_str = bytes_to_readable(used_bytes)
    lim_str = pd.get("limit") or "نامحدود"
    rem_minutes = int(pd.get("remaining_time") or 0)
    init_d = int(pd.get("initial_duration") or 0)
    if init_d <= 0:
        init_d = max(1440, rem_minutes)
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
                        if (time.time() - hs_ts) < 180 and hs_ts > 0:
                            is_online_now = True
    except Exception:
        pass

    icon = get_peer_status_icon(pd)
    if icon == "🔴":
        st_text = "🔴 مسدود / منقضی شده"
        rem_str = "منقضی شده"
    elif icon == "🟡":
        st_text = "🟡 در انتظار اولین اتصال"
        rem_str = f"در انتظار اتصال (کل: {total_plan_str})"
    else:
        st_text = "🟢 فعال و متصل" if is_online_now else "🟢 فعال / آماده"
        rem_str = format_precise_duration_fa(rem_minutes)

    date_str = get_peer_creation_date_jalali(peer_name)
    sub_url = get_peer_sublink_url(peer_name, pd.get("config", "wg0.conf"))
    
    msg = (
        f"👤 <b>جزئیات کلاینت:</b> <code>{peer_name}</code>\n\n"
        f"📊 <b>حجم کل پلن:</b> <code>{lim_str}</code>\n"
        f"📉 <b>حجم مصرفی:</b> <code>{used_str}</code>\n"
        f"⏳ <b>کل اعتبار اولیه:</b> <code>{total_plan_str}</code>\n"
        f"⏱ <b>زمان باقی‌مانده:</b> <b>{rem_str}</b>\n"
        f"🚦 <b>وضعیت حساب:</b> <b>{st_text}</b>\n"
        f"🌐 <b>آی‌پی کلاینت:</b> <code>{pd.get('peer_ip', '10.0.0.2')}</code>\n"
        f"📅 <b>تاریخ و ساعت ساخت:</b> <code>{date_str}</code>\n\n"
        f"🔗 <b>لینک ساب‌اسکریپشن:</b>\n<code>{sub_url}</code>"
    )
    
    kb = [
        [{"text": "📥 دریافت کانفیگ", "callback_data": "extwg_" + str(peer_name)}, {"text": "📷 دریافت کد QR", "callback_data": "sendqr_" + str(peer_name)}],
        [{"text": "🔄 ریست مصرف حجم", "callback_data": f"mg_act_rstvol_{peer_name}_{page}"}, {"text": "🔘 فعال / غیرفعال", "callback_data": f"mg_act_toggle_{peer_name}_{page}"}],
        [{"text": "➕ افزایش زمان", "callback_data": f"mg_act_time_{peer_name}_{page}"}, {"text": "➖ کاهش زمان", "callback_data": f"mg_act_dectime_{peer_name}_{page}"}],
        [{"text": "➕ افزایش حجم", "callback_data": f"mg_act_vol_{peer_name}_{page}"}, {"text": "➖ کاهش حجم", "callback_data": f"mg_act_decvol_{peer_name}_{page}"}],
        [{"text": "🗑 حذف دائم کلاینت", "callback_data": f"mg_act_del_{peer_name}_{page}"}],
        [{"text": "🔙 بازگشت به لیست", "callback_data": f"mg_list_{page}"}]
    ]
    if message_id:
        tg_edit_message(chat_id, message_id, msg, {"inline_keyboard": kb}, token)
    else:
        tg_send_message(chat_id, msg, {"inline_keyboard": kb}, token)

# ========================================================================= #
# 🤖 OFFICIAL PROCESS TELEGRAM UPDATE (PRODUCTION / NO DEBUG LOGS)          #
# ========================================================================= #

def process_telegram_update(update, token):
    msg = update.get("message") or update.get("callback_query", {}).get("message")
    cb = update.get("callback_query")
    from_user = update.get("message", {}).get("from") or update.get("callback_query", {}).get("from") or {}
    user_id = from_user.get("id")
    chat_id = msg.get("chat", {}).get("id") if msg else user_id
    message_id = msg.get("message_id") if msg else None
    text = update.get("message", {}).get("text", "").strip()
    cb_data = cb.get("data") if cb else None
    
    if not user_id or not chat_id:
        return

    auth = get_user_auth(chat_id, user_id)

    if auth["role"] not in ["admin", "client"]:
        if cb:
            tg_answer_callback(cb.get("id"), "دسترسی مسدود است!", alert=True, token=token)
        tg_send_message(chat_id, auth.get("reason", "❌ عدم دسترسی"), {"remove_keyboard": True}, token=token)
        return

    if cb:
        tg_answer_callback(cb.get("id"), token=token)

    custom_base_url = None
    if auth.get("reseller_id"):
        try:
            with _db_lock:
                conn_u = get_db_conn()
                r_u = conn_u.execute("SELECT bot_base_url FROM sub_panels WHERE id=?", (auth["reseller_id"],)).fetchone()
                if r_u and r_u["bot_base_url"]:
                    custom_base_url = r_u["bot_base_url"].strip().rstrip('/')
                conn_u.close()
        except Exception:
            pass

    try:
        # --- دستور شروع ---
        if text == "/start":
            _user_steps[user_id] = {"step": "idle"}
            welcome = f"🤖 <b>به ربات مدیریت هوشمند وایرگارد خوش آمدید!</b>\n\n👤 نقش شما: <b>{auth['username']}</b>\n⚙️ اینترفیس مجاز: <code>{auth['interface'] if not auth['all_interfaces'] else 'تمامی اینترفیس‌ها'}</code>\n\nگزینه مورد نظر را انتخاب کنید:"
            tg_send_message(chat_id, welcome, get_main_reply_keyboard(), token)
            return

        # --- 📊 آمار پنل من ---
        if text == "📊 آمار پنل من":
            _user_steps[user_id] = {"step": "idle"}
            now_time = format_jalali_date(time.time())
            m_stat = subprocess.getoutput("free -m | grep Mem | awk '{print $3, $2}'").split()
            ram_info = str(m_stat[0]) + "MB / " + str(m_stat[1]) + "MB" if len(m_stat) >= 2 else "نامشخص"
            cpu_usage = subprocess.getoutput("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")

            with _db_lock:
                conn = get_db_conn()
                cur = conn.cursor()
                try:
                    if auth["all_interfaces"]:
                        total_p = cur.execute("SELECT COUNT(*) FROM peers").fetchone()[0] or 0
                        blocked_p = cur.execute("SELECT COUNT(*) FROM peers WHERE monitor_blocked=1 OR expiry_blocked=1").fetchone()[0] or 0
                        live_used = cur.execute("SELECT SUM(used) FROM peers").fetchone()[0] or 0
                        del_used = cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1").fetchone()
                        del_val = del_used[0] if del_used else 0
                        vault_total = cur.execute("SELECT SUM(vault_bytes) FROM interface_vault").fetchone()[0] or 0
                        total_used_gb = (live_used + max(del_val, vault_total)) / (1024 * 1024 * 1024)

                        report = (
                            f"📊 <b>آمار پنل مدیریت کل (Admin)</b>\n\n"
                            f"👤 <b>کاربر:</b> {auth['username']}\n"
                            f"👥 <b>کل کلاینت‌ها:</b> <code>{total_p} نفر</code>\n"
                            f"🟢 <b>کلاینت‌های فعال:</b> <code>{max(0, total_p - blocked_p)} نفر</code>\n"
                            f"🔴 <b>کلاینت‌های مسدود/منقضی:</b> <code>{blocked_p} نفر</code>\n"
                            f"📈 <b>مجموع کل مصرف ترافیک:</b> <code>{total_used_gb:.2f} گیگابایت</code>\n"
                            f"🖥 <b>سرور:</b> CPU: <code>{cpu_usage}%</code> | RAM: <code>{ram_info}</code>\n"
                            f"🕒 <b>زمان:</b> <code>{now_time}</code>"
                        )
                    else:
                        cfg = f"{auth['interface']}.conf"
                        iface = auth['interface']
                        total_p = cur.execute("SELECT COUNT(*) FROM peers WHERE config=? OR config=?", (cfg, iface)).fetchone()[0] or 0
                        blocked_p = cur.execute("SELECT COUNT(*) FROM peers WHERE (config=? OR config=?) AND (monitor_blocked=1 OR expiry_blocked=1)", (cfg, iface)).fetchone()[0] or 0
                        live_used = cur.execute("SELECT SUM(used) FROM peers WHERE config=? OR config=?", (cfg, iface)).fetchone()[0] or 0
                        
                        sub_info = cur.execute("SELECT data_limit_gb, deleted_traffic FROM sub_panels WHERE id=?", (auth["reseller_id"],)).fetchone()
                        limit_gb = float(sub_info["data_limit_gb"] or 100.0) if sub_info else 100.0
                        del_traffic = int(sub_info["deleted_traffic"] or 0) if sub_info else 0

                        vault_info = cur.execute("SELECT vault_bytes FROM interface_vault WHERE interface_name=?", (iface,)).fetchone()
                        vault_bytes = int(vault_info[0] or 0) if vault_info else 0

                        used_gb = (live_used + max(del_traffic, vault_bytes)) / (1024 * 1024 * 1024)
                        rem_gb = max(0.0, limit_gb - used_gb)

                        report = (
                            f"📊 <b>آمار پنل نمایندگی</b>\n\n"
                            f"👤 <b>نماینده:</b> {auth['username']}\n"
                            f"⚙️ <b>اینترفیس:</b> <code>{auth['interface']}</code>\n"
                            f"👥 <b>کل کلاینت‌ها:</b> <code>{total_p} نفر</code>\n"
                            f"🟢 <b>کلاینت‌های فعال:</b> <code>{max(0, total_p - blocked_p)} نفر</code>\n"
                            f"🔴 <b>کلاینت‌های مسدود/منقضی:</b> <code>{blocked_p} نفر</code>\n"
                            f"📈 <b>مجموع مصرف ترافیک:</b> <code>{used_gb:.2f} گیگابایت</code>\n"
                            f"📦 <b>ظرفیت مصرف:</b> <code>{limit_gb:.2f} گیگابایت</code>\n"
                            f"⏳ <b>باقی‌مانده:</b> <code>{rem_gb:.2f} گیگابایت</code>\n"
                            f"🖥 <b>سرور:</b> CPU: <code>{cpu_usage}%</code> | RAM: <code>{ram_info}</code>\n"
                            f"🕒 <b>زمان:</b> <code>{now_time}</code>"
                        )
                finally:
                    conn.close()

            tg_send_message(chat_id, report, get_main_reply_keyboard(), token)
            return

        # --- ➕ ساخت کاربر جدید ---
        if text == "➕ ساخت کاربر جدید":
            _user_steps[user_id] = {"step": "idle"}
            kb = {"inline_keyboard": [[{"text": "🛠 ساخت دستی", "callback_data": "create_manual"}, {"text": "📋 الگو های آماده", "callback_data": "create_template"}]]}
            tg_send_message(chat_id, "✨ نحوه ساخت کاربر را انتخاب کنید:", kb, token)
            return

        # --- 👥 مدیریت کاربران ---
        if text == "👥 مدیریت کاربران":
            _user_steps[user_id] = {"step": "idle"}
            show_users_list_tg(chat_id, user_id, 1, token=token)
            return

        # --- 🧹 بررسی غیرفعال‌ها ---
        if text == "🧹 بررسی غیرفعال‌ها":
            _user_steps[user_id] = {"step": "idle"}
            kb = {"inline_keyboard": [[{"text": "بله، کاملاً مطمئنم ✅", "callback_data": "bulk_del_inactive_yes"}, {"text": "خیر، انصراف ❌", "callback_data": "bulk_del_inactive_no"}]]}
            tg_send_message(chat_id, f"⚠️ <b>آیا مایل به حذف تمام کلاینت‌های غیرفعال/منقضی مربوط به {auth['interface'] if not auth['all_interfaces'] else 'کل پنل'} هستید؟</b>", kb, token)
            return

        state = _user_steps.get(user_id, {})
        step = state.get("step")

        # --- پردازش مراحل تعاملی (Steps) ---
        if step == "wait_search_query":
            q = text.strip()
            show_users_list_tg(chat_id, user_id, 1, search_query=q, message_id=state.get("orig_msg_id"), token=token)
            tg_delete_message(chat_id, message_id, token)
            _user_steps[user_id] = {"step": "idle"}
            return

        if step == "wait_manual_prefix":
            prefix = re.sub(r"[^a-zA-Z0-9_]", "", text)
            if not prefix:
                prefix = "user"
            state["prefix"] = prefix
            state["step"] = "wait_manual_volume"
            tg_delete_message(chat_id, message_id, token)
            if state.get("orig_msg_id"):
                tg_edit_message(chat_id, state["orig_msg_id"], f"✍️ پیشوند: <code>{prefix}</code>\n\n📊 <b>حجم اشتراک چقدر باشد؟</b> (مثلاً 50 یا 50GB):", None, token)
            return

        if step == "wait_manual_volume":
            lim_str, bytes_val, num_val = parse_volume_input_to_wg_limit(text)
            state["vol_str"] = lim_str
            state["vol_num"] = num_val
            state["step"] = "wait_manual_days"
            tg_delete_message(chat_id, message_id, token)
            if state.get("orig_msg_id"):
                tg_edit_message(chat_id, state["orig_msg_id"], f"📊 حجم: <code>{lim_str}</code>\n\n⏳ <b>مدت اعتبار چند روز باشد؟</b> (مثلاً 30):", None, token)
            return

        if step == "wait_manual_days":
            try:
                days = float(text)
            except Exception:
                days = 30.0
            state["days"] = int(round(days))
            state["step"] = "wait_manual_calc"
            tg_delete_message(chat_id, message_id, token)
            kb = {"inline_keyboard": [[{"text": "⏱ در اولین اتصال", "callback_data": "calc_first_conn"}, {"text": "⚡ همین الان", "callback_data": "calc_now"}]]}
            if state.get("orig_msg_id"):
                tg_edit_message(chat_id, state["orig_msg_id"], f"⏳ زمان: <code>{state['days']} روز</code>\n\n⚙️ <b>نحوه محاسبه زمان چگونه باشد؟</b>", kb, token)
            return

        if step == "wait_manual_bulk_count":
            try:
                count = int(text)
            except Exception:
                count = 5
            count = min(50, max(1, count))
            tg_delete_message(chat_id, message_id, token)
            if state.get("orig_msg_id"):
                tg_edit_message(chat_id, state["orig_msg_id"], f"⏳ در حال ساخت <b>{count}</b> کاربر در اینترفیس <code>{auth['interface']}</code>...", None, token)
            succ = 0
            for i in range(1, count + 1):
                email = f"{state['prefix']}_{time.time_ns()%100000}"
                first_u = (state.get("first_usage") == "calc_first_conn")
                ok_res, res_obj = create_peer_native_scoped(email, state["vol_str"], state["days"], auth, first_usage=first_u, custom_base_url=custom_base_url)
                if ok_res:
                    succ += 1
                    sub_l = get_peer_sublink_url(email, f"{auth['interface']}.conf", custom_base_url)
                    card = f"🎁 <b>کاربر شماره {i} ساخته شد!</b>\n\n👤 نام: <code>{email}</code>\n📊 حجم: <code>{state['vol_str']}</code>\n⏳ زمان: <code>{state['days']} روز</code>\n🔗 لینک ساب:\n<code>{sub_l}</code>"
                    tg_send_message(chat_id, card, {"inline_keyboard": [[{"text": "📥 استخراج کانفیگ", "callback_data": "extwg_" + str(email)}]]}, token)
            tg_send_message(chat_id, f"🏁 ساخت گروهی به پایان رسید.\n✅ موفق: <b>{succ}</b> از <b>{count}</b>", get_main_reply_keyboard(), token)
            _user_steps[user_id] = {"step": "idle"}
            return

        if step in ["wait_user_time", "wait_user_dectime"]:
            try:
                days = float(text)
            except Exception:
                days = 0.0
            p_name = state.get("target_user")
            page = state.get("page", 1)
            tg_delete_message(chat_id, message_id, token)
            if p_name and days > 0:
                diff = days if step == "wait_user_time" else -days
                target_cfg = f"{auth['interface']}.conf" if not auth["all_interfaces"] else None
                edit_peer_days_direct(p_name, diff, target_cfg)
                txt_res = f"✅ مقدار <b>{days:g} روز</b> با موفقیت {'اضافه' if diff > 0 else 'کسر'} شد."
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
                target_cfg = f"{auth['interface']}.conf" if not auth["all_interfaces"] else None
                edit_peer_volume_direct(p_name, diff, target_cfg)
                txt_res = f"✅ مقدار <b>{num_val:g} گیگابایت</b> با موفقیت {'اضافه' if diff > 0 else 'کسر'} شد."
                tg_send_message(chat_id, txt_res, token=token)
            show_detailed_user_tg(chat_id, p_name, page, message_id=state.get("orig_msg_id"), token=token)
            _user_steps[user_id] = {"step": "idle"}
            return

        if step == "wait_tpl_name":
            state["tpl_name"] = text.strip()
            state["step"] = "wait_tpl_vol"
            tg_delete_message(chat_id, message_id, token)
            if state.get("orig_msg_id"):
                tg_edit_message(chat_id, state["orig_msg_id"], f"🏷 نام الگو: <b>{text}</b>\n\n📊 <b>حجم الگو چقدر باشد؟</b> (مثلاً 50 یا 50GB):", None, token)
            return

        if step == "wait_tpl_vol":
            lim_str, bytes_val, num_val = parse_volume_input_to_wg_limit(text)
            state["vol_str"] = lim_str
            state["vol_num"] = num_val
            state["step"] = "wait_tpl_days"
            tg_delete_message(chat_id, message_id, token)
            if state.get("orig_msg_id"):
                tg_edit_message(chat_id, state["orig_msg_id"], f"📊 حجم الگو: <code>{lim_str}</code>\n\n⏳ <b>مدت زمان الگو چند روز باشد؟</b> (مثلاً 30):", None, token)
            return

        if step == "wait_tpl_days":
            try:
                days = int(text)
            except Exception:
                days = 30
            state["days"] = days
            state["step"] = "wait_tpl_calc"
            tg_delete_message(chat_id, message_id, token)
            kb = {"inline_keyboard": [[{"text": "⏱ در اولین اتصال", "callback_data": "tplcalc_first_conn"}, {"text": "⚡ همین الان", "callback_data": "tplcalc_now"}]]}
            if state.get("orig_msg_id"):
                tg_edit_message(chat_id, state["orig_msg_id"], f"⏳ زمان: <code>{days} روز</code>\n\n⚙️ <b>نحوه محاسبه زمان الگو چگونه باشد؟</b>", kb, token)
            return

        if step in ["wait_tpl_prefix_single", "wait_tpl_prefix_bulk"]:
            prefix = re.sub(r"[^a-zA-Z0-9_]", "", text)
            if not prefix:
                prefix = "user"
            qtype = "single" if "single" in step else "bulk"
            tpl_id = state.get("tpl_id")
            tg_delete_message(chat_id, message_id, token)
            if qtype == "single":
                tpl = None
                with _db_lock:
                    conn = get_db_conn()
                    cur = conn.cursor()
                    try:
                        tpl = cur.execute("SELECT * FROM templates WHERE id=?", (tpl_id,)).fetchone()
                    finally:
                        conn.close()

                if tpl:
                    email = f"{prefix}_{time.time_ns()%100000}"
                    first_u = (int(tpl["first_usage"] or 0) == 1)
                    lim_str, _, _ = parse_volume_input_to_wg_limit(tpl["vol"])
                    ok_res, res_obj = create_peer_native_scoped(email, lim_str, tpl["days"], auth, first_usage=first_u, custom_base_url=custom_base_url)
                    if ok_res:
                        sub_l = get_peer_sublink_url(email, f"{auth['interface']}.conf", custom_base_url)
                        calc_txt = "در اولین اتصال" if first_u else "همین الان"
                        card = f"✅ <b>سرویس با الگو ساخته شد!</b>\n\n📦 الگو: <b>{tpl['name']}</b>\n👤 نام: <code>{email}</code>\n📊 حجم: <code>{lim_str}</code>\n⏳ زمان: <code>{tpl['days']} روز</code>\n⏱ شروع: <code>{calc_txt}</code>\n🔗 لینک ساب:\n<code>{sub_l}</code>"
                        tg_send_message(chat_id, card, {"inline_keyboard": [[{"text": "📥 استخراج کانفیگ", "callback_data": "extwg_" + str(email)}]]}, token)
                _user_steps[user_id] = {"step": "idle"}
            else:
                state["prefix"] = prefix
                state["step"] = "wait_tpl_bulk_count"
                tg_send_message(chat_id, "🔢 تعداد اکانت‌هایی که می‌خواهید با این الگو ساخته شود را وارد کنید (مثلاً 5):", token=token)
            return

        if step == "wait_tpl_bulk_count":
            try:
                count = int(text)
            except Exception:
                count = 5
            count = min(50, max(1, count))
            tpl_id = state.get("tpl_id")
            prefix = state.get("prefix", "user")
            tg_delete_message(chat_id, message_id, token)

            tpl = None
            with _db_lock:
                conn = get_db_conn()
                cur = conn.cursor()
                try:
                    tpl = cur.execute("SELECT * FROM templates WHERE id=?", (tpl_id,)).fetchone()
                finally:
                    conn.close()

            if tpl:
                tg_send_message(chat_id, f"⏳ در حال ساخت <b>{count}</b> کاربر با الگو...", token=token)
                succ = 0
                first_u = (int(tpl["first_usage"] or 0) == 1)
                lim_str, _, _ = parse_volume_input_to_wg_limit(tpl["vol"])
                for i in range(1, count + 1):
                    email = f"{prefix}_{time.time_ns()%100000}"
                    ok_res, res_obj = create_peer_native_scoped(email, lim_str, tpl["days"], auth, first_usage=first_u, custom_base_url=custom_base_url)
                    if ok_res:
                        succ += 1
                        sub_l = get_peer_sublink_url(email, f"{auth['interface']}.conf", custom_base_url)
                        card = f"🎁 <b>کاربر شماره {i} (الگو):</b>\n👤 نام: <code>{email}</code>\n📊 حجم: <code>{lim_str}</code>\n⏳ زمان: <code>{tpl['days']} روز</code>\n🔗 لینک ساب:\n<code>{sub_l}</code>"
                        tg_send_message(chat_id, card, {"inline_keyboard": [[{"text": "📥 استخراج کانفیگ", "callback_data": "extwg_" + str(email)}]]}, token)
                tg_send_message(chat_id, f"🏁 ساخت گروهی الگو پایان یافت.\n✅ موفق: <b>{succ}</b> از <b>{count}</b>", get_main_reply_keyboard(), token)
            _user_steps[user_id] = {"step": "idle"}
            return

        # --- بخش مدیریت Callback Queryها (دکمه‌های شیشه‌ای) ---
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
                kb = {"inline_keyboard": [[{"text": "👤 تکی", "callback_data": "man_type_single"}, {"text": "👥 گروهی", "callback_data": "man_type_bulk"}]]}
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
                    email = f"{state['prefix']}_{time.time_ns()%100000}"
                    first_u = (cb_data == "calc_first_conn")
                    ok_res, res_obj = create_peer_native_scoped(email, state["vol_str"], state["days"], auth, first_usage=first_u, custom_base_url=custom_base_url)
                    if ok_res:
                        sub_l = get_peer_sublink_url(email, f"{auth['interface']}.conf", custom_base_url)
                        calc_txt = "در اولین اتصال" if first_u else "همین الان"
                        card = f"✅ <b>سرویس با موفقیت ساخته شد!</b>\n\n👤 نام: <code>{email}</code>\n📊 حجم: <code>{state['vol_str']}</code>\n⏳ زمان: <code>{state['days']} روز</code>\n⏱ شروع: <code>{calc_txt}</code>\n🔗 لینک ساب:\n<code>{sub_l}</code>"
                        tg_edit_message(chat_id, message_id, card, {"inline_keyboard": [[{"text": "📥 استخراج کانفیگ", "callback_data": "extwg_" + str(email)}]]}, token)
                    else:
                        tg_edit_message(chat_id, message_id, "❌ خطا: " + str(res_obj), None, token)
                    _user_steps[user_id] = {"step": "idle"}
                else:
                    state["step"] = "wait_manual_bulk_count"
                    tg_edit_message(chat_id, message_id, "🔢 تعداد اکانت‌هایی که می‌خواهید ساخته شود را وارد کنید (مثلاً 5):", None, token)
                return
            if cb_data == "create_template":
                show_templates_list_tg(chat_id, user_id=user_id, message_id=message_id, token=token)
                return
            if cb_data == "start_action":
                welcome = f"🤖 <b>به ربات مدیریت هوشمند وایرگارد خوش آمدید!</b>\n\n👤 نقش شما: <b>{auth['username']}</b>\n⚙️ اینترفیس: <code>{auth['interface']}</code>\n\nگزینه مورد نظر را انتخاب کنید:"
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

                with _db_lock:
                    conn = get_db_conn()
                    cur = conn.cursor()
                    try:
                        cur.execute("CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0, name TEXT NOT NULL, vol TEXT NOT NULL, days INTEGER NOT NULL, first_usage INTEGER DEFAULT 1)")
                        cur.execute("INSERT INTO templates (user_id, name, vol, days, first_usage) VALUES (?, ?, ?, ?, ?)", (auth.get("reseller_id", 0), tpl_name, vol_str, days_val, first_u))
                        conn.commit()
                    finally:
                        conn.close()

                tg_answer_callback(cb_id, f"✅ الگوی '{tpl_name}' با موفقیت ذخیره شد!", alert=True, token=token)
                _user_steps[user_id] = {"step": "idle"}
                show_templates_list_tg(chat_id, user_id=user_id, message_id=message_id, token=token)
                return
            if cb_data.startswith("tpl_view_"):
                tpl_id = int(cb_data.replace("tpl_view_", ""))
                tpl = None
                with _db_lock:
                    conn = get_db_conn()
                    cur = conn.cursor()
                    try:
                        tpl = cur.execute("SELECT * FROM templates WHERE id=?", (tpl_id,)).fetchone()
                    finally:
                        conn.close()

                if tpl:
                    calc_txt = "در اولین اتصال" if (int(tpl["first_usage"] or 0) == 1) else "همین الان"
                    msg_tpl = f"📦 <b>الگو:</b> {tpl['name']}\n📊 حجم: <code>{tpl['vol']}</code>\n⏳ زمان: <code>{tpl['days']} روز</code>\n⏱ نحوه محاسبه: <code>{calc_txt}</code>\n\nعملیات مورد نظر را انتخاب کنید:"
                    kb_tpl = [
                        [{"text": "?? ساخت ۱ کاربر تکی", "callback_data": f"tplrun_single_{tpl_id}"}, {"text": "👥 ساخت گروهی", "callback_data": f"tplrun_bulk_{tpl_id}"}],
                        [{"text": "🗑 حذف این الگو", "callback_data": f"tpldel_{tpl_id}"}],
                        [{"text": "🔙 بازگشت به لیست الگوها", "callback_data": "create_template"}]
                    ]
                    tg_edit_message(chat_id, message_id, msg_tpl, {"inline_keyboard": kb_tpl}, token)
                return
            if cb_data.startswith("tplrun_"):
                parts = cb_data.replace("tplrun_", "").split("_")
                qtype, tpl_id = parts[0], int(parts[1])
                _user_steps[user_id] = {"step": f"wait_tpl_prefix_{qtype}", "tpl_id": tpl_id, "orig_msg_id": message_id}
                tg_edit_message(chat_id, message_id, "✍️ <b>نام اشتراک (پیشوند)</b> را انگلیسی وارد کنید:", None, token)
                return
            if cb_data.startswith("tpldel_"):
                tpl_id = int(cb_data.replace("tpldel_", ""))
                with _db_lock:
                    conn = get_db_conn()
                    cur = conn.cursor()
                    try:
                        cur.execute("DELETE FROM templates WHERE id=?", (tpl_id,))
                        conn.commit()
                    finally:
                        conn.close()

                tg_answer_callback(cb_id, "🗑 الگو حذف شد.", alert=True, token=token)
                show_templates_list_tg(chat_id, user_id=user_id, message_id=message_id, token=token)
                return
            if cb_data.startswith("sendqr_"):
                p_name = cb_data.replace("sendqr_", "")
                tg_answer_callback(cb_id, "📷 در حال ساخت QR Code...", token=token)
                send_peer_qr_image_tg(chat_id, p_name, token=token, custom_base_url=custom_base_url)
                return
            if cb_data.startswith("extwg_"):
                p_name = cb_data.replace("extwg_", "")
                tg_answer_callback(cb_id, "📥 دریافت کانفیگ‌ها...", token=token)
                try:
                    target_cfg = "wg0.conf"
                    with _db_lock:
                        conn = get_db_conn()
                        cur = conn.cursor()
                        try:
                            r = cur.execute("SELECT config FROM peers WHERE peer_name=?", (p_name,)).fetchone()
                            if r and r[0]:
                                target_cfg = r[0]
                        finally:
                            conn.close()

                    # استخراج دقیق کانفیگ‌ها مطابق با صفحه ساب‌لینک
                    cfgs = get_peer_all_subscription_configs(p_name, target_cfg)
                    
                    if cfgs:
                        for c_obj in cfgs:
                            f_name = c_obj['file_name']
                            s_label = html.escape(clean_html_tags(c_obj.get('server_label', '')))
                            desc = html.escape(clean_html_tags(c_obj.get('description', '')))
                            
                            cap = f"📁 <b>نام فایل:</b> <code>{f_name}</code>\n"
                            if s_label:
                                cap += f"🏷 <b>پلن / سرور:</b> <b>{s_label}</b>\n"
                            if desc:
                                cap += f"📝 <b>توضیحات:</b> <i>{desc}</i>\n"

                            tg_send_document(chat_id, f_name, c_obj["content"], caption=cap.strip(), token=token)
                    else:
                        tg_send_message(chat_id, f"❌ امکان دریافت کانفیگ برای {p_name} وجود ندارد.", token=token)
                except Exception as e:
                    bot_write_log("Export Error: " + str(e), "ERROR")
                    tg_send_message(chat_id, "❌ خطا: " + str(e), token=token)
                return
            # --- 1. تاییدیه حذف کلاینت ---
            if cb_data.startswith("mg_act_del_"):
                raw_payload = cb_data.replace("mg_act_del_", "")
                parts = raw_payload.rsplit("_", 1)
                p_name = parts[0]
                page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                
                kb = {"inline_keyboard": [
                    [{"text": "بله، حذف شود ✅", "callback_data": f"mg_confirm_del_{p_name}_{page}"}],
                    [{"text": "خیر ❌", "callback_data": f"mg_det_{p_name}_{page}"}]
                ]}
                tg_edit_message(chat_id, message_id, f"⚠️ <b>آیا مطمئن هستید که می‌خواهید کاربر <code>{p_name}</code> را حذف کنید؟</b>", kb, token)
                return

            # --- 2. اجرای حذف قطعی کلاینت ---
            if cb_data.startswith("mg_confirm_del_"):
                raw_payload = cb_data.replace("mg_confirm_del_", "")
                parts = raw_payload.rsplit("_", 1)
                p_name = parts[0]
                page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                
                try:
                    cfg_f = "wg0.conf"
                    with _db_lock:
                        conn = get_db_conn()
                        cur = conn.cursor()
                        try:
                            r = cur.execute("SELECT public_key, peer_ip, config, used FROM peers WHERE peer_name=?", (p_name,)).fetchone()
                            if r:
                                pub_k = r["public_key"]
                                p_ip = r["peer_ip"]
                                cfg_f = r["config"] or "wg0.conf"
                                used_b = int(r["used"] or 0)
                                iface = cfg_f.replace(".conf", "")
                                
                                if used_b > 0:
                                    credit_to_vault_permanently(p_name, cfg_f)
                                    
                                if pub_k:
                                    subprocess.run(f"wg set {iface} peer {pub_k} remove", shell=True, stderr=subprocess.DEVNULL)
                                if p_ip:
                                    subprocess.run(f"ip route del blackhole {p_ip}", shell=True, stderr=subprocess.DEVNULL)
                                    
                                cur.execute("DELETE FROM peers WHERE peer_name=?", (p_name,))
                                cur.execute("DELETE FROM services WHERE email=?", (p_name,))
                                cur.execute("DELETE FROM short_links WHERE long_link LIKE ?", (f"%{p_name}%",))
                                cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=?", (p_name,))
                                conn.commit()
                                
                                reconcile_db_and_conf_files()
                                subprocess.run(f"wg-quick save {iface}", shell=True, stderr=subprocess.DEVNULL)
                                sync_action_to_edges("delete", p_name, cfg_f)
                                
                                bot_write_log(f"Peer '{p_name}' successfully deleted", "INFO")
                                tg_send_message(chat_id, f"🗑 کاربر <code>{p_name}</code> با موفقیت کامل حذف شد.", token=token)
                            else:
                                tg_send_message(chat_id, f"❌ کاربر <code>{p_name}</code> در دیتابیس یافت نشد.", token=token)
                        finally:
                            conn.close()
                except Exception as ex_del:
                    bot_write_log("Delete error: " + str(ex_del), "ERROR")
                    tg_send_message(chat_id, "❌ خطا در حذف: " + str(ex_del), token=token)
                
                show_users_list_tg(chat_id, user_id, page, message_id=message_id, token=token)
                return

            # --- 3. ریست ترافیک کلاینت ---
            if cb_data.startswith("mg_act_rstvol_"):
                raw_payload = cb_data.replace("mg_act_rstvol_", "")
                parts = raw_payload.rsplit("_", 1)
                p_name = parts[0]
                page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                
                target_cfg = "wg0.conf"
                with _db_lock:
                    conn = get_db_conn()
                    cur = conn.cursor()
                    try:
                        cur.execute("SELECT config, used, initial_duration FROM peers WHERE peer_name=?", (p_name,))
                        p_rec = cur.fetchone()
                        
                        if not p_rec:
                            tg_answer_callback(cb_id, "❌ کاربر یافت نشد یا دسترسی به آن ندارید.", alert=True, token=token)
                            return
                            
                        target_cfg = p_rec["config"] or "wg0.conf"
                        used_b = int(p_rec["used"] or 0)
                        init_d = int(p_rec["initial_duration"] or 43200)
                        if init_d <= 0: init_d = 43200
                        
                        if used_b > 0:
                            credit_to_vault_permanently(p_name, target_cfg)
                            
                        cur.execute("UPDATE peers SET local_used=0, used=0, remaining_time=?, expiry_blocked=0, monitor_blocked=0 WHERE peer_name=?", (init_d, p_name))
                        cur.execute("UPDATE peer_synced_edges SET node_used=0 WHERE peer_name=?", (p_name,))
                        conn.commit()
                    finally:
                        conn.close()
                
                sync_action_to_edges("reset", p_name, target_cfg)
                tg_answer_callback(cb_id, f"🔄 ترافیک و زمان اعتبار {p_name} ریست گردید.", alert=True, token=token)
                show_detailed_user_tg(chat_id, p_name, page, message_id=message_id, token=token)
                return

            # --- 4. سایر اکشن‌ها (تغییر وضعیت، زمان، حجم) ---
            if cb_data.startswith("mg_act_"):
                raw_act = cb_data.replace("mg_act_", "")
                action = None
                for act_prefix in ["dectime_", "decvol_", "toggle_", "time_", "vol_"]:
                    if raw_act.startswith(act_prefix):
                        action = act_prefix.rstrip("_")
                        rem_str = raw_act[len(act_prefix):]
                        parts = rem_str.rsplit("_", 1)
                        p_name = parts[0]
                        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                        break
                
                if action == "toggle":
                    target_cfg = f"{auth['interface']}.conf" if not auth["all_interfaces"] else None
                    ok_res, st_msg = toggle_peer_direct(p_name, target_cfg)
                    show_detailed_user_tg(chat_id, p_name, page, message_id=message_id, token=token)
                    return
                if action in ["time", "dectime", "vol", "decvol"]:
                    _user_steps[user_id] = {"step": "wait_user_" + str(action), "target_user": p_name, "page": page, "orig_msg_id": message_id}
                    txt_lbl = "زمان (به روز)" if "time" in action else "حجم (به گیگابایت)"
                    tg_edit_message(chat_id, message_id, f"✍️ مقدار <b>{txt_lbl}</b> مورد نظر برای <code>{p_name}</code> را ارسال کنید:\n(مثلاً 5 برای روز یا 2 برای گیگابایت)", None, token)
                    return

            if cb_data == "bulk_del_inactive_yes":
                tg_answer_callback(cb_id, "⏳ در حال پاکسازی امن و یکپارچه...", token=token)
                
                deleted_peers_info = []
                del_count = 0
                target_ifaces_to_save = set()

                # ۱. واکشی امن، محاسبه و حذف مستقیم درون دیتابیس بدون قفل تودرتو
                with _db_lock:
                    conn = get_db_conn()
                    cur = conn.cursor()
                    try:
                        if auth["all_interfaces"]:
                            cur.execute("""
                                SELECT peer_name, public_key, peer_ip, config, used, [limit], remaining_time, 
                                       monitor_blocked, expiry_blocked, first_usage, token 
                                FROM peers
                            """)
                        else:
                            cfg = f"{auth['interface']}.conf"
                            cur.execute("""
                                SELECT peer_name, public_key, peer_ip, config, used, [limit], remaining_time, 
                                       monitor_blocked, expiry_blocked, first_usage, token 
                                FROM peers WHERE config=? OR config=?
                            """, (cfg, auth['interface']))

                        all_rows = [dict(r) for r in cur.fetchall()]

                        for p in all_rows:
                            p_name = p["peer_name"]
                            pub_k = p.get("public_key")
                            p_ip = p.get("peer_ip")
                            p_cfg = p.get("config") or "wg0.conf"
                            p_iface = p_cfg.replace(".conf", "")
                            used_b = int(p.get("used") or 0)
                            rem_t = int(p.get("remaining_time") or 0)
                            tok = p.get("token")
                            
                            try:
                                lim_b = convert_to_bytes(p.get("limit") or "0GiB")
                            except Exception:
                                lim_b = 0

                            # 🛡️ محافظت از کاربران در انتظار اولین اتصال
                            f_raw = str(p.get("first_usage", "0")).strip().lower()
                            is_wait = (f_raw in ["1", "true", "yes", "on", "calc_first_conn"]) and (used_b <= 1024) and (rem_t > 0)

                            is_expired = (
                                not is_wait and (
                                    (rem_t <= 0) or 
                                    (lim_b > 0 and used_b >= lim_b) or 
                                    bool(p.get("monitor_blocked") or p.get("expiry_blocked"))
                                )
                            )

                            if is_expired:
                                # واریز ترافیک مصرفی به صندوق برای حفظ آمار سرور
                                if used_b > 0:
                                    if p_iface == "wg0":
                                        cur.execute("UPDATE global_deleted_traffic SET total = total + ? WHERE id=1", (used_b,))
                                    else:
                                        cur.execute("UPDATE sub_panels SET deleted_traffic = deleted_traffic + ? WHERE interface_name=?", (used_b, p_iface))
                                    cur.execute("""
                                        INSERT INTO interface_vault (interface_name, vault_bytes) 
                                        VALUES (?, ?) 
                                        ON CONFLICT(interface_name) DO UPDATE SET vault_bytes = vault_bytes + excluded.vault_bytes
                                    """, (p_iface, used_b))

                                # حذف قطعی رکوردهای کلاینت
                                cur.execute("DELETE FROM peers WHERE peer_name=?", (p_name,))
                                cur.execute("DELETE FROM services WHERE email=?", (p_name,))
                                if tok:
                                    cur.execute("DELETE FROM short_links WHERE short_id=? OR short_id=?", (tok, tok[:8]))
                                cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=?", (p_name,))

                                deleted_peers_info.append({
                                    "name": p_name,
                                    "pub": pub_k,
                                    "ip": p_ip,
                                    "iface": p_iface,
                                    "config": p_cfg
                                })
                                target_ifaces_to_save.add(p_iface)
                                del_count += 1

                        conn.commit()
                    finally:
                        conn.close()

                # ۲. اعمال تغییرات در کرنل مستر پس از بستن دیتابیس
                for dp in deleted_peers_info:
                    if dp["pub"]:
                        subprocess.run(f"wg set {dp['iface']} peer {dp['pub']} remove", shell=True, stderr=subprocess.DEVNULL)
                    if dp["ip"]:
                        subprocess.run(f"ip route del blackhole {dp['ip']}", shell=True, stderr=subprocess.DEVNULL)

                # ۳. ذخیره‌سازی کانفیگ‌ها فقط ۱ بار برای هر کارت شبکه
                for if_save in target_ifaces_to_save:
                    subprocess.run(f"wg-quick save {if_save}", shell=True, stderr=subprocess.DEVNULL)

                # ۴. همگام‌سازی ناهمگام با نودهای کلاستر و سرور SSH
                for dp in deleted_peers_info:
                    try:
                        sync_action_to_edges("delete", dp["name"], dp["config"])
                    except Exception:
                        pass

                iface_label = f"کارت {auth['interface']}" if not auth["all_interfaces"] else "کل پنل"
                msg_res = f"✅ <b>پاکسازی ریشه‌ای با موفقیت انجام شد!</b>\n\nتعداد <b>{del_count}</b> کلاینت غیرفعال، منقضی و اتمام‌حجم از {iface_label} با موفقیت حذف شدند."
                tg_edit_message(chat_id, message_id, msg_res, None, token)
                return

            if cb_data == "bulk_del_inactive_no":
                tg_edit_message(chat_id, message_id, "☑️ عملیات پاکسازی لغو شد.", None, token)
                return

    except Exception as e:
        err_str = str(e)
        tb_str = traceback.format_exc()
        bot_write_log(f"Bot Update Handler Exception: {err_str}\n{tb_str}", "ERROR")
        tg_send_message(chat_id, f"❌ خطایی در پردازش رخ داد:\n<code>{html.escape(err_str)}</code>", token=token)


def _poll_single_token(token):
    offset = 0
    while _bot_worker_running:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=5"
            req = urllib.request.Request(url, headers={"User-Agent": "WGPanelBot/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        threading.Thread(target=process_telegram_update, args=(update, token), daemon=True).start()
        except Exception:
            time.sleep(2)
        time.sleep(0.5)

def start_bot_polling_daemon():
    global _bot_worker_running, _active_polling_threads
    if _bot_worker_running:
        return
    _bot_worker_running = True

    def master_supervisor():
        time.sleep(1)
        while _bot_worker_running:
            try:
                from sqlite_backend import get_server_role
                if get_server_role() == "master":
                    tokens = get_all_active_bot_tokens()
                    for tok in tokens:
                        if tok not in _active_polling_threads or not _active_polling_threads[tok].is_alive():
                            t = threading.Thread(target=_poll_single_token, args=(tok,), daemon=True)
                            _active_polling_threads[tok] = t
                            t.start()
                else:
                    # روی نود پولینگ ربات متوقف می‌شود
                    _active_polling_threads.clear()
            except Exception:
                pass
            time.sleep(10)

    threading.Thread(target=master_supervisor, daemon=True).start()

def stop_bot_polling_daemon():
    global _bot_worker_running, _active_polling_threads
    _bot_worker_running = False
    _active_polling_threads.clear()

if get_bot_status_str() == "on":
    start_bot_polling_daemon()

def check_and_send_reseller_alerts():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(sub_panels)")
        cols = [c[1] for c in cur.fetchall()]
        has_tg_chat = "telegram_chat_id" in cols
        has_alert_cols = "alert_80_sent" in cols and "alert_100_sent" in cols

        resellers = [dict(r) for r in cur.execute("SELECT * FROM sub_panels").fetchall()]
        admin_chat = get_bot_admin_chat_id()
        default_bot_token = get_bot_active_token()

        for r in resellers:
            iface = r["interface_name"]
            uname = r["username"]
            limit_gb = float(r.get("data_limit_gb") or 0)
            status = r.get("status", "active")
            del_traf = int(r.get("deleted_traffic") or 0)
            
            used_b = cur.execute("SELECT SUM(used) FROM peers WHERE config=? OR config=?", (iface + ".conf", iface)).fetchone()[0] or 0
            total_used_b = del_traf + used_b
            used_gb = total_used_b / (1024 * 1024 * 1024)

            reseller_chat = r.get("telegram_chat_id") if has_tg_chat else None
            reseller_tok = (r.get("telegram_bot_token") if has_tg_chat and r.get("telegram_bot_token") else None) or default_bot_token

            alert_80_sent = int(r.get("alert_80_sent") or 0) if has_alert_cols else 0
            alert_100_sent = int(r.get("alert_100_sent") or 0) if has_alert_cols else 0

            if limit_gb > 0:
                usage_ratio = used_gb / limit_gb
                
                if usage_ratio >= 0.80 and usage_ratio < 1.0 and not alert_80_sent:
                    warn_msg = f"⚠️ <b>هشدار مصرف ۸۰٪ سقف ترافیک ({iface}):</b>\n\nنماینده گرامی <code>{uname}</code>، مصرف ترافیک اینترفیس شما از ۸۰٪ عبور کرد.\n📊 مصرف: <code>{used_gb:.2f} GB</code> از <code>{limit_gb} GB</code>"
                    if reseller_chat and reseller_tok:
                        tg_send_message(reseller_chat, warn_msg, token=reseller_tok)
                    if admin_chat and default_bot_token and admin_chat != reseller_chat:
                        tg_send_message(admin_chat, f"⚠️ <b>اخطار مصرف ۸۰٪ نماینده ({uname} - {iface}):</b>\nمصرف: {used_gb:.2f}GB / {limit_gb}GB", token=default_bot_token)
                    
                    if has_alert_cols:
                        cur.execute("UPDATE sub_panels SET alert_80_sent=1 WHERE id=?", (r["id"],))

                elif (usage_ratio >= 1.0 or status != "active") and not alert_100_sent:
                    stop_msg = f"🚨 <b>اخطار قطع سرویس و تعلیق ترافیک ({iface}):</b>\n\nاینترفیس <code>{iface}</code> متعلق به <code>{uname}</code> به علت اتمام حجم سقف ترافیک مسدود و متوقف گردید."
                    if reseller_chat and reseller_tok:
                        tg_send_message(reseller_chat, stop_msg, token=reseller_tok)
                    if admin_chat and default_bot_token and admin_chat != reseller_chat:
                        tg_send_message(admin_chat, stop_msg, token=default_bot_token)
                    
                    if has_alert_cols:
                        cur.execute("UPDATE sub_panels SET alert_100_sent=1 WHERE id=?", (r["id"],))

                elif usage_ratio < 0.80 and has_alert_cols and (alert_80_sent or alert_100_sent):
                    cur.execute("UPDATE sub_panels SET alert_80_sent=0, alert_100_sent=0 WHERE id=?", (r["id"],))

        conn.commit()
        conn.close()
    except Exception:
        pass

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
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception:
        pass

def run_accurate_time_countdown():
    # 📌 شمارش معکوس زمان فقط روی مستر انجام می‌شود
    try:
        from sqlite_backend import get_server_role
        if get_server_role() == "node":
            return
    except Exception:
        pass
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, peer_name, config, remaining_time, first_usage, used, peer_ip, public_key "
            "FROM peers WHERE monitor_blocked=0 AND expiry_blocked=0"
        )
        active_peers = [dict(r) for r in cur.fetchall()]

        for p in active_peers:
            pid = p["id"]
            p_name = p["peer_name"]
            cfg = p.get("config", "wg0.conf")
            rem = int(p.get("remaining_time") or 0)
            used_b = int(p.get("used") or 0)
            
            f_raw = str(p.get("first_usage", "0")).strip().lower()
            # وضعیت انتظار: تیک اتصال اول فعال است (1 / true)
            is_first_u = (f_raw in ["1", "true", "yes", "on", "calc_first_conn"])
            has_traffic = (used_b > 1024)

            # ۱. اگر در انتظار اتصال است و هنوز ترافیکی رد و بدل نکرده -> از زمان کم نمی‌شود
            if is_first_u and not has_traffic:
                continue

            # ۲. اگر در انتظار اتصال بود ولی ترافیک ارسال کرد -> تیک اتصال اول به پایان می‌رسد
            if is_first_u and has_traffic:
                cur.execute("UPDATE peers SET first_usage=0 WHERE id=?", (pid,))
                is_first_u = False

            # ۳. کسر ۱ دقیقه برای کلاینت فعال
            new_rem = max(0, rem - 1)
            if new_rem <= 0:
                cur.execute("UPDATE peers SET remaining_time=0, monitor_blocked=1, expiry_blocked=1 WHERE id=?", (pid,))
                if p.get("peer_ip"):
                    subprocess.run(f"ip route add blackhole {p['peer_ip']}", shell=True, stderr=subprocess.DEVNULL)
                if p.get("public_key"):
                    iface = cfg.replace(".conf", "") if str(cfg).endswith(".conf") else str(cfg)
                    subprocess.run(f"wg set {iface} peer {p['public_key']} remove", shell=True, stderr=subprocess.DEVNULL)
                sync_action_to_edges("toggle", p_name, cfg, {"blocked": True})
            else:
                cur.execute("UPDATE peers SET remaining_time=? WHERE id=?", (new_rem, pid))

        conn.commit()
        conn.close()
    except Exception as ex_t:
        bot_write_log("Countdown worker notice: " + str(ex_t), "ERROR")

def start_time_worker_loop():
    global _time_worker_running
    if _time_worker_running:
        return
    _time_worker_running = True
    def loop():
        time.sleep(5)
        while True:
            run_accurate_time_countdown()
            time.sleep(60)
    threading.Thread(target=loop, daemon=True).start()

start_time_worker_loop()

# -------------------------------------------------------------------------
# 🔗 بایندینگ ایمن هوک‌های وب‌سرور فلاسک
# -------------------------------------------------------------------------
def bind_v100_hooks(app_instance):
    globals()["sync_single_peer_action_to_edges"] = sync_action_to_edges
    globals()["credit_to_vault_permanently"] = credit_to_vault_permanently
    globals()["reconcile_db_and_conf_files"] = reconcile_db_and_conf_files
    try:
        if "short_redirect" in app_instance.view_functions:
            app_instance.view_functions["short_redirect"] = universal_sublink_renderer
        if "short_download_config" in app_instance.view_functions:
            app_instance.view_functions["short_download_config"] = short_download_config_native
    except Exception:
        pass

_sync_job_status = {
    "running": False,
    "progress": 0,
    "logs": [],
    "last_result": None
}
_sync_job_lock = threading.Lock()

def get_sync_progress_status():
    with _sync_job_lock:
        return dict(_sync_job_status)

def start_master_sync_job():
    with _sync_job_lock:
        if _sync_job_status["running"]:
            return False, "عملیات همگام‌سازی در حال حاضر در حال اجرا است."
        _sync_job_status["running"] = True
        _sync_job_status["progress"] = 5
        _sync_job_status["logs"] = ["🚀 فرآیند همگام‌سازی کلان آغاز شد..."]
        _sync_job_status["last_result"] = None

    threading.Thread(target=_run_full_cluster_sync_worker, daemon=True).start()
    return True, "عملیات همگام‌سازی کلان آغاز شد."

def _run_full_cluster_sync_worker():
    global _sync_job_status
    
    def log(msg):
        with _sync_job_lock:
            _sync_job_status["logs"].append(msg)
            if len(_sync_job_status["logs"]) > 100:
                _sync_job_status["logs"] = _sync_job_status["logs"][-100:]

    try:
        log("🔍 گام ۱: واکشی یکپارچه کلاینت‌ها و صندوق ترافیک از Master...")
        with _db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, server_ip, ssh_ip, ssh_port, ssh_user, ssh_pass, server_name FROM edge_servers")
            edges = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT interface_name, username, password_hash, password_plain, data_limit_gb, port, status, disabled_at, deleted_traffic FROM sub_panels")
            master_resellers = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT peer_name, peer_ip, public_key, private_key, [limit], used, remaining, remaining_time, 
                       config, first_usage, expiry_blocked, monitor_blocked, dns, mtu, persistent_keepalive, allowed_ips
                FROM peers WHERE public_key IS NOT NULL AND public_key != ''
            """)
            master_peers = [dict(r) for r in cur.fetchall()]

            cur.execute("CREATE TABLE IF NOT EXISTS global_deleted_traffic (id INTEGER PRIMARY KEY, total INTEGER DEFAULT 0)")
            row_g = cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1").fetchone()
            master_global_deleted = int(row_g[0] or 0) if row_g else 0

            cur.execute("CREATE TABLE IF NOT EXISTS interface_vault (interface_name TEXT PRIMARY KEY, vault_bytes INTEGER DEFAULT 0)")
            master_vaults = {r[0]: int(r[1] or 0) for r in cur.execute("SELECT interface_name, vault_bytes FROM interface_vault").fetchall()}
            conn.close()

        if not edges:
            log("⚠️ هیچ نودی در مستر ثبت نشده است.")
            with _sync_job_lock:
                _sync_job_status["running"] = False
                _sync_job_status["progress"] = 100
            return

        with _sync_job_lock:
            _sync_job_status["progress"] = 25

        total_edges = len(edges)
        log(f"?? پکیج کلان شامل {len(master_peers)} کلاینت آماده ارسال به {total_edges} نود است.")

        payload_data = {
            "master_global_deleted": master_global_deleted,
            "master_vaults": master_vaults,
            "resellers": master_resellers,
            "peers": master_peers
        }
        
        local_p_file = "/tmp/cluster_payload.json"
        with open(local_p_file, "w", encoding="utf-8") as f:
            json.dump(payload_data, f, ensure_ascii=False)

        # 📌 اسکریپت رسیور نود: بدون حذف کردن جدول peers (استفاده از ON CONFLICT جهت حفظ پایداری و حجم زنده)
        node_receiver_py = '''# -*- coding: utf-8 -*-
import sqlite3, subprocess, os, json, re, sys

payload_path = "/tmp/cluster_payload.json"
if not os.path.exists(payload_path):
    print("ERROR_PAYLOAD_MISSING")
    sys.exit(1)

with open(payload_path, "r", encoding="utf-8") as pf:
    data = json.load(pf)

db_p = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
os.makedirs(os.path.dirname(db_p), exist_ok=True)

conn = sqlite3.connect(db_p, timeout=60.0)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ساخت جداول در صورت عدم وجود
cur.execute("""CREATE TABLE IF NOT EXISTS peers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, peer_name TEXT, peer_ip TEXT, public_key TEXT UNIQUE,
    [limit] TEXT, used INTEGER DEFAULT 0, remaining INTEGER DEFAULT 0, config TEXT DEFAULT 'wg0.conf',
    expiry_time_json TEXT DEFAULT '{}', first_usage INTEGER DEFAULT 0, expiry_blocked INTEGER DEFAULT 0,
    monitor_blocked INTEGER DEFAULT 0, last_received_bytes INTEGER DEFAULT 0, last_sent_bytes INTEGER DEFAULT 0,
    remaining_time INTEGER DEFAULT 0, private_key TEXT, dns TEXT DEFAULT '1.1.1.1', mtu INTEGER DEFAULT 1280,
    persistent_keepalive INTEGER DEFAULT 25, allowed_ips TEXT DEFAULT '0.0.0.0/0, ::/0', token TEXT,
    created_at_gregorian TEXT, created_at_jalali TEXT, first_connected_gregorian TEXT, first_connected_jalali TEXT,
    local_used INTEGER DEFAULT 0, initial_duration INTEGER DEFAULT 0, created_at INTEGER
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS sub_panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT, interface_name TEXT UNIQUE, username TEXT UNIQUE,
    password_hash TEXT, data_limit_gb REAL, port INTEGER, created_at TEXT, status TEXT,
    disabled_at TEXT, password_plain TEXT, deleted_traffic INTEGER DEFAULT 0
)""")
cur.execute("CREATE TABLE IF NOT EXISTS global_deleted_traffic (id INTEGER PRIMARY KEY, total INTEGER DEFAULT 0)")
cur.execute("CREATE TABLE IF NOT EXISTS interface_vault (interface_name TEXT PRIMARY KEY, vault_bytes INTEGER DEFAULT 0)")

cur.execute("INSERT OR REPLACE INTO global_deleted_traffic (id, total) VALUES (1, ?)", (data.get("master_global_deleted", 0),))
for iv_n, iv_b in data.get("master_vaults", {}).items():
    cur.execute("INSERT OR REPLACE INTO interface_vault (interface_name, vault_bytes) VALUES (?, ?)", (iv_n, iv_b))

master_resellers = data.get("resellers", [])
master_ifaces = set(r["interface_name"] for r in master_resellers)
master_ifaces.add("wg0")

for r in master_resellers:
    iface = r["interface_name"]
    cfg = f"{iface}.conf"
    conf_path = f"/etc/wireguard/{cfg}"
    m_num = re.search(r'\\d+', iface)
    num = int(m_num.group(0)) if m_num else 1
    target_subnet = f"10.{num}.0.1/16"
    target_port = int(r.get("port") or (51820 + num))
    status = r.get("status") or "active"

    if not os.path.exists(conf_path):
        priv = subprocess.getoutput("wg genkey").strip()
        nic = subprocess.getoutput("ip route | grep default | awk '{print $5}' | head -n1").strip() or "eth0"
        with open(conf_path, "w", encoding="utf-8") as f:
            f.write(f"[Interface]\\nPrivateKey = {priv}\\nListenPort = {target_port}\\nAddress = {target_subnet}\\nSaveConfig = false\\nPostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -t nat -A POSTROUTING -o {nic} -j MASQUERADE\\nPostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -t nat -D POSTROUTING -o {nic} -j MASQUERADE\\n")

    cur.execute("""
        INSERT INTO sub_panels (interface_name, username, password_hash, password_plain, data_limit_gb, port, status, disabled_at, deleted_traffic)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(interface_name) DO UPDATE SET
            username=excluded.username,
            password_hash=excluded.password_hash,
            password_plain=excluded.password_plain,
            data_limit_gb=excluded.data_limit_gb,
            port=excluded.port,
            status=excluded.status,
            disabled_at=excluded.disabled_at,
            deleted_traffic=excluded.deleted_traffic
    """, (iface, r["username"], r["password_hash"], r["password_plain"], float(r.get("data_limit_gb") or 100), target_port, status, r.get("disabled_at"), int(r.get("deleted_traffic") or 0)))

# 📌 درج و بروزرسانی کلاینت‌ها در نود با حفظ ساختار و عدم حذف ناگهانی جدول
master_peers = data.get("peers", [])
master_peer_pubs = set()

for mp in master_peers:
    pub = mp.get("public_key")
    if not pub: continue
    master_peer_pubs.add(pub)
    cfg = mp.get("config") or "wg0.conf"
    if not cfg.endswith(".conf"): cfg += ".conf"
    
    cur.execute("""
        INSERT INTO peers (
            peer_name, peer_ip, public_key, private_key, [limit], used, remaining, remaining_time,
            config, first_usage, expiry_blocked, monitor_blocked, dns, mtu, persistent_keepalive, allowed_ips
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(public_key) DO UPDATE SET
            peer_name=excluded.peer_name,
            peer_ip=excluded.peer_ip,
            private_key=excluded.private_key,
            [limit]=excluded.[limit],
            used=excluded.used,
            remaining=excluded.remaining,
            remaining_time=excluded.remaining_time,
            config=excluded.config,
            first_usage=excluded.first_usage,
            expiry_blocked=excluded.expiry_blocked,
            monitor_blocked=excluded.monitor_blocked,
            dns=excluded.dns,
            mtu=excluded.mtu,
            persistent_keepalive=excluded.persistent_keepalive,
            allowed_ips=excluded.allowed_ips
    """, (
        mp["peer_name"], mp.get("peer_ip", "10.0.0.2"), pub, mp.get("private_key", ""),
        mp.get("limit", "50GiB"), int(mp.get("used") or 0), int(mp.get("remaining") or 0),
        int(mp.get("remaining_time") or 0), cfg, 1 if mp.get("first_usage") else 0,
        int(mp.get("expiry_blocked") or 0), int(mp.get("monitor_blocked") or 0),
        mp.get("dns", "1.1.1.1"), int(mp.get("mtu") or 1420), int(mp.get("persistent_keepalive") or 25),
        mp.get("allowed_ips", "0.0.0.0/0, ::/0")
    ))

# حذف کلاینت‌هایی که دیگر در مستر وجود ندارند
if master_peer_pubs:
    placeholders = ', '.join(['?'] * len(master_peer_pubs))
    cur.execute(f"DELETE FROM peers WHERE public_key NOT IN ({placeholders})", list(master_peer_pubs))

conn.commit()
conn.close()

# به‌روزرسانی فایل‌های کانفیگ وایرگارد در نود
for if_n in master_ifaces:
    conf_path = f"/etc/wireguard/{if_n}.conf"
    if not os.path.exists(conf_path): continue
    header = open(conf_path, "r", encoding="utf-8", errors="ignore").read().split("[Peer]")[0].strip()
    active_peers = [p for p in master_peers if (p.get("config") == f"{if_n}.conf" or p.get("config") == if_n) and not (p.get("monitor_blocked") or p.get("expiry_blocked"))]
    peer_blocks = []
    for p in active_peers:
        pub = p.get("public_key")
        pip = p.get("peer_ip")
        keep = p.get("persistent_keepalive", 25)
        pname = p.get("peer_name", "User")
        if pub and pip:
            peer_blocks.append(f"\\n[Peer]\\n# {pname}\\nPublicKey = {pub}\\nAllowedIPs = {pip}/32\\nPersistentKeepalive = {keep}")
    with open(conf_path, "w", encoding="utf-8") as f:
        f.write(header + "\\n" + "".join(peer_blocks) + "\\n")
    subprocess.run(f"wg-quick save {if_n} 2>/dev/null", shell=True)

if os.path.exists(payload_path):
    os.remove(payload_path)

print(f"NODE_INGEST_SUCCESS|{len(master_peers)}")
'''
        local_r_file = "/tmp/node_sync_receiver.py"
        with open(local_r_file, "w", encoding="utf-8") as f:
            f.write(node_receiver_py)

        # ارسال به تک‌تک سرورهای لبه و آپدیت پایدار مستر بدون حذف سابقه مصرف
        for idx, edge in enumerate(edges):
            srv_ip = edge["server_ip"]
            s_ip = edge["ssh_ip"]
            s_port = edge["ssh_port"] or 22
            s_user = edge["ssh_user"] or "root"
            s_pass = edge["ssh_pass"]
            s_name = edge.get("server_name") or srv_ip

            log(f"⚡ انتقال پرسرعت SCP به نود {s_name} ({s_ip})...")
            scp_cmd = f"sshpass -p '{s_pass}' scp -P {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=8 {local_p_file} {local_r_file} {s_user}@{s_ip}:/tmp/"
            subprocess.run(scp_cmd, shell=True, check=True)

            exec_cmd = f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no -o ConnectTimeout=8 {s_user}@{s_ip} '/usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/node_sync_receiver.py; rm -f /tmp/node_sync_receiver.py'"
            res = subprocess.run(exec_cmd, shell=True, capture_output=True, text=True, timeout=50)

            if res.returncode == 0 and "NODE_INGEST_SUCCESS|" in res.stdout:
                c_count = res.stdout.split("NODE_INGEST_SUCCESS|")[1].strip()
                with _db_lock:
                    conn = get_db_conn()
                    cur = conn.cursor()
                    
                    # 📌 کلید اصلی: عدم استفاده از DELETE FROM peer_synced_edges جهت حفظ node_used و last_bytes
                    master_peer_names = set()
                    for p in master_peers:
                        p_name = p["peer_name"]
                        master_peer_names.add(p_name)
                        cur.execute("""
                            INSERT INTO peer_synced_edges (peer_name, server_ip, config, edge_ip, edge_priv_key, edge_pub_key)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(peer_name, server_ip, config) DO UPDATE SET
                                edge_ip = excluded.edge_ip,
                                edge_priv_key = excluded.edge_priv_key,
                                edge_pub_key = excluded.edge_pub_key
                        """, (p_name, srv_ip, p.get("config", "wg0.conf"), p.get("peer_ip"), p.get("private_key"), p.get("public_key")))

                    # فقط رکوردهایی که کلاً از مستر پاک شده‌اند از این نود حذف شوند
                    if master_peer_names:
                        placeholders = ', '.join(['?'] * len(master_peer_names))
                        cur.execute(f"DELETE FROM peer_synced_edges WHERE server_ip = ? AND peer_name NOT IN ({placeholders})", [srv_ip] + list(master_peer_names))

                    conn.commit()
                    conn.close()

                log(f"✅ نود {s_name} با موفقیت کامل همگام شد (تعداد {c_count} کلاینت تأیید شدند).")
            else:
                log(f"❌ خطا در سینک نود {s_name}: {res.stderr.strip()[:100]}")

        if os.path.exists(local_p_file): os.remove(local_p_file)
        if os.path.exists(local_r_file): os.remove(local_r_file)

        log("🎉 همگام‌سازی کلان به پایان رسید. تمام کلاینت‌ها با حفظ کامل ترافیک و بدون تایم‌اوت مستقر شدند.")
        with _sync_job_lock:
            _sync_job_status["progress"] = 100
            _sync_job_status["running"] = False
            _sync_job_status["last_result"] = "completed"

    except Exception as e:
        log(f"❌ خطای غیرمنتظره: {e}")
        with _sync_job_lock:
            _sync_job_status["running"] = False
            _sync_job_status["progress"] = 100
