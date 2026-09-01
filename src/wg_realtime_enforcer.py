#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
=============================================================================
🛡️ WireGuard Real-Time Universal Cluster & Leak Enforcer Daemon
-----------------------------------------------------------------------------
پایش بلادرنگ (Real-Time)، مسدودسازی قطعی در لحظه انقضا در کارت‌های کلاینتی
و احیای خودکار کلاینت‌های شارژ شده (بدون هرگونه تداخل با تانل‌های پروکسی).
=============================================================================
"""

import os
import sys
import time
import sqlite3
import subprocess
import re
import json

# مسیرهای استاندارد پایگاه‌داده
DB_CANDIDATES = [
    "/usr/local/bin/Wireguard-panel/src/db.sqlite3",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.sqlite3"),
    "/etc/wireguard/db.sqlite3"
]

def get_resolved_db_path():
    for p in DB_CANDIDATES:
        if os.path.exists(p):
            return p
    return DB_CANDIDATES[0]

def parse_bytes(val):
    """تبدیل رشته‌های حجم (مانند 50GiB, 100MiB, 1.5GB) به بایت دقیق"""
    if not val:
        return 0
    s = str(val).strip().upper()
    m = re.match(r"^([0-9\.]+)\s*(T|TB|TIB|G|GB|GIB|M|MB|MIB|K|KB|KIB|B)?$", s)
    if not m:
        return 0
    try:
        size = float(m.group(1))
    except ValueError:
        return 0
    unit = m.group(2) or "GIB"
    mapping = {
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
        "T": 1024**4,
        "TB": 1024**4
    }
    return int(size * mapping.get(unit, 1024**3))

def get_safe_client_interfaces():
    """استخراج تمام کارت‌های شبکه فعال کلاینتی و فیلتر کردن کارت‌های تانل پروکسی"""
    safe_list = []
    try:
        raw_ifs = subprocess.getoutput("wg show interfaces 2>/dev/null").split()
        for iface in raw_ifs:
            clean = iface.strip()
            # فیلتر کردن کارت‌های تانل خروجی پروکسی و وارپ
            if clean.startswith("tun_") or clean == "proxy" or clean == "wgcf":
                continue
            # فقط اینترفیس‌های کلاینتی: wg0..wg99 و adv10..adv99
            if re.match(r"^wg\d+$", clean) or re.match(r"^adv\d+$", clean):
                safe_list.append(clean)
    except Exception:
        pass
    if "wg0" not in safe_list:
        safe_list.append("wg0")
    return list(set(safe_list))

def get_ssh_node_cfg(db_path):
    """استعلام مشخصات اتصال به سرور ریموت SSH پیشرفته"""
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT server_ip, server_port, server_user, server_pass 
            FROM advanced_ssh_settings 
            WHERE mode='ssh' LIMIT 1
        """)
        row = cur.fetchone()
        conn.close()
        if row and row["server_ip"] and row["server_pass"]:
            return dict(row)
    except Exception:
        pass
    return None

