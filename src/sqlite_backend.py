import os, json, sqlite3, threading

_sqlite_path = None
_db_lock = threading.RLock()

def init_sqlite(base_dir: str):
    global _sqlite_path
    _sqlite_path = os.path.join(base_dir, "db.sqlite3")
    os.makedirs(base_dir, exist_ok=True)
    con = sqlite3.connect(_sqlite_path)
    try:
        con.execute("PRAGMA journal_mode=WAL;"); con.execute("PRAGMA busy_timeout=60000;"); con.execute("PRAGMA synchronous=NORMAL;")
        con.executescript(
            "CREATE TABLE IF NOT EXISTS users("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    username TEXT UNIQUE NOT NULL,"
            "    password_hash TEXT NOT NULL,"
            "    password_plain TEXT"
            ");"
            "CREATE TABLE IF NOT EXISTS peers("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    peer_name TEXT,"
            "    peer_ip TEXT,"
            "    public_key TEXT UNIQUE,"
            "    [limit] TEXT,"
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
            "CREATE TABLE IF NOT EXISTS peer_synced_edges("
            "    peer_name TEXT,"
            "    server_ip TEXT,"
            "    config TEXT,"
            "    last_bytes INTEGER DEFAULT 0,"
            "    edge_ip TEXT,"
            "    UNIQUE(peer_name, server_ip, config)"
            ");"
            "CREATE TABLE IF NOT EXISTS short_links ("
            "    short_id TEXT PRIMARY KEY,"
            "    long_link TEXT NOT NULL,"
            "    created_at TEXT DEFAULT CURRENT_TIMESTAMP"
            ");"
            "CREATE TABLE IF NOT EXISTS api_keys ("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    encrypted_key TEXT UNIQUE NOT NULL,"
            "    created_at TEXT DEFAULT CURRENT_TIMESTAMP"
            ");"
            "CREATE TABLE IF NOT EXISTS system_config ("
            "    key_name TEXT PRIMARY KEY,"
            "    value_text TEXT"
            ");"
            "CREATE TABLE IF NOT EXISTS global_deleted_traffic ("
            "    id INTEGER PRIMARY KEY,"
            "    total INTEGER DEFAULT 0"
            ");"
            "CREATE TABLE IF NOT EXISTS sub_panels ("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    interface_name TEXT UNIQUE,"
            "    username TEXT UNIQUE,"
            "    password_hash TEXT,"
            "    data_limit_gb REAL,"
            "    port INTEGER,"
            "    created_at TEXT,"
            "    status TEXT,"
            "    disabled_at TEXT,"
            "    password_plain TEXT,"
            "    deleted_traffic INTEGER DEFAULT 0"
            ");"
            "CREATE TABLE IF NOT EXISTS client_settings ("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    interface_name TEXT UNIQUE,"
            "    special_mode INTEGER DEFAULT 1"
            ");"
            "CREATE TABLE IF NOT EXISTS master_settings ("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    endpoint_domain TEXT,"
            "    ssh_ip TEXT,"
            "    server_name TEXT DEFAULT '',"
            "    file_suffix TEXT DEFAULT ''"
            ");"
            "CREATE TABLE IF NOT EXISTS edge_servers ("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    server_ip TEXT UNIQUE,"
            "    panel_url TEXT,"
            "    panel_user TEXT,"
            "    panel_pass TEXT,"
            "    ssh_ip TEXT,"
            "    ssh_port INTEGER DEFAULT 22,"
            "    ssh_user TEXT DEFAULT 'root',"
            "    ssh_pass TEXT,"
            "    location TEXT,"
            "    flag TEXT,"
            "    server_name TEXT DEFAULT '',"
            "    file_suffix TEXT DEFAULT '',"
            "    created_at TEXT"
            ");"
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_peers_pubkey ON peers(public_key);"
            "CREATE INDEX IF NOT EXISTS idx_peers_config ON peers(config);"
            "CREATE INDEX IF NOT EXISTS idx_peers_name_cfg ON peers(peer_name, config);"
        )
        con.execute("INSERT OR IGNORE INTO global_deleted_traffic (id, total) VALUES (1, 0);")
        con.commit()
    finally:
        con.close()

def _connect():
    if _sqlite_path is None:
        db_p = '/home/irandnss/public_html/git/github_workspace/base/src/db.sqlite3'
        if not os.path.exists(db_p):
            db_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.sqlite3")
        con = sqlite3.connect(db_p, check_same_thread=False, timeout=15.0)
    else:
        con = sqlite3.connect(_sqlite_path, check_same_thread=False, timeout=15.0)
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

def _row_to_peer(row: sqlite3.Row) -> dict:
    def g(col, default=None):
        try: return row[col]
        except Exception: return default

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
    }
    try: p["expiry_time"] = json.loads(g("expiry_time_json", "") or "{}")
    except Exception: p["expiry_time"] = {}

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
        peer.get("dns"),
        int(peer.get("mtu", 1280) or 1280),
        int(peer.get("persistent_keepalive", 25) or 25),
        peer.get("allowed_ips", "0.0.0.0/0, ::/0"),
        peer.get("token")
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
            if not p.get("public_key"): continue
            con.execute(
                "INSERT INTO peers (peer_name, peer_ip, public_key, [limit], used, remaining, config, "
                "expiry_time_json, first_usage, expiry_blocked, monitor_blocked, "
                "last_received_bytes, last_sent_bytes, remaining_time, "
                "private_key, dns, mtu, persistent_keepalive, allowed_ips, token) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(public_key) DO UPDATE SET "
                "peer_name=excluded.peer_name, peer_ip=excluded.peer_ip, [limit]=excluded.[limit], "
                "used=excluded.used, remaining=excluded.remaining, config=excluded.config, "
                "expiry_time_json=excluded.expiry_time_json, first_usage=excluded.first_usage, "
                "expiry_blocked=excluded.expiry_blocked, monitor_blocked=excluded.monitor_blocked, "
                "remaining_time=excluded.remaining_time, private_key=excluded.private_key, "
                "dns=excluded.dns, mtu=excluded.mtu, persistent_keepalive=excluded.persistent_keepalive, "
                "allowed_ips=excluded.allowed_ips, token=excluded.token",
                _peer_to_columns(p, config_file)
            )
        con.commit()

def load_peers_with_lock(config_name: str):
    return load_peers_from_json(config_name)

def save_peers_with_lock(config_name: str, peers_data: list):
    return save_peers_to_json(config_name, peers_data)
