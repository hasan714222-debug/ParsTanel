# ========================================================================= #
# نام فایل: sqlite_backend.py                                               #
# نقش: هسته جامع و یکپارچه پایگاه‌داده، تبدیل واحد، تاریخ و توابع کمکی امن  #
# ========================================================================= #

import os
import re
import json
import time
import shutil
import sqlite3
import threading
import secrets

_sqlite_path = None
_db_lock = threading.RLock()

# -------------------------------------------------------------------------
# ساختار جامع پایگاه‌داده (Schema Definition & Auto-Migration)
# -------------------------------------------------------------------------
SCHEMA_DEFINITIONS = {
    "users": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "username": "TEXT UNIQUE NOT NULL",
            "password_hash": "TEXT NOT NULL",
            "password_plain": "TEXT"
        }
    },
    "peers": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "peer_name": "TEXT",
            "peer_ip": "TEXT",
            "public_key": "TEXT UNIQUE",
            "limit": "TEXT",
            "used": "INTEGER DEFAULT 0",
            "remaining": "INTEGER DEFAULT 0",
            "config": "TEXT DEFAULT 'wg0.conf'",
            "expiry_time_json": "TEXT DEFAULT '{}'",
            "first_usage": "INTEGER DEFAULT 0",
            "expiry_blocked": "INTEGER DEFAULT 0",
            "monitor_blocked": "INTEGER DEFAULT 0",
            "last_received_bytes": "INTEGER DEFAULT 0",
            "last_sent_bytes": "INTEGER DEFAULT 0",
            "is_advanced": "INTEGER DEFAULT 0",
            "remaining_time": "INTEGER DEFAULT 0",
            "private_key": "TEXT",
            "dns": "TEXT DEFAULT '1.1.1.1'",
            "mtu": "INTEGER DEFAULT 1280",
            "persistent_keepalive": "INTEGER DEFAULT 25",
            "allowed_ips": "TEXT DEFAULT '0.0.0.0/0, ::/0'",
            "token": "TEXT",
            "created_at_gregorian": "TEXT",
            "created_at_jalali": "TEXT",
            "first_connected_gregorian": "TEXT",
            "first_connected_jalali": "TEXT",
            "local_used": "INTEGER DEFAULT 0",
            "initial_duration": "INTEGER DEFAULT 0",
            "created_at": "INTEGER"
        }
    },
    "sub_panels": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "interface_name": "TEXT UNIQUE",
            "username": "TEXT UNIQUE",
            "password_hash": "TEXT",
            "data_limit_gb": "REAL DEFAULT 100.0",
            "port": "INTEGER DEFAULT 51820",
            "created_at": "TEXT",
            "status": "TEXT DEFAULT 'active'",
            "disabled_at": "TEXT",
            "password_plain": "TEXT",
            "deleted_traffic": "INTEGER DEFAULT 0",
            "alert_80_sent": "INTEGER DEFAULT 0",
            "alert_100_sent": "INTEGER DEFAULT 0",
            "telegram_chat_id": "TEXT DEFAULT ''",
            "telegram_bot_token": "TEXT DEFAULT ''",
            "telegram_bot_status": "TEXT DEFAULT 'off'",
            "bot_base_url": "TEXT DEFAULT ''"
        }
    },
    "advanced_services": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "name": "TEXT NOT NULL",
            "flag": "TEXT DEFAULT '🌐'",
            "description": "TEXT DEFAULT ''",
            "suffix": "TEXT DEFAULT ''",
            "proxy_config": "TEXT NOT NULL",
            "domain": "TEXT NOT NULL",
            "port": "INTEGER UNIQUE NOT NULL",
            "dns": "TEXT DEFAULT '1.1.1.1, 1.0.0.1'",
            "mtu": "INTEGER DEFAULT 1420",
            "allowed_ips": "TEXT DEFAULT '0.0.0.0/0, ::/0'",
            "persistent_keepalive": "INTEGER DEFAULT 25",
            "interface_name": "TEXT UNIQUE NOT NULL",
            "status": "INTEGER DEFAULT 1",
            "last_ping": "TEXT DEFAULT 'N/A'",
            "last_ping_time": "INTEGER DEFAULT 0",
            "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP"
        }
    },
    "advanced_ssh_settings": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "mode": "TEXT DEFAULT 'plan'",
            "panel_url": "TEXT DEFAULT ''",
            "panel_user": "TEXT DEFAULT ''",
            "panel_pass": "TEXT DEFAULT ''",
            "server_ip": "TEXT DEFAULT ''",
            "server_port": "INTEGER DEFAULT 22",
            "server_user": "TEXT DEFAULT 'root'",
            "server_pass": "TEXT DEFAULT ''",
            "remote_sub_url": "TEXT DEFAULT ''",
            "updated_at": "TEXT DEFAULT CURRENT_TIMESTAMP"
        }
    },
    "templates": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "user_id": "INTEGER DEFAULT 0",
            "name": "TEXT NOT NULL",
            "vol": "TEXT NOT NULL",
            "days": "INTEGER NOT NULL",
            "first_usage": "INTEGER DEFAULT 1"
        }
    },
    "client_settings": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "interface_name": "TEXT UNIQUE",
            "special_mode": "INTEGER DEFAULT 1"
        }
    },
    "master_settings": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "endpoint_domain": "TEXT DEFAULT ''",
            "ssh_ip": "TEXT DEFAULT ''",
            "server_name": "TEXT DEFAULT ''",
            "file_suffix": "TEXT DEFAULT ''",
            "sub_domain": "TEXT DEFAULT ''",
            "support_url": "TEXT DEFAULT ''",
            "announcement_text": "TEXT DEFAULT ''"
        }
    },
    "edge_servers": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "server_ip": "TEXT UNIQUE",
            "panel_url": "TEXT",
            "panel_user": "TEXT",
            "panel_pass": "TEXT",
            "ssh_ip": "TEXT",
            "ssh_port": "INTEGER DEFAULT 22",
            "ssh_user": "TEXT DEFAULT 'root'",
            "ssh_pass": "TEXT",
            "location": "TEXT DEFAULT 'Unknown'",
            "flag": "TEXT DEFAULT '🌍'",
            "server_name": "TEXT DEFAULT ''",
            "file_suffix": "TEXT DEFAULT ''",
            "created_at": "TEXT"
        }
    },
    "peer_synced_edges": {
        "columns": {
            "peer_name": "TEXT",
            "server_ip": "TEXT",
            "config": "TEXT",
            "edge_ip": "TEXT DEFAULT ''",
            "edge_priv_key": "TEXT DEFAULT ''",
            "edge_pub_key": "TEXT DEFAULT ''",
            "node_used": "INTEGER DEFAULT 0",
            "last_bytes": "INTEGER DEFAULT 0"
        },
        "constraint": "UNIQUE(peer_name, server_ip, config)"
    },
    "short_links": {
        "columns": {
            "short_id": "TEXT PRIMARY KEY",
            "long_link": "TEXT NOT NULL",
            "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP"
        }
    },
    "api_keys": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "encrypted_key": "TEXT UNIQUE NOT NULL",
            "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP"
        }
    },
    "system_config": {
        "columns": {
            "key_name": "TEXT PRIMARY KEY",
            "value_text": "TEXT"
        }
    },
    "global_deleted_traffic": {
        "columns": {
            "id": "INTEGER PRIMARY KEY",
            "total": "INTEGER DEFAULT 0"
        }
    },
    "interface_vault": {
        "columns": {
            "interface_name": "TEXT PRIMARY KEY",
            "vault_bytes": "INTEGER DEFAULT 0"
        }
    },
    "peer_interface_traffic": {
        "columns": {
            "interface_name": "TEXT",
            "public_key": "TEXT",
            "last_raw_bytes": "INTEGER DEFAULT 0"
        },
        "constraint": "PRIMARY KEY (interface_name, public_key)"
    },
    "subscription_plans": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "plan_name": "TEXT",
            "description": "TEXT",
            "suffix": "TEXT DEFAULT ''",
            "mtu": "INTEGER DEFAULT 1420",
            "dns": "TEXT DEFAULT '1.1.1.1, 1.0.0.1'",
            "keepalive": "INTEGER DEFAULT 25",
            "allowed_ips": "TEXT DEFAULT '0.0.0.0/0, ::/0'",
            "active_servers": "TEXT DEFAULT '[\"master\"]'"
        }
    },
    "services": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "user_id": "INTEGER DEFAULT 0",
            "email": "TEXT",
            "sub_id": "TEXT",
            "plan_name": "TEXT",
            "purchase_date": "INTEGER",
            "vol": "REAL",
            "days": "INTEGER",
            "first_usage": "INTEGER DEFAULT 0"
        }
    },
    "ssl_settings": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "fullchain_path": "TEXT",
            "privkey_path": "TEXT"
        }
    },
    "smite_tunnel_settings": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "panel_url": "TEXT DEFAULT 'http://127.0.0.1:8009'",
            "username": "TEXT DEFAULT 'Pars'",
            "password": "TEXT DEFAULT 'Pars'",
            "iran_node_id": "TEXT DEFAULT 'local'",
            "foreign_node_id": "TEXT DEFAULT 'local'",
            "auto_tunnel_resellers": "INTEGER DEFAULT 1",
            "accept_udp": "INTEGER DEFAULT 1",
            "use_ipv6": "INTEGER DEFAULT 1",
            "updated_at": "TEXT"
        }
    },
    "xray_tunnel_settings": {
        "columns": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "proxy_link": "TEXT",
            "status": "INTEGER DEFAULT 0"
        }
    }
}
def obtain_custom_ip() -> str:
    """دریافت دامنه یا آی‌پی اختصاصی ثبت‌شده برای اندپوینت کلاینت‌ها"""
    try:
        with _db_lock, _connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS system_config (key_name TEXT PRIMARY KEY, value_text TEXT);")
            row = con.execute("SELECT value_text FROM system_config WHERE key_name='custom_endpoint_ip'").fetchone()
            if row and row[0]:
                return row[0].strip()
    except Exception:
        pass
    return ""

def set_custom_ip(custom_ip: str) -> str:
    """ذخیره دامنه یا آی‌پی اختصاصی برای اندپوینت کلاینت‌ها"""
    ip_clean = str(custom_ip or "").strip()
    with _db_lock, _connect() as con:
        con.execute("CREATE TABLE IF NOT EXISTS system_config (key_name TEXT PRIMARY KEY, value_text TEXT);")
        con.execute("INSERT OR REPLACE INTO system_config (key_name, value_text) VALUES ('custom_endpoint_ip', ?)", (ip_clean,))
        con.commit()
    return ip_clean

def is_client_interface(iface_name: str) -> bool:
    """تشخیص کارت‌های شبکه ورودی کلاینت و فیلتر کردن کارت‌های تانل خروجی پروکسی"""
    if not iface_name:
        return False
    name = str(iface_name).replace(".conf", "").strip().lower()
    # کارت‌های خروجی تانل پروکسی نباید کلاینت داشته باشند
    if name.startswith("tun_") or name == "proxy" or name == "wgcf":
        return False
    # فقط اینترفیس‌های کلاینت: wg0..wg99 و adv10..adv99
    if re.match(r"^wg\d+$", name) or re.match(r"^adv\d+$", name):
        return True
    return False

def parse_smart_volume_input(val_input, unit_input="GiB"):
    """پارس دقیق و هوشمند رشته‌های حجم و تبدیل به (نمایش وایرگارد، بایت، مقدار گیگابایت)"""
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