def enforce_sync_cycle(last_expired_set):
    """یک چرخه کامل بررسی وضعیت، مسدودسازی محلی و همگام‌سازی نود SSH"""
    db_path = get_resolved_db_path()
    if not os.path.exists(db_path):
        return last_expired_set

    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT peer_name, peer_ip, public_key, config, [limit], used, 
                   remaining_time, monitor_blocked, expiry_blocked, first_usage 
            FROM peers 
            WHERE public_key IS NOT NULL AND public_key != ''
        """)
        peers = [dict(r) for r in cur.fetchall()]

        current_expired = {}
        current_active = {}

        for p in peers:
            pub = p["public_key"].strip()
            pip = (p.get("peer_ip") or "").strip().split("/")[0]
            rem_t = int(p.get("remaining_time") or 0)
            used_b = int(p.get("used") or 0)
            lim_b = parse_bytes(p.get("limit"))
            m_blk = int(p.get("monitor_blocked") or 0)
            e_blk = int(p.get("expiry_blocked") or 0)

            # بررسی کلاینت در انتظار اولین اتصال
            f_raw = str(p.get("first_usage", "0")).strip().lower()
            is_waiting_first = (f_raw in ["1", "true", "yes", "on", "calc_first_conn"]) and (used_b <= 1024) and (rem_t > 0)

            # شرط انقضا: اتمام زمان، اتمام حجم یا مسدودی در پنل
            is_expired = not is_waiting_first and (
                (rem_t <= 0) or 
                (lim_b > 0 and used_b >= lim_b) or 
                bool(m_blk or e_blk)
            )

            if is_expired:
                current_expired[pub] = {"name": p["peer_name"], "ip": pip}
                if not (m_blk and e_blk):
                    cur.execute("UPDATE peers SET monitor_blocked=1, expiry_blocked=1 WHERE public_key=?", (pub,))
            else:
                cfg = (p.get("config") or "wg0.conf").replace(".conf", "")
                current_active[pub] = {"name": p["peer_name"], "ip": pip, "iface": cfg}
                if m_blk or e_blk:
                    cur.execute("UPDATE peers SET monitor_blocked=0, expiry_blocked=0 WHERE public_key=?", (pub,))

        conn.commit()
        conn.close()

        # ۱. استخراج کارت‌های فقط کلاینتی (حفاظت از کارت‌های تانل پروکسی)
        client_ifs = get_safe_client_interfaces()

        current_expired_set = set(current_expired.keys())
        newly_expired_pubs = current_expired_set - last_expired_set
        restored_pubs = last_expired_set - current_expired_set

        # مسدودسازی محلی فقط برای کلاینت‌هایی که تازه منقضی شدند
        for pub in newly_expired_pubs:
            info = current_expired[pub]
            for iface in client_ifs:
                subprocess.run(["wg", "set", iface, "peer", pub, "remove"], stderr=subprocess.DEVNULL)
            if info["ip"] and re.match(r"^\d{1,3}(\.\d{1,3}){3}$", info["ip"]):
                subprocess.run(["ip", "route", "add", "blackhole", f"{info['ip']}/32"], stderr=subprocess.DEVNULL)

        # احیای محلی فقط برای کلاینت‌هایی که تازه شارژ شدند با کانفیگ خودشان
        for pub in restored_pubs:
            if pub in current_active:
                act = current_active[pub]
                if act["ip"] and re.match(r"^\d{1,3}(\.\d{1,3}){3}$", act["ip"]):
                    subprocess.run(["ip", "route", "del", "blackhole", f"{act['ip']}/32"], stderr=subprocess.DEVNULL)
                target_iface = act.get("iface", "wg0")
                if target_iface in client_ifs and act["ip"]:
                    subprocess.run(["wg", "set", target_iface, "peer", pub, "allowed-ips", f"{act['ip']}/32"], stderr=subprocess.DEVNULL)
                    subprocess.run(f"wg-quick save {target_iface}", shell=True, stderr=subprocess.DEVNULL)

        # ۲. ارسال تغییرات به سرور ریموت SSH در صورت وجود تغییر
        if newly_expired_pubs or restored_pubs:
            ssh_cfg = get_ssh_node_cfg(db_path)
            if ssh_cfg:
                payload = {
                    "expired": list(newly_expired_pubs),
                    "restored": [
                        {"pub": k, "ip": current_active[k]["ip"]}
                        for k in restored_pubs
                        if k in current_active and current_active[k]["ip"]
                    ]
                }
                payload_str = json.dumps(payload)
                ssh_cmd = (
                    f"sshpass -p '{ssh_cfg['server_pass']}' ssh -p {ssh_cfg['server_port'] or 22} "
                    f"-o StrictHostKeyChecking=no -o ConnectTimeout=4 "
                    f"{ssh_cfg['server_user'] or 'root'}@{ssh_cfg['server_ip']} "
                    f"'/usr/local/bin/remote_wg_sync.py'"
                )
                subprocess.run(
                    ssh_cmd, 
                    input=payload_str, 
                    text=True, 
                    shell=True, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )

        return current_expired_set

    except Exception:
        return last_expired_set

def main():
    last_set = set()
    while True:
        try:
            last_set = enforce_sync_cycle(last_set)
        except Exception:
            pass
        time.sleep(3)

if __name__ == "__main__":
    main()