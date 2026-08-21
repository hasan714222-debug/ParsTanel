# ========================================================================= #
# نام فایل: sqlite_backend.py                                               #
# نقش: پایگاه‌داده خودکار SQLite با قابلیت مایگریشن خودکار و تنظیمات ضدقفل     #
# ========================================================================= #

import os
import re
import json
import time
import shutil
import sqlite3
import threading

_sqlite_path = None
_db_lock = threading.RLock()

# -------------------------------------------------------------------------
# ساختار جامع جدول‌ها و ستون‌ها برای ساخت خودکار و Auto-Migration
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
            "deleted_traffic": "INTEGER DEFAULT 0"
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
            "server_name": "TEXT DEFAULT 'سرور اصلی'",
            "file_suffix": "TEXT DEFAULT ''"
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
        # تست سلامت ارتباط با دیتابیس
        con.execute("SELECT 1 FROM sqlite_master LIMIT 1;")
        return con
    except sqlite3.DatabaseError as e:
        if "malformed" in str(e).lower() or "corrupt" in str(e).lower():
            print(f"[CRITICAL AUTO-REPAIR] Corrupted SQLite database detected: {e}. Rebuilding fresh DB...")
            try:
                con.close()
            except Exception:
                pass
            # پشتیبان‌گیری از فایل آسیب‌دیده و ایجاد دیتابیس تمیز
            for ext in ["", "-wal", "-shm"]:
                bad_file = _sqlite_path + ext
                if os.path.exists(bad_file):
                    try:
                        shutil.move(bad_file, bad_file + f".corrupted_{int(time.time())}")
                    except Exception:
                        pass
            
            # برقراری اتصال جدید
            con = sqlite3.connect(_sqlite_path, check_same_thread=False, timeout=60.0)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA busy_timeout=60000;")
            con.execute("PRAGMA synchronous=NORMAL;")
            return con
        raise


def init_sqlite(base_dir: str):
    """
    موتور ساخت و مایگریشن خودکار پایگاه‌داده در زمان راه‌اندازی و آپدیت
    """
    global _sqlite_path
    _sqlite_path = os.path.join(base_dir, "db.sqlite3")
    os.makedirs(base_dir, exist_ok=True)

    with _db_lock, _connect() as con:
        cur = con.cursor()

        # ۱. ساخت جداول و مایگریشن ستون‌های مفقود
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

        # ۲. ایجاد ایندکس‌های کلیدی
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_peers_pubkey ON peers(public_key);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_peers_config ON peers(config);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_peers_name_cfg ON peers(peer_name, config);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_short_links_id ON short_links(short_id);")

        # ۳. ایجاد رکوردهای اولیه
        cur.execute("INSERT OR IGNORE INTO global_deleted_traffic (id, total) VALUES (1, 0);")
        con.commit()


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


def _json_default_peer_fields(peer: dict) -> dict:
    peer = dict(peer)
    peer.setdefault("used", 0)
    peer.setdefault("remaining", 0)
    peer.setdefault("first_usage", False)
    peer.setdefault("expiry_blocked", False)
    peer.setdefault("monitor_blocked", False)
    peer.setdefault("last_received_bytes", 0)
    peer.setdefault("last_sent_bytes", 0)
    peer.setdefault("remaining_time", 0)
    return peer


def obtain_peers_file(config_name: str) -> str:
    base_name = config_name.split(".")[0]
    return f"sqlite://peers/{base_name}.json"


def _row_to_peer(row: sqlite3.Row) -> dict:
    def g(col, default=None):
        try:
            return row[col]
        except Exception:
            return default

    p = {
        "peer_name": g("peer_name"),
        "peer_ip": g("peer_ip"),
        "public_key": g("public_key"),
        "limit": g("limit"),
        "used": int(g("used", 0) or 0),
        "remaining": int(g("remaining", 0) or 0),
        "config": g("config"),
        "first_usage": bool(g("first_usage", 0)),
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
        "token": g("token"),
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

    return _json_default_peer_fields(p)


def _peer_to_columns(peer: dict, config_file: str):
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
        peer.get("token"),
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