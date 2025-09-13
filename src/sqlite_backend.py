import os
import json
import sqlite3
import threading

_sqlite_path = None
_db_lock = threading.RLock()

def init_sqlite(base_dir: str):
    global _sqlite_path
    _sqlite_path = os.path.join(base_dir, "db.sqlite3")
    os.makedirs(base_dir, exist_ok=True)
    con = sqlite3.connect(_sqlite_path)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.executescript(
        "CREATE TABLE IF NOT EXISTS users("
        "    username TEXT PRIMARY KEY,"
        "    password_hash TEXT NOT NULL"
        ");"
        "CREATE TABLE IF NOT EXISTS peers("
        "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "    peer_name TEXT,"
        "    peer_ip TEXT,"
        "    public_key TEXT,"
        "    \"limit\" TEXT,"
        "    used INTEGER DEFAULT 0,"
        "    remaining INTEGER DEFAULT 0,"
        "    config TEXT,"
        "    expiry_time_json TEXT,"
        "    first_usage INTEGER DEFAULT 0,"
        "    expiry_blocked INTEGER DEFAULT 0,"
        "    monitor_blocked INTEGER DEFAULT 0,"
        "    last_received_bytes INTEGER DEFAULT 0,"
        "    last_sent_bytes INTEGER DEFAULT 0,"
        "    remaining_time INTEGER DEFAULT 0,"
        "    private_key TEXT,"
        "    dns TEXT,"
        "    mtu INTEGER DEFAULT 1280,"
        "    persistent_keepalive INTEGER DEFAULT 25,"
        "    allowed_ips TEXT DEFAULT '0.0.0.0/0, ::/0',"
        "    token TEXT"
        ");"
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_peers_pubkey ON peers(public_key);"
        "CREATE INDEX IF NOT EXISTS idx_peers_config ON peers(config);"
        "CREATE INDEX IF NOT EXISTS idx_peers_ip ON peers(peer_ip);"
    )

        con.commit()
    finally:
        con.close()

def _connect():
    if _sqlite_path is None:
        raise RuntimeError("init_sqlite() must be called first")
    con = sqlite3.connect(_sqlite_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def load_users():
    with _db_lock, _connect() as con:
        rows = con.execute("SELECT username, password_hash FROM users").fetchall()
        return {r["username"]: r["password_hash"] for r in rows}

def save_users(users: dict):
    with _db_lock, _connect() as con:
        con.execute("DELETE FROM users")
        for username, pw in users.items():
            con.execute("INSERT INTO users(username, password_hash) VALUES (?,?)", (username, pw))
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

# def _row_to_peer(row: sqlite3.Row) -> dict:
#     # دسترسی امن به ستون (برای سازگاری قبل/بعدِ مایگریشن)
#     def g(col, default=None):
#         try:
#             return row[col]
#         except Exception:
#             return default

#     p = {
#         "peer_name": g("peer_name"),
#         "peer_ip": g("peer_ip"),
#         "public_key": g("public_key"),
#         "limit": g("limit"),
#         "used": int(g("used", 0) or 0),
#         "remaining": int(g("remaining", 0) or 0),
#         "config": g("config"),
#         "first_usage": bool(g("first_usage", 0)),
#         "expiry_blocked": bool(g("expiry_blocked", 0)),
#         "monitor_blocked": bool(g("monitor_blocked", 0)),
#         "last_received_bytes": int(g("last_received_bytes", 0) or 0),
#         "last_sent_bytes": int(g("last_sent_bytes", 0) or 0),
#         "remaining_time": int(g("remaining_time", 0) or 0),
#     }

#     # expiry_time_json -> expiry_time (dict)
#     try:
#         p["expiry_time"] = json.loads(g("expiry_time_json", "") or "{}")
#     except Exception:
#         p["expiry_time"] = {}

#     # ستون‌های جدید (اگر وجود نداشته باشند، مقادیر پیش‌فرض)
#     p["private_key"] = g("private_key")                         # ممکنه None باشه
#     p["dns"] = g("dns") or "1.1.1.1"
#     p["mtu"] = int(g("mtu", 1280) or 1280)
#     p["persistent_keepalive"] = int(g("persistent_keepalive", 25) or 25)
#     p["allowed_ips"] = g("allowed_ips") or "0.0.0.0/0, ::/0"
#     p["token"] = g("token")

#     return _json_default_peer_fields(p)

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

        # فیلدهای «پایینی» که گفتی، یکجا داخل dict:
        "private_key": g("private_key"),
        "dns": g("dns") or "1.1.1.1",
        "mtu": int(g("mtu", 1280) or 1280),
        "persistent_keepalive": int(g("persistent_keepalive", 25) or 25),
        "allowed_ips": g("allowed_ips") or "0.0.0.0/0, ::/0",
        "token": g("token"),
    }

    # expiry_time_json → expiry_time
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

        # ستون‌های جدید
        peer.get("private_key"),
        peer.get("dns"),
        int(peer.get("mtu", 1280) or 1280),
        int(peer.get("persistent_keepalive", 25) or 25),
        peer.get("allowed_ips", "0.0.0.0/0, ::/0"),
        peer.get("token")
    )


def load_peers_from_json(config_name: str):
    config_file = config_name if config_name.endswith(".conf") else f"{config_name}.conf"
    with _db_lock, _connect() as con:
        rows = con.execute(
            "SELECT * FROM peers WHERE config=? ORDER BY id ASC", (config_file,)
        ).fetchall()
        return [_row_to_peer(r) for r in rows]


def save_peers_to_json(config_name: str, peers: list):
    config_file = config_name if config_name.endswith(".conf") else f"{config_name}.conf"
    with _db_lock, _connect() as con:
        con.execute("DELETE FROM peers WHERE config=?", (config_file,))
        for p in peers or []:
            con.execute(
                "INSERT INTO peers (peer_name,peer_ip,public_key, \"limit\",used,remaining,config,"
                " expiry_time_json, first_usage, expiry_blocked, monitor_blocked,"
                " last_received_bytes, last_sent_bytes, remaining_time,"
                " private_key, dns, mtu, persistent_keepalive, allowed_ips, token)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                _peer_to_columns(p, config_file)
            )
        con.commit()


def load_peers_with_lock(config_name: str):
    return load_peers_from_json(config_name)

def save_peers_with_lock(config_name: str, peers_data: list):
    return save_peers_to_json(config_name, peers_data)
