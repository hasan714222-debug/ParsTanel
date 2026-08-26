# =========================================================================
# 📦 ماژول‌ها و کتابخانه‌های استاندارد و جانبی
# =========================================================================
import os
import sys
import re
import json
import time
import glob
import shlex
import shutil
import base64
import sqlite3
import secrets
import logging
import tempfile
import threading
import subprocess
import platform
import fcntl
import urllib.parse
import urllib.request
import urllib.error
from io import BytesIO
from queue import Queue
from functools import wraps
from datetime import datetime, timedelta, timezone

# ماژول‌های زمان‌بندی و تایم‌زون
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.base import JobLookupError, ConflictingIdError
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# ماژول‌های شبکه، سخت‌افزار، رمزنگاری و تصاویر
import psutil
import requests
import nacl.bindings
import nacl.public
from ipaddress import ip_address, ip_network
from fasteners import InterProcessLock
from threading import Thread, Event, Lock
from cryptography.fernet import Fernet
import qrcode
from PIL import Image, ImageDraw, ImageFont
import yaml

# ماژول‌های وب سرور، امنیت و قالب فلاسک
from flask import (
    Flask, render_template, jsonify, request, redirect, session, 
    flash, send_file, send_from_directory, make_response, Response, url_for, abort
)
from flask_session import Session
from flask_bcrypt import Bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from werkzeug.security import generate_password_hash, check_password_hash
from jsonschema import validate, ValidationError
from jinja2 import select_autoescape
from redis import Redis
import gunicorn.app.base
from gunicorn.app.base import BaseApplication

# ماژول‌های اختصاصی پروژه
from warp import install_warp, install_fullwarp, install_progress
from sqlite_backend import (
    init_sqlite,
    load_users, save_users,
    load_peers_from_json, save_peers_to_json,
    load_peers_with_lock, save_peers_with_lock,
    obtain_peers_file,
    _db_lock, _connect,
    record_deleted_traffic_atomic,
    get_server_role, set_server_role  # <-- ایمپورت متدهای نقش سرور
)

# =========================================================================
# ⚙️ تابع بارگذاری فایل پیکربندی (config.yaml)
# =========================================================================
def load_config():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.yaml") 
    try:
        if not os.path.exists(config_path):
            default_cfg = {
                "wireguard": {"config_dir": "/etc/wireguard"},
                "flask": {
                    "port": 5000, 
                    "tls": False, 
                    "cert_path": "", 
                    "key_path": "", 
                    "secret_key": "azumiisinyourarea", 
                    "debug": False
                }
            }
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(default_cfg, f, default_flow_style=False)
            return default_cfg

        with open(config_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file) or {}

        config.setdefault("wireguard", {}).setdefault("config_dir", "/etc/wireguard")
        config.setdefault("flask", {}).setdefault("port", 5000)
        config.setdefault("flask", {}).setdefault("tls", False)
        config.setdefault("flask", {}).setdefault("cert_path", "")
        config.setdefault("flask", {}).setdefault("key_path", "")
        config.setdefault("flask", {}).setdefault("secret_key", "azumiisinyourarea")
        config.setdefault("flask", {}).setdefault("debug", False)
        return config

    except yaml.YAMLError as e:
        print(f"ERROR: Wrong YAML format in config.yaml. Details: {e}")
        raise
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")
        raise

config = load_config()

# =========================================================================
# 🚀 پیکربندی اپلیکیشن فلاسک
# =========================================================================
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config['SESSION_TYPE'] = 'filesystem'  
app.config['SESSION_PERMANENT'] = True  
app.config['SESSION_USE_SIGNER'] = True  
app.config['SESSION_COOKIE_NAME'] = 'session'  
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.secret_key = config["flask"]["secret_key"]
Session(app)
app.debug = config["flask"]["debug"]
app.jinja_env.autoescape = select_autoescape(['html', 'htm', 'xml', 'xhtml'])

@app.route("/api/cluster-role", methods=["GET", "POST"])
def api_cluster_role():
    """دریافت و تغییر نقش سرور بین Master و Node"""
    if request.method == "GET":
        role = get_server_role()
        return jsonify({"role": role, "is_master": (role == "master")}), 200

    if session.get("role") == "client":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(silent=True) or request.form or {}
    new_role = "node" if data.get("role") == "node" or data.get("is_master") is False else "master"
    saved_role = set_server_role(new_role)

    try:
        import v100_master_edge_sync
        if saved_role == "master":
            v100_master_edge_sync.start_bot_polling_daemon()
        else:
            v100_master_edge_sync.stop_bot_polling_daemon()
    except Exception:
        pass

    return jsonify({
        "success": True,
        "role": saved_role,
        "is_master": (saved_role == "master"),
        "message": f"نقش سرور با موفقیت به {'Master (سرور اصلی)' if saved_role == 'master' else 'Edge Node (سرور نود)'} تغییر یافت."
    }), 200

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_FILE = os.path.join(BASE_DIR, "api.json")
SECRET_KEY_FILE = os.path.join(BASE_DIR, "secret.key")
INSTALL_PROGRESS_FILE = os.path.join(BASE_DIR, "install_progress.json")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
DB_FILE = os.path.join(BASE_DIR, "db.sqlite3")
SQLITE_FILE = os.path.join(BASE_DIR, "db.sqlite3")
DB_DIR = os.path.join(BASE_DIR, "db") 
SHORT_LINKS_FILE = os.path.join(BASE_DIR, "short_links.json")
DECRYPTED_LINKS_FILE = os.path.join(BASE_DIR, "short_links_decrypted.json")
WIREGUARD_CONFIG_DIR = config["wireguard"]["config_dir"]
PEERS = []  

# ایجاد خودکار دایرکتوری‌های پروژه در صورت عدم وجود
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "templates"), exist_ok=True)
init_sqlite(BASE_DIR)
try:
    redis_client = Redis(host="127.0.0.1", port=6379, db=0, socket_timeout=1.5)
    redis_client.ping()
    limiter = Limiter(get_remote_address, app=app, storage_uri="redis://127.0.0.1:6379")
    app.config["CACHE_TYPE"] = "RedisCache"
    app.config["CACHE_REDIS_HOST"] = "127.0.0.1"
    app.config["CACHE_REDIS_PORT"] = 6379
    app.config["CACHE_REDIS_DB"] = 0
    cache = Cache(app)
except Exception:
    limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")
    cache = Cache(app, config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300})

bcrypt = Bcrypt(app)
countdown_event = Event()
json_lock = Lock()
metrics_queue = Queue(maxsize=1)
stop_event = Event()
short_links_lock = Lock()
def get_system_timezone():
    try:
        if os.path.exists("/etc/timezone"):
            with open("/etc/timezone", "r", encoding="utf-8") as f:
                tz_name = f.read().strip()
                if tz_name:
                    return tz_name
        if os.path.exists("/etc/localtime") and os.path.islink("/etc/localtime"):
            tz_target = os.path.realpath("/etc/localtime")
            if "zoneinfo/" in tz_target:
                return tz_target.split("zoneinfo/")[-1]
        if time.tzname and time.tzname[0]:
            return time.tzname[0]
    except Exception:
        pass
    return "UTC"
system_timezone = pytz.timezone(get_system_timezone())
print(f"[INFO] Detected System Timezone: {system_timezone}")


@app.route("/set-language", methods=["POST"])
def set_language():
    selected_language = request.form.get("language")
    if selected_language in ["en", "fa"]:
        session["language"] = selected_language
        response = make_response(redirect(request.referrer or url_for("home")))
        response.set_cookie("language", selected_language, max_age=30*24*60*60)  
        return response
    return redirect(request.referrer or url_for("home"))


@app.route('/api/activate-bot', methods=['POST'])
def api_activate_bot_official():
    data = request.get_json(silent=True) or request.form or {}
    token = data.get('bot_token', '').strip()
    chat_id = data.get('admin_chat_id', '').strip()
    role = session.get('role', 'admin')
    username = session.get('username')

    if not token:
        return jsonify(success=False, message="لطفاً توکن ربات را وارد کنید."), 400

    try:
        import v100_master_edge_sync
        
        # استخراج آدرس دامنه‌ای که کاربر در حال حاضر با آن وارد پنل شده است
        current_request_url = request.host_url.rstrip('/')
        
        if role == 'client':
            with _db_lock, _connect() as conn:
                # ذخیره توکن، چت‌آیدی و آدرس دامنه اختصاصی نماینده
                conn.execute(
                    """UPDATE sub_panels 
                       SET telegram_bot_token=?, telegram_chat_id=?, telegram_bot_status='on', bot_base_url=? 
                       WHERE username=?""",
                    (token, chat_id, current_request_url, username)
                )
                conn.commit()
        else:
            cfg_p = get_local_cfg_p()
            with open(cfg_p, 'w', encoding='utf-8') as f:
                json.dump({'t': token, 'c': chat_id, 'status': 'on', 'panel_url': current_request_url}, f, indent=4)
            
            # ذخیره آدرس پنل ادمین در جدول system_config برای دسترسی دائم
            with _db_lock, _connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO system_config (key_name, value_text) VALUES ('panel_url', ?)",
                    (current_request_url,)
                )
                conn.commit()

        # حذف وبهوک قبلی برای فعال‌سازی بدون تداخل پولینگ
        try:
            del_url = f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=True"
            urllib.request.urlopen(urllib.request.Request(del_url), timeout=8)
        except Exception:
            pass

        # راه‌اندازی دیمن پولینگ ربات
        v100_master_edge_sync.start_bot_polling_daemon()
        
        if chat_id:
            v100_master_edge_sync.tg_send_message(
                chat_id,
                "🤖 <b>ربات مدیریت وایرگارد فعال شد!</b>\n\n✅ دسترسی تایید شد و تمام منوها فعال هستند.",
                v100_master_edge_sync.get_main_reply_keyboard(),
                token
            )

        return jsonify(success=True, message="✅ ربات تلگرام با موفقیت فعال شد! اکنون در تلگرام دستور /start را بفرستید.")
    except Exception as e:
        app.logger.error(f"Error in activate-bot: {e}")
        return jsonify(success=False, message=str(e)), 500

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({"message": "Logged out successfully!"}), 200


@app.route('/api/wireguard-interfaces', methods=['GET'])
def obtain_wireguard_interfaces():

    try:
        config_dir = "/etc/wireguard"
        interfaces = [
            f for f in os.listdir(config_dir)
            if f.endswith(".conf")
        ]

        if not interfaces:
            return jsonify({"interfaces": []}), 200

        return jsonify({"interfaces": interfaces}), 200
    except FileNotFoundError:
        return jsonify({"error": "Wireguard config directory not found."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
def parse_smart_volume_input(val_input, unit_input="GiB"):
    if not val_input or str(val_input).strip() == "":
        return "50GiB", 50 * 1073741824, 50.0

    s = str(val_input).strip()
    # تبدیل اعداد فارسی و عربی به انگلیسی
    for p, a, e in zip("۰۱۲۳۴۵۶۷۸۹", "٠١٢٣٤٥٦٧٨٩", "0123456789"):
        s = s.replace(p, e).replace(a, e)

    # تشخیص اعشار، اسلش یا ممیز
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

    # ۱. اگر اعشاری بود (1/5 یا 1.5) -> همیشه گیگابایت
    if has_fraction or (num != int(num)):
        bytes_val = int(num * 1073741824)
        wg_limit_str = f"{num:g}GiB"
        gb_val = num
    else:
        # ۲. اگر عدد رند بود -> طبق واحد انتخابی کاربر
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

def validate_json(schema=None):

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not request.is_json:  
                return jsonify({"error": "Wrong content type. JSON required."}), 400
            try:
                data = request.get_json()
                if schema:
                    validate(instance=data, schema=schema)  
            except ValidationError as e:
                return jsonify({"error": f"Wrong JSON input: {e.message}"}), 400
            except Exception as e:
                return jsonify({"error": f"Unexpected error: {str(e)}"}), 500
            return f(*args, **kwargs)
        return decorated_function
    return decorator

peer_schema = {
    "type": "object",
    "properties": {
        "peerName": {
            "type": "string",
            "pattern": r"^[a-zA-Z0-9_-]+$"
        },
        "peerIp": {
            "type": "string",
            "format": "ipv4"
        },
        "limit": {  
            "type": "string",
            "pattern": r"^\d+(MiB|GiB)$"
        },
        "configFile": {
            "type": "string",
            "pattern": r"^[a-zA-Z0-9_-]+\.conf$"
        },
        "dns": {"type": "string"},
        "expiryMonths": {"type": "integer", "minimum": 0},
        "expiryDays": {"type": "integer", "minimum": 0},
        "expiryHours": {"type": "integer", "minimum": 0},
        "expiryMinutes": {"type": "integer", "minimum": 0},
        "firstUsage": {"type": "boolean"},
        "mtu": {"type": "integer", "minimum": 0},
        "persistentKeepalive": {"type": "integer", "minimum": 0}
    },
    "required": ["peerName", "peerIp", "limit"],  
    "additionalProperties": False
}

edit_peer_schema = {
    "type": "object",
    "properties": {
        "peerName": {
            "type": "string",
            "pattern": r"^[a-zA-Z0-9_-]+$"
        },
        "dataLimit": {
            "type": ["string", "null"],
            "pattern": r"^\d+(MiB|GiB)$"
        },
        "dns": {"type": ["string", "null"]},
        "expiryDays": {"type": ["integer", "null"], "minimum": 0},
        "expiryMonths": {"type": ["integer", "null"], "minimum": 0},
        "expiryHours": {"type": ["integer", "null"], "minimum": 0},
        "expiryMinutes": {"type": ["integer", "null"], "minimum": 0},
        "configFile": {
            "type": "string",
            "pattern": r"^[a-zA-Z0-9_-]+\.conf$"
        }
    },
    "required": ["peerName"],
    "additionalProperties": False
}


@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({"status": "running"}), 200

@app.route('/get-api-keys', methods=['GET'])
def obtain_api_keys():
    api_data = load_file(API_FILE)
    if "api_keys" in api_data:
        decrypted_keys = [cipher.decrypt(key.encode()).decode() for key in api_data["api_keys"]]
        return jsonify({"api_keys": decrypted_keys})
    return jsonify({"api_keys": []})

def decrypt_short_links(
    input_file=SHORT_LINKS_FILE,
    output_file=DECRYPTED_LINKS_FILE
):

    
    try:
        with open(input_file, "r") as f:
            short_links = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"Could not load '{input_file}' or invalid JSON.")
        return

    decrypted_links = {}

    for short_id, encrypted_link in short_links.items():
        try:
            plaintext_url = cipher.decrypt(encrypted_link.encode()).decode()
            decrypted_links[short_id] = plaintext_url
        except Exception as e:
            print(f"Failed to decrypt short_id '{short_id}': {e}")

    with open(output_file, "w") as f:
        json.dump(decrypted_links, f, indent=4)

    print(f"Decrypted short links have been saved to '{output_file}'.")

def create_secret_key():
    if os.path.exists(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, "rb") as key_file:
            return key_file.read()
    else:
        secret_key = Fernet.generate_key()
        with open(SECRET_KEY_FILE, "wb") as key_file:
            key_file.write(secret_key)
        return secret_key
    
SECRET_KEY = create_secret_key()
cipher = Fernet(SECRET_KEY)


def load_file(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            return json.load(file)
    return {}


def save_file(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file)

@app.route('/create-api-key', methods=['POST'])
def create_api_key():
    api_data = load_file(API_FILE)
    api_key = os.urandom(16).hex() 
    encrypted_key = cipher.encrypt(api_key.encode()).decode() 

    if "api_keys" not in api_data:
        api_data["api_keys"] = []
    
    api_data["api_keys"].append(encrypted_key)  
    save_file(API_FILE, api_data)  

    return jsonify({"api_key": api_key}) 


@app.route('/delete-api-key/<int:index>', methods=['DELETE'])
def delete_api_key(index):
    api_data = load_file(API_FILE)
    if "api_keys" in api_data and 0 <= index < len(api_data["api_keys"]):
        del api_data["api_keys"][index] 
        save_file(API_FILE, api_data)  
        return jsonify({"message": "API Key deleted successfully"})
    return jsonify({"error": "API Key not found"}), 404

new_backup_created = False

def delete_old_backup(backup_dir: str, backup_prefix: str):
    try:
        backups = [f for f in os.listdir(backup_dir) if f.startswith(backup_prefix)]
        if backups:
            oldest_backup_path = os.path.join(backup_dir, backups[0])
            os.remove(oldest_backup_path)
            logging.info(f"Deleted old backup: {oldest_backup_path}")
    except Exception as e:
        logging.error(f"Couldn't delete old backup: {e}")


def create_automated_backup():
    global new_backup_created
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        logging.info(f"Creating backup with timestamp: {timestamp}")


        wireguard_backup_dir = os.path.join(BACKUP_DIR, "wireguard")
        os.makedirs(wireguard_backup_dir, exist_ok=True)
        if os.path.exists(WIREGUARD_CONFIG_DIR):
            for file in os.listdir(WIREGUARD_CONFIG_DIR):
                if file.endswith(".conf"):
                    src_path = os.path.join(WIREGUARD_CONFIG_DIR, file)
                    dest_path = os.path.join(wireguard_backup_dir, f"{file}_{timestamp}")
                    delete_old_backup(wireguard_backup_dir, file)
                    shutil.copy2(src_path, dest_path)
        logging.info(f"Wireguard configs backed up to {wireguard_backup_dir}")

    
        db_backup_dir = os.path.join(BACKUP_DIR, "db")
        os.makedirs(db_backup_dir, exist_ok=True)


        if os.path.exists(DB_DIR):
            for file in os.listdir(DB_DIR):
                if file.endswith(".json"):
                    src_path = os.path.join(DB_DIR, file)
                    dest_path = os.path.join(db_backup_dir, f"{file}_{timestamp}")
                    delete_old_backup(db_backup_dir, file)
                    shutil.copy2(src_path, dest_path)

      
        if os.path.exists(SQLITE_FILE):
            sqlite_dest = os.path.join(db_backup_dir, f"db.sqlite3_{timestamp}")
            delete_old_backup(db_backup_dir, "db.sqlite3")
            try:
                with sqlite3.connect(f"file:{SQLITE_FILE}?mode=ro", uri=True) as src_conn:
                    with sqlite3.connect(sqlite_dest) as dst_conn:
                        src_conn.backup(dst_conn)
                shutil.copystat(SQLITE_FILE, sqlite_dest)
                logging.info(f"SQLite online backup created at {sqlite_dest}")
            except Exception as e:
                logging.warning(f"SQLite backup API failed, fallback to file copy: {e}")
                shutil.copy2(SQLITE_FILE, sqlite_dest)

                for ext in ("-wal", "-shm"):
                    wal_src = SQLITE_FILE + ext
                    if os.path.exists(wal_src):
                        shutil.copy2(wal_src, sqlite_dest + ext)

        logging.info(f"Database files backed up to {db_backup_dir}")
        new_backup_created = True
        logging.info("Automated backup created and notification flag set.")
    except Exception as e:
        logging.error(f"Couldn't create automated backup: {e}")



@app.route("/api/backup-status", methods=["GET"])
def check_backup_status():
    global new_backup_created
    if new_backup_created:
        new_backup_created = False 
        return jsonify({"new_backup": True})
    return jsonify({"new_backup": False})



def setup_logging(debug_mode):

    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wireguard.log")

    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    log_format = "%(asctime)s [%(levelname)s] %(message)s"

    file_handler = logging.FileHandler(log_file_path)
    file_handler.setFormatter(logging.Formatter(log_format))

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter(log_format))

    logger = logging.getLogger()
    logger.handlers.clear()  

    if debug_mode:
        logger.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
    else:
        logger.setLevel(logging.INFO)
        logger.addHandler(file_handler)

        logging.getLogger("werkzeug").setLevel(logging.ERROR)

@app.route('/api/stuff', methods=['GET'])
def track_statuses():
    def check_xray_status():
        try:
            command = ["sudo", "systemctl", "is-active", "xray"]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return result.stdout.strip() == 'active'
        except subprocess.CalledProcessError:
            return False
        except Exception:
            return False

    def check_warp_status():
        try:
            interfaces = psutil.net_if_addrs()
            for interface in interfaces:
                if "wgcf" in interface:
                    return True
            return False
        except Exception:
            return False

    xray_status = check_xray_status()
    warp_status = check_warp_status()

    return jsonify({"warp": warp_status, "xray": xray_status})


@app.route("/api/web-config", methods=["GET"])
def obtain_web_config():
    try:
        print("Returning web config:", config["flask"])  
        return jsonify({
            "port": config["flask"]["port"],
            "tls": config["flask"]["tls"]
        }), 200
    except Exception as e:
        print(f"error in /api/web-config: {e}")  
        return jsonify({"error": f"Couldn't load web config: {str(e)}"}), 500

@app.route("/")
def index():
    if "username" not in session:
        return redirect("/login")
    return redirect("/home")

@app.route("/home")
def home():
    if not session.get("logged_in") or not session.get("username"):
        flash("Please log in to access the dashboard.", "error")
        return redirect("/login")

    language = session.get('language', 'fa')
    template_name = "index-fa.html" if language == "fa" else "index.html"
    return render_template(template_name, username=session["username"])

def load_username_from_db():
    try:
        users = load_users()
        if users:
            return next(iter(users.keys()), "Admin")
    except Exception:
        pass
    return "Admin"  

@app.route('/logout-user', methods=['GET'])
def logout_user():

    print("Session before logout:", session)  

    session.clear()
    print("Session after logout:", session)  

    response = make_response(redirect('/login'))
    response.delete_cookie('username')  

    return response


@app.context_processor
def inject_username():
    return {'username': load_username_from_db()}

@app.route("/peers")
def peers_list():
    if "username" not in session or session["username"] not in load_users():
        flash("Please log in to access peers.", "error")
        return redirect("/login")
    
    language = session.get('language', 'en')
    template_name = "peers-fa.html" if language == "fa" else "peers.html"
    return render_template(template_name)

@app.route("/settings")
def settings():
    if "username" not in session:
        flash("Please log in to access settings.", "error")
        return redirect("/login")
    
    language = session.get('language', 'en')
    template_name = "settings-fa.html" if language == "fa" else "settings.html"
    return render_template(template_name)


@app.route('/api/flask-config', methods=['GET'])
def obtain_flask_config():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "config.yaml")

        with open(config_path, "r") as file:
            config = yaml.safe_load(file)

        flask_config = config.get("flask", {})
        if not flask_config:
            return jsonify({"message": "Flask config not found in config.yaml"}), 404

        return jsonify({
            "port": flask_config.get("port", 5000),
            "tls": flask_config.get("tls", False)
        })
    except FileNotFoundError:
        return jsonify({"message": "config.yaml file not found."}), 404
    except Exception as e:
        return jsonify({"message": f"error in retrieving Flask config: {str(e)}"}), 500


@app.route("/api/update-flask-config", methods=["POST"])
def update_flask_config():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "config.yaml")

        data = request.json
        port = data.get("port")
        tls = data.get("tls")
        cert_path = data.get("cert_path")
        key_path = data.get("key_path")

        if port is None or tls is None:
            return jsonify({"message": "Both port and TLS settings are required."}), 400

        if not isinstance(port, int) or port < 1 or port > 65535:
            return jsonify({"message": "Port must be an integer between 1 and 65535."}), 400

        if not isinstance(tls, bool):
            return jsonify({"message": "TLS setting must be a boolean (true/false)."}), 400

        try:
            with open(config_path, "r") as file:
                config = yaml.safe_load(file)
                existing_port = config.get("flask", {}).get("port")
        except FileNotFoundError:
            config = {"flask": {}, "wireguard": {}}
            existing_port = None

        config["flask"]["port"] = port
        config["flask"]["tls"] = tls

        if tls:
            if not cert_path or not key_path:
                return jsonify({"message": "TLS is enabled but cert_path or key_path not provided."}), 400
            config["flask"]["cert_path"] = cert_path
            config["flask"]["key_path"] = key_path
        else:
            config["flask"]["cert_path"] = ""
            config["flask"]["key_path"] = ""

        with open(config_path, "w") as file:
            yaml.dump(config, file, default_flow_style=False)

        response = {
            "message": "Flask config updated successfully.",
            "port": port,
            "tls": tls
        }

        if existing_port != port:
            try:
                service_name = "wireguard-panel.service"

                subprocess.run(
                    ["systemctl", "restart", service_name],  
                    check=True, 
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True  
                )
                response["service_restart"] = "wireguard-panel.service restarted successfully."
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.strip() if e.stderr else str(e)
                return jsonify({
                    "message": "Flask config updated, but failed to restart Wireguard-panel.service.",
                    "error": error_msg
                }), 500

        return jsonify(response), 200

    except yaml.YAMLError as yaml_error:
        return jsonify({"message": f"YAML error while updating config: {yaml_error}"}), 500
    except Exception as e:
        return jsonify({"message": f"error in updating Flask config: {e}"}), 500


@app.route('/api/update-user', methods=['POST'])
def update_user():
    if 'username' not in session:
        return jsonify({'error': 'You must be logged in to update your account.'}), 403

    data = request.get_json(silent=True) or {}
    new_username = str(data.get("username") or "").strip()
    new_password = str(data.get("password") or "")
    if not new_username or not new_password:
        return jsonify({'error': 'Both username and password are required.'}), 400

    try:
        users = load_users()
        current_user = session['username']

        if new_username != current_user and new_username in users:
            return jsonify({'error': 'The new username already exists!'}), 400

        users.pop(current_user, None)
        hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
        users[new_username] = hashed_password

        save_users(users)
        session['username'] = new_username
        return jsonify({'message': 'Username and password updated successfully!'}), 200
    except Exception as e:
        app.logger.exception("error in updating user")
        return jsonify({'error': f'An error occurred while updating the user: {e}'}), 500


@app.route('/api/update-wireguard-config', methods=['POST'])
def update_wireguard_config():
    data = request.json
    config_name = data.get('config')
    port = data.get('port')
    mtu = data.get('mtu')
    dns = data.get('dns')

    if not config_name:
        return jsonify({"message": "Config name is required"}), 400

    config_path = f"/etc/wireguard/{config_name}"
    if not config_name.endswith(".conf"):
        config_path += ".conf"

    if not os.path.isfile(config_path):
        return jsonify({"message": f"Configuration file '{config_path}' not found"}), 404

    try:
        with open(config_path, "r") as file:
            config_data = file.readlines()

        updated_config = []
        for line in config_data:
            if port and line.startswith("ListenPort"):
                updated_config.append(f"ListenPort = {port}\n")
            elif port and "PostUp = iptables -I INPUT -p udp --dport" in line:
                updated_config.append(f"PostUp = iptables -I INPUT -p udp --dport {port} -j ACCEPT\n")
            elif port and "PostDown = iptables -D INPUT -p udp --dport" in line:
                updated_config.append(f"PostDown = iptables -D INPUT -p udp --dport {port} -j ACCEPT\n")
            elif mtu and line.startswith("MTU"):
                updated_config.append(f"MTU = {mtu}\n")
            elif dns and line.startswith("DNS"):
                updated_config.append(f"DNS = {dns}\n")
            else:
                updated_config.append(line)

        with open(config_path, "w") as file:
            file.writelines(updated_config)

        return jsonify({"message": "Wireguard config updated successfully!"})
    except Exception as e:
        return jsonify({"message": f"Couldn't update Wireguard config: {str(e)}"}), 500


@app.route('/api/user-info', methods=['GET'])
def obtain_user_info():
    try:
        current_user = session.get('username')
        if not current_user:
            return jsonify({"error": "User not logged in"}), 401
        return jsonify({"username": current_user})
    except Exception as e:
        return jsonify({"error": f"Couldn't load user info: {e}"}), 500

@app.route("/api/backups", methods=["GET"])
def list_manual_backups():
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        backups = [
            f for f in os.listdir(BACKUP_DIR)
            if f.startswith("manual_") and f.endswith(".backup.zip")
        ]
        return jsonify(backups=backups)
    except Exception as e:
        logging.error(f"Couldn't list backups: {e}")
        return jsonify(error=f"Couldn't list backups: {e}"), 500
   