def convert_to_bytes(limit_val) -> int:
    """تبدیل هر نوع مقدار ورودی حجم به بایت"""
    if not limit_val:
        return 0
    if isinstance(limit_val, (int, float)):
        return int(limit_val)
    return parse_smart_volume_input(limit_val)[1]

def bytes_to_readable(bytes_val) -> str:
    """تبدیل بایت به فرمت خوانا (B, KB, MB, GB, TB)"""
    b = float(bytes_val or 0)
    if b <= 0:
        return "0 B"
    if b >= 1024**4:
        return f"{b / (1024**4):.2f} TB"
    elif b >= 1024**3:
        return f"{b / (1024**3):.2f} GiB"
    elif b >= 1024**2:
        return f"{b / (1024**2):.2f} MiB"
    elif b >= 1024:
        return f"{b / 1024:.2f} KiB"
    return f"{int(b)} B"

# سازگاری برای توابع قدیمی
format_size = bytes_to_readable
parse_limit_to_bytes = convert_to_bytes

def gregorian_to_jalali(gy, gm, gd):
    """تبدیل تاریخ میلادی به شمسی دقیق"""
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
    """تولید رشته تاریخ و ساعت شمسی فرمت‌شده"""
    if not timestamp or int(timestamp) < 1000000:
        timestamp = int(time.time())
    t = time.gmtime(int(timestamp) + 12600)  # +3:30 IRST
    jy, jm, jd = gregorian_to_jalali(t.tm_year, t.tm_mon, t.tm_mday)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {t.tm_hour:02d}:{t.tm_min:02d}"