@app.route("/api/create-backup", methods=["POST"])
def create_backup():
    try:
        backup_name = f"manual_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.backup.zip"
        backup_path = os.path.join(BACKUP_DIR, backup_name)

        temp_dir = tempfile.mkdtemp()
        try:
  
            wireguard_backup_dir = os.path.join(temp_dir, "wireguard")
            os.makedirs(wireguard_backup_dir, exist_ok=True)
            if os.path.exists(WIREGUARD_CONFIG_DIR):
                for file in os.listdir(WIREGUARD_CONFIG_DIR):
                    if file.endswith(".conf"):
                        shutil.copy2(
                            os.path.join(WIREGUARD_CONFIG_DIR, file),
                            os.path.join(wireguard_backup_dir, file),
                        )

            db_backup_dir = os.path.join(temp_dir, "db")
            if os.path.exists(db_backup_dir):
                shutil.rmtree(db_backup_dir)
            shutil.copytree(DB_DIR, db_backup_dir)

            if os.path.exists(SQLITE_FILE):
                sqlite_tmp = os.path.join(db_backup_dir, "db.sqlite3")
                try:
                    with sqlite3.connect(f"file:{SQLITE_FILE}?mode=ro", uri=True) as src_conn:
                        with sqlite3.connect(sqlite_tmp) as dst_conn:
                            src_conn.backup(dst_conn)
                    shutil.copystat(SQLITE_FILE, sqlite_tmp)
                except Exception as e:
                    logging.warning(f"SQLite backup API failed in manual zip: {e}")
                    shutil.copy2(SQLITE_FILE, sqlite_tmp)
                    for ext in ("-wal", "-shm"):
                        wal_src = SQLITE_FILE + ext
                        if os.path.exists(wal_src):
                            shutil.copy2(wal_src, sqlite_tmp + ext)

            links_backup_dir = os.path.join(temp_dir, "links")
            os.makedirs(links_backup_dir, exist_ok=True)
            if os.path.exists(SHORT_LINKS_FILE):
                shutil.copy2(SHORT_LINKS_FILE, os.path.join(links_backup_dir, os.path.basename(SHORT_LINKS_FILE)))
            if os.path.exists(DECRYPTED_LINKS_FILE):
                shutil.copy2(DECRYPTED_LINKS_FILE, os.path.join(links_backup_dir, os.path.basename(DECRYPTED_LINKS_FILE)))

            shutil.make_archive(backup_path.replace(".zip", ""), 'zip', temp_dir)
        finally:
            shutil.rmtree(temp_dir)

        return jsonify(message=f"Backup created successfully as {backup_name}.")
    except Exception as e:
        logging.error(f"error in creating backup: {e}")
        return jsonify(error=f"Couldn't create backup: {e}"), 500


    try:
        data = request.json
        folder = data.get("folder")  
        backup_name = data.get("backupName")
        if not folder or not backup_name:
            return jsonify(error="Folder and backup name are required."), 400

        backup_dir = os.path.join(BACKUP_DIR, folder)
        backup_path = os.path.join(backup_dir, backup_name)
        if not os.path.exists(backup_path):
            return jsonify(error="Backup not found."), 404

        if folder == "wireguard":
            base_name = os.path.splitext(backup_name.split("_")[0])[0]
            dest_path = os.path.join(WIREGUARD_CONFIG_DIR, f"{base_name}.conf")
            shutil.copy2(backup_path, dest_path)
        elif folder == "db":
            base_name = os.path.splitext(backup_name.split("_")[0])[0]
            dest_path = os.path.join(DB_DIR, f"{base_name}.json")
            shutil.copy2(backup_path, dest_path)
        else:
            return jsonify(error="Wrong folder specified."), 400

        return jsonify(message=f"Backup {backup_name} restored successfully.")
    except Exception as e:
        logging.error(f"Couldn't restore automated backup: {e}")
        return jsonify(error=f"Couldn't restore automated backup: {e}"), 500

@app.route("/api/delete-backup", methods=["DELETE"])
def delete_backup():
    try:
        backup_name = request.args.get("name")
        folder = request.args.get("folder") 

        print(f"Received backup_name: {backup_name}, folder: {folder}")

        if not backup_name:
            return jsonify(error="Backup name is required."), 400

        if folder == "wireguard":
            backup_dir = os.path.join(BACKUP_DIR, "wireguard")
        elif folder == "db":
            backup_dir = os.path.join(BACKUP_DIR, "db")
        elif folder == "root" or folder is None:  
            backup_dir = BACKUP_DIR
        else:
            return jsonify(error="Wrong folder specified."), 400

        backup_path = os.path.join(backup_dir, backup_name)

        if not os.path.exists(backup_path):
            return jsonify(error="Backup not found."), 404

        os.remove(backup_path)
        return jsonify(message=f"Backup {backup_name} deleted successfully.")
    except Exception as e:
        logging.error(f"error in deleting backup: {e}")
        return jsonify(error=f"Couldn't delete backup: {e}"), 500

@app.route("/api/restore-backup", methods=["POST"])
def restore_backup():
    try:
        data = request.json
        backup_name = data.get("backupName")
        if not backup_name:
            return jsonify(error="Backup name is required."), 400

        if not re.match(r"^[\w\-]+\.backup\.zip$", backup_name):
            return jsonify(error="Wrong backup name."), 400

        backup_path = os.path.join(BACKUP_DIR, backup_name)
        if not os.path.exists(backup_path):
            return jsonify(error="Backup not found."), 404

        temp_dir = tempfile.mkdtemp()
        try:
            logging.info(f"Extracting backup {backup_name} to temporary directory {temp_dir}")
            shutil.unpack_archive(backup_path, temp_dir, "zip")

            wireguard_dir = os.path.join(temp_dir, "wireguard")
            if os.path.exists(wireguard_dir):
                os.makedirs(WIREGUARD_CONFIG_DIR, exist_ok=True)
                for file in os.listdir(wireguard_dir):
                    if file.endswith(".conf"):
                        src = os.path.join(wireguard_dir, file)
                        dest = os.path.join(WIREGUARD_CONFIG_DIR, file)
                        try:
                            shutil.copy2(src, dest)
                            logging.info(f"Restored Wireguard config: {file} -> {WIREGUARD_CONFIG_DIR}")
                        except Exception as e:
                            logging.error(f"error in restoring Wireguard config {file}: {e}")
                            return jsonify(error=f"Couldn't restore Wireguard config: {file}"), 500

            db_dir = os.path.join(temp_dir, "db")
            if os.path.exists(db_dir):
                for file in os.listdir(db_dir):
                    if file.endswith(".json"):
                        src = os.path.join(db_dir, file)
                        dest = os.path.join(DB_DIR, file)
                        try:
                            shutil.copy2(src, dest)
                            logging.info(f"Restored database file: {file} -> {DB_DIR}")
                        except Exception as e:
                            logging.error(f"error in restoring database file {file}: {e}")
                            return jsonify(error=f"Couldn't restore database file: {file}"), 500


                sqlite_in_zip = os.path.join(db_dir, "db.sqlite3")
                if os.path.exists(sqlite_in_zip):
                    try:
                        with sqlite3.connect(f"file:{sqlite_in_zip}?mode=ro", uri=True) as src_conn:
                            with sqlite3.connect(SQLITE_FILE) as dst_conn:
                                src_conn.backup(dst_conn)
                        shutil.copystat(sqlite_in_zip, SQLITE_FILE)
                        logging.info(f"SQLite restored from manual zip to {SQLITE_FILE}")
                    except Exception as e:
                        logging.warning(f"SQLite online restore (manual zip) failed, fallback to file copy: {e}")
                        shutil.copy2(sqlite_in_zip, SQLITE_FILE)

            return jsonify(message=f"Backup {backup_name} restored successfully.")
        except shutil.ReadError as e:
            logging.error(f"Backup file is not a valid archive: {e}")
            return jsonify(error="Backup file is not a valid archive."), 400
        except Exception as e:
            logging.error(f"Couldn't restore backup: {e}")
            return jsonify(error=f"Couldn't restore backup: {e}"), 500
        finally:
            shutil.rmtree(temp_dir)
            logging.info(f"Temporary directory {temp_dir} removed after restore.")
    except Exception as e:
        logging.error(f"error in restoring backup: {e}")
        return jsonify(error=f"Couldn't restore backup: {e}"), 500

@app.route("/api/auto-backups", methods=["GET"])
def list_auto_backups():
    folder = request.args.get("folder")
    if folder not in ["wireguard", "db"]:
        return jsonify(error="Wrong folder specified."), 400

    backup_dir = os.path.join(BACKUP_DIR, folder)

    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir, exist_ok=True) 
        logging.info(f"Created missing backup folder: {backup_dir}")

    backups = [f for f in os.listdir(backup_dir) if os.path.isfile(os.path.join(backup_dir, f))]

    if not backups:
        return jsonify(backups=[])

    backups.sort(reverse=True)  
    
    return jsonify(backups=backups)

@app.route("/api/restore-automated-backup", methods=["POST"])
def restore_automated_backup():
    try:
        data = request.json or {}
        folder = data.get("folder")            
        backup_name = data.get("backupName")

        if folder not in ["wireguard", "db"]:
            return jsonify(error="Wrong folder specified. Use 'wireguard' or 'db'."), 400

        backup_dir = os.path.join(BACKUP_DIR, folder)
        if not os.path.exists(backup_dir):
            return jsonify(error=f"Backup folder {folder} does not exist."), 404

        def restore_sqlite_file(src_sqlite_path: str):
            os.makedirs(os.path.dirname(SQLITE_FILE), exist_ok=True)
            try:
                with sqlite3.connect(f"file:{src_sqlite_path}?mode=ro", uri=True) as src_conn:
                    with sqlite3.connect(SQLITE_FILE) as dst_conn:
                        src_conn.backup(dst_conn)
                shutil.copystat(src_sqlite_path, SQLITE_FILE)
                logging.info(f"SQLite restored to {SQLITE_FILE} from {src_sqlite_path}")
            except Exception as e:
                logging.warning(f"SQLite online restore failed, fallback to file copy: {e}")
                shutil.copy2(src_sqlite_path, SQLITE_FILE)
            
                for ext in ("-wal", "-shm"):
                    wal_src = src_sqlite_path + ext
                    if os.path.exists(wal_src):
                        shutil.copy2(wal_src, SQLITE_FILE + ext)

        def restore_one(folder_name: str, file_name: str):
            src_path = os.path.join(backup_dir, file_name)
            if folder_name == "wireguard":
                if not file_name.endswith(".conf") and "_" in file_name and file_name.split("_")[0].endswith(".conf"):
                    base_conf = file_name.split("_")[0]
                    dst_path = os.path.join(WIREGUARD_CONFIG_DIR, base_conf)
                else:
                    dst_path = os.path.join(WIREGUARD_CONFIG_DIR, file_name)
                shutil.copy2(src_path, dst_path)
                logging.info(f"Restored Wireguard config: {file_name} -> {dst_path}")
            elif folder_name == "db":
                if file_name.startswith("db.sqlite3"):
                    restore_sqlite_file(src_path)
                elif file_name.endswith(".json") or ".json_" in file_name:
                    base_json = file_name.split("_")[0]
                    dst_path = os.path.join(DB_DIR, base_json)
                    shutil.copy2(src_path, dst_path)
                    logging.info(f"Restored JSON DB file: {file_name} -> {dst_path}")

        if backup_name:
            backup_path = os.path.join(backup_dir, backup_name)
            if not os.path.exists(backup_path):
                return jsonify(error="Backup not found."), 404
            restore_one(folder, backup_name)
        else:
            for file in sorted(os.listdir(backup_dir)):
                restore_one(folder, file)

        return jsonify(message=f"Backup from {folder} restored successfully.")
    except Exception as e:
        logging.error(f"Couldn't restore automated backup: {e}")
        return jsonify(error=f"Couldn't restore automated backup: {e}"), 500

@app.route("/backups", methods=["GET"])
def backups_page():
    if "username" not in session:
        flash("Please log in to access backups.", "error")
        return redirect("/login")

    language = session.get('language', 'en') 
    template_name = "backups-fa.html" if language == "fa" else "backups.html"
    return render_template(template_name)


@app.route("/api/download-backup", methods=["GET"])
def download_backup():
    backup_name = request.args.get("name")
    if not backup_name:
        return jsonify(error="Backup name is required."), 400

    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.exists(backup_path):
        return jsonify(error="Backup not found."), 404

    try:
        return send_from_directory(BACKUP_DIR, backup_name, as_attachment=True)
    except Exception as e:
        return jsonify(error=f"Couldn't download backup: {e}"), 500

@app.route("/api/reset-user", methods=["POST"])
def api_reset_user():
    try:
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")

        if not username or not password:
            return jsonify({"error": "Username and password required"}), 400

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        users = {username: hashed_password}

        with open(DB_FILE, "w") as f:
            json.dump(users, f)

        return jsonify({"message": "Credentials reset successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


from sqlite_backend import load_users, save_users


@app.route("/logout")
def logout():
    session.pop("username", None)
    response = make_response(redirect("/login"))
    response.delete_cookie("username") 
    flash("You have been logged out.", "success")
    return response

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("wireguard.log"),  
        logging.StreamHandler()  
    ]
)

class SuppressNoDeviceFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        suppressed_patterns = [
            "No such device",
            "Non-critical error for interface",
            "Unable to access interface: No such device"
            
        ]
        return not any(pattern in message for pattern in suppressed_patterns)

def obtain_disk_usage():
    try:
        total, used, free = shutil.disk_usage("/")
        return {
            "total": f"{total // (1024**3)} GB",
            "used": f"{used // (1024**3)} GB",
            "free": f"{free // (1024**3)} GB",
            "percent": round((used / total) * 100, 2)
        }
    except Exception as e:
        print(f"error in fetching disk usage: {e}")
        return {"total": "N/A", "used": "N/A", "free": "N/A", "percent": "N/A"}


def calculate_cpu_usage():

    try:
        with open('/proc/stat', 'r') as f:
            lines = f.readlines()

        cpu_line = lines[0] 
        stats = list(map(int, cpu_line.split()[1:]))
        idle_time, total_time = stats[3], sum(stats)

        if not hasattr(calculate_cpu_usage, "last_idle"):
            calculate_cpu_usage.last_idle = idle_time
            calculate_cpu_usage.last_total = total_time

        idle_delta = idle_time - calculate_cpu_usage.last_idle
        total_delta = total_time - calculate_cpu_usage.last_total

        calculate_cpu_usage.last_idle = idle_time
        calculate_cpu_usage.last_total = total_time

        if total_delta == 0:
            return 0.0

        usage_percentage = (1 - idle_delta / total_delta) * 100

        if usage_percentage < 0.01:  
            return 0.01

        return round(usage_percentage, 2) 
    except Exception as e:
        print(f"error in calculating CPU usage: {e}")
        return None

def valid_private_key(key: str) -> bool:
    try:
        decoded = base64.b64decode(key)
        is_valid = len(decoded) == 32
        print(f"Decoded Key Valid: {is_valid}, Length: {len(decoded)}")  
        return is_valid
    except Exception as e:
        print(f"error in validating PrivateKey: {e}")
        return False

@app.route('/api/interface-status', methods=['GET'])
def interface_status():
    try:
        wg_path = "wg"  

        if not os.path.isfile(wg_path) or not os.access(wg_path, os.X_OK):
            return jsonify({"error": f"wg command not found or not executable at {wg_path}"}), 500

        result = subprocess.run(
            [wg_path, "show"],  
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )

        if result.stdout:
            return jsonify({"status": "up"}), 200
        else:
            return jsonify({"status": "down"}), 200
    except subprocess.CalledProcessError as e:
        return jsonify({"status": "down", "error": e.stderr}), 200
    except Exception as e:

        print(f"Unexpected error: {e}")
        return jsonify({"error": "An unexpected error occurred."}), 500

@app.route('/api/toggle-interface', methods=['POST'])
def toggle_interface():
    action = request.args.get('action')
    config_file = request.args.get('config', 'wg0.conf')

    if action not in ['up', 'down']:
        return jsonify(error="Wrong action. Must be 'up' or 'down'."), 400

    interface = config_file.split(".")[0] 
    sanitized_interface = sanitize_input(interface)  

    try:
        wg_quick_path = "wg-quick"  

        command_down = [wg_quick_path, "down", sanitized_interface]
        command_up = [wg_quick_path, "up", sanitized_interface]

        if action == "down":
            subprocess.run(command_down, check=False, stderr=subprocess.PIPE, text=True)
            is_active = False
        else:
            subprocess.run(command_down, check=False, stderr=subprocess.PIPE, text=True)
            subprocess.run(command_up, check=True, stderr=subprocess.PIPE, text=True)
            is_active = True

        # 📌 همگام‌سازی آنی وضعیت فعال/غیرفعال wg0 یا هر اینترفیس دیگر با تمام Nodeها
        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_interface_state_to_edges(sanitized_interface, is_active, wait=True)
        except Exception as e_sync:
            app.logger.warning(f"Failed to sync interface toggle to edge nodes: {e_sync}")

        return jsonify(success=True, message=f"Interface '{sanitized_interface}' has been turned {action}.")

    except subprocess.CalledProcessError as e:
        return jsonify(success=False, error=e.stderr if e.stderr else str(e)), 500
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500


@app.route("/api/toggle-config", methods=["POST"])
def toggle_config():
    config_file = request.args.get("config", "wg0.conf")
    if not config_file:
        return jsonify(error="Configuration file is required."), 400

    try:
        interface_name = sanitize_interface_name(config_file.split(".")[0])
    except ValueError as e:
        return jsonify(error=str(e)), 400

    active = request.args.get("active", "false").lower() == "true"
    wg_quick_path = "wg-quick"  

    try:
        if active:
            result = subprocess.run([wg_quick_path, "up", interface_name], check=False, capture_output=True, text=True)
        else:
            result = subprocess.run([wg_quick_path, "down", interface_name], check=False, capture_output=True, text=True)

        ip_path = "ip" 
        interface_state = subprocess.run([ip_path, "link", "show", interface_name], capture_output=True, text=True)
        is_active = "state UNKNOWN" in interface_state.stdout or "state UP" in interface_state.stdout

        # 📌 همگام‌سازی آنی با تمام Nodeها
        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_interface_state_to_edges(interface_name, is_active, wait=True)
        except Exception as e_sync:
            app.logger.warning(f"Failed to sync config toggle to edge nodes: {e_sync}")

        return jsonify(
            message=f"Configuration '{config_file}' has been {'enabled' if is_active else 'disabled'}.",
            active=is_active,
            output=result.stdout + result.stderr,
        )
    except Exception as e:
        return jsonify(error=str(e)), 500

def hash_out_peer(peer_ip, config_file="wg0.conf"):

    config_path = os.path.join(DB_DIR, config_file)

    try:
        with open(config_path, "r") as file:
            lines = file.readlines()

        updated_lines = []
        skip_block = False
        for line in lines:
            if line.startswith("[Peer]"):
                skip_block = False
            if peer_ip in line:
                skip_block = True  
            if not skip_block:
                updated_lines.append(line)
            else:
                updated_lines.append(f"# {line.strip()}\n")  

        with open(config_path, "w") as file:
            file.writelines(updated_lines)

        print(f"Hashed out peer {peer_ip} in {config_file}")
    except Exception as e:
        print(f"error in hashing out peer {peer_ip} in {config_file}: {e}")

def restart_wireguard_interface(interface="wg0"):
    try:
        sanitized_interface = sanitize_interface_name(interface)

        wg_quick_path = "wg-quick" 
        
        subprocess.run([wg_quick_path, "down", sanitized_interface], check=True)
        subprocess.run([wg_quick_path, "up", sanitized_interface], check=True)
        
        print(f"Restarted Wireguard interface: {sanitized_interface}")
    except subprocess.CalledProcessError as e:
        print(f"error in restarting Wireguard interface {sanitized_interface}: {e}")
    except ValueError as e:
        print(f"Error: {e}")


def recover_from_backup(config_name: str):
    backup_dir = "backups"
    base_name = config_name.split(".")[0]
    backups = [f for f in os.listdir(backup_dir) if f.startswith(base_name)]
    if not backups:
        print(f"No backups found for {config_name}.")
        return []

    backups.sort(reverse=True)
    latest_backup = os.path.join(backup_dir, backups[0])
    try:
        with open(latest_backup, "r") as f:
            print(f"Recovering from backup: {latest_backup}")
            return json.load(f)
    except Exception as e:
        print(f"Couldn't recover from backup {latest_backup}: {e}")
        return []

monitor_lock = Lock()  

@app.route("/api/reset-traffic", methods=["POST"])
def reset_traffic():
    try:
        data = request.json or {}
        peer_name = data.get("peerName")
        config_name = data.get("config", "wg0.conf")
        clean_cfg = config_name if config_name.endswith(".conf") else f"{config_name}.conf"
        iface = clean_cfg.replace(".conf", "")

        if not peer_name:
            return jsonify(error="Peer name is required."), 400

        with _db_lock, _connect() as con:
            cur = con.cursor()
            # ۱. استخراج ترافیک مصرفی فعلی کلاینت قبل از ریست
            cur.execute("SELECT used, public_key, peer_ip FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
            row = cur.fetchone()
            if not row:
                return jsonify(error=f"Peer '{peer_name}' not found."), 404

            old_used = int(row["used"] or 0)
            public_key = row["public_key"]
            peer_ip = row["peer_ip"]

            # ۲. واریز ترافیک مصرف‌شده به صندوق دائمی اینترفیس و سرور
            if old_used > 0:
                record_deleted_traffic_atomic(iface, old_used)

            # ۳. صفر کردن مصرف کلاینت
            cur.execute("UPDATE peers SET used=0, local_used=0, last_received_bytes=0, last_sent_bytes=0 WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
            cur.execute("UPDATE peer_synced_edges SET node_used=0, last_bytes=0 WHERE peer_name=? AND config=?", (peer_name, clean_cfg))
            con.commit()

        # ۴. ریست کارت شبکه
        reset_peer_traffic(iface, public_key, peer_ip)

        # ۵. همگام‌سازی ریست روی سرورهای لبه (Edge)
        sync_single_peer_action_to_edges('reset', peer_name, clean_cfg)

        return jsonify(
            success=True,
            message=f"ترافیک کلاینت '{peer_name}' ریست شد و ترافیک قبلی در صندوق دائمی اینترفیس ثبت گردید."
        )
    except Exception as e:
        return jsonify(error=f"Error resetting traffic: {e}"), 500


@app.route("/api/reset-expiry", methods=["POST"])
def reset_expiry():
    try:
        data = request.json
        peer_name = data.get("peerName")
        config_name = data.get("config", "wg0.conf")  

        if not peer_name:
            return jsonify(error="Peer name is required."), 400

        with json_lock:  
            peers = load_peers_with_lock(config_name)

            peer = next((p for p in peers if p["peer_name"] == peer_name), None)
            if not peer:
                return jsonify(error=f"Peer '{peer_name}' not found in {config_name}."), 404

            expiry_duration = calculate_expiry_duration(peer.get("expiry_time", {}))  
            peer["remaining_time"] = expiry_duration  

            save_peers_with_lock(config_name, peers)

        return jsonify(
            success=True,
            message=f"Expiry time for peer '{peer_name}' in {config_name} has been reset.",
        )
    except Exception as e:
        print(f"error in resetting expiry: {e}")
        return jsonify(error=f"error in resetting expiry: {e}"), 500

def calculate_expiry_duration(expiry_config):

    months = expiry_config.get("months", 0) * 30 * 24 * 60  
    days = expiry_config.get("days", 0) * 24 * 60
    hours = expiry_config.get("hours", 0) * 60
    minutes = expiry_config.get("minutes", 0)
    return months + days + hours + minutes
def sanitize_ip(ip_str: str) -> str:
    """اعتبارسنجی و پاکسازی IPv4"""
    if not ip_str or not isinstance(ip_str, str):
        return ""
    cleaned = ip_str.strip()
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", cleaned):
        return cleaned
    return ""

def sanitize_public_key(pub_key: str) -> str:
    """اعتبارسنجی و پاکسازی کلید عمومی وایرگارد"""
    if not pub_key or not isinstance(pub_key, str):
        return ""
    cleaned = pub_key.strip()
    if re.match(r"^[A-Za-z0-9+/=]{43,44}$", cleaned):
        return cleaned
    return ""

def sanitize_interface_name(iface: str) -> str:
    """پاکسازی نام اینترفیس (پیش‌فرض wg0)"""
    if not iface or not isinstance(iface, str):
        return "wg0"
    cleaned = iface.replace(".conf", "").strip()
    if re.match(r"^[a-zA-Z0-9_-]+$", cleaned):
        return cleaned
    return "wg0"

def sanitize_input(val: str) -> str:
    """پاکسازی عمومی رشته‌ها برای جلوگیری از Command Injection"""
    if val and re.match(r"^[a-zA-Z0-9_.-]+$", str(val).strip()):
        return str(val).strip()
    raise ValueError(f"Invalid input: {val}")

def add_blackhole_route(peer_ip):
    try:
        sanitized_ip = sanitize_ip(peer_ip)
        ip_path = "ip"

        check_route = subprocess.run(
            [ip_path, "route", "show", f"{sanitized_ip}/32"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if check_route.returncode == 0:
            if f"blackhole {sanitized_ip}" in check_route.stdout:
                print(f"Blackhole route already exists for {sanitized_ip}. Skipping.")
                return True  

            print(f"Existing non-blackhole route found for {sanitized_ip}. Removing it.")
            remove_route = subprocess.run(
                [ip_path, "route", "del", f"{sanitized_ip}/32"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if remove_route.returncode != 0:
                print(f"error in removing existing route for {sanitized_ip}: {remove_route.stderr.strip()}")
        else:
            print(f"no existing route found for {sanitized_ip}. adding blackhole route.")

        add_route = subprocess.run(
            [ip_path, "route", "add", "blackhole", f"{sanitized_ip}/32"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if add_route.returncode == 0:
            print(f"Successfully added blackhole route for {sanitized_ip}")
            return True
        else:
            print(f"error in adding blackhole route for {sanitized_ip}: {add_route.stderr.strip()}")
            return False

    except subprocess.CalledProcessError as e:
        print(f"error in IP route command for {sanitized_ip}: {e}")
        return False
    except ValueError as e:
        print(f"wrong IP address provided: {e}")
        return False


def remove_blackhole_route(peer_ip):
    try:
        sanitized_ip = sanitize_ip(peer_ip)
        ip_path = "ip"

        check_route = subprocess.run(
            [ip_path, "route", "show", f"{sanitized_ip}/32"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if check_route.returncode == 0 and f"dev" in check_route.stdout:
            print(f"Route exists for {sanitized_ip}, but it is not a blackhole route. Not removing.")
            return False

        if check_route.returncode != 0 or f"blackhole {sanitized_ip}" not in check_route.stdout:
            print(f"No blackhole route found for {sanitized_ip}. Nothing to remove.")
            return False

        subprocess.run([ip_path, "route", "del", "blackhole", f"{sanitized_ip}/32"], check=True)
        print(f"Successfully removed blackhole route for {sanitized_ip}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"error in removing blackhole route for {sanitized_ip}: {e}")
        return False
    except ValueError as e:
        print(f"Invalid IP address provided: {e}")
        return False

@app.route('/api/generate-template', methods=['POST'])
def generate_template():
    try:
        data = request.json
        peer_name = data.get("peer_name")
        config_name = data.get("config_name") 

        if not peer_name or not config_name:
            app.logger.error("Peer name and config name are required.")
            return jsonify({"error": "Peer name and config name are required."}), 400

        db_file_name = f"{config_name}.json" 
        db_path = os.path.join("db", db_file_name)
        if not os.path.exists(db_path):
            app.logger.error(f"Configuration file '{db_file_name}' not found in 'db'.")
            return jsonify({"error": f"Configuration file '{db_file_name}' not found in 'db'."}), 404

        with open(db_path, "r") as db_file:
            peers = json.load(db_file)

        peer = next((p for p in peers if p["peer_name"] == peer_name), None)
        if not peer:
            app.logger.error(f"Peer '{peer_name}' not found in '{db_file_name}'.")
            return jsonify({"error": f"Peer '{peer_name}' not found in '{db_file_name}'"}), 404

        peer_ip = peer.get("peer_ip", "N/A")
        dns = peer.get("dns", "N/A")
        data_limit = peer.get("limit", "N/A")
        expiry_time = peer.get("expiry_time", {})
        expiry = f"{expiry_time.get('months', 0)} months, {expiry_time.get('days', 0)} days"
        persistent_keepalive = peer.get("persistent_keepalive", 25)
        mtu = peer.get("mtu", 1280)
        private_key = peer.get("private_key", "N/A")
        public_key = peer.get("public_key", "N/A")
        allowed_ips = peer.get("allowed_ips") or "0.0.0.0/0, ::/0"

        server_ip = obtain_server_public_ip()
        wg_config_file = f"{config_name}.conf"
        server_port = server_listen_port(wg_config_file)  

        qr_data = f"""
[Interface]
PrivateKey = {private_key}
Address = {peer_ip}/32
DNS = {dns}
MTU = {mtu}

[Peer]
PublicKey = {public_key}
AllowedIPs = {allowed_ips}
Endpoint = {server_ip}:{server_port}
PersistentKeepalive = {persistent_keepalive}
""".strip()

        app.logger.debug(f"Generated QR Data: {qr_data}")

        return jsonify({
            "peer_name": peer_name,
            "peer_ip": peer_ip,
            "data_limit": data_limit,
            "expiry": expiry,
            "qr_data": qr_data
        }), 200

    except Exception as e:
        app.logger.exception("Couldn't generate template.")
        return jsonify({"error": f"Couldn't generate template: {str(e)}"}), 500


@app.route('/api/delete-template', methods=['POST'])
def delete_template():

    try:
        data = request.json
        filename = data.get("filename")

        if not filename:
            return jsonify({"error": "Filename is required."}), 400

        file_path = os.path.join("static", "generated", filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({"message": f"File '{filename}' deleted successfully."}), 200
        else:
            return jsonify({"error": f"File '{filename}' not found."}), 404

    except Exception as e:
        app.logger.error(f"Couldn't delete file: {str(e)}", exc_info=True)
        return jsonify({"error": f"Couldn't delete file: {str(e)}"}), 500

@app.route("/api/block-peer", methods=["POST"])
def block_peer():
    try:
        data = request.json
        peer_name = data.get("peerName")
        config_name = data.get("config", "wg0.conf")

        if not peer_name:
            return jsonify(error="Peer name is required."), 400

        with json_lock:  
            peers = load_peers_with_lock(config_name)  

            peer = next((p for p in peers if p["peer_name"] == peer_name), None)
            if not peer:
                return jsonify(error=f"Peer '{peer_name}' not found in {config_name}."), 404

            if peer.get("monitor_blocked", False) and peer.get("expiry_blocked", False):
                return jsonify(
                    success=True,
                    message=f"Peer {peer_name} in {config_name} is already blocked."
                )

            print(f"Blocking IP: {peer['peer_ip']} for {config_name}")
            success = add_blackhole_route(peer["peer_ip"])
            if not success:
                return jsonify(error=f"Couldn't block peer {peer_name} in {config_name}."), 500

            peer["monitor_blocked"] = True
            peer["expiry_blocked"] = True

            save_peers_with_lock(config_name, peers)

        return jsonify(
            success=True,
            blocked=True,
            message=f"Peer {peer_name} in {config_name} has been blocked."
        )
    except Exception as e:
        print(f"error in blocking peer: {e}")
        return jsonify(error=str(e)), 500


@app.route("/api/unblock-peer", methods=["POST"])
def unblock_peer():
    try:
        data = request.json
        peer_name = data.get("peerName")
        config_name = data.get("config", "wg0.conf")

        if not peer_name:
            return jsonify(error="Peer name is required."), 400

        with json_lock:  
            peers = load_peers_with_lock(config_name)  

            peer = next((p for p in peers if p["peer_name"] == peer_name), None)
            if not peer:
                return jsonify(error=f"Peer '{peer_name}' not found in {config_name}."), 404

            if not peer.get("monitor_blocked", False) and not peer.get("expiry_blocked", False):
                return jsonify(
                    success=True,
                    message=f"Peer {peer_name} in {config_name} is already unblocked."
                )

            print(f"Unblocking IP: {peer['peer_ip']} for {config_name}")
            success = remove_blackhole_route(peer["peer_ip"])
            if not success:
                return jsonify(error=f"Couldn't unblock peer {peer_name} in {config_name}."), 500

            peer["monitor_blocked"] = False
            peer["expiry_blocked"] = False

            save_peers_with_lock(config_name, peers)

        return jsonify(
            success=True,
            blocked=False,
            message=f"Peer {peer_name} in {config_name} has been unblocked."
        )
    except Exception as e:
        print(f"error in unblocking peer: {e}")
        return jsonify(error=str(e)), 500

    

def derive_public_key(private_key: str) -> str:

    try:
        private_key = private_key.strip()
        missing_padding = len(private_key) % 4
        if missing_padding:
            private_key += "=" * (4 - missing_padding)

        private_key_bytes = base64.b64decode(private_key)

        if len(private_key_bytes) != 32:
            raise ValueError("Wrong private key length. Expected 32 bytes.")

        public_key_bytes = nacl.bindings.crypto_scalarmult_base(private_key_bytes)

        public_key = base64.b64encode(public_key_bytes).decode("utf-8")
        return public_key
    except Exception as e:
        raise ValueError(f"Couldn't derive public key from private key: {e}")


def server_config_details(config_file: str) -> dict:

    config_path = os.path.join(WIREGUARD_CONFIG_DIR, config_file)
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file {config_file} not found.")

    private_key = None
    listen_port = None
    with open(config_path, "r") as file:
        for line in file:
            if line.startswith("PrivateKey"):
                private_key = line.split("=")[1].strip()
            if line.startswith("ListenPort"):
                listen_port = line.split("=")[1].strip()

    if not private_key:
        raise ValueError(f"No PrivateKey found in {config_file}.")
    if not listen_port:
        raise ValueError(f"No ListenPort found in {config_file}.")

    public_key = derive_public_key(private_key)
    return {"private_key": private_key, "public_key": public_key, "listen_port": listen_port}


def server_listen_port(config_file: str) -> str:

    config_path = os.path.join(WIREGUARD_CONFIG_DIR, config_file)
    listen_port = None
    with open(config_path, "r") as file:
        for line in file:
            if line.startswith("ListenPort"):
                listen_port = line.split("=")[1].strip()
    if not listen_port:
        raise ValueError(f"No ListenPort found in {config_file}.")
    return listen_port

def obtain_server_keys() -> dict:

    server_keys = {}
    for config_file in os.listdir(WIREGUARD_CONFIG_DIR):
        if config_file.endswith(".conf"):
            config_path = os.path.join(WIREGUARD_CONFIG_DIR, config_file)
            with open(config_path, "r") as file:
                private_key = None
                for line in file:
                    if line.strip().startswith("PrivateKey"):
                        private_key = line.split("=")[1].strip()
                        break
                if private_key:
                    public_key = derive_public_key(private_key)
                    server_keys[config_file] = (private_key, public_key)
                else:
                    print(f"No private key found in {config_file}.")
    return server_keys


def obtain_public_key_conf(config_name: str) -> str:

    try:
        server_details = server_config_details(config_name)
        return server_details['public_key']
    except Exception as e:
        raise ValueError(f"error in retrieving server public key: {e}")

try:
    server_keys = obtain_server_keys()
    for config, keys in server_keys.items():
        private_key, public_key = keys
        print(f"Config: {config}\nPrivateKey: {private_key}\nPublicKey: {public_key}\n")
except Exception as e:
    print(f"Error: {e}")

@app.route('/api/export-peer-qr', methods=['GET'])
def export_peer_qr():
    peer_name = request.args.get('peerName')
    config = request.args.get('config')

    if not peer_name or not config:
        return jsonify({"error": "Peer name and config are required"}), 400

    response = export_peer() 
    if response.status_code != 200:
        return response

    peer_config = response.get_data(as_text=True)

    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(peer_config)
    qr.make(fit=True)
    img = qr.make_image(fill="black", back_color="white")

    img_io = BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return send_file(img_io, mimetype="image/png", as_attachment=False, download_name=f"{peer_name}.png")

@app.route("/api/export-peer", methods=["GET"])
def export_peer():
    peer_name = request.args.get("peerName")
    config_file = request.args.get("config", "wg0.conf")
    if not peer_name:
        return jsonify(error="Peer name is required to export config."), 400

    try:
        peers = load_peers_from_json(config_file)
    except Exception as e:
        return jsonify(error=f"Error reading JSON for {config_file}: {str(e)}"), 500

    peer = next((p for p in peers if p["peer_name"] == peer_name and p["config"] == config_file), None)
    if not peer:
        return jsonify(error=f"Peer '{peer_name}' not found in {config_file}."), 404

    dns = peer.get("dns", "1.1.1.1")
    persistent_keepalive = peer.get("persistent_keepalive", 25)
    mtu = peer.get("mtu", 1280)

    try:
        server_public_key = obtain_public_key_conf(config_file)
        custom_ip = obtain_custom_ip()
        server_ip = custom_ip or obtain_server_public_ip()
        server_port = server_listen_port(config_file)
    except ValueError as e:
        return jsonify(error=f"Error retrieving server details: {e}"), 500

    address_cidr = f"{peer['peer_ip']}/32"
    allowed_ips = peer.get("allowed_ips") or "0.0.0.0/0, ::/0"

    peer_config = (
        f"[Interface]\n"
        f"PrivateKey = {peer['private_key']}\n"
        f"Address = {address_cidr}\n"
        f"DNS = {dns}\n"
        f"MTU = {mtu}\n"
        f"\n"
        f"[Peer]\n"
        f"PublicKey = {server_public_key}\n"
        f"Endpoint = {server_ip}:{server_port}\n"
        f"AllowedIPs = {allowed_ips}\n"
        f"PersistentKeepalive = {persistent_keepalive}\n"
    )

    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".conf")
        with open(temp_file.name, "w") as file:
            file.write(peer_config)

        response = send_file(
            temp_file.name,
            as_attachment=True,
            download_name=f"{peer_name}.conf",  
            mimetype="application/octet-stream"
        )

        response.cache_control.no_cache = True
        response.cache_control.no_store = True
        response.cache_control.must_revalidate = True

        return response
    except Exception as e:
        return jsonify(error=f"Error creating config file: {str(e)}"), 500


@app.route("/api/qr-code", methods=["GET"])
def generate_qr_code():
    peer_name = request.args.get("peerName")
    config_file = request.args.get("config", "wg0.conf") 

    if not peer_name:
        return jsonify(error="Peer name is required."), 400

    try:
        peers = load_peers_from_json(config_file)
    except Exception as e:
        return jsonify(error=f"Error reading JSON for {config_file}: {str(e)}"), 500

    peer = next((p for p in peers if p["peer_name"] == peer_name and p["config"] == config_file), None)
    if not peer:
        return jsonify(error=f"Peer '{peer_name}' not found in {config_file}."), 404

    dns = peer.get("dns", "1.1.1.1") 
    persistent_keepalive = peer.get("persistent_keepalive", 25)  
    mtu = peer.get("mtu", 1280)  

    try:
        server_public_key = obtain_public_key_conf(config_file)
        custom_ip = obtain_custom_ip()
        server_ip = custom_ip or obtain_server_public_ip()
        server_port = server_listen_port(config_file)
    except ValueError as e:
        return jsonify(error=f"Error retrieving server details: {e}"), 500

    address_cidr = f"{peer['peer_ip']}/32"
    allowed_ips = peer.get("allowed_ips") or "0.0.0.0/0, ::/0"

    peer_config = (
        f"[Interface]\n"
        f"PrivateKey = {peer['private_key']}\n"
        f"Address = {address_cidr}\n"
        f"DNS = {dns}\n"
        f"MTU = {mtu}\n"
        f"\n"
        f"[Peer]\n"
        f"PublicKey = {server_public_key}\n"
        f"Endpoint = {server_ip}:{server_port}\n"
        f"AllowedIPs = {allowed_ips}\n"
        f"PersistentKeepalive = {persistent_keepalive}\n"
    )

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(peer_config)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return jsonify(qr_code=f"data:image/png;base64,{img_str}")

@app.route('/api/get-peers', methods=['GET'])
def get_peers():
    peer_name = request.args.get("peer_name")
    config_name = request.args.get("config_name")  

    if not peer_name:
        return jsonify(error="Peer name is required."), 400

    db_file_path = os.path.join("db", f"{config_name}.json") if config_name else "db/all_peers.json"

    if not os.path.exists(db_file_path):
        return jsonify(error=f"Config file `{db_file_path}` not found."), 404

    try:
        with open(db_file_path, "r") as db_file:
            peers = json.load(db_file)

        matched_peers = [peer for peer in peers if peer_name.lower() in peer["peer_name"].lower()]
        return jsonify(peers=matched_peers), 200

    except Exception as e:
        return jsonify(error=f"error in reading peer data: {str(e)}"), 500

@app.route("/api/download-peer-config", methods=["GET"])
def download_peer_config():
    try:
        peer_name = request.args.get("peerName") or request.args.get("peer_name")
        config_file = request.args.get("config", "wg0.conf") or request.args.get("configFile", "wg0.conf")
        if not config_file.endswith(".conf"): config_file += ".conf"

        if not peer_name:
            return jsonify({"error": "Peer name is required"}), 400

        peers = load_peers_from_json(config_file)
        peer = next((p for p in peers if p["peer_name"] == peer_name and (p["config"] == config_file or p["config"] == config_file.replace(".conf", ""))), None)
        if not peer:
            return jsonify({"error": f"Peer '{peer_name}' not found."}), 404

        dns = peer.get("dns", "1.1.1.1")
        persistent_keepalive = peer.get("persistent_keepalive", 25)
        mtu = peer.get("mtu", 1420)
        server_public_key = obtain_public_key_conf(config_file)
        custom_ip = obtain_custom_ip()
        server_ip = custom_ip or obtain_server_public_ip()
        server_port = server_listen_port(config_file)
        allowed_ips = peer.get("allowed_ips") or "0.0.0.0/0, ::/0"

        peer_config = (
            f"[Interface]\n"
            f"PrivateKey = {peer['private_key']}\n"
            f"Address = {peer['peer_ip']}/32\n"
            f"DNS = {dns}\n"
            f"MTU = {mtu}\n\n"
            f"[Peer]\n"
            f"PublicKey = {server_public_key}\n"
            f"Endpoint = {server_ip}:{server_port}\n"
            f"AllowedIPs = {allowed_ips}\n"
            f"PersistentKeepalive = {persistent_keepalive}\n"
        )

        return Response(
            peer_config,
            mimetype="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{peer_name}.conf"'}
        )
    except Exception as e:
        app.logger.error(f"error in /api/download-peer-config: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/download-peer-qr", methods=["GET"])
def download_peer_qr():
    try:
        peer_name = request.args.get("peerName") or request.args.get("peer_name")
        config_file = request.args.get("config", "wg0.conf") or request.args.get("configFile", "wg0.conf")
        if not config_file.endswith(".conf"): config_file += ".conf"

        if not peer_name:
            return jsonify({"error": "Peer name is required"}), 400

        peers = load_peers_from_json(config_file)
        peer = next((p for p in peers if p["peer_name"] == peer_name and (p["config"] == config_file or p["config"] == config_file.replace(".conf", ""))), None)
        if not peer:
            return jsonify({"error": f"Peer '{peer_name}' not found."}), 404

        dns = peer.get("dns", "1.1.1.1")
        persistent_keepalive = peer.get("persistent_keepalive", 25)
        mtu = peer.get("mtu", 1420)
        server_public_key = obtain_public_key_conf(config_file)
        custom_ip = obtain_custom_ip()
        server_ip = custom_ip or obtain_server_public_ip()
        server_port = server_listen_port(config_file)
        allowed_ips = peer.get("allowed_ips") or "0.0.0.0/0, ::/0"

        peer_config = (
            f"[Interface]\n"
            f"PrivateKey = {peer['private_key']}\n"
            f"Address = {peer['peer_ip']}/32\n"
            f"DNS = {dns}\n"
            f"MTU = {mtu}\n\n"
            f"[Peer]\n"
            f"PublicKey = {server_public_key}\n"
            f"Endpoint = {server_ip}:{server_port}\n"
            f"AllowedIPs = {allowed_ips}\n"
            f"PersistentKeepalive = {persistent_keepalive}\n"
        )

        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(peer_config)
        qr.make(fit=True)
        img = qr.make_image(fill="black", back_color="white")
        img_io = BytesIO()
        img.save(img_io, "PNG")
        img_io.seek(0)

        return send_file(
            img_io,
            mimetype="image/png",
            as_attachment=False, 
            download_name=f"{peer_name}.png"
        )
    except Exception as e:
        app.logger.error(f"error in /api/download-peer-qr: {e}")
        return jsonify({"error": "Internal server error"}), 500

def obtain_config_files():
    try:
        return [f for f in os.listdir(WIREGUARD_CONFIG_DIR) if f.endswith(".conf")]
    except Exception as e:
        print(f"error in accessing {WIREGUARD_CONFIG_DIR}: {e}")
        return []

def custom_ip_or_default() -> str:
    """دریافت آی‌پی اختصاصی یا آی‌پی عمومی سرور"""
    return obtain_custom_ip() or obtain_server_public_ip()

@app.route("/api/get-custom-ip", methods=["GET"])
def custom_ip_endpoint():
    try:
        ip = custom_ip_or_default()
        return jsonify(custom_ip=ip)
    except Exception as e:
        return jsonify(error=f"error in retrieving custom IP: {str(e)}"), 500

@app.route("/api/update-custom-ip", methods=["POST"])
def update_custom_ip():
    data = request.get_json()
    custom_ip = data.get("custom_ip")

    if not custom_ip:
        return jsonify(error="Custom IP or Subdomain is required"), 400

    try:
        set_custom_ip(custom_ip)
        return jsonify(message="Custom IP/Subdomain updated successfully")
    except Exception as e:
        return jsonify(error=f"error in updating custom IP/Subdomain: {str(e)}"), 500


def read_file_content(file_name):
    try:
        path = os.path.join(WIREGUARD_CONFIG_DIR, file_name)
        with open(path, "r") as file:
            content = file.read()
            print(f"Content of {file_name}:\n{content}")  
        return content
    except Exception as e:
        print(f"error in reading {file_name}: {str(e)}")
        return None

def obtain_private_key(config_file):
    content = read_file_content(config_file)
    if content is None:
        return None
    for line in content.splitlines():
        if line.startswith("PrivateKey"):
            private_key = line.split("=")[1].strip()
            if private_key:
                return private_key
    return None


def gen_public_from_private(private_key: str) -> str:

    try:
        private_key = private_key.strip()  
        missing_padding = len(private_key) % 4
        if missing_padding:
            private_key += '=' * (4 - missing_padding)

        private_key_bytes = base64.b64decode(private_key)

        if len(private_key_bytes) != 32:
            raise ValueError("Wrong private key length. Expected 32 bytes.")

        public_key_bytes = nacl.bindings.crypto_scalarmult_base(private_key_bytes)

        public_key = base64.b64encode(public_key_bytes).decode('utf-8')
        return public_key
    except base64.binascii.Error as e:
        print(f"Base64 decoding error: {e}")
        return None
    except ValueError as e:
        print(f"Validation error: {e}")
        return None
    except Exception as e:
        print(f"error in generating public key: {e}")
        return None


def load_peers():
    global PEERS
    PEERS = []  

    public_ip = obtain_server_public_ip()

    for config_file in obtain_config_files():
        listen_port = None
        try:
            content = read_file_content(config_file)
            for line in content.splitlines():
                if line.startswith("ListenPort"):
                    listen_port = line.split("=")[1].strip()
                    break
        except Exception as e:
            print(f"error in reading ListenPort from {config_file}: {e}")
            continue

        endpoint = f"{public_ip}:{listen_port}" if public_ip and listen_port else None

        if content and "Error" not in content:
            peer = None
            for line in content.splitlines():
                if line.startswith("[Peer]"):
                    if peer and peer.get("publicKey") and peer.get("ip"):
                        peer["config_file"] = config_file
                        peer["endpoint"] = endpoint  
                        PEERS.append(peer)
                    peer = {"name": None, "ip": None, "publicKey": None}
                elif peer is not None:
                    if line.startswith("#"):
                        peer["name"] = line[1:].strip()
                    if line.startswith("PublicKey"):
                        peer["publicKey"] = line.split("=")[1].strip()
                    if line.startswith("AllowedIPs"):
                        peer["ip"] = line.split("=")[1].strip().split("/")[0]
            if peer and peer.get("publicKey") and peer.get("ip"):
                peer["config_file"] = config_file
                peer["endpoint"] = endpoint  
                PEERS.append(peer)


def obt_private_ip(file_name):
    content = read_file_content(file_name)
    if "Error" in content:
        return None
    for line in content.splitlines():
        if line.startswith("Address"):
            return line.split("=")[1].strip()
    return None


def calculate_available_ips(private_ip):
    try:
        network = ip_network(private_ip, strict=False)
        
        used_ips = set()

        for conf in obtain_config_files():
            content = read_file_content(conf)
            
            for line in content.splitlines():
                if line.startswith("AllowedIPs") or line.startswith("Address"):
                    ip = line.split("=")[-1].strip().split("/")[0]
                    used_ips.add(ip)
        
        available_ips = [str(ip) for ip in network.hosts() if str(ip) not in used_ips]
        
        return available_ips
    except ValueError:
        return []

@app.route("/api/config-details", methods=["GET"])
def wg_config_details():
    config_file = request.args.get("config", "wg0.conf")
    config_path = os.path.join(WIREGUARD_CONFIG_DIR, config_file)

    if not os.path.exists(config_path):
        return jsonify(error=f"Configuration file {config_file} does not exist."), 404

    details = {"active": False, "Address": "N/A", "ListenPort": "N/A", "DNS": "N/A", "MTU": "N/A"}

    try:
        with open(config_path, "r") as file:
            for line in file:
                line = line.strip()
                if line.startswith("Address"):
                    details["Address"] = line.split("=")[1].strip()
                elif line.startswith("ListenPort"):
                    details["ListenPort"] = line.split("=")[1].strip()
                elif line.startswith("DNS"):
                    details["DNS"] = line.split("=")[1].strip()
                elif line.startswith("MTU"):
                    details["MTU"] = line.split("=")[1].strip()

        interface_name = config_file.split(".")[0]
        try:
            sanitized_interface_name = sanitize_interface_name(interface_name)

            ip_path = "ip"  

            command = [ip_path, "link", "show", sanitized_interface_name] 
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            if result.returncode == 0:
                details["active"] = "state UNKNOWN" in result.stdout or "state UP" in result.stdout
            else:
                details["active"] = False 

        except ValueError as e:
            return jsonify(error=str(e)), 400  
        except Exception as e:
            print(f"Error checking interface status: {e}")
            details["active"] = False  

        return jsonify(details), 200

    except Exception as e:
        print(f"error in reading config file {config_file}: {e}")
        return jsonify(error=f"Couldn't read config file {config_file}. {str(e)}"), 500

@app.route("/api/available-ips", methods=["GET"])
def track_available_ips():
    config_file = request.args.get("config", "wg0.conf")
    
    private_ip = obt_private_ip(config_file)
    
    if not private_ip:
        return jsonify(error=f"Unable to extract private IP from {config_file}"), 400
    
    available_ips = calculate_available_ips(private_ip)
    
    return jsonify(availableIps=available_ips[:100])

@app.route("/api/generate-keys", methods=["GET"])
def generate_keys():
    try:
        wg_path = "wg" 

        result_private = subprocess.run(
            [wg_path, "genkey"], 
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        private_key = result_private.stdout.strip() 
        
        if not private_key:
            raise ValueError("Couldn't generate private key")

        result_public = subprocess.run(
            [wg_path, "pubkey"], 
            input=private_key,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        public_key = result_public.stdout.strip() 
        
        if not public_key:
            raise ValueError("Couldn't generate public key")

        return jsonify(privateKey=private_key, publicKey=public_key)

    except subprocess.CalledProcessError as e:
        print(f"error in generating keys: {e.stderr}")
        return jsonify(error=f"error in generating keys: {e.stderr}"), 500
    except ValueError as e:
        print(f"Value error generating keys: {e}")
        return jsonify(error=f"Value error: {e}"), 500
    except Exception as e:
        print(f"Unexpected error generating keys: {str(e)}")
        return jsonify(error=f"Unexpected error generating keys: {str(e)}"), 500


def obtain_server_public_ip():
    try:
        response = requests.get("https://api.ipify.org?format=text", timeout=5)
        return response.text.strip() if response.status_code == 200 else None
    except Exception as e:
        print(f"error in retrieving public IP: {e}")
        return None

def reload_blocked_peers():
    try:
        config_files = [f for f in os.listdir(WIREGUARD_CONFIG_DIR) if f.endswith(".conf")]
        
        for config_file in config_files:
            try:
                peers = load_peers_from_json(config_file)

                for peer in peers:
                    if peer.get("monitor_blocked") or peer.get("expiry_blocked"):
                        logging.info(f"Blocking peer: {peer['peer_name']} ({peer['peer_ip']})")
                        add_blackhole_route(peer["peer_ip"])  
                    else:
                        logging.info(f"Peer {peer['peer_name']} does not meet blocking criteria.")
            except Exception as e:
                logging.error(f"error in processing peers for {config_file}: {e}")
    except Exception as e:
        logging.error(f"error in reloading blocked peers: {e}")



def reload_unblocked_peers():
    try:
        config_files = [f for f in os.listdir(WIREGUARD_CONFIG_DIR) if f.endswith(".conf")]
        
        for config_file in config_files:
            try:
                peers = load_peers_from_json(config_file)

                for peer in peers:
                    if not peer.get("blocked"):
                        print(f"Removing blackhole route for unblocked peer: {peer['peer_name']} ({peer['peer_ip']})")
                        remove_blackhole_route(peer["peer_ip"]) 
            except Exception as e:
                print(f"error in processing peers for {config_file}: {e}")
    except Exception as e:
        print(f"error in reloading unblocked peers: {e}")

@app.route('/api/reload-blocked-peers', methods=['POST'])
def api_reload_blocked_peers():
    try:
        reload_blocked_peers()
        return jsonify({"message": "Blocked peers reloaded successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/reload-unblocked-peers', methods=['POST'])
def api_reload_unblocked_peers():
    try:
        reload_unblocked_peers()
        return jsonify({"message": "Unblocked peers reloaded successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def sanitize_command_part(command_part):

    sanitized_part = re.sub(r'[^a-zA-Z0-9_./-]', '', command_part)
    return sanitized_part

def run_command(command):
    try:
        if not all(isinstance(part, str) for part in command):
            raise ValueError("All command components must be strings.")

        sanitized_command = [sanitize_command_part(part) for part in command]

        process = subprocess.Popen(
            sanitized_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            raise Exception(f"Command failed: {stderr.strip()}")

        return stdout.strip() if stdout.strip() else "Success"
    
    except Exception as e:
        print(f"error in executing command '{' '.join(command)}': {str(e)}")
        return f"error in executing command: {str(e)}"
    
@app.route('/warp/status', methods=['GET'])
def warp_status():
    wgcf_status = "Inactive"

    try:
        command = ["ip", "link", "show"]
        interfaces = run_command(command).splitlines()

        if any("wgcf" in line for line in interfaces):
            wgcf_status = "Active"

    except Exception as e:
        print(f"error in checking service status: {str(e)}")

    return jsonify({
        "wgcf_status": wgcf_status
    })


@app.route('/xray/status', methods=['GET'])
def xray_status():
    xray_status = "Inactive"

    try:
        command = ["sudo", "systemctl", "is-active", "xray"]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            xray_status = "Active"
    except Exception as e:
        print(f"error in checking service status: {str(e)}")

    return jsonify({
        "xray_status": xray_status
    })



@app.route('/warp/reset', methods=['POST'])
def reset_warp():
    try:
        messages = []

        command = ["ip", "link", "show"]
        interfaces = run_command(command).splitlines()

        if any("wgcf" in line for line in interfaces):
            messages.append("Wireguard interface 'wgcf' is already up.")
        else:
            try:
                wg_up_result = run_command(["sudo", "wg-quick", "up", "wgcf"])
                messages.append("Wireguard interface 'wgcf' brought up successfully.")
            except Exception as e:
                messages.append(f"error in bringing up Wireguard interface 'wgcf': {str(e)}")
                return jsonify({"message": " | ".join(messages)}), 500

        return jsonify({"message": " | ".join(messages)})

    except Exception as e:
        print(f"Unexpected error in /warp/reset: {str(e)}")
        return jsonify({"message": "Unexpected error occurred while resetting WARP. Please try again."}), 500



@app.route('/xray/reset', methods=['POST'])
def reset_xray():
    try:
        messages = []

        try:
            xray_result = run_command(["sudo", "systemctl", "restart", "xray"])
            messages.append("Xray restarted successfully.")
        except Exception as e:
            messages.append(f"error in restarting Xray: {str(e)}")
            return jsonify({"message": " | ".join(messages)}), 500

        return jsonify({"message": " | ".join(messages)})

    except Exception as e:
        print(f"Unexpected error in /xray/reset: {str(e)}")
        return jsonify({"message": "Unexpected error occurred while resetting Xray. Please try again."}), 500



@app.route('/warp/enable', methods=['POST'])
def enable_warp():
    wg_result1 = run_command(["sudo", "wg-quick", "down", "wgcf"])
    wg_result2 = run_command(["sudo", "wg-quick", "up", "wgcf"])
    wg_result3 = run_command(["sudo", "systemctl", "enable", "wg-quick@wgcf"])
    xray_result = run_command(["sudo", "systemctl", "restart", "xray"])

    if "Error" in wg_result1 or "Error" in wg_result2 or "Error" in wg_result3 or "Error" in xray_result:
        return jsonify({"message": f"error in enabling WARP: {wg_result1} | {wg_result2} | {wg_result3} | {xray_result}"}), 500

    return jsonify({"message": "WARP enabled successfully! Wireguard and Xray restarted."})


@app.route('/warp/stop', methods=['POST'])
def stop_warp():
    messages = []
    
    try:
        interfaces = run_command(["ip", "link", "show"]).splitlines()
        if any("wgcf" in line for line in interfaces):
            try:
                wg_down_result = run_command(["sudo", "wg-quick", "down", "wgcf"])
                disable_warp()
                messages.append("Wireguard interface brought down successfully.")
            except Exception as e:
                messages.append(f"error in bringing down Wireguard interface: {str(e)}")
        else:
            messages.append("Wireguard interface 'wgcf' not found.")
        
        try:
            wg_stop_result = run_command(["sudo", "systemctl", "stop", "wg-quick@wgcf"])
            messages.append("Wireguard service stopped successfully.")
        except Exception as e:
            messages.append(f"error in stopping Wireguard service: {str(e)}")
        
        return jsonify({"message": " | ".join(messages)})

    except Exception as e:
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500



@app.route('/xray/stop', methods=['POST'])
def stop_xray():
    messages = []
    
    try:
        try:
            xray_stop_result = run_command(["sudo", "systemctl", "stop", "xray"])
            disable_xray()
            messages.append("Xray service stopped successfully.")
        except Exception as e:
            messages.append(f"error in stopping Xray service: {str(e)}")
        
        return jsonify({"message": " | ".join(messages)})

    except Exception as e:
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500



@app.route('/warp/disable', methods=['POST'])
def disable_warp():
    messages = [] 

    try:
        try:
            wg_down_result = run_command("sudo wg-quick down wgcf")
            print(f"Wireguard Down Result: {wg_down_result}")
            messages.append("Wireguard interface brought down successfully.")
        except Exception as e:
            error_message = f"error in bringing down Wireguard interface: {str(e)}"
            print(error_message)
            messages.append(error_message)

        try:
            wg_stop_result = run_command("sudo systemctl stop wg-quick@wgcf")
            print(f"Wireguard Stop Result: {wg_stop_result}")
            messages.append("Wireguard service stopped successfully.")
        except Exception as e:
            error_message = f"error in stopping Wireguard service: {str(e)}"
            print(error_message)
            messages.append(error_message)

        return jsonify({"message": " | ".join(messages)})

    except Exception as e:
        error_message = f"Unexpected error occurred while disabling WARP: {str(e)}"
        print(error_message)
        return jsonify({"message": error_message}), 500


@app.route('/xray/disable', methods=['POST'])
def disable_xray():
    messages = []  

    try:
        try:
            xray_stop_result = run_command(["sudo", "systemctl", "stop", "xray"])
            print(f"Xray Stop Result: {xray_stop_result}")
            messages.append("Xray service stopped successfully.")
        except Exception as e:
            error_message = f"error in stopping Xray service: {str(e)}"
            print(error_message)
            messages.append(error_message)

        try:
            xray_disable_result = run_command(["sudo", "systemctl", "disable", "xray"])
            print(f"Xray Disable Result: {xray_disable_result}")
            messages.append("Xray service disabled successfully.")
        except Exception as e:
            error_message = f"error in disabling Xray service: {str(e)}"
            print(error_message)
            messages.append(error_message)

        return jsonify({"message": " | ".join(messages)})

    except Exception as e:
        error_message = f"Unexpected error occurred while disabling Xray: {str(e)}"
        print(error_message)
        return jsonify({"message": error_message}), 500



@app.route('/warp/apply-geosites', methods=['POST'])
def apply_geosites():
    try:
        geosites = request.json.get('geosites', [])
        if not geosites:
            return {"message": "No geosites selected."}, 400

        config_path = "/usr/local/etc/xray/config.json"
        with open(config_path, "r") as xray_file:
            config = json.load(xray_file)

        for rule in config["routing"]["rules"]:
            if rule["type"] == "field" and rule["outboundTag"] == "warp":
                rule["domain"] = geosites

        with open(config_path, "w") as xray_file:
            json.dump(config, xray_file, indent=4)

        xray_restart = run_command(["sudo", "systemctl", "restart", "xray"])
        if "Error" in xray_restart:
            return {"message": "error in restarting Xray"}, 500

        return {"message": f"Geosites {geosites} applied successfully!"}

    except Exception as e:
        return {"message": f"error in applying geosites: {str(e)}"}, 500



@app.route('/warp/install', methods=['POST'])
def install_fullwarp_route():
    try:
        thread = Thread(target=install_fullwarp)
        thread.start()
        return jsonify({"message": "Installation started!"})
    except Exception as e:
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500

@app.route('/warp/install-progress', methods=['GET'])
def install_progress_route():
    try:
        if not os.path.exists(INSTALL_PROGRESS_FILE):
            return jsonify({"error": "Progress file not found."}), 404

        with open(INSTALL_PROGRESS_FILE, "r") as f:
            progress_data = json.load(f)
        return jsonify(progress_data), 200
    except json.JSONDecodeError:
        return jsonify({"error": "Progress file contains invalid JSON."}), 500
    except Exception as e:
        return jsonify({"error": f"error in fetching progress: {str(e)}"}), 500


@app.route('/warp/install-xray', methods=['POST'])
def install_xray_warp_route():
    try:
        thread = Thread(target=install_warp)
        thread.start()
        return jsonify({"message": "Installation started!"})
    except Exception as e:
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500

@app.route('/warp/install-xray-progress', methods=['GET'])
def install_xray_progress_route():
    try:
        if not os.path.exists(INSTALL_PROGRESS_FILE):
            return jsonify({"error": "Progress file not found."}), 404

        with open(INSTALL_PROGRESS_FILE, "r") as f:
            progress_data = json.load(f)
        return jsonify(progress_data), 200
    except json.JSONDecodeError:
        return jsonify({"error": "Progress file contains invalid JSON."}), 500
    except Exception as e:
        return jsonify({"error": f"error in fetching progress: {str(e)}"}), 500


@app.route('/warp/install-xray', methods=['POST'])
def install_xraywarp_route():
    try:
        result = install_warp()  
        if "Error" in result.get("message", ""):
            return jsonify({"message": result["message"]}), 500
        return jsonify(result)
    except Exception as e:
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500


@app.route('/warp/uninstall', methods=['POST'])
def uninstall_warp():
    try:
        print("Stopping related services...")
        try:
            run_command(["sudo", "systemctl", "stop", "wg-quick@wgcf"])
        except Exception as e:
            print(f"Warning: Couldn't stop wg-quick@wgcf service. {str(e)}")

        try:
            run_command(["sudo", "wg-quick", "down", "wgcf"])
        except Exception as e:
            print(f"Warning: Couldn't stop WARP {str(e)}")

        print("Removing WARP configs...")
        run_command(["sudo", "rm", "-f", "/etc/wireguard/wgcf.conf"])
        run_command(["sudo", "rm", "-f", "/usr/local/bin/wgcf"])

        print("Ensuring Wireguard remains installed...")
        try:
            wireguard_status = run_command(["dpkg-query", "-l", "|", "grep", "wireguard"])
            if "wireguard" not in wireguard_status:
                raise Exception("Warp deleted")
        except Exception as e:
            raise Exception(f"Wireguard validation failed: {str(e)}")

        print("WARP uninstallation completed successfully!")
        return {"message": "WARP uninstallation completed successfully!"}

    except Exception as e:
        error_message = f"error in during WARP uninstallation: {str(e)}"
        print(error_message)
        return {"message": error_message}



@app.route('/xray/uninstall', methods=['POST'])
def uninstall_xray():
    try:
        print("Stopping related services...")
        try:
            run_command(["sudo", "systemctl", "stop", "xray"])
        except Exception as e:
            print(f"Warning: Couldn't stop Xray service. {str(e)}")

        print("Removing Xray configs...")
        run_command(["sudo", "rm", "-rf", "/usr/local/etc/xray"])
        run_command(["sudo", "rm", "-f", "/usr/local/bin/xray"])

        print("Xray uninstallation completed successfully!")
        return jsonify({"message": "Xray uninstallation completed successfully!"})

    except Exception as e:
        error_message = f"error in during Xray uninstallation: {str(e)}"
        print(error_message)
        return jsonify({"message": error_message}), 500



@app.route('/api/server-ips', methods=['GET'])
def obtain_server_ips():
    try:
        ipv4 = None
        try:
            result = subprocess.run(
                ["hostname", "-I"], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                timeout=5, 
                check=True
            )
            ipv4 = result.stdout.split()[0] 
        except subprocess.CalledProcessError:
            ipv4 = 'Unavailable'
        except Exception as e:
            ipv4 = 'Unavailable'
            print(f"error in obtaining IPv4: {e}")

        ipv6 = None
        try:
            ipv6_response = requests.get('https://api6.ipify.org?format=json', timeout=5)
            if ipv6_response.status_code == 200:
                ipv6 = ipv6_response.json().get('ip', 'Unavailable')
            else:
                ipv6 = 'Unavailable'
        except requests.RequestException as e:
            ipv6 = 'Unavailable'
            print(f"error in obtaining IPv6: {e}")

        return jsonify({'public_ipv4': ipv4, 'public_ipv6': ipv6}), 200

    except Exception as e:
        print(f"error in obtaining server IPs: {e}")
        return jsonify({'error': str(e)}), 500  
    
@app.route('/api/logs', methods=['GET', 'DELETE'])
def manage_logs():
    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wireguard.log')

    if request.method == 'GET':
        limit = request.args.get('limit', 20, type=int)
        try:
            if not os.path.exists(log_file_path) or os.stat(log_file_path).st_size == 0:
                return jsonify({'logs': []}), 200

            with open(log_file_path, 'r') as log_file:
                logs = log_file.readlines()
            return jsonify({'logs': logs[-limit:]}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'DELETE':
        try:
            with open(log_file_path, 'w') as log_file:
                log_file.truncate(0)  
            return jsonify({'message': 'Logs cleared successfully'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route("/warp")
def warp_page():
    if "username" not in session:
        flash("Please log in to access Warp.", "error")
        return redirect("/login")
    
    language = session.get('language', 'en')
    template_name = "warp-fa.html" if language == "fa" else "warp.html"
    return render_template(template_name)

short_links = {}

@app.route("/api/get-peer-link", methods=["GET"])
def get_peer_short_link():
    peer_name = request.args.get("peerName")
    config_file = request.args.get("config")

    if not peer_name or not config_file:
        return jsonify({"error": "Peer name and config file are required."}), 400

    try:
        short_links = load_short_links()
        short_id = None
        for key, value in short_links.items():
            if f"peer_name={peer_name}" in value and f"config_file={config_file}" in value:
                short_id = key
                break

        if short_id:
            short_link = url_for('short_redirect', short_id=short_id, _external=True)
            return jsonify({"short_link": short_link})
        else:
            return jsonify({"error": "Short link not found."}), 404
    except Exception as e:
        print(f"Error in fetching peer short link: {e}")
        return jsonify({"error": f"Error happened: {str(e)}"}), 500

def generate_peer_token():
    return secrets.token_urlsafe(16)

@app.route('/peer-details', methods=['GET'])
def peer_details():
    peer_name = request.args.get('peer_name')
    config_file = request.args.get('config_file')
    token = request.args.get('token')

    app.logger.info(f"Peer Name: {peer_name}")
    app.logger.info(f"Config File: {config_file}")
    app.logger.info(f"Token: {token}")

    if not peer_name or not config_file or not token:
        return jsonify({"error": "Peer name, config file, and token are required."}), 400

    return render_template(
        'template.html',
        peer_name=peer_name,
        config_file=config_file,
        token=token
    )

@app.route('/api/peer-detailz', methods=['GET'])
def api_peer_details():
    peer_name = request.args.get('peer_name')  
    config_file = request.args.get('config_file')  
    token = request.args.get('token') 

    if not peer_name or not config_file or not token:
        return jsonify({"error": "Peer name, config file, and token are required."}), 400

    try:
        peer_details = obtain_peer_details_from_storage(peer_name, config_file, token)

        return jsonify(peer_details)

    except ValueError as e:
        app.logger.error(f"ValueError: {str(e)}")
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        app.logger.error(f"Exception: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

def obtain_peer_details_from_storage(peer_name, config_file, token):
    try:
        peers_metadata = load_peers_from_json(config_file)

        peer = next((p for p in peers_metadata if p["peer_name"] == peer_name), None)

        if not peer:
            raise ValueError(f"Peer with name '{peer_name}' not found in {config_file}.")

        if peer["token"] != token:
            raise ValueError("Invalid token for this peer.")

        peer["used_human"] = bytes_to_readable(peer.get("used", 0))
        peer["remaining_human"] = bytes_to_readable(peer.get("remaining", 0))
        peer["limit_human"] = bytes_to_readable(convert_to_bytes(peer["limit"]))

        created_at_str = peer.get("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
        created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

        expiry_months = peer.get("expiry_time", {}).get("months", 0)
        expiry_days = peer.get("expiry_time", {}).get("days", 0)
        expiry_hours = peer.get("expiry_time", {}).get("hours", 0)
        expiry_minutes = peer.get("expiry_time", {}).get("minutes", 0)

        expiry = created_at + timedelta(
            days=(expiry_months * 30) + expiry_days,
            hours=expiry_hours,
            minutes=expiry_minutes
        )
        now = datetime.now(timezone.utc)

        peer["expiry"] = expiry.strftime("%Y-%m-%d %H:%M:%S")

        time_diff = expiry - now
        if time_diff.total_seconds() <= 0:
            peer["expiry_human"] = "Expired"
        else:
            exp_days = time_diff.days
            exp_hours = (time_diff.seconds // 3600) % 24
            exp_minutes = (time_diff.seconds % 3600) // 60
            peer["expiry_human"] = f"{exp_days} روز، {exp_hours} ساعت، {exp_minutes} دقیقه باقی مانده"

        total_minutes = peer.get("remaining_time", 0)
        days = total_minutes // (24 * 60)
        hours = (total_minutes % (24 * 60)) // 60
        minutes = total_minutes % 60
        peer["remaining_time_human"] = f"{days} روز، {hours} ساعت، {minutes} دقیقه"

        is_active = not (peer.get("monitor_blocked", False) or peer.get("expiry_blocked", False))
        peer["status"] = "active" if is_active else "inactive"

        return {
            "peer_name": peer["peer_name"],
            "limit_human": peer["limit_human"],
            "used_human": peer["used_human"],
            "remaining_human": peer["remaining_human"],
            "expiry_human": peer["expiry_human"],
            "remaining_time": peer["remaining_time"],
            "remaining_time_human": peer["remaining_time_human"],
            "status": peer["status"]  
        }

    except Exception as e:
        raise ValueError(f"error in obtaining peer details: {str(e)}")



def get_public_ip():
    try:
        response = requests.get("https://api.ipify.org?format=json")
        if response.status_code == 200:
            return response.json().get("ip")
    except Exception as e:
        print(f"error in fetching public IP: {e}")
    return None

def get_server_location():
    try:
        cached_loc = cache.get("server_location")
        if cached_loc:
            return cached_loc
        public_ip = get_public_ip()
        if not public_ip:
            return {"country": "Germany", "country_code": "de"}
        response = requests.get(f"https://ipwho.is/{public_ip}", timeout=0.8)
        if response.status_code == 200:
            data = response.json()
            loc = {
                "country": data.get("country", "Germany"),
                "country_code": data.get("country_code", "de").lower(),
            }
            cache.set("server_location", loc, timeout=86400)
            return loc
    except Exception:
        pass
    return {"country": "Germany", "country_code": "de"}

@app.context_processor
def inject_server_location():
    location = get_server_location()
    return dict(server_location=location)

@app.route("/api/get-peer-info", methods=["GET"])
def get_peer_info():

    try:
        peer_name = request.args.get("peerName")
        config_file = request.args.get("configFile", "wg0.conf")

        if not peer_name:
            return jsonify({"error": "Peer name is required."}), 400

        if not re.match(r"^[a-zA-Z0-9_-]+\.conf$", config_file):
            return jsonify({"error": "Wrong config file name."}), 400

        peers = load_peers_from_json(config_file)
        peer = next((p for p in peers if p["peer_name"] == peer_name), None)

        if not peer:
            return jsonify({"error": f"Peer '{peer_name}' not found in {config_file}."}), 404

        return jsonify({"peerInfo": peer})
    except Exception as e:
        logging.error(f"error in retrieving peer info: {e}")
        return jsonify({"error": "Couldn't retrieve peer info."}), 500


def reset_peer_traffic(interface, public_key, peer_ip=None):
    try:
        interface = sanitize_interface_name(interface)
        public_key = sanitize_public_key(public_key)

        wg_path = "wg"  

        config_file = f"/etc/wireguard/{interface}.conf"

        with tempfile.TemporaryDirectory() as tmp_dir:
            backup_file = f"{tmp_dir}/peer_backup.conf"

            with open(config_file, "r") as config:
                lines = config.readlines()

            peer_config = []
            in_peer_section = False

            for line in lines:
                if f"PublicKey = {public_key}" in line:
                    in_peer_section = True
                if in_peer_section:
                    peer_config.append(line)
                if in_peer_section and line.strip() == "":
                    break  

            if peer_config:
                with open(backup_file, "w") as backup:
                    backup.writelines(peer_config)

                print(f"Backup of peer {public_key} saved to {backup_file}.")
            else:
                print(f"Peer {public_key} not found in {config_file}. Skipping backup.")

            subprocess.run([wg_path, "set", interface, "peer", public_key, "remove"], check=True)
            print(f"Peer {public_key} removed from {interface}, resetting counters.")

            if peer_ip:
                sanitized_peer_ip = sanitize_ip(peer_ip)
                subprocess.run(
                    [wg_path, "set", interface, "peer", public_key, "allowed-ips", f"{sanitized_peer_ip}/32"],
                    check=True
                )
                print(f"Peer {public_key} re-added to {interface} with allowed IP {sanitized_peer_ip}. Traffic counters reset.")
            else:
                if peer_config:
                    with open(config_file, "a") as config:
                        config.writelines(peer_config)
                    print(f"Peer {public_key} re-added to {interface} with backed-up configuration. Traffic counters reset.")
                else:
                    print(f"No peer configuration found for {public_key}. Cannot re-add.")

    except subprocess.CalledProcessError as e:
        print(f"error checking/removing peer {public_key} in {interface}: {e}")
        return
    except ValueError as e:
        print(f"Sanitization error: {e}")
        return



def parse_traffic(peer_ip, public_key):
    try:
        if not isinstance(peer_ip, str) or not isinstance(public_key, str):
            raise ValueError("Both peer_ip and public_key must be strings.")

        wg_path = "wg"  

        result = subprocess.run(
            [wg_path, "show", "all", "dump"], 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        wg_output = result.stdout

        lines = wg_output.splitlines()

        for line in lines:
            columns = line.split("\t")
            if len(columns) > 5 and columns[1] == public_key:
                allowed_ips = columns[4].split(",")
                if any(peer_ip in ip for ip in allowed_ips):
                    received_bytes = int(columns[5])
                    sent_bytes = int(columns[6])
                    total_bytes = received_bytes + sent_bytes
                    return total_bytes

        return 0
    except Exception as e:
        print(f"error in parsing traffic for IP {peer_ip}: {e}")
        return 0


@app.route("/api/peers-by-interface", methods=["GET"])
def obtain_peers_interface():
    interface = request.args.get("interface")

    if not interface:
        return jsonify({"error": "Interface parameter is required."}), 400

    try:
        peers_file = obtain_peers_file(f"{interface}.conf")
        
        peers_metadata = load_peers_from_json(peers_file)

        if not peers_metadata:
            return jsonify({"error": f"No peers found for interface {interface}."}), 404

        for peer in peers_metadata:
            peer["peer_name"] = peer.get("peer_name", "Unnamed Peer")
            peer["peer_ip"] = peer.get("peer_ip", "N/A")
            peer["public_key"] = peer.get("public_key", "N/A")
            peer["used_human"] = bytes_to_readable(peer.get("used", 0))
            peer["remaining_human"] = bytes_to_readable(peer.get("remaining", 0))
            peer["limit_human"] = bytes_to_readable(convert_to_bytes(peer["limit"]))

        return jsonify({"peers": peers_metadata})
    except FileNotFoundError:
        return jsonify({"error": f"Configuration file for interface {interface} not found."}), 404
    except Exception as e:
        print(f"error in loading peers for interface {interface}: {e}") 
        return jsonify(error=f"error occurred: {str(e)}"), 500


def convert_to_bytes(limit):
    return parse_smart_volume_input(limit)[1]
    if not limit_val:
        return 0
    if isinstance(limit_val, (int, float)):
        return int(limit_val)
    
    s = str(limit_val).strip().upper()
    m = re.match(r"^([0-9\.]+)\s*(T|TB|TIB|G|GB|GIB|M|MB|MIB|K|KB|KIB|B)?$", s)
    if not m:
        return 0
        
    size = float(m.group(1))
    unit = m.group(2) or "GIB"
    
    mapping = {
        "B": 1,
        "K": 1024, "KB": 1024, "KIB": 1024,
        "M": 1024**2, "MB": 1024**2, "MIB": 1024**2,
        "G": 1024**3, "GB": 1024**3, "GIB": 1024**3,
        "T": 1024**4, "TB": 1024**4, "TIB": 1024**4
    }
    return int(size * mapping.get(unit, 1024**3))

def bytes_to_readable(bytes_val) -> str:
    """تبدیل بایت به فرمت استاندارد و خوانا برای انسان"""
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

# جهت حفظ سازگاری با کدهای قدیمی که format_size و parse_limit_to_bytes را صدا می‌زدند:
format_size = bytes_to_readable
parse_limit_to_bytes = convert_to_bytes

@app.route('/api/search-peers', methods=['GET'])
def search_peers():
    try:
        query = (request.args.get('query', '') or '').strip().lower()
        filter_value = (request.args.get('filter', '') or '').strip().lower()  # "active" | "inactive" | ""

        with _db_lock, _connect() as con:
            rows = con.execute(
                "SELECT peer_name, peer_ip, public_key, \"limit\", used, remaining, "
                "       config, first_usage, expiry_blocked, monitor_blocked, "
                "       last_received_bytes, last_sent_bytes, remaining_time, expiry_time_json "
                "FROM peers"
            ).fetchall()

        out = []
        for r in rows:
            p = dict(r)
            name = (p.get('peer_name') or '')
            ip   = (p.get('peer_ip') or '')

            if query and (query not in name.lower()) and (query not in ip.lower()):
                continue

            is_banned = bool(p.get('monitor_blocked')) or bool(p.get('expiry_blocked'))
            if filter_value == 'active' and is_banned:
                continue
            if filter_value == 'inactive' and not is_banned:
                continue

            used = int(p.get('used') or 0)

            try:
                limit_bytes = convert_to_bytes(p.get('limit') or "")
            except Exception:
                limit_bytes = None

            if limit_bytes is None or limit_bytes == 0:
                remaining_bytes = None
                p['limit_human'] = "Unlimited"
                p['remaining_human'] = "Unlimited"
            else:
                rem_col = int(p.get('remaining') or 0)
                remaining_bytes = rem_col if rem_col > 0 else max(0, limit_bytes - used)
                p['limit_human'] = bytes_to_readable(limit_bytes)
                p['remaining_human'] = bytes_to_readable(remaining_bytes)

            p['used_human'] = bytes_to_readable(used)
            p['status'] = 'active' if not is_banned else 'inactive'

            out.append(p)

        return jsonify({"peers": out, "count": len(out)})

    except Exception as e:
        app.logger.error(f"Error in search-peers: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

@app.route("/api/peers", methods=["GET"])
def obtain_peers():
    config_file = request.args.get("config", "wg0.conf")
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 10))
    fetch_all = request.args.get("fetch_all", "false").lower() == "true"

    try:
        peers_metadata = load_peers_from_json(config_file)
        filtered_peers = [p for p in peers_metadata if p.get("config") == config_file]

        for peer in filtered_peers:
            limit_bytes = convert_to_bytes(peer.get("limit", "0GiB"))
            used_bytes = int(peer.get("used", 0) or 0)
            
            if limit_bytes > 0:
                remaining_bytes = max(0, limit_bytes - used_bytes)
                peer["limit_human"] = bytes_to_readable(limit_bytes)
                peer["remaining_human"] = bytes_to_readable(remaining_bytes)
            else:
                peer["limit_human"] = "نامحدود"
                peer["remaining_human"] = "نامحدود"
                
            peer["used_human"] = bytes_to_readable(used_bytes)
            peer["peer_name"] = peer.get("peer_name", "Unnamed Peer")
            peer["peer_ip"] = peer.get("peer_ip", "N/A")
            peer["public_key"] = peer.get("public_key", "N/A")

            # 📌 تعیین دقیق وضعیت سه‌گانه
            is_blk = bool(peer.get("monitor_blocked") or peer.get("expiry_blocked"))
            f_raw = str(peer.get("first_usage", "0")).strip().lower()
            is_wait = (not is_blk) and (f_raw in ["1", "true", "yes", "calc_first_conn"]) and (used_bytes <= 1024)

            if is_blk:
                peer["status"] = "inactive"
                peer["status_text"] = "غیرفعال"
            elif is_wait:
                peer["status"] = "onhold"
                peer["status_text"] = "انتظار"
            else:
                peer["status"] = "active"
                peer["status_text"] = "فعال"

        total_peers = len(filtered_peers)
        if fetch_all:
            return jsonify({"peers": filtered_peers, "total_peers": total_peers})

        start = (page - 1) * limit
        end = start + limit
        paginated_peers = filtered_peers[start:end]
        total_pages = (total_peers + limit - 1) // limit

        return jsonify({
            "peers": paginated_peers,
            "total_peers": total_peers,
            "total_pages": total_pages,
            "current_page": page,
        })
    except Exception as e:
        return jsonify(error=f"Error loading peers: {str(e)}"), 500

@app.route("/api/wireguard-details", methods=["GET"])
def wireguard_details():
    try:
        # ۱. در صورتی که نماینده وارد شده باشد، فقط اینترفیس اختصاصی خودش لود شود
        if session.get('role') == 'client':
            config_file = f"{session.get('interface', 'wg0')}.conf"
        else:
            config_file = request.args.get("config") or request.args.get("configFile") or "wg0.conf"

        if not config_file.endswith(".conf"):
            config_file += ".conf"

        interface_name = sanitize_interface_name(config_file.split(".")[0])
        config_path = os.path.join(WIREGUARD_CONFIG_DIR, config_file)

        if not os.path.exists(config_path):
            return jsonify({"error": f"Configuration file {config_file} not found"}), 404

        ip_path = "ip"
        result = subprocess.run(
            [ip_path, "link", "show", interface_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        is_active = (result.returncode == 0 and ("state UP" in result.stdout or "state UNKNOWN" in result.stdout))
        uptime = obtain_system_uptime()
        
        # استخراج مشخصات کلیدها و پورت اینترفیس انتخابی
        server_details = server_config_details(config_file)

        ip_address, dns = None, None
        with open(config_path, "r", encoding="utf-8", errors="ignore") as file:
            for line in file:
                line_clean = line.strip()
                if line_clean.startswith("Address"):
                    ip_address = line_clean.split("=")[1].strip()
                elif line_clean.startswith("DNS"):
                    dns = line_clean.split("=")[1].strip()

        return jsonify({
            "interface": interface_name,
            "active": is_active,
            "uptime": uptime,
            "private_key": server_details.get("private_key", "N/A"),
            "public_key": server_details.get("public_key", "N/A"),
            "ip": ip_address or "N/A",
            "port": server_details.get("listen_port", "N/A"),
            "dns": dns or "N/A",
        })

    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        app.logger.error(f"Error fetching Wireguard details for {config_file}: {e}")
        return jsonify(error=f"Couldn't retrieve Wireguard details: {str(e)}"), 500

@app.route("/api/get-interfaces", methods=["GET"])
def obt_interfaces():
    try:
        if session.get('role') == 'client':
            return jsonify(interfaces=[session.get('interface', 'wg0')])

        interfaces = [f for f in os.listdir(WIREGUARD_CONFIG_DIR) if f.endswith(".conf")]
        interfaces = [os.path.splitext(f)[0] for f in interfaces]  
        return jsonify(interfaces=interfaces)
    except Exception as e:
        logging.error(f"error in fetching interfaces: {e}")
        return jsonify(error=f"Couldn't fetch interfaces: {e}"), 500

@app.route("/api/configs", methods=["GET"])
def wg_configs():
    try:
        if session.get('role') == 'client':
            assigned = f"{session.get('interface', 'wg0')}.conf"
            return jsonify({"configs": [assigned]}), 200

        configs = [f for f in os.listdir(WIREGUARD_CONFIG_DIR) if f.endswith(".conf")]
        return jsonify({"configs": configs}), 200
    except Exception as e:
        return jsonify({"error": f"Couldn't load configs: {str(e)}"}), 500

def track_peer_usage(peer_ip):

    config_files = [f for f in os.listdir(WIREGUARD_CONFIG_DIR) if f.endswith(".conf")]

    for config_file in config_files:
        peers_file = f"{config_file.split('.')[0]}.json"
        peers = load_peers_from_json(peers_file)

        for peer in peers:
            if peer['peer_ip'] == peer_ip:
                if peer.get("first_usage", False):
                    print(f"DEBUG: First usage already registered for peer {peer['peer_name']} in {peers_file}. No reset performed.")
                    return {"message": "Usage already tracked."}

                if peer.get("used", 0) > 0:
                    peer["first_usage"] = True

                    expiry_time = peer.get("expiry_time", {})
                    peer["remaining_time"] = (
                        expiry_time.get("months", 0) * 30 * 24 * 60
                        + expiry_time.get("days", 0) * 24 * 60
                        + expiry_time.get("hours", 0) * 60
                        + expiry_time.get("minutes", 0)
                    )
                    print(f"DEBUG: First usage set to True and remaining time initialized to {peer['remaining_time']} minutes for peer {peer['peer_name']} in {peers_file}.")

                    save_peers_to_json(peers_file, peers)
                    return {"message": f"First usage registered for peer {peer['peer_name']}"}

                print(f"DEBUG: No traffic used yet for peer {peer['peer_name']} in {peers_file}.")
                return {"error": "No traffic used yet."}

    print("DEBUG: Peer with IP {peer_ip} not found in any config.")
    return {"error": "Peer not found."}


def clean_invalid_jobs(scheduler):
    for job_id in ["backup_json", "backup_wireguard"]:
        try:
            job = scheduler.get_job(job_id)
            if job:
                logging.info(f"Removing stale job: {job_id}")
                scheduler.remove_job(job_id)
        except JobLookupError:
            logging.warning(f"Job {job_id} not found in the scheduler.")


GEO_PATH = "/usr/local/etc/xray/config.json"

@app.route('/api/get-active-geosites', methods=['GET'])
def get_active_geosites():
    try:
        with open(GEO_PATH, 'r') as config_file:
            config_data = json.load(config_file)
        
        active_geosites = []
        for rule in config_data.get('routing', {}).get('rules', []):
            if rule.get('type') == 'field' and rule.get('outboundTag') == 'warp':
                active_geosites.extend(rule.get('domain', []))
        
        return jsonify({"active_geosites": active_geosites})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route("/api/track-usage", methods=["POST"])
def handle_track_usage():
    data = request.get_json()
    peer_ip = data.get("peerIp")
    
    if not peer_ip:
        return jsonify({"error": "Peer IP is required"}), 400
    
    result = track_peer_usage(peer_ip)
    if "error" in result:
        return jsonify(result), 400
    
    return jsonify({"message": f"Countdown started for peer with IP {peer_ip}"})


def create_shortlinks():

    if not os.path.exists(SHORT_LINKS_FILE):
        try:
            with open(SHORT_LINKS_FILE, "w") as file:
                json.dump({}, file) 
            print(f"{SHORT_LINKS_FILE} created successfully.")
        except Exception as e:
            print(f"Error creating {SHORT_LINKS_FILE}: {str(e)}")
    else:
        print(f"{SHORT_LINKS_FILE} already exists.")

jobstores = {'default': MemoryJobStore()}
executors = {
    'default': ThreadPoolExecutor(10), 
}
job_defaults = {
    'coalesce': True,  
    'misfire_grace_time': 30  
}
# فراخوانی خودکار احیا و گارد ضدروح هنگام استارت اپلیکیشن
try:
    import v100_master_edge_sync
    v100_master_edge_sync.auto_heal_and_recover_ghosts_live()
except Exception as ex_init_heal:
    print(f"[Healer Init] Notice: {ex_init_heal}")

scheduler = BackgroundScheduler(
    jobstores=jobstores,
    executors=executors,
    job_defaults=job_defaults,
    timezone=system_timezone
)
# تابع محاسبه آی‌پی آزاد بر اساس ساب‌نت /16
@app.route("/api/get-free-ip", methods=["GET"])
def api_get_free_ip():
    import sqlite3, os, re
    from flask import request, jsonify, session
    
    config_file = request.args.get('config', 'wg0.conf')
    if session.get('role') == 'client':
        config_file = session.get('interface') + ".conf"
        
    if not config_file.endswith('.conf'):
        config_file += ".conf"
        
    iface = config_file.replace('.conf', '')
    m = re.search(r'\d+', iface)
    num = int(m.group(0)) if m else 0

    base_prefix = f"10.{num}"
    
    used_ips = set()
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=15.0)
        cur = conn.cursor()
        cur.execute("SELECT peer_ip FROM peers WHERE config=? OR config=?", (config_file, iface))
        used_ips = set(r[0] for r in cur.fetchall() if r[0])
        conn.close()
    except: pass

    # جستجوی اولین آی‌پی خالی در فضای /16
    free_ip = None
    for oct3 in range(0, 256):
        for oct4 in range(2, 255):
            candidate = f"{base_prefix}.{oct3}.{oct4}"
            if candidate not in used_ips and candidate != f"{base_prefix}.0.1":
                free_ip = candidate
                break
        if free_ip:
            break
            
    if not free_ip:
        free_ip = f"{base_prefix}.0.2"
            
    return jsonify({"free_ip": free_ip})

def get_config_file_from_request(data, request_args, session_val):
    keys = ['config', 'config_file', 'configName', 'configFile', 'config_name']
    cfg = None
    for k in keys:
        if request_args.get(k):
            cfg = request_args.get(k)
            break
    if not cfg and data:
        for k in keys:
            if data.get(k):
                cfg = data.get(k)
                break
    if not cfg:
        cfg = session_val or "wg0.conf"
    if not cfg.endswith('.conf'):
        cfg = cfg + ".conf"
    return cfg

def start_wireguard_handshake_tracker():
    import threading, time, sqlite3, subprocess, datetime
    def tracker_loop():
        db_p = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
        while True:
            time.sleep(60)
            try:
                out = subprocess.check_output("wg show all latest-handshakes", shell=True, text=True, stderr=subprocess.DEVNULL)
                updates = []
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 3:
                        iface, pub, hs = parts[0], parts[1], int(parts[2])
                        if hs > 0: updates.append((pub, f"{iface}.conf"))
                
                if updates:
                    conn_h = sqlite3.connect(db_p, timeout=10.0)
                    cur_h = conn_h.cursor()
                    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    for pub, cfg in updates:
                        cur_h.execute("UPDATE peers SET first_connected_at=? WHERE public_key=? AND config=? AND (first_connected_at IS NULL OR first_connected_at='' OR first_connected_at='1')", (now_str, pub, cfg))
                    conn_h.commit(); conn_h.close()
            except: pass
    threading.Thread(target=tracker_loop, daemon=True).start()

try: start_wireguard_handshake_tracker()
except Exception as e: print("Tracker Error:", e)

def secure_config_file_param(config_file):
    from flask import session, has_request_context, abort
    if has_request_context():
        if not session.get('logged_in'):
            abort(401)
            
        if session.get('role') == 'client':
            return session.get('interface') + ".conf"
    return config_file

# اورراید کردن توابع اصلی خواندن و نوشتن فایل‌های کانفیگ برای تضمین عدم تجاوز به فایل‌های ادمین
for func_name in ['load_peers', 'save_peers', 'load_peers_with_lock', 'save_peers_with_lock']:
    orig_func = globals().get(func_name)
    if orig_func:
        def make_secure_wrapper(f):
            def wrapper(config_file, *args, **kwargs):
                config_file = secure_config_file_param(config_file)
                return f(config_file, *args, **kwargs)
            return wrapper
        globals()[func_name] = make_secure_wrapper(orig_func)

# 📌 هـ: روت‌های انحصاری Configurations مورد انتظار ربات سنایی و نفیسی (تضمین شناسایی پورت نمایندگان جدید با صفر کاربر)
@app.route("/api/getWireguardConfigurations", methods=["GET"])
@app.route("/api/getConfigurations", methods=["GET"])
def api_get_configurations_shield():
    from flask import session, jsonify
    allowed_config = "wg0.conf"
    if session.get('role') == 'client':
        allowed_config = session.get('interface') + ".conf"
    
    # بازگرداندن پاسخ شیک و دقیقاً منطبق بر آرایه "data" برای ربات
    return jsonify({
        "data": [
            {
                "configuration": allowed_config,
                "name": allowed_config.replace(".conf", "")
            }
        ]
    })

try:
    if 'csrf' in globals():
        csrf.exempt(api_get_configurations_shield)
except: pass

def heal_and_reconstruct_short_links():
    try:
        short_links_file = os.path.join(BASE_DIR, "short_links.json")
        short_links = {}
        if os.path.exists(short_links_file):
            try:
                with open(short_links_file, "r", encoding="utf-8") as f:
                    short_links = json.load(f)
            except Exception:
                short_links = {}

        # استعلام کاربران از SQLite و ترمیم لینک‌های مفقود
        db_p = os.path.join(BASE_DIR, "db.sqlite3")
        if os.path.exists(db_p):
            conn = sqlite3.connect(db_p, timeout=10.0)
            cur = conn.cursor()
            cur.execute("SELECT peer_name, config, token FROM peers WHERE token IS NOT NULL AND token != ''")
            rows = cur.fetchall()
            conn.close()

            updated = False
            for p_name, cfg, tok in rows:
                target_url_snippet = f"peer_name={p_name}"
                exists = any(target_url_snippet in str(url) for url in short_links.values())
                if not exists and tok:
                    # بازسازی شناسه کوتاه و لینک برای کلاینت
                    short_id = secrets.token_urlsafe(8) if 'secrets' in globals() else tok[:8]
                    long_link = f"http://localhost:5000/peer-details?peer_name={p_name}&config_file={cfg}&token={tok}"
                    short_links[short_id] = long_link
                    updated = True

            if updated:
                with open(short_links_file, "w", encoding="utf-8") as f:
                    json.dump(short_links, f, indent=4, ensure_ascii=False)
                print("✅ تمامی لینک‌های ساب‌لینک مفقود با موفقیت بازسازی و ترمیم شدند.")
    except Exception as e:
        print(f"[Sublink Healer] Error: {e}")

# فراخوانی خودکار ترمیم لینک‌ها هنگام بالا آمدن برنامه
try:
    heal_and_reconstruct_short_links()
except Exception:
    pass

@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(500)
def v76_handle_auth_and_system_errors(e):
    from flask import request, redirect, jsonify, session
    if request.path.startswith('/api/'):
        return jsonify({"error": "Unauthorized", "redirect": "/login"}), 401
    # اگر سشن معتبر نباشد مستقیم به لاگین هدایت شود
    if not session.get('logged_in'):
        return redirect('/login')
    return redirect('/login')
# --- [END STEP 76 STRICT REDIRECT FIX] ---



# --- [STEP 77 DUAL DATE PARSER ENGINE] ---
def parse_smart_dual_date(d_str, is_end=False):
    if not d_str or not str(d_str).strip():
        return None
    s = str(d_str).strip()
    for p, a, e in zip("۰۱۲۳۴۵۶۷۸۹", "٠١٢٣٤٥٦٧٨٩", "0123456789"):
        s = s.replace(p, e).replace(a, e)
    s = s.replace("-", "/").replace(".", "/")
    
    match = re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', s)
    if not match:
        return None
        
    y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
    from datetime import datetime
    
    if y > 1900:
        if is_end:
            return datetime(y, m, d, 23, 59, 59)
        return datetime(y, m, d, 0, 0, 0)
    else:
        try:
            import jdatetime
            if is_end:
                j_dt = jdatetime.datetime(y, m, d, 23, 59, 59)
            else:
                j_dt = jdatetime.datetime(y, m, d, 0, 0, 0)
            return j_dt.togregorian()
        except Exception:
            return None

def safe_check_password(p_hash, p_plain, password):
    """بررسی امن و چندلایه پسورد (هش و متن ساده)"""
    if not password:
        return False
    if p_plain and str(p_plain) == str(password):
        return True
    if p_hash and str(p_hash) == str(password):
        return True
    if p_hash and str(p_hash).startswith(('pbkdf2:', 'scrypt:', 'sha256$', 'bcrypt$', '$2b$')):
        try:
            if check_password_hash(p_hash, password) or bcrypt.check_password_hash(p_hash, password):
                return True
        except Exception:
            pass
    return False

def handle_universal_auth(username, password, lang='fa'):
    """احراز هویت جامع: ادمین اصلی، نمایندگان (Sub-Panels) و کلاینت‌ها"""
    is_fa = (lang == 'fa')
    err_wrong_pw = "نام کاربری یا کلمه عبور اشتباه است." if is_fa else "Wrong username or password."
    err_suspended = "حساب شما معلق یا غیرفعال شده است." if is_fa else "Your account has been suspended."
    err_not_found = "کاربری با این مشخصات یافت نشد." if is_fa else "User not found."

    username = str(username).strip()
    if not username or not password:
        return {"success": False, "error": err_wrong_pw}

    try:
        with _db_lock, _connect() as conn:
            # ۱. بررسی ادمین اصلی
            row_adm = conn.execute(
                "SELECT username, password_hash, password_plain FROM users WHERE username=?", 
                (username,)
            ).fetchone()

            if row_adm:
                if safe_check_password(row_adm["password_hash"], row_adm["password_plain"], password):
                    return {"success": True, "role": "admin", "interface": "wg0"}
                return {"success": False, "error": err_wrong_pw}

            # ۲. بررسی نمایندگان (Resellers)
            row_sub = conn.execute(
                "SELECT interface_name, password_hash, password_plain, status FROM sub_panels WHERE username=?", 
                (username,)
            ).fetchone()

            if row_sub:
                if row_sub["status"] != 'active':
                    return {"success": False, "error": err_suspended}
                if safe_check_password(row_sub["password_hash"], row_sub["password_plain"], password):
                    return {"success": True, "role": "client", "interface": row_sub["interface_name"]}
                return {"success": False, "error": err_wrong_pw}

            # ۳. بررسی کلاینت‌های معمولی (Peers)
            row_peer = conn.execute(
                "SELECT peer_name, expiry_blocked, monitor_blocked, remaining_time FROM peers WHERE peer_name=?", 
                (username,)
            ).fetchone()

            if row_peer:
                if row_peer["expiry_blocked"] or row_peer["monitor_blocked"] or (row_peer["remaining_time"] and row_peer["remaining_time"] <= 0):
                    return {"success": False, "error": err_suspended}
                return {"success": False, "error": err_wrong_pw}

        return {"success": False, "error": err_not_found}
    except Exception as e:
        app.logger.error(f"Auth error: {e}")
        return {"success": False, "error": "خطای پایگاه داده در احراز هویت." if is_fa else "Database auth error."}


@app.before_request
def unified_global_gatekeeper():
    """گیت‌کیپر مرکزی و یکپارچه فایروال، سشن و محدودسازی اینترفیس نمایندگان"""
    path = request.path

    # مسیرهای استاتیک و بدون نیاز به لاگین
    if path.startswith('/static') or path in ['/favicon.ico', '/set-language']:
        return

    # ۱. تنظیم زبان پیش‌فرض
    if "language" not in session:
        session["language"] = request.cookies.get("language", "fa")

    # ۲. بررسی ثبت‌نام اولیه
    users = load_users() or {}
    user_count = len([u for u in users.keys() if u and str(u).strip()])

    if user_count == 0:
        if path not in ['/register', '/api/register']:
            return redirect('/register')
        return
    else:
        if path == '/register':
            return redirect('/login')

    # ۳. مسیرهای عمومی و مجاز
    public_paths = [
        '/login', '/api/login', '/s/', '/api/health', 
        '/api/server-ips', '/api/get-free-ip', '/api/xray-ping', 
        '/api/xray-check', '/api/sync-all-peers', '/api/sync-all-peers-status'
    ]
    is_public = any(path.startswith(p) for p in public_paths) or path == '/'

    if not is_public and not session.get('logged_in'):
        if path.startswith('/api/'):
            return jsonify({"error": "Unauthorized", "redirect": "/login"}), 401
        return redirect('/login')

    # ۴. مهار و فیلتر کردن پارامترهای Config برای نماینده فرعی
    keys = ['config', 'config_file', 'configName', 'configFile', 'config_name']
    active_config = None
    for k in keys:
        if request.args.get(k):
            active_config = request.args.get(k)
            break

    if session.get('role') == 'client':
        assigned = f"{session.get('interface', 'wg0')}.conf"
        active_config = assigned

        blocked_routes = ['/settings', '/backups', '/api/backups', '/warp', '/telegram', '/template']
        if any(path.startswith(b) for b in blocked_routes):
            abort(403)

        if request.is_json:
            try:
                data = request.get_json(silent=True) or {}
                for k in keys:
                    data[k] = assigned
                request._cached_json = (data, data)
            except Exception:
                pass

    if active_config:
        if not active_config.endswith('.conf'):
            active_config += '.conf'
        request.args = request.args.copy()
        for k in keys:
            request.args[k] = active_config
        session['active_config'] = active_config


@app.after_request
def unified_response_handler(response):
    """فیلتر امنیتی خروجی APIها برای نمایندگان + فشرده‌سازی هوشمند GZIP"""
    if session.get('role') == 'client' and response.content_type and 'application/json' in response.content_type:
        try:
            allowed_iface = session.get('interface', 'wg0')

            def filter_node(item):
                if isinstance(item, list):
                    return [filter_node(x) for x in item if not (isinstance(x, dict) and str(x.get('config') or x.get('configuration') or '').replace('.conf', '') not in ['', allowed_iface])]
                elif isinstance(item, dict):
                    cfg_val = item.get('config') or item.get('configuration') or item.get('configFile')
                    if cfg_val and str(cfg_val).replace('.conf', '') != allowed_iface:
                        return None
                    return {k: filter_node(v) for k, v in item.items()}
                return item

            raw_text = response.get_data(as_text=True)
            original_json = json.loads(raw_text)
            filtered_json = filter_node(original_json)
            response.set_data(json.dumps(filtered_json, ensure_ascii=False))
        except Exception:
            pass

    # فشرده‌سازی GZIP
    try:
        if (200 <= response.status_code < 300 and 
            'gzip' not in response.headers.get('Content-Encoding', '') and 
            not response.direct_passthrough and
            response.content_type and any(t in response.content_type for t in ['text/', 'application/json', 'javascript', 'css'])):
            
            accept_encoding = request.headers.get('Accept-Encoding', '')
            if 'gzip' in accept_encoding.lower():
                import gzip
                from io import BytesIO
                data = response.get_data()
                if len(data) > 300:
                    buf = BytesIO()
                    with gzip.GzipFile(mode='wb', fileobj=buf) as gz:
                        gz.write(data)
                    response.set_data(buf.getvalue())
                    response.headers['Content-Encoding'] = 'gzip'
                    response.headers['Content-Length'] = str(len(response.get_data()))
    except Exception:
        pass

    return response


@app.route('/login', methods=['GET', 'POST'])
def login():
    lang = session.get('language', 'fa')
    template_name = "login-fa.html" if lang == "fa" else "login.html"

    if request.method == "GET":
        if session.get("logged_in") and session.get("username"):
            return redirect("/home")
        return render_template(template_name)

    username = str(request.form.get("username") or "").strip()
    password = str(request.form.get("password") or "")
    remember = request.form.get("remember")

    if not username or not password:
        flash("نام کاربری و رمز عبور الزامی است." if lang == 'fa' else "Username and password are required.", "error")
        return redirect("/login")

    auth_res = handle_universal_auth(username, password, lang)
    if auth_res and auth_res.get("success"):
        session['logged_in'] = True
        session['username'] = username
        session['role'] = auth_res.get("role", "admin")
        session['interface'] = auth_res.get("interface", "wg0")
        session['language'] = lang

        resp = make_response(redirect("/home"))
        if remember == "yes":
            resp.set_cookie("username", username, max_age=30*24*60*60)
        return resp

    flash(auth_res.get("error", "اطلاعات ورود اشتباه است."), "error")
    return redirect("/login")


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or request.form or {}
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    lang = session.get('language', 'fa')

    if not username or not password:
        return jsonify({"error": "نام کاربری و رمز عبور الزامی است." if lang == 'fa' else "Username and password are required."}), 400

    auth_res = handle_universal_auth(username, password, lang)
    if auth_res and auth_res.get("success"):
        session['logged_in'] = True
        session['username'] = username
        session['role'] = auth_res.get("role", "admin")
        session['interface'] = auth_res.get("interface", "wg0")
        session['language'] = lang
        return jsonify({"message": "Login successful!", "role": auth_res.get("role")}), 200

    return jsonify({"error": auth_res.get("error", "Unauthorized")}), 401


@app.route('/register', methods=['GET', 'POST'])
def register():
    lang = session.get('language', 'fa')
    template_name = "register-fa.html" if lang == "fa" else "register.html"

    users = load_users()
    if users:
        flash("امکان ثبت‌نام وجود ندارد زیرا کاربر ادمین قبلاً ساخته شده است.", "error")
        return redirect('/login')

    if request.method == "GET":
        return render_template(template_name)

    username = str(request.form.get("username") or "").strip()
    password = str(request.form.get("password") or "")
    confirm_password = str(request.form.get("confirm_password") or "")

    if not username or not password:
        flash("نام کاربری و رمز عبور الزامی است.", "error")
        return redirect('/register')
    if password != confirm_password:
        flash("رمزهای عبور واردشده مطابقت ندارند.", "error")
        return redirect('/register')

    hashed_password = generate_password_hash(password)
    users[username] = hashed_password
    save_users(users)

    flash("ثبت‌نام با موفقیت انجام شد! اکنون وارد شوید.", "success")
    return redirect('/login')

def get_local_cfg_p():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_bot_config.json")


@app.route('/bot')
def bot():
    if not session.get('logged_in') or not session.get('username'):
        return redirect("/login")
    
    language = session.get('language', 'fa')
    template_name = "bot-fa.html" if language == "fa" else "bot.html"
    role = session.get('role', 'admin')
    username = session.get('username')
    
    b_tok, c_id, b_status = "", "", "off"
    
    if role == 'client':
        with _db_lock, _connect() as conn:
            row = conn.execute(
                "SELECT telegram_bot_token, telegram_chat_id, telegram_bot_status FROM sub_panels WHERE username=?", 
                (username,)
            ).fetchone()
            if row:
                b_tok = row['telegram_bot_token'] or ""
                c_id = row['telegram_chat_id'] or ""
                b_status = row['telegram_bot_status'] or "off"
    else:
        cfg_p = get_local_cfg_p()
        if os.path.exists(cfg_p):
            try:
                with open(cfg_p, 'r', encoding='utf-8') as f:
                    cd = json.load(f)
                b_tok = cd.get('t', '')
                c_id = cd.get('c', '')
                b_status = cd.get('status', 'off')
            except Exception:
                pass

    return render_template(template_name, bot_token=b_tok, admin_chat_id=c_id, bot_status=b_status)

@app.route('/api/toggle-bot-status', methods=['POST'])
def api_toggle_bot_status():
    data = request.get_json(silent=True) or request.form or {}
    token = data.get('bot_token', '').strip()
    chat_id = data.get('admin_chat_id', '').strip()
    status = data.get('status', 'on').strip().lower()
    role = session.get('role', 'admin')
    username = session.get('username')

    if status == 'on' and not token:
        return jsonify(success=False, message="برای روشن کردن ربات، وارد کردن توکن الزامی است."), 400

    try:
        import v100_master_edge_sync
        
        if role == 'client':
            with _db_lock, _connect() as conn:
                conn.execute(
                    "UPDATE sub_panels SET telegram_bot_token=?, telegram_chat_id=?, telegram_bot_status=? WHERE username=?",
                    (token, chat_id, status, username)
                )
                conn.commit()
        else:
            cfg_p = get_local_cfg_p()
            with open(cfg_p, 'w', encoding='utf-8') as f:
                json.dump({'t': token, 'c': chat_id, 'status': status}, f, indent=4)

        if status == 'on':
            try:
                del_url = f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=True"
                urllib.request.urlopen(urllib.request.Request(del_url), timeout=8)
            except Exception:
                pass

            v100_master_edge_sync.start_bot_polling_daemon()
            if chat_id:
                v100_master_edge_sync.tg_send_message(
                    chat_id,
                    "🤖 <b>ربات مدیریت وایرگارد روشن و فعال شد!</b>\n\n✅ دسترسی تایید شد و تمام منوها فعال هستند.",
                    v100_master_edge_sync.get_main_reply_keyboard(),
                    token
                )
            return jsonify(success=True, message="✅ ربات تلگرام روشن شد! دستور /start را در تلگرام ارسال کنید.")
        else:
            if role != 'client':
                v100_master_edge_sync.stop_bot_polling_daemon()
            return jsonify(success=True, message="🔴 ربات تلگرام با موفقیت خاموش شد.")
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@app.route('/api/update-bot', methods=['POST'])
def api_update_bot_official():
    data = request.get_json(silent=True) or request.form or {}
    token = data.get('bot_token', '').strip()
    chat_id = data.get('admin_chat_id', '').strip()
    role = session.get('role', 'admin')
    username = session.get('username')

    try:
        import v100_master_edge_sync
        
        if role == 'client':
            with _db_lock, _connect() as conn:
                conn.execute(
                    "UPDATE sub_panels SET telegram_bot_token=?, telegram_chat_id=?, telegram_bot_status='on' WHERE username=?",
                    (token, chat_id, username)
                )
                conn.commit()
        else:
            cfg_p = get_local_cfg_p()
            if not token and os.path.exists(cfg_p):
                with open(cfg_p, 'r', encoding='utf-8') as f:
                    cd = json.load(f)
                token = cd.get('t', '')
                chat_id = chat_id or cd.get('c', '')
            else:
                with open(cfg_p, 'w', encoding='utf-8') as f:
                    json.dump({'t': token, 'c': chat_id, 'status': 'on'}, f, indent=4)

        v100_master_edge_sync.start_bot_polling_daemon()
        if chat_id:
            v100_master_edge_sync.tg_send_message(
                chat_id, 
                "🔄 <b>ربات تلگرام مجدداً راه‌اندازی و همگام‌سازی شد.</b>", 
                v100_master_edge_sync.get_main_reply_keyboard(), 
                token
            )

        return jsonify(success=True, message="✅ ربات با موفقیت به‌روزرسانی و ریستارت شد.")
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@app.route('/api/test-bot', methods=['POST'])
def api_test_bot_official():
    data = request.get_json(silent=True) or {}
    token = data.get('bot_token', '').strip()
    chat_id = data.get('admin_chat_id', '').strip()
    role = session.get('role', 'admin')
    username = session.get('username')

    if role == 'client' and (not token or not chat_id):
        with _db_lock, _connect() as conn:
            row = conn.execute(
                "SELECT telegram_bot_token, telegram_chat_id FROM sub_panels WHERE username=?", 
                (username,)
            ).fetchone()
            if row:
                token = token or row['telegram_bot_token']
                chat_id = chat_id or row['telegram_chat_id']
    elif not token or not chat_id:
        cfg_p = get_local_cfg_p()
        if os.path.exists(cfg_p):
            with open(cfg_p, 'r', encoding='utf-8') as f:
                cd = json.load(f)
            token = token or cd.get('t', '')
            chat_id = chat_id or cd.get('c', '')

    if not token or not chat_id:
        return jsonify(success=False, message="توکن و Chat ID الزامی هستند."), 400

    try:
        import v100_master_edge_sync
        res = v100_master_edge_sync.tg_send_message(
            chat_id, 
            "🔔 <b>پیام تست ارتباط ربات پنل وایرگارد با موفقیت ارسال شد!</b>", 
            v100_master_edge_sync.get_main_reply_keyboard(), 
            token
        )
        if res and res.get('ok'):
            return jsonify(success=True, message="✅ پیام تست با موفقیت به تلگرام ارسال شد.")
        return jsonify(success=False, message="خطا در ارسال پیام به تلگرام. توکن یا Chat ID را بررسی کنید."), 400
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# ========================================================================= #
# 🔐 CHANGE PASSWORD ROUTE                                                  #
# ========================================================================= #

@app.route('/change-password', methods=['GET', 'POST'])
def change_password():
    if not session.get('logged_in') or not session.get('username'):
        return redirect('/login')

    current_user = session.get('username')
    lang = session.get('language', 'fa')

    if request.method == 'GET':
        return render_template('change-password.html', username=current_user)

    new_pw = str(request.form.get('new_password') or '').strip()
    if not new_pw:
        flash('لطفاً رمز عبور جدید را وارد کنید.' if lang == 'fa' else 'Please enter the new password.', 'error')
        return render_template('change-password.html', username=current_user)

    try:
        from sqlite_backend import load_users, save_users, _db_lock, _connect
        from werkzeug.security import generate_password_hash
        hashed = generate_password_hash(new_pw)

        # بروزرسانی ادمین
        users = load_users()
        if current_user in users:
            users[current_user] = hashed
            save_users(users)
            with _db_lock, _connect() as con:
                con.execute("UPDATE users SET password_hash=?, password_plain=? WHERE username=?", (hashed, new_pw, current_user))
                con.commit()

        # بروزرسانی نماینده
        with _db_lock, _connect() as con:
            con.execute("UPDATE sub_panels SET password_hash=?, password_plain=? WHERE interface_name=?", (hashed, new_pw, current_user))
            con.commit()

        flash('رمز عبور با موفقیت تغییر یافت.' if lang == 'fa' else 'Password changed successfully.', 'success')
        return redirect('/home')
    except Exception as e:
        flash(f'خطا در تغییر رمز: {e}' if lang == 'fa' else f'Error: {e}', 'error')
        return render_template('change-password.html', username=current_user)

@app.route("/api/sync-all-peers", methods=["POST", "GET"])
def api_sync_all_peers():
    import v100_master_edge_sync
    success, msg = v100_master_edge_sync.start_master_sync_job()
    return jsonify({"success": success, "message": msg, "status": "started"}), 200

@app.route("/api/sync-all-peers-status", methods=["GET"])
def api_sync_all_peers_status():
    import v100_master_edge_sync
    status = v100_master_edge_sync.get_sync_progress_status()
    return jsonify(status), 200

try:
    if 'csrf' in globals():
        csrf.exempt(api_sync_all_peers)
        csrf.exempt(api_sync_all_peers_status)
except Exception:
    pass

@app.route("/api/create-peer", methods=["POST"])
def create_peer():
    """ساخت کلاینت (تکی یا گروهی) با تخصیص هوشمند IP، ثبت ساب‌لینک و سینک نودها"""
    try:
        data = request.get_json(silent=True) or request.form or {}

        # ۱. استخراج و اعتبارسنجی کانفیگ اینترفیس
        cfg_raw = data.get("configFile") or data.get("config") or "wg0.conf"
        if session.get('role') == 'client':
            cfg_raw = f"{session.get('interface', 'wg0')}.conf"

        config_file = str(cfg_raw).strip()
        if not config_file.endswith(".conf"):
            config_file += ".conf"
        iface = config_file.replace(".conf", "")

        # ۲. اعتبارسنجی نام کلاینت
        peer_name_raw = data.get('peerName') or data.get('peer_name') or ''
        peer_name = str(peer_name_raw).strip()
        if not peer_name or not re.match(r"^[a-zA-Z0-9_-]+$", peer_name):
            return jsonify({"error": "نام کاربری فقط می‌تواند شامل حروف انگلیسی، اعداد، خط تیره و زیرخط باشد."}), 400

        # ۳. وضعیت اتصال اول
        f_raw = data.get("firstUsage") if data.get("firstUsage") is not None else data.get("first_usage")
        is_first_usage = 1 if (str(f_raw).strip().lower() in ["true", "1", "yes", "on", "calc_first_conn"]) else 0

        # ۴. حجم هوشمند (پشتیبانی از 1.5، 1/5 و 500) و مشخصات شبکه
        raw_limit = data.get('dataLimit') or data.get('limit') or "50"
        unit_val = data.get('dataLimitUnit') or data.get('limit_unit') or data.get('limitUnit') or "GiB"
        data_limit, limit_bytes, _ = parse_smart_volume_input(raw_limit, unit_val)

        dns = str(data.get('dns') or "1.1.1.1, 1.0.0.1").strip()
        persistent_keepalive = int(data.get("persistentKeepalive") or data.get("keepalive") or 25)
        mtu = int(data.get("mtu") or 1420)
        allowed_ips = str(data.get("allowedIps") or data.get("allowed_ips") or "0.0.0.0/0, ::/0").strip()

        # ۵. محاسبه زمان انقضا
        expiry_months = int(data.get("expiryMonths") or 0)
        expiry_days = int(data.get("expiryDays") or data.get("days") or 0)
        expiry_hours = int(data.get("expiryHours") or 0)
        expiry_minutes = int(data.get("expiryMinutes") or 0)

        if expiry_days < 0 or expiry_months < 0 or expiry_hours < 0 or expiry_minutes < 0:
            return jsonify({"error": "مقادیر زمان انقضا نمی‌توانند منفی باشند."}), 400

        total_expiry_minutes = (expiry_months * 30 * 24 * 60) + (expiry_days * 24 * 60) + (expiry_hours * 60) + expiry_minutes
        if total_expiry_minutes <= 0:
            total_expiry_minutes = 30 * 24 * 60

        bulk_count = int(data.get("bulkCount") or data.get("bulk_count") or 1)

        # ۶. پیشوند IP
        m_num = re.search(r'\d+', iface)
        num = int(m_num.group(0)) if m_num else 0
        base_prefix = f"10.{num}"

        def get_or_gen_keys(in_data):
            p_k = in_data.get("private_key") or in_data.get("privateKey")
            pb_k = in_data.get("public_key") or in_data.get("publicKey")
            if p_k and len(str(p_k).strip()) == 44:
                p_k = str(p_k).strip()
                if not pb_k or len(str(pb_k).strip()) != 44:
                    pb_k = subprocess.getoutput(f"echo '{p_k}' | wg pubkey").strip()
                return p_k, str(pb_k).strip()
            p_k = subprocess.getoutput("wg genkey").strip()
            pb_k = subprocess.getoutput(f"echo '{p_k}' | wg pubkey").strip()
            return p_k, pb_k

        # --- ساخت تکی (Single Creation) ---
        if bulk_count == 1:
            peer_ip_raw = data.get('peerIp') or data.get('ip') or ''
            peer_ip = str(peer_ip_raw).strip()

            with _db_lock, _connect() as con:
                cur = con.cursor()
                cur.execute("SELECT id FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, config_file, iface))
                if cur.fetchone():
                    return jsonify({"error": f"کاربر '{peer_name}' در اینترفیس {iface} از قبل وجود دارد."}), 400

                used_ips = set(r[0] for r in cur.execute("SELECT peer_ip FROM peers WHERE config=? OR config=?", (config_file, iface)).fetchall() if r[0])

                if not peer_ip or peer_ip in used_ips or peer_ip.endswith('.0') or peer_ip.endswith('.255'):
                    free_ip = None
                    for oct3 in range(0, 256):
                        for oct4 in range(2, 255):
                            cand = f"{base_prefix}.{oct3}.{oct4}"
                            if cand not in used_ips and cand != f"{base_prefix}.0.1":
                                free_ip = cand
                                break
                        if free_ip: break
                    peer_ip = free_ip or f"{base_prefix}.0.2"

                priv_key, pub_key = get_or_gen_keys(data)
                token = data.get("token") or secrets.token_urlsafe(16)
                exp_json_str = json.dumps({"months": expiry_months, "days": expiry_days, "hours": expiry_hours, "minutes": expiry_minutes})

                cur.execute("""
                    INSERT INTO peers (
                        peer_name, peer_ip, public_key, [limit], used, remaining_time, 
                        config, expiry_time_json, first_usage, expiry_blocked, monitor_blocked, 
                        private_key, dns, mtu, persistent_keepalive, allowed_ips, token, 
                        initial_duration, created_at, created_at_gregorian
                    ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'), datetime('now'))
                """, (peer_name, peer_ip, pub_key, data_limit, total_expiry_minutes, config_file, exp_json_str, is_first_usage, priv_key, dns, mtu, persistent_keepalive, allowed_ips, token, total_expiry_minutes))

                cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token, f"/peer-details?peer_name={peer_name}&config_file={config_file}&token={token}"))
                cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token[:8], f"/peer-details?peer_name={peer_name}&config_file={config_file}&token={token}"))
                con.commit()

            # فعال‌سازی محلی روی کارت شبکه
            subprocess.run(f"wg set {iface} peer {pub_key} allowed-ips {peer_ip}/32", shell=True, stderr=subprocess.DEVNULL)
            subprocess.run(f"wg-quick save {iface}", shell=True, stderr=subprocess.DEVNULL)

            # همگام‌سازی با نودها
            try:
                import v100_master_edge_sync
                v100_master_edge_sync.sync_action_to_edges(
                    "create", peer_name, config_file, 
                    extra_data={
                        "first_usage": (is_first_usage == 1),
                        "private_key": priv_key,
                        "public_key": pub_key,
                        "limit": data_limit,
                        "remaining_time": total_expiry_minutes
                    }
                )
            except Exception as ex_sync:
                app.logger.warning(f"Edge sync notice: {ex_sync}")

            return jsonify({
                "success": True,
                "message": f"کاربر '{peer_name}' با موفقیت ساخته شد.",
                "peer_name": peer_name,
                "peer_ip": peer_ip,
                "public_key": pub_key,
                "private_key": priv_key,
                "short_link": f"/s/{token}",
                "first_usage": is_first_usage
            }), 200

        # --- ساخت گروهی (Bulk Creation) ---
        else:
            responses = []
            with _db_lock, _connect() as con:
                cur = con.cursor()
                used_ips = set(r[0] for r in cur.execute("SELECT peer_ip FROM peers WHERE config=? OR config=?", (config_file, iface)).fetchall() if r[0])

                available_ips = []
                for oct3 in range(0, 256):
                    for oct4 in range(2, 255):
                        cand = f"{base_prefix}.{oct3}.{oct4}"
                        if cand not in used_ips and cand != f"{base_prefix}.0.1":
                            available_ips.append(cand)
                            if len(available_ips) >= bulk_count: break
                    if len(available_ips) >= bulk_count: break

                if len(available_ips) < bulk_count:
                    return jsonify({"error": "آی‌پی آزاد کافی برای ساخت گروهی وجود ندارد."}), 400

                exp_json_str = json.dumps({"months": expiry_months, "days": expiry_days, "hours": expiry_hours, "minutes": expiry_minutes})

                for i in range(bulk_count):
                    curr_ip = available_ips[i]
                    sub_peer_name = f"{peer_name}_{i + 1}"
                    priv_key, pub_key = get_or_gen_keys({})
                    token = secrets.token_urlsafe(16)

                    cur.execute("""
                        INSERT INTO peers (
                            peer_name, peer_ip, public_key, [limit], used, remaining_time, 
                            config, expiry_time_json, first_usage, expiry_blocked, monitor_blocked, 
                            private_key, dns, mtu, persistent_keepalive, allowed_ips, token, 
                            initial_duration, created_at, created_at_gregorian
                        ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'), datetime('now'))
                    """, (sub_peer_name, curr_ip, pub_key, data_limit, total_expiry_minutes, config_file, exp_json_str, is_first_usage, priv_key, dns, mtu, persistent_keepalive, allowed_ips, token, total_expiry_minutes))

                    cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token, f"/peer-details?peer_name={sub_peer_name}&config_file={config_file}&token={token}"))
                    cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (token[:8], f"/peer-details?peer_name={sub_peer_name}&config_file={config_file}&token={token}"))

                    subprocess.run(f"wg set {iface} peer {pub_key} allowed-ips {curr_ip}/32", shell=True, stderr=subprocess.DEVNULL)
                    responses.append({"peer_name": sub_peer_name, "short_link": f"/s/{token}", "peer_ip": curr_ip})

                con.commit()

            subprocess.run(f"wg-quick save {iface}", shell=True, stderr=subprocess.DEVNULL)

            try:
                import v100_master_edge_sync
                for r_item in responses:
                    v100_master_edge_sync.sync_action_to_edges("create", r_item["peer_name"], config_file)
            except Exception:
                pass

            return jsonify({"success": True, "message": f"{bulk_count} کاربر به صورت گروهی ساخته شدند.", "peers": responses}), 200

    except Exception as e:
        app.logger.error(f"Error in create_peer: {e}")
        return jsonify({"error": f"خطا در ساخت کاربر: {str(e)}"}), 500

@app.route("/api/edit-peer", methods=["POST"])
def edit_peer():
    """ویرایش کلاینت (تغییر حجم، زمان و DNS) و همگام‌سازی بلادرنگ"""
    data = request.get_json(silent=True) or request.form or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    cfg_raw = data.get("configFile") or data.get("config") or "wg0.conf"
    if session.get('role') == 'client':
        cfg_raw = f"{session.get('interface', 'wg0')}.conf"

    config_file = str(cfg_raw).strip()
    if not config_file.endswith('.conf'): config_file += '.conf'
    iface = config_file.replace('.conf', '')

    if not peer_name:
        return jsonify({"error": "نام کلاینت الزامی است."}), 400

    try:
        raw_limit = data.get("dataLimit") or data.get("limit")
        unit_val = data.get("dataLimitUnit") or data.get("limit_unit") or data.get("limitUnit") or "GiB"

        new_dns = data.get("dns")
        months = int(data.get("expiryMonths") or data.get("months") or 0)
        days = int(data.get("expiryDays") or data.get("days") or 0)
        hours = int(data.get("expiryHours") or data.get("hours") or 0)
        minutes = int(data.get("expiryMinutes") or data.get("minutes") or 0)

        total_minutes = (months * 30 * 1440) + (days * 1440) + (hours * 60) + minutes

        with _db_lock, _connect() as con:
            cur = con.cursor()
            cur.execute("SELECT id, peer_ip, public_key, [limit], remaining_time, used FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, config_file, iface))
            peer = cur.fetchone()

            if not peer:
                return jsonify({"error": f"کاربر '{peer_name}' یافت نشد."}), 404

            updates = []
            params = []

            # اعمال پارسر هوشمند حجم در ویرایش کلاینت
            if raw_limit:
                new_limit_str, limit_bytes, _ = parse_smart_volume_input(raw_limit, unit_val)
                rem_bytes = max(0, limit_bytes - int(peer["used"] or 0))
                updates.extend(["[limit]=?", "remaining=?"])
                params.extend([new_limit_str, rem_bytes])

            if new_dns:
                updates.append("dns=?")
                params.append(new_dns)

            if total_minutes > 0:
                exp_json = json.dumps({"months": months, "days": days, "hours": hours, "minutes": minutes})
                updates.extend(["expiry_time_json=?", "remaining_time=?", "expiry_blocked=0", "monitor_blocked=0"])
                params.extend([exp_json, total_minutes])

            if updates:
                params.extend([peer_name, config_file, iface])
                cur.execute(f"UPDATE peers SET {', '.join(updates)} WHERE peer_name=? AND (config=? OR config=?)", params)
                con.commit()

            # رفع خودکار بلک‌هول در صورت تمدید اعتبار
            peer_ip = peer["peer_ip"]
            pub = peer["public_key"]
            if peer_ip:
                subprocess.run(f"ip route del blackhole {peer_ip}", shell=True, stderr=subprocess.DEVNULL)
                subprocess.run(f"wg set {iface} peer {pub} allowed-ips {peer_ip}/32", shell=True, stderr=subprocess.DEVNULL)

        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_action_to_edges("edit", peer_name, config_file)
        except Exception:
            pass

        return jsonify({"success": True, "message": "اطلاعات کلاینت با موفقیت به‌روزرسانی شد."}), 200

    except Exception as e:
        app.logger.error(f"Edit peer error: {e}")
        return jsonify({"error": f"خطا در ویرایش کلاینت: {str(e)}"}), 500

@app.route("/api/delete-peer", methods=["POST"])
def delete_peer():
    """حذف دائم کلاینت، واریز ترافیک مصرفی به صندوق، شستشوی فایل conf و سینک نودها"""
    data = request.get_json(silent=True) or request.form or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    cfg_raw = data.get("configFile") or data.get("config") or "wg0.conf"
    if session.get('role') == 'client':
        cfg_raw = f"{session.get('interface', 'wg0')}.conf"

    config_file = str(cfg_raw).strip()
    if not config_file.endswith('.conf'): config_file += '.conf'
    iface = config_file.replace('.conf', '')

    if not peer_name:
        return jsonify({"error": "نام کلاینت الزامی است."}), 400

    try:
        with _db_lock, _connect() as con:
            cur = con.cursor()
            cur.execute("SELECT public_key, used, peer_ip, token FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, config_file, iface))
            row = cur.fetchone()

            if not row:
                return jsonify({"error": f"کاربر '{peer_name}' یافت نشد."}), 404

            pub_key = row["public_key"]
            used_val = int(row["used"] or 0)
            peer_ip = row["peer_ip"]
            token = row["token"]

            # ۱. واریز ترافیک مصرفی به صندوق دائمی
            if used_val > 0:
                record_deleted_traffic_atomic(iface, used_val)

            # ۲. حذف از کارت شبکه و جدول روتینگ بلک‌هول
            if pub_key:
                subprocess.run(f"wg set {iface} peer {pub_key} remove", shell=True, stderr=subprocess.DEVNULL)
            if peer_ip:
                subprocess.run(f"ip route del blackhole {peer_ip}", shell=True, stderr=subprocess.DEVNULL)

            # ۳. حذف از دیتابیس
            cur.execute("DELETE FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, config_file, iface))
            cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=?", (peer_name,))
            cur.execute("DELETE FROM services WHERE email=?", (peer_name,))
            if token:
                cur.execute("DELETE FROM short_links WHERE short_id=? OR short_id=?", (token, token[:8]))
            con.commit()

        # ۴. شستشوی فیزیکی دیسک فایل .conf
        conf_path = f"/etc/wireguard/{config_file}"
        if os.path.exists(conf_path):
            with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            new_lines = []
            skip = False
            for line in lines:
                if line.startswith("[Peer]"):
                    skip = False
                if f"#{peer_name}" in line.replace(" ", "") or (pub_key and pub_key in line):
                    skip = True
                if not skip:
                    new_lines.append(line)
            with open(conf_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            subprocess.run(f"wg-quick save {iface}", shell=True, stderr=subprocess.DEVNULL)

        # ۵. همگام‌سازی حذف با نودها
        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_action_to_edges("delete", peer_name, config_file)
        except Exception:
            pass

        return jsonify({"success": True, "message": f"کاربر '{peer_name}' با موفقیت حذف شد."}), 200

    except Exception as e:
        app.logger.error(f"Delete peer error: {e}")
        return jsonify({"error": f"خطا در حذف کاربر: {str(e)}"}), 500


@app.route("/api/toggle-peer", methods=["POST"])
def toggle_peer():
    """قطع/وصل کلاینت بدون ریست شدن مصرف یا زمان انقضا"""
    data = request.get_json(silent=True) or request.form or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    cfg_raw = data.get("configFile") or data.get("config") or "wg0.conf"
    if session.get('role') == 'client':
        cfg_raw = f"{session.get('interface', 'wg0')}.conf"

    config_file = str(cfg_raw).strip()
    if not config_file.endswith('.conf'): config_file += '.conf'
    iface = config_file.replace('.conf', '')

    if not peer_name:
        return jsonify({"error": "نام کلاینت الزامی است."}), 400

    try:
        with _db_lock, _connect() as con:
            cur = con.cursor()
            cur.execute("SELECT monitor_blocked, expiry_blocked, peer_ip, public_key FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, config_file, iface))
            row = cur.fetchone()

            if not row:
                return jsonify({"error": f"کاربر '{peer_name}' یافت نشد."}), 404

            is_blocked = bool(row["monitor_blocked"] or row["expiry_blocked"])
            new_blocked = 0 if is_blocked else 1

            cur.execute("UPDATE peers SET monitor_blocked=?, expiry_blocked=? WHERE peer_name=? AND (config=? OR config=?)", (new_blocked, new_blocked, peer_name, config_file, iface))
            con.commit()

            peer_ip = row["peer_ip"]
            pub_key = row["public_key"]

            if new_blocked == 1:
                if peer_ip: subprocess.run(f"ip route add blackhole {peer_ip}", shell=True, stderr=subprocess.DEVNULL)
                if pub_key: subprocess.run(f"wg set {iface} peer {pub_key} remove", shell=True, stderr=subprocess.DEVNULL)
            else:
                if peer_ip: subprocess.run(f"ip route del blackhole {peer_ip}", shell=True, stderr=subprocess.DEVNULL)
                if pub_key and peer_ip: subprocess.run(f"wg set {iface} peer {pub_key} allowed-ips {peer_ip}/32", shell=True, stderr=subprocess.DEVNULL)

            subprocess.run(f"wg-quick save {iface}", shell=True, stderr=subprocess.DEVNULL)

        try:
            import v100_master_edge_sync
            v100_master_edge_sync.sync_action_to_edges("toggle", peer_name, config_file, {"blocked": bool(new_blocked)})
        except Exception:
            pass

        return jsonify({"success": True, "message": "وضعیت کاربر با موفقیت تغییر یافت.", "blocked": bool(new_blocked)}), 200

    except Exception as e:
        app.logger.error(f"Toggle peer error: {e}")
        return jsonify({"error": f"خطا در تغییر وضعیت: {str(e)}"}), 500


@app.route("/api/delete-all-configs", methods=["POST"])
@app.route("/api/delete-all", methods=["POST"])
def delete_all_inactive_configs():
    """بررسی و پاکسازی دسته‌جمعی تمام کلاینت‌های منقضی و اتمام‌حجم در اینترفیس مربوطه"""
    data = request.get_json(silent=True) or request.form or {}
    cfg_raw = data.get("configFile") or data.get("config") or "wg0.conf"
    if session.get('role') == 'client':
        cfg_raw = f"{session.get('interface', 'wg0')}.conf"

    config_file = str(cfg_raw).strip()
    if not config_file.endswith('.conf'): config_file += '.conf'
    iface = config_file.replace('.conf', '')

    try:
        deleted_count = 0
        with _db_lock, _connect() as con:
            cur = con.cursor()
            cur.execute("SELECT peer_name, public_key, used, peer_ip, [limit], remaining_time, expiry_blocked, monitor_blocked FROM peers WHERE config=? OR config=?", (config_file, iface))
            rows = cur.fetchall()

            for r in rows:
                p_name = r["peer_name"]
                pub_k = r["public_key"]
                used_b = int(r["used"] or 0)
                p_ip = r["peer_ip"]
                rem_t = int(r["remaining_time"] or 0)
                lim_b = convert_to_bytes(r["limit"])

                is_expired = (rem_t <= 0) or (lim_b > 0 and used_b >= lim_b) or bool(r["expiry_blocked"] or r["monitor_blocked"])

                if is_expired:
                    if used_b > 0:
                        record_deleted_traffic_atomic(iface, used_b)
                    if pub_k:
                        subprocess.run(f"wg set {iface} peer {pub_k} remove", shell=True, stderr=subprocess.DEVNULL)
                    if p_ip:
                        subprocess.run(f"ip route del blackhole {p_ip}", shell=True, stderr=subprocess.DEVNULL)

                    cur.execute("DELETE FROM peers WHERE peer_name=? AND (config=? OR config=?)", (p_name, config_file, iface))
                    cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=?", (p_name,))
                    cur.execute("DELETE FROM services WHERE email=?", (p_name,))
                    deleted_count += 1

            con.commit()

        subprocess.run(f"wg-quick save {iface}", shell=True, stderr=subprocess.DEVNULL)

        try:
            import v100_master_edge_sync
            v100_master_edge_sync.reconcile_db_and_conf_files()
        except Exception:
            pass

        return jsonify({"success": True, "message": f"تعداد {deleted_count} کاربر غیرفعال/منقضی پاکسازی شدند."}), 200

    except Exception as e:
        app.logger.error(f"Bulk delete error: {e}")
        return jsonify({"error": f"خطا در پاکسازی دسته‌جمعی: {str(e)}"}), 500
# =========================================================================
# 🔗 UNIFIED SUBLINK & CLUSTER CONFIG ENGINE (STEP 3 - MASTER DEFINITION)
# =========================================================================

def load_short_links():
    """واکشی یکپارچه لینک‌های ساب‌لینک از SQLite با فایل Fallback"""
    links = {}
    try:
        with _db_lock, _connect() as conn:
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS short_links (short_id TEXT PRIMARY KEY, long_link TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);")
            for r in cur.execute("SELECT short_id, long_link FROM short_links").fetchall():
                links[r[0]] = r[1]
    except Exception:
        pass

    if not links and os.path.exists(SHORT_LINKS_FILE):
        try:
            with open(SHORT_LINKS_FILE, 'r', encoding='utf-8') as f:
                links = json.load(f)
        except Exception:
            pass
    return links

def save_short_links(short_links_dict):
    """ذخیره پایدار ساب‌لینک‌ها در SQLite و فایل JSON"""
    if not short_links_dict or not isinstance(short_links_dict, dict):
        return
    try:
        with _db_lock, _connect() as conn:
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS short_links (short_id TEXT PRIMARY KEY, long_link TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);")
            for s_id, l_link in short_links_dict.items():
                if s_id and l_link:
                    cur.execute("INSERT OR REPLACE INTO short_links (short_id, long_link) VALUES (?, ?)", (str(s_id).strip(), str(l_link).strip()))
            conn.commit()
    except Exception as e:
        app.logger.error(f"Error saving short links: {e}")

    try:
        existing = {}
        if os.path.exists(SHORT_LINKS_FILE):
            try:
                with open(SHORT_LINKS_FILE, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
        existing.update(short_links_dict)
        with open(SHORT_LINKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=4, ensure_ascii=False)
    except Exception:
        pass


@app.route("/s/<short_id>", methods=["GET"])
def short_redirect(short_id):
    """رندر هوشمند صفحه وضعیت ساب‌لینک برای کلاینت (پشتیبانی از پلن‌ها و نودهای کلاستر)"""
    short_id = str(short_id).strip()
    peer_name = None
    config_file = "wg0.conf"
    token = None

    with _db_lock, _connect() as conn:
        cur = conn.cursor()

        # ۱. استعلام از جدول short_links
        try:
            cur.execute("SELECT long_link FROM short_links WHERE short_id = ?", (short_id,))
            row = cur.fetchone()
            if row and row["long_link"]:
                long_link = row["long_link"]
                p_m = re.search(r"peer_name=([^&]+)", long_link) or re.search(r"peerName=([^&]+)", long_link)
                c_m = re.search(r"config_file=([^&]+)", long_link) or re.search(r"configFile=([^&]+)", long_link) or re.search(r"config=([^&]+)", long_link)
                t_m = re.search(r"token=([^&]+)", long_link)
                if p_m: peer_name = urllib.parse.unquote(p_m.group(1))
                if c_m: config_file = urllib.parse.unquote(c_m.group(1))
                if t_m: token = urllib.parse.unquote(t_m.group(1))
        except Exception:
            pass

        # ۲. جستجوی مستقیم در جدول peers بر اساس توکن، نام یا کلید
        if not peer_name:
            try:
                cur.execute(
                    "SELECT peer_name, config, token FROM peers WHERE peer_name = ? OR token = ? OR token LIKE ?", 
                    (short_id, short_id, f"{short_id}%")
                )
                p_row = cur.fetchone()
                if p_row:
                    peer_name = p_row["peer_name"]
                    config_file = p_row["config"]
                    token = p_row["token"]
            except Exception:
                pass

        clean_cfg = config_file if str(config_file).endswith(".conf") else f"{config_file}.conf"
        iface = clean_cfg.replace(".conf", "")

        peer_row = None
        if peer_name:
            try:
                cur.execute("SELECT * FROM peers WHERE peer_name = ? AND (config = ? OR config = ?)", (peer_name, clean_cfg, iface))
                peer_row = cur.fetchone()
            except Exception:
                pass

        if not peer_row:
            display_name = peer_name or short_id
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
                status_text="<span style='display:flex; align-items:center; gap:5px;'><i class='fas fa-times-circle' style='color:#ff4757; font-size:16px;'></i> اشتراک یافت نشد یا حذف شده است</span>",
                status_class="st-offline",
                cache_buster=int(time.time())
            )
            resp = make_response(rendered)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

        p_dict = dict(peer_row)
        limit_str = str(p_dict.get("limit") or "50GiB")
        used_bytes = int(p_dict.get("used") or 0)
        rem_minutes = int(p_dict.get("remaining_time") or 0)
        init_duration = int(p_dict.get("initial_duration") or 0)
        expiry_json_str = str(p_dict.get("expiry_time_json") or "")

        total_min = init_duration if init_duration > 0 else (rem_minutes if rem_minutes > 0 else 43200)
        if expiry_json_str and str(expiry_json_str).strip() not in ["None", "{}", ""]:
            try:
                exp_json = json.loads(str(expiry_json_str))
                m = int(exp_json.get("months", 0))
                d = int(exp_json.get("days", 0))
                h = int(exp_json.get("hours", 0))
                mn = int(exp_json.get("minutes", 0))
                t_calc = (m * 30 * 1440) + (d * 1440) + (h * 60) + mn
                if t_calc > 0: total_min = t_calc
            except Exception:
                pass

        if rem_minutes > total_min:
            total_min = rem_minutes

        days_val = total_min // 1440
        total_days = f"{days_val} روز" if days_val > 0 else f"{total_min} دقیقه"

        f_raw = str(p_dict.get("first_usage", "0")).strip().lower()
        is_waiting_first_conn = (f_raw in ["1", "true", "yes", "calc_first_conn"])
        has_traffic = (used_bytes > 1024)

        limit_bytes = convert_to_bytes(limit_str)
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
            time_percent = min(100.0, max(0.0, float(round((elapsed_min / float(total_min)) * 100.0, 1)))) if total_min > 0 else 0.0
            r_d = rem_minutes // 1440
            r_h = (rem_minutes % 1440) // 60
            time_str_fa = f"{r_d} روز و {r_h} ساعت" if r_d > 0 else f"{rem_minutes} دقیقه"
            status_text = "<span style='display:flex; align-items:center; gap:5px;'><i class='fas fa-check-circle' style='color:#00ffc3; font-size:16px;'></i> فعال</span>"
            status_class = "st-online"

        special_mode = 1
        try:
            cur.execute("SELECT special_mode FROM client_settings WHERE interface_name = ?", (iface,))
            sm_row = cur.fetchone()
            if sm_row and sm_row[0] is not None:
                special_mode = int(sm_row[0])
        except Exception:
            pass

        master_name = "سرور اصلی"
        master_flag = "🇩🇪"
        master_suffix = ""
        try:
            cur.execute("SELECT server_name, file_suffix FROM master_settings LIMIT 1")
            m_row = cur.fetchone()
            if m_row:
                if m_row["server_name"]: master_name = m_row["server_name"].strip()
                if m_row["file_suffix"]: master_suffix = m_row["file_suffix"].strip()
        except Exception:
            pass

        all_edge_servers = []
        try:
            cur.execute("SELECT id, server_ip, flag, location, server_name, file_suffix FROM edge_servers")
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

        active_flags = [master_flag]
        for ef in all_edge_servers:
            srv_ip = (ef.get("server_ip") or "").strip()
            if srv_ip in synced_edge_ips:
                active_flags.append(ef.get("flag") or "🌍")
        location_html = " ".join([f"<span class='flag-item'>{fl}</span>" for fl in set(active_flags)])

        download_configs = []

        if special_mode == 1:
            try:
                cur.execute("SELECT id, plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers FROM subscription_plans")
                plans = [dict(r) for r in cur.fetchall()]

                for p_row in plans:
                    p_id = p_row["id"]
                    p_name = p_row["plan_name"]
                    p_desc = p_row.get("description") or ""
                    p_suf = p_row.get("suffix") or ""

                    try:
                        active_s = json.loads(p_row["active_servers"]) if p_row["active_servers"] else ["master"]
                    except Exception:
                        active_s = ["master"]

                    for srv_ip in active_s:
                        if srv_ip != "master" and srv_ip not in synced_edge_ips:
                            continue

                        if srv_ip == "master":
                            s_label = f"<i class='fas fa-server'></i> {p_name} | {master_name} {master_flag}"
                        else:
                            e_info = next((e for e in all_edge_servers if e.get("server_ip") == srv_ip), None)
                            e_label = e_info.get("server_name") if e_info else "سرور لبه"
                            e_fl = e_info.get("flag") if e_info else "🌍"
                            s_label = f"<i class='fas fa-satellite-dish'></i> {p_name} | {e_label} {e_fl}"

                        download_configs.append({
                            "server_label": s_label,
                            "plan_name": p_name,
                            "description": p_desc,
                            "file_name": f"{peer_name}{p_suf}.conf",
                            "suffix": f"{p_id}_{srv_ip}",
                            "mtu": p_row.get("mtu") or 1420,
                            "dns": p_row.get("dns") or "1.1.1.1",
                            "keepalive": p_row.get("keepalive") or 25,
                            "allowed_ips": p_row.get("allowed_ips") or "0.0.0.0/0, ::/0"
                        })
            except Exception:
                pass

        if not download_configs or special_mode == 0:
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


@app.route("/s/<short_id>/download/<suffix_key>", methods=["GET"])
def short_download_config(short_id, suffix_key):
    """دانلود داینامیک فایل کانفیگ کلاینت برای Master یا نود لبه انتخابی"""
    try:
        short_id = str(short_id).strip()
        suffix_key = str(suffix_key).strip()

        with _db_lock, _connect() as conn:
            cur = conn.cursor()

            peer_name = None
            config_file = "wg0.conf"

            # استعلام نام کلاینت
            cur.execute("SELECT long_link FROM short_links WHERE short_id = ?", (short_id,))
            row = cur.fetchone()
            if row and row["long_link"]:
                long_link = row["long_link"]
                p_m = re.search(r"peer_name=([^&]+)", long_link) or re.search(r"peerName=([^&]+)", long_link)
                c_m = re.search(r"config_file=([^&]+)", long_link) or re.search(r"configFile=([^&]+)", long_link) or re.search(r"config=([^&]+)", long_link)
                if p_m: peer_name = urllib.parse.unquote(p_m.group(1))
                if c_m: config_file = urllib.parse.unquote(c_m.group(1))

            if not peer_name:
                cur.execute("SELECT peer_name, config FROM peers WHERE token=? OR peer_name=?", (short_id, short_id))
                p_row = cur.fetchone()
                if p_row:
                    peer_name = p_row["peer_name"]
                    config_file = p_row["config"]

            if not peer_name:
                return "Error: Peer not found", 404

            clean_cfg = config_file if str(config_file).endswith(".conf") else f"{config_file}.conf"
            iface = clean_cfg.replace(".conf", "")

            cur.execute("SELECT * FROM peers WHERE peer_name=? AND (config=? OR config=?)", (peer_name, clean_cfg, iface))
            peer_rec = cur.fetchone()
            if not peer_rec:
                cur.execute("SELECT * FROM peers WHERE peer_name=?", (peer_name,))
                peer_rec = cur.fetchone()

            if not peer_rec:
                return "Error: Peer record missing", 404

            p_dict = dict(peer_rec)
            client_priv_key = p_dict.get("private_key") or ""
            client_ip = p_dict.get("peer_ip") or "10.0.0.2"
            mtu = p_dict.get("mtu") or 1420
            dns = p_dict.get("dns") or "1.1.1.1, 1.0.0.1"
            keepalive = p_dict.get("persistent_keepalive") or 25
            allowed_ips = p_dict.get("allowed_ips") or "0.0.0.0/0, ::/0"

            plan_id = suffix_key.split("_")[0] if "_" in suffix_key else "main"
            target_server = suffix_key.split("_", 1)[1] if "_" in suffix_key else "master"

            filename = f"{peer_name}.conf"
            if plan_id != "main" and plan_id.isdigit():
                cur.execute("SELECT suffix, mtu, dns, keepalive, allowed_ips FROM subscription_plans WHERE id=?", (int(plan_id),))
                plan_row = cur.fetchone()
                if plan_row:
                    p_suf = plan_row["suffix"] or ""
                    filename = f"{peer_name}{p_suf}.conf"
                    if plan_row["mtu"]: mtu = plan_row["mtu"]
                    if plan_row["dns"]: dns = plan_row["dns"]
                    if plan_row["keepalive"]: keepalive = plan_row["keepalive"]
                    if plan_row["allowed_ips"]: allowed_ips = plan_row["allowed_ips"]

            server_ip = "127.0.0.1"
            server_pub_key = ""
            listen_port = 51820

            # اگر سرور اصلی باشد:
            if target_server.lower() == "master":
                cur.execute("SELECT endpoint_domain, ssh_ip FROM master_settings LIMIT 1")
                m_row = cur.fetchone()
                if m_row and m_row["endpoint_domain"]:
                    server_ip = m_row["endpoint_domain"].strip()
                elif m_row and m_row["ssh_ip"]:
                    server_ip = m_row["ssh_ip"].strip()
                else:
                    server_ip = obtain_server_public_ip()

                master_conf_path = f"/etc/wireguard/{clean_cfg}"
                if os.path.exists(master_conf_path):
                    try:
                        with open(master_conf_path, "r", encoding="utf-8", errors="ignore") as f:
                            cf_text = f.read()
                        port_match = re.search(r"ListenPort\s*=\s*(\d+)", cf_text, re.IGNORECASE)
                        if port_match: listen_port = int(port_match.group(1))
                        priv_match = re.search(r"PrivateKey\s*=\s*(.*)", cf_text, re.IGNORECASE)
                        if priv_match:
                            s_priv = priv_match.group(1).strip()
                            server_pub_key = subprocess.check_output(f"echo '{s_priv}' | wg pubkey", shell=True, text=True).strip()
                    except Exception:
                        pass

            # اگر سرور لبه (Edge) باشد:
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

                cur.execute("SELECT server_ip, panel_url, panel_user, panel_pass FROM edge_servers WHERE server_ip=?", (target_server,))
                edge_row = cur.fetchone()
                if edge_row:
                    server_ip = edge_row["server_ip"] or "127.0.0.1"
                    panel_url = edge_row["panel_url"]
                    panel_user = edge_row["panel_user"]
                    panel_pass = edge_row["panel_pass"]
                    if panel_url and panel_user and panel_pass:
                        try:
                            import v100_master_edge_sync
                            session_edge = v100_master_edge_sync.get_edge_authenticated_session(panel_url, panel_user, panel_pass)
                            norm_url = panel_url.rstrip("/")
                            det_res = session_edge.get(f"{norm_url}/api/wireguard-details?config={clean_cfg}", timeout=4)
                            if det_res.status_code == 200:
                                d_json = det_res.json()
                                server_pub_key = d_json.get("public_key") or ""
                                listen_port = int(d_json.get("port") or 51820)
                        except Exception:
                            pass

        conf_content = f"""[Interface]
PrivateKey = {client_priv_key}
Address = {client_ip}/32
DNS = {dns}
MTU = {mtu}

[Peer]
PublicKey = {server_pub_key}
Endpoint = {server_ip}:{listen_port}
AllowedIPs = {allowed_ips}
PersistentKeepalive = {keepalive}
"""
        return Response(
            conf_content,
            mimetype="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache, no-store, must-revalidate"
            }
        )

    except Exception as e:
        app.logger.error(f"Error downloading config: {e}")
        return f"Error generating config: {e}", 500
# =========================================================================
# 📊 UNIFIED SYSTEM METRICS, TRAFFIC & SPEED ENGINE (STEP 4)
# =========================================================================

def format_smart_traffic(num_bytes) -> str:
    """فرمت‌بندی خوانا و استاندارد بایت (B, KB, MB, GB, TB)"""
    b = float(num_bytes or 0)
    if b >= 1024**4:
        tb = b / (1024**4)
        return f"{tb:.2f} TB" if tb != int(tb) else f"{int(tb)} TB"
    elif b >= 1024**3:
        gb = b / (1024**3)
        return f"{gb:.2f} GB" if gb != int(gb) else f"{int(gb)} GB"
    elif b >= 1024**2:
        mb = b / (1024**2)
        return f"{mb:.2f} MB" if mb != int(mb) else f"{int(mb)} MB"
    elif b >= 1024:
        return f"{b / 1024:.2f} KB"
    return f"{int(b)} B"

def format_smart_gb(gb_val) -> str:
    """فرمت‌بندی حجم‌های بر حسب گیگابایت برای سقف پکیج‌ها"""
    gb = float(gb_val or 0)
    if gb >= 1024:
        tb = gb / 1024.0
        return f"{tb:.2f} TB" if tb != int(tb) else f"{int(tb)} TB"
    return f"{gb:.2f} GB" if gb != int(gb) else f"{int(gb)} GB"

def calculate_traffic_unified():
    """محاسبه دقیق و اتمیک ترافیک مصرفی اینترفیس جاری / کل سرور و صندوق حذف‌شده‌ها"""
    config_file = "wg0.conf"
    is_client = (session.get('role') == 'client')

    if is_client:
        config_file = f"{session.get('interface', 'wg0')}.conf"
    else:
        req_cfg = request.args.get("config")
        if req_cfg:
            config_file = req_cfg

    if not config_file.endswith('.conf'):
        config_file += ".conf"

    interface = config_file.split(".")[0]
    total_bytes = 0
    limit_gb = 0.0

    try:
        with _db_lock, _connect() as conn:
            cur = conn.cursor()
            if interface == 'wg0' and not is_client:
                # ۱. مجموع کل ترافیک زنده تمام کلاینت‌ها روی تمام کارت‌ها
                r_live = cur.execute("SELECT SUM(used) FROM peers").fetchone()
                live_used = r_live[0] if r_live and r_live[0] else 0

                # ۲. ترافیک حذف‌شده ادمین
                cur.execute("CREATE TABLE IF NOT EXISTS global_deleted_traffic (id INTEGER PRIMARY KEY, total INTEGER DEFAULT 0)")
                r_del = cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1").fetchone()
                del_global = r_del[0] if r_del and r_del[0] else 0

                # ۳. ترافیک حذف‌شده نمایندگان
                cur.execute("CREATE TABLE IF NOT EXISTS sub_panels (id INTEGER PRIMARY KEY AUTOINCREMENT, interface_name TEXT UNIQUE, username TEXT UNIQUE, password_hash TEXT, data_limit_gb REAL, port INTEGER, created_at TEXT, status TEXT, disabled_at TEXT, password_plain TEXT, deleted_traffic INTEGER DEFAULT 0)")
                r_sub_del = cur.execute("SELECT SUM(deleted_traffic) FROM sub_panels").fetchone()
                sub_del_total = r_sub_del[0] if r_sub_del and r_sub_del[0] else 0

                # ۴. صندوق اینترفیس‌ها
                cur.execute("CREATE TABLE IF NOT EXISTS interface_vault (interface_name TEXT PRIMARY KEY, vault_bytes INTEGER DEFAULT 0)")
                r_vault = cur.execute("SELECT SUM(vault_bytes) FROM interface_vault").fetchone()
                vault_total = r_vault[0] if r_vault and r_vault[0] else 0

                total_bytes = live_used + max(del_global, vault_total) + sub_del_total
            else:
                # محاسبه اختصاصی برای نماینده و اینترفیس انتخابی
                r_live = cur.execute("SELECT SUM(used) FROM peers WHERE config=? OR config=?", (config_file, interface)).fetchone()
                live_used = r_live[0] if r_live and r_live[0] else 0

                cur.execute("CREATE TABLE IF NOT EXISTS sub_panels (id INTEGER PRIMARY KEY AUTOINCREMENT, interface_name TEXT UNIQUE, username TEXT UNIQUE, password_hash TEXT, data_limit_gb REAL, port INTEGER, created_at TEXT, status TEXT, disabled_at TEXT, password_plain TEXT, deleted_traffic INTEGER DEFAULT 0)")
                r_sub = cur.execute("SELECT deleted_traffic, data_limit_gb FROM sub_panels WHERE interface_name=?", (interface,)).fetchone()
                sub_del = r_sub[0] if r_sub and r_sub[0] else 0
                limit_gb = float(r_sub[1]) if r_sub and r_sub[1] else 0.0

                cur.execute("CREATE TABLE IF NOT EXISTS interface_vault (interface_name TEXT PRIMARY KEY, vault_bytes INTEGER DEFAULT 0)")
                r_v = cur.execute("SELECT vault_bytes FROM interface_vault WHERE interface_name=?", (interface,)).fetchone()
                v_bytes = r_v[0] if r_v and r_v[0] else 0

                total_bytes = live_used + max(sub_del, v_bytes)
    except Exception:
        pass

    used_str = format_smart_traffic(total_bytes)

    if (is_client or interface != 'wg0') and limit_gb > 0:
        limit_str = format_smart_gb(limit_gb)
        traffic_display = f"{used_str} / {limit_str}"
    else:
        traffic_display = used_str

    return traffic_display, total_bytes, limit_gb


def obtain_system_uptime():
    """سازگاری با کدهای داشبورد برای نمایش حجم کل به جای زمان آپتایم سرور"""
    return calculate_traffic_unified()[0]


@app.route("/api/metrics", methods=["GET"])
def obtain_metrics():
    """استعلام زنده آمار منابع (CPU, RAM, Disk, Traffic) برای حلقه‌های نئونی"""
    try:
        cpu_val = psutil.cpu_percent(interval=None) or 0.0
        ram_val = psutil.virtual_memory().percent or 0.0
        disk_val = psutil.disk_usage("/").percent or 0.0

        traffic_text, used_bytes, limit_gb = calculate_traffic_unified()

        traffic_percent = 0.0
        if limit_gb > 0:
            traffic_percent = min(100.0, max(0.0, round((used_bytes / (limit_gb * 1073741824.0)) * 100.0, 1)))

        is_client = (session.get('role') == 'client')
        req_cfg = request.args.get("config", "wg0.conf") if request.args else "wg0.conf"
        is_reseller = is_client or (req_cfg.replace('.conf', '') != 'wg0')

        return jsonify({
            "cpu": cpu_val,
            "ram": ram_val,
            "disk": disk_val,
            "disk_percent": disk_val,
            "disk_info": {"percent": disk_val},
            "uptime": traffic_text,
            "traffic": traffic_text,
            "uptime_percent": traffic_percent,
            "traffic_percent": traffic_percent,
            "is_reseller": is_reseller
        }), 200
    except Exception as e:
        return jsonify({
            "cpu": 0.0, "ram": 0.0, "disk": 0.0, "disk_percent": 0.0,
            "uptime": "0 B", "traffic": "0 B", "uptime_percent": 0.0, "traffic_percent": 0.0,
            "is_reseller": False
        }), 200


@app.route("/api/speed", methods=["GET"])
@app.route("/api/obtain_speed", methods=["GET"])
@app.route("/api/obtain-speed", methods=["GET"])
def obtain_speed():
    """محاسبه دقیق و زنده نرخ آپلود و دانلود بر روی کارت‌های شبکه WireGuard"""
    def get_wg_bytes():
        rx_sum, tx_sum = 0, 0
        try:
            for iface in os.listdir('/sys/class/net'):
                if iface.startswith('wg'):
                    try:
                        with open(f"/sys/class/net/{iface}/statistics/rx_bytes", "r") as f:
                            rx_sum += int(f.read().strip())
                        with open(f"/sys/class/net/{iface}/statistics/tx_bytes", "r") as f:
                            tx_sum += int(f.read().strip())
                    except Exception:
                        pass
        except Exception:
            pass
        return rx_sum, tx_sum

    try:
        r1, t1 = get_wg_bytes()
        time.sleep(0.5)
        r2, t2 = get_wg_bytes()
        down_speed = max(0.0, (r2 - r1) / (1024.0 * 0.5))
        up_speed = max(0.0, (t2 - t1) / (1024.0 * 0.5))

        return jsonify({
            'uploadSpeed': round(up_speed, 2),
            'downloadSpeed': round(down_speed, 2)
        }), 200
    except Exception:
        return jsonify({'uploadSpeed': 0.0, 'downloadSpeed': 0.0}), 200

# =========================================================================
# 🌐 UNIFIED CLUSTER, EDGE NODES, MASTER & PLANS ENGINE (STEP 5)
# =========================================================================

@app.route("/api/master-settings", methods=["GET", "POST"])
def api_master_settings():
    """مدیریت تنظیمات سرور اصلی (Endpoint، دامنه اختصاصی ساب‌لینک، نام سرور و پرچم)"""
    with _db_lock, _connect() as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(master_settings)")
        cols = [c["name"] for c in cur.fetchall()]
        for col_n in ["endpoint_domain", "ssh_ip", "server_name", "file_suffix", "sub_domain"]:
            if col_n not in cols:
                try:
                    cur.execute(f"ALTER TABLE master_settings ADD COLUMN {col_n} TEXT DEFAULT ''")
                except Exception:
                    pass

        if request.method == "GET":
            row = cur.execute("SELECT endpoint_domain, ssh_ip, server_name, file_suffix, sub_domain FROM master_settings LIMIT 1").fetchone()
            if row:
                return jsonify({
                    "endpoint_domain": row["endpoint_domain"] or "",
                    "ssh_ip": row["ssh_ip"] or "",
                    "server_name": row["server_name"] or "سرور اصلی",
                    "file_suffix": row["file_suffix"] or "",
                    "sub_domain": row["sub_domain"] or ""
                }), 200
            return jsonify({"endpoint_domain": "", "ssh_ip": "", "server_name": "سرور اصلی", "file_suffix": "", "sub_domain": ""}), 200

        elif request.method == "POST":
            data = request.get_json(silent=True) or request.form or {}
            endpoint = str(data.get("endpoint_domain") or "").strip()
            ssh_ip = str(data.get("ssh_ip") or "").strip()
            server_name = str(data.get("server_name") or "سرور اصلی").strip()
            file_suffix = str(data.get("file_suffix") or "").strip()
            sub_domain = str(data.get("sub_domain") or "").strip()

            row = cur.execute("SELECT id FROM master_settings LIMIT 1").fetchone()
            if row:
                cur.execute(
                    "UPDATE master_settings SET endpoint_domain=?, ssh_ip=?, server_name=?, file_suffix=?, sub_domain=? WHERE id=?", 
                    (endpoint, ssh_ip, server_name, file_suffix, sub_domain, row["id"])
                )
            else:
                cur.execute(
                    "INSERT INTO master_settings (endpoint_domain, ssh_ip, server_name, file_suffix, sub_domain) VALUES (?, ?, ?, ?, ?)", 
                    (endpoint, ssh_ip, server_name, file_suffix, sub_domain)
                )
            conn.commit()
            return jsonify({"success": True, "message": "تنظیمات سرور اصلی با موفقیت ذخیره شد."}), 200


@app.route("/api/edge-servers", methods=["GET", "POST", "DELETE"])
def api_edge_servers():
    """مدیریت نودهای لبه کلاسترینگ (افزودن، ویرایش، حذف و استعلام)"""
    with _db_lock, _connect() as conn:
        cur = conn.cursor()

        if request.method == "GET":
            cur.execute("SELECT id, server_ip, panel_url, panel_user, panel_pass, ssh_ip, ssh_port, ssh_user, ssh_pass, location, flag, server_name, file_suffix FROM edge_servers")
            servers = []
            for r in cur.fetchall():
                servers.append({
                    "id": r["id"],
                    "server_ip": r["server_ip"],
                    "panel_url": r["panel_url"],
                    "panel_user": r["panel_user"],
                    "panel_pass": r["panel_pass"],
                    "ssh_ip": r["ssh_ip"],
                    "ssh_port": r["ssh_port"] or 22,
                    "ssh_user": r["ssh_user"] or "root",
                    "ssh_pass": r["ssh_pass"],
                    "location": r["location"] or "Unknown",
                    "flag": r["flag"] or "🌍",
                    "server_name": r["server_name"] or r["server_ip"],
                    "file_suffix": r["file_suffix"] or ""
                })
            return jsonify(servers), 200

        elif request.method == "POST":
            data = request.get_json(silent=True) or request.form or {}
            srv_id = data.get("id")
            ip = str(data.get("server_ip") or "").strip()
            p_url = str(data.get("panel_url") or "").strip()
            p_user = str(data.get("panel_user") or "").strip()
            p_pass = str(data.get("panel_pass") or "").strip()
            s_ip = str(data.get("ssh_ip") or ip).strip()
            s_port = int(data.get("ssh_port") or 22)
            s_user = str(data.get("ssh_user") or "root").strip()
            s_pass = str(data.get("ssh_pass") or "").strip()
            s_name = str(data.get("server_name") or ip).strip()
            s_suf = str(data.get("file_suffix") or "").strip()

            if not ip or not p_url or not p_user or not p_pass:
                return jsonify({"error": "تمام فیلدهای الزامی نود باید تکمیل شوند."}), 400

            location = "Unknown"
            flag = "🛡️"
            try:
                test_ip = s_ip or ip
                geo = requests.get(f"http://ip-api.com/json/{test_ip}", timeout=2).json()
                location = geo.get("country", "Unknown")
                cc = geo.get("countryCode", "")
                if cc:
                    flag = "".join(chr(127397 + ord(c)) for c in cc.upper())
            except Exception:
                pass

            if srv_id:
                cur.execute("""
                    UPDATE edge_servers SET server_ip=?, panel_url=?, panel_user=?, panel_pass=?, ssh_ip=?, 
                                            ssh_port=?, ssh_user=?, ssh_pass=?, location=?, flag=?, server_name=?, file_suffix=? 
                    WHERE id=?
                """, (ip, p_url, p_user, p_pass, s_ip, s_port, s_user, s_pass, location, flag, s_name, s_suf, srv_id))
            else:
                cur.execute("""
                    INSERT INTO edge_servers (server_ip, panel_url, panel_user, panel_pass, ssh_ip, ssh_port, ssh_user, ssh_pass, location, flag, server_name, file_suffix, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """, (ip, p_url, p_user, p_pass, s_ip, s_port, s_user, s_pass, location, flag, s_name, s_suf))

            conn.commit()
            return jsonify({"success": True, "message": "اطلاعات سرور لبه با موفقیت ذخیره شد."}), 200

        elif request.method == "DELETE":
            srv_id = request.args.get("id")
            if srv_id:
                row = cur.execute("SELECT server_ip FROM edge_servers WHERE id=?", (srv_id,)).fetchone()
                if row:
                    cur.execute("DELETE FROM peer_synced_edges WHERE server_ip=?", (row["server_ip"],))
                cur.execute("DELETE FROM edge_servers WHERE id=?", (srv_id,))
                conn.commit()
            return jsonify({"success": True, "message": "سرور لبه حذف شد."}), 200


@app.route("/api/advanced-settings", methods=["GET", "POST", "DELETE"])
def api_advanced_settings():
    """مدیریت پلن‌های پیشرفته ساب‌لینک (تخصیص MTU, DNS, Keepalive و نودهای مجاز)"""
    with _db_lock, _connect() as conn:
        cur = conn.cursor()

        if request.method == "GET":
            cur.execute("SELECT id, plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers FROM subscription_plans")
            plans = []
            for r in cur.fetchall():
                try:
                    active_s = json.loads(r["active_servers"]) if r["active_servers"] else ["master"]
                except Exception:
                    active_s = ["master"]
                plans.append({
                    "id": r["id"],
                    "plan_name": r["plan_name"],
                    "description": r["description"] or "",
                    "suffix": r["suffix"] or "",
                    "mtu": r["mtu"] or 1420,
                    "dns": r["dns"] or "1.1.1.1, 1.0.0.1",
                    "keepalive": r["keepalive"] or 25,
                    "allowed_ips": r["allowed_ips"] or "0.0.0.0/0, ::/0",
                    "active_servers": active_s
                })
            return jsonify(plans), 200

        elif request.method == "POST":
            data = request.get_json(silent=True) or request.form or {}
            plan_id = data.get("id")
            name = str(data.get("plan_name") or "").strip()
            desc = str(data.get("description") or "").strip()
            suffix = str(data.get("suffix") or "").strip()
            mtu = int(data.get("mtu") or 1420)
            dns = str(data.get("dns") or "1.1.1.1, 1.0.0.1").strip()
            keepalive = int(data.get("keepalive") or 25)
            allowed_ips = str(data.get("allowed_ips") or "0.0.0.0/0, ::/0").strip()
            active_servers = json.dumps(data.get("active_servers") or ["master"])

            if not name:
                return jsonify({"error": "نام پلن الزامی است."}), 400

            if plan_id:
                cur.execute("""
                    UPDATE subscription_plans 
                    SET plan_name=?, description=?, suffix=?, mtu=?, dns=?, keepalive=?, allowed_ips=?, active_servers=? 
                    WHERE id=?
                """, (name, desc, suffix, mtu, dns, keepalive, allowed_ips, active_servers, plan_id))
            else:
                cur.execute("""
                    INSERT INTO subscription_plans (plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, desc, suffix, mtu, dns, keepalive, allowed_ips, active_servers))

            conn.commit()
            return jsonify({"success": True, "message": "پلن اشتراک ذخیره شد."}), 200

        elif request.method == "DELETE":
            plan_id = request.args.get("id")
            if plan_id:
                cur.execute("DELETE FROM subscription_plans WHERE id=?", (plan_id,))
                conn.commit()
            return jsonify({"success": True, "message": "پلن حذف شد."}), 200


@app.route("/api/client-special-mode", methods=["GET", "POST"])
def api_client_special_mode():
    """مدیریت فعال/غیرفعال بودن حالت ویژه (Special Mode) برای هر اینترفیس"""
    interface = session.get('interface', 'wg0')
    if session.get('role') == 'admin':
        interface = (request.args.get("config") or "wg0.conf").replace(".conf", "")

    with _db_lock, _connect() as conn:
        cur = conn.cursor()

        if request.method == "GET":
            row = cur.execute("SELECT special_mode FROM client_settings WHERE interface_name=?", (interface,)).fetchone()
            mode = row["special_mode"] if row and row["special_mode"] is not None else 1
            return jsonify({"special_mode": mode}), 200

        elif request.method == "POST":
            data = request.get_json(silent=True) or request.form or {}
            mode = int(data.get("special_mode", 1))

            cur.execute("""
                INSERT INTO client_settings (interface_name, special_mode) VALUES (?, ?)
                ON CONFLICT(interface_name) DO UPDATE SET special_mode=excluded.special_mode
            """, (interface, mode))
            conn.commit()
            return jsonify({"success": True, "special_mode": mode}), 200

# =========================================================================
# 🚀 UNIFIED TUNNELING (XRAY & SMITE), SSL & BULK EXTEND ENGINE (STEP 6)
# =========================================================================

# -------------------------------------------------------------------------
# 🌐 XRAY CORE & PROXY ROUTING CONTROLLER
# -------------------------------------------------------------------------

def parse_proxy_link_to_xray_outbound(link_str: str) -> dict:
    """تبدیل انواع لینک‌های پروکسی (VLESS, Trojan, Shadowsocks, WireGuard, SOCKS) به Outbound استاندارد Xray"""
    link = str(link_str).strip()
    
    # ۱. کانفیگ کامل وایرگارد
    if "[Interface]" in link and "[Peer]" in link:
        priv_m = re.search(r"PrivateKey\s*=\s*(.*)", link, re.I)
        addr_m = re.search(r"Address\s*=\s*(.*)", link, re.I)
        pub_m = re.search(r"PublicKey\s*=\s*(.*)", link, re.I)
        end_m = re.search(r"Endpoint\s*=\s*(.*)", link, re.I)
        
        priv = priv_m.group(1).strip() if priv_m else ""
        addr = addr_m.group(1).strip() if addr_m else ""
        pub = pub_m.group(1).strip() if pub_m else ""
        endpoint = end_m.group(1).strip() if end_m else ""

        return {
            "tag": "proxy",
            "protocol": "wireguard",
            "settings": {
                "secretKey": priv,
                "address": [a.strip() for a in addr.split(",") if a.strip()],
                "peers": [{
                    "publicKey": pub,
                    "endpoint": endpoint,
                    "keepAlive": 25
                }]
            }
        }

    # ۲. لینک‌های VLESS
    if link.startswith("vless://"):
        m = re.search(r"vless://([^@]+)@([^:]+):(\d+)(\?.*)?", link)
        if m:
            uuid, host, port, query = m.group(1), m.group(2), int(m.group(3)), m.group(4) or ""
            sec = "tls" if "security=tls" in query else ("reality" if "security=reality" in query else "none")
            net = "ws" if "type=ws" in query else ("grpc" if "type=grpc" in query else "tcp")
            return {
                "protocol": "vless",
                "tag": "proxy",
                "settings": {
                    "vnext": [{
                        "address": host,
                        "port": port,
                        "users": [{"id": uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": {"network": net, "security": sec}
            }

    # ۳. لینک‌های Trojan
    if link.startswith("trojan://"):
        m = re.search(r"trojan://([^@]+)@([^:]+):(\d+)(\?.*)?", link)
        if m:
            passw, host, port, query = m.group(1), m.group(2), int(m.group(3)), m.group(4) or ""
            sec = "tls" if "security=tls" in query else "none"
            return {
                "protocol": "trojan",
                "tag": "proxy",
                "settings": {
                    "servers": [{"address": host, "port": port, "password": passw}]
                },
                "streamSettings": {"security": sec}
            }

    # ۴. لینک‌های SOCKS5
    if link.startswith("socks://") or link.startswith("socks5://"):
        m = re.search(r"socks5?://([^:]+):(\d+)", link)
        if m:
            host, port = m.group(1), int(m.group(2))
            return {
                "protocol": "socks",
                "tag": "proxy",
                "settings": {
                    "servers": [{"address": host, "port": port}]
                }
            }

    return {"protocol": "freedom", "tag": "proxy"}

def apply_xray_iptables_routing(enable: bool = True):
    """هدایت خودکار و مستقیم ترافیک کارت‌های شبکه وایرگارد به پورت Dokodemo-Door پروکسی Xray"""
    try:
        xray_port = 12345
        wg_ifaces = []
        if os.path.exists(WIREGUARD_CONFIG_DIR):
            for f in os.listdir(WIREGUARD_CONFIG_DIR):
                if f.endswith(".conf"):
                    wg_ifaces.append(f.replace(".conf", ""))
        if not wg_ifaces:
            wg_ifaces = ["wg0"]

        subprocess.run("sysctl -w net.ipv4.ip_forward=1", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for iface in wg_ifaces:
            subprocess.run(f"iptables -t nat -D PREROUTING -i {iface} -p tcp -j REDIRECT --to-ports {xray_port}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(f"iptables -t nat -D PREROUTING -i {iface} -p udp --dport 53 -j REDIRECT --to-ports {xray_port}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if enable:
                subprocess.run(f"iptables -t nat -I PREROUTING -i {iface} -p tcp -j REDIRECT --to-ports {xray_port}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(f"iptables -t nat -I PREROUTING -i {iface} -p udp --dport 53 -j REDIRECT --to-ports {xray_port}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(f"iptables -A FORWARD -i {iface} -j ACCEPT", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if enable:
            subprocess.run(f"iptables -t nat -I PREROUTING -i wg+ -p tcp -j REDIRECT --to-ports {xray_port}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        app.logger.warning(f"Xray iptables error: {e}")

@app.route("/api/xray-settings", methods=["GET", "POST"])
@app.route("/api/xray-check", methods=["GET", "POST"])
def api_xray_settings():
    """استعلام و ذخیره کانفیگ تانل Xray با تفکیک هوشمند ترافیک ایران و پروکسی خارجی"""
    with _db_lock, _connect() as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS xray_tunnel_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, proxy_link TEXT, status INTEGER DEFAULT 0)")
        conn.commit()

        if request.method == "GET":
            row = cur.execute("SELECT proxy_link, status FROM xray_tunnel_settings LIMIT 1").fetchone()
            if row:
                return jsonify({"success": True, "proxy_link": row["proxy_link"] or "", "status": row["status"] or 0}), 200
            return jsonify({"success": True, "proxy_link": "", "status": 0}), 200

        elif request.method == "POST":
            try:
                data = request.get_json(silent=True) or request.form or {}
                link = str(data.get("proxy_link") or "").strip()
                status = int(data.get("status") or 0)

                cur.execute("DELETE FROM xray_tunnel_settings")
                cur.execute("INSERT INTO xray_tunnel_settings (proxy_link, status) VALUES (?, ?)", (link, status))
                conn.commit()

                xray_cfg_path = "/usr/local/etc/xray/config.json"
                os.makedirs(os.path.dirname(xray_cfg_path), exist_ok=True)

                if status == 1 and link:
                    proxy_outbound = parse_proxy_link_to_xray_outbound(link)
                    xray_cfg = {
                        "log": {"loglevel": "warning"},
                        "routing": {
                            "domainStrategy": "IPIfNonMatch",
                            "rules": [
                                {"type": "field", "outboundTag": "direct", "domain": ["regexp:.*\\.ir$", "geosite:ir", "geosite:category-ir"], "ip": ["geoip:ir", "geoip:private"]},
                                {"type": "field", "outboundTag": "proxy", "network": "tcp,udp"}
                            ]
                        },
                        "inbounds": [{
                            "tag": "wg-inbound", "port": 12345, "listen": "0.0.0.0",
                            "protocol": "dokodemo-door",
                            "settings": {"network": "tcp,udp", "followRedirect": True}
                        }],
                        "outbounds": [proxy_outbound, {"protocol": "freedom", "tag": "direct"}]
                    }
                    with open(xray_cfg_path, "w", encoding="utf-8") as xf:
                        json.dump(xray_cfg, xf, indent=2)

                    apply_xray_iptables_routing(enable=True)
                    subprocess.run("systemctl restart xray", shell=True, stderr=subprocess.DEVNULL)
                else:
                    apply_xray_iptables_routing(enable=False)
                    subprocess.run("systemctl stop xray", shell=True, stderr=subprocess.DEVNULL)

                return jsonify({"success": True, "message": "تنظیمات تانل Xray ذخیره و اعمال شد."}), 200
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/xray-ping", methods=["GET", "POST"])
def api_xray_ping():
    """تست تاخیر و پینگ زنده پروکسی وارد شده"""
    import socket
    proxy_link = request.args.get("proxy_link") or (request.get_json(silent=True) or {}).get("proxy_link") or ""
    if not proxy_link:
        return jsonify({"success": False, "error": "پروکسی وارد نشده است.", "ping": 0}), 200

    host, port = None, 443
    if "://" in proxy_link:
        m = re.search(r"@([^:/]+):(\d+)", proxy_link) or re.search(r"://([^:/]+):(\d+)", proxy_link)
        if m:
            host, port = m.group(1), int(m.group(2))
    elif ":" in proxy_link:
        parts = proxy_link.split(":")
        host, port = parts[0], int(parts[1]) if parts[1].isdigit() else 443
    else:
        host = proxy_link.strip()

    if not host:
        return jsonify({"success": False, "error": "آدرس هاست نامعتبر است.", "ping": 0}), 200

    try:
        start_t = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.5)
        res = sock.connect_ex((host, port))
        sock.close()
        ping_ms = int((time.time() - start_t) * 1000)

        if res == 0:
            return jsonify({"success": True, "ping": ping_ms, "host": host, "port": port}), 200
        return jsonify({"success": False, "error": f"عدم برقراری ارتباط با {host}:{port}", "ping": 0}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "ping": 0}), 200


# -------------------------------------------------------------------------
# 🔒 SSL / TLS CERTIFICATE CONTROLLER
# -------------------------------------------------------------------------

@app.route("/api/ssl-detect", methods=["GET"])
def api_ssl_detect():
    """تشخیص خودکار مسیر و محتوای گواهی Let's Encrypt موجود روی سرور"""
    if not session.get('logged_in') or session.get('role') == 'client':
        return jsonify(error="Unauthorized"), 401

    fc_path, pk_path = "", ""
    for c_dir in glob.glob("/etc/letsencrypt/live/*/"):
        fc = os.path.join(c_dir, "fullchain.pem")
        pk = os.path.join(c_dir, "privkey.pem")
        if os.path.exists(fc) and os.path.exists(pk):
            fc_path, pk_path = fc, pk
            break

    if not fc_path:
        fc_path = "/etc/letsencrypt/live/domain/fullchain.pem"
        pk_path = "/etc/letsencrypt/live/domain/privkey.pem"

    fc_content, pk_content = "", ""
    if os.path.exists(fc_path):
        try:
            with open(fc_path, "r", encoding="utf-8") as f: fc_content = f.read()
        except Exception: pass
    if os.path.exists(pk_path):
        try:
            with open(pk_path, "r", encoding="utf-8") as f: pk_content = f.read()
        except Exception: pass

    return jsonify({
        "success": True,
        "fullchain": fc_path,
        "privkey": pk_path,
        "fullchain_content": fc_content,
        "privkey_content": pk_content
    }), 200

@app.route("/api/ssl-settings", methods=["GET", "POST"])
def api_ssl_settings():
    """ذخیره محتوا و مسیر گواهی SSL و ریستارت خودکار پنل وب"""
    if not session.get('logged_in') or session.get('role') == 'client':
        return jsonify(error="Unauthorized"), 401

    with _db_lock, _connect() as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS ssl_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, fullchain_path TEXT, privkey_path TEXT)")
        conn.commit()

        if request.method == "GET":
            row = cur.execute("SELECT fullchain_path, privkey_path FROM ssl_settings LIMIT 1").fetchone()
            fc_path = row["fullchain_path"] if row else "/etc/letsencrypt/live/domain/fullchain.pem"
            pk_path = row["privkey_path"] if row else "/etc/letsencrypt/live/domain/privkey.pem"

            fc_content, pk_content = "", ""
            if os.path.exists(fc_path):
                try:
                    with open(fc_path, "r", encoding="utf-8") as f: fc_content = f.read()
                except Exception: pass
            if os.path.exists(pk_path):
                try:
                    with open(pk_path, "r", encoding="utf-8") as f: pk_content = f.read()
                except Exception: pass

            return jsonify({
                "fullchain": fc_path,
                "privkey": pk_path,
                "fullchain_content": fc_content,
                "privkey_content": pk_content
            }), 200

        elif request.method == "POST":
            data = request.get_json(silent=True) or {}
            fullchain = str(data.get("fullchain") or "").strip()
            privkey = str(data.get("privkey") or "").strip()
            fc_content = str(data.get("fullchain_content") or "").strip()
            pk_content = str(data.get("privkey_content") or "").strip()

            if not fullchain or not privkey:
                return jsonify(error="مسیر فایل‌های SSL الزامی است."), 400

            if fc_content:
                os.makedirs(os.path.dirname(fullchain), exist_ok=True)
                with open(fullchain, "w", encoding="utf-8") as f: f.write(fc_content + "\n")
            if pk_content:
                os.makedirs(os.path.dirname(privkey), exist_ok=True)
                with open(privkey, "w", encoding="utf-8") as f: f.write(pk_content + "\n")
                os.chmod(privkey, 0o600)

            cur.execute("DELETE FROM ssl_settings")
            cur.execute("INSERT INTO ssl_settings (fullchain_path, privkey_path) VALUES (?, ?)", (fullchain, privkey))
            conn.commit()

            config_yaml = os.path.join(BASE_DIR, "config.yaml")
            if os.path.exists(config_yaml):
                try:
                    with open(config_yaml, 'r', encoding='utf-8') as f:
                        cfg = yaml.safe_load(f) or {}
                    cfg.setdefault("flask", {})
                    cfg["flask"]["tls"] = True
                    cfg["flask"]["cert_path"] = fullchain
                    cfg["flask"]["key_path"] = privkey
                    with open(config_yaml, 'w', encoding='utf-8') as f:
                        yaml.dump(cfg, f, default_flow_style=False)
                except Exception: pass

            threading.Thread(target=lambda: (time.sleep(1), subprocess.run("systemctl restart wireguard-panel", shell=True)), daemon=True).start()
            return jsonify(success=True, message="گواهی SSL با موفقیت ذخیره شد. پنل در حال راه‌اندازی مجدد است..."), 200


# -------------------------------------------------------------------------
# 🛰️ SMITE TUNNEL (BACKHAUL / IPV6) CONTROLLER
# -------------------------------------------------------------------------

def smite_request(panel_url, endpoint, method="GET", payload=None, token=None):
    url = f"{panel_url.rstrip('/')}{endpoint}"
    headers = {"Accept": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    data_bytes = json.dumps(payload).encode('utf-8') if (method in ["POST", "PUT"] and payload is not None) else None
    if data_bytes: headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_body = resp.read().decode('utf-8')
            try: return json.loads(res_body)
            except Exception: return res_body
    except Exception as e:
        return {"error": str(e)}

@app.route("/api/smite-settings", methods=["GET", "POST"])
def api_smite_settings():
    """مدیریت تنظیمات تانل معکوس Smite"""
    if session.get('role') == 'client':
        return jsonify(error="Unauthorized"), 403

    with _db_lock, _connect() as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS smite_tunnel_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, panel_url TEXT DEFAULT 'http://127.0.0.1:8009', username TEXT DEFAULT 'Pars', password TEXT DEFAULT 'Pars', iran_node_id TEXT DEFAULT 'local', foreign_node_id TEXT DEFAULT 'local', auto_tunnel_resellers INTEGER DEFAULT 1, accept_udp INTEGER DEFAULT 1, use_ipv6 INTEGER DEFAULT 1, updated_at TEXT)")
        conn.commit()

        if request.method == "GET":
            row = cur.execute("SELECT panel_url, username, password, iran_node_id, foreign_node_id, auto_tunnel_resellers, accept_udp, use_ipv6 FROM smite_tunnel_settings LIMIT 1").fetchone()
            if row:
                return jsonify({
                    "panel_url": row["panel_url"], "username": row["username"], "password": row["password"],
                    "iran_node_id": row["iran_node_id"], "foreign_node_id": row["foreign_node_id"],
                    "auto_tunnel_resellers": bool(row["auto_tunnel_resellers"]),
                    "accept_udp": bool(row["accept_udp"]),
                    "use_ipv6": bool(row["use_ipv6"])
                }), 200
            return jsonify({"panel_url": "http://127.0.0.1:8009", "username": "Pars", "password": "Pars", "iran_node_id": "local", "foreign_node_id": "local", "auto_tunnel_resellers": True, "accept_udp": True, "use_ipv6": True}), 200

        elif request.method == "POST":
            data = request.get_json(silent=True) or {}
            p_url = str(data.get("panel_url") or "http://127.0.0.1:8009").strip()
            p_user = str(data.get("username") or "Pars").strip()
            p_pass = str(data.get("password") or "Pars").strip()
            iran_node = str(data.get("iran_node_id") or "local").strip()
            foreign_node = str(data.get("foreign_node_id") or "local").strip()
            auto_tunnel = 1 if data.get("auto_tunnel_resellers", True) else 0
            accept_udp = 1 if data.get("accept_udp", True) else 0
            use_ipv6 = 1 if data.get("use_ipv6", True) else 0

            cur.execute("DELETE FROM smite_tunnel_settings")
            cur.execute("INSERT INTO smite_tunnel_settings (panel_url, username, password, iran_node_id, foreign_node_id, auto_tunnel_resellers, accept_udp, use_ipv6, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))", (p_url, p_user, p_pass, iran_node, foreign_node, auto_tunnel, accept_udp, use_ipv6))
            conn.commit()
            return jsonify(success=True, message="تنظیمات تانل Smite ذخیره شد."), 200

@app.route("/api/smite-nodes", methods=["GET"])
def api_smite_nodes():
    """واکشی لایو لیست نودهای Smite"""
    if session.get('role') == 'client':
        return jsonify(error="Unauthorized"), 403

    with _db_lock, _connect() as conn:
        row = conn.execute("SELECT panel_url, username, password FROM smite_tunnel_settings LIMIT 1").fetchone()
    p_url = row["panel_url"] if row else "http://127.0.0.1:8009"
    p_user = row["username"] if row else "Pars"
    p_pass = row["password"] if row else "Pars"

    login_res = smite_request(p_url, "/api/auth/login", "POST", {"username": p_user, "password": p_pass})
    token = login_res.get("access_token") if isinstance(login_res, dict) else None
    if not token:
        return jsonify(error="عدم امکان لاگین به پنل Smite."), 400

    nodes_res = smite_request(p_url, "/api/nodes", "GET", token=token)
    return jsonify(success=True, nodes=nodes_res if isinstance(nodes_res, list) else []), 200

@app.route("/api/smite-sync-tunnels", methods=["POST"])
def api_smite_sync_tunnels():
    """بررسی و ساخت خودکار تانل‌های Backhaul روی تمام پورت‌های وایرگارد"""
    if session.get('role') == 'client':
        return jsonify(success=False, logs=["❌ عدم دسترسی کاربر"]), 403

    logs = ["🚀 شروع فرآیند همگام‌سازی تانل‌های Smite..."]
    try:
        with _db_lock, _connect() as conn:
            s_row = conn.execute("SELECT panel_url, username, password, iran_node_id, foreign_node_id, accept_udp, use_ipv6 FROM smite_tunnel_settings LIMIT 1").fetchone()
        if not s_row:
            return jsonify(success=False, logs=["❌ تنظیمات Smite یافت نشد."]), 200

        p_url = s_row["panel_url"]
        login_res = smite_request(p_url, "/api/auth/login", "POST", {"username": s_row["username"], "password": s_row["password"]})
        token = login_res.get("access_token") if isinstance(login_res, dict) else None
        if not token:
            return jsonify(success=False, logs=["❌ خطا در ورود به Smite."]), 200

        nodes = smite_request(p_url, "/api/nodes", "GET", token=token)
        nodes = nodes if isinstance(nodes, list) else []

        iran_id = None if s_row["iran_node_id"] == "local" else s_row["iran_node_id"]
        foreign_id = None if s_row["foreign_node_id"] == "local" else s_row["foreign_node_id"]
        foreign_ip = "127.0.0.1"

        for n in nodes:
            r = (n.get("metadata") or {}).get("role", "")
            if not iran_id and r == "iran": iran_id = n.get("id")
            if not foreign_id and r == "foreign":
                foreign_id = n.get("id")
                foreign_ip = (n.get("metadata") or {}).get("ip_address", "127.0.0.1")

        if not iran_id and nodes: iran_id = nodes[0].get("id")
        if not foreign_id and nodes: foreign_id = nodes[0].get("id")

        wg_ports = []
        if os.path.exists(WIREGUARD_CONFIG_DIR):
            for f in os.listdir(WIREGUARD_CONFIG_DIR):
                if f.endswith('.conf'):
                    try:
                        txt = open(os.path.join(WIREGUARD_CONFIG_DIR, f), 'r').read()
                        m = re.search(r"ListenPort\s*=\s*(\d+)", txt, re.IGNORECASE)
                        if m: wg_ports.append({"iface": f.replace('.conf', ''), "port": int(m.group(1))})
                    except Exception: pass

        for idx, wp in enumerate(wg_ports):
            ctrl_port = 7080 + idx
            payload = {
                "name": f"WG-{wp['iface']}-{wp['port']}", "core": "backhaul", "type": "tcp",
                "iran_node_id": iran_id, "foreign_node_id": foreign_id,
                "spec": {
                    "transport": "tcp", "bind_addr": f"0.0.0.0:{ctrl_port}", "remote_addr": f"{foreign_ip}:{ctrl_port}",
                    "listen_ip": "0.0.0.0", "control_port": ctrl_port, "public_port": wp['port'], "listen_port": wp['port'],
                    "target_host": "127.0.0.1", "target_port": wp['port'], "target_addr": f"127.0.0.1:{wp['port']}",
                    "public_host": foreign_ip, "ports": [f"{wp['port']}=127.0.0.1:{wp['port']}"],
                    "accept_udp": bool(s_row["accept_udp"]), "use_ipv6": bool(s_row["use_ipv6"])
                }
            }
            c_res = smite_request(p_url, "/api/tunnels", "POST", payload=payload, token=token)
            if isinstance(c_res, dict) and c_res.get("id"):
                smite_request(p_url, f"/api/tunnels/{c_res['id']}/apply", "POST", token=token)
                logs.append(f"  ✔ تانل پورت {wp['port']} فعال گردید.")

        logs.append("🎉 عملیات تانلینگ Smite با موفقیت تکمیل شد.")
        return jsonify(success=True, logs=logs), 200
    except Exception as e:
        return jsonify(success=False, logs=[f"❌ خطا: {e}"]), 200


# -------------------------------------------------------------------------
# 📅 BULK EXTEND (VOLUME & TIME) ENGINE
# -------------------------------------------------------------------------

@app.route("/api/bulk-extend", methods=["POST"])
def api_bulk_extend_peers():
    """شارژ گروهی حجم یا زمان با پشتیبانی از بازه زمانی تاریخ ساخت یا اولین اتصال"""
    if session.get('role') == 'client':
        return jsonify(error="دسترسی غیرمجاز."), 403

    data = request.get_json(silent=True) or {}
    ext_type = data.get("type")
    
    try:
        amount = float(data.get("amount", 0) or 0.0)
    except ValueError:
        return jsonify(error="مقدار عددی نامعتبر است."), 400

    if amount <= 0:
        return jsonify(error="مقدار باید بیشتر از صفر باشد."), 400

    start_g = parse_smart_dual_date(data.get("start_date"), is_end=False)
    end_g = parse_smart_dual_date(data.get("end_date"), is_end=True)

    try:
        with _db_lock, _connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, peer_name, config, [limit], used, remaining_time, public_key, peer_ip, 
                       monitor_blocked, expiry_blocked, created_at_gregorian, first_connected_gregorian 
                FROM peers WHERE config='wg0.conf'
            """)
            all_peers = cur.fetchall()

            updated_peers = []
            for row in all_peers:
                target_date_str = row["first_connected_gregorian"] or row["created_at_gregorian"]
                
                if start_g or end_g:
                    if not target_date_str:
                        continue
                    try:
                        p_date = datetime.strptime(str(target_date_str)[:19], "%Y-%m-%d %H:%M:%S")
                        if start_g and p_date < start_g: continue
                        if end_g and p_date > end_g: continue
                    except Exception:
                        continue

                new_limit = row["limit"]
                new_rem = int(row["remaining_time"] or 0)
                new_m_blk = int(row["monitor_blocked"] or 0)
                new_e_blk = int(row["expiry_blocked"] or 0)

                if ext_type == 'volume':
                    cur_lim_bytes = convert_to_bytes(new_limit)
                    add_bytes = int(amount * 1073741824)
                    new_lim_bytes = cur_lim_bytes + add_bytes
                    new_limit = format_smart_traffic(new_lim_bytes).replace(" ", "")
                    if int(row["used"] or 0) < new_lim_bytes:
                        new_m_blk = 0
                elif ext_type == 'time':
                    new_rem += int(amount * 1440)
                    if new_rem > 0:
                        new_e_blk = 0

                cur.execute("UPDATE peers SET [limit]=?, remaining_time=?, monitor_blocked=?, expiry_blocked=? WHERE id=?", 
                            (new_limit, new_rem, new_m_blk, new_e_blk, row["id"]))

                if new_m_blk == 0 and new_e_blk == 0:
                    if row["peer_ip"]: subprocess.run(f"ip route del blackhole {row['peer_ip']}", shell=True, stderr=subprocess.DEVNULL)
                    if row["public_key"] and row["peer_ip"]: subprocess.run(f"wg set wg0 peer {row['public_key']} allowed-ips {row['peer_ip']}/32", shell=True, stderr=subprocess.DEVNULL)

                updated_peers.append({"peer_name": row["peer_name"], "config": "wg0.conf", "limit": new_limit, "remaining_time": new_rem})

            conn.commit()

        # همگام‌سازی تغییرات با نودها
        if updated_peers:
            try:
                import v100_master_edge_sync
                for up in updated_peers:
                    v100_master_edge_sync.sync_action_to_edges("edit", up["peer_name"], up["config"], extra_data=up)
            except Exception: pass

        return jsonify(message=f"تعداد {len(updated_peers)} کاربر با موفقیت تمدید و همگام‌سازی شدند."), 200
    except Exception as e:
        return jsonify(error=f"خطا در شارژ گروهی: {e}"), 500

# =========================================================================
# 🏁 APPLICATION INITIALIZER & RUNNER (SECURE & BUG-FREE)
# =========================================================================

if __name__ == '__main__':
    # ۱. مقداردهی اولیه دیتابیس
    init_sqlite(BASE_DIR)
    
    # ۲. بارگذاری امن و مستقل تنظیمات جهت جلوگیری از تداخل متغیر سراسری
    app_cfg = load_config()
    if not isinstance(app_cfg, dict):
        app_cfg = {}

    # ۳. راه‌اندازی زمان‌بند بکاپ خودکار
    try:
        if 'scheduler' in globals() and not scheduler.running:
            auto_backup_int = app_cfg.get("wireguard", {}).get("auto_backup_int", 30)
            scheduler.add_job(
                create_automated_backup,
                "interval",
                minutes=auto_backup_int,
                id="automated_backup",
                replace_existing=True
            )
            scheduler.start()
    except Exception as ex_sc:
        print(f"[Scheduler Warning]: {ex_sc}")

    # ۴. احیای خودکار و اتصال کلاستر
    try:
        import v100_master_edge_sync
        v100_master_edge_sync.auto_heal_and_recover_ghosts_live()
        v100_master_edge_sync.bind_v100_hooks(app)
    except Exception as ex_init:
        print(f"[Init Warning] Cluster hook notice: {ex_init}")

    # ۵. استخراج پورت و راه‌اندازی سرور
    flask_port = int(app_cfg.get("flask", {}).get("port", 5000))
    debug_mode = bool(app_cfg.get("flask", {}).get("debug", False))
    
    print(f"🚀 WireGuard Panel is running on port {flask_port} (Debug: {debug_mode})")
    app.run(host='0.0.0.0', port=flask_port, debug=debug_mode)