# ========================================================================= #
# اتصال پایدار و Self-Healing پایگاه داده
# ========================================================================= #

def _connect():
    global _sqlite_path
    if _sqlite_path is None:
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.sqlite3"),
            "/usr/local/bin/Wireguard-panel/src/db.sqlite3",
            "/etc/wireguard/db.sqlite3"
        ]
        for c in candidates:
            if os.path.exists(c):
                _sqlite_path = c
                break
        if _sqlite_path is None:
            _sqlite_path = candidates[0]

    try:
        con = sqlite3.connect(_sqlite_path, check_same_thread=False, timeout=60.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA busy_timeout=60000;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("SELECT 1 FROM sqlite_master LIMIT 1;")
        return con

    except sqlite3.DatabaseError as e:
        err_msg = str(e).lower()
        if "malformed" in err_msg or "corrupt" in err_msg:
            print(f"[CRITICAL AUTO-REPAIR] Corrupted SQLite DB detected: {e}. Rebuilding...")
            try:
                con.close()
            except Exception:
                pass

            ts = int(time.time())
            for ext in ["", "-wal", "-shm"]:
                bad_file = _sqlite_path + ext
                if os.path.exists(bad_file):
                    try:
                        shutil.move(bad_file, bad_file + f".corrupted_{ts}")
                    except Exception:
                        pass

            con = sqlite3.connect(_sqlite_path, check_same_thread=False, timeout=60.0)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA busy_timeout=60000;")
            con.execute("PRAGMA synchronous=NORMAL;")
            base_dir = os.path.dirname(_sqlite_path)
            init_sqlite(base_dir)
            return con
        raise

def get_server_role() -> str:
    """دریافت نقش سرور: master یا node"""
    try:
        with _db_lock, _connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS system_config (key_name TEXT PRIMARY KEY, value_text TEXT);")
            row = con.execute("SELECT value_text FROM system_config WHERE key_name='server_role'").fetchone()
            if row and row[0]:
                return row[0].strip().lower()
    except Exception:
        pass
    return "master"

def set_server_role(role: str) -> str:
    """تنظیم نقش سرور: master یا node"""
    role_clean = "node" if str(role).strip().lower() == "node" else "master"
    with _db_lock, _connect() as con:
        con.execute("CREATE TABLE IF NOT EXISTS system_config (key_name TEXT PRIMARY KEY, value_text TEXT);")
        con.execute("INSERT OR REPLACE INTO system_config (key_name, value_text) VALUES ('server_role', ?)", (role_clean,))
        con.commit()
    return role_clean

def record_deleted_traffic_atomic(interface_name: str, bytes_amount: int):
    """ثبت اتمیک ترافیک کلاینت‌های حذف‌شده در صندوق بدون دوباره‌شماری"""
    if not bytes_amount or bytes_amount <= 0:
        return

    clean_iface = str(interface_name).replace(".conf", "").strip()

    with _db_lock, _connect() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO interface_vault (interface_name, vault_bytes) 
            VALUES (?, ?)
            ON CONFLICT(interface_name) DO UPDATE SET vault_bytes = vault_bytes + excluded.vault_bytes;
        """, (clean_iface, bytes_amount))

        if clean_iface != "wg0":
            cur.execute("""
                UPDATE sub_panels 
                SET deleted_traffic = deleted_traffic + ? 
                WHERE interface_name = ?;
            """, (bytes_amount, clean_iface))

        con.commit()

def init_sqlite(base_dir: str):
    """ساخت اسکلت جداول و ایندکس‌ها با مایگریشن ستون‌های جدید"""
    global _sqlite_path
    _sqlite_path = os.path.join(base_dir, "db.sqlite3")
    os.makedirs(base_dir, exist_ok=True)

    with _db_lock, _connect() as con:
        cur = con.cursor()

        for tbl_name, tbl_info in SCHEMA_DEFINITIONS.items():
            cols = tbl_info["columns"]
            constraint = tbl_info.get("constraint", "")

            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl_name,))
            table_exists = cur.fetchone()

            if not table_exists:
                col_defs = []
                for c_name, c_type in cols.items():
                    col_defs.append(f'"{c_name}" {c_type}' if c_name == "limit" else f"{c_name} {c_type}")
                if constraint:
                    col_defs.append(constraint)

                create_sql = f"CREATE TABLE IF NOT EXISTS {tbl_name} ({', '.join(col_defs)});"
                cur.execute(create_sql)
            else:
                cur.execute(f"PRAGMA table_info({tbl_name})")
                existing_cols = set(r["name"] for r in cur.fetchall())

                for c_name, c_type in cols.items():
                    if c_name not in existing_cols:
                        try:
                            clean_type = re.sub(r'\b(PRIMARY KEY|AUTOINCREMENT|UNIQUE)\b', '', c_type, flags=re.I).strip()
                            col_field = f'"{c_name}"' if c_name == "limit" else c_name
                            cur.execute(f"ALTER TABLE {tbl_name} ADD COLUMN {col_field} {clean_type};")
                        except Exception:
                            pass

        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_peers_pubkey ON peers(public_key);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_peers_config ON peers(config);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_peers_name_cfg ON peers(peer_name, config);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_short_links_id ON short_links(short_id);")
        cur.execute("INSERT OR IGNORE INTO global_deleted_traffic (id, total) VALUES (1, 0);")
        con.commit()

# ========================================================================= #
# توابع دسترسی داده‌ها و سازگاری با متدهای قدیمی
# ========================================================================= #

def load_users():
    with _db_lock, _connect() as con:
        rows = con.execute("SELECT username, password_hash FROM users").fetchall()
        return {r["username"]: r["password_hash"] for r in rows}

def save_users(users: dict):
    with _db_lock, _connect() as con:
        con.execute("DELETE FROM users")
        for username, pw in users.items():
            con.execute("INSERT INTO users(username, password_hash, password_plain) VALUES (?,?,?)", (username, pw, pw))
        con.commit()

def obtain_peers_file(config_name: str) -> str:
    base_name = config_name.split(".")[0]
    return f"sqlite://peers/{base_name}.json"

def _row_to_peer(row: sqlite3.Row) -> dict:
    def g(col, default=None):
        try:
            return row[col]
        except Exception:
            return default

    tok = g("token")
    if not tok or str(tok).strip() in ["", "None"]:
        tok = secrets.token_urlsafe(16)

    p = {
        "peer_name": g("peer_name"),
        "peer_ip": g("peer_ip"),
        "public_key": g("public_key"),
        "limit": g("limit"),
        "used": int(g("used", 0) or 0),
        "remaining": int(g("remaining", 0) or 0),
        "is_advanced": int(g("is_advanced", 0) or 0),
        "config": g("config") or "wg0.conf",
        "first_usage": bool(
            str(g("first_usage", 0)).strip().lower()
            in ["1", "true", "yes", "on", "calc_first_conn"]
        ),
        "expiry_blocked": bool(g("expiry_blocked", 0)),
        "monitor_blocked": bool(g("monitor_blocked", 0)),
        "last_received_bytes": int(g("last_received_bytes", 0) or 0),
        "last_sent_bytes": int(g("last_sent_bytes", 0) or 0),
        "remaining_time": int(g("remaining_time", 0) or 0),
        "private_key": g("private_key"),
        "dns": g("dns") or "1.1.1.1",
        "mtu": int(g("mtu", 1280) or 1280),
        "persistent_keepalive": int(g("persistent_keepalive", 25) or 25),
        "allowed_ips": g("allowed_ips") or "0.0.0.0/0, ::/0",
        "token": tok,
        "created_at_gregorian": g("created_at_gregorian") or "",
        "created_at_jalali": g("created_at_jalali") or "",
        "first_connected_gregorian": g("first_connected_gregorian") or "",
        "first_connected_jalali": g("first_connected_jalali") or "",
        "local_used": int(g("local_used", 0) or 0),
        "initial_duration": int(g("initial_duration", 0) or 0),
        "created_at": g("created_at") or int(time.time())
    }
    try:
        p["expiry_time"] = json.loads(g("expiry_time_json", "") or "{}")
    except Exception:
        p["expiry_time"] = {}

    return p

def _peer_to_columns(peer: dict, config_file: str):
    token_val = peer.get("token")
    if not token_val or str(token_val).strip() in ["", "None"]:
        token_val = secrets.token_urlsafe(16)
        peer["token"] = token_val

    return (
        peer.get("peer_name"),
        peer.get("peer_ip"),
        peer.get("public_key"),
        peer.get("limit"),
        int(peer.get("used", 0) or 0),
        int(peer.get("remaining", 0) or 0),
        config_file,
        json.dumps(peer.get("expiry_time", {}), ensure_ascii=False),
        1 if peer.get("first_usage") else 0,
        1 if peer.get("expiry_blocked") else 0,
        1 if peer.get("monitor_blocked") else 0,
        int(peer.get("last_received_bytes", 0) or 0),
        int(peer.get("last_sent_bytes", 0) or 0),
        int(peer.get("remaining_time", 0) or 0),
        peer.get("private_key"),
        peer.get("dns") or "1.1.1.1",
        int(peer.get("mtu", 1280) or 1280),
        int(peer.get("persistent_keepalive", 25) or 25),
        peer.get("allowed_ips", "0.0.0.0/0, ::/0"),
        token_val,
        peer.get("created_at_gregorian", ""),
        peer.get("created_at_jalali", ""),
        peer.get("first_connected_gregorian", ""),
        peer.get("first_connected_jalali", ""),
        int(peer.get("local_used", 0) or 0),
        int(peer.get("initial_duration", 0) or 0),
        peer.get("created_at", int(time.time()))
    )

def load_peers_from_json(config_name: str):
    config_file = config_name if config_name.endswith(".conf") else f"{config_name}.conf"
    iface_name = config_file.replace(".conf", "")
    with _db_lock, _connect() as con:
        rows = con.execute(
            "SELECT * FROM peers WHERE config=? OR config=? ORDER BY id ASC", (config_file, iface_name)
        ).fetchall()
        return [_row_to_peer(r) for r in rows]

def save_peers_to_json(config_name: str, peers: list):
    config_file = config_name if config_name.endswith(".conf") else f"{config_name}.conf"
    with _db_lock, _connect() as con:
        for p in peers or []:
            if not p.get("public_key"):
                continue
            con.execute(
                "INSERT INTO peers (peer_name, peer_ip, public_key, [limit], used, remaining, config, "
                "expiry_time_json, first_usage, expiry_blocked, monitor_blocked, "
                "last_received_bytes, last_sent_bytes, remaining_time, "
                "private_key, dns, mtu, persistent_keepalive, allowed_ips, token, "
                "created_at_gregorian, created_at_jalali, first_connected_gregorian, first_connected_jalali, "
                "local_used, initial_duration, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(public_key) DO UPDATE SET "
                "peer_name=excluded.peer_name, peer_ip=excluded.peer_ip, [limit]=excluded.[limit], "
                "used=excluded.used, remaining=excluded.remaining, config=excluded.config, "
                "expiry_time_json=excluded.expiry_time_json, first_usage=excluded.first_usage, "
                "expiry_blocked=excluded.expiry_blocked, monitor_blocked=excluded.monitor_blocked, "
                "remaining_time=excluded.remaining_time, private_key=excluded.private_key, "
                "dns=excluded.dns, mtu=excluded.mtu, persistent_keepalive=excluded.persistent_keepalive, "
                "allowed_ips=excluded.allowed_ips, token=excluded.token, "
                "created_at_gregorian=excluded.created_at_gregorian, created_at_jalali=excluded.created_at_jalali, "
                "first_connected_gregorian=excluded.first_connected_gregorian, first_connected_jalali=excluded.first_connected_jalali, "
                "local_used=excluded.local_used, initial_duration=excluded.initial_duration, created_at=excluded.created_at",
                _peer_to_columns(p, config_file)
            )
        con.commit()

def load_peers_with_lock(config_name: str):
    return load_peers_from_json(config_name)

def save_peers_with_lock(config_name: str, peers_data: list):
    return save_peers_to_json(config_name, peers_data)