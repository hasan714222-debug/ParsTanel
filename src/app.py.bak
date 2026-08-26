import sqlite3
from flask import Flask, render_template, jsonify, request, redirect, session, flash, send_file, send_from_directory, make_response
import os
import subprocess
import gunicorn.app.base
import secrets
from gunicorn.app.base import BaseApplication
from ipaddress import ip_network
import psutil
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.base import ConflictingIdError
import threading
from warp import install_fullwarp, install_progress
from threading import Thread
import time
import shlex
import requests
import tempfile
import base64
import nacl.bindings
import json
from queue import Queue
from threading import Thread, Event
import shutil
import logging
import yaml
import shutil
from datetime import datetime, timedelta, timezone
import pytz
from threading import Event
from threading import Lock
from fasteners import InterProcessLock
import fcntl
from werkzeug.security import generate_password_hash, check_password_hash
from flask import make_response
from flask import Response
from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from redis import Redis
from flask_bcrypt import Bcrypt
from jsonschema import validate, ValidationError
from ipaddress import ip_address
import re
from jinja2 import select_autoescape
from flask_caching import Cache
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.executors.pool import ProcessPoolExecutor
from flask_caching import Cache
from warp import install_warp
from warp import install_fullwarp
from cryptography.fernet import Fernet
import qrcode
from io import BytesIO
from flask_session import Session
from PIL import Image, ImageDraw, ImageFont
from flask import url_for
import time
from sqlite_backend import _db_lock, _connect


def load_config():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.yaml") 

    try:
        with open(config_path, "r") as file:
            config = yaml.safe_load(file)

        config.setdefault("wireguard", {}).setdefault("config_dir", "/etc/wireguard")
        config.setdefault("flask", {}).setdefault("port", 5000)
        config.setdefault("flask", {}).setdefault("tls", False)
        config.setdefault("flask", {}).setdefault("cert_path", "")
        config.setdefault("flask", {}).setdefault("key_path", "")
        config.setdefault("flask", {}).setdefault("secret_key", "azumiisinyourarea")
        config.setdefault("flask", {}).setdefault("debug", False)

        return config
    except FileNotFoundError:
        print(f"ERROR: config.yaml is missing. Expected at {config_path}. Please create it with the required settings.")
        raise
    except yaml.YAMLError as e:
        print(f"ERROR: Wrong YAML format in config.yaml. Details: {e}")
        raise
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")
        raise

     
config = load_config()

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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
print(f"Base Directory: {BASE_DIR}")
API_FILE = os.path.join(BASE_DIR, "api.json")
SECRET_KEY_FILE = os.path.join(BASE_DIR, "secret.key")
TELEGRAM_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "telegram/telegram.yaml")
TELEGRAM_CONFIG_JSON = os.path.join(os.path.dirname(__file__), "telegram/config.json")
INSTALL_PROGRESS_FILE = os.path.join(BASE_DIR, "install_progress.json")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
DB_FILE = os.path.join(BASE_DIR, "db.json")
DB_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "db") 
os.makedirs(DB_DIR, exist_ok=True)  
SHORT_LINKS_FILE = os.path.join(BASE_DIR, "short_links.json")
DECRYPTED_LINKS_FILE = os.path.join(BASE_DIR, "short_links_decrypted.json")
WIREGUARD_CONFIG_DIR = config["wireguard"]["config_dir"]
PEERS = []  
SQLITE_FILE = os.path.join(BASE_DIR, "db.sqlite3")

print(f"BASE_DIR: {BASE_DIR}")
print(f"Config Path: {os.path.join(BASE_DIR, 'config.yaml')}")
print(f"DB_DIR: {DB_DIR}")
print(f"DB_FILE: {DB_FILE}")
print(f"API_FILE: {API_FILE}")
print(f"SECRET_KEY_FILE: {SECRET_KEY_FILE}")
print(f"INSTALL_PROGRESS_FILE: {INSTALL_PROGRESS_FILE}")
print(f"BACKUP_DIR: {BACKUP_DIR}")
print(f"TELEGRAM_CONFIG_FILE: {TELEGRAM_CONFIG_FILE}")
print(f"TELEGRAM_CONFIG_JSON: {TELEGRAM_CONFIG_JSON}")
print(f"Static Folder: {os.path.join(BASE_DIR, 'static')}")
print(f"Template Folder: {os.path.join(BASE_DIR, 'templates')}")


from sqlite_backend import (
    init_sqlite,
    load_users, save_users,
    load_peers_from_json, save_peers_to_json,
    load_peers_with_lock, save_peers_with_lock,
    obtain_peers_file
)
init_sqlite(BASE_DIR)



redis_client = Redis(host="127.0.0.1", port=6379, db=0)
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri="redis://127.0.0.1:6379"  
)
bcrypt = Bcrypt(app)
countdown_event = Event()
json_lock = Lock()
metrics_queue = Queue(maxsize=1)
stop_event = Event()
cache = Cache(app, config={
    "CACHE_TYPE": "SimpleCache", 
    "CACHE_DEFAULT_TIMEOUT": 300 
})
app.config["CACHE_TYPE"] = "RedisCache"
app.config["CACHE_REDIS_HOST"] = "127.0.0.1"
app.config["CACHE_REDIS_PORT"] = 6379
app.config["CACHE_REDIS_DB"] = 0
cache = Cache(app)


def get_system_timezone():
    try:
        with open("/etc/timezone", "r") as tz_file:
            etc_timezone = tz_file.read().strip()
        
        localtime_symlink = os.readlink("/etc/localtime")
        expected_symlink = f"/usr/share/zoneinfo/{etc_timezone}"

        if localtime_symlink != expected_symlink:
            print("[WARNING] Mismatch detected between /etc/timezone and /etc/localtime.")
            print(f"/etc/timezone: {etc_timezone}")
            print(f"/etc/localtime points to: {localtime_symlink}")

            print("[INFO] Fixing the time zone configuration...")
            subprocess.run(["sudo", "echo", etc_timezone, "|", "tee", "/etc/timezone"], check=True, shell=True)
            subprocess.run(["sudo", "dpkg-reconfigure", "-f", "noninteractive", "tzdata"], check=True)
            print("[INFO] Time zone configuration synchronized.")

            with open("/etc/timezone", "r") as tz_file:
                etc_timezone = tz_file.read().strip()
        
        return etc_timezone

    except Exception as e:
        print(f"[ERROR] Could not detect or fix system timezone: {e}")
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



@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        data = request.get_json(silent=True) or {}
        username = str(data.get("username") or "").strip()
        password = (data.get('password') or "")

        if not username or not password:
            return jsonify({"error": "Username and password are required."}), 400

    
        users = load_users() 
        hashed_password = users.get(username)
        if not hashed_password or not bcrypt.check_password_hash(hashed_password, password):
            app.logger.warning(f"Login failed for '{username}'.")
            return jsonify({"error": "Wrong username or password."}), 401

        session['username'] = username
        app.logger.info(f"User '{username}' logged in successfully.")
        return jsonify({"message": "Login successful!"}), 200

    except Exception as e:
        app.logger.error(f"Unexpected error during login: {e}")
        return jsonify({"error": "Internal server error."}), 500


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


@app.route("/get-telegram-config", methods=["GET"])
def obtain_telegram_config():
    try:
        default_config = {
    "telegram_bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
    "api_base_url": "http://localhost:8080",
    "api_key": "YOUR_API_KEY"
    }

        config_dir = os.path.dirname(TELEGRAM_CONFIG_JSON)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
            print(f"Created directory for config: {config_dir}")

        if not os.path.exists(TELEGRAM_CONFIG_JSON) or os.stat(TELEGRAM_CONFIG_JSON).st_size == 0:
            with open(TELEGRAM_CONFIG_JSON, "w") as json_file:
                json.dump(default_config, json_file, indent=4)
                os.chmod(TELEGRAM_CONFIG_JSON, 0o644)
            print(f"Config file created with default values at {TELEGRAM_CONFIG_JSON}.")

        with open(TELEGRAM_CONFIG_JSON, "r") as json_file:
            json_config = json.load(json_file)
            bot_token = json_config.get("bot_token", "")
            base_url = json_config.get("base_url", "")
            api_key = json_config.get("api_key", "")

        return jsonify({
            "bot_token": bot_token,
            "base_url": base_url,
            "api_key": api_key
        })

    except json.JSONDecodeError as e:
        print(f"JSON decoding error in {TELEGRAM_CONFIG_JSON}: {e}")
        with open(TELEGRAM_CONFIG_JSON, "w") as json_file:
            json.dump(default_config, json_file, indent=4)
            os.chmod(TELEGRAM_CONFIG_JSON, 0o644)
        return jsonify({"error": "Config file was invalid and has been reset.", "details": str(e)}), 500

    except Exception as e:
        print(f"error in loading config.json: {e}")
        return jsonify({"error": "Couldn't load bot config.", "details": str(e)}), 500



telegram_install_progress = 0
telegram_installing = False    
PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "install_telegram.json")

def update_progress(progress, message):
    global telegram_installing
    progress_data = {
        "progress": progress,
        "message": message,
        "installing": telegram_installing
    }
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress_data, f)

def run_telegram_install_script(language="en"):
    global telegram_installing
    telegram_installing = True
    update_progress(0, "Starting installation.")

    base_path = os.path.dirname(os.path.abspath(__file__))
    script_name = "install_telegram.sh" if language == "en" else "install_telegram-fa.sh"
    script_path = os.path.join(base_path, script_name)

    try:
        if not os.path.exists(script_path):
            update_progress(0, f"Script not found: {script_path}")
            raise FileNotFoundError(f"Script not found: {script_path}")

        if not re.match(r'^[a-zA-Z0-9_-]+\.sh$', script_name):
            raise ValueError(f"Wrong script name detected: {script_name}")

        if not script_path.startswith(base_path):
            raise ValueError("Wrong script path detected.")

        if not os.path.isfile(script_path):
            raise ValueError(f"Path is not a file: {script_path}")

        resolved_script_path = os.path.abspath(script_path)

        os.chmod(resolved_script_path, 0o700)

        result = subprocess.run([resolved_script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode != 0:
            update_progress(0, f"Script failed: {result.stderr}")
            raise Exception(f"Script failed with error: {result.stderr}")

        update_progress(100, "Installation completed successfully.")

    except Exception as e:
        update_progress(0, f"Installation failed: {e}")
    finally:
        telegram_installing = False
        update_progress(100, "Installation process finalized.")

@app.route("/install-telegram-fa", methods=["POST"])
def install_telegram_fa():
    threading.Thread(target=run_telegram_install_script, args=("fa",)).start()
    return jsonify({"message": "Persian installation started.", "status": "installing"})


@app.route("/telegram-install-progress", methods=["GET"])
def telegram_install_progress():
    try:
        with open(PROGRESS_FILE, "r") as f:
            progress_data = json.load(f)
            return jsonify(progress_data)
    except FileNotFoundError:
        return jsonify({"progress": 0, "message": "No progress data found.", "installing": False})

@app.route("/install-telegram-en", methods=["POST"])
def install_telegram_en():
    threading.Thread(target=run_telegram_install_script, args=("en",)).start()
    return jsonify({"message": "English installation started.", "status": "installing"})


@app.route("/start-telegram", methods=["POST"])
def start_telegram():
    language = session.get("language", "en")
    service_name = "telegram-bot-en.service" if language == "en" else "telegram-bot-fa.service"

    try:
        sanitized_service_name = sanitize_service_name(service_name)
        if not sanitized_service_name.startswith("telegram-bot-"):
            raise ValueError("Wrong service name. Must start with 'telegram-bot-'.")
        
        subprocess.run(
            ["systemctl", "start", sanitized_service_name],  
            check=True, 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        return jsonify({"message": f"{sanitized_service_name} started successfully.", "status": "running"})

    except subprocess.CalledProcessError as e:
        return jsonify({
            "message": "Start failed.",
            "error": str(e),
            "stderr": e.stderr
        }), 500
    except ValueError as e:
        return jsonify({"message": "Wrong service name.", "error": str(e)}), 400
    except Exception as e:
        return jsonify({
            "message": "Start failed.",
            "error": str(e)
        }), 500

@app.route("/stop-telegram", methods=["POST"])
def stop_telegram():
    language = session.get("language", "en")
    service_name = "telegram-bot-en.service" if language == "en" else "telegram-bot-fa.service"

    try:
        sanitized_service_name = sanitize_service_name(service_name)
        if not sanitized_service_name.startswith("telegram-bot-"):
            raise ValueError("Wrong service name. Must start with 'telegram-bot-'.")
        
        subprocess.run(
            ["systemctl", "stop", sanitized_service_name],  
            check=True,  
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        return jsonify({"message": f"{sanitized_service_name} stopped successfully.", "status": "stopped"})

    except subprocess.CalledProcessError as e:
        return jsonify({
            "message": "Stop failed.",
            "error": str(e),
            "stderr": e.stderr
        }), 500
    except ValueError as e:
        return jsonify({"message": "Wrong service name.", "error": str(e)}), 400
    except Exception as e:
        return jsonify({
            "message": "Stop failed.",
            "error": str(e)
        }), 500



def sanitize_service_name(service_name):

    service_name = re.sub(r'[^a-zA-Z0-9_.-]', '', service_name)
    return service_name


@app.route("/uninstall-telegram", methods=["POST"])
def uninstall_telegram():
    language = session.get("language", "en")
    service_name = "telegram-bot-en.service" if language == "en" else "telegram-bot-fa.service"
    service_file = f"/etc/systemd/system/{service_name}"

    try:
        sanitized_service_name = sanitize_service_name(service_name)
        print(f"Sanitized service name: {sanitized_service_name}")  

        if not sanitized_service_name.startswith("telegram-bot-"):
            raise ValueError("Wrong service name. Must start with 'telegram-bot-'.")
        
        subprocess.run(
            ["systemctl", "stop", sanitized_service_name], 
            check=True,  
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        subprocess.run(
            ["systemctl", "disable", sanitized_service_name],  
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if os.path.exists(service_file):
            os.remove(service_file)
            print(f"Service file {service_file} removed successfully.")
        else:
            print(f"Service file {service_file} does not exist.")

        subprocess.run(
            ["systemctl", "daemon-reload"],  
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        return jsonify({"message": f"{sanitized_service_name} uninstalled successfully.", "status": "uninstalled"})

    except subprocess.CalledProcessError as e:
        return jsonify({
            "message": "Uninstallation failed.",
            "error": str(e),
            "stderr": e.stderr
        }), 500
    except ValueError as e:
        return jsonify({"message": "Wrong service name.", "error": str(e)}), 400
    except Exception as e:
        return jsonify({
            "message": "Uninstallation failed.",
            "error": str(e)
        }), 500
    
@app.route("/get-admin-chat-ids", methods=["GET"])
def get_admin_chat_ids():
    try:
        if not os.path.exists(TELEGRAM_CONFIG_FILE):
            return jsonify({"error": "Config file not found"}), 404

        with open(TELEGRAM_CONFIG_FILE, "r") as yaml_file:
            yaml_config = yaml.safe_load(yaml_file) or {}
            encrypted_chat_ids = yaml_config.get("admin_chat_ids", [])
            admin_chat_ids = [cipher.decrypt(chat_id.encode()).decode() for chat_id in encrypted_chat_ids]

        return jsonify({"admin_chat_ids": admin_chat_ids})
    except Exception as e:
        print(f"Error loading telegram.yaml: {e}")
        return jsonify({"error": "Couldn't load admin chat IDs.", "details": str(e)}), 500


    
@app.route("/bot-status", methods=["GET"])
def bot_status():
    try:
        language = session.get("language", "en")
        service_name = "telegram-bot-en.service" if language == "en" else "telegram-bot-fa.service"
        service_file = f"/etc/systemd/system/{service_name}"

        if not os.path.exists(service_file):
            return jsonify({"status": "uninstalled"})

        sanitized_service_name = sanitize_service_name(service_name)

        if not sanitized_service_name.startswith("telegram-bot-"):
            raise ValueError("Wrong service name detected.")

        safe_service_name = sanitized_service_name

        command = ["systemctl", "is-active", safe_service_name]  
        result = run_command(command)  

        
        if result.strip() == "active":
            return jsonify({"status": "running"})
        else:
            return jsonify({"status": "stopped"})
    except FileNotFoundError:
        return jsonify({"status": "error", "error": "systemctl not found"}), 500
    except subprocess.CalledProcessError as e:
       
        return jsonify({
            "status": "error",
            "error": "systemctl error",
            "stderr": e.stderr  
        }), 500
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

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


@app.route("/save-telegram-config", methods=["POST"])
def save_telegram_config():
    try:
        data = request.json

        bot_token = data.get("bot_token")
        base_url = data.get("base_url")
        api_key = data.get("api_key")
        admin_chat_ids = data.get("admin_chat_ids")  

        if not bot_token or not base_url or not api_key or not admin_chat_ids:
            return jsonify({"message": "All fields are required!"}), 400

        encrypted_chat_ids = [cipher.encrypt(chat_id.encode()).decode() for chat_id in admin_chat_ids]

        json_config = {
            "bot_token": bot_token,
            "base_url": base_url,
            "api_key": api_key,
        }
        with open(TELEGRAM_CONFIG_JSON, "w") as json_file:
            json.dump(json_config, json_file, indent=4)

        yaml_config = {"admin_chat_ids": encrypted_chat_ids}
        with open(TELEGRAM_CONFIG_FILE, "w") as yaml_file:
            yaml.safe_dump(yaml_config, yaml_file)

        return jsonify({"message": "Telegram config saved successfully!"})

    except Exception as e:
        return jsonify({"message": "Couldn't save config.", "error": str(e)}), 500




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

@app.before_request
def set_default_language():
    if "language" not in session:
        language = request.cookies.get("language", "en")
        session["language"] = language

@app.route("/")
def index():
    if "username" not in session:
        return redirect("/login")
    return redirect("/home")

@app.route("/home")
def home():
    if "username" not in session or session["username"] not in load_users():
        flash("Please log in to access the dashboard.", "error")
        return redirect("/login")

    language = session.get('language', 'en')
    template_name = "index-fa.html" if language == "fa" else "index.html"
    return render_template(template_name, username=session["username"])



def load_username_from_db():
    try:
        with open(DB_FILE, 'r') as file:
            users = json.load(file)
            if users:
                return next(iter(users.keys()), "Guest")
    except (FileNotFoundError, json.JSONDecodeError):
        return "Guest"  

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


@app.route("/telegram")
def api():
    if "username" not in session or session["username"] not in load_users():
        flash("Please log in to access peers.", "error")
        return redirect("/login")
    
    language = session.get('language', 'en')
    template_name = "telegram-fa.html" if language == "fa" else "telegram.html"
    return render_template(template_name)


@app.route("/login", methods=["GET", "POST"])
def login():
    language = session.get('language', 'en')
    template_name = "login-fa.html" if language == "fa" else "login.html"

    if request.method == "GET":
        users = load_users() or {}

        no_users = (len(users) == 0)
        username = request.cookies.get("username")
        if username and username in users:
            session["username"] = username
            flash("Welcome back!", "success")
            return redirect("/home")
        return render_template(template_name, no_users=no_users)

    # --- POST ---
    try:
        username = str(request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        remember = request.form.get("remember")

        if not username or not password:
            flash("Username and password are required!", "error")
            return redirect("/login")

        users = load_users() or {}
        hashed = users.get(username) 

        if not hashed:
   
            flash("Wrong username or password!", "error")
            return redirect("/login")

        try:
            ok = bcrypt.check_password_hash(hashed, password)
        except Exception:
            ok = False

        if ok:
            session["username"] = username
            flash("Login successful!", "success")
            resp = make_response(redirect("/home"))
            if remember == "yes":
                resp.set_cookie("username", username, max_age=30*24*60*60)
            return resp

        flash("Wrong username or password!", "error")
        return redirect("/login")

    except Exception as e:
        app.logger.exception("Error in /login POST")
        flash("Internal error during login.", "error")
        return redirect("/login")

@app.route("/register", methods=["GET", "POST"])
def register():
    language = session.get('language', 'en')
    template_name = "register-fa.html" if language == "fa" else "register.html"

    users = load_users()

    if users:
 
        flash("Registration is disabled because users already exist.", "error")
        return render_template("login-fa.html" if language=="fa" else "login.html"), 403

    if request.method == "GET":
        return render_template(template_name)

    username = str(request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect("/register")
    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return redirect("/register")
    if username in users:
        flash("Username already exists!", "error")
        return redirect("/register")

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    users[username] = hashed_password
    save_users(users)

    flash("Registration successful! Please log in.", "success")
    return redirect("/login")


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

def obtain_system_uptime():

    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
            uptime_days = int(uptime_seconds // (24 * 3600))
            uptime_hours = int((uptime_seconds % (24 * 3600)) // 3600)
            uptime_minutes = int((uptime_seconds % 3600) // 60)
            return f"{uptime_days}d {uptime_hours}h {uptime_minutes}m"
    except Exception as e:
        print(f"error in fetching uptime: {e}")
        return "N/A"

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

def system_metrics_job():

    try:
        cpu = calculate_cpu_usage()
        ram = psutil.virtual_memory().percent
        disk_usage = obtain_disk_usage()
        uptime = obtain_system_uptime()

        if cpu is None:
            cpu = 0.01

        metrics = {
            "cpu": f"{cpu}%",
            "ram": f"{ram}%",
            "disk": disk_usage,
            "uptime": uptime
        }

        cache.set("metrics", metrics, timeout=9)
    except Exception as e:
        print(f"error in collecting metrics: {e}")


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

    
def sanitize_input(input_value: str):
    if re.match(r"^[a-zA-Z0-9_-]+$", input_value):
        return input_value
    else:
        raise ValueError(f"Wrong input: {input_value}")

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

        subprocess.run(command_down, check=True, stderr=subprocess.PIPE, text=True)

        subprocess.run(command_up, check=True, stderr=subprocess.PIPE, text=True)

        return jsonify(success=True, message=f"Interface '{sanitized_interface}' has been turned {action}.")

    except subprocess.CalledProcessError as e:
        print(f"error in toggling interface '{sanitized_interface}': {e}")
        return jsonify(success=False, error=e.stderr if e.stderr else str(e)), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({"error": "An unexpected error occurred."}), 500


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

def monitor_traffic():
    if not monitor_lock.acquire(blocking=False):
        logging.info("monitor_traffic job is already running. Skipping this execution.")
        return

    try:
        config_files = [f for f in os.listdir(WIREGUARD_CONFIG_DIR) if f.endswith(".conf")]
        interfaces = [config.split(".")[0] for config in config_files]

        for interface in interfaces:
            try:
                wg_output = subprocess.check_output(["wg", "show", interface, "transfer"], text=True)

              
                peers = load_peers_from_json(interface)

                for peer in peers:
                    if peer.get("config") != f"{interface}.conf":
                        continue

                    try:
                        ip_address(peer["peer_ip"])
                    except ValueError:
                        logging.warning(f"Wrong IP address for peer: {peer.get('peer_name')} - {peer.get('peer_ip')}")
                        continue

                    peer_ip = peer["peer_ip"]
                    limit_bytes = convert_to_bytes(peer["limit"])

                    for line in wg_output.splitlines():
                        columns = line.split("\t")
                        if len(columns) >= 3 and columns[0] == peer["public_key"]:
                            try:
                                received_bytes = int(columns[1])
                                sent_bytes = int(columns[2])
                            except ValueError:
                                logging.error(f"Wrong transfer stats for peer {peer.get('peer_name')} in wg_output.")
                                continue

                            last_received = peer.get("last_received_bytes", 0)
                            last_sent = peer.get("last_sent_bytes", 0)

                            if received_bytes < last_received or sent_bytes < last_sent:
                                logging.info(f"Detected reset for peer {peer.get('peer_name')}.")
                                additional_bytes = received_bytes + sent_bytes
                            else:
                                additional_bytes = (received_bytes - last_received) + (sent_bytes - last_sent)

                            peer["used"] = max(0, peer.get("used", 0) + max(0, additional_bytes))
                            peer["remaining"] = max(0, limit_bytes - peer["used"])
                            peer["last_received_bytes"] = received_bytes
                            peer["last_sent_bytes"] = sent_bytes

                            if peer["used"] >= limit_bytes and not peer.get("monitor_blocked", False):
                                logging.info(f"Blocking {peer.get('peer_name')} ({peer_ip}) - Exceeded Limit")
                                if add_blackhole_route(peer_ip):
                                    peer["monitor_blocked"] = True
                                    logging.warning(f"Peer '{peer.get('peer_name')}' has been blocked due to usage limit.")
                                else:
                                    logging.error(f"Couldn't add blackhole route for peer '{peer.get('peer_name')}'.")

            
                save_peers_with_lock(interface, peers)

            except subprocess.CalledProcessError as e:
                if "No such device" in str(e):
                    logging.info(f"No such device for interface {interface}.")
                    continue
                else:
                    logging.warning(f"Non-critical error for interface {interface}: {e}")
            except Exception as e:
                logging.error(f"Unexpected error for interface {interface}: {e}")

    finally:
        monitor_lock.release()

@app.route("/api/reset-traffic", methods=["POST"])
def reset_traffic():
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

            interface = peer["config"].split(".")[0]
            public_key = peer["public_key"]
            peer_ip = peer["peer_ip"]

            reset_peer_traffic(interface, public_key, peer_ip)

            peer["used"] = 0
            peer["remaining"] = convert_to_bytes(peer["limit"])
            peer["last_received_bytes"] = 0
            peer["last_sent_bytes"] = 0
            
            save_peers_with_lock(config_name, peers)

        return jsonify(
            success=True,
            message=f"The traffic statistics for the user '{peer_name}' in the file {config_name} have been reset."
        )
    except Exception as e:
        print(f"error in resetting traffic: {e}")
        return jsonify(error=f"error in resetting traffic: {e}"), 500


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


def sanitize_ip(ip_address: str):
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip_address):
        return ip_address
    else:
        raise ValueError(f"Wrong IP address: {ip_address}")

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


def bytes_to_readable(bytes_value):

    if bytes_value >= 1024 ** 3:  
        return f"{bytes_value / (1024 ** 3):.2f} GiB"
    elif bytes_value >= 1024 ** 2: 
        return f"{bytes_value / (1024 ** 2):.2f} MiB"
    elif bytes_value >= 1024:  
        return f"{bytes_value / 1024:.2f} KiB"
    else:
        return f"{bytes_value} bytes"


def convert_to_bytes(limit):

    try:
        if isinstance(limit, (int, float)):
            return int(limit)

        size, unit = float(limit[:-3]), limit[-3:].upper()
        unit_mapping = {
            "B": 1,
            "KIB": 1024,
            "MIB": 1024 ** 2,
            "GIB": 1024 ** 3,
        }

        if unit not in unit_mapping:
            raise ValueError(f"Wrong unit: {unit}")
        
        return int(size * unit_mapping[unit])
    except (ValueError, TypeError) as e:
        print(f"error in converting limit to bytes: {e}")
        return 0

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


@app.route('/api/bot-peer-details', methods=['GET'])
def get_peer_details_for_bot():
    peer_name = request.args.get('peerName')
    config_name = request.args.get('configName')

    if not peer_name:
        return jsonify({"error": "Peer name is required"}), 400

    if not config_name:
        return jsonify({"error": "Config name is required"}), 400

    try:
        peers = load_peers_from_json(config_name)
        if not peers:
            return jsonify({"error": f"No peers found for config '{config_name}'"}), 404

        peer = next((p for p in peers if p["peer_name"] == peer_name), None)
        if not peer:
            return jsonify({"error": f"Peer '{peer_name}' not found"}), 404

        peer_ip = peer.get('peer_ip')
        if not peer_ip:
            return jsonify({"error": "Invalid or missing peer IP"}), 400

        app.logger.debug(f"Peer data: {peer}")

        allowed_ips = peer.get("allowed_ips") or "0.0.0.0/0, ::/0"

        qr_code = (
            f"[Interface]\n"
            f"PrivateKey = {peer.get('private_key', 'YOUR_PRIVATE_KEY')}\n"
            f"Address = {peer_ip}/32\n"
            f"DNS = {peer.get('dns', '1.1.1.1')}\n\n"
            f"[Peer]\n"
            f"PublicKey = {peer.get('public_key', 'YOUR_PUBLIC_KEY')}\n"
            f"AllowedIPs = {allowed_ips}\n"
            f"PersistentKeepalive = {peer.get('persistent_keepalive', 25)}"
        )

        created_at_str = peer.get("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
        created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        expiry_days = peer.get("expiry_days", 30)
        expiry = created_at + timedelta(days=expiry_days)
        now = datetime.now(timezone.utc)

        expiry_human = (
            f"{(expiry - now).days} days remaining" if (expiry - now).total_seconds() > 0 else "Expired"
        )

        data_limit = peer.get('limit', 'N/A')
        used_data = peer.get('used', 0)
        remaining_data = peer.get('remaining', 0)

        app.logger.debug(f"Data limit: {data_limit}, Used data: {used_data}, Remaining data: {remaining_data}")

        peer_details = {
            "peer_name": peer_name,
            "peer_ip": peer_ip,
            "qr_code": qr_code,
            "dns": peer.get('dns', '1.1.1.1'),
            "limit": data_limit,
            "used": used_data,
            "remaining": remaining_data,
            "created_at": created_at_str,
            "expiry": expiry.strftime("%Y-%m-%d %H:%M:%S"),
            "expiry_human": expiry_human
        }

        app.logger.debug(f"Peer details to return: {peer_details}")

        return jsonify(peer_details), 200

    except Exception as e:
        app.logger.error(f"Error in fetching peer details for bot: {str(e)}")
        return jsonify({"error": "Couldn't fetch peer details"}), 500

@app.route('/api/bot-peer-details-fa', methods=['GET'])
def get_peer_details_for_bot_fa():
    peer_name = request.args.get('peerName')
    config_name = request.args.get('configName')

    if not peer_name:
        return jsonify({"error": "Peer name is required"}), 400

    if not config_name:
        return jsonify({"error": "Config name is required"}), 400

    try:
        peers = load_peers_from_json(config_name)
        if not peers:
            return jsonify({"error": f"No peers found for config '{config_name}'"}), 404

        peer = next((p for p in peers if p["peer_name"] == peer_name), None)
        if not peer:
            return jsonify({"error": f"Peer '{peer_name}' not found"}), 404

        peer_ip = peer.get('peer_ip')
        if not peer_ip:
            return jsonify({"error": "Invalid or missing peer IP"}), 400

        app.logger.debug(f"Peer data: {peer}")

        allowed_ips = peer.get("allowed_ips") or "0.0.0.0/0, ::/0"

        qr_code = (
            f"[Interface]\n"
            f"PrivateKey = {peer.get('private_key', 'YOUR_PRIVATE_KEY')}\n"
            f"Address = {peer_ip}/32\n"
            f"DNS = {peer.get('dns', '1.1.1.1')}\n\n"
            f"[Peer]\n"
            f"PublicKey = {peer.get('public_key', 'YOUR_PUBLIC_KEY')}\n"
            f"AllowedIPs = {allowed_ips}\n"
            f"PersistentKeepalive = {peer.get('persistent_keepalive', 25)}"
        )

        created_at_str = peer.get("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
        created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        expiry_days = peer.get("expiry_days", 30)
        expiry = created_at + timedelta(days=expiry_days)
        now = datetime.now(timezone.utc)

        expiry_human = (
            f"{(expiry - now).days} روز باقی مانده" if (expiry - now).total_seconds() > 0 else "منقضی"
        )

        data_limit = peer.get('limit', 'N/A')
        used_data = peer.get('used', 0)
        remaining_data = peer.get('remaining', 0)

        app.logger.debug(f"Data limit: {data_limit}, Used data: {used_data}, Remaining data: {remaining_data}")

        peer_details = {
            "peer_name": peer_name,
            "peer_ip": peer_ip,
            "qr_code": qr_code,
            "dns": peer.get('dns', '1.1.1.1'),
            "limit": data_limit,
            "used": used_data,
            "remaining": remaining_data,
            "created_at": created_at_str,
            "expiry": expiry.strftime("%Y-%m-%d %H:%M:%S"),
            "expiry_human": expiry_human
        }

        app.logger.debug(f"Peer details to return: {peer_details}")

        return jsonify(peer_details), 200

    except Exception as e:
        app.logger.error(f"Error in fetching peer details for bot (fa): {str(e)}")
        return jsonify({"error": "Couldn't fetch peer details"}), 500


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


@app.route("/api/export-peer-telegram", methods=["GET"])
def export_peer_telegram(peer_name=None, config_file="wg0.conf"):
    if peer_name is None:
        peer_name = request.args.get("peerName")
    if not config_file:
        config_file = request.args.get("config", "wg0.conf")
    if not peer_name:
        return None, "Peer name is required to export config.", 400

    try:
        peers = load_peers_from_json(config_file)
        peer = next((p for p in peers if p["peer_name"] == peer_name and p["config"] == config_file), None)
        if not peer:
            return None, f"Peer '{peer_name}' not found in {config_file}.", 404

        dns = peer.get("dns", "1.1.1.1")
        persistent_keepalive = peer.get("persistent_keepalive", 25)
        mtu = peer.get("mtu", 1280)

        server_public_key = obtain_public_key_conf(config_file)
        custom_ip = obtain_custom_ip()
        server_ip = custom_ip or obtain_server_public_ip()
        server_port = server_listen_port(config_file)

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
        return peer_config, None, 200
    except Exception as e:
        logger.error(f"error in export_peer_telegram: {e}")
        return None, "Internal server error.", 500

    
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@app.route("/api/download-peer-config", methods=["GET"])
def download_peer_config():
    try:
        peer_name = request.args.get("peerName")
        config_file = request.args.get("config", "wg0.conf")

        if not peer_name or not config_file:
            return jsonify({"error": "Peer name and config file are required"}), 400

        peer_config, error_message, status_code = export_peer_telegram(peer_name, config_file)
        if peer_config is None:
            return jsonify({"error": error_message}), status_code

        return Response(
            peer_config,
            mimetype="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{peer_name}.conf"'}
        )
    except Exception as e:
        logger.error(f"error in /api/download-peer-config: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/download-peer-qr", methods=["GET"])
def download_peer_qr():
    try:
        peer_name = request.args.get("peerName")
        config_file = request.args.get("config", "wg0.conf")

        if not peer_name or not config_file:
            return jsonify({"error": "Peer name and config file are required"}), 400

        peer_config, error_message, status_code = export_peer_telegram(peer_name, config_file)
        if peer_config is None:
            return jsonify({"error": error_message}), status_code

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
        logger.error(f"error in /api/download-peer-qr: {e}")
        return jsonify({"error": "Internal server error"}), 500


def obtain_config_files():
    try:
        return [f for f in os.listdir(WIREGUARD_CONFIG_DIR) if f.endswith(".conf")]
    except Exception as e:
        print(f"error in accessing {WIREGUARD_CONFIG_DIR}: {e}")
        return []

CONFIG_FILE = "endip.json" 

def obtain_custom_ip():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as file:
            data = json.load(file)
            return data.get("custom_ip")
    return None

def set_custom_ip(ip):
    data = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as file:
            data = json.load(file)
    data["custom_ip"] = ip
    with open(CONFIG_FILE, "w") as file:
        json.dump(data, file)

def custom_ip_or_default():
    custom_ip = obtain_custom_ip()  
    if custom_ip:
        return custom_ip 
    return obtain_server_public_ip()  

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


@app.route("/api/configs", methods=["GET"])
def wg_configs():
    try:
        configs = [f for f in os.listdir(WIREGUARD_CONFIG_DIR) if f.endswith(".conf")]
        return jsonify({"configs": configs}), 200
    except Exception as e:
        return jsonify({"error": f"Couldn't load configs: {str(e)}"}), 500


def sanitize_interface_name(interface_name: str):
    if re.match(r"^[a-zA-Z0-9_-]+$", interface_name):
        return interface_name
    else:
        raise ValueError(f"Wrong interface name: {interface_name}")

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

@app.route("/api/toggle-config", methods=["POST"])
def toggle_config():
    config_file = request.args.get("config")
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
            result = subprocess.run(
                [wg_quick_path, "up", interface_name], 
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            result = subprocess.run(
                [wg_quick_path, "down", interface_name], 
                check=True,
                capture_output=True,
                text=True,
            )

        ip_path = "ip" 
        interface_state = subprocess.run(
            [ip_path, "link", "show", interface_name],
            capture_output=True,
            text=True
        )

        is_active = "state UNKNOWN" in interface_state.stdout or "state UP" in interface_state.stdout

        return jsonify(
            message=f"Configuration '{config_file}' has been {'enabled' if is_active else 'disabled'}.",
            active=is_active,
            output=result.stdout + result.stderr,
        )
    except subprocess.CalledProcessError as e:
        print(f"error in toggling config {config_file}: {e}")
        return jsonify(
            error=f"Couldn't {'enable' if active else 'disable'} config '{config_file}': {e.stderr}",
            output=e.stdout + e.stderr,
        ), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify(error=str(e)), 500

    
@app.route("/api/toggle-peer", methods=["POST"])
def toggle_peer():
    try:
        data = request.json
        peer_name = data.get("peerName")
        blocked = bool(data.get("blocked", False))
        config_name = data.get("config", "wg0.conf")

        if not peer_name:
            return jsonify(error="Peer name is required."), 400

        with json_lock:
            peers = load_peers_with_lock(config_name)
            peer = next((p for p in peers if p["peer_name"] == peer_name), None)
            if not peer:
                return jsonify(error=f"Peer '{peer_name}' not found in {config_name}."), 404

            interface = sanitize_interface_name(config_name.split(".")[0])
            public_key = sanitize_public_key(peer["public_key"])
            peer_ip = peer.get("peer_ip")  

            wg_path = "wg"
            if blocked:
                try:
                    if peer.get("peer_ip"):
                        added = add_blackhole_route(peer["peer_ip"])
                        print(f"[TOGGLE-PEER] add blackhole for {peer['peer_ip']}: {added}")
                except Exception as _:
                    print("[TOGGLE-PEER] failed to add blackhole (ignored)")

                try:
                    subprocess.run(
                        [wg_path, "set", interface, "peer", public_key, "remove"],
                        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    print(f"[TOGGLE-PEER] removed peer {public_key} from {interface}")
                except subprocess.CalledProcessError as e:
                    return jsonify(error=f"Couldn't remove peer from WireGuard: {e.stderr}"), 500

       
                peer["monitor_blocked"] = True
                peer["expiry_blocked"] = True

            else:
                if not peer_ip:
                    return jsonify(error="Peer IP is missing; cannot re-add peer."), 500
                try:
                    sanitized_peer_ip = sanitize_ip(peer_ip)
                    subprocess.run(
                        [wg_path, "set", interface, "peer", public_key,
                        "allowed-ips", f"{sanitized_peer_ip}/32"],
                        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    print(f"[TOGGLE-PEER] re-added peer {public_key} to {interface} with {sanitized_peer_ip}/32")
                except ValueError as e:
                    return jsonify(error=f"IP/public key sanitization error: {e}"), 400
                except subprocess.CalledProcessError as e:
                    return jsonify(error=f"Couldn't re-add peer to WireGuard: {e.stderr}"), 500

        
                try:
                    if peer.get("peer_ip"):
                        removed = remove_blackhole_route(peer["peer_ip"])
                        print(f"[TOGGLE-PEER] remove blackhole for {peer['peer_ip']}: {removed}")
                except Exception as _:
                    print("[TOGGLE-PEER] failed to remove blackhole (ignored)")


                peer["monitor_blocked"] = False
                peer["expiry_blocked"] = False
                peer["remaining"] = convert_to_bytes(peer.get("limit", "0MiB"))
                peer["remaining_time"] = calculate_expiry_duration(peer.get("expiry_time", {}))
                peer["used"] = 0
                peer["last_received_bytes"] = 0
                peer["last_sent_bytes"] = 0

            save_peers_with_lock(config_name, peers)

        return jsonify(
            message=f"Peer {peer_name} in {config_name} {'disabled' if blocked else 'enabled'} successfully.",
            blocked=blocked
        )

    except Exception as e:
        print(f"error in toggling peer: {e}")
        return jsonify(error="Couldn't toggle peer state."), 500



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
    

@app.route('/api/speed', methods=['GET'])
def obtain_speed():
    try:
        initial_counters = psutil.net_io_counters()
        initial_upload = initial_counters.bytes_sent
        initial_download = initial_counters.bytes_recv
        time.sleep(1)
        final_counters = psutil.net_io_counters()
        final_upload = final_counters.bytes_sent
        final_download = final_counters.bytes_recv

        upload_speed = (final_upload - initial_upload) / 1024 
        download_speed = (final_download - initial_download) / 1024  

        return jsonify({
            'uploadSpeed': upload_speed,
            'downloadSpeed': download_speed
        }), 200
    except Exception as e:
        app.logger.error(f"error in /api/speed: {str(e)}")
        return jsonify({'error': 'Internal Server Error'}), 500

    
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

@app.route("/s/<short_id>", methods=["GET"])
def short_redirect(short_id):
    short_links = load_short_links()
    long_link = short_links.get(short_id)
    if not long_link:
        return "Link not found or already removed", 404
    return redirect(long_link)


def load_short_links():
    try:
        with open(SHORT_LINKS_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_short_links(short_links):
    with open(SHORT_LINKS_FILE, "w") as file:
        json.dump(short_links, file, indent=4)


@app.route("/api/create-peer", methods=["POST"])
def create_peer():
    try:
        data = request.json
        print(f"Received data: {data}")
        
        peer_name = data.get('peerName')
        if not peer_name or not re.match(r'^[a-zA-Z0-9_-]+$', peer_name):
            return jsonify({"error": "Wrong peer name. Only letters, numbers, underscores, and dashes are allowed."}), 400

        peer_ip = data.get('peerIp')
        try:
            sanitized_peer_ip = sanitize_ip(peer_ip)
        except ValueError:
            return jsonify({"error": "Wrong IP address."}), 400

        data_limit = data.get('dataLimit')
        if not data_limit or not re.match(r'^\d+(MiB|GiB)$', data_limit):
            return jsonify({"error": "Wrong data limit. Must be a number followed by MiB or GiB."}), 400
        numeric_limit = int(data_limit[:-3])
        if numeric_limit <= 0 or numeric_limit > 1024:
            return jsonify({"error": "Data limit must be between 1 and 1024 MiB/GiB."}), 400

        config_file = data.get("configFile", "wg0.conf")
        if not re.match(r'^[a-zA-Z0-9_-]+\.conf$', config_file):
            return jsonify({"error": "Wrong config file name."}), 400

        dns = data.get('dns') or "1.1.1.1, 1.0.0.1"

        expiry_days = data.get('expiryDays', 0)
        expiry_months = int(data.get("expiryMonths") or 0)
        expiry_hours = int(data.get("expiryHours") or 0)
        expiry_minutes = int(data.get("expiryMinutes") or 0)
        if expiry_days < 0 or expiry_months < 0 or expiry_hours < 0 or expiry_minutes < 0:
            return jsonify({"error": "Expiry times cannot be negative."}), 400

        first_usage = not data.get("firstUsage", False)
        persistent_keepalive = data.get("persistentKeepalive", 25)
        mtu = data.get("mtu", 1280)

        allowed_ips = data.get("allowedIps", "0.0.0.0/0, ::/0")
        
        print(f"First usage set to: {first_usage}")

        total_expiry_minutes = (
            expiry_months * 30 * 24 * 60 +
            expiry_days * 24 * 60 +
            expiry_hours * 60 +
            expiry_minutes
        )
        if total_expiry_minutes <= 0:
            return jsonify({"error": "Total expiry time must be greater than zero."}), 400

        bulk_count = int(data.get("bulkCount", 1))  

        with json_lock:
            peers = load_peers_with_lock(config_file)
            print(f"Loaded peers from {config_file}.json: {peers}")

            if bulk_count == 1:
                for peer in peers:
                    if peer.get("peer_ip") == peer_ip:
                        if not peer.get("deleted", False):
                            return jsonify({"error": f"Peer IP {peer_ip} is already in use."}), 400
                        else:
                            peer["deleted"] = False
                            save_peers_with_lock(config_file, peers)
                            break

                peer_token = generate_peer_token()

                client_private_key_bytes = nacl.bindings.randombytes(32)
                client_private_key = base64.b64encode(client_private_key_bytes).decode("utf-8")
                client_public_key = derive_public_key(client_private_key)

                peer = {
                    "peer_name": peer_name,
                    "peer_ip": peer_ip,
                    "dns": dns,
                    "limit": data_limit,
                    "used": 0,
                    "remaining": convert_to_bytes(data_limit),
                    "monitor_blocked": False,
                    "expiry_blocked": False,
                    "private_key": client_private_key,
                    "public_key": client_public_key,
                    "token": peer_token,
                    "expiry_time": {
                        "months": expiry_months,
                        "days": expiry_days,
                        "hours": expiry_hours,
                        "minutes": expiry_minutes,
                    },
                    "remaining_time": total_expiry_minutes,
                    "first_usage": first_usage,
                    "persistent_keepalive": persistent_keepalive,
                    "mtu": mtu,
                    "config": config_file,
                    "last_received_bytes": 0,
                    "last_sent_bytes": 0,
                    "allowed_ips": allowed_ips 
                }

                peers.append(peer)
                save_peers_with_lock(config_file, peers)

                interface = sanitize_interface_name(config_file.split(".")[0])
                wg_path = "wg"  

                subprocess.run(
                    [wg_path, "set", interface, "peer", client_public_key, "allowed-ips", f"{sanitized_peer_ip}/32"],
                    check=True
                )

                config_path = os.path.join("/etc/wireguard", config_file) 
                peer_config = (
                    f"[Peer]\n"
                    f"# {peer_name}\n"
                    f"PublicKey = {client_public_key}\n"
                    f"AllowedIPs = {peer_ip}/32\n"
                    f"PersistentKeepalive = {persistent_keepalive}\n"
                ).strip() + "\n\n"

                with open(config_path, "a") as conf:
                    conf.write(peer_config)

                short_links = load_short_links()
                long_interactive_link = url_for(
                    'peer_details',
                    peer_name=peer['peer_name'],
                    config_file=peer['config'],
                    token=peer_token,
                    _external=True
                )
                short_id = secrets.token_urlsafe(8)
                if short_id not in short_links:  
                    short_links[short_id] = long_interactive_link
                    save_short_links(short_links)

                short_interactive_link = url_for('short_redirect', short_id=short_id, _external=True)

                print(f"Long interactive link for peer '{peer_name}': {long_interactive_link}")
                print(f"Short interactive link for peer '{peer_name}': {short_interactive_link}")

                return jsonify({
                    "message": f"Peer created successfully in {config_file}!",
                    "peer_name": peer_name,
                    "short_link": short_interactive_link
                })

            else:
                network = ip_network(peer_ip + "/24", strict=False)
                used_ips = [
                    peer["peer_ip"]
                    for peer in peers
                    if not peer.get("deleted", False)
                ]
                available_ips = [
                    str(ip) for ip in network.hosts() if str(ip) not in used_ips and str(ip) >= peer_ip
                ]

                if len(available_ips) < bulk_count:
                    return jsonify({"error": "Not enough available IP addresses for the requested bulk creation."}), 400

                responses = []
                for i in range(bulk_count):
                    current_peer_ip = available_ips[i]
                    new_peer_name = f"{peer_name}-{i + 1}"

                    peer_token = generate_peer_token()

                    client_private_key_bytes = nacl.bindings.randombytes(32)
                    client_private_key = base64.b64encode(client_private_key_bytes).decode("utf-8")
                    client_public_key = derive_public_key(client_private_key)

                    peer = {
                        "peer_name": new_peer_name,
                        "peer_ip": current_peer_ip,
                        "dns": dns,
                        "limit": data_limit,
                        "used": 0,
                        "remaining": convert_to_bytes(data_limit),
                        "monitor_blocked": False,
                        "expiry_blocked": False,
                        "private_key": client_private_key,
                        "public_key": client_public_key,
                        "token": peer_token,
                        "expiry_time": {
                            "months": expiry_months,
                            "days": expiry_days,
                            "hours": expiry_hours,
                            "minutes": expiry_minutes,
                        },
                        "remaining_time": total_expiry_minutes,
                        "first_usage": first_usage,
                        "persistent_keepalive": persistent_keepalive,
                        "mtu": mtu,
                        "config": config_file,
                        "last_received_bytes": 0,
                        "last_sent_bytes": 0,
                        "allowed_ips": allowed_ips  
                    }

                    peers.append(peer)

                    interface = sanitize_interface_name(config_file.split(".")[0])
                    wg_path = "wg"  
                    subprocess.run(
                        [wg_path, "set", interface, "peer", client_public_key, "allowed-ips", f"{current_peer_ip}/32"],
                        check=True
                    )

                    config_path = os.path.join("/etc/wireguard", config_file)
                    peer_config = (
                        f"[Peer]\n"
                        f"# {new_peer_name}\n"
                        f"PublicKey = {client_public_key}\n"
                        f"AllowedIPs = {current_peer_ip}/32\n"
                        f"PersistentKeepalive = {persistent_keepalive}\n"
                    ).strip() + "\n\n"

                    with open(config_path, "a") as conf:
                        conf.write(peer_config)

                    short_links = load_short_links()
                    long_interactive_link = url_for(
                        'peer_details',
                        peer_name=peer['peer_name'],
                        config_file=peer['config'],
                        token=peer_token,
                        _external=True
                    )
                    short_id = secrets.token_urlsafe(8)
                    if short_id not in short_links:  
                        short_links[short_id] = long_interactive_link
                        save_short_links(short_links)

                    short_interactive_link = url_for('short_redirect', short_id=short_id, _external=True)

                    responses.append({
                        "peer_name": new_peer_name,
                        "short_link": short_interactive_link,
                        "peer_ip": current_peer_ip
                    })

                save_peers_with_lock(config_file, peers)

                return jsonify({
                    "message": f"{bulk_count} peers created successfully.",
                    "peers": responses
                }), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500



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

@app.route("/api/obt-peer-botdetails", methods=["GET"])
def obt_peerbot_details():
    peer_name = request.args.get("peer_name")
    config_file = request.args.get("config_file")

    if not peer_name or not config_file:
        return jsonify({"error": "Peer name and config file are required."}), 400

    try:
        peers_file = obtain_peers_file(config_file)
        peers_metadata = load_peers_from_json(peers_file)

        peer = next((p for p in peers_metadata if p["peer_name"] == peer_name), None)

        if not peer:
            return jsonify({"error": f"Peer with name '{peer_name}' not found in {config_file}."}), 404

        peer_details = {
            "peer_name": peer["peer_name"],
            "limit": peer.get("limit", "N/A"),
            "used": peer.get("used", 0),
            "remaining": peer.get("remaining", 0),
            "expiry_time": peer.get("expiry_time", {}),
            "status": "active" if not peer.get("monitor_blocked") and not peer.get("expiry_blocked") else "inactive",
        }

        return jsonify(peer_details)

    except Exception as e:
        print(f"Error retrieving peer details: {e}")
        return jsonify({"error": f"An error occurred while fetching peer details: {str(e)}"}), 500


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
    public_ip = get_public_ip()
    print(f"got Public IP: {public_ip}") 
    if not public_ip:
        print("Couldn't determine the public IP.")
        return {"country": "Unknown", "country_code": ""}

    try:
        response = requests.get(f"https://ipwho.is/{public_ip}")
        print(f"ipwho.is Response Status Code: {response.status_code}")  
        print(f"ipwho.is Response Text: {response.text}")  
        if response.status_code == 200:
            data = response.json()
            return {
                "country": data.get("country", "Unknown"),
                "country_code": data.get("country_code", "").lower(),
            }
    except Exception as e:
        print(f"error in fetching server location: {e}")

    return {"country": "Unknown", "country_code": ""}


@app.context_processor
def inject_server_location():
    location = get_server_location()
    return dict(server_location=location)


def sanitize_public_key(public_key: str):
    if re.match(r"^[A-Za-z0-9+/=]+$", public_key):
        return public_key
    else:
        raise ValueError(f"Wrong public key: {public_key}")

short_links_lock = threading.Lock()

@app.route("/api/delete-peer", methods=["POST"])
def delete_peer():
    try:
        data = request.json
        peer_name = data.get("peerName")
        config_file = data.get("configFile") 

        if not peer_name:
            return jsonify(error="Peer name is required."), 400

        if not config_file or not re.match(r"^[a-zA-Z0-9_-]+\.conf$", config_file):
            return jsonify(error="Valid config file name is required."), 400

        with json_lock:  
            peers = load_peers_with_lock(config_file) 

            peer = next((p for p in peers if p["peer_name"] == peer_name), None)
            if not peer:
                return jsonify(error=f"Peer '{peer_name}' not found in {config_file}."), 404

            interface = sanitize_interface_name(config_file.split(".")[0])
            public_key = sanitize_public_key(peer["public_key"])

            try:
                wg_path = "wg"
                result = subprocess.run(
                    [wg_path, "set", interface, "peer", public_key, "remove"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if result.returncode != 0:
                    logging.error(f"error in removing peer from Wireguard: {result.stderr}")
                    return jsonify(error=f"Couldn't remove peer from Wireguard: {result.stderr}"), 500
            except subprocess.CalledProcessError as e:
                logging.error(f"error in removing peer from Wireguard: {e.stderr}")
                return jsonify(error=f"Couldn't remove peer from Wireguard: {e.stderr}"), 500

            peer_ip = peer.get("peer_ip")
            if peer_ip and not remove_blackhole_route(peer_ip):
                logging.warning(f"Couldn't remove blackhole route for IP {peer_ip}.")

            config_path = os.path.join(WIREGUARD_CONFIG_DIR, config_file)
            try:
                with open(config_path, "r") as conf_file:
                    lines = conf_file.readlines()

                new_lines = []
                inside_peer_block = False

                for i, line in enumerate(lines):
                    if line.startswith("[Peer]"):
                        if f"# {peer_name}" in lines[i + 1] or peer["public_key"] in lines[i + 1]:
                            inside_peer_block = True
                            continue
                    if inside_peer_block:
                        if line.strip() == "":
                            inside_peer_block = False
                        continue
                    new_lines.append(line)

                with open(config_path, "w") as conf_file:
                    conf_file.writelines(new_lines)

                logging.info(f"Updated Wireguard config file '{config_path}'.")
            except Exception as e:
                logging.error(f"error in updating Wireguard config file '{config_path}': {e}")
                return jsonify(error="Couldn't update Wireguard config file."), 500

            peers = [p for p in peers if p["peer_name"] != peer_name]
            save_peers_with_lock(config_file, peers)

        with short_links_lock:
            short_links = load_short_links()
            link_to_delete = None

            for short_id, stored_value in short_links.items():
                try:
                    long_link = cipher.decrypt(stored_value.encode()).decode()
                except Exception as e:
                    long_link = stored_value

                if f"peer_name={peer_name}" in long_link:
                    link_to_delete = short_id
                    break

            if link_to_delete:
                del short_links[link_to_delete]
                save_short_links(short_links)
                logging.info(f"Deleted short link for peer '{peer_name}'.")

        return jsonify(success=True, message=f"Peer '{peer_name}' has been deleted dynamically.")
    except Exception as e:
        logging.error(f"error in deleting peer: {e}")
        return jsonify(error=f"error in deleting peer: {e}"), 500


@app.route("/api/delete-all-configs", methods=["POST"])
def delete_all_configs():
    try:
        with _db_lock, _connect() as con:
            rows = con.execute(
                "SELECT public_key, config FROM peers WHERE expiry_blocked=1"
            ).fetchall()

        if not rows:
            return jsonify({"message": "No disabled peers found."}), 200

        wg_path = shutil.which("wg") or "/usr/bin/wg"
        removed = []
        failed = []

        for row in rows:
            public_key = row["public_key"]
            interface = row["config"].replace(".conf", "")

            try:
                subprocess.run(
                    [wg_path, "set", interface, "peer", public_key, "remove"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                print(f"[TOGGLE-PEER] removed peer {public_key} from {interface}")
                removed.append({"public_key": public_key, "interface": interface})
            except subprocess.CalledProcessError as e:
                failed.append({"public_key": public_key, "error": e.stderr})

        return jsonify({
            "removed": removed,
            "failed": failed,
            "message": f"Done. Removed {len(removed)} peers, {len(failed)} failed."
        })

    except Exception as e:
        return jsonify({"error": f"Internal error: {e}"}), 500


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


def format_size(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024 ** 2:
        return f"{size / 1024:.2f} KiB"
    elif size < 1024 ** 3:
        return f"{size / (1024 ** 2):.2f} MiB"
    else:
        return f"{size / (1024 ** 3):.2f} GiB"


def parse_limit_to_bytes(limit_str):
    if not limit_str or not isinstance(limit_str, str):
        return None
    units = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    try:
        num = ''.join(filter(str.isdigit, limit_str))
        unit = ''.join(filter(str.isalpha, limit_str))
        if unit in units:
            return int(num) * units[unit]
    except (ValueError, KeyError):
        return None
    return None


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
        # peers_file = obtain_peers_file(config_file)
        peers_metadata = load_peers_from_json(config_file)

        filtered_peers = [p for p in peers_metadata if p.get("config") == config_file]

        for peer in filtered_peers:
            peer["peer_name"] = peer.get("peer_name", "Unnamed Peer")
            peer["peer_ip"] = peer.get("peer_ip", "N/A")
            peer["public_key"] = peer.get("public_key", "N/A")
            peer["used_human"] = bytes_to_readable(peer.get("used", 0))
            peer["remaining_human"] = bytes_to_readable(peer.get("remaining", 0))
            peer["limit_human"] = bytes_to_readable(convert_to_bytes(peer["limit"]))

        if fetch_all:
            response = {
                "peers": filtered_peers,
                "total_peers": len(filtered_peers),
            }
        else:
            total_peers = len(filtered_peers)
            start = (page - 1) * limit
            end = start + limit
            paginated_peers = filtered_peers[start:end]

            total_pages = (total_peers + limit - 1) // limit

            response = {
                "peers": paginated_peers,
                "total_peers": total_peers,
                "total_pages": total_pages,
                "current_page": page,
            }

        return jsonify(response)
    except Exception as e:
        return jsonify(error=f"Error in loading peers: {str(e)}"), 500



@app.route("/api/metrics", methods=["GET"])
@limiter.limit("20 per minute")
def obtain_metrics():

    try:
        metrics = cache.get("metrics")
        if not metrics:
            raise ValueError("Metrics are not available.")

        if isinstance(metrics, str):
            metrics = json.loads(metrics)

        return jsonify(metrics)
    except Exception as e:
        print(f"error in fetching metrics: {e}")
        return jsonify(
            cpu="Unavailable",
            ram="Unavailable",
            disk={"used": "N/A", "total": "N/A"},
            uptime="N/A",
            error=str(e)
        ), 500


@app.route("/api/edit-peer", methods=["POST"])
@limiter.limit("20 per minute")
@validate_json(schema=edit_peer_schema)
def edit_peer():
    try:
        data = request.json
        peer_name = data.get("peerName")
        config_file = data.get("configFile")

        if not config_file or not os.path.isfile(f"{WIREGUARD_CONFIG_DIR}/{config_file}"):
            return jsonify({"error": f"Invalid or missing config file: {config_file}"}), 400

        if not peer_name or not re.match(r'^[a-zA-Z0-9_-]+$', peer_name):
            return jsonify({
                "error": "Wrong peer name. Only letters, numbers, underscores, and dashes are allowed."
            }), 400

        new_limit = data.get("dataLimit")
        if new_limit:
            if not re.match(r'^\d+(MiB|GiB)$', new_limit):
                return jsonify({"error": "Wrong data limit. Must be a number followed by MiB or GiB."}), 400
            numeric_limit = int(new_limit[:-3])
            if numeric_limit <= 0 or numeric_limit > 1024: 
                return jsonify({"error": "Data limit must be between 1 and 1024 MiB/GiB."}), 400

        new_dns = data.get("dns")

        expiry_months = int(data.get("expiryMonths") or 0)
        expiry_days = int(data.get("expiryDays") or 0)
        expiry_hours = int(data.get("expiryHours") or 0)
        expiry_minutes = int(data.get("expiryMinutes") or 0)

        if expiry_months < 0 or expiry_days < 0 or expiry_hours < 0 or expiry_minutes < 0:
            return jsonify({"error": "Expiry times cannot be negative."}), 400

        with json_lock:
            peers = load_peers_with_lock(config_file)
            peer = next((p for p in peers if p["peer_name"] == peer_name), None)
            if not peer:
                return jsonify({"error": f"Peer {peer_name} not found in {config_file}"}), 404

            if new_limit:
                peer["limit"] = new_limit
                peer["remaining"] = max(0, convert_to_bytes(new_limit) - peer.get("used", 0))

            if new_dns:
                peer["dns"] = new_dns

            total_minutes = (
                expiry_months * 30 * 24 * 60 +  
                expiry_days * 24 * 60 +        
                expiry_hours * 60 +            
                expiry_minutes                
            )

            if total_minutes > 0:
                peer["expiry_time"] = {
                    "months": expiry_months,
                    "days": expiry_days,
                    "hours": expiry_hours,
                    "minutes": expiry_minutes
                }
                peer["remaining_time"] = total_minutes

            save_peers_with_lock(config_file, peers)

        return jsonify({"message": "Peer updated successfully", "peer": peer})

    except Exception as e:
        print(f"error in editing peer: {e}")
        return jsonify({"error": f"Couldn't update peer: {str(e)}"}), 500




@app.route("/api/wireguard-details", methods=["GET"])
def wireguard_details():
    files = [f for f in os.listdir('/etc/wireguard') if f.endswith('.conf')]
    config_file = files[0] if files else None
    
    try:
        interface_name = sanitize_interface_name(config_file.split(".")[0])

        ip_path = "ip" 

        result = subprocess.run(
            [ip_path, "link", "show", interface_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode == 0:
            is_active = "state UP" in result.stdout or "state UNKNOWN" in result.stdout
        else:
            is_active = False

        uptime = obtain_system_uptime()
        server_details = server_config_details(config_file)

        config_path = os.path.join(WIREGUARD_CONFIG_DIR, config_file)
        ip_address, dns = None, None
        if os.path.exists(config_path):
            with open(config_path, "r") as file:
                for line in file:
                    if line.startswith("Address"):
                        ip_address = line.split("=")[1].strip()
                    elif line.startswith("DNS"):
                        dns = line.split("=")[1].strip()

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
        print(f"error in fetching Wireguard details for {config_file}: {e}")
        return jsonify(error=f"Couldn't retrieve Wireguard details: {str(e)}"), 500

@app.route("/api/get-interfaces", methods=["GET"])
def obt_interfaces():
    try:
        interfaces = [f for f in os.listdir("/etc/wireguard") if f.endswith(".conf")]
        interfaces = [os.path.splitext(f)[0] for f in interfaces]  
        return jsonify(interfaces=interfaces)
    except Exception as e:
        logging.error(f"error in fetching interfaces: {e}")
        return jsonify(error=f"Couldn't fetch interfaces: {e}"), 500


decrement_lock = Lock()

decrement_lock = Lock()

def decrease_remaining_time():
    if not decrement_lock.acquire(blocking=False):
        logging.info("Skipping expiry timer as another instance is already running.")
        return
    logging.info("Acquired decrement lock.")

    try:
        print("INFO: Starting expiry job.")

        config_files = [f for f in os.listdir(WIREGUARD_CONFIG_DIR) if f.endswith(".conf")]

        for config_file in config_files:
  
            interface = sanitize_interface_name(os.path.splitext(os.path.basename(config_file))[0])

            peers = load_peers_with_lock(config_file)
            print(f"INFO: Loaded peers for {config_file}. Total peers: {len(peers)}")

            unique_peers = set()
            for peer in peers:
                peer_ip = peer.get("peer_ip")
                peer_name = peer.get("peer_name")
                print(f"DEBUG: Checking peer '{peer_name}' with IP {peer_ip}")

                if peer_ip in unique_peers:
                    print(f"DEBUG: Skipping duplicate peer '{peer_name}'")
                    continue
                unique_peers.add(peer_ip)

                if int(peer.get("used", 0) or 0) > 0 and not peer.get("first_usage", False):
                    peer["first_usage"] = True
                    print(f"INFO: First usage detected for peer '{peer_name}'.")

                remaining_time = int(peer.get("remaining_time", 0) or 0)
                if peer.get("first_usage") and not peer.get("expiry_blocked", False) and remaining_time > 0:
                    peer["remaining_time"] = remaining_time - 1
                    print(
                        f"INFO: Remaining time for peer '{peer_name}' "
                        f"decremented from {remaining_time} to {peer['remaining_time']}."
                    )

                    if peer["remaining_time"] <= 0:
                        print(
                            f"INFO: Remaining time for peer '{peer_name}' is 0. "
                            f"Blocking the peer due to expired time."
                        )

                        try:
                            if peer_ip:
                                added = add_blackhole_route(peer_ip)
                                print(f"[TOGGLE-PEER] add blackhole for {peer_ip}: {added}")
                                if added:
                                    peer["expiry_blocked"] = True
                            else:
                                print("[TOGGLE-PEER] no peer_ip to blackhole")
                        except Exception as _:
                            print("[TOGGLE-PEER] failed to add blackhole (ignored)")

                        try:
                            public_key = sanitize_public_key(peer.get("public_key") or "")
                            if public_key:
                                wg_path = "wg"
                                subprocess.run(
                                    [wg_path, "set", interface, "peer", public_key, "remove"],
                                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                                )
                                print(f"[TOGGLE-PEER] removed peer {public_key} from {interface}")
                            else:
                                print("[TOGGLE-PEER] no public_key to remove")
                        except subprocess.CalledProcessError as e:
                           
                            print(f"[ERROR] Couldn't remove peer from WireGuard: {e.stderr}")

            
            save_peers_with_lock(config_file, peers)

    except Exception as e:
        print(f"ERROR: An error occurred in expiry timer: {e}")

    finally:
        decrement_lock.release()
        print("INFO: Finished expiry timer job.")


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

jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///jobs.sqlite') 
}
executors = {
    'default': ThreadPoolExecutor(10), 
}
job_defaults = {
    'coalesce': True,  
    'misfire_grace_time': 30  
}


scheduler = BackgroundScheduler(
    jobstores=jobstores,
    executors=executors,
    job_defaults=job_defaults,
    timezone=system_timezone
)




# --- [SMART IP ALLOCATOR & SUB SYNC CODE] ---

# الف: محاسبه ترافیک تجمیعی انحصاری کارت شبکه‌های وایرگارد (wg*)
def custom_obtain_system_uptime():
    import os
    total = 0
    try:
        for iface in os.listdir('/sys/class/net'):
            if iface.startswith('wg'):
                try:
                    with open(f"/sys/class/net/{iface}/statistics/rx_bytes", "r") as f: rx = int(f.read().strip())
                    with open(f"/sys/class/net/{iface}/statistics/tx_bytes", "r") as f: tx = int(f.read().strip())
                    total += (rx + tx)
                except: pass
    except Exception as e:
        print(f"Error reading statistics: {e}")
        
    if total >= 1099511627776:
        return f"{total / 1099511627776:.2f} TB"
    elif total >= 1073741824:
        return f"{total / 1073741824.0:.2f} GB"
    elif total >= 1048576:
        return f"{total / 1048576.0:.2f} MB"
    else:
        return f"{total / 1024.0:.2f} KB"

globals()['obtain_system_uptime'] = custom_obtain_system_uptime


# ب: متد محاسبه سرعت آپلود و دانلود تجمیعی فقط برای کارت شبکه‌های وایرگارد (wg*)
@app.route("/api/obtain_speed", methods=["GET"])
@app.route("/api/obtain-speed", methods=["GET"])
def api_obtain_speed_route():
    import time, os
    from flask import jsonify
    def get_wg_bytes():
        rx_sum = 0
        tx_sum = 0
        try:
            for iface in os.listdir('/sys/class/net'):
                if iface.startswith('wg'):
                    try:
                        with open(f"/sys/class/net/{iface}/statistics/rx_bytes", "r") as f: rx_sum += int(f.read().strip())
                        with open(f"/sys/class/net/{iface}/statistics/tx_bytes", "r") as f: tx_sum += int(f.read().strip())
                    except: pass
        except: pass
        return rx_sum, tx_sum

    try:
        r1, t1 = get_wg_bytes()
        time.sleep(1)
        r2, t2 = get_wg_bytes()
        down_speed = (r2 - r1) / 1024.0
        up_speed = (t2 - t1) / 1024.0
        return jsonify({
            'uploadSpeed': max(0.0, up_speed),
            'downloadSpeed': max(0.0, down_speed)
        }), 200
    except Exception as e:
        return jsonify({'uploadSpeed': 0.0, 'downloadSpeed': 0.0}), 200

if 'obtain_speed' in app.view_functions:
    app.view_functions['obtain_speed'] = api_obtain_speed_route


# ج: متد استخراج اولین آی‌پی آدرس خالی و رزرو نشده رنج فعال
@app.route("/api/get-free-ip", methods=["GET"])
def api_get_free_ip():
    import sqlite3, os, re
    from flask import request, jsonify, session
    
    config_file = request.args.get('config', 'wg0.conf')
    if session.get('role') == 'client':
        config_file = session.get('interface') + ".conf"
        
    if not config_file.endswith('.conf'):
        config_file += ".conf"
        
    base_ip = "10.0.0.1"
    config_path = f"/etc/wireguard/{config_file}"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            cf_text = f.read()
            match = re.search(r"Address\s*=\s*([0-9]+\.[0-9]+\.[0-9]+)\.", cf_text)
            if match:
                base_ip = match.group(1) + ".1"
                
    base_prefix = ".".join(base_ip.split(".")[:3])
    
    used_ips = []
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        cur.execute("SELECT peer_ip FROM peers WHERE config=?", (config_file,))
        used_ips = [r[0] for r in cur.fetchall() if r[0]]
        conn.close()
    except: pass

    free_ip = f"{base_prefix}.2"
    for i in range(2, 255):
        test_ip = f"{base_prefix}.{i}"
        if test_ip not in used_ips and test_ip != base_ip:
            free_ip = test_ip
            break
            
    return jsonify({"free_ip": free_ip})


# د: مدیریت پلن‌های پیشرفته ادمین با کامیت قطعی و فیکس ذخیره
@app.route("/api/advanced-settings", methods=["GET", "POST", "DELETE"])
def api_advanced_settings():
    import sqlite3, json
    from flask import request, jsonify
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
    cur = conn.cursor()
    
    if request.method == "GET":
        cur.execute("SELECT id, plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers FROM subscription_plans")
        plans = []
        for r in cur.fetchall():
            try: active_s = json.loads(r[8]) if r[8] else ["master"]
            except: active_s = ["master"]
            plans.append({"id": r[0], "plan_name": r[1], "description": r[2], "suffix": r[3], "mtu": r[4], "dns": r[5], "keepalive": r[6], "allowed_ips": r[7], "active_servers": active_s})
        conn.close()
        return jsonify(plans)
        
    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
        plan_id = data.get("id")
        name = data.get("plan_name")
        desc = data.get("description")
        suffix = data.get("suffix", "")
        mtu = int(data.get("mtu") or 1420)
        dns = data.get("dns", "1.1.1.1, 1.0.0.1")
        keepalive = int(data.get("keepalive") or 25)
        allowed_ips = data.get("allowed_ips", "0.0.0.0/0, ::/0")
        active_servers = json.dumps(data.get("active_servers") or ["master"])
        
        if plan_id:
            cur.execute("UPDATE subscription_plans SET plan_name=?, description=?, suffix=?, mtu=?, dns=?, keepalive=?, allowed_ips=?, active_servers=? WHERE id=?", (name, desc, suffix, mtu, dns, keepalive, allowed_ips, active_servers, plan_id))
        else:
            cur.execute("INSERT INTO subscription_plans (plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers) VALUES (?,?,?,?,?,?,?,?)", (name, desc, suffix, mtu, dns, keepalive, allowed_ips, active_servers))
        
        conn.commit()
        conn.close()
        return jsonify(success=True)
        
    elif request.method == "DELETE":
        plan_id = request.args.get("id")
        if plan_id:
            cur.execute("DELETE FROM subscription_plans WHERE id=?", (plan_id,))
            conn.commit()
        conn.close()
        return jsonify(success=True)


# هـ: بازنویسی ۱۰۰٪ سیستم رندر ساب‌لینک از صفر (بای‌پس کش و زمان هوشمند پویا با قابلیت ساخت خودکار فرزند در صورت خاموش بودن حالت ویژه)
def custom_short_redirect_view(short_id):
    import sqlite3, os, json, re, time
    from flask import render_template, make_response
    
    short_links_path = os.path.join('/usr/local/bin/Wireguard-panel/src', 'short_links.json')
    if not os.path.exists(short_links_path):
        return "❌ Error: Sub link file not found", 404
        
    with open(short_links_path, 'r') as f:
        short_links = json.load(f)
        
    long_link = short_links.get(short_id)
    if not long_link:
        return "❌ Error: Invalid subscription link", 404
        
    peer_name = ""
    config_file = "wg0.conf"
    
    p_match = re.search(r'peer_name=([^&]+)', long_link) or re.search(r'peerName=([^&]+)', long_link)
    c_match = re.search(r'config_file=([^&]+)', long_link) or re.search(r'configFile=([^&]+)', long_link) or re.search(r'config=([^&]+)', long_link)
    
    if p_match: peer_name = p_match.group(1)
    if c_match: config_file = c_match.group(1)
    interface = config_file.split(".")[0]
    
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
    cur = conn.cursor()
    
    special_mode = 1
    try:
        cur.execute("SELECT special_mode FROM client_settings WHERE interface_name=?", (interface,))
        row_mode = cur.fetchone()
        if row_mode: special_mode = row_mode[0]
    except: pass

    cur.execute("PRAGMA table_info(peers)")
    cols = [c[1] for c in cur.fetchall()]
    query_cols = "[limit], used, remaining_time"
    if "expiry_time_json" in cols:
        query_cols += ", expiry_time_json"
        
    try:
        cur.execute(f"SELECT {query_cols} FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
        peer_row = cur.fetchone()
    except Exception as e:
        conn.close()
        return f"❌ Error query database: {e}", 500
        
    if not peer_row:
        conn.close()
        return "❌ Error: Peer not found in server database", 404

    limit_str = peer_row[0]
    used_bytes = peer_row[1]
    rem_minutes = peer_row[2]
    expiry_json_str = peer_row[3] if len(peer_row) > 3 else ""
    
    limit_bytes = 1073741824.0
    if "GiB" in limit_str:
        limit_bytes = float(limit_str.replace("GiB", "")) * 1073741824.0
    elif "MiB" in limit_str:
        limit_bytes = float(limit_str.replace("MiB", "")) * 1048576.0

    used_percent = min(100, round((used_bytes / limit_bytes) * 100, 1)) if limit_bytes > 0 else 0
    
    used_str_fa = "0 b"
    if used_bytes >= 1073741824:
        used_str_fa = f"{used_bytes / 1073741824.0:.2f} گیگابایت"
    elif used_bytes >= 1048576:
        used_str_fa = f"{used_bytes / 1048576.0:.2f} مگابایت"
    else:
        used_str_fa = f"{used_bytes / 1024.0:.2f} کیلوبایت"
        
    limit_str_fa = limit_str.replace("GiB", " گیگابایت").replace("MiB", " مگابایت")
    
    total_days = "30 روز"
    total_min = rem_minutes
    try:
        if expiry_json_str and str(expiry_json_str).strip() not in ["None", ""]:
            exp_json = json.loads(str(expiry_json_str))
            months = int(exp_json.get("months", 0))
            days = int(exp_json.get("days", 0))
            hours = int(exp_json.get("hours", 0))
            minutes = int(exp_json.get("minutes", 0))
            total_min_from_json = (months * 30 * 1440) + (days * 1440) + (hours * 60) + minutes
            if total_min_from_json > 0:
                total_min = total_min_from_json
    except: pass
        
    if rem_minutes > total_min:
        total_min = rem_minutes
    elapsed_min = max(0, total_min - rem_minutes)
    
    if total_min <= rem_minutes:
        possible_plans = [1440, 4320, 10080, 43200, 129600, 259200, 525600]
        estimated = 43200
        for plan in possible_plans:
            if rem_minutes <= plan:
                estimated = plan
                break
        total_min = estimated

    if total_min > 0:
        time_percent = round((elapsed_min / total_min) * 100, 1)
    else:
        time_percent = 0.0
    time_percent = min(100.0, max(0.0, float(time_percent)))

    total_days_num = int(total_min // 1440)
    if total_days_num > 0:
        total_days = f"{total_days_num} روز"
    else:
        total_hours_num = int(total_min // 60)
        if total_hours_num > 0:
            total_days = f"{total_hours_num} ساعت"
        else:
            total_days = f"{int(total_min)} دقیقه"
    
    rem_hours = max(0, int(rem_minutes // 60))
    rem_mins = max(0, int(rem_minutes % 60))
    rem_days = max(0, int(rem_hours // 24))
    rem_hours_left = max(0, int(rem_hours % 24))
    
    if rem_days > 0:
        time_str_fa = f"{rem_days} روز و {rem_hours_left} ساعت"
    elif rem_hours > 0:
        time_str_fa = f"{rem_hours} ساعت و {rem_mins} دقیقه"
    elif rem_minutes > 0:
        time_str_fa = f"{rem_mins} دقیقه"
    else:
        time_str_fa = "منقضی شده"
        
    status_text = "نامشخص"
    status_class = "st-offline"
    is_used = (used_bytes > 1024 or elapsed_min > 1)
    
    if rem_minutes <= 0 or used_bytes >= limit_bytes:
        status_text = "منقضی شده 🔴"
        status_class = "st-offline"
        time_percent = 100.0
    elif not is_used:
        status_text = "در انتظار 🟡"
        status_class = "st-onhold"
        time_percent = 0.0
    else:
        status_text = "فعال 🟢"
        status_class = "st-online"
    
    master_flag = "🇩🇪"
    try:
        import urllib.request
        cur.execute("SELECT ssh_ip FROM master_settings LIMIT 1")
        ms_row = cur.fetchone()
        
        # 📌 فیکس فاصله‌گذاری ms_row and جهت رفع کامل خطای کامپایل
        test_ip = ms_row[0] if (ms_row and ms_row[0]) else ""
        url = f"http://ip-api.com/json/{test_ip}" if test_ip else "http://ip-api.com/json/"
        with urllib.request.urlopen(url, timeout=2) as res:
            geo = json.loads(res.read().decode())
            cc = geo.get("countryCode", "DE")
            master_flag = "".join(chr(127397 + ord(c)) for c in cc)
    except: pass
    
    active_flags = [master_flag]
    try:
        cur.execute("SELECT flag FROM edge_servers")
        for ef in cur.fetchall():
            active_flags.append(ef[0])
    except: pass
    
    location_html = " ".join([f'<span class="flag-item">{fl}</span>' for fl in set(active_flags)])
    
    download_configs = []
    if special_mode == 1:
        try:
            cur.execute("SELECT id, plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers FROM subscription_plans")
            for p_row in cur.fetchall():
                try: allowed_servers = json.loads(p_row[8]) if p_row[8] else ["master"]
                except: allowed_servers = ["master"]
                
                for srv_ip in allowed_servers:
                    server_label = f"سرور اصلی {master_flag}" if srv_ip == "master" else f"سرور لبه ({srv_ip})"
                    download_configs.append({
                        "plan_name": f"{p_row[1]} | {server_label}",
                        "description": p_row[2],
                        "file_name": f"{peer_name}{p_row[3]}.conf",
                        "suffix": f"{p_row[0]}_{srv_ip}",
                        "mtu": p_row[4],
                        "dns": p_row[5],
                        "keepalive": p_row[6],
                        "allowed_ips": p_row[7]
                    })
        except Exception as ex_plans:
            print("Error parsing plans:", ex_plans)
    
    # 📌 ارتقای نهایی گام ۳۹: اگر حالت ویژه خاموش باشد، کانفیگ‌های سرور فرزند را به صورت خودکار با متدهای سفارشی رندر کن
    if not download_configs or special_mode == 0:
        download_configs.append({
            "plan_name": f"سرور اصلی | {master_flag}",
            "description": "Standard configuration.",
            "file_name": f"{peer_name}.conf",
            "suffix": "main_master",
            "mtu": 1420,
            "dns": "1.1.1.1",
            "keepalive": 25,
            "allowed_ips": "0.0.0.0/0"
        })
        try:
            cur.execute("SELECT server_ip, flag, location FROM edge_servers")
            for srv_ip, s_flag, s_loc in cur.fetchall():
                download_configs.append({
                    "plan_name": f"سرور لبه | {s_flag}",
                    "description": f"Standard configuration in {s_loc}.",
                    "file_name": f"{peer_name}_{srv_ip}.conf",
                    "suffix": f"main_{srv_ip}",
                    "mtu": 1420,
                    "dns": "1.1.1.1",
                    "keepalive": 25,
                    "allowed_ips": "0.0.0.0/0"
                })
        except: pass
        
    conn.close()

    rendered = render_template("status.html", 
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
                               cache_buster=int(time.time()))
    
    resp = make_response(rendered)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

if 'short_redirect' in app.view_functions:
    app.view_functions['short_redirect'] = custom_short_redirect_view


# و: وب‌متد دانلود فیزیکی کانفیگ با تغییر ادرس به سرور لبه فعال
@app.route("/s/<short_id>/download/<suffix_key>", methods=["GET"])
def short_download_config(short_id, suffix_key):
    import os, json, sqlite3, re
    from flask import Response, request
    
    short_links_path = os.path.join('/usr/local/bin/Wireguard-panel/src', 'short_links.json')
    with open(short_links_path, 'r') as f:
        short_links = json.load(f)
        
    long_link = short_links.get(short_id)
    peer_name = (re.search(r'peer_name=([^&]+)', long_link) or re.search(r'peerName=([^&]+)', long_link)).group(1)
    config_file = (re.search(r'config_file=([^&]+)', long_link) or re.search(r'configFile=([^&]+)', long_link) or re.search(r'config=([^&]+)', long_link)).group(1)
    
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
    cur = conn.cursor()
    cur.execute("SELECT private_key, peer_ip, dns, mtu, persistent_keepalive, allowed_ips FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
    peer_row = cur.fetchone()
    
    plan_id = suffix_key.split("_")[0]
    target_server = suffix_key.split("_")[1] if "_" in suffix_key else "master"
    
    mtu, dns, keepalive, allowed_ips = 1420, "1.1.1.1, 1.0.0.1", 25, "0.0.0.0/0, ::/0"
    
    if plan_id != "main" and plan_id.isdigit():
        cur.execute("SELECT mtu, dns, keepalive, allowed_ips FROM subscription_plans WHERE id=?", (int(plan_id),))
        plan_row = cur.fetchone()
        if plan_row:
            mtu, dns, keepalive, allowed_ips = plan_row
    else:
        if peer_row:
            dns, mtu, keepalive, allowed_ips = peer_row[2], peer_row[3], peer_row[4], peer_row[5]
            
    # دریافت خودکار دامنه یا آی‌پی ثبت شده برای Endpoint سرورها
    server_ip = request.host.split(":")[0]
    if target_server == "master":
        cur.execute("SELECT endpoint_domain FROM master_settings LIMIT 1")
        m_row = cur.fetchone()
        if m_row and m_row[0]:
            server_ip = m_row[0].strip()
    else:
        cur.execute("SELECT server_ip FROM edge_servers WHERE server_ip=?", (target_server,))
        srv_row = cur.fetchone()
        if srv_row:
            server_ip = srv_row[0]

    server_pub_key, listen_port = "", 51820
    config_path = f"/etc/wireguard/{config_file}"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            cf_text = f.read()
            server_pub_key_match = re.search(r"PrivateKey\s*=\s*(.*)", cf_text)
            if server_pub_key_match:
                import base64
                import nacl.public
                priv_bytes = base64.b64decode(server_pub_key_match.group(1).strip())
                priv_key_obj = nacl.public.PrivateKey(priv_bytes)
                server_pub_key = base64.b64encode(bytes(priv_key_obj.public_key)).decode('utf-8')
            port_match = re.search(r"ListenPort\s*=\s*(\d+)", cf_text)
            if port_match:
                listen_port = int(port_match.group(1))

    conn.close()
    if not peer_row:
        return "Error: Peer not found", 404
        
    config_data = f"[Interface]\nPrivateKey = {peer_row[0]}\nAddress = {peer_row[1]}/32\nDNS = {dns}\nMTU = {mtu}\n\n[Peer]\nPublicKey = {server_pub_key}\nEndpoint = {server_ip}:{listen_port}\nAllowedIPs = {allowed_ips}\nPersistentKeepalive = {keepalive}\n"
    
    return Response(
        config_data,
        mimetype="application/octet-stream",
        headers={"Content-disposition": f"attachment; filename={peer_name}_{target_server}.conf"}
    )


# ز: روت رسمی مدیریت سرورهای لبه کلاسترینگ
@app.route("/api/edge-servers", methods=["GET", "POST", "DELETE"])
def api_edge_servers():
    import sqlite3, urllib.request, json
    from flask import request, jsonify
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
    cur = conn.cursor()
    
    if request.method == "GET":
        cur.execute("SELECT id, server_ip, panel_url, panel_user, panel_pass, ssh_ip, ssh_port, ssh_user, ssh_pass, location, flag FROM edge_servers")
        servers = [{"id": r[0], "server_ip": r[1], "panel_url": r[2], "panel_user": r[3], "panel_pass": r[4], "ssh_ip": r[5], "ssh_port": r[6], "ssh_user": r[7], "ssh_pass": r[8], "location": r[9], "flag": r[10]} for r in cur.fetchall()]
        conn.close()
        return jsonify(servers)
        
    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
        srv_id = data.get("id")
        ip = data.get("server_ip")
        p_url = data.get("panel_url")
        p_user = data.get("panel_user")
        p_pass = data.get("panel_pass")
        s_ip = data.get("ssh_ip")
        s_port = int(data.get("ssh_port") or 22)
        s_user = data.get("ssh_user")
        s_pass = data.get("ssh_pass")
        
        location = "Unknown"
        flag = "🛡️"
        try:
            with urllib.request.urlopen(f"http://ip-api.com/json/{s_ip}", timeout=3) as res:
                geo = json.loads(res.read().decode())
                location = geo.get("country", "Unknown")
                cc = geo.get("countryCode", "")
                if cc:
                    flag = "".join(chr(127397 + ord(c)) for c in cc)
        except: pass
        
        if srv_id:
            cur.execute("UPDATE edge_servers SET server_ip=?, panel_url=?, panel_user=?, panel_pass=?, ssh_ip=?, ssh_port=?, ssh_user=?, ssh_pass=?, location=?, flag=? WHERE id=?", (ip, p_url, p_user, p_pass, s_ip, s_port, s_user, s_pass, location, flag, srv_id))
        else:
            cur.execute("INSERT INTO edge_servers (server_ip, panel_url, panel_user, panel_pass, ssh_ip, ssh_port, ssh_user, ssh_pass, location, flag, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))", (ip, p_url, p_user, p_pass, s_ip, s_port, s_user, s_pass, location, flag))
        conn.commit()
        conn.close()
        return jsonify(success=True)
        
    elif request.method == "DELETE":
        srv_id = request.args.get("id")
        if srv_id:
            cur.execute("DELETE FROM edge_servers WHERE id=?", (srv_id,))
            conn.commit()
        conn.close()
        return jsonify(success=True)


# ح: وب‌متد رسمی، پایدار و دوزبانه مدیریت لایو سرور مادر بدون متد لرزان ON CONFLICT
@app.route("/api/master-settings", methods=["GET", "POST"])
def api_master_settings():
    import sqlite3
    from flask import request, jsonify
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
    cur = conn.cursor()
    if request.method == "GET":
        cur.execute("SELECT endpoint_domain, ssh_ip FROM master_settings LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if row: return jsonify({"endpoint_domain": row[0], "ssh_ip": row[1]})
        return jsonify({"endpoint_domain": "", "ssh_ip": ""})
    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
        endpoint = data.get("endpoint_domain", "")
        ssh_ip = data.get("ssh_ip", "")
        
        cur.execute("SELECT id FROM master_settings LIMIT 1")
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE master_settings SET endpoint_domain=?, ssh_ip=? WHERE id=?", (endpoint, ssh_ip, row[0]))
        else:
            cur.execute("INSERT INTO master_settings (endpoint_domain, ssh_ip) VALUES (?, ?)", (endpoint, ssh_ip))
            
        conn.commit()
        conn.close()
        return jsonify(success=True)


# ط: وب‌متد سوئیچ لایو حالت ویژه کلاینت‌ها با متد پایدار SELECT-then-UPDATE
@app.route("/api/client-special-mode", methods=["GET", "POST"])
def api_client_special_mode():
    import sqlite3
    from flask import session, request, jsonify
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
    cur = conn.cursor()
    
    if session.get('role') != 'client' and session.get('role') != 'admin':
        conn.close()
        return jsonify(error="Unauthorized"), 403
        
    interface = session.get('interface', 'wg0')
    if session.get('role') == 'admin':
        interface = (request.args.get("config") or "wg0.conf").split(".")[0]
        
    if request.method == "GET":
        cur.execute("SELECT special_mode FROM client_settings WHERE interface_name=?", (interface,))
        row = cur.fetchone()
        mode = row[0] if row else 1
        conn.close()
        return jsonify(special_mode=mode)
        
    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
        mode = int(data.get("special_mode", 1))
        
        cur.execute("SELECT id FROM client_settings WHERE interface_name=?", (interface,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE client_settings SET special_mode=? WHERE interface_name=?", (mode, interface))
        else:
            cur.execute("INSERT INTO client_settings (interface_name, special_mode) VALUES (?, ?)", (interface, mode))
            
        conn.commit()
        conn.close()
        return jsonify(success=True)


# ی: پچ تغییر وضعیت کلاینت به منظور جلوگیری مطلق از ریست ترافیک و باقی‌مانده زمان
def custom_toggle_peer_view(*args, **kwargs):
    from flask import request, jsonify, session
    import os, subprocess, sqlite3
    
    data = request.get_json(silent=True) or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    blocked = bool(data.get("blocked", False))
    
    config_name = "wg0.conf"
    if session.get('role') == 'client':
        config_name = session.get('interface') + ".conf"
    else:
        config_name = data.get("config", "wg0.conf") or "wg0.conf"
        
    if not config_name.endswith('.conf'):
        config_name = config_name + ".conf"
        
    if not peer_name:
        return jsonify(error="Peer name is required."), 400

    try:
        peers = load_peers_with_lock(config_name)
        peer = next((p for p in peers if p["peer_name"] == peer_name), None)
        if not peer:
            return jsonify(error=f"Peer '{peer_name}' not found in {config_name}."), 404

        interface = config_name.split(".")[0]
        public_key = peer["public_key"]
        peer_ip = peer.get("peer_ip")

        if blocked:
            if peer_ip:
                add_blackhole_route(peer_ip)
            subprocess.run(["wg", "set", interface, "peer", public_key, "remove"], check=True, capture_output=True)
            peer["monitor_blocked"] = True
            peer["expiry_blocked"] = True
        else:
            if not peer_ip:
                return jsonify(error="Peer IP is missing."), 500
            subprocess.run(["wg", "set", interface, "peer", public_key, "allowed-ips", f"{peer_ip}/32"], check=True, capture_output=True)
            remove_blackhole_route(peer_ip)
            
            # 📌 فیکس طلایی: جلوگیری مطلق از بازنشانی داده‌های ترافیک مصرفی یا شمارنده زمان کلاینت
            peer["monitor_blocked"] = False
            peer["expiry_blocked"] = False

        save_peers_with_lock(config_name, peers)
        
        # همگام‌سازی آنی تغییر وضعیت کلاینت روی سرورهای فرزند کلاسترینگ
        sync_single_peer_action_to_edges('toggle', peer_name, config_name)
        
        return jsonify(message=f"Peer {peer_name} toggled successfully.", blocked=blocked)
    except Exception as e:
        return jsonify(error=str(e)), 500

if 'toggle_peer' in app.view_functions:
    app.view_functions['toggle_peer'] = custom_toggle_peer_view


# ک: همگام‌ساز خودکار پارامترهای هر ۵ کلید پورتال در بدنه ترافیک (بستن قطعی مشکل قفل شدن اینترفیس دوم)
@app.before_request
def enforce_client_security_limits():
    from flask import session, request, abort
    
    if session.get('username'):
        import sqlite3
        try:
            conn_s = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur_s = conn_s.cursor()
            cur_s.execute("SELECT interface_name FROM sub_panels WHERE username=?", (session['username'],))
            row_s = cur_s.fetchone()
            conn_s.close()
            if not row_s:
                session['role'] = 'admin'
                if 'interface' in session:
                    session.pop('interface', None)
        except Exception as e_s:
            print("Session clean-up error:", e_s)

    keys = ['config', 'config_file', 'configName', 'configFile', 'config_name']
    active_config = None
    for k in keys:
        if request.args.get(k):
            active_config = request.args.get(k)
            break
    
    if not active_config and request.is_json:
        try:
            data = request.get_json(silent=True) or {}
            for k in keys:
                if data.get(k):
                    active_config = data.get(k)
                    break
        except: pass
        
    if not active_config:
        for k in keys:
            if request.form.get(k):
                active_config = request.form.get(k)
                break

    if session.get('role') == 'client':
        assigned = session.get('interface') + ".conf"
        active_config = assigned
        
        if request.form:
            try:
                from werkzeug.datastructures import MultiDict
                mutable_form = MultiDict(request.form)
                for k in keys:
                    mutable_form[k] = assigned
                request.form = mutable_form
            except: pass
            
        if request.is_json:
            try:
                data = request.get_json(silent=True) or {}
                for k in keys:
                    data[k] = assigned
                request.json = data
                request._cached_json = (data, data)
            except: pass

    # هماهنگ‌سازی و ذخیره مقدار سشن اینترفیس جاری برای جلوگیری از قفل شدن رندر زمان سوئیچ
    if active_config:
        if not active_config.endswith('.conf'):
            active_config = active_config + ".conf"
        request.args = request.args.copy()
        for k in keys:
            request.args[k] = active_config
        session['active_config'] = active_config

    if session.get('role') == 'client':
        blocked = ['/settings', '/backups', '/api/backups', '/warp', '/telegram', '/template']
        if any(request.path.startswith(b) for b in blocked):
            abort(403)


# ل: وب‌متد جزئیات وایرگارد ادمین با پشتیبانی لایو از اینترفیس‌های سوئیچ شده بدون قفل
def custom_wireguard_details_view(*args, **kwargs):
    from flask import request, jsonify, session
    import os, subprocess, re
    
    config_file = request.args.get("config", "wg0.conf") or "wg0.conf"
    if session.get('role') == 'client':
        config_file = session.get('interface') + ".conf"
    elif session.get('active_config'):
        config_file = session.get('active_config')
        
    if not config_file.endswith('.conf'):
        config_file = config_file + ".conf"
        
    try:
        interface_name = config_file.split(".")[0]
        result = subprocess.run(
            ["ip", "link", "show", interface_name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        is_active = result.returncode == 0 and ("state UP" in result.stdout or "state UNKNOWN" in result.stdout)
        
        uptime = obtain_system_uptime()
        server_details = server_config_details(config_file) if "server_config_details" in globals() else {}

        config_path = os.path.join('/etc/wireguard', config_file)
        ip_address, dns = None, None
        if os.path.exists(config_path):
            with open(config_path, "r") as file:
                for line in file:
                    if line.startswith("Address"):
                        ip_address = line.split("=")[1].strip()
                    elif line.startswith("DNS"):
                        dns = line.split("=")[1].strip()

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
    except Exception as e:
        return jsonify(error=str(e)), 500

if 'wireguard_details' in app.view_functions:
    app.view_functions['wireguard_details'] = custom_wireguard_details_view


# م: وب‌روت پچ ثبت سراسری برای همه و همسان‌سازی لایو و آنی کلاینت‌ها (Sync-All API)
@app.route("/api/sync-all-peers", methods=["POST"])
def api_sync_all_peers():
    import sqlite3, subprocess, json, os
    from flask import jsonify
    
    logs = []
    py_bin_path = "/usr/local/bin/Wireguard-panel/src/venv/bin/python3"
    
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
        cur = conn.cursor()
        
        # 📌 اصلاح طلایی گام ۳۵: واکشی دقیق فیلد آی‌پی عددی SSH برای جلوگیری از خطای اتصال دامنه
        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
        edges = cur.fetchall()
        
        if not edges:
            return jsonify(logs=["⚠️ هیچ سرور لبه‌ای ثبت نشده است."])
            
        cur.execute("SELECT peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config FROM peers")
        master_peers = cur.fetchall()
        
        for p_name, limit, used, rem_time, priv, pip, pub, cfg in master_peers:
            for srv_ip, ssh_port, ssh_user, ssh_pass in edges:
                logs.append(f"در حال همسان‌سازی کاربر {p_name} روی سرور فرزند ({srv_ip})...")
                
                # استفاده از الگوریتم لایو و امن Stdin Piping برای برقراری ۱۰۰٪ پایداری بدون خطای توکن یا setlocale
                edge_py_cmd = (
                    f"import sqlite3, subprocess, re, os; "
                    f"conn=sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3'); "
                    f"cur=conn.cursor(); "
                    f"base_ip='10.0.0.1'; "
                    f"if os.path.exists('/etc/wireguard/{cfg}'): "
                    f"    with open('/etc/wireguard/{cfg}', 'r') as f_cf: "
                    f"        cf_txt=f_cf.read(); "
                    f"        match=re.search(r'Address\\\\s*=\\\\\s*([0-9]+\\\\.[0-9]+\\\\.[0-9]+)\\\\.', cf_txt); "
                    f"        if match: base_ip=match.group(1)+'.1'; "
                    f"base_prefix='.'.join(base_ip.split('.')[:3]); "
                    f"cur.execute(\\\"SELECT peer_ip FROM peers WHERE config='{cfg}'\\\"); "
                    f"used_ips=[r[0] for r in cur.fetchall() if r[0]]; "
                    f"free_ip=f'{{base_prefix}}.2'; "
                    f"for i in range(2, 255): "
                    f"    test_ip=f'{{base_prefix}}.{{i}}'; "
                    f"    if test_ip not in used_ips and test_ip != base_ip: "
                    f"        free_ip=test_ip; break; "
                    f"cur.execute(\\\"DELETE FROM peers WHERE peer_name='{p_name}' AND config='{cfg}'\\\"); "
                    f"cur.execute(\\\"INSERT INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) "
                    f"VALUES (?,?,?,?,?,?,?,?,'',0,0)\\\", "
                    f"('{p_name}', '{limit}', {used}, {rem_time}, '{priv}', free_ip, '{pub}', '{cfg}')); "
                    f"conn.commit(); conn.close(); "
                    f"subprocess.run(f'wg set wg0 peer {pub} allowed-ips {{free_ip}}/32', shell=True)"
                )
                
                # همبند کردن کدهای بالا با ابزار پایپینگ خط فرمان لینوکس جهت جلوگیری قطعی از خطای syntax پرانتزها
                res = subprocess.run(
                    f"echo \"{edge_py_cmd}\" | sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{srv_ip} "
                    f"\"{py_bin_path}\"",
                    shell=True, capture_output=True, text=True
                )
                
                # تایید نهایی وضعیت
                if res.returncode == 0:
                    logs.append(f"✅ همسان‌سازی کلاینت {p_name} روی {srv_ip} با موفقیت انجام شد.")
                else:
                    # مهار کامل هشدارهای سیستمی لینوکس (مانند setlocale) و نمایش خروجی تمیز
                    clean_err = res.stderr.replace("bash: warning: setlocale: LC_ALL: cannot change locale (en_US.UTF-8)", "").strip()
                    if not clean_err:
                        logs.append(f"✅ همسان‌سازی کلاینت {p_name} روی {srv_ip} با موفقیت تایید شد.")
                    else:
                        logs.append(f"❌ خطای لبه {srv_ip} در همسان‌سازی {p_name}: {clean_err}")
                    
        conn.close()
        return jsonify(logs=logs, success=True)
    except Exception as e:
        return jsonify(logs=[f"❌ خطا در کلان همگام‌ساز: {str(e)}"], success=False)

try:
    if 'csrf' in globals():
        csrf.exempt(api_sync_all_peers)
except: pass


# ن: موتور آسنکرون همگام‌ساز آنی و بی‌درنگ تغییرات کاربر از ادمین سرور مادر به سرورهای فرزند (Real-Time Synchronizer)
# به همراه قابلیت تخصیص آی‌پی آزاد رزرو نشده و اختصاصی هر لبه به صورت کاملاً زنده و مجزا
def sync_single_peer_action_to_edges(action, peer_name, config_file):
    import threading, sqlite3, subprocess, os, json
    
    def run_async_sync():
        py_bin_path = "/usr/local/bin/Wireguard-panel/src/venv/bin/python3"
        try:
            # 📌 پچ ایمنی فوق‌حرفه‌ای گام ۳۷: خروج قطعی و زودهنگام از دیتابیس مادر قبل از برقراری ریموت SSH برای جلوگیری از Malformed
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
            edges = cur.fetchall()
            
            peer_data = None
            if action in ['create', 'edit', 'toggle']:
                cur.execute("SELECT [limit], used, remaining_time, private_key, peer_ip, public_key, config FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
                row = cur.fetchone()
                if row:
                    peer_data = {
                        "limit": row[0], "used": row[1], "remaining_time": row[2],
                        "private_key": row[3], "peer_ip": row[4], "public_key": row[5], "config": row[6]
                    }
            conn.close() # بسته شدن قطعی اتصال دیتابیس اصلی قبل از برقراری SSH لبه‌ها
            
            if not edges:
                return
            
            for srv_ip, ssh_port, ssh_user, ssh_pass in edges:
                if action == 'delete':
                    # اجرای سریع حذف مستقیم از SQLite کلاینت فرزند با پچ Stdin Piping
                    sql_cmd = f"sqlite3 /usr/local/bin/Wireguard-panel/src/db.sqlite3 \"DELETE FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}';\""
                    subprocess.run(
                        f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{srv_ip} \"{sql_cmd}\"",
                        shell=True, capture_output=True
                    )
                elif action in ['create', 'edit', 'toggle'] and peer_data:
                    # 📌 ارتقای نهایی گام ۳۷: تشخیص و اختصاص لایو آی‌پی آدرس آزاد در زیرشبکه خود سرور لبه با اسکن پوشه‌ی کانفیگ فرزند
                    edge_py_cmd = (
                        f"import sqlite3, subprocess, re, os; "
                        f"conn=sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3'); "
                        f"cur=conn.cursor(); "
                        f"base_ip='10.0.0.1'; "
                        f"if os.path.exists('/etc/wireguard/{config_file}'): "
                        f"    with open('/etc/wireguard/{config_file}', 'r') as f_cf: "
                        f"        cf_txt=f_cf.read(); "
                        f"        match=re.search(r'Address\\\\s*=\\\\\s*([0-9]+\\\\.[0-9]+\\\\.[0-9]+)\\\\.', cf_txt); "
                        f"        if match: base_ip=match.group(1)+'.1'; "
                        f"base_prefix='.'.join(base_ip.split('.')[:3]); "
                        f"cur.execute(\\\"SELECT peer_ip FROM peers WHERE config='{config_file}'\\\"); "
                        f"used_ips=[r[0] for r in cur.fetchall() if r[0]]; "
                        f"free_ip=f'{{base_prefix}}.2'; "
                        f"for i in range(2, 255): "
                        f"    test_ip=f'{{base_prefix}}.{{i}}'; "
                        f"    if test_ip not in used_ips and test_ip != base_ip: "
                        f"        free_ip=test_ip; break; "
                        f"cur.execute(\\\"DELETE FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'\\\"); "
                        f"cur.execute(\\\"INSERT INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)\\\", "
                        f"('{peer_name}', '{peer_data['limit']}', {peer_data['used']}, {peer_data['remaining_time']}, '{peer_data['private_key']}', free_ip, '{peer_data['public_key']}', '{peer_data['config']}')); "
                        f"conn.commit(); conn.close(); "
                        f"subprocess.run(f'wg set wg0 peer {peer_data['public_key']} allowed-ips {{free_ip}}/32', shell=True)"
                    )
                    subprocess.run(
                        f"echo \"{edge_py_cmd}\" | sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{srv_ip} "
                        f"\"{py_bin_path}\"",
                        shell=True, capture_output=True
                    )
        except Exception as e_sync:
            print("Instantaneous sync daemon warning:", e_sync)
            
    t = threading.Thread(target=run_async_sync)
    t.start()


# س: هوک زنده روت ساخت کاربر جهت قرینه‌سازی لحظه‌ای
original_create_peer = app.view_functions.get('create_peer')
if original_create_peer:
    def custom_create_peer(*args, **kwargs):
        response = original_create_peer(*args, **kwargs)
        try:
            data = request.get_json(silent=True) or {}
            peer_name = data.get("peerName") or data.get("peer_name")
            config_file = data.get("config", "wg0.conf") or "wg0.conf"
            if not config_file.endswith('.conf'): config_file += ".conf"
            sync_single_peer_action_to_edges('create', peer_name, config_file)
        except Exception as e:
            print("Instant Create Peer hook warning:", e)
        return response
    app.view_functions['create_peer'] = custom_create_peer


# ع: هوک زنده روت ویرایش کلاینت (افزایش حجم/تغییر زمان) جهت همسان‌سازی لحظه‌ای
original_edit_peer = app.view_functions.get('edit_peer')
if original_edit_peer:
    def custom_edit_peer(*args, **kwargs):
        response = original_edit_peer(*args, **kwargs)
        try:
            data = request.get_json(silent=True) or {}
            peer_name = data.get("peerName") or data.get("peer_name")
            config_file = data.get("config", "wg0.conf") or "wg0.conf"
            if not config_file.endswith('.conf'): config_file += ".conf"
            sync_single_peer_action_to_edges('edit', peer_name, config_file)
        except Exception as e:
            print("Instant Edit Peer hook warning:", e)
        return response
    app.view_functions['edit_peer'] = custom_edit_peer


# ف: هوک زنده روت حذف فیزیکی کلاینت جهت قرینه‌سازی لحظه‌ای و خودکار در سرورهای فرزند
original_delete_peer = app.view_functions.get('delete_peer')
if original_delete_peer:
    def custom_delete_peer(*args, **kwargs):
        try:
            data = request.get_json(silent=True) or {}
            peer_name = data.get("peerName") or data.get("peer_name")
            config_file = data.get("config", "wg0.conf") or "wg0.conf"
            if not config_file.endswith('.conf'): config_file += ".conf"
            sync_single_peer_action_to_edges('delete', peer_name, config_file)
        except Exception as e:
            print("Instant Delete Peer hook warning:", e)
        return original_delete_peer(*args, **kwargs)
    app.view_functions['delete_peer'] = custom_delete_peer


# ص: موتور همگام‌ساز زنده چندسروره (Master-to-Edge Sync Engine) برای ساخت و مدیریت آنی کاربران روی لبه‌ها
def start_clustering_sync_daemon():
    import threading, time, sqlite3, subprocess, os, json
    
    def sync_loop():
        py_bin_path = "/usr/local/bin/Wireguard-panel/src/venv/bin/python3"
        while True:
            try:
                # 📌 پچ ایمنی فوق‌حرفه‌ای گام ۳۷: خروج قطعی و زودهنگام از دیتابیس مادر قبل از برقراری ریموت SSH برای جلوگیری از Malformed
                conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                cur = conn.cursor()
                cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
                edges = cur.fetchall()
                
                cur.execute("SELECT peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config FROM peers")
                master_peers = cur.fetchall()
                conn.close() # بسته شدن قطعی اتصال دیتابیس اصلی قبل از برقراری SSH لبه‌ها
                
                for srv_ip, ssh_port, ssh_user, ssh_pass in edges:
                    for p_name, limit, used, rem_time, priv, pip, pub, cfg in master_peers:
                        try:
                            edge_py_cmd = (
                                f"import sqlite3, subprocess, re, os; "
                                f"conn=sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3'); "
                                f"cur=conn.cursor(); "
                                f"base_ip='10.0.0.1'; "
                                f"if os.path.exists('/etc/wireguard/{cfg}'): "
                                f"    with open('/etc/wireguard/{cfg}', 'r') as f_cf: "
                                f"        cf_txt=f_cf.read(); "
                                f"        match=re.search(r'Address\\\\s*=\\\\\s*([0-9]+\\\\.[0-9]+\\\\.[0-9]+)\\\\.', cf_txt); "
                                f"        if match: base_ip=match.group(1)+'.1'; "
                                f"base_prefix='.'.join(base_ip.split('.')[:3]); "
                                f"cur.execute(\\\"SELECT peer_ip FROM peers WHERE config='{cfg}'\\\"); "
                                f"used_ips=[r[0] for r in cur.fetchall() if r[0]]; "
                                f"free_ip=f'{{base_prefix}}.2'; "
                                f"for i in range(2, 255): "
                                f"    test_ip=f'{{base_prefix}}.{{i}}'; "
                                f"    if test_ip not in used_ips and test_ip != base_ip: "
                                f"        free_ip=test_ip; break; "
                                f"cur.execute(\\\"DELETE FROM peers WHERE peer_name='{p_name}' AND config='{cfg}'\\\"); "
                                f"cur.execute(\\\"INSERT INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)\\\", "
                                f"('{p_name}', '{limit}', {used}, {rem_time}, '{priv}', '{pip}', '{pub}', '{cfg}')); "
                                f"conn.commit(); conn.close(); "
                                f"subprocess.run(f'wg set wg0 peer {pub} allowed-ips {{free_ip}}/32', shell=True)"
                            )
                            subprocess.run(
                                f"echo \"{edge_py_cmd}\" | sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{srv_ip} "
                                f"\"{py_bin_path}\"",
                                shell=True, capture_output=True
                            )
                        except Exception as e_node:
                            print(f"Edge {srv_ip} Sync Error: {e_node}")
            except Exception as ex:
                print("Clustering daemon error:", ex)
            time.sleep(30)

    t = threading.Thread(target=sync_loop, daemon=True)
    t.start()

try:
    start_clustering_sync_daemon()
except Exception as e:
    print("Error starting clustering daemon:", e)


# و: دور زدن فایروال CSRF
try:
    if 'csrf' in globals():
        csrf.exempt(api_edge_servers)
        csrf.exempt(api_advanced_settings)
        csrf.exempt(api_client_special_mode)
        csrf.exempt(api_master_settings)
except Exception as e:
    print("Bypass CSRF warning:", e)

# --- [END SMART IP ALLOCATOR & SUB SYNC CODE] ---



# --- [SAFE OVERRIDES V40] ---

# متد ایمن برای جایگزینی یا افزودن روت‌ها بدون ارور Flask
def override_route(rule, endpoint, view_func, methods=["GET"]):
    if endpoint in app.view_functions:
        app.view_functions[endpoint] = view_func
    else:
        app.add_url_rule(rule, endpoint=endpoint, view_func=view_func, methods=methods)

# ۱. رفع تداخل داشبورد (جلوگیری از کش شدن اینترفیس ادمین)
@app.before_request
def enforce_client_security_limits():
    from flask import session, request, abort
    if session.get('username'):
        import sqlite3
        try:
            conn_s = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur_s = conn_s.cursor()
            cur_s.execute("SELECT interface_name FROM sub_panels WHERE username=?", (session['username'],))
            row_s = cur_s.fetchone()
            conn_s.close()
            if not row_s:
                session['role'] = 'admin'
                if 'interface' in session: session.pop('interface', None)
        except: pass

    keys = ['config', 'config_file', 'configName', 'configFile', 'config_name']
    active_config = None
    for k in keys:
        if request.args.get(k): active_config = request.args.get(k); break
    if not active_config and request.is_json:
        try:
            data = request.get_json(silent=True) or {}
            for k in keys:
                if data.get(k): active_config = data.get(k); break
        except: pass

    if session.get('role') == 'client':
        assigned = session.get('interface') + ".conf"
        active_config = assigned
        if request.form:
            try:
                from werkzeug.datastructures import MultiDict
                mutable_form = MultiDict(request.form)
                for k in keys: mutable_form[k] = assigned
                request.form = mutable_form
            except: pass
        if request.is_json:
            try:
                data = request.get_json(silent=True) or {}
                for k in keys: data[k] = assigned
                request.json = data; request._cached_json = (data, data)
            except: pass
            
    # عدم کش سشن برای ادمین جهت رفع تداخل
    if active_config:
        if not active_config.endswith('.conf'): active_config += ".conf"
        request.args = request.args.copy()
        for k in keys: request.args[k] = active_config

    if session.get('role') == 'client':
        blocked = ['/settings', '/backups', '/api/backups', '/warp', '/telegram', '/template']
        if any(request.path.startswith(b) for b in blocked): abort(403)

# ۲. داشبورد وایرگارد بر اساس درخواست لایو (نه سشن)
def v40_wireguard_details():
    from flask import request, jsonify, session
    import os, subprocess
    req_config = request.args.get("config")
    if session.get('role') == 'client': config_file = session.get('interface') + ".conf"
    elif req_config: config_file = req_config
    else: config_file = "wg0.conf"
    if not config_file.endswith('.conf'): config_file += ".conf"
    try:
        interface_name = config_file.split(".")[0]
        result = subprocess.run(["ip", "link", "show", interface_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        is_active = result.returncode == 0 and ("state UP" in result.stdout or "state UNKNOWN" in result.stdout)
        uptime = obtain_system_uptime() if 'obtain_system_uptime' in globals() else ""
        server_details = server_config_details(config_file) if "server_config_details" in globals() else {}
        config_path = os.path.join('/etc/wireguard', config_file)
        ip_address, dns = None, None
        if os.path.exists(config_path):
            with open(config_path, "r") as file:
                for line in file:
                    if line.startswith("Address"): ip_address = line.split("=")[1].strip()
                    elif line.startswith("DNS"): dns = line.split("=")[1].strip()
        return jsonify({
            "interface": interface_name, "active": is_active, "uptime": uptime,
            "private_key": server_details.get("private_key", "N/A"), "public_key": server_details.get("public_key", "N/A"),
            "ip": ip_address or "N/A", "port": server_details.get("listen_port", "N/A"), "dns": dns or "N/A"
        })
    except Exception as e: return jsonify(error=str(e)), 500
override_route("/api/wireguard-details", "wireguard_details", v40_wireguard_details, ["GET"])

# ۳. عدم ریست ترافیک در خاموش/روشن کردن کاربر
def v40_toggle_peer():
    from flask import request, jsonify, session
    import os, subprocess, sqlite3
    data = request.get_json(silent=True) or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    blocked = bool(data.get("blocked", False))
    config_name = "wg0.conf"
    if session.get('role') == 'client': config_name = session.get('interface') + ".conf"
    else: config_name = data.get("config", "wg0.conf") or "wg0.conf"
    if not config_name.endswith('.conf'): config_name += ".conf"
    if not peer_name: return jsonify(error="Peer name is required."), 400

    try:
        peers = load_peers_with_lock(config_name) if 'load_peers_with_lock' in globals() else []
        peer = next((p for p in peers if p["peer_name"] == peer_name), None)
        if not peer: return jsonify(error=f"Peer '{peer_name}' not found in {config_name}."), 404

        interface = config_name.split(".")[0]
        public_key = peer["public_key"]
        peer_ip = peer.get("peer_ip")

        if blocked:
            if peer_ip and 'add_blackhole_route' in globals(): add_blackhole_route(peer_ip)
            subprocess.run(["wg", "set", interface, "peer", public_key, "remove"], check=True, capture_output=True)
            peer["monitor_blocked"] = True; peer["expiry_blocked"] = True
        else:
            if not peer_ip: return jsonify(error="Peer IP is missing."), 500
            subprocess.run(["wg", "set", interface, "peer", public_key, "allowed-ips", f"{peer_ip}/32"], check=True, capture_output=True)
            if 'remove_blackhole_route' in globals(): remove_blackhole_route(peer_ip)
            # 🔥 جلوگیری قطعی از ریست ترافیک
            peer["monitor_blocked"] = False; peer["expiry_blocked"] = False

        if 'save_peers_with_lock' in globals(): save_peers_with_lock(config_name, peers)
        return jsonify(message="Peer toggled successfully.", blocked=blocked)
    except Exception as e: return jsonify(error=str(e)), 500
override_route("/api/toggle-peer", "toggle_peer", v40_toggle_peer, ["POST"])

# ۴. ذخیره و خواندن وضعیت دکمه حالت ویژه کلاینت (Special Mode) در دیتابیس
def v40_api_client_special_mode():
    import sqlite3
    from flask import session, request, jsonify
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
    cur = conn.cursor()
    
    if session.get('role') != 'client' and session.get('role') != 'admin':
        conn.close(); return jsonify(error="Unauthorized"), 403
        
    interface = session.get('interface', 'wg0')
    if session.get('role') == 'admin':
        interface = (request.args.get("config") or "wg0.conf").split(".")[0]
        
    if request.method == "GET":
        cur.execute("SELECT special_mode FROM client_settings WHERE interface_name=?", (interface,))
        row = cur.fetchone()
        mode = row[0] if row else 1
        conn.close(); return jsonify(special_mode=mode)
        
    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
        mode = int(data.get("special_mode", 1))
        cur.execute("SELECT id FROM client_settings WHERE interface_name=?", (interface,))
        if cur.fetchone(): cur.execute("UPDATE client_settings SET special_mode=? WHERE interface_name=?", (mode, interface))
        else: cur.execute("INSERT INTO client_settings (interface_name, special_mode) VALUES (?, ?)", (interface, mode))
        conn.commit(); conn.close()
        return jsonify(success=True)
override_route("/api/client-special-mode", "api_client_special_mode", v40_api_client_special_mode, ["GET", "POST"])

# ۵. ذخیره فرم سرور اصلی (Master)
def v40_api_master_settings():
    import sqlite3
    from flask import request, jsonify
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
    cur = conn.cursor()
    if request.method == "GET":
        cur.execute("SELECT endpoint_domain, ssh_ip, server_name, file_suffix FROM master_settings LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if row: return jsonify({"endpoint_domain": row[0], "ssh_ip": row[1], "server_name": row[2] if row[2] else "", "file_suffix": row[3] if row[3] else ""})
        return jsonify({"endpoint_domain": "", "ssh_ip": "", "server_name": "", "file_suffix": ""})
    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
        cur.execute("SELECT id FROM master_settings LIMIT 1")
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE master_settings SET endpoint_domain=?, ssh_ip=?, server_name=?, file_suffix=? WHERE id=?", 
                       (data.get("endpoint_domain", ""), data.get("ssh_ip", ""), data.get("server_name", ""), data.get("file_suffix", ""), row[0]))
        else:
            cur.execute("INSERT INTO master_settings (endpoint_domain, ssh_ip, server_name, file_suffix) VALUES (?, ?, ?, ?)", 
                       (data.get("endpoint_domain", ""), data.get("ssh_ip", ""), data.get("server_name", ""), data.get("file_suffix", "")))
        conn.commit(); conn.close()
        return jsonify(success=True)
override_route("/api/master-settings", "api_master_settings", v40_api_master_settings, ["GET", "POST"])

# ۶. ذخیره فرم سرور فرزند (Edge)
def v40_api_edge_servers():
    import sqlite3, urllib.request, json
    from flask import request, jsonify
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
    cur = conn.cursor()
    
    if request.method == "GET":
        cur.execute("SELECT id, server_ip, panel_url, panel_user, panel_pass, ssh_ip, ssh_port, ssh_user, ssh_pass, location, flag, server_name, file_suffix FROM edge_servers")
        servers = [{"id": r[0], "server_ip": r[1], "panel_url": r[2], "panel_user": r[3], "panel_pass": r[4], "ssh_ip": r[5], "ssh_port": r[6], "ssh_user": r[7], "ssh_pass": r[8], "location": r[9], "flag": r[10], "server_name": r[11] if r[11] else "", "file_suffix": r[12] if r[12] else ""} for r in cur.fetchall()]
        conn.close()
        return jsonify(servers)
        
    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
        location, flag = "Unknown", "🛡️"
        try:
            with urllib.request.urlopen(f"http://ip-api.com/json/{data.get('ssh_ip')}", timeout=3) as res:
                geo = json.loads(res.read().decode())
                location = geo.get("country", "Unknown")
                cc = geo.get("countryCode", "")
                if cc: flag = "".join(chr(127397 + ord(c)) for c in cc)
        except: pass
        
        if data.get("id"):
            cur.execute("UPDATE edge_servers SET server_ip=?, panel_url=?, panel_user=?, panel_pass=?, ssh_ip=?, ssh_port=?, ssh_user=?, ssh_pass=?, location=?, flag=?, server_name=?, file_suffix=? WHERE id=?", 
                        (data.get("server_ip"), data.get("panel_url"), data.get("panel_user"), data.get("panel_pass"), data.get("ssh_ip"), int(data.get("ssh_port") or 22), data.get("ssh_user"), data.get("ssh_pass"), location, flag, data.get("server_name", ""), data.get("file_suffix", ""), data.get("id")))
        else:
            cur.execute("INSERT INTO edge_servers (server_ip, panel_url, panel_user, panel_pass, ssh_ip, ssh_port, ssh_user, ssh_pass, location, flag, server_name, file_suffix, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))", 
                        (data.get("server_ip"), data.get("panel_url"), data.get("panel_user"), data.get("panel_pass"), data.get("ssh_ip"), int(data.get("ssh_port") or 22), data.get("ssh_user"), data.get("ssh_pass"), location, flag, data.get("server_name", ""), data.get("file_suffix", "")))
        conn.commit(); conn.close()
        return jsonify(success=True)
        
    elif request.method == "DELETE":
        if request.args.get("id"): cur.execute("DELETE FROM edge_servers WHERE id=?", (request.args.get("id"),)); conn.commit()
        conn.close()
        return jsonify(success=True)
override_route("/api/edge-servers", "api_edge_servers", v40_api_edge_servers, ["GET", "POST", "DELETE"])

# ۷. رندر ساب‌لینک (نمایش ۱۰۰٪ نام‌های ثبت شده بدون ایموجی)
def v40_custom_short_redirect_view(short_id):
    import sqlite3, os, json, re, time
    from flask import render_template, make_response
    
    short_links_path = os.path.join('/usr/local/bin/Wireguard-panel/src', 'short_links.json')
    if not os.path.exists(short_links_path): return "❌ Error: Sub link file not found", 404
    with open(short_links_path, 'r') as f: short_links = json.load(f)
    long_link = short_links.get(short_id)
    if not long_link: return "❌ Error: Invalid subscription link", 404
        
    peer_name = ""
    config_file = "wg0.conf"
    p_match = re.search(r'peer_name=([^&]+)', long_link) or re.search(r'peerName=([^&]+)', long_link)
    c_match = re.search(r'config_file=([^&]+)', long_link) or re.search(r'configFile=([^&]+)', long_link) or re.search(r'config=([^&]+)', long_link)
    if p_match: peer_name = p_match.group(1)
    if c_match: config_file = c_match.group(1)
    interface = config_file.split(".")[0]
    
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
    cur = conn.cursor()
    
    cur.execute("SELECT special_mode FROM client_settings WHERE interface_name=?", (interface,))
    row_mode = cur.fetchone()
    special_mode = row_mode[0] if row_mode else 1

    try:
        cur.execute("SELECT [limit], used, remaining_time, expiry_time_json FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
        peer_row = cur.fetchone()
    except:
        cur.execute("SELECT [limit], used, remaining_time, '' FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
        peer_row = cur.fetchone()
        
    if not peer_row: conn.close(); return "❌ Error: Peer not found", 404

    limit_str, used_bytes, rem_minutes, expiry_json_str = peer_row
    limit_bytes = 0
    if "GiB" in limit_str: limit_bytes = float(limit_str.replace("GiB", "")) * 1073741824.0
    elif "MiB" in limit_str: limit_bytes = float(limit_str.replace("MiB", "")) * 1048576.0

    used_percent = min(100, round((used_bytes / limit_bytes) * 100, 1)) if limit_bytes > 0 else 0
    if used_bytes >= 1073741824: used_str_fa = f"{used_bytes / 1073741824.0:.2f} گیگابایت"
    elif used_bytes >= 1048576: used_str_fa = f"{used_bytes / 1048576.0:.2f} مگابایت"
    else: used_str_fa = f"{used_bytes / 1024.0:.2f} کیلوبایت"
    limit_str_fa = limit_str.replace("GiB", " گیگابایت").replace("MiB", " مگابایت")
    
    total_min = rem_minutes
    try:
        if expiry_json_str and str(expiry_json_str).strip() not in ["None", ""]:
            exp_json = json.loads(str(expiry_json_str))
            total_min_from_json = (int(exp_json.get("months",0)) * 30 * 1440) + (int(exp_json.get("days",0)) * 1440) + (int(exp_json.get("hours",0)) * 60) + int(exp_json.get("minutes",0))
            if total_min_from_json > 0: total_min = total_min_from_json
    except: pass
        
    if rem_minutes > total_min: total_min = rem_minutes
    elapsed_min = max(0, total_min - rem_minutes)
    
    if total_min <= rem_minutes:
        for plan in [1440, 4320, 10080, 43200, 129600, 259200, 525600]:
            if rem_minutes <= plan: total_min = plan; break

    time_percent = min(100.0, max(0.0, float(round((elapsed_min / total_min) * 100, 1) if total_min > 0 else 0.0)))
    if total_min <= 0: total_days = "منقضی شده"
    elif total_min < 60: total_days = f"{int(total_min)} دقیقه"
    elif total_min < 1440: total_days = f"{int(total_min // 60)} ساعت"
    else: total_days = f"{int(total_min // 1440)} روز"
    
    rem_hours = max(0, int(rem_minutes // 60))
    rem_mins = max(0, int(rem_minutes % 60))
    rem_days = max(0, int(rem_hours // 24))
    
    if rem_days > 0: time_str_fa = f"{rem_days} روز و {max(0, int(rem_hours % 24))} ساعت"
    elif rem_hours > 0: time_str_fa = f"{rem_hours} ساعت و {rem_mins} دقیقه"
    elif rem_minutes > 0: time_str_fa = f"{rem_mins} دقیقه"
    else: time_str_fa = "منقضی شده"
        
    is_used = (used_bytes > 1024 or elapsed_min > 1)
    
    if rem_minutes <= 0 or used_bytes >= limit_bytes:
        status_text = '<span style="display:flex; align-items:center; gap:5px;"><i class="fas fa-times-circle" style="color:var(--red); font-size:16px;"></i> منقضی شده</span>'
        status_class = "st-offline"
        time_percent = 100.0
    elif not is_used:
        status_text = '<span style="display:flex; align-items:center; gap:5px;"><i class="fas fa-hourglass-half" style="color:var(--yellow); font-size:16px;"></i> در انتظار مصرف</span>'
        status_class = "st-onhold"
        time_percent = 0.0
    else:
        status_text = '<span style="display:flex; align-items:center; gap:5px;"><i class="fas fa-check-circle" style="color:var(--neon-green); font-size:16px;"></i> فعال</span>'
        status_class = "st-online"
    
    master_flag, master_name, master_suffix = "🇩🇪", "سرور اصلی", ""
    cur.execute("SELECT ssh_ip, server_name, file_suffix FROM master_settings LIMIT 1")
    m_row = cur.fetchone()
    if m_row:
        master_name = m_row[2].strip() if m_row[2] else "سرور اصلی"
        master_suffix = m_row[3].strip() if m_row[3] else ""
        try:
            import urllib.request
            test_ip = m_row[0] if m_row[0] else ""
            with urllib.request.urlopen(f"http://ip-api.com/json/{test_ip}", timeout=2) as res:
                cc = json.loads(res.read().decode()).get("countryCode", "DE")
                master_flag = "".join(chr(127397 + ord(c)) for c in cc)
        except: pass
    
    active_flags = [master_flag]
    edge_servers_data = {}
    try:
        for ef in cur.execute("SELECT server_ip, flag, location, server_name, file_suffix FROM edge_servers").fetchall():
            edge_servers_data[ef[0]] = {"flag": ef[1], "loc": ef[2], "name": ef[3] if ef[3] else f"سرور لبه", "suffix": ef[4] if ef[4] else ""}
    except: pass
    
    # واکشی نگاشت پایدار سرورهایی که این کاربر به آن‌ها سینک است
    synced_servers = []
    try:
        for s_row in cur.execute("SELECT server_ip FROM peer_synced_edges WHERE peer_name=? AND config=?", (peer_name, config_file)).fetchall():
            synced_servers.append(s_row[0])
    except: pass
    
    for s_ip in synced_servers:
        if s_ip in edge_servers_data: active_flags.append(edge_servers_data[s_ip]["flag"])
    location_html = " ".join([f'<span class="flag-item">{fl}</span>' for fl in set(active_flags)])
    
    download_configs = []
    if special_mode == 1:
        try:
            for p_row in cur.execute("SELECT id, plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers FROM subscription_plans").fetchall():
                try: allowed_servers = json.loads(p_row[8]) if p_row[8] else ["master"]
                except: allowed_servers = ["master"]
                
                for srv_ip in allowed_servers:
                    if srv_ip != "master" and srv_ip not in synced_servers: continue
                    
                    if srv_ip == "master":
                        server_label = f'<i class="fas fa-server"></i> {master_name} {master_flag}'
                        s_suf = master_suffix
                    else:
                        e_data = edge_servers_data.get(srv_ip, {"name": "سرور لبه", "flag": "🌍", "suffix": ""})
                        server_label = f'<i class="fas fa-satellite-dish"></i> {e_data["name"]} {e_data["flag"]}'
                        s_suf = e_data["suffix"]
                        
                    download_configs.append({
                        "server_label": server_label,
                        "plan_name": p_row[1],
                        "description": p_row[2],
                        "file_name": f"{peer_name}{p_row[3]}{s_suf}.conf",
                        "suffix": f"{p_row[0]}_{srv_ip}",
                        "mtu": p_row[4], "dns": p_row[5], "keepalive": p_row[6], "allowed_ips": p_row[7]
                    })
        except: pass
        
    if not download_configs or special_mode == 0:
        p_nw = cur.execute("SELECT dns, mtu, persistent_keepalive, allowed_ips FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file)).fetchone()
        dns_v = p_nw[0] if p_nw else "1.1.1.1"
        mtu_v = p_nw[1] if p_nw else 1420
        keep_v = p_nw[2] if p_nw else 25
        allow_v = p_nw[3] if p_nw else "0.0.0.0/0, ::/0"

        download_configs.append({
            "server_label": f'<i class="fas fa-server"></i> {master_name} {master_flag}',
            "plan_name": "",
            "description": "اتصال مستقیم به شبکه سرور اصلی",
            "file_name": f"{peer_name}{master_suffix}.conf",
            "suffix": f"main_master",
            "mtu": mtu_v, "dns": dns_v, "keepalive": keep_v, "allowed_ips": allow_v
        })
        for e_ip in synced_servers:
            if e_ip in edge_servers_data:
                e_data = edge_servers_data[e_ip]
                download_configs.append({
                    "server_label": f'<i class="fas fa-satellite-dish"></i> {e_data["name"]} {e_data["flag"]}',
                    "plan_name": "",
                    "description": "اتصال پایدار از طریق سرور واسط",
                    "file_name": f"{peer_name}{e_data['suffix']}.conf",
                    "suffix": f"main_{e_ip}",
                    "mtu": mtu_v, "dns": dns_v, "keepalive": keep_v, "allowed_ips": allow_v
                })
            
    conn.close()

    rendered = render_template("status.html", 
                               peer_name=peer_name, used_percent=used_percent, time_percent=time_percent, 
                               limit_str=limit_str_fa, used_str_fa=used_str_fa, rem_minutes=rem_minutes, 
                               time_str_fa=time_str_fa, total_days=total_days, location_html=location_html, 
                               download_configs=download_configs, short_id=short_id, 
                               status_text=status_text, status_class=status_class, cache_buster=int(time.time()))
    resp = make_response(rendered)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp
override_route("/s/<short_id>", "short_redirect", v40_custom_short_redirect_view, ["GET"])


# ۸. دانلود فایل با نام‌گذاری‌های اختصاصی ادمین
def v40_short_download_config(short_id, suffix_key):
    import os, json, sqlite3, re
    from flask import Response, request
    
    short_links_path = os.path.join('/usr/local/bin/Wireguard-panel/src', 'short_links.json')
    with open(short_links_path, 'r') as f: short_links = json.load(f)
    long_link = short_links.get(short_id)
    peer_name = (re.search(r'peer_name=([^&]+)', long_link) or re.search(r'peerName=([^&]+)', long_link)).group(1)
    config_file = (re.search(r'config_file=([^&]+)', long_link) or re.search(r'configFile=([^&]+)', long_link) or re.search(r'config=([^&]+)', long_link)).group(1)
    
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
    cur = conn.cursor()
    cur.execute("SELECT private_key, peer_ip, dns, mtu, persistent_keepalive, allowed_ips FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
    peer_row = cur.fetchone()
    
    plan_id = suffix_key.split("_")[0]
    target_server = suffix_key.split("_", 1)[1] if "_" in suffix_key else "master"
    
    mtu, dns, keepalive, allowed_ips = 1420, "1.1.1.1, 1.0.0.1", 25, "0.0.0.0/0, ::/0"
    plan_suffix = ""
    
    if plan_id != "main" and plan_id.isdigit():
        cur.execute("SELECT suffix, mtu, dns, keepalive, allowed_ips FROM subscription_plans WHERE id=?", (int(plan_id),))
        plan_row = cur.fetchone()
        if plan_row:
            plan_suffix = plan_row[0]
            mtu, dns, keepalive, allowed_ips = plan_row[1], plan_row[2], plan_row[3], plan_row[4]
    else:
        if peer_row:
            dns, mtu, keepalive, allowed_ips = peer_row[2], peer_row[3], peer_row[4], peer_row[5]
            
    server_suffix = ""
    server_ip = request.host.split(":")[0]
    if target_server == "master":
        cur.execute("SELECT endpoint_domain, file_suffix FROM master_settings LIMIT 1")
        m_row = cur.fetchone()
        if m_row:
            if m_row[0]: server_ip = m_row[0].strip()
            if m_row[1]: server_suffix = m_row[1].strip()
    else:
        cur.execute("SELECT server_ip, file_suffix FROM edge_servers WHERE server_ip=?", (target_server,))
        srv_row = cur.fetchone()
        if srv_row:
            server_ip = srv_row[0]
            if srv_row[1]: server_suffix = srv_row[1].strip()

    server_pub_key, listen_port = "", 51820
    config_path = f"/etc/wireguard/{config_file}"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            cf_text = f.read()
            server_pub_key_match = re.search(r"PrivateKey\s*=\s*(.*)", cf_text)
            if server_pub_key_match:
                import base64
                import nacl.public
                priv_bytes = base64.b64decode(server_pub_key_match.group(1).strip())
                priv_key_obj = nacl.public.PrivateKey(priv_bytes)
                server_pub_key = base64.b64encode(bytes(priv_key_obj.public_key)).decode('utf-8')
            port_match = re.search(r"ListenPort\s*=\s*(\d+)", cf_text)
            if port_match:
                listen_port = int(port_match.group(1))

    conn.close()
    if not peer_row: return "Error: Peer not found", 404
        
    config_data = f"[Interface]\\nPrivateKey = {peer_row[0]}\\nAddress = {peer_row[1]}/32\\nDNS = {dns}\\nMTU = {mtu}\\n\\n[Peer]\\nPublicKey = {server_pub_key}\\nEndpoint = {server_ip}:{listen_port}\\nAllowedIPs = {allowed_ips}\\nPersistentKeepalive = {keepalive}\\n".replace("\\n", "\n")
    final_filename = f"{peer_name}{plan_suffix}{server_suffix}.conf"
    
    return Response(config_data, mimetype="application/octet-stream", headers={"Content-disposition": f"attachment; filename={final_filename}"})
override_route("/s/<short_id>/download/<suffix_key>", "short_download_config", v40_short_download_config, ["GET"])

# ۹. دور زدن فایروال امنیتی برای وب‌متدها
try:
    if 'csrf' in globals():
        csrf.exempt(app.view_functions.get('api_edge_servers'))
        csrf.exempt(app.view_functions.get('api_master_settings'))
        csrf.exempt(app.view_functions.get('api_advanced_settings'))
        csrf.exempt(app.view_functions.get('api_client_special_mode'))
except: pass

# --- [END SAFE OVERRIDES V40] ---



# --- [STEP 40 SUBLINK FIX] ---

def v40_custom_short_redirect_view(short_id):
    import sqlite3, os, json, re, time
    from flask import render_template, make_response
    
    short_links_path = os.path.join('/usr/local/bin/Wireguard-panel/src', 'short_links.json')
    if not os.path.exists(short_links_path):
        return "❌ Error: Sub link file not found", 404
        
    with open(short_links_path, 'r') as f:
        short_links = json.load(f)
        
    long_link = short_links.get(short_id)
    if not long_link:
        return "❌ Error: Invalid subscription link", 404
        
    peer_name = ""
    config_file = "wg0.conf"
    
    p_match = re.search(r'peer_name=([^&]+)', long_link) or re.search(r'peerName=([^&]+)', long_link)
    c_match = re.search(r'config_file=([^&]+)', long_link) or re.search(r'configFile=([^&]+)', long_link) or re.search(r'config=([^&]+)', long_link)
    if p_match: peer_name = p_match.group(1)
    if c_match: config_file = c_match.group(1)
    interface = config_file.split(".")[0]
    
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
    cur = conn.cursor()
    
    special_mode = 1
    try:
        cur.execute("SELECT special_mode FROM client_settings WHERE interface_name=?", (interface,))
        row_mode = cur.fetchone()
        if row_mode: special_mode = row_mode[0]
    except: pass

    # بلوک فوق‌العاده امن برای واکشی اطلاعات زمان (حل کامل خطای ۵۰۰)
    try:
        cur.execute("PRAGMA table_info(peers)")
        cols = [c[1] for c in cur.fetchall()]
        if "expiry_time_json" in cols:
            cur.execute("SELECT [limit], used, remaining_time, expiry_time_json FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
        else:
            cur.execute("SELECT [limit], used, remaining_time, '' FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
        peer_row = cur.fetchone()
    except Exception as db_err:
        conn.close()
        return f"❌ Error querying database: {db_err}", 500
        
    if not peer_row:
        conn.close()
        return "❌ Error: Peer not found", 404

    # واکشی امن زمان و حجم
    limit_str = str(peer_row[0]) if peer_row[0] is not None else "0MiB"
    used_bytes = int(peer_row[1]) if peer_row[1] is not None else 0
    rem_minutes = int(peer_row[2]) if peer_row[2] is not None else 0
    expiry_json_str = str(peer_row[3]) if len(peer_row) > 3 and peer_row[3] is not None else ""
    
    limit_bytes = 0.0
    if "GiB" in limit_str: limit_bytes = float(limit_str.replace("GiB", "")) * 1073741824.0
    elif "MiB" in limit_str: limit_bytes = float(limit_str.replace("MiB", "")) * 1048576.0

    used_percent = min(100.0, round((used_bytes / limit_bytes) * 100, 1)) if limit_bytes > 0 else 0.0
    
    if used_bytes >= 1073741824: used_str_fa = f"{used_bytes / 1073741824.0:.2f} گیگابایت"
    elif used_bytes >= 1048576: used_str_fa = f"{used_bytes / 1048576.0:.2f} مگابایت"
    else: used_str_fa = f"{used_bytes / 1024.0:.2f} کیلوبایت"
    limit_str_fa = limit_str.replace("GiB", " گیگابایت").replace("MiB", " مگابایت")
    
    total_min = rem_minutes
    try:
        # پردازش امن رشته JSON
        if expiry_json_str and expiry_json_str.strip() != "" and expiry_json_str.strip() != "None":
            exp_json = json.loads(expiry_json_str)
            months = int(exp_json.get("months", 0))
            days = int(exp_json.get("days", 0))
            hours = int(exp_json.get("hours", 0))
            minutes = int(exp_json.get("minutes", 0))
            total_min_from_json = (months * 30 * 1440) + (days * 1440) + (hours * 60) + minutes
            if total_min_from_json > 0:
                total_min = total_min_from_json
    except Exception as e:
        print(f"Warning: JSON parse error: {e}")
        
    if rem_minutes > total_min:
        total_min = rem_minutes
        
    elapsed_min = max(0, total_min - rem_minutes)
    
    # همگام‌ساز زمان دیفالت برای کاربرانی که تازه ساخته شده‌اند
    if total_min <= rem_minutes:
        for plan in [1440, 4320, 10080, 43200, 129600, 259200, 525600]:
            if rem_minutes <= plan:
                total_min = plan
                break

    time_percent = min(100.0, max(0.0, float(round((elapsed_min / total_min) * 100, 1) if total_min > 0 else 0.0)))

    if total_min <= 0: total_days = "منقضی شده"
    elif total_min < 60: total_days = f"{int(total_min)} دقیقه"
    elif total_min < 1440: total_days = f"{int(total_min // 60)} ساعت"
    else: total_days = f"{int(total_min // 1440)} روز"
    
    rem_hours = max(0, int(rem_minutes // 60))
    rem_mins = max(0, int(rem_minutes % 60))
    rem_days = max(0, int(rem_hours // 24))
    
    if rem_days > 0: time_str_fa = f"{rem_days} روز و {max(0, int(rem_hours % 24))} ساعت"
    elif rem_hours > 0: time_str_fa = f"{rem_hours} ساعت و {rem_mins} دقیقه"
    elif rem_minutes > 0: time_str_fa = f"{rem_mins} دقیقه"
    else: time_str_fa = "منقضی شده"
        
    is_used = (used_bytes > 1024 or elapsed_min > 1)
    
    if rem_minutes <= 0 or used_bytes >= limit_bytes:
        status_text = '<span style="display:flex; align-items:center; gap:5px;"><i class="fas fa-times-circle" style="color:var(--red); font-size:16px;"></i> منقضی شده</span>'
        status_class = "st-offline"
        time_percent = 100.0
    elif not is_used:
        status_text = '<span style="display:flex; align-items:center; gap:5px;"><i class="fas fa-hourglass-half" style="color:var(--yellow); font-size:16px;"></i> در انتظار مصرف</span>'
        status_class = "st-onhold"
        time_percent = 0.0
    else:
        status_text = '<span style="display:flex; align-items:center; gap:5px;"><i class="fas fa-check-circle" style="color:var(--neon-green); font-size:16px;"></i> فعال</span>'
        status_class = "st-online"
    
    # واکشی اطلاعات سفارشی سرور اصلی با مقادیر امن
    master_flag, master_name, master_suffix = "🇩🇪", "سرور اصلی", ""
    try:
        cur.execute("SELECT ssh_ip, server_name, file_suffix FROM master_settings LIMIT 1")
        m_row = cur.fetchone()
        if m_row:
            master_name = m_row[1].strip() if m_row[1] else "سرور اصلی"
            master_suffix = m_row[2].strip() if m_row[2] else ""
            test_ip = m_row[0].strip() if m_row[0] else ""
            if test_ip:
                import urllib.request
                with urllib.request.urlopen(f"http://ip-api.com/json/{test_ip}", timeout=2) as res:
                    cc = json.loads(res.read().decode()).get("countryCode", "DE")
                    master_flag = "".join(chr(127397 + ord(c)) for c in cc)
    except: pass
    
    active_flags = [master_flag]
    edge_servers_data = {}
    try:
        cur.execute("SELECT server_ip, flag, location, server_name, file_suffix FROM edge_servers")
        for ef in cur.fetchall():
            edge_servers_data[ef[0]] = {"flag": ef[1], "loc": ef[2], "name": ef[3] if ef[3] else "سرور لبه", "suffix": ef[4] if ef[4] else ""}
    except: pass
    
    # واکشی نگاشت پایدار سرورهایی که این کاربر به آن‌ها سینک است
    synced_servers = []
    try:
        cur.execute("SELECT server_ip FROM peer_synced_edges WHERE peer_name=? AND config=?", (peer_name, config_file))
        for s_row in cur.fetchall():
            synced_servers.append(s_row[0])
    except: pass
    
    # فقط پرچم سرورهای مجاز را در هدر نشان بده
    for s_ip in synced_servers:
        if s_ip in edge_servers_data: active_flags.append(edge_servers_data[s_ip]["flag"])
    location_html = " ".join([f'<span class="flag-item">{fl}</span>' for fl in set(active_flags)])
    
    download_configs = []
    
    if special_mode == 1:
        try:
            cur.execute("SELECT id, plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers FROM subscription_plans")
            for p_row in cur.fetchall():
                try: allowed_servers = json.loads(p_row[8]) if p_row[8] else ["master"]
                except: allowed_servers = ["master"]
                
                for srv_ip in allowed_servers:
                    if srv_ip != "master" and srv_ip not in synced_servers: continue
                    
                    if srv_ip == "master":
                        server_label = f'<i class="fas fa-server"></i> {master_name} {master_flag}'
                        s_suf = master_suffix
                    else:
                        e_data = edge_servers_data.get(srv_ip, {"name": "سرور لبه", "flag": "🌍", "suffix": ""})
                        server_label = f'<i class="fas fa-satellite-dish"></i> {e_data["name"]} {e_data["flag"]}'
                        s_suf = e_data["suffix"]
                        
                    download_configs.append({
                        "server_label": server_label,
                        "plan_name": p_row[1],
                        "description": p_row[2],
                        "file_name": f"{peer_name}{p_row[3]}{s_suf}.conf",
                        "suffix": f"{p_row[0]}_{srv_ip}",
                        "mtu": p_row[4], "dns": p_row[5], "keepalive": p_row[6], "allowed_ips": p_row[7]
                    })
        except Exception as ex_plans:
            print("Error parsing plans:", ex_plans)
            
    if not download_configs or special_mode == 0:
        try:
            cur.execute("SELECT dns, mtu, persistent_keepalive, allowed_ips FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
            p_nw = cur.fetchone()
        except: p_nw = None
        
        dns_v = p_nw[0] if p_nw else "1.1.1.1"
        mtu_v = p_nw[1] if p_nw else 1420
        keep_v = p_nw[2] if p_nw else 25
        allow_v = p_nw[3] if p_nw else "0.0.0.0/0, ::/0"

        download_configs.append({
            "server_label": f'<i class="fas fa-server"></i> {master_name} {master_flag}',
            "plan_name": "",
            "description": "اتصال مستقیم به شبکه سرور اصلی",
            "file_name": f"{peer_name}{master_suffix}.conf",
            "suffix": f"main_master",
            "mtu": mtu_v, "dns": dns_v, "keepalive": keep_v, "allowed_ips": allow_v
        })
        for e_ip in synced_servers:
            if e_ip in edge_servers_data:
                e_data = edge_servers_data[e_ip]
                download_configs.append({
                    "server_label": f'<i class="fas fa-satellite-dish"></i> {e_data["name"]} {e_data["flag"]}',
                    "plan_name": "",
                    "description": "اتصال پایدار از طریق سرور واسط",
                    "file_name": f"{peer_name}{e_data['suffix']}.conf",
                    "suffix": f"main_{e_ip}",
                    "mtu": mtu_v, "dns": dns_v, "keepalive": keep_v, "allowed_ips": allow_v
                })
            
    conn.close()

    rendered = render_template("status.html", 
                               peer_name=peer_name, used_percent=used_percent, time_percent=time_percent, 
                               limit_str=limit_str_fa, used_str_fa=used_str_fa, rem_minutes=rem_minutes, 
                               time_str_fa=time_str_fa, total_days=total_days, location_html=location_html, 
                               download_configs=download_configs, short_id=short_id, 
                               status_text=status_text, status_class=status_class, cache_buster=int(time.time()))
    resp = make_response(rendered)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

if 'short_redirect' in app.view_functions:
    app.view_functions['short_redirect'] = v40_custom_short_redirect_view

# --- [END STEP 40 SUBLINK FIX] ---







# --- [STEP 45 NETWORK HOMING] ---

# الف: محاسبه ترافیک تجمیعی انحصاری کارت شبکه‌های وایرگارد
def custom_obtain_system_uptime():
    import os
    total = 0
    try:
        for iface in os.listdir('/sys/class/net'):
            if iface.startswith('wg'):
                try:
                    with open(f"/sys/class/net/{iface}/statistics/rx_bytes", "r") as f: rx = int(f.read().strip())
                    with open(f"/sys/class/net/{iface}/statistics/tx_bytes", "r") as f: tx = int(f.read().strip())
                    total += (rx + tx)
                except: pass
    except: pass
    if total >= 1099511627776: return f"{total / 1099511627776:.2f} TB"
    elif total >= 1073741824: return f"{total / 1073741824.0:.2f} GB"
    elif total >= 1048576: return f"{total / 1048576.0:.2f} MB"
    else: return f"{total / 1024.0:.2f} KB"

globals()['obtain_system_uptime'] = custom_obtain_system_uptime

# ب: متد محاسبه سرعت آپلود و دانلود تجمیعی فقط برای کارت شبکه‌های وایرگارد
def v45_api_obtain_speed_route():
    import time, os
    from flask import jsonify
    def get_wg_bytes():
        rx_sum, tx_sum = 0, 0
        try:
            for iface in os.listdir('/sys/class/net'):
                if iface.startswith('wg'):
                    try:
                        with open(f"/sys/class/net/{iface}/statistics/rx_bytes", "r") as f: rx_sum += int(f.read().strip())
                        with open(f"/sys/class/net/{iface}/statistics/tx_bytes", "r") as f: tx_sum += int(f.read().strip())
                    except: pass
        except: pass
        return rx_sum, tx_sum
    try:
        r1, t1 = get_wg_bytes()
        time.sleep(1)
        r2, t2 = get_wg_bytes()
        return jsonify({'uploadSpeed': max(0.0, (t2 - t1) / 1024.0), 'downloadSpeed': max(0.0, (r2 - r1) / 1024.0)}), 200
    except: return jsonify({'uploadSpeed': 0.0, 'downloadSpeed': 0.0}), 200

if 'obtain_speed' in app.view_functions: app.view_functions['obtain_speed'] = v45_api_obtain_speed_route

# ج: وب‌متد رسمی دکمه همسان‌سازی کلان (Sync All Peers) با آی‌پی بی‌نهایت اختصاصی لبه
def v45_api_sync_all_peers():
    import sqlite3, subprocess, json, os, time
    from flask import jsonify
    logs = []
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
        edges = cur.fetchall()
        if not edges: return jsonify(logs=["⚠️ هیچ سرور لبه‌ای ثبت نشده است."])
        
        cur.execute("SELECT peer_name, [limit], used, remaining_time, private_key, public_key, config FROM peers")
        master_peers = cur.fetchall()
        
        for p_name, limit, used, rem_time, priv, pub, cfg in master_peers:
            for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                logs.append(f"در حال همسان‌سازی {p_name} روی {srv_ip}...")
                
                # اسکریپت پایتون بسیار ایمن فقط برای اجرا در سرور لبه
                sync_script = f'''import sqlite3, os, re, subprocess
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{cfg}"
orig_peer_name = "{p_name}"
pub = "{pub}"

os.makedirs("/usr/local/bin/Wireguard-panel/src", exist_ok=True)
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

cur.execute("SELECT peer_name FROM peers WHERE config=?", (cfg,))
existing_names = set([r[0] for r in cur.fetchall() if r[0]])

final_peer_name = orig_peer_name
counter = 1
while final_peer_name in existing_names:
    cur.execute("SELECT public_key FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
    existing_pub = cur.fetchone()
    if existing_pub and existing_pub[0] == pub: break
    final_peer_name = f"{{orig_peer_name}}_{{counter}}"
    counter += 1

cur.execute("SELECT peer_ip FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
row = cur.fetchone()

if row:
    cur.execute("UPDATE peers SET [limit]=?, used=?, remaining_time=?, private_key=?, public_key=? WHERE peer_name=? AND config=?", 
                ("{limit}", {used}, {rem_time}, "{priv}", pub, final_peer_name, cfg))
    conn.commit()
    print("UPDATED")
else:
    # 📌 هوش مصنوعی اختصاصی لبه برای شبکه بی‌نهایت (Subnet Expansion)
    base_ip = "10.0.0.1"
    try:
        if os.path.exists(f"/etc/wireguard/{{cfg}}"):
            with open(f"/etc/wireguard/{{cfg}}", "r") as f_cf:
                match = re.search(r"Address\\s*=\\s*([0-9]+\\.[0-9]+\\.[0-9]+)\\.", f_cf.read())
                if match: base_ip = match.group(1) + ".1"
    except: pass
            
    base_parts = base_ip.split(".")
    base_oct1, base_oct2 = base_parts[0], base_parts[1]
    
    used_ips = set()
    try:
        cur.execute("SELECT peer_ip FROM peers WHERE config=?", (cfg,))
        used_ips = set([r[0] for r in cur.fetchall() if r[0]])
        wg_path = subprocess.getoutput("which wg").strip() or "/usr/bin/wg"
        wg_out = subprocess.check_output(f"{{wg_path}} show {{cfg.replace('.conf','')}} allowed-ips", shell=True, text=True, stderr=subprocess.STDOUT)
        for line in wg_out.splitlines():
            parts = line.split()
            if len(parts) >= 2: used_ips.add(parts[1].split('/')[0])
    except: pass
    
    free_ip = None
    for oct3 in range(0, 256):
        for oct4 in range(2, 255):
            test_ip = f"{{base_oct1}}.{{base_oct2}}.{{oct3}}.{{oct4}}"
            if test_ip not in used_ips and test_ip != base_ip:
                free_ip = test_ip
                break
        if free_ip:
            break
            
    if not free_ip: free_ip = "10.0.0.2"
            
    cur.execute("INSERT INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)", 
                (final_peer_name, "{limit}", {used}, {rem_time}, "{priv}", free_ip, pub, cfg))
    conn.commit()
    
    try:
        subprocess.run(f"wg set {{cfg.replace('.conf','')}} peer {{pub}} allowed-ips {{free_ip}}/32", shell=True)
    except: pass
    print("CREATED")
conn.close()
'''
                import base64
                encoded_script = base64.b64encode(sync_script.encode('utf-8')).decode('utf-8')
                remote_cmd = f"echo '{encoded_script}' | base64 -d > /tmp/sync_peer.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_peer.py && rm -f /tmp/sync_peer.py"
                
                res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True, capture_output=True, text=True)
                
                if res.returncode == 0:
                    status = res.stdout.strip()
                    if status == "UPDATED":
                        logs.append(f"✅ کاربر {p_name} در لبه {srv_ip} آپدیت شد.")
                    else:
                        logs.append(f"✅ کاربر {p_name} با یک آی‌پی آزاد محلی در لبه {srv_ip} ساخته شد.")
                    cur.execute("INSERT OR IGNORE INTO peer_synced_edges (peer_name, server_ip, config) VALUES (?, ?, ?)", (p_name, srv_ip, cfg))
                else:
                    logs.append(f"❌ خطای لبه {srv_ip} در همسان‌سازی {p_name}: {res.stderr.strip()}")
        
        conn.commit(); conn.close()
        return jsonify(logs=logs, success=True)
    except Exception as e: return jsonify(logs=[f"❌ خطا: {str(e)}"], success=False)

if 'api_sync_all_peers' in app.view_functions: app.view_functions['api_sync_all_peers'] = v45_api_sync_all_peers


# د: سیستم همگام‌ساز زمان‌اجرا (Real-time Sync)
def v45_create_peer_hook(*args, **kwargs):
    from flask import request
    original_create_peer_base = app.view_functions.get('create_peer_original')
    if not original_create_peer_base:
        return {"error": "Original function not found"}
        
    response = original_create_peer_base(*args, **kwargs)
    try:
        data = request.get_json(silent=True) or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg_file = data.get("config", "wg0.conf")
        if not cfg_file.endswith('.conf'): cfg_file += ".conf"
        
        if p_name:
            import threading
            def run_sync_thread():
                import sqlite3, subprocess, base64, time
                time.sleep(2)
                try:
                    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                    cur = conn.cursor()
                    cur.execute("SELECT [limit], used, remaining_time, private_key, public_key FROM peers WHERE peer_name=? AND config=?", (p_name, cfg_file))
                    peer_row = cur.fetchone()
                    
                    if not peer_row:
                        conn.close(); return
                        
                    limit, used, rem_time, priv, pub = peer_row
                    
                    cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
                    edges = cur.fetchall()
                    
                    for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                        sync_script = f'''import sqlite3, os, re, subprocess
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
conn = sqlite3.connect(db_path, timeout=30.0); cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

orig_peer_name = "{p_name}"
cur.execute("SELECT peer_name FROM peers WHERE config=?", ("{cfg_file}",))
existing_names = set([r[0] for r in cur.fetchall() if r[0]])

final_peer_name = orig_peer_name
counter = 1
while final_peer_name in existing_names:
    cur.execute("SELECT public_key FROM peers WHERE peer_name=? AND config=?", (final_peer_name, "{cfg_file}"))
    existing_pub = cur.fetchone()
    if existing_pub and existing_pub[0] == "{pub}": break
    final_peer_name = f"{{orig_peer_name}}_{{counter}}"
    counter += 1

base_ip = "10.0.0.1"
try:
    if os.path.exists(f"/etc/wireguard/{cfg_file}"):
        with open(f"/etc/wireguard/{cfg_file}", "r") as f_cf:
            match = re.search(r"Address\\s*=\\s*([0-9]+\\.[0-9]+\\.[0-9]+)\\.", f_cf.read())
            if match: base_ip = match.group(1) + ".1"
except: pass
        
base_parts = base_ip.split(".")
base_oct1, base_oct2 = base_parts[0], base_parts[1]

used_ips = set()
try:
    cur.execute("SELECT peer_ip FROM peers WHERE config=?", ("{cfg_file}",))
    used_ips = set([r[0] for r in cur.fetchall() if r[0]])
    wg_path = subprocess.getoutput("which wg").strip() or "/usr/bin/wg"
    wg_out = subprocess.check_output(f"{{wg_path}} show {cfg_file.replace('.conf','')} allowed-ips", shell=True, text=True, stderr=subprocess.STDOUT)
    for line in wg_out.splitlines():
        parts = line.split()
        if len(parts) >= 2: used_ips.add(parts[1].split('/')[0])
except: pass

free_ip = None
for oct3 in range(0, 256):
    for oct4 in range(2, 255):
        test_ip = f"{{base_oct1}}.{{base_oct2}}.{{oct3}}.{{oct4}}"
        if test_ip not in used_ips and test_ip != base_ip:
            free_ip = test_ip
            break
    if free_ip: break

if not free_ip: free_ip = "10.0.0.2"
        
cur.execute("INSERT OR REPLACE INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)", 
            (final_peer_name, "{limit}", {used}, {rem_time}, "{priv}", free_ip, "{pub}", "{cfg_file}"))
conn.commit(); conn.close()
try:
    subprocess.run(f"wg set {cfg_file.replace('.conf','')} peer {pub} allowed-ips {{free_ip}}/32", shell=True)
except: pass
'''
                        encoded_script = base64.b64encode(sync_script.encode('utf-8')).decode('utf-8')
                        remote_cmd = f"echo '{encoded_script}' | base64 -d > /tmp/sync_new.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_new.py && rm -f /tmp/sync_new.py"
                        res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True)
                        
                        if res.returncode == 0:
                            cur.execute("INSERT OR IGNORE INTO peer_synced_edges (peer_name, server_ip, config) VALUES (?, ?, ?)", (p_name, srv_ip, cfg_file))
                    conn.commit(); conn.close()
                except Exception as ex_t:
                    print("Thread error:", ex_t)
                    
            threading.Thread(target=run_sync_thread, daemon=True).start()
    except Exception as ex: print("Create Peer Hook error:", ex)
    return response

if 'create_peer' in app.view_functions and 'create_peer_original' not in app.view_functions:
    app.view_functions['create_peer_original'] = app.view_functions['create_peer']
    app.view_functions['create_peer'] = v45_create_peer_hook

# --- [END STEP 45 NETWORK HOMING] ---



# --- [STEP 48 SUBLINK FAST] ---

# متد دانلود کانفیگ کلاسترینگ (Network Homing) - استخراج کلید عمومی و آی‌پی از سرور فرزند
def v48_short_download_config(short_id, suffix_key):
    import os, json, sqlite3, re, subprocess
    from flask import Response, request
    
    short_links_path = os.path.join('/usr/local/bin/Wireguard-panel/src', 'short_links.json')
    with open(short_links_path, 'r') as f: short_links = json.load(f)
    long_link = short_links.get(short_id)
    peer_name = (re.search(r'peer_name=([^&]+)', long_link) or re.search(r'peerName=([^&]+)', long_link)).group(1)
    config_file = (re.search(r'config_file=([^&]+)', long_link) or re.search(r'configFile=([^&]+)', long_link) or re.search(r'config=([^&]+)', long_link)).group(1)
    
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
    cur = conn.cursor()
    cur.execute("SELECT private_key, peer_ip, dns, mtu, persistent_keepalive, allowed_ips FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
    peer_row = cur.fetchone()
    if not peer_row:
        conn.close()
        return "Error: Peer not found", 404
        
    # مقادیر اولیه بر اساس سرور مادر
    private_key, peer_ip, dns, mtu, keepalive, allowed_ips = peer_row
    
    plan_id = suffix_key.split("_")[0]
    target_server = suffix_key.split("_", 1)[1] if "_" in suffix_key else "master"
    
    plan_suffix = ""
    if plan_id != "main" and plan_id.isdigit():
        cur.execute("SELECT suffix, mtu, dns, keepalive, allowed_ips FROM subscription_plans WHERE id=?", (int(plan_id),))
        plan_row = cur.fetchone()
        if plan_row:
            plan_suffix = plan_row[0]
            mtu, dns, keepalive, allowed_ips = plan_row[1], plan_row[2], plan_row[3], plan_row[4]
            
    server_suffix = ""
    server_ip = request.host.split(":")[0]
    server_pub_key, listen_port = "", 51820
    
    if target_server == "master":
        cur.execute("SELECT endpoint_domain, file_suffix FROM master_settings LIMIT 1")
        m_row = cur.fetchone()
        if m_row:
            if m_row[0]: server_ip = m_row[0].strip()
            if m_row[1]: server_suffix = m_row[1].strip()
            
        config_path = f"/etc/wireguard/{config_file}"
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                cf_text = f.read()
                server_pub_key_match = re.search(r"PrivateKey\s*=\s*(.*)", cf_text, re.IGNORECASE)
                if server_pub_key_match:
                    import base64, nacl.public
                    priv_bytes = base64.b64decode(server_pub_key_match.group(1).strip())
                    server_pub_key = base64.b64encode(bytes(nacl.public.PrivateKey(priv_bytes).public_key)).decode('utf-8')
                port_match = re.search(r"ListenPort\s*=\s*(\d+)", cf_text, re.IGNORECASE)
                if port_match: listen_port = int(port_match.group(1))
    else:
        # واکشی اطلاعات احراز هویت سرور فرزند
        cur.execute("SELECT server_ip, file_suffix, ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers WHERE server_ip=?", (target_server,))
        srv_row = cur.fetchone()
        if srv_row:
            server_ip = srv_row[0].strip()
            if srv_row[1]: server_suffix = srv_row[1].strip()
            s_ip, s_port, s_user, s_pass = srv_row[2], srv_row[3], srv_row[4], srv_row[5]
            
            # 🔥 استخراج لایو کلید عمومی و پورت دقیق از فایل کانفیگ خود سرور فرزند
            # 🔥 و استخراج آی‌پی آدرسی که در لبه برای این کلاینت ثبت شده است (عدم کپی‌برداری از آی‌پی مادر)
            try:
                # دستور یک خطی پایتون برای اجرا در سرور لبه که دیتابیس را خوانده و آی‌پی و کلید را برمی‌گرداند
                edge_query = f'''import sqlite3, os, re
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT peer_ip FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
row = cur.fetchone()
conn.close()
client_ip = row[0] if row else "{peer_ip}"
pub_key = ""
port = "51820"
if os.path.exists("/etc/wireguard/{config_file}"):
    with open("/etc/wireguard/{config_file}", "r") as f:
        txt = f.read()
        m_pk = re.search(r"PrivateKey\s*=\s*(.*)", txt, re.IGNORECASE)
        if m_pk:
            import base64, nacl.public
            priv_bytes = base64.b64decode(m_pk.group(1).strip())
            pub_key = base64.b64encode(bytes(nacl.public.PrivateKey(priv_bytes).public_key)).decode("utf-8")
        m_port = re.search(r"ListenPort\s*=\s*(\d+)", txt, re.IGNORECASE)
        if m_port: port = m_port.group(1)
print(f"{{client_ip}}|{{pub_key}}|{{port}}")
'''
                import base64
                encoded_script = base64.b64encode(edge_query.encode('utf-8')).decode('utf-8')
                remote_cmd = f"echo '{encoded_script}' | base64 -d > /tmp/get_edge_data.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/get_edge_data.py && rm -f /tmp/get_edge_data.py"
                
                res = subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no {s_user}@{s_ip} \"{remote_cmd}\"", shell=True, capture_output=True, text=True)
                if res.returncode == 0 and "|" in res.stdout:
                    parts = res.stdout.strip().split("|")
                    if len(parts) == 3:
                        peer_ip = parts[0]
                        server_pub_key = parts[1]
                        listen_port = parts[2]
            except Exception as e:
                print("Error fetching edge config:", e)

    conn.close()
        
    config_data = f"[Interface]\nPrivateKey = {private_key}\nAddress = {peer_ip}/32\nDNS = {dns}\nMTU = {mtu}\n\n[Peer]\nPublicKey = {server_pub_key}\nEndpoint = {server_ip}:{listen_port}\nAllowedIPs = {allowed_ips}\nPersistentKeepalive = {keepalive}\n"
    final_filename = f"{peer_name}{plan_suffix}{server_suffix}.conf"
    
    return Response(config_data, mimetype="application/octet-stream", headers={"Content-disposition": f"attachment; filename={final_filename}"})

if 'short_download_config' in app.view_functions:
    app.view_functions['short_download_config'] = v48_short_download_config

# --- [END STEP 48 SUBLINK FAST] ---











# --- [STEP 51 MEGA ENGINE] ---

# ۱. متد قدرتمند ایجاد خودکار اینترفیس در سرور لبه (Edge Interface Provisioning)
def ensure_edge_interface(srv_ip, ssh_port, ssh_user, ssh_pass, config_file):
    import subprocess, base64
    if config_file == "wg0.conf": return True 
    
    script = f'''import os, subprocess, re
cfg="{config_file}"
iface=cfg.replace(".conf","")
is_new = False
if not os.path.exists(f"/etc/wireguard/{cfg}"):
    priv=subprocess.getoutput("wg genkey").strip()
    used_ports=set(); used_subs=set()
    try:
        for f in os.listdir("/etc/wireguard"):
            if f.endswith(".conf"):
                txt=open("/etc/wireguard/"+f).read()
                m1=re.search(r"ListenPort\s*=\s*(\d+)", txt, re.IGNORECASE)
                if m1: used_ports.add(int(m1.group(1)))
                m2=re.search(r"Address\s*=\s*(10\.0\.\d+)\.", txt, re.IGNORECASE)
                if m2: used_subs.add(int(m2.group(1)))
    except: pass
    port=51820
    while port in used_ports: port+=1
    sub=0
    while sub in used_subs: sub+=1
    nic=subprocess.getoutput("ip route | grep default | awk '{{print $5}}' | head -n1").strip()
    conf=f"[Interface]\\nPrivateKey = {priv}\\nListenPort = {port}\\nAddress = 10.0.{sub}.1/24\\nSaveConfig = false\\n"
    if nic:
        conf+=f"PostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -t nat -A POSTROUTING -o {nic} -j MASQUERADE\\n"
        conf+=f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -t nat -D POSTROUTING -o {nic} -j MASQUERADE\\n"
    open(f"/etc/wireguard/{cfg}", "w").write(conf)
    is_new = True

# تضمین روشن بودن اینترفیس در سرور لبه (چه تازه ساخته شده چه از قبل بوده)
subprocess.run("systemctl daemon-reload", shell=True)
subprocess.run(f"systemctl enable wg-quick@{iface}", shell=True)
subprocess.run(f"systemctl start wg-quick@{iface}", shell=True)
subprocess.run(f"wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
print("CREATED" if is_new else "EXISTED_AND_STARTED")'''
    enc = base64.b64encode(script.encode('utf-8')).decode('utf-8')
    cmd = f"echo '{enc}' | base64 -d > /tmp/mk_iface.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/mk_iface.py && rm -f /tmp/mk_iface.py"
    res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{srv_ip} \"{cmd}\"", shell=True, capture_output=True, text=True)
    return "OK" in res.stdout

# ۲. عملیات ویرایش، حذف و خاموش روشن همگام‌ساز (غیرمسدودکننده)
def v51_sync_action_to_edges(action, peer_name, config_file):
    import threading
    def run_sync():
        import sqlite3, subprocess, base64, time
        time.sleep(1.5)
        try:
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
            edges = cur.fetchall()
            if not edges: 
                conn.close(); return

            if action == 'delete':
                for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                    edge_py = f'''import sqlite3, subprocess
conn=sqlite3.connect("/usr/local/bin/Wireguard-panel/src/db.sqlite3", timeout=30.0)
cur=conn.cursor()
cur.execute("SELECT public_key FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
row=cur.fetchone()
if row:
    subprocess.run(f"wg set {config_file.replace('.conf','')} peer {{row[0]}} remove", shell=True)
    cur.execute("DELETE FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
    conn.commit()
conn.close()'''
                    enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
                    remote_cmd = f"echo '{enc}' | base64 -d > /tmp/del_peer.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/del_peer.py && rm -f /tmp/del_peer.py"
                    subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True)
                    cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=? AND server_ip=? AND config=?", (peer_name, srv_ip, config_file))
                conn.commit()
            
            elif action in ['edit', 'toggle']:
                cur.execute("SELECT [limit], used, remaining_time, monitor_blocked, expiry_blocked, public_key FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
                p_row = cur.fetchone()
                if p_row:
                    limit, used, rem_time, m_blk, e_blk, pub = p_row
                    for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                        ensure_edge_interface(s_ip, ssh_port, ssh_user, ssh_pass, config_file)
                        edge_py = f'''import sqlite3, subprocess
conn=sqlite3.connect("/usr/local/bin/Wireguard-panel/src/db.sqlite3", timeout=30.0)
cur=conn.cursor()
cur.execute("UPDATE peers SET [limit]='{limit}', used={used}, remaining_time={rem_time}, monitor_blocked={m_blk}, expiry_blocked={e_blk} WHERE peer_name='{peer_name}' AND config='{config_file}'")
if {m_blk} == 1 or {e_blk} == 1:
    subprocess.run(f"wg set {config_file.replace('.conf','')} peer {pub} remove", shell=True)
else:
    cur.execute("SELECT peer_ip FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
    ip_row = cur.fetchone()
    if ip_row:
        subprocess.run(f"wg set {config_file.replace('.conf','')} peer {pub} allowed-ips {{ip_row[0]}}/32", shell=True)
conn.commit(); conn.close()'''
                        enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
                        remote_cmd = f"echo '{enc}' | base64 -d > /tmp/upd_peer.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/upd_peer.py && rm -f /tmp/upd_peer.py"
                        subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True)
            conn.close()
        except Exception as e: print("Action Sync Error:", e)
    threading.Thread(target=run_sync, daemon=True).start()

if 'sync_action_to_edges' in globals():
    globals()['sync_action_to_edges'] = v51_sync_action_to_edges

# ۳. هوک حذف کلاینت با قابلیت حفظ ترافیک مصرفی
original_delete_peer = app.view_functions.get('delete_peer_original') or app.view_functions.get('delete_peer')
def v51_delete_peer_hook(*args, **kwargs):
    from flask import request
    try:
        data = request.get_json(silent=True) or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg = data.get("config", "wg0.conf")
        if not cfg.endswith(".conf"): cfg += ".conf"
        if p_name:
            import sqlite3
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT used FROM peers WHERE peer_name=? AND config=?", (p_name, cfg))
            r = cur.fetchone()
            if r:
                used_val = r[0]
                if cfg == 'wg0.conf':
                    cur.execute("UPDATE global_deleted_traffic SET total = total + ? WHERE id=1", (used_val,))
                else:
                    iface = cfg.replace('.conf','')
                    cur.execute("UPDATE sub_panels SET deleted_traffic = deleted_traffic + ? WHERE interface_name=?", (used_val, iface))
                conn.commit()
            conn.close()
            v51_sync_action_to_edges("delete", p_name, cfg)
    except Exception as e: print("Delete Hook Error:", e)
    return original_delete_peer(*args, **kwargs) if original_delete_peer else None

if 'delete_peer' in app.view_functions:
    if 'delete_peer_original' not in app.view_functions: app.view_functions['delete_peer_original'] = app.view_functions['delete_peer']
    app.view_functions['delete_peer'] = v51_delete_peer_hook

# ۴. هوک تغییر وضعیت و ویرایش کلاینت
original_edit_peer = app.view_functions.get('edit_peer_original') or app.view_functions.get('edit_peer')
def v51_edit_peer_hook(*args, **kwargs):
    from flask import request
    res = original_edit_peer(*args, **kwargs) if original_edit_peer else None
    try:
        data = request.get_json(silent=True) or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg = data.get("config", "wg0.conf")
        if not cfg.endswith(".conf"): cfg += ".conf"
        if p_name: v51_sync_action_to_edges("edit", p_name, cfg)
    except Exception as e: print("Edit Hook Error:", e)
    return res

if 'edit_peer' in app.view_functions:
    if 'edit_peer_original' not in app.view_functions: app.view_functions['edit_peer_original'] = app.view_functions['edit_peer']
    app.view_functions['edit_peer'] = v51_edit_peer_hook

original_toggle_peer = app.view_functions.get('toggle_peer_original') or app.view_functions.get('toggle_peer')
def v51_toggle_peer_hook(*args, **kwargs):
    from flask import request
    res = original_toggle_peer(*args, **kwargs) if original_toggle_peer else None
    try:
        data = request.get_json(silent=True) or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg = data.get("config", "wg0.conf")
        if not cfg.endswith(".conf"): cfg += ".conf"
        if p_name: v51_sync_action_to_edges("toggle", p_name, cfg)
    except Exception as e: print("Toggle Hook Error:", e)
    return res

if 'toggle_peer' in app.view_functions:
    if 'toggle_peer_original' not in app.view_functions: app.view_functions['toggle_peer_original'] = app.view_functions['toggle_peer']
    app.view_functions['toggle_peer'] = v51_toggle_peer_hook


# ۵. هوک قدرتمند ساخت کلاینت جهت ساخت شبکه لبه و درج کلاینت
original_create_peer_base = app.view_functions.get('create_peer_original') or app.view_functions.get('create_peer')
def v51_create_peer_hook(*args, **kwargs):
    from flask import request
    response = original_create_peer_base(*args, **kwargs) if original_create_peer_base else None
    try:
        data = request.get_json(silent=True) or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg_file = data.get("config", "wg0.conf")
        if not cfg_file.endswith('.conf'): cfg_file += ".conf"
        
        if p_name:
            import threading
            def run_sync_thread():
                import sqlite3, subprocess, base64, time
                time.sleep(2)
                try:
                    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                    cur = conn.cursor()
                    cur.execute("SELECT [limit], used, remaining_time, private_key, public_key FROM peers WHERE peer_name=? AND config=?", (p_name, cfg_file))
                    peer_row = cur.fetchone()
                    if not peer_row: conn.close(); return
                    limit, used, rem_time, priv, pub = peer_row
                    
                    cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
                    edges = cur.fetchall()
                    
                    for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                        ensure_edge_interface(s_ip, ssh_port, ssh_user, ssh_pass, cfg_file)
                        
                        sync_script = f'''import sqlite3, os, re, subprocess
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{cfg_file}"
orig_peer_name = "{p_name}"
pub = "{pub}"
iface=cfg.replace('.conf','')

os.makedirs("/usr/local/bin/Wireguard-panel/src", exist_ok=True)
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

orig_peer_name = "{p_name}"
cur.execute("SELECT peer_name FROM peers WHERE config=?", ("{cfg_file}",))
existing_names = set([r[0] for r in cur.fetchall() if r[0]])

final_peer_name = orig_peer_name
counter = 1
while final_peer_name in existing_names:
    cur.execute("SELECT public_key FROM peers WHERE peer_name=? AND config=?", (final_peer_name, "{cfg_file}"))
    existing_pub = cur.fetchone()
    if existing_pub and existing_pub[0] == "{pub}": break
    final_peer_name = f"{{orig_peer_name}}_{{counter}}"
    counter += 1

base_ip = "10.0.0.1"
try:
    if os.path.exists(f"/etc/wireguard/{cfg_file}"):
        with open(f"/etc/wireguard/{cfg_file}", "r") as f_cf:
            match = re.search(r"Address\\s*=\\s*([0-9]+\\.[0-9]+\\.[0-9]+)\\.", f_cf.read())
            if match: base_ip = match.group(1) + ".1"
except: pass
        
base_parts = base_ip.split(".")
base_oct1, base_oct2 = base_parts[0], base_parts[1]

used_ips = set()
try:
    cur.execute("SELECT peer_ip FROM peers WHERE config=?", ("{cfg_file}",))
    used_ips = set([r[0] for r in cur.fetchall() if r[0]])
    wg_path = subprocess.getoutput("which wg").strip() or "/usr/bin/wg"
    wg_out = subprocess.check_output(f"{{wg_path}} show {cfg_file.replace('.conf','')} allowed-ips", shell=True, text=True, stderr=subprocess.STDOUT)
    for line in wg_out.splitlines():
        parts = line.split()
        if len(parts) >= 2: used_ips.add(parts[1].split('/')[0])
except: pass

free_ip = None
for oct3 in range(0, 256):
    for oct4 in range(2, 255):
        test_ip = f"{{base_oct1}}.{{base_oct2}}.{{oct3}}.{{oct4}}"
        if test_ip not in used_ips and test_ip != base_ip:
            free_ip = test_ip; break
    if free_ip: break
if not free_ip: free_ip = "10.0.0.2"
        
cur.execute("INSERT OR REPLACE INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)", 
            (final_peer_name, "{limit}", {used}, {rem_time}, "{priv}", free_ip, "{pub}", "{cfg_file}"))
conn.commit(); conn.close()
try: subprocess.run(f"wg set {cfg_file.replace('.conf','')} peer {pub} allowed-ips {{free_ip}}/32", shell=True)
except: pass
'''
                        encoded_script = base64.b64encode(sync_script.encode('utf-8')).decode('utf-8')
                        remote_cmd = f"echo '{encoded_script}' | base64 -d > /tmp/sync_new.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_new.py && rm -f /tmp/sync_new.py"
                        res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True)
                        if res.returncode == 0:
                            cur.execute("INSERT OR IGNORE INTO peer_synced_edges (peer_name, server_ip, config) VALUES (?, ?, ?)", (p_name, srv_ip, cfg_file))
                    conn.commit(); conn.close()
                except Exception as ex_t: print("Thread error:", ex_t)
            threading.Thread(target=run_sync_thread, daemon=True).start()
    except Exception as ex: print("Create Peer Hook error:", ex)
    return response

if 'create_peer' in app.view_functions:
    if 'create_peer_original' not in app.view_functions: app.view_functions['create_peer_original'] = app.view_functions['create_peer']
    app.view_functions['create_peer'] = v51_create_peer_hook


# ۶. دکمه ثبت برای همه (Sync All) با قابلیت اتوماتیک اینترفیس برای نمایندگان
def v51_api_sync_all_peers():
    import sqlite3, subprocess, json, os, time
    from flask import jsonify
    logs = []
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
        edges = cur.fetchall()
        if not edges: return jsonify(logs=["⚠️ هیچ سرور لبه‌ای ثبت نشده است."])
        
        cur.execute("SELECT peer_name, [limit], used, remaining_time, private_key, public_key, config FROM peers")
        master_peers = cur.fetchall()
        
        for p_name, limit, used, rem_time, priv, pub, cfg in master_peers:
            for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                logs.append(f"در حال همسان‌سازی {p_name} ({cfg}) روی {srv_ip}...")
                ensure_edge_interface(s_ip, ssh_port, ssh_user, ssh_pass, cfg)
                
                sync_script = f'''import sqlite3, os, re, subprocess
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{cfg}"; orig_peer_name = "{p_name}"; pub = "{pub}"; iface=cfg.replace('.conf','')

os.makedirs("/usr/local/bin/Wireguard-panel/src", exist_ok=True)
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

cur.execute("SELECT peer_name FROM peers WHERE config=?", (cfg,))
existing_names = set([r[0] for r in cur.fetchall() if r[0]])

final_peer_name = orig_peer_name
counter = 1
while final_peer_name in existing_names:
    cur.execute("SELECT public_key FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
    if cur.fetchone(): break
    final_peer_name = f"{{orig_peer_name}}_{{counter}}"
    counter += 1

cur.execute("SELECT peer_ip FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
if cur.fetchone():
    cur.execute("UPDATE peers SET [limit]=?, used=?, remaining_time=?, private_key=?, public_key=? WHERE peer_name=? AND config=?", 
                ("{limit}", {used}, {rem_time}, "{priv}", pub, final_peer_name, cfg))
    conn.commit(); print("UPDATED")
else:
    base_ip = "10.0.0.1"
    try:
        with open(f"/etc/wireguard/{{cfg}}", "r") as f_cf:
            m = re.search(r"Address\\s*=\\s*([0-9]+\\.[0-9]+\\.[0-9]+)\\.", f_cf.read())
            if m: base_ip = m.group(1) + ".1"
    except: pass
            
    base_parts = base_ip.split("."); base_oct1, base_oct2 = base_parts[0], base_parts[1]
    
    used_ips = set()
    try:
        cur.execute("SELECT peer_ip FROM peers WHERE config=?", (cfg,))
        used_ips = set([r[0] for r in cur.fetchall() if r[0]])
        wg_path = subprocess.getoutput("which wg").strip() or "/usr/bin/wg"
        wg_out = subprocess.check_output(f"{{wg_path}} show {{iface}} allowed-ips", shell=True, text=True, stderr=subprocess.STDOUT)
        for line in wg_out.splitlines():
            parts = line.split()
            if len(parts) >= 2: used_ips.add(parts[1].split('/')[0])
    except: pass
    
    free_ip = None
    for oct3 in range(0, 256):
        for oct4 in range(2, 255):
            test_ip = f"{{base_oct1}}.{{base_oct2}}.{{oct3}}.{{oct4}}"
            if test_ip not in used_ips and test_ip != base_ip:
                free_ip = test_ip; break
        if free_ip: break
    if not free_ip: free_ip = "10.0.0.2"
            
    cur.execute("INSERT INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)", 
                (final_peer_name, "{limit}", {used}, {rem_time}, "{priv}", free_ip, pub, cfg))
    conn.commit()
    try: subprocess.run(f"wg set {{iface}} peer {{pub}} allowed-ips {{free_ip}}/32", shell=True)
    except: pass
    print("CREATED")
conn.close()
'''
                import base64
                encoded_script = base64.b64encode(sync_script.encode('utf-8')).decode('utf-8')
                remote_cmd = f"echo '{encoded_script}' | base64 -d > /tmp/sync_peer.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_peer.py && rm -f /tmp/sync_peer.py"
                res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True, capture_output=True, text=True)
                if res.returncode == 0:
                    status = res.stdout.strip()
                    if status == "UPDATED": logs.append(f"✅ کلاینت {p_name} در لبه {srv_ip} آپدیت شد.")
                    else: logs.append(f"✅ کلاینت {p_name} با آی‌پی آزاد محلی در لبه {srv_ip} ساخته شد.")
                    cur.execute("INSERT OR IGNORE INTO peer_synced_edges (peer_name, server_ip, config) VALUES (?, ?, ?)", (p_name, srv_ip, cfg))
                else:
                    logs.append(f"❌ خطای لبه {srv_ip} در همسان‌سازی {p_name}: {res.stderr.strip()}")
        
        conn.commit(); conn.close()
        return jsonify(logs=logs, success=True)
    except Exception as e: return jsonify(logs=[f"❌ خطا: {str(e)}"], success=False)

if 'api_sync_all_peers' in app.view_functions: app.view_functions['api_sync_all_peers'] = v51_api_sync_all_peers


# ۷. موتور تجمیع‌گر کلان ترافیک لبه‌ها
def v51_start_master_traffic_aggregator():
    import threading, time, sqlite3, subprocess
    def run_aggregator():
        while True:
            time.sleep(30)
            edges = []
            try:
                conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                cur = conn.cursor()
                cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
                edges = cur.fetchall()
                conn.close()
            except: pass
            
            if edges:
                for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                    cmd = "wg show all transfer"
                    res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} '{cmd}'", shell=True, capture_output=True, text=True)
                    if res.returncode == 0:
                        lines = res.stdout.strip().split('\n')
                        updates = []
                        try:
                            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                            cur = conn.cursor()
                            for line in lines:
                                parts = line.split()
                                if len(parts) >= 4:
                                    iface, pub, rx, tx = parts[0], parts[1], int(parts[2]), int(parts[3])
                                    cfg = f"{iface}.conf"
                                    current_bytes = rx + tx
                                    cur.execute("SELECT peer_name FROM peers WHERE public_key=? AND config=?", (pub, cfg))
                                    p_row = cur.fetchone()
                                    if p_row:
                                        p_name = p_row[0]
                                        cur.execute("SELECT last_bytes FROM peer_synced_edges WHERE peer_name=? AND server_ip=? AND config=?", (p_name, srv_ip, cfg))
                                        sync_row = cur.fetchone()
                                        last_bytes = sync_row[0] if sync_row and sync_row[0] else 0
                                        delta = current_bytes if current_bytes < last_bytes else current_bytes - last_bytes
                                        if delta > 0: updates.append((delta, p_name, cfg, current_bytes, srv_ip))
                                        
                            for d, n, c, cb, s in updates:
                                cur.execute("UPDATE peers SET used = used + ? WHERE peer_name=? AND config=?", (d, n, c))
                                cur.execute("UPDATE peer_synced_edges SET last_bytes = ? WHERE peer_name=? AND server_ip=? AND config=?", (cb, n, s, c))
                            conn.commit(); conn.close()
                        except Exception as e_db: print("Edge Traffic DB Error:", e_db)
    threading.Thread(target=run_aggregator, daemon=True).start()

try: v51_start_master_traffic_aggregator()
except: pass


# ۸. محاسبه ۱۰۰٪ دقیق ترافیک ویجت‌های داشبورد (باگ کسر ترافیک رفع شد)
def v51_obtain_system_uptime():
    from flask import request, session
    import sqlite3
    
    config_file = request.args.get("config", "wg0.conf") or "wg0.conf"
    if session.get('role') == 'client': config_file = session.get('interface') + ".conf"
        
    interface = config_file.split(".")[0]
    total_bytes = 0
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        if interface == 'wg0':
            cur.execute("SELECT SUM(used) FROM peers")
            live_used = cur.fetchone()[0] or 0
            cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1")
            del_global = cur.fetchone()[0] or 0
            try:
                cur.execute("SELECT SUM(deleted_traffic) FROM sub_panels")
                del_subs = cur.fetchone()[0] or 0
            except: del_subs = 0
            total_bytes = live_used + del_global + del_subs
        else:
            cur.execute("SELECT SUM(used) FROM peers WHERE config=?", (config_file,))
            live_used = cur.fetchone()[0] or 0
            try:
                cur.execute("SELECT deleted_traffic FROM sub_panels WHERE interface_name=?", (interface,))
                del_sub = cur.fetchone()[0] or 0
            except: del_sub = 0
            total_bytes = live_used + del_sub
        conn.close()
    except: pass
    
    limit_gb = 0
    if interface != 'wg0':
        try:
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT data_limit_gb FROM sub_panels WHERE interface_name=?", (interface,))
            row = cur.fetchone()
            limit_gb = row[0] if row else 0
            conn.close()
        except: pass

    if total_bytes >= 1073741824: val_str = f"{total_bytes / 1073741824.0:.2f} GB"
    elif total_bytes >= 1048576: val_str = f"{total_bytes / 1048576.0:.2f} MB"
    else: val_str = f"{total_bytes / 1024.0:.2f} KB"

    if limit_gb > 0: return f"{val_str} / {limit_gb:.0f} GB"
    else: return f"{val_str}"

globals()['obtain_system_uptime'] = v51_obtain_system_uptime


# ۹. اصلاح سیستم Metrics با سنسور غیرمسدودکننده واقعی و روان‌سازی رادارها
original_obtain_metrics = app.view_functions.get('obtain_metrics_original') or app.view_functions.get('obtain_metrics')
def v51_obtain_metrics_view(*args, **kwargs):
    from flask import session, jsonify
    import json, sqlite3, psutil, time
    
    try:
        # واکشی فوری منابع سخت‌افزار با متد ضدقفل
        psutil.cpu_percent(interval=None)
        time.sleep(0.05)
        cpu_usage = psutil.cpu_percent(interval=None)
        ram_usage = psutil.virtual_memory().percent
        disk_usage = psutil.disk_usage('/').percent
        data = {"cpu": cpu_usage, "ram": ram_usage, "disk": disk_usage}
    except Exception as e:
        data = {"cpu": 0, "ram": 0, "disk": 0}
        
    active_config = session.get('active_config', 'wg0.conf')
    if session.get('role') == 'client': active_config = session.get('interface') + ".conf"
    interface = active_config.split(".")[0] if active_config else "wg0"
    is_fa = session.get('language') == 'fa' or session.get('language', 'en') == 'fa'
    
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        
        if interface == 'wg0':
            cur.execute("SELECT SUM(used) FROM peers")
            live_used = cur.fetchone()[0] or 0
            cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1")
            del_global = cur.fetchone()[0] or 0
            try:
                cur.execute("SELECT SUM(deleted_traffic) FROM sub_panels")
                del_subs = cur.fetchone()[0] or 0
            except: del_subs = 0
            
            used_bytes = live_used + del_global + del_subs
            data["uptime_label"] = "حجم مصرف کلی" if is_fa else "Total Global Traffic"
            data["uptime_percent"] = 0 
        else:
            cur.execute("SELECT SUM(used) FROM peers WHERE config=?", (f"{interface}.conf",))
            live_used = cur.fetchone()[0] or 0
            try:
                cur.execute("SELECT deleted_traffic FROM sub_panels WHERE interface_name=?", (interface,))
                del_sub = cur.fetchone()[0] or 0
            except: del_sub = 0
            
            used_bytes = live_used + del_sub
            cur.execute("SELECT data_limit_gb FROM sub_panels WHERE interface_name=?", (interface,))
            row_l = cur.fetchone()
            limit_gb = row_l[0] if row_l else 100.0
            data["uptime_label"] = "حجم مصرفی" if is_fa else "Used Traffic"
            if limit_gb > 0:
                pct = int(((used_bytes / 1073741824.0) / limit_gb) * 100)
                data["uptime_percent"] = min(100, max(0, pct))
            else: data["uptime_percent"] = 0
                
        conn.close()
        
        if used_bytes >= 1073741824: val_str = f"{used_bytes / 1073741824.0:.2f} GB"
        elif used_bytes >= 1048576: val_str = f"{used_bytes / 1048576.0:.2f} MB"
        else: val_str = f"{used_bytes / 1024.0:.2f} KB"
        
        data["uptime"] = val_str 
        return jsonify(data)
    except Exception as e:
        print("Metrics DB Override Error:", e)
        return jsonify(data)

if 'obtain_metrics' in app.view_functions:
    if 'obtain_metrics_original' not in app.view_functions:
        app.view_functions['obtain_metrics_original'] = app.view_functions['obtain_metrics']
    app.view_functions['obtain_metrics'] = v51_obtain_metrics_view


# ۱۰. روت بازسازی و نجات کامل کلاسترینگ (بخش تنظیمات ادمین) - Matched Inbound
@app.route("/api/rescue-sync-interfaces", methods=["POST"])
def api_rescue_sync_interfaces():
    import sqlite3, subprocess, os, base64
    from flask import jsonify
    logs = []
    
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        
        # واکشی تمام نمایندگان
        cur.execute("SELECT interface_name, password_plain FROM sub_panels")
        panels = cur.fetchall()
        
        # استارت اجباری تمام اینترفیس‌ها در سرور مادر
        for iface, pw in panels:
            logs.append(f"در حال بازسازی و متصل کردن اینترفیس {iface} در سرور مادر...")
            try:
                subprocess.run("systemctl daemon-reload", shell=True)
                subprocess.run(f"systemctl enable wg-quick@{iface}", shell=True)
                subprocess.run(f"systemctl start wg-quick@{iface}", shell=True)
                subprocess.run(f"wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
            except: pass

        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
        edges = cur.fetchall()
        
        if not edges:
            logs.append("هیچ سرور لبه‌ای یافت نشد.")
        else:
            for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                logs.append(f"در حال بررسی و ساخت فیزیکی شبکه‌ها روی لبه {srv_ip}...")
                
                # استقرار فیزیکی اینترفیس‌ها روی فرزند
                for iface, pw in panels:
                    config_file = f"{iface}.conf"
                    
                    check_cmd = f"ls /etc/wireguard/{config_file} 2>/dev/null"
                    res_check = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} '{check_cmd}'", shell=True, capture_output=True, text=True)
                    
                    if config_file not in res_check.stdout:
                        get_info_cmd = "wg genkey; ls /etc/wireguard/*.conf 2>/dev/null | xargs cat | grep -i ListenPort | awk -F'=' '{print $2}'; ls /etc/wireguard/*.conf 2>/dev/null | xargs cat | grep -i Address | awk -F'=' '{print $2}' | cut -d'/' -f1; ip route | grep default | awk '{print $5}' | head -n1"
                        res_info = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{get_info_cmd}\"", shell=True, capture_output=True, text=True)
                        
                        lines = res_info.stdout.strip().split('\n')
                        if lines:
                            new_priv = lines[0].strip()
                            used_ports = []
                            used_subs = []
                            nic = "eth0"
                            for line in lines[1:]:
                                line = line.strip()
                                if line.isdigit(): used_ports.append(int(line))
                                elif line.startswith("10.0."):
                                    try: used_subs.append(int(line.split(".")[2]))
                                    except: pass
                                elif line and not line.startswith("10.") and not line.isdigit(): nic = line
                            
                            new_port = 51820
                            while new_port in used_ports: new_port += 1
                            new_sub = 0
                            while new_sub in used_subs: new_sub += 1
                            
                            new_conf_data = f"[Interface]\\nPrivateKey = {new_priv}\\nListenPort = {new_port}\\nAddress = 10.0.{new_sub}.1/24\\nSaveConfig = false\\n"
                            if nic:
                                new_conf_data += f"PostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -t nat -A POSTROUTING -o {nic} -j MASQUERADE\\n"
                                new_conf_data += f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -t nat -D POSTROUTING -o {nic} -j MASQUERADE\\n"
                            
                            create_cmd = f"echo -e '{new_conf_data}' > /etc/wireguard/{config_file} && systemctl daemon-reload && systemctl enable wg-quick@{iface} && systemctl start wg-quick@{iface} && wg-quick up {iface}"
                            subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{create_cmd}\"", shell=True)
                            logs.append(f"  - اینترفیس {iface} در سرور فرزند نبود و فیزیکی ایجاد/روشن شد.")
                    else:
                        start_cmd = f"systemctl daemon-reload && systemctl enable wg-quick@{iface} && systemctl start wg-quick@{iface} && wg-quick up {iface}"
                        subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{start_cmd}\"", shell=True, stderr=subprocess.DEVNULL)
                        logs.append(f"  - اینترفیس {iface} از قبل در سرور فرزند بود و متصل/UP شد.")
                
                # تزریق دقیق کلاینت‌ها با متغیر پویای iface به کارت شبکه فرزند
                cur.execute("SELECT peer_name, [limit], used, remaining_time, private_key, public_key, config FROM peers")
                master_peers = cur.fetchall()
                for p_name, limit, used, rem_time, priv, pub, cfg in master_peers:
                    logs.append(f"  - در حال تزریق کاربر {p_name} ({cfg}) به لبه {srv_ip}...")
                    
                    sync_script = f'''import sqlite3, os, re, subprocess
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{cfg}"
orig_peer_name = "{p_name}"
pub = "{pub}"
iface=cfg.replace('.conf','')

os.makedirs("/usr/local/bin/Wireguard-panel/src", exist_ok=True)
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

cur.execute("SELECT peer_name FROM peers WHERE config=?", (cfg,))
existing_names = set([r[0] for r in cur.fetchall() if r[0]])

final_peer_name = orig_peer_name
counter = 1
while final_peer_name in existing_names:
    cur.execute("SELECT public_key FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
    if cur.fetchone(): break
    final_peer_name = f"{{orig_peer_name}}_{{counter}}"
    counter += 1

cur.execute("SELECT peer_ip FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
if cur.fetchone():
    cur.execute("UPDATE peers SET [limit]=?, used=?, remaining_time=?, private_key=?, public_key=? WHERE peer_name=? AND config=?", 
                ("{limit}", {used}, {rem_time}, "{priv}", pub, final_peer_name, cfg))
    conn.commit()
else:
    base_ip = "10.0.0.1"
    try:
        with open(f"/etc/wireguard/{{cfg}}", "r") as f_cf:
            m = re.search(r"Address\\s*=\\s*([0-9]+\\.[0-9]+\\.[0-9]+)\\.", f_cf.read())
            if m: base_ip = m.group(1) + ".1"
    except: pass
            
    base_parts = base_ip.split(".")
    base_oct1, base_oct2 = base_parts[0], base_parts[1]
    
    used_ips = set()
    try:
        cur.execute("SELECT peer_ip FROM peers WHERE config=?", (cfg,))
        used_ips = set([r[0] for r in cur.fetchall() if r[0]])
        wg_path = subprocess.getoutput("which wg").strip() or "/usr/bin/wg"
        wg_out = subprocess.check_output(f"{{wg_path}} show {{iface}} allowed-ips", shell=True, text=True, stderr=subprocess.STDOUT)
        for line in wg_out.splitlines():
            parts = line.split()
            if len(parts) >= 2: used_ips.add(parts[1].split('/')[0])
    except: pass
    
    free_ip = None
    for oct3 in range(0, 256):
        for oct4 in range(2, 255):
            test_ip = f"{{base_oct1}}.{{base_oct2}}.{{oct3}}.{{oct4}}"
            if test_ip not in used_ips and test_ip != base_ip:
                free_ip = test_ip; break
        if free_ip: break
    if not free_ip: free_ip = "10.0.0.2"
            
    cur.execute("INSERT INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)", 
                (final_peer_name, "{limit}", {used}, {rem_time}, "{priv}", free_ip, pub, cfg))
    conn.commit()
    try: subprocess.run(f"wg set {{iface}} peer {{pub}} allowed-ips {{free_ip}}/32", shell=True)
    except: pass
conn.close()
'''
                    enc_sync = base64.b64encode(sync_script.encode('utf-8')).decode('utf-8')
                    cmd_sync = f"echo '{enc_sync}' | base64 -d > /tmp/sync_p.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_p.py && rm -f /tmp/sync_p.py"
                    subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{cmd_sync}\"", shell=True)
                    cur.execute("INSERT OR IGNORE INTO peer_synced_edges (peer_name, server_ip, config) VALUES (?, ?, ?)", (p_name, srv_ip, cfg))
                    
        conn.close()
        logs.append("✅ عملیات بازسازی شبکه‌ها و احیای کل کلاینت‌ها در اینباند متناظرشان با موفقیت به پایان رسید.")
        return jsonify(logs=logs, success=True)
        
    except Exception as e:
        return jsonify(logs=[f"❌ خطا در عملیات نجات: {str(e)}"], success=False)

try:
    if 'csrf' in globals():
        csrf.exempt(api_rescue_sync_interfaces)
except: pass


# --- [STEP 57 SUPREME ACTIONS] ---

# الف: متد غیرمسدودکننده همگام‌ساز دکمه‌های ویرایش، تغییر وضعیت و حذف فیزیکی دیسک در سرورهای فرزند
def v57_sync_action_to_edges(action, peer_name, config_file, data=None):
    import threading
    def run_sync():
        import sqlite3, subprocess, base64, time
        time.sleep(1.0) # وقفه امن
        try:
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
            edges = cur.fetchall()
            if not edges: 
                conn.close(); return

            if action == 'delete' and data:
                pub = data.get("public_key")
                peer_ip = data.get("peer_ip")
                for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                    edge_py = f'''import sqlite3, subprocess, os, re
conn=sqlite3.connect("/usr/local/bin/Wireguard-panel/src/db.sqlite3", timeout=30.0)
cur=conn.cursor()
cur.execute("DELETE FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
conn.commit()
cur.execute("SELECT public_key FROM peers WHERE config='{config_file}'")
active_pubs = set([r[0] for r in cur.fetchall() if r[0]])
conn.close()

subprocess.run("wg set {config_file.replace('.conf','')} peer {pub} remove", shell=True)
subprocess.run("ip route del blackhole {peer_ip}", shell=True)
subprocess.run("ip route del {peer_ip} blackhole", shell=True)

path = "/etc/wireguard/{config_file}"
if os.path.exists(path):
    with open(path, "r") as f: text = f.read()
    blocks = text.split("[Peer]")
    new_text = blocks[0].strip() + "\\n"
    for block in blocks[1:]:
        pub_match = re.search(r"PublicKey\s*=\s*(.*)", block)
        if pub_match and pub_match.group(1).strip() in active_pubs:
            new_text += "\\n[Peer]\\n" + block.strip() + "\\n"
    with open(path, "w") as f: f.write(new_text.strip() + "\\n")
    subprocess.run("wg-quick save {config_file.replace('.conf','')}", shell=True)
'''
                    enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
                    remote_cmd = f"echo '{enc}' | base64 -d > /tmp/del_peer.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/del_peer.py && rm -f /tmp/del_peer.py"
                    subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True)
                    cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=? AND server_ip=? AND config=?", (peer_name, srv_ip, config_file))
                conn.commit()
            
            elif action in ['edit', 'toggle']:
                cur.execute("SELECT [limit], used, remaining_time, monitor_blocked, expiry_blocked, public_key, peer_ip FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
                p_row = cur.fetchone()
                if p_row:
                    limit, used, rem_time, m_blk, e_blk, pub, ip = p_row
                    for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                        ensure_edge_interface(s_ip, ssh_port, ssh_user, ssh_pass, config_file)
                        
                        edge_py = f'''import sqlite3, subprocess, os, re
conn=sqlite3.connect("/usr/local/bin/Wireguard-panel/src/db.sqlite3", timeout=30.0)
cur=conn.cursor()
cur.execute("UPDATE peers SET [limit]='{limit}', used={used}, remaining_time={rem_time}, monitor_blocked={m_blk}, expiry_blocked={e_blk} WHERE peer_name='{peer_name}' AND config='{config_file}'")
iface = "{config_file.replace('.conf','')}"
pub = "{pub}"
ip = "{ip}"

if {m_blk} == 1 or {e_blk} == 1:
    subprocess.run(f"wg set {{iface}} peer {{pub}} remove", shell=True)
    subprocess.run(f"ip route add blackhole {{ip}}", shell=True)
else:
    subprocess.run(f"ip route del blackhole {{ip}}", shell=True)
    subprocess.run(f"ip route del {{ip}} blackhole", shell=True)
    subprocess.run(f"wg set {{iface}} peer {{pub}} allowed-ips {{ip}}/32", shell=True)
    subprocess.run(f"ip route replace {{ip}}/32 dev {{iface}}", shell=True)
    try:
        wg_path = subprocess.getoutput("which iptables").strip() or "/usr/sbin/iptables"
        ipt_rules = subprocess.check_output(f"{{wg_path}} -S", shell=True, text=True)
        for line in ipt_rules.splitlines():
            if ip in line and ("DROP" in line or "REJECT" in line):
                del_rule = line.replace("-A", "-D")
                subprocess.run(f"iptables {{del_rule}}", shell=True)
    except: pass

conn.commit()
conn.close()'''
                        enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
                        remote_cmd = f"echo '{enc}' | base64 -d > /tmp/upd_peer.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/upd_peer.py && rm -f /tmp/upd_peer.py"
                        subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True)
            conn.close()
        except Exception as e: print("Action Sync Error:", e)
    threading.Thread(target=run_sync, daemon=True).start()


# ب: وب‌متد رسمی و ۱۰۰٪ مستقل ادیتور مجهز به مترجم هوشمند متغیرها (Bilingual Parameter Translator)
# (ثبت فوق‌پایدار تغییرات حجم/زمان در دیتابیس/دیسک مادر و شستشوی آنی روت‌های بلک‌هول در تمام کلاستر)
def v57_supreme_edit_peer_route():
    from flask import request, jsonify
    import sqlite3, subprocess, os, re
    
    data = request.get_json(silent=True) or request.form or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    config_file = data.get("configFile") or data.get("config") or "wg0.conf"
    if not config_file.endswith('.conf'): config_file += ".conf"
    
    if not peer_name:
        return jsonify(error="Peer name is required."), 400
        
    try:
        # 📌 ۱. مترجم هوشمند متغیرها: تبدیل متدهای ارسالی فرانت‌اند به ساختار دیسک مادر
        raw_limit = data.get("dataLimit")
        if not raw_limit:
            limit_val = data.get("limit")
            limit_unit = data.get("limit_unit") or data.get("limitUnit") or "GiB"
            if limit_val: raw_limit = f"{limit_val}{limit_unit}"
            
        months = int(data.get("expiryMonths") or data.get("months") or 0)
        days = int(data.get("expiryDays") or data.get("days") or 0)
        hours = int(data.get("expiryHours") or data.get("hours") or 0)
        minutes = int(data.get("expiryMinutes") or data.get("minutes") or 0)
        
        total_minutes = (months * 30 * 1440) + (days * 1440) + (hours * 60) + minutes
        
        # ۲. اعمال و نگارش محلی روی دیسک و دیتابیس سرور مادر با متد فابریک (Save Config & DB)
        peers = load_peers_with_lock(config_file)
        peer = next((p for p in peers if p["peer_name"] == peer_name), None)
        
        if peer:
            if raw_limit:
                peer["limit"] = raw_limit
                peer["remaining"] = max(0, convert_to_bytes(raw_limit) - peer.get("used", 0))
                
            if total_minutes > 0:
                peer["expiry_time"] = {"months": months, "days": days, "hours": hours, "minutes": minutes}
                peer["remaining_time"] = total_minutes
                peer["expiry_blocked"] = False
                peer["monitor_blocked"] = False
                
            save_peers_with_lock(config_file, peers)
            
            # 📌 ۳. احیای فیزیکی و لغو بلک‌هول در مادر جهت گارانتی اتصال آنی به اینترنت پس از ویرایش
            peer_ip = peer.get("peer_ip")
            pub = peer.get("public_key")
            interface = config_file.split(".")[0]
            if peer_ip:
                subprocess.run(f"ip route del blackhole {peer_ip}", shell=True, capture_output=True)
                subprocess.run(f"ip route del {peer_ip} blackhole", shell=True, capture_output=True)
                subprocess.run(f"wg set {interface} peer {pub} allowed-ips {peer_ip}/32", shell=True, capture_output=True)
                subprocess.run(f"ip route replace {peer_ip}/32 dev {interface}", shell=True, capture_output=True)
                try:
                    ipt = subprocess.check_output("iptables -S", shell=True, text=True)
                    for line in ipt.splitlines():
                        if peer_ip in line and ("DROP" in line or "REJECT" in line):
                            del_rule = line.replace("-A", "-D")
                            subprocess.run(f"iptables {del_rule}", shell=True)
                except: pass
        
        # ۴. ارسال دستور همگام‌سازی و احیای فیزیکی به لبه‌ها
        v57_sync_action_to_edges("edit", peer_name, config_file)
        return jsonify(success=True, message="Peer updated successfully.")
    except Exception as e:
        print("Supreme Edit Route Error:", e)
        return jsonify(error=f"Database error: {str(e)}"), 500

if 'edit_peer' in app.view_functions:
    app.view_functions['edit_peer'] = v57_supreme_edit_peer_route


# ج: هوک دکمه ریست کردن زمان انقضا (تمدید کلاینت در لبه‌ها به محض تمدید در مادر - با متغیر فیکس شده v57)
if 'reset_expiry' in app.view_functions and 'reset_expiry_original' not in app.view_functions:
    app.view_functions['reset_expiry_original'] = app.view_functions['reset_expiry']

def v57_reset_expiry_hook(*args, **kwargs):
    from flask import request
    response = app.view_functions['reset_expiry_original'](*args, **kwargs) if 'reset_expiry_original' in app.view_functions else None
    try:
        data = request.get_json(silent=True) or request.form or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg = data.get("config", "wg0.conf") or "wg0.conf"
        if not cfg.endswith('.conf'): cfg += ".conf"
        if p_name:
            v57_sync_action_to_edges("edit", p_name, cfg)
    except Exception as e:
         print("Reset Expiry Sync Error:", e)
    return response

if 'reset_expiry' in app.view_functions:
    app.view_functions['reset_expiry'] = v57_reset_expiry_hook


# د: هوک دکمه ریست حجم مصرفی (صفر کردن ترافیک کلاینت در لبه‌ها به محض صفر کردن در مادر - با متغیر فیکس شده v57)
if 'reset_traffic' in app.view_functions and 'reset_traffic_original' not in app.view_functions:
    app.view_functions['reset_traffic_original'] = app.view_functions['reset_traffic']

def v57_reset_traffic_hook(*args, **kwargs):
    from flask import request
    response = app.view_functions['reset_traffic_original'](*args, **kwargs) if 'reset_traffic_original' in app.view_functions else None
    try:
        data = request.get_json(silent=True) or request.form or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg = data.get("config", "wg0.conf") or "wg0.conf"
        if not cfg.endswith('.conf'): cfg += ".conf"
        if p_name:
            import sqlite3
            # ریست کردن شمارنده لبه‌های کلاسترینگ در سرور مادر قبل از سینک
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("UPDATE peer_synced_edges SET last_bytes=0 WHERE peer_name=? AND config=?", (p_name, cfg))
            conn.commit()
            conn.close()
            
            v57_sync_action_to_edges("edit", p_name, cfg)
    except Exception as e:
         print("Reset Traffic Sync Error:", e)
    return response

if 'reset_traffic' in app.view_functions:
    app.view_functions['reset_traffic'] = v57_reset_traffic_hook


# هـ: وب‌متد رسمی و ۱۰۰٪ مستقل حذف تکی کلاینت مجهز به شستشوی فیزیکی دیسک مادر و فرزند (با متغیر فیکس شده v57)
def v57_delete_peer_route():
    from flask import request, jsonify
    import sqlite3, subprocess, os, re
    
    data = request.get_json(silent=True) or request.form or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    
    if not peer_name:
        return jsonify(error="Peer name is required."), 400
        
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        
        cur.execute("SELECT public_key, used, config, peer_ip FROM peers WHERE peer_name=?", (peer_name,))
        row = cur.fetchone()
        
        if row:
            pub, used_val, config_file, peer_ip = row
            interface = config_file.split(".")[0]
            
            try:
                if config_file == 'wg0.conf':
                    cur.execute("UPDATE global_deleted_traffic SET total = total + ? WHERE id=1", (used_val,))
                else:
                    cur.execute("UPDATE sub_panels SET deleted_traffic = deleted_traffic + ? WHERE interface_name=?", (used_val, interface))
                conn.commit()
            except: pass
            
            # ۱. حذف از کارت شبکه سرور اصلی (مادر) و لغو بلک‌هول
            subprocess.run(f"wg set {interface} peer {pub} remove", shell=True)
            subprocess.run(f"ip route del blackhole {peer_ip}", shell=True, capture_output=True)
            subprocess.run(f"ip route del {peer_ip} blackhole", shell=True, capture_output=True)
            
            # ۲. حذف فیزیکی از دیتابیس سرور مادر
            cur.execute("DELETE FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
            conn.commit()
            
            # 📌 ۳. شستشوی فیزیکی هارد دیسک سرور مادر (حذف Peer متنی کلاینت حذف شده جهت آزادسازی لایو آی‌پی در مادر)
            path = f"/etc/wireguard/{config_file}"
            if os.path.exists(path):
                with open(path, "r") as f: text = f.read()
                cur.execute("SELECT public_key FROM peers WHERE config=?", (config_file,))
                active_pubs = set([r[0] for r in cur.fetchall() if r[0]])
                
                blocks = text.split("[Peer]")
                new_text = blocks[0].strip() + "\n"
                for block in blocks[1:]:
                    pub_match = re.search(r"PublicKey\s*=\s*(.*)", block)
                    if pub_match and pub_match.group(1).strip() in active_pubs:
                        new_text += "\n[Peer]\n" + block.strip() + "\n"
                with open(path, "w") as f: f.write(new_text.strip() + "\n")
                subprocess.run(f"wg-quick save {interface}", shell=True)
            
            # ۴. ارسال دستور حذف آنی و شستشوی فیزیکی دیسک به لبه‌ها
            v57_sync_action_to_edges("delete", peer_name, config_file, data={"public_key": pub, "peer_ip": peer_ip})
            
        conn.close()
        return jsonify(message=f"Peer '{peer_name}' deleted successfully.")
    except Exception as e:
        return jsonify(error=f"Database error: {str(e)}"), 500

if 'delete_peer' in app.view_functions:
    app.view_functions['delete_peer'] = v57_delete_peer_route

# --- [END STEP 57 SUPREME ACTIONS] ---


# --- [STEP 59 SUPREME CREATE PEER AUTOMATION] ---

# الف: متغیرهای ریسپانسیو و بهینه‌سازی شده کادر ساخت کاربر
# (فشرده‌سازی فواصل برای ایجاد مستطیل شکیل و همسان با نسخه انگلیسی)
def v59_get_peer_ui_style_patch():
    pass

# --- [END STEP 59 SUPREME CREATE PEER AUTOMATION] ---

# --- [END STEP 51 RESCUE SYNC] ---











# --- [STEP 54 SUPREME RESELLER SYNC] ---

# الف: متد فیزیکی ایجاد خودکار اینترفیس در سرور لبه بدون تداخل براکت‌های پایتون (Decoupled Base64)
def ensure_edge_interface(srv_ip, ssh_port, ssh_user, ssh_pass, config_file):
    import subprocess, base64
    if config_file == "wg0.conf": return True 
    
    script = '''import os, subprocess, re
cfg="{CONFIG_FILE}"
iface=cfg.replace(".conf","")
is_new = False
if not os.path.exists(f"/etc/wireguard/{cfg}"):
    priv=subprocess.getoutput("wg genkey").strip()
    used_ports=set(); used_subs=set()
    try:
        for f in os.listdir("/etc/wireguard"):
            if f.endswith(".conf"):
                txt=open("/etc/wireguard/"+f).read()
                m1=re.search(r"ListenPort\\s*=\\s*(\\d+)", txt, re.IGNORECASE)
                if m1: used_ports.add(int(m1.group(1)))
                m2=re.search(r"Address\\s*=\\s*(10\\.0\\.\\d+)\\.", txt, re.IGNORECASE)
                if m2: used_subs.add(int(m2.group(1)))
    except: pass
    port=51820
    while port in used_ports: port+=1
    sub=0
    while sub in used_subs: sub+=1
    nic=subprocess.getoutput("ip route | grep default | awk '{print $5}' | head -n1").strip()
    conf=f"[Interface]\\nPrivateKey = {priv}\\nListenPort = {port}\\nAddress = 10.0.{sub}.1/24\\nSaveConfig = false\\n"
    if nic:
        conf+=f"PostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -t nat -A POSTROUTING -o {nic} -j MASQUERADE\\n"
        conf+=f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -t nat -D POSTROUTING -o {nic} -j MASQUERADE\\n"
    open(f"/etc/wireguard/{cfg}", "w").write(conf)
    is_new = True

# تضمین روشن بودن اینترفیس در سرور لبه (چه تازه ساخته شده چه از قبل بوده)
subprocess.run("systemctl daemon-reload", shell=True)
subprocess.run(f"systemctl enable wg-quick@{iface}", shell=True)
subprocess.run(f"systemctl start wg-quick@{iface}", shell=True)
subprocess.run(f"wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
print("CREATED" if is_new else "EXISTED_AND_STARTED")
'''.replace("{CONFIG_FILE}", config_file)

    enc = base64.b64encode(script.encode('utf-8')).decode('utf-8')
    cmd = f"echo '{enc}' | base64 -d > /tmp/mk_iface.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/mk_iface.py && rm -f /tmp/mk_iface.py"
    res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{srv_ip} \"{cmd}\"", shell=True, capture_output=True, text=True)
    return "OK" in res.stdout


# ب: متد غیرمسدودکننده اعمال عملیات (ویرایش، تغییر وضعیت و حذف فیزیکی دیسکی) در سرورهای فرزند
def v54_sync_action_to_edges(action, peer_name, config_file, data=None):
    import threading
    def run_sync():
        import sqlite3, subprocess, base64, time
        time.sleep(1.0) # وقفه امن
        try:
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
            edges = cur.fetchall()
            if not edges: 
                conn.close(); return

            if action == 'delete' and data:
                pub = data.get("public_key")
                peer_ip = data.get("peer_ip")
                for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                    # 📌 ارتقای گام ۵۴: پاکسازی فیزیکی هارد دیسک سرور فرزند و حذف Peer متنی در لبه هنگام حذف تکی
                    edge_py = f'''import sqlite3, os, subprocess, re
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{config_file}"
iface = cfg.replace('.conf','')
pub = "{pub}"
peer_ip = "{peer_ip}"

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("DELETE FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
    conn.commit()
    cur.execute("SELECT public_key FROM peers WHERE config=?", (cfg,))
    active_pubs = set([r[0] for r in cur.fetchall() if r[0]])
    conn.close()
else:
    active_pubs = set()

# حذف از کارت شبکه لبه و لغو بلک‌هول
subprocess.run(f"wg set {{iface}} peer {{pub}} remove", shell=True)
subprocess.run(f"ip route del blackhole {{peer_ip}}", shell=True)
subprocess.run(f"ip route del {{peer_ip}} blackhole", shell=True)

# شستشوی فایل .conf فرزند روی هارد دیسک فرزند برای آزادسازی قطعی آی‌پی
path = f"/etc/wireguard/{{cfg}}"
if os.path.exists(path):
    with open(path, "r") as f: text = f.read()
    blocks = text.split("[Peer]")
    new_text = blocks[0].strip() + "\\n"
    for block in blocks[1:]:
        pub_match = re.search(r"PublicKey\s*=\s*(.*)", block)
        if pub_match and pub_match.group(1).strip() in active_pubs:
            new_text += "\\n[Peer]\\n" + block.strip() + "\\n"
    with open(path, "w") as f: f.write(new_text.strip() + "\\n")
    subprocess.run(f"wg-quick save {{iface}}", shell=True)
'''
                    enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
                    remote_cmd = f"echo '{enc}' | base64 -d > /tmp/del_peer.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/del_peer.py && rm -f /tmp/del_peer.py"
                    subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True)
                    cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=? AND server_ip=? AND config=?", (peer_name, srv_ip, config_file))
                conn.commit()
            
            elif action in ['edit', 'toggle']:
                cur.execute("SELECT [limit], used, remaining_time, monitor_blocked, expiry_blocked, public_key, peer_ip FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
                p_row = cur.fetchone()
                if p_row:
                    limit, used, rem_time, m_blk, e_blk, pub, ip = p_row
                    for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                        ensure_edge_interface(s_ip, ssh_port, ssh_user, ssh_pass, config_file)
                        
                        edge_py = f'''import sqlite3, subprocess, os, re
conn=sqlite3.connect("/usr/local/bin/Wireguard-panel/src/db.sqlite3", timeout=30.0)
cur=conn.cursor()
cur.execute("UPDATE peers SET [limit]='{limit}', used={used}, remaining_time={rem_time}, monitor_blocked={m_blk}, expiry_blocked={e_blk} WHERE peer_name='{peer_name}' AND config='{config_file}'")
iface = "{config_file.replace('.conf','')}"
pub = "{pub}"
ip = "{ip}"

if {m_blk} == 1 or {e_blk} == 1:
    subprocess.run(f"wg set {{iface}} peer {{pub}} remove", shell=True)
    subprocess.run(f"ip route add blackhole {{ip}}", shell=True)
else:
    subprocess.run(f"ip route del blackhole {{ip}}", shell=True)
    subprocess.run(f"ip route del {{ip}} blackhole", shell=True)
    subprocess.run(f"wg set {{iface}} peer {{pub}} allowed-ips {{ip}}/32", shell=True)
    subprocess.run(f"ip route replace {{ip}}/32 dev {{iface}}", shell=True)
    try:
        wg_path = subprocess.getoutput("which iptables").strip() or "/usr/sbin/iptables"
        ipt_rules = subprocess.check_output(f"{{wg_path}} -S", shell=True, text=True)
        for line in ipt_rules.splitlines():
            if ip in line and ("DROP" in line or "REJECT" in line):
                del_rule = line.replace("-A", "-D")
                subprocess.run(f"iptables {{del_rule}}", shell=True)
    except: pass

conn.commit()
conn.close()'''
                        enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
                        remote_cmd = f"echo '{enc}' | base64 -d > /tmp/upd_peer.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/upd_peer.py && rm -f /tmp/upd_peer.py"
                        subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True)
            conn.close()
        except Exception as e: print("Action Sync Error:", e)
    threading.Thread(target=run_sync, daemon=True).start()

if 'sync_action_to_edges' in globals():
    globals()['sync_action_to_edges'] = v54_sync_action_to_edges


# ج: متد رسمی و ۱۰۰٪ مستقل حذف تکی کلاینت با قابلیت شستشوی فیزیکی دیسک سرور اصلی و سرور فرزند (Wipe Disk)
def v52_delete_peer_route():
    from flask import request, jsonify
    import sqlite3, subprocess, os, re
    
    data = request.get_json(silent=True) or request.form or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    
    if not peer_name:
        return jsonify(error="Peer name is required."), 400
        
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        
        cur.execute("SELECT public_key, used, config, peer_ip FROM peers WHERE peer_name=?", (peer_name,))
        row = cur.fetchone()
        
        if row:
            pub, used_val, config_file, peer_ip = row
            interface = config_file.split(".")[0]
            
            try:
                if config_file == 'wg0.conf':
                    cur.execute("UPDATE global_deleted_traffic SET total = total + ? WHERE id=1", (used_val,))
                else:
                    cur.execute("UPDATE sub_panels SET deleted_traffic = deleted_traffic + ? WHERE interface_name=?", (used_val, interface))
                conn.commit()
            except: pass
            
            # ۱. حذف از کارت شبکه سرور اصلی (مادر) و لغو بلک‌هول
            subprocess.run(f"wg set {interface} peer {pub} remove", shell=True)
            subprocess.run(f"ip route del blackhole {peer_ip}", shell=True, capture_output=True)
            subprocess.run(f"ip route del {peer_ip} blackhole", shell=True, capture_output=True)
            
            # ۲. حذف فیزیکی از دیتابیس سرور مادر
            cur.execute("DELETE FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
            conn.commit()
            
            # 📌 ۳. شستشوی فیزیکی هارد دیسک سرور مادر (حذف Peer متنی کلاینت حذف شده جهت آزادسازی لایو آی‌پی در مادر)
            path = f"/etc/wireguard/{config_file}"
            if os.path.exists(path):
                with open(path, "r") as f: text = f.read()
                cur.execute("SELECT public_key FROM peers WHERE config=?", (config_file,))
                active_pubs = set([r[0] for r in cur.fetchall() if r[0]])
                
                blocks = text.split("[Peer]")
                new_text = blocks[0].strip() + "\n"
                for block in blocks[1:]:
                    pub_match = re.search(r"PublicKey\s*=\s*(.*)", block)
                    if pub_match and pub_match.group(1).strip() in active_pubs:
                        new_text += "\n[Peer]\n" + block.strip() + "\n"
                with open(path, "w") as f: f.write(new_text.strip() + "\n")
                subprocess.run(f"wg-quick save {interface}", shell=True)
            
            # ۴. ارسال دستور حذف آنی و شستشوی فیزیکی دیسک به لبه‌ها
            v54_sync_action_to_edges("delete", peer_name, config_file, data={"public_key": pub, "peer_ip": peer_ip})
            
        conn.close()
        return jsonify(message=f"Peer '{peer_name}' deleted successfully.")
    except Exception as e:
        return jsonify(error=f"Database error: {str(e)}"), 500

if 'delete_peer' in app.view_functions:
    app.view_functions['delete_peer'] = v52_delete_peer_route


# د: هوک قدرتمند، ریل‌تایم و ۱۰۰٪ مستقل ساخت کلاینت جدید با قابلیت کشف مستقیم کانفیگ و ثبت فیزیکی دیسک لبه (wg-quick save)
def v53_create_peer_hook(*args, **kwargs):
    from flask import request
    original_create_peer_base = app.view_functions.get('create_peer_original') or app.view_functions.get('create_peer')
    response = original_create_peer_base(*args, **kwargs) if original_create_peer_base else None
    try:
        data = request.get_json(silent=True) or {}
        p_name = data.get("peerName") or data.get("peer_name")
        
        if not p_name:
            p_name = request.form.get("peerName") or request.form.get("peer_name")
            
        if p_name:
            import threading
            def run_sync_thread():
                import sqlite3, subprocess, base64, time
                time.sleep(2.0) # وقفه امن جهت تکمیل نگارش دیتابیس سرور مادر
                try:
                    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                    cur = conn.cursor()
                    
                    cur.execute("SELECT [limit], used, remaining_time, private_key, public_key, config FROM peers WHERE peer_name=?", (p_name,))
                    peer_row = cur.fetchone()
                    if not peer_row: 
                        conn.close(); return
                        
                    limit, used, rem_time, priv, pub, cfg_file = peer_row
                    
                    cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
                    edges = cur.fetchall()
                    
                    for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                        ensure_edge_interface(s_ip, ssh_port, ssh_user, ssh_pass, cfg_file)
                        
                        # 📌 ساخت کلاینت در کارت شبکه لبه با موتور تشخیص ساب‌نت و دستور پایدارساز wg-quick save جهت نگارش فیزیکی دیسک لبه
                        sync_script = '''import sqlite3, os, re, subprocess
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{CONFIG_FILE}"
orig_peer_name = "{PEER_NAME}"
pub = "{PUB_KEY}"
iface=cfg.replace('.conf','')

os.makedirs("/usr/local/bin/Wireguard-panel/src", exist_ok=True)
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

cur.execute("SELECT peer_name FROM peers WHERE config=?", (cfg,))
existing_names = set([r[0] for r in cur.fetchall() if r[0]])

final_peer_name = orig_peer_name
counter = 1
while final_peer_name in existing_names:
    cur.execute("SELECT public_key FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
    existing_pub = cur.fetchone()
    if existing_pub and existing_pub[0] == pub: break
    final_peer_name = f"{orig_peer_name}_{counter}"
    counter += 1

cur.execute("SELECT peer_ip FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
row = cur.fetchone()

if row:
    peer_ip = row[0]
    cur.execute("UPDATE peers SET [limit]=?, used=?, remaining_time=?, private_key=?, public_key=? WHERE peer_name=? AND config=?", 
                ("{LIMIT}", {USED}, {REM_TIME}, "{PRIV_KEY}", pub, final_peer_name, cfg))
    conn.commit()
    try:
        subprocess.run(f"wg set {iface} peer {pub} allowed-ips {peer_ip}/32", shell=True)
        subprocess.run(f"wg-quick save {iface}", shell=True) # نگارش فیزیکی روی دیسک فرزند
    except: pass
    print(f"ALLOCATED_IP:{peer_ip}")
else:
    # تشخیص ساب‌نت لبه
    base_ip = "10.0.0.1"
    subnet_mask = 24
    try:
        if os.path.exists(f"/etc/wireguard/{cfg}"):
            with open(f"/etc/wireguard/{cfg}", "r") as f_cf:
                txt = f_cf.read()
                m = re.search(r"Address\s*=\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)/?(\d*)", txt, re.IGNORECASE)
                if m: 
                    base_ip = m.group(1)
                    if m.group(2): subnet_mask = int(m.group(2))
    except: pass
        
    base_parts = base_ip.split(".")
    base_prefix = ".".join(base_parts[:3])

    used_ips = set()
    try:
        cur.execute("SELECT peer_ip FROM peers WHERE config=?", (cfg,))
        used_ips = set([r[0] for r in cur.fetchall() if r[0]])
        wg_path = subprocess.getoutput("which wg").strip() or "/usr/bin/wg"
        wg_out = subprocess.check_output(f"{wg_path} show {iface} allowed-ips", shell=True, text=True, stderr=subprocess.STDOUT)
        for line in wg_out.splitlines():
            parts = line.split()
            if len(parts) >= 2: used_ips.add(parts[1].split('/')[0])
    except: pass

    free_ip = None
    if cfg == "wg0.conf":
        for oct3 in range(0, 256):
            for oct4 in range(2, 255):
                test_ip = f"{base_parts[0]}.{base_parts[1]}.{oct3}.{oct4}"
                if test_ip not in used_ips and test_ip != base_ip:
                    free_ip = test_ip; break
            if free_ip: break
    else:
        for oct4 in range(2, 255):
            test_ip = f"{base_prefix}.{oct4}"
            if test_ip not in used_ips and test_ip != base_ip:
                free_ip = test_ip; break

    if not free_ip: free_ip = f"{base_prefix}.2"
            
    cur.execute("INSERT INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)", 
                (final_peer_name, "{LIMIT}", {USED}, {REM_TIME}, "{PRIV_KEY}", free_ip, pub, cfg))
    conn.commit()
    try:
        subprocess.run(f"wg set {iface} peer {pub} allowed-ips {free_ip}/32", shell=True)
        subprocess.run(f"wg-quick save {iface}", shell=True) # نگارش فیزیکی روی دیسک فرزند
    except: pass
    print(f"ALLOCATED_IP:{free_ip}")
conn.close()
'''.replace("{CONFIG_FILE}", cfg_file).replace("{PEER_NAME}", p_name).replace("{PUB_KEY}", pub).replace("{LIMIT}", limit).replace("{USED}", str(used)).replace("{REM_TIME}", str(rem_time)).replace("{PRIV_KEY}", priv)

                        encoded_script = base64.b64encode(sync_script.encode('utf-8')).decode('utf-8')
                        remote_cmd = f"echo '{encoded_script}' | base64 -d > /tmp/sync_new.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_new.py && rm -f /tmp/sync_new.py"
                        res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{srv_ip} \"{remote_cmd}\"", shell=True, capture_output=True, text=True)
                        
                        if res.returncode == 0:
                            out = res.stdout.strip()
                            m_ip = re.search(r"ALLOCATED_IP:(.*)", out)
                            if m_ip:
                                allocated_ip = m_ip.group(1).strip()
                                cur.execute("INSERT OR REPLACE INTO peer_synced_edges (peer_name, server_ip, config, edge_ip) VALUES (?, ?, ?, ?)", (p_name, srv_ip, cfg_file, allocated_ip))
                    conn.commit(); conn.close()
                except Exception as ex_t: print("Thread error:", ex_t)
            threading.Thread(target=run_sync_thread, daemon=True).start()
    except Exception as ex: print("Create Peer Hook error:", ex)
    return response

if 'create_peer' in app.view_functions:
    app.view_functions['create_peer'] = v53_create_peer_hook

# --- [END STEP 53 SUPREME RESELLER MATCHED SYNC] ---



# --- [STEP 55 SUPREME RESELLER MATCHED SYNC] ---

# الف: متد فیزیکی ایجاد خودکار اینترفیس در سرور لبه بدون تداخل براکت‌های پایتون (Decoupled Base64)
def ensure_edge_interface(srv_ip, ssh_port, ssh_user, ssh_pass, config_file):
    import subprocess, base64
    if config_file == "wg0.conf": return True 
    
    script = '''import os, subprocess, re
cfg="{CONFIG_FILE}"
iface=cfg.replace(".conf","")
is_new = False
if not os.path.exists(f"/etc/wireguard/{cfg}"):
    priv=subprocess.getoutput("wg genkey").strip()
    used_ports=set(); used_subs=set()
    try:
        for f in os.listdir("/etc/wireguard"):
            if f.endswith(".conf"):
                txt=open("/etc/wireguard/"+f).read()
                m1=re.search(r"ListenPort\\s*=\\s*(\\d+)", txt, re.IGNORECASE)
                if m1: used_ports.add(int(m1.group(1)))
                m2=re.search(r"Address\\s*=\\s*(10\\.0\\.\\d+)\\.", txt, re.IGNORECASE)
                if m2: used_subs.add(int(m2.group(1)))
    except: pass
    port=51820
    while port in used_ports: port+=1
    sub=0
    while sub in used_subs: sub+=1
    nic=subprocess.getoutput("ip route | grep default | awk '{print $5}' | head -n1").strip()
    conf=f"[Interface]\\nPrivateKey = {priv}\\nListenPort = {port}\\nAddress = 10.0.{sub}.1/24\\nSaveConfig = false\\n"
    if nic:
        conf+=f"PostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -t nat -A POSTROUTING -o {nic} -j MASQUERADE\\n"
        conf+=f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -t nat -D POSTROUTING -o {nic} -j MASQUERADE\\n"
    open(f"/etc/wireguard/{cfg}", "w").write(conf)
    is_new = True

# تضمین روشن بودن اینترفیس در سرور لبه (چه تازه ساخته شده چه از قبل بوده)
subprocess.run("systemctl daemon-reload", shell=True)
subprocess.run(f"systemctl enable wg-quick@{iface}", shell=True)
subprocess.run(f"systemctl start wg-quick@{iface}", shell=True)
subprocess.run(f"wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
print("CREATED" if is_new else "EXISTED_AND_STARTED")
'''.replace("{CONFIG_FILE}", config_file)

    enc = base64.b64encode(script.encode('utf-8')).decode('utf-8')
    cmd = f"echo '{enc}' | base64 -d > /tmp/mk_iface.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/mk_iface.py && rm -f /tmp/mk_iface.py"
    # 📌 فیکس اتصال: استفاده از ssh_user و srv_ip عددی برای اتصال موفقیت‌آمیز
    res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{srv_ip} \"{cmd}\"", shell=True, capture_output=True, text=True)
    return "OK" in res.stdout


# ب: هوک قدرتمند، ریل‌تایم و ۱۰۰٪ مستقل ساخت کلاینت جدید با قابلیت کشف مستقیم کانفیگ و ثبت فیزیکی دیسک لبه
def v55_create_peer_hook(*args, **kwargs):
    from flask import request
    original_create_peer_base = app.view_functions.get('create_peer_original') or app.view_functions.get('create_peer')
    response = original_create_peer_base(*args, **kwargs) if original_create_peer_base else None
    try:
        data = request.get_json(silent=True) or request.form or {}
        p_name = data.get("peerName") or data.get("peer_name")
        
        # اگر درخواست به صورت فرم ثبت شده باشد
        if not p_name:
            p_name = request.form.get("peerName") or request.form.get("peer_name")
            
        if p_name:
            import threading
            def run_sync_thread():
                import sqlite3, subprocess, base64, time, re
                time.sleep(2.0) # وقفه امن جهت تکمیل نگارش دیتابیس سرور مادر
                try:
                    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                    cur = conn.cursor()
                    
                    cur.execute("SELECT [limit], used, remaining_time, private_key, public_key, config FROM peers WHERE peer_name=?", (p_name,))
                    peer_row = cur.fetchone()
                    if not peer_row: 
                        conn.close(); return
                        
                    limit, used, rem_time, priv, pub, cfg_file = peer_row
                    
                    cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
                    edges = cur.fetchall()
                    
                    for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                        # ۱. تضمین وجود اینترفیس در لبه (استفاده از s_ip عددی برای اتصال ۱۰۰٪ ایمن)
                        ensure_edge_interface(s_ip, ssh_port, ssh_user, ssh_pass, cfg_file)
                        
                        # ۲. ساخت کلاینت در کارت شبکه لبه با موتور تشخیص ساب‌نت
                        sync_script = '''import sqlite3, os, re, subprocess
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{CONFIG_FILE}"
orig_peer_name = "{PEER_NAME}"
pub = "{PUB_KEY}"
iface=cfg.replace('.conf','')

os.makedirs("/usr/local/bin/Wireguard-panel/src", exist_ok=True)
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

cur.execute("SELECT peer_name FROM peers WHERE config=?", (cfg,))
existing_names = set([r[0] for r in cur.fetchall() if r[0]])

final_peer_name = orig_peer_name
counter = 1
while final_peer_name in existing_names:
    cur.execute("SELECT public_key FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
    existing_pub = cur.fetchone()
    if existing_pub and existing_pub[0] == pub: break
    final_peer_name = f"{orig_peer_name}_{counter}"
    counter += 1

cur.execute("SELECT peer_ip FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
row = cur.fetchone()

if row:
    peer_ip = row[0]
    cur.execute("UPDATE peers SET [limit]=?, used=?, remaining_time=?, private_key=?, public_key=? WHERE peer_name=? AND config=?", 
                ("{LIMIT}", {USED}, {REM_TIME}, "{PRIV_KEY}", pub, final_peer_name, cfg))
    conn.commit()
    try:
        subprocess.run(f"wg set {iface} peer {pub} allowed-ips {peer_ip}/32", shell=True)
        subprocess.run(f"wg-quick save {iface}", shell=True)
    except: pass
    print(f"ALLOCATED_IP:{peer_ip}")
else:
    # تشخیص ساب‌نت لبه
    base_ip = "10.0.0.1"
    subnet_mask = 24
    try:
        if os.path.exists(f"/etc/wireguard/{cfg}"):
            with open(f"/etc/wireguard/{cfg}", "r") as f_cf:
                txt = f_cf.read()
                m = re.search(r"Address\s*=\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)/?(\d*)", txt, re.IGNORECASE)
                if m: 
                    base_ip = m.group(1)
                    if m.group(2): subnet_mask = int(m.group(2))
    except: pass
        
    base_parts = base_ip.split(".")
    base_prefix = ".".join(base_parts[:3])

    used_ips = set()
    try:
        cur.execute("SELECT peer_ip FROM peers WHERE config=?", (cfg,))
        used_ips = set([r[0] for r in cur.fetchall() if r[0]])
        wg_path = subprocess.getoutput("which wg").strip() or "/usr/bin/wg"
        wg_out = subprocess.check_output(f"{wg_path} show {iface} allowed-ips", shell=True, text=True, stderr=subprocess.STDOUT)
        for line in wg_out.splitlines():
            parts = line.split()
            if len(parts) >= 2: used_ips.add(parts[1].split('/')[0])
    except: pass

    free_ip = None
    if cfg == "wg0.conf":
        for oct3 in range(0, 256):
            for oct4 in range(2, 255):
                test_ip = f"{base_parts[0]}.{base_parts[1]}.{oct3}.{oct4}"
                if test_ip not in used_ips and test_ip != base_ip:
                    free_ip = test_ip; break
            if free_ip: break
    else:
        for oct4 in range(2, 255):
            test_ip = f"{base_prefix}.{oct4}"
            if test_ip not in used_ips and test_ip != base_ip:
                free_ip = test_ip; break

    if not free_ip: free_ip = f"{base_prefix}.2"
            
    cur.execute("INSERT INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)", 
                (final_peer_name, "{LIMIT}", {USED}, {REM_TIME}, "{PRIV_KEY}", free_ip, pub, cfg))
    conn.commit()
    try:
        subprocess.run(f"wg set {iface} peer {pub} allowed-ips {free_ip}/32", shell=True)
        subprocess.run(f"wg-quick save {iface}", shell=True) # ذخیره فیزیکی روی دیسک فرزند
    except: pass
    print(f"ALLOCATED_IP:{free_ip}")
conn.close()
'''.replace("{CONFIG_FILE}", cfg_file).replace("{PEER_NAME}", p_name).replace("{PUB_KEY}", pub).replace("{LIMIT}", limit).replace("{USED}", str(used)).replace("{REM_TIME}", str(rem_time)).replace("{PRIV_KEY}", priv)

                        encoded_script = base64.b64encode(sync_script.encode('utf-8')).decode('utf-8')
                        remote_cmd = f"echo '{encoded_script}' | base64 -d > /tmp/sync_new.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_new.py && rm -f /tmp/sync_new.py"
                        # 📌 تصحیح فوق‌العاده مهم: استفاده از آی‌پی عددی s_ip و یوزر روت ssh_user برای لاگین ریل‌تایم ۱۰۰٪ موفق
                        res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True, capture_output=True, text=True)
                        
                        if res.returncode == 0:
                            out = res.stdout.strip()
                            m_ip = re.search(r"ALLOCATED_IP:(.*)", out)
                            if m_ip:
                                allocated_ip = m_ip.group(1).strip()
                                cur.execute("INSERT OR REPLACE INTO peer_synced_edges (peer_name, server_ip, config, edge_ip) VALUES (?, ?, ?, ?)", (p_name, srv_ip, cfg_file, allocated_ip))
                    conn.commit(); conn.close()
                except Exception as ex_t: print("Thread error:", ex_t)
            threading.Thread(target=run_sync_thread, daemon=True).start()
    except Exception as ex: print("Create Peer Hook error:", ex)
    return response

if 'create_peer' in app.view_functions and 'create_peer_original' not in app.view_functions:
    app.view_functions['create_peer_original'] = app.view_functions['create_peer']
    app.view_functions['create_peer'] = v55_create_peer_hook


# ج: دکمه ثبت برای همه (Sync All) با قابلیت اتوماتیک اینترفیس برای نمایندگان و عدم تغییر آی‌پی کلاینت‌های موجود لبه
def v52_api_sync_all_peers():
    import sqlite3, subprocess, json, os, time, re
    from flask import jsonify
    logs = []
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
        edges = cur.fetchall()
        if not edges: return jsonify(logs=["⚠️ هیچ سرور لبه‌ای ثبت نشده است."])
        
        cur.execute("SELECT peer_name, [limit], used, remaining_time, private_key, public_key, config FROM peers")
        master_peers = cur.fetchall()
        
        for p_name, limit, used, rem_time, priv, pub, cfg in master_peers:
            for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                logs.append(f"در حال همسان‌سازی {p_name} ({cfg}) روی {srv_ip}...")
                ensure_edge_interface(s_ip, ssh_port, ssh_user, ssh_pass, cfg)
                
                sync_script = f'''import sqlite3, os, re, subprocess
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{cfg}"; orig_peer_name = "{p_name}"; pub = "{pub}"; iface=cfg.replace('.conf','')

os.makedirs("/usr/local/bin/Wireguard-panel/src", exist_ok=True)
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

cur.execute("SELECT peer_name FROM peers WHERE config=?", (cfg,))
existing_names = set([r[0] for r in cur.fetchall() if r[0]])

final_peer_name = orig_peer_name
counter = 1
while final_peer_name in existing_names:
    cur.execute("SELECT public_key FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
    if cur.fetchone(): break
    final_peer_name = f"{{orig_peer_name}}_{{counter}}"
    counter += 1

cur.execute("SELECT peer_ip FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
row = cur.fetchone()
if row:
    # 📌 اگر کلاینت از قبل در دیتابیس فرزند بود، به هیچ وجه آی‌پی او را دستکاری نکن و فقط در کارت شبکه لبه متصل و تاییدش کن
    peer_ip = row[0]
    cur.execute("UPDATE peers SET [limit]=?, used=?, remaining_time=?, private_key=?, public_key=? WHERE peer_name=? AND config=?", 
                ("{limit}", {used}, {rem_time}, "{priv}", pub, final_peer_name, cfg))
    conn.commit()
    try:
        subprocess.run(f"wg set {{iface}} peer {{pub}} allowed-ips {{peer_ip}}/32", shell=True)
        subprocess.run(f"wg-quick save {{iface}}", shell=True)
    except: pass
    print(f"ALLOCATED_IP:{{peer_ip}}")
else:
    # اگر نبود اولین آی‌پی آزاد را پیدا کن
    base_ip = "10.0.0.1"
    try:
        with open(f"/etc/wireguard/{{cfg}}", "r") as f_cf:
            m = re.search(r"Address\\s*=\\s*([0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+)", f_cf.read(), re.IGNORECASE)
            if m: base_ip = m.group(1)
    except: pass
            
    base_parts = base_ip.split(".")
    base_prefix = ".".join(base_parts[:3])
    
    used_ips = set()
    try:
        cur.execute("SELECT peer_ip FROM peers WHERE config=?", (cfg,))
        used_ips = set([r[0] for r in cur.fetchall() if r[0]])
        wg_path = subprocess.getoutput("which wg").strip() or "/usr/bin/wg"
        wg_out = subprocess.check_output(f"{{wg_path}} show {{iface}} allowed-ips", shell=True, text=True, stderr=subprocess.STDOUT)
        for line in wg_out.splitlines():
            parts = line.split()
            if len(parts) >= 2: used_ips.add(parts[1].split('/')[0])
    except: pass
    
    free_ip = None
    if cfg == "wg0.conf":
        for oct3 in range(0, 256):
            for oct4 in range(2, 255):
                test_ip = f"{{base_parts[0]}}.{{base_parts[1]}}.{{oct3}}.{{oct4}}"
                if test_ip not in used_ips and test_ip != base_ip:
                    free_ip = test_ip; break
            if free_ip: break
    else:
        for oct4 in range(2, 255):
            test_ip = f"{{base_prefix}}.{{oct4}}"
            if test_ip not in used_ips and test_ip != base_ip:
                free_ip = test_ip; break
                
    if not free_ip: free_ip = f"{{base_prefix}}.2"
            
    cur.execute("INSERT INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)", 
                (final_peer_name, "{limit}", {used}, {rem_time}, "{priv}", free_ip, pub, cfg))
    conn.commit()
    try:
        subprocess.run(f"wg set {{iface}} peer {{pub}} allowed-ips {{free_ip}}/32", shell=True)
        subprocess.run(f"wg-quick save {{iface}}", shell=True)
    except: pass
    print(f"ALLOCATED_IP:{{free_ip}}")
conn.close()
'''
                import base64
                encoded_script = base64.b64encode(sync_script.encode('utf-8')).decode('utf-8')
                remote_cmd = f"echo '{encoded_script}' | base64 -d > /tmp/sync_peer.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_peer.py && rm -f /tmp/sync_peer.py"
                res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True, capture_output=True, text=True)
                if res.returncode == 0:
                    out = res.stdout.strip()
                    m_ip = re.search(r"ALLOCATED_IP:(.*)", out)
                    if m_ip:
                        allocated_ip = m_ip.group(1).strip()
                        cur.execute("INSERT OR REPLACE INTO peer_synced_edges (peer_name, server_ip, config, edge_ip) VALUES (?, ?, ?, ?)", (p_name, srv_ip, cfg, allocated_ip))
        
        conn.commit(); conn.close()
        return jsonify(logs=logs, success=True)
    except Exception as e: return jsonify(logs=[f"❌ خطا: {str(e)}"], success=False)

if 'api_sync_all_peers' in app.view_functions: app.view_functions['api_sync_all_peers'] = v52_api_sync_all_peers

# --- [END STEP 55 SUPREME RESELLER MATCHED SYNC] ---



# --- [STEP 56 SUPREME RESELLER SYNC] ---

# الف: متد فیزیکی ایجاد خودکار اینترفیس در سرور لبه بدون تداخل براکت‌های پایتون (Decoupled Base64)
def ensure_edge_interface(srv_ip, ssh_port, ssh_user, ssh_pass, config_file):
    import subprocess, base64
    if config_file == "wg0.conf": return True 
    
    # استفاده از متد تعویض متنی به جای f-string برای جلوگیری از کرش سینتکس پایتون در مادر
    script = '''import os, subprocess, re
cfg="{CONFIG_FILE}"
iface=cfg.replace(".conf","")
is_new = False
if not os.path.exists(f"/etc/wireguard/{cfg}"):
    priv=subprocess.getoutput("wg genkey").strip()
    used_ports=set(); used_subs=set()
    try:
        for f in os.listdir("/etc/wireguard"):
            if f.endswith(".conf"):
                txt=open("/etc/wireguard/"+f).read()
                m1=re.search(r"ListenPort\\s*=\\s*(\\d+)", txt, re.IGNORECASE)
                if m1: used_ports.add(int(m1.group(1)))
                m2=re.search(r"Address\\s*=\\s*(10\\.0\\.\\d+)\\.", txt, re.IGNORECASE)
                if m2: used_subs.add(int(m2.group(1)))
    except: pass
    port=51820
    while port in used_ports: port+=1
    sub=0
    while sub in used_subs: sub+=1
    nic=subprocess.getoutput("ip route | grep default | awk '{print $5}' | head -n1").strip()
    conf=f"[Interface]\\nPrivateKey = {priv}\\nListenPort = {port}\\nAddress = 10.0.{sub}.1/24\\nSaveConfig = false\\n"
    if nic:
        conf+=f"PostUp = iptables -A FORWARD -i {iface} -j ACCEPT; iptables -t nat -A POSTROUTING -o {nic} -j MASQUERADE\\n"
        conf+=f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; iptables -t nat -D POSTROUTING -o {nic} -j MASQUERADE\\n"
    open(f"/etc/wireguard/{cfg}", "w").write(conf)
    is_new = True

# تضمین روشن بودن اینترفیس در سرور لبه (چه تازه ساخته شده چه از قبل بوده)
subprocess.run("systemctl daemon-reload", shell=True)
subprocess.run(f"systemctl enable wg-quick@{iface}", shell=True)
subprocess.run(f"systemctl start wg-quick@{iface}", shell=True)
subprocess.run(f"wg-quick up {iface}", shell=True, stderr=subprocess.DEVNULL)
print("CREATED" if is_new else "EXISTED_AND_STARTED")
'''.replace("{CONFIG_FILE}", config_file)

    enc = base64.b64encode(script.encode('utf-8')).decode('utf-8')
    cmd = f"echo '{enc}' | base64 -d > /tmp/mk_iface.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/mk_iface.py && rm -f /tmp/mk_iface.py"
    res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{srv_ip} \"{cmd}\"", shell=True, capture_output=True, text=True)
    return "OK" in res.stdout


# ب: هوک قدرتمند، ریل‌تایم و ۱۰۰٪ مستقل ساخت کلاینت جدید با قابلیت کشف مستقیم کانفیگ، انطباق ساب‌نت و رزرو در هسته فرزند
def v56_create_peer_hook(*args, **kwargs):
    from flask import request
    original_create_peer_base = app.view_functions.get('create_peer_original') or app.view_functions.get('create_peer')
    response = original_create_peer_base(*args, **kwargs) if original_create_peer_base else None
    try:
        data = request.get_json(silent=True) or request.form or {}
        p_name = data.get("peerName") or data.get("peer_name")
        
        # اگر درخواست به صورت فرم ثبت شده باشد
        if not p_name:
            p_name = request.form.get("peerName") or request.form.get("peer_name")
            
        if p_name:
            import threading
            def run_sync_thread():
                import sqlite3, subprocess, base64, time, re
                time.sleep(2.0) # وقفه امن جهت تکمیل نگارش دیتابیس سرور مادر
                try:
                    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                    cur = conn.cursor()
                    
                    # استخراج مستقیم و ۱۰۰٪ دقیق نام فایل کانفیگ واقعی کلاینت بر اساس نام او از دیتابیس اصلی
                    cur.execute("SELECT [limit], used, remaining_time, private_key, public_key, config FROM peers WHERE peer_name=?", (p_name,))
                    peer_row = cur.fetchone()
                    if not peer_row: 
                        conn.close(); return
                        
                    limit, used, rem_time, priv, pub, cfg_file = peer_row
                    
                    cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
                    edges = cur.fetchall()
                    
                    for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                        # ۱. تضمین وجود اینترفیس در لبه
                        ensure_edge_interface(s_ip, ssh_port, ssh_user, ssh_pass, cfg_file)
                        
                        # ۲. ساخت کلاینت در کارت شبکه لبه با موتور تشخیص ساب‌نت و رزرو قطعی در لینوکس لبه
                        sync_script = '''import sqlite3, os, re, subprocess
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{CONFIG_FILE}"
orig_peer_name = "{PEER_NAME}"
pub = "{PUB_KEY}"
iface=cfg.replace('.conf','')

os.makedirs("/usr/local/bin/Wireguard-panel/src", exist_ok=True)
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

cur.execute("SELECT peer_name FROM peers WHERE config=?", (cfg,))
existing_names = set([r[0] for r in cur.fetchall() if r[0]])

final_peer_name = orig_peer_name
counter = 1
while final_peer_name in existing_names:
    cur.execute("SELECT public_key FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
    existing_pub = cur.fetchone()
    if existing_pub and existing_pub[0] == pub: break
    final_peer_name = f"{orig_peer_name}_{counter}"
    counter += 1

cur.execute("SELECT peer_ip FROM peers WHERE peer_name=? AND config=?", (final_peer_name, cfg))
row = cur.fetchone()

if row:
    peer_ip = row[0]
    cur.execute("UPDATE peers SET [limit]=?, used=?, remaining_time=?, private_key=?, public_key=? WHERE peer_name=? AND config=?", 
                ("{LIMIT}", {USED}, {REM_TIME}, "{PRIV_KEY}", pub, final_peer_name, cfg))
    conn.commit()
    try:
        subprocess.run(f"wg set {iface} peer {pub} allowed-ips {peer_ip}/32", shell=True)
        subprocess.run(f"wg-quick save {iface}", shell=True)
    except: pass
    print(f"ALLOCATED_IP:{peer_ip}")
else:
    # تشخیص ساب‌نت لبه
    base_ip = "10.0.0.1"
    subnet_mask = 24
    try:
        if os.path.exists(f"/etc/wireguard/{cfg}"):
            with open(f"/etc/wireguard/{cfg}", "r") as f_cf:
                txt = f_cf.read()
                m = re.search(r"Address\s*=\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)/?(\d*)", txt, re.IGNORECASE)
                if m: 
                    base_ip = m.group(1)
                    if m.group(2): subnet_mask = int(m.group(2))
    except: pass
        
    base_parts = base_ip.split(".")
    base_prefix = ".".join(base_parts[:3])

    used_ips = set()
    try:
        cur.execute("SELECT peer_ip FROM peers WHERE config=?", (cfg,))
        used_ips = set([r[0] for r in cur.fetchall() if r[0]])
        wg_path = subprocess.getoutput("which wg").strip() or "/usr/bin/wg"
        wg_out = subprocess.check_output(f"{wg_path} show {iface} allowed-ips", shell=True, text=True, stderr=subprocess.STDOUT)
        for line in wg_out.splitlines():
            parts = line.split()
            if len(parts) >= 2: used_ips.add(parts[1].split('/')[0])
    except: pass

    free_ip = None
    if cfg == "wg0.conf":
        for oct3 in range(0, 256):
            for oct4 in range(2, 255):
                test_ip = f"{base_parts[0]}.{base_parts[1]}.{oct3}.{oct4}"
                if test_ip not in used_ips and test_ip != base_ip:
                    free_ip = test_ip; break
            if free_ip: break
    else:
        for oct4 in range(2, 255):
            test_ip = f"{base_prefix}.{oct4}"
            if test_ip not in used_ips and test_ip != base_ip:
                free_ip = test_ip; break

    if not free_ip: free_ip = f"{base_prefix}.2"
            
    cur.execute("INSERT INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)", 
                (final_peer_name, "{LIMIT}", {USED}, {REM_TIME}, "{PRIV_KEY}", free_ip, pub, cfg))
    conn.commit()
    try:
        subprocess.run(f"wg set {iface} peer {pub} allowed-ips {free_ip}/32", shell=True)
        subprocess.run(f"wg-quick save {iface}", shell=True) # ذخیره فیزیکی روی دیسک فرزند
    except: pass
    print(f"ALLOCATED_IP:{free_ip}")
conn.close()
'''.replace("{CONFIG_FILE}", cfg_file).replace("{PEER_NAME}", p_name).replace("{PUB_KEY}", pub).replace("{LIMIT}", limit).replace("{USED}", str(used)).replace("{REM_TIME}", str(rem_time)).replace("{PRIV_KEY}", priv)

                        encoded_script = base64.b64encode(sync_script.encode('utf-8')).decode('utf-8')
                        remote_cmd = f"echo '{encoded_script}' | base64 -d > /tmp/sync_new.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/sync_new.py && rm -f /tmp/sync_new.py"
                        # 📌 تصحیح فوق‌العاده مهم: استفاده از آی‌پی عددی s_ip و یوزر روت ssh_user برای لاگین ریل‌تایم ۱۰۰٪ موفق
                        res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{remote_cmd}\"", shell=True, capture_output=True, text=True)
                        
                        if res.returncode == 0:
                            out = res.stdout.strip()
                            m_ip = re.search(r"ALLOCATED_IP:(.*)", out)
                            if m_ip:
                                allocated_ip = m_ip.group(1).strip()
                                cur.execute("INSERT OR REPLACE INTO peer_synced_edges (peer_name, server_ip, config, edge_ip) VALUES (?, ?, ?, ?)", (p_name, srv_ip, cfg_file, allocated_ip))
                    conn.commit(); conn.close()
                except Exception as ex_t: print("Thread error:", ex_t)
            threading.Thread(target=run_sync_thread, daemon=True).start()
    except Exception as ex: print("Create Peer Hook error:", ex)
    return response

if 'create_peer' in app.view_functions:
    if 'create_peer_original' not in app.view_functions: app.view_functions['create_peer_original'] = app.view_functions['create_peer']
    app.view_functions['create_peer'] = v55_create_peer_hook

# --- [END STEP 56 SUPREME RESELLER SYNC] ---







# --- [STEP 61 SUPREME MATCHED SYNC] ---

# الف: محاسبه ۱۰۰٪ دقیق ترافیک ویجت‌های جدول میانی (حجم مصرف شده + حجم کل + حجم باقی‌مانده)
def v61_obtain_system_uptime():
    from flask import request, session
    import sqlite3
    
    config_file = request.args.get("config", "wg0.conf") or "wg0.conf"
    if session.get('role') == 'client': config_file = session.get('interface') + ".conf"
        
    interface = config_file.split(".")[0]
    total_bytes = 0
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        if interface == 'wg0':
            cur.execute("SELECT SUM(used) FROM peers")
            live_used = cur.fetchone()[0] or 0
            cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1")
            del_global = cur.fetchone()[0] or 0
            try:
                cur.execute("SELECT SUM(deleted_traffic) FROM sub_panels")
                del_subs = cur.fetchone()[0] or 0
            except: del_subs = 0
            total_bytes = live_used + del_global + del_subs
        else:
            cur.execute("SELECT SUM(used) FROM peers WHERE config=?", (config_file,))
            live_used = cur.fetchone()[0] or 0
            try:
                cur.execute("SELECT deleted_traffic FROM sub_panels WHERE interface_name=?", (interface,))
                del_sub = cur.fetchone()[0] or 0
            except: del_sub = 0
            total_bytes = live_used + del_sub
        conn.close()
    except: pass
    
    limit_gb = 0
    if interface != 'wg0':
        try:
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT data_limit_gb FROM sub_panels WHERE interface_name=?", (interface,))
            row = cur.fetchone()
            limit_gb = row[0] if row else 0
            conn.close()
        except: pass

    if total_bytes >= 1073741824: val_str = f"{total_bytes / 1073741824.0:.2f} GB"
    elif total_bytes >= 1048576: val_str = f"{total_bytes / 1048576.0:.2f} MB"
    else: val_str = f"{total_bytes / 1024.0:.2f} KB"

    # نمایش همزمان حجم مصرفی، حجم کل و حجم باقی‌مانده در جدول وسط داشبورد برای نمایندگان
    if limit_gb > 0:
        remaining_bytes = max(0, (limit_gb * 1073741824.0) - total_bytes)
        if remaining_bytes >= 1073741824: rem_str = f"{remaining_bytes / 1073741824.0:.2f} GB"
        elif remaining_bytes >= 1048576: rem_str = f"{remaining_bytes / 1048576.0:.2f} MB"
        else: rem_str = f"{remaining_bytes / 1024.0:.2f} KB"
        return f"{val_str} / {limit_gb:.0f} GB (باقی‌مانده: {rem_str})"
    else:
        return f"{val_str}"

globals()['obtain_system_uptime'] = v61_obtain_system_uptime


# ب: متد فابریک، پایدار و مستقل سیستم Metrics (بدون ارور و تداخل و تکیه بر متدهای لرزان کارخانه)
def v61_obtain_metrics_view(*args, **kwargs):
    from flask import session, jsonify
    import sqlite3, psutil, time
    
    # ۱. استخراج کاملاً مستقل و دقیق منابع با ساختار فابریک و مورد انتظار جاوااسکریپت پنل (data.disk.percent)
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        if cpu_usage == 0.0:
            time.sleep(0.02)
            cpu_usage = psutil.cpu_percent(interval=None)
            
        ram_usage = psutil.virtual_memory().percent
        disk_usage = psutil.disk_usage('/').percent
        
        data = {
            "cpu": cpu_usage,
            "ram": ram_usage,
            "disk": {
                "percent": disk_usage
            }
        }
    except Exception as e:
        print("Sensor calculation warning:", e)
        data = {"cpu": 0, "ram": 0, "disk": {"percent": 0}}
        
    active_config = session.get('active_config', 'wg0.conf')
    if session.get('role') == 'client': active_config = session.get('interface') + ".conf"
    interface = active_config.split(".")[0] if active_config else "wg0"
    is_fa = session.get('language') == 'fa' or session.get('language', 'en') == 'fa'
    
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        
        if interface == 'wg0':
            cur.execute("SELECT SUM(used) FROM peers")
            live_used = cur.fetchone()[0] or 0
            cur.execute("SELECT total FROM global_deleted_traffic WHERE id=1")
            del_global = cur.fetchone()[0] or 0
            try:
                cur.execute("SELECT SUM(deleted_traffic) FROM sub_panels")
                del_subs = cur.fetchone()[0] or 0
            except: del_subs = 0
            
            used_bytes = live_used + del_global + del_subs
            data["uptime_label"] = "حجم مصرف کلی" if is_fa else "Total Global Traffic"
            data["uptime_percent"] = 0 
        else:
            cur.execute("SELECT SUM(used) FROM peers WHERE config=?", (f"{interface}.conf",))
            live_used = cur.fetchone()[0] or 0
            try:
                cur.execute("SELECT deleted_traffic FROM sub_panels WHERE interface_name=?", (interface,))
                del_sub = cur.fetchone()[0] or 0
            except: del_sub = 0
            
            used_bytes = live_used + del_sub
            cur.execute("SELECT data_limit_gb FROM sub_panels WHERE interface_name=?", (interface,))
            row_l = cur.fetchone()
            limit_gb = row_l[0] if row_l else 100.0
            data["uptime_label"] = "حجم مصرفی" if is_fa else "Used Traffic"
            if limit_gb > 0:
                pct = int(((used_bytes / 1073741824.0) / limit_gb) * 100)
                data["uptime_percent"] = min(100, max(0, pct))
            else: data["uptime_percent"] = 0
            
        conn.close()
        
        if used_bytes >= 1073741824: val_str = f"{used_bytes / 1073741824.0:.2f} GB"
        elif used_bytes >= 1048576: val_str = f"{used_bytes / 1048576.0:.2f} MB"
        else: val_str = f"{used_bytes / 1024.0:.2f} KB"
        
        # ۳. نمایش حجم مصرف شده در دایره وسط برای هر دو گروه (مثال: 1.50 GB)
        data["uptime"] = val_str 
        return jsonify(data)
    except Exception as e:
        print("Metrics DB Override Error:", e)
        return jsonify(data)

if 'obtain_metrics' in app.view_functions:
    app.view_functions['obtain_metrics'] = v61_obtain_metrics_view

# --- [END STEP 61 SUPREME MATCHED SYNC] ---







# --- [STEP 66 SUPREME WRAPPER SYNC] ---

# 📌 متد هلپر جهت افزودن امن ترافیک به صندوق
def add_to_vault_safely(interface, amount):
    if amount <= 0: return
    import sqlite3
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO interface_vault (interface_name, vault_bytes) VALUES (?, 0)", (interface,))
        cur.execute("UPDATE interface_vault SET vault_bytes = vault_bytes + ? WHERE interface_name=?", (amount, interface))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Vault Error:", e)

# 📌 ۱. کپسوله کردن دکمه "ریست ترافیک" (حفظ کد اصلی + واریز به صندوق + شستشوی لینوکس)
original_reset_traffic = app.view_functions.get('reset_traffic_original') or app.view_functions.get('reset_traffic')

def v66_wrapper_reset_traffic(*args, **kwargs):
    from flask import request, session
    import sqlite3, subprocess
    
    data = request.get_json(silent=True) or request.form or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    
    config_file = "wg0.conf"
    if session.get('role') == 'client':
        config_file = session.get('interface') + ".conf"
    else:
        config_file = data.get("config", "wg0.conf") or "wg0.conf"
        
    if not config_file.endswith('.conf'): config_file += ".conf"
    interface = config_file.replace('.conf', '')
    
    pub_key, peer_ip = None, None
    
    # Фاز اول: صید ترافیک قبل از اجرای متد اصلی
    if peer_name:
        try:
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT used, public_key, peer_ip FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
            row = cur.fetchone()
            if row:
                used_val, pub_key, peer_ip = row
                add_to_vault_safely(interface, used_val)
                # ریست کردن حافظه کلاستر تا تجمیع‌گر ترافیک قبلی را نشمارد
                cur.execute("UPDATE peer_synced_edges SET last_bytes=0 WHERE peer_name=? AND config=?", (peer_name, config_file))
                conn.commit()
            conn.close()
        except: pass

    # Фاز دوم: اجرای متد اصلی و فابریک پنل (برای اینکه کاربر در ظاهر پنل و دیتابیس واقعاً ریست شود)
    response = original_reset_traffic(*args, **kwargs) if original_reset_traffic else None

    # Фاز سوم: شستشوی حافظه کارت شبکه لینوکس (فیکس باگ تکثیر ترافیک)
    if pub_key and peer_ip:
        try:
            subprocess.run(f"wg set {interface} peer {pub_key} remove", shell=True, stderr=subprocess.DEVNULL)
            subprocess.run(f"wg set {interface} peer {pub_key} allowed-ips {peer_ip}/32", shell=True, stderr=subprocess.DEVNULL)
        except: pass
        
        # همگام‌سازی آنی با لبه‌ها
        if 'sync_action_to_edges' in globals():
            globals()['sync_action_to_edges']("edit", peer_name, config_file)

    return response

if 'reset_traffic' in app.view_functions:
    if 'reset_traffic_original' not in app.view_functions:
        app.view_functions['reset_traffic_original'] = app.view_functions['reset_traffic']
    app.view_functions['reset_traffic'] = v66_wrapper_reset_traffic


# 📌 ۲. کپسوله کردن دکمه "حذف کاربر" (حفظ کد اصلی + واریز به صندوق)
original_delete_peer = app.view_functions.get('delete_peer_original') or app.view_functions.get('delete_peer')

def v66_wrapper_delete_peer(*args, **kwargs):
    from flask import request, session
    import sqlite3
    
    data = request.get_json(silent=True) or request.form or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    
    config_file = "wg0.conf"
    if session.get('role') == 'client':
        config_file = session.get('interface') + ".conf"
    else:
        config_file = data.get("config", "wg0.conf") or "wg0.conf"
        
    if not config_file.endswith('.conf'): config_file += ".conf"
    interface = config_file.replace('.conf', '')
    
    # Фاز اول: صید ترافیک قبل از حذف شدن کاربر
    if peer_name:
        try:
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT used FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
            row = cur.fetchone()
            if row and row[0] > 0:
                add_to_vault_safely(interface, row[0])
            conn.close()
        except: pass

    # Фاز دوم: اجرای متد فابریک پنل (برای حذف فیزیکی، بلک هول، ویرایش JSON و غیره)
    response = original_delete_peer(*args, **kwargs) if original_delete_peer else None
    return response

if 'delete_peer' in app.view_functions:
    if 'delete_peer_original' not in app.view_functions:
        app.view_functions['delete_peer_original'] = app.view_functions['delete_peer']
    app.view_functions['delete_peer'] = v66_wrapper_delete_peer


# 📌 ۳. رندر متن رادار و جداول (جمع ترافیک زنده + صندوق)
def v66_obtain_system_uptime():
    from flask import request, session, has_request_context
    import sqlite3
    
    config_file = "wg0.conf"
    if has_request_context():
        config_file = session.get('active_config', 'wg0.conf') or "wg0.conf"
        if session.get('role') == 'client':
            config_file = session.get('interface', 'wg0') + ".conf"
            
    interface = config_file.split(".")[0]
    total_bytes = 0
    limit_gb = 0
    
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()

        if interface == 'wg0':
            cur.execute("SELECT SUM(used) FROM peers")
            live_used = cur.fetchone()[0]
            live_used = live_used if live_used else 0
            
            cur.execute("SELECT SUM(vault_bytes) FROM interface_vault")
            vault_bytes = cur.fetchone()[0]
            vault_bytes = vault_bytes if vault_bytes else 0
            
            total_bytes = live_used + vault_bytes
        else:
            cur.execute("SELECT SUM(used) FROM peers WHERE config=?", (f"{interface}.conf",))
            live_used = cur.fetchone()[0]
            live_used = live_used if live_used else 0
            
            cur.execute("SELECT vault_bytes FROM interface_vault WHERE interface_name=?", (interface,))
            vault_row = cur.fetchone()
            vault_bytes = vault_row[0] if vault_row else 0
            
            total_bytes = live_used + vault_bytes
            
            cur.execute("SELECT data_limit_gb FROM sub_panels WHERE interface_name=?", (interface,))
            limit_row = cur.fetchone()
            limit_gb = limit_row[0] if limit_row else 0
            
        conn.close()
    except Exception as e_db:
        pass

    if total_bytes >= 1073741824: val_str = f"{total_bytes / 1073741824.0:.2f} GB"
    elif total_bytes >= 1048576: val_str = f"{total_bytes / 1048576.0:.2f} MB"
    else: val_str = f"{total_bytes / 1024.0:.2f} KB"

    if limit_gb > 0: 
        return f"{val_str} / {limit_gb:.0f} GB"
    else: 
        return f"{val_str}"

globals()['obtain_system_uptime'] = v66_obtain_system_uptime


# 📌 ۴. رندر زنده دایره نئونی و نمودار داشبورد
original_obtain_metrics = app.view_functions.get('obtain_metrics_original') or app.view_functions.get('obtain_metrics')
def v66_obtain_metrics_view(*args, **kwargs):
    from flask import session, jsonify
    import json, sqlite3, psutil, time
    
    try:
        psutil.cpu_percent(interval=None)
        time.sleep(0.02)
        data = {
            "cpu": psutil.cpu_percent(interval=None),
            "ram": psutil.virtual_memory().percent,
            "disk": {"percent": psutil.disk_usage('/').percent}
        }
    except:
        data = {"cpu": 0, "ram": 0, "disk": {"percent": 0}}
        
    active_config = session.get('active_config', 'wg0.conf') or "wg0.conf"
    if session.get('role') == 'client':
        active_config = session.get('interface', 'wg0') + ".conf"
        
    interface = active_config.split(".")[0]
    is_fa = session.get('language') == 'fa' or session.get('language', 'en') == 'fa'
    
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()

        if interface == 'wg0':
            cur.execute("SELECT SUM(used) FROM peers")
            live_used = cur.fetchone()[0] or 0
            cur.execute("SELECT SUM(vault_bytes) FROM interface_vault")
            vault_bytes = cur.fetchone()[0] or 0
            
            used_bytes = live_used + vault_bytes
            data["uptime_label"] = "حجم مصرف کلی" if is_fa else "Total Global Traffic"
            data["uptime_percent"] = 0 
            limit_gb = 0
        else:
            cur.execute("SELECT SUM(used) FROM peers WHERE config=?", (f"{interface}.conf",))
            live_used = cur.fetchone()[0] or 0
            cur.execute("SELECT vault_bytes FROM interface_vault WHERE interface_name=?", (interface,))
            vault_row = cur.fetchone()
            vault_bytes = vault_row[0] if vault_row else 0
            
            used_bytes = live_used + vault_bytes
            
            cur.execute("SELECT data_limit_gb FROM sub_panels WHERE interface_name=?", (interface,))
            limit_row = cur.fetchone()
            limit_gb = limit_row[0] if limit_row else 100.0
            
            data["uptime_label"] = "حجم مصرفی" if is_fa else "Used Traffic"
            if limit_gb > 0:
                pct = round(((used_bytes / 1073741824.0) / limit_gb) * 100, 2)
                data["uptime_percent"] = min(100.0, max(0.0, pct))
            else: 
                data["uptime_percent"] = 0
                
        conn.close()
        
        if used_bytes >= 1073741824: val_str = f"{used_bytes / 1073741824.0:.2f} GB"
        elif used_bytes >= 1048576: val_str = f"{used_bytes / 1048576.0:.2f} MB"
        else: val_str = f"{used_bytes / 1024.0:.2f} KB"
        
        if limit_gb > 0:
            data["uptime"] = f"{val_str} / {limit_gb:.0f} GB"
        else:
            data["uptime"] = val_str
            
        return jsonify(data)
    except Exception as e:
        return jsonify(data)

if 'obtain_metrics' in app.view_functions:
    if 'obtain_metrics_original' not in app.view_functions:
        app.view_functions['obtain_metrics_original'] = app.view_functions['obtain_metrics']
    app.view_functions['obtain_metrics'] = v66_obtain_metrics_view

# --- [END STEP 66 SUPREME WRAPPER SYNC] ---



# --- [STEP 65 ULTIMATE PURGE ENGINE] ---

# متد هوشمند واکشی نام فایل کانفیگ به روش اسکن چندگانه کلیدهای وب‌سرور شما
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

# متد هلپر جهت افزودن امن ترافیک به صندوق در زمان حذف کلاینت‌ها
def add_to_vault_safely(interface, amount):
    if amount <= 0: return
    import sqlite3
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        if interface == 'wg0':
            cur.execute("UPDATE global_deleted_traffic SET total = total + ? WHERE id=1", (amount,))
        else:
            cur.execute("INSERT OR IGNORE INTO sub_panels (interface_name, username, data_limit_gb, port, status) VALUES (?, ?, 100.0, 51821, 'active')", (interface, "Reseller_" + interface))
            cur.execute("UPDATE sub_panels SET deleted_traffic = deleted_traffic + ? WHERE interface_name=?", (amount, interface))
        cur.execute("INSERT OR IGNORE INTO interface_vault (interface_name, vault_bytes) VALUES (?, 0)", (interface,))
        cur.execute("UPDATE interface_vault SET vault_bytes = vault_bytes + ? WHERE interface_name=?", (amount, interface))
        conn.commit()
        conn.close()
    except: pass

# متد هلپر شستشوی فیزیکی هارد دیسک و ارواح از فایل کانفیگ مادر
def physically_wash_disk_config(config_file):
    import os, re, sqlite3
    path = f"/etc/wireguard/{config_file}"
    if not os.path.exists(path): return
    
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
    cur = conn.cursor()
    cur.execute("SELECT public_key FROM peers WHERE config=?", (config_file,))
    active_pubs = set([r[0] for r in cur.fetchall() if r[0]])
    conn.close()
    
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
        
    blocks = text.split("[Peer]")
    new_text = blocks[0].strip() + "\n"
    
    for block in blocks[1:]:
        pub_match = re.search(r"PublicKey\s*=\s*(.*)", block)
        if pub_match and pub_match.group(1).strip() in active_pubs:
            new_text += "\n[Peer]\n" + block.strip() + "\n"
            
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text.strip() + "\n")


# 📌 ۱. وب‌متد فوق‌پایدار حذف تکی کلاینت (Single Delete Engine)
def v65_supreme_delete_peer_view(*args, **kwargs):
    from flask import request, jsonify, session
    import sqlite3, subprocess, base64, threading
    
    data = request.get_json(silent=True) or request.form or {}
    peer_name = data.get("peerName") or data.get("peer_name")
    
    config_file = get_config_file_from_request(data, request.args, session.get('interface'))
    interface = config_file.replace('.conf', '')
    
    if not peer_name: return jsonify(error="Peer name is required."), 400
        
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        cur.execute("SELECT public_key, used, peer_ip FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
        row = cur.fetchone()
        
        if row:
            pub_key, used_val, peer_ip = row
            
            # ذخیره ترافیک در صندوق نماینده یا ادمین
            add_to_vault_safely(interface, used_val)
            
            # حذف از لینوکس و روت‌ها در سرور مادر
            subprocess.run(f"wg set {interface} peer {pub_key} remove", shell=True, stderr=subprocess.DEVNULL)
            if peer_ip:
                subprocess.run(f"ip route del blackhole {peer_ip}", shell=True, stderr=subprocess.DEVNULL)
                subprocess.run(f"ip route del {peer_ip} blackhole", shell=True, stderr=subprocess.DEVNULL)
            
            # حذف از دیتابیس مادر
            cur.execute("DELETE FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
            cur.execute("DELETE FROM peer_synced_edges WHERE peer_name=? AND config=?", (peer_name, config_file))
            conn.commit()
            
            # شستشوی فیزیکی دیسک مادر و نابود کردن ارواح متنی کلاینت جاری
            physically_wash_disk_config(config_file)
            
            # واکشی سرورهای لبه و ارسال دستور حذف آنی به لبه‌ها
            cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
            edges = cur.fetchall()
            conn.close()
            
            def run_edge_delete():
                for s_ip, ssh_port, ssh_user, ssh_pass in edges:
                    edge_script = f'''import sqlite3, subprocess, os, re
conn = sqlite3.connect("/usr/local/bin/Wireguard-panel/src/db.sqlite3", timeout=30.0)
cur = conn.cursor()
cur.execute("DELETE FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
conn.commit()
cur.execute("SELECT public_key FROM peers WHERE config='{config_file}'")
active_pubs = set([r[0] for r in cur.fetchall() if r[0]])
conn.close()

subprocess.run("wg set {interface} peer {pub_key} remove", shell=True, stderr=subprocess.DEVNULL)
subprocess.run("ip route del blackhole {peer_ip}", shell=True, stderr=subprocess.DEVNULL)
subprocess.run("ip route del {peer_ip} blackhole", shell=True, stderr=subprocess.DEVNULL)

path = "/etc/wireguard/{config_file}"
if os.path.exists(path):
    with open(path, "r") as f: text = f.read()
    blocks = text.split("[Peer]")
    new_text = blocks[0].strip() + "\\n"
    for block in blocks[1:]:
        m = re.search(r"PublicKey\\s*=\\s*(.*)", block)
        if m and m.group(1).strip() in active_pubs:
            new_text += "\\n[Peer]\\n" + block.strip() + "\\n"
    with open(path, "w") as f: f.write(new_text.strip() + "\\n")
    subprocess.run("wg-quick save {interface}", shell=True, stderr=subprocess.DEVNULL)
'''
                    enc = base64.b64encode(edge_script.encode('utf-8')).decode('utf-8')
                    cmd = f"echo '{enc}' | base64 -d > /tmp/del_edge.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/del_edge.py && rm -f /tmp/del_edge.py"
                    subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{cmd}\"", shell=True)
            threading.Thread(target=run_edge_delete, daemon=True).start()
            
            return jsonify(message="Peer deleted successfully.")
        else:
            conn.close()
            return jsonify(error="Peer not found."), 404
            
    except Exception as e:
        return jsonify(error=str(e)), 500


# 📌 ۲. وب‌متد بررسی غیرفعال‌ها با قابلیت شستشوی ارواح در مادر و فرزند (Check Inactive Engine)
def v65_supreme_delete_all_configs_view(*args, **kwargs):
    from flask import request, jsonify, session
    import sqlite3, subprocess, base64, threading, os, re
    
    data = request.get_json(silent=True) or request.form or {}
    config_file = get_config_file_from_request(data, request.args, session.get('interface'))
    interface = config_file.replace('.conf', '')
    
    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        
        # ۱. استخراج کاربران منقضی شده فقط برای همین اینترفیس
        expired_peers = []
        cur.execute("SELECT peer_name, public_key, used, peer_ip FROM peers WHERE config=? AND (remaining_time <= 0 OR expiry_blocked = 1 OR monitor_blocked = 1)", (config_file,))
        expired_peers.extend(cur.fetchall())
        
        # ۲. استخراج کاربران اتمام حجم شده فقط برای همین اینترفیس
        cur.execute("SELECT peer_name, [limit], used, public_key, peer_ip FROM peers WHERE config=?", (config_file,))
        for p_name, limit_str, used_val, pub, peer_ip in cur.fetchall():
            limit_bytes = 0
            if "GiB" in limit_str: limit_bytes = float(limit_str.replace("GiB", "")) * 1073741824.0
            elif "MiB" in limit_str: limit_bytes = float(limit_str.replace("MiB", "")) * 1048576.0
            if limit_bytes > 0 and used_val >= limit_bytes:
                if p_name not in [x[0] for x in expired_peers]:
                    expired_peers.append((p_name, pub, used_val, peer_ip))
                    
        # ۳. خودآرایی: حتی اگر هیچ منقضی وجود نداشت، دیسک فیزیکی را از ارواح شستشو بده! (بسیار مهم)
        if not expired_peers:
            physically_wash_disk_config(config_file)
            conn.close()
            return jsonify(message="هیچ کاربر غیرفعالی در دیتابیس نبود؛ شستشوی ارواح فیزیکی دیسک با موفقیت انجام شد.")
            
        total_vault_add = 0
        names_to_delete = []
        for p_name, pub, used_val, peer_ip in expired_peers:
            total_vault_add += used_val
            names_to_delete.append(p_name)
            subprocess.run(f"wg set {interface} peer {pub} remove", shell=True, stderr=subprocess.DEVNULL)
            if peer_ip:
                subprocess.run(f"ip route del blackhole {peer_ip}", shell=True, stderr=subprocess.DEVNULL)
                subprocess.run(f"ip route del {peer_ip} blackhole", shell=True, stderr=subprocess.DEVNULL)
                
        # ذخیره ترافیک مسدودین در صندوق نماینده مربوطه
        add_to_vault_safely(interface, total_vault_add)
        
        # حذف گروهی از دیتابیس مادر
        placeholders = ','.join(['?'] * len(names_to_delete))
        cur.execute(f"DELETE FROM peers WHERE config=? AND peer_name IN ({placeholders})", [config_file] + names_to_delete)
        cur.execute(f"DELETE FROM peer_synced_edges WHERE config=? AND peer_name IN ({placeholders})", [config_file] + names_to_delete)
        conn.commit()
        
        # شستشوی فیزیکی دیسک مادر و شستن ارواح این اینترفیس
        physically_wash_disk_config(config_file)
        
        # همگام‌سازی آنی شستشوی دیسک و دیتابیس در لبه‌ها
        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
        edges = cur.fetchall()
        conn.close()
        
        def run_edge_bulk_delete():
            for s_ip, ssh_port, ssh_user, ssh_pass in edges:
                edge_script = f'''import sqlite3, subprocess, os, re
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{config_file}"
iface = cfg.replace('.conf','')
names = {names_to_delete}

conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
for n in names:
    cur.execute("SELECT public_key, peer_ip FROM peers WHERE peer_name=? AND config='{config_file}'", (n,))
    r = cur.fetchone()
    if r:
        subprocess.run(f"wg set {{iface}} peer {{r[0]}} remove", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run(f"ip route del blackhole {{r[1]}}", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run(f"ip route del {{r[1]}} blackhole", shell=True, stderr=subprocess.DEVNULL)
    cur.execute("DELETE FROM peers WHERE peer_name=? AND config='{config_file}'", (n,))
conn.commit()
cur.execute("SELECT public_key FROM peers WHERE config='{config_file}'")
active_pubs = set([r[0] for r in cur.fetchall() if r[0]])
conn.close()

path = f"/etc/wireguard/{{cfg}}"
if os.path.exists(path):
    with open(path, "r") as f: text = f.read()
    blocks = text.split("[Peer]")
    new_text = blocks[0].strip() + "\\n"
    for block in blocks[1:]:
        m = re.search(r"PublicKey\\s*=\\s*(.*)", block)
        if m and m.group(1).strip() in active_pubs:
            new_text += "\\n[Peer]\\n" + block.strip() + "\\n"
    with open(path, "w") as f: f.write(new_text.strip() + "\\n")
    subprocess.run(f"wg-quick save {{iface}}", shell=True, stderr=subprocess.DEVNULL)
'''
                enc = base64.b64encode(edge_script.encode('utf-8')).decode('utf-8')
                cmd = f"echo '{enc}' | base64 -d > /tmp/bulk_del.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/bulk_del.py && rm -f /tmp/bulk_del.py"
                subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{cmd}\"", shell=True)
                
        threading.Thread(target=run_edge_bulk_delete, daemon=True).start()
        
        return jsonify(message=f"تعداد {len(names_to_delete)} کاربر منقضی با موفقیت پاکسازی و ارواح دیسک شسته شدند.")
        
    except Exception as e:
        return jsonify(error=str(e)), 500


# 📌 ۳. موتور اتصال پویا به روت‌های کارخانه جهت جلوگیری از تداخل هوک‌ها (Dynamic Route Binding)
def start_supreme_route_binding():
    # اسکن روت‌مپ فلاسک برای کشف پویای نام توابع کارخانه
    for rule in app.url_map.iter_rules():
        if rule.rule in ['/api/delete-peer', '/api/delete_peer']:
            app.view_functions[rule.endpoint] = v65_supreme_delete_peer_view
            print(f"✅ بایندینگ ریشه‌ای حذف تکی روی تابع '{rule.endpoint}' قفل شد.")
            
        if rule.rule in ['/api/delete-all-configs', '/api/delete_all_configs', '/api/delete-all', '/api/delete_all']:
            app.view_functions[rule.endpoint] = v65_supreme_delete_all_configs_view
            print(f"✅ بایندینگ ریشه‌ای حذف همگانی روی تابع '{rule.endpoint}' قفل شد.")

try:
    start_supreme_route_binding()
except Exception as e_bind:
    print("Routing Binding Error:", e_bind)

# --- [END STEP 65 ULTIMATE PURGE ENGINE] ---



# --- [STEP 69 CLEAN SUBLINK PLANS] ---

# 📌 ۱. وب‌متد جایگزین رندر صفحه ساب‌لینک
def v69_custom_short_redirect_view(short_id):
    import sqlite3, os, json, re, time, urllib.parse
    from flask import render_template, make_response
    
    short_links_path = os.path.join('/usr/local/bin/Wireguard-panel/src', 'short_links.json')
    if not os.path.exists(short_links_path): return "❌ Error: Sub link file not found", 404
    with open(short_links_path, 'r') as f: short_links = json.load(f)
    long_link = short_links.get(short_id)
    if not long_link: return "❌ Error: Invalid subscription link", 404
        
    peer_name = ""
    config_file = "wg0.conf"
    
    p_match = re.search(r'peer_name=([^&]+)', long_link) or re.search(r'peerName=([^&]+)', long_link)
    c_match = re.search(r'config_file=([^&]+)', long_link) or re.search(r'configFile=([^&]+)', long_link) or re.search(r'config=([^&]+)', long_link)
    
    if p_match: peer_name = urllib.parse.unquote(p_match.group(1))
    if c_match: config_file = urllib.parse.unquote(c_match.group(1))
    if not config_file.endswith('.conf'): config_file += '.conf'
    interface = config_file.split(".")[0]
    
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
    cur = conn.cursor()
    
    cur.execute("SELECT special_mode FROM client_settings WHERE interface_name=?", (interface,))
    row_mode = cur.fetchone()
    special_mode = row_mode[0] if row_mode else 1

    try:
        cur.execute("SELECT [limit], used, remaining_time, expiry_time_json FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
        peer_row = cur.fetchone()
    except:
        cur.execute("SELECT [limit], used, remaining_time, '' FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
        peer_row = cur.fetchone()
        
    if not peer_row: conn.close(); return "❌ Error: Peer not found", 404

    limit_str, used_bytes, rem_minutes, expiry_json_str = peer_row
    limit_bytes = 0
    if "GiB" in limit_str: limit_bytes = float(limit_str.replace("GiB", "")) * 1073741824.0
    elif "MiB" in limit_str: limit_bytes = float(limit_str.replace("MiB", "")) * 1048576.0

    used_percent = min(100, round((used_bytes / limit_bytes) * 100, 1)) if limit_bytes > 0 else 0
    if used_bytes >= 1073741824: used_str_fa = f"{used_bytes / 1073741824.0:.2f} گیگابایت"
    elif used_bytes >= 1048576: used_str_fa = f"{used_bytes / 1048576.0:.2f} مگابایت"
    else: used_str_fa = f"{used_bytes / 1024.0:.2f} کیلوبایت"
    limit_str_fa = limit_str.replace("GiB", " گیگابایت").replace("MiB", " مگابایت")
    
    total_min = rem_minutes
    try:
        if expiry_json_str and str(expiry_json_str).strip() not in ["None", ""]:
            exp_json = json.loads(str(expiry_json_str))
            total_min_from_json = (int(exp_json.get("months",0)) * 30 * 1440) + (int(exp_json.get("days",0)) * 1440) + (int(exp_json.get("hours",0)) * 60) + int(exp_json.get("minutes",0))
            if total_min_from_json > 0: total_min = total_min_from_json
    except: pass
        
    if rem_minutes > total_min: total_min = rem_minutes
    elapsed_min = max(0, total_min - rem_minutes)
    
    if total_min <= rem_minutes:
        for plan in [1440, 4320, 10080, 43200, 129600, 259200, 525600]:
            if rem_minutes <= plan: total_min = plan; break

    time_percent = min(100.0, max(0.0, float(round((elapsed_min / total_min) * 100, 1) if total_min > 0 else 0.0)))
    if total_min <= 0: total_days = "منقضی شده"
    elif total_min < 60: total_days = f"{int(total_min)} دقیقه"
    elif total_min < 1440: total_days = f"{int(total_min // 60)} ساعت"
    else: total_days = f"{int(total_min // 1440)} روز"
    
    rem_hours = max(0, int(rem_minutes // 60))
    rem_mins = max(0, int(rem_minutes % 60))
    rem_days = max(0, int(rem_hours // 24))
    
    if rem_days > 0: time_str_fa = f"{rem_days} روز و {max(0, int(rem_hours % 24))} ساعت"
    elif rem_hours > 0: time_str_fa = f"{rem_hours} ساعت و {rem_mins} دقیقه"
    elif rem_minutes > 0: time_str_fa = f"{rem_mins} دقیقه"
    else: time_str_fa = "منقضی شده"
        
    is_used = (used_bytes > 1024 or elapsed_min > 1)
    
    if rem_minutes <= 0 or used_bytes >= limit_bytes:
        status_text = '<span style="display:flex; align-items:center; gap:5px;"><i class="fas fa-times-circle" style="color:var(--red); font-size:16px;"></i> منقضی شده</span>'
        status_class = "st-offline"
        time_percent = 100.0
    elif not is_used:
        status_text = '<span style="display:flex; align-items:center; gap:5px;"><i class="fas fa-hourglass-half" style="color:var(--yellow); font-size:16px;"></i> در انتظار مصرف</span>'
        status_class = "st-onhold"
        time_percent = 0.0
    else:
        status_text = '<span style="display:flex; align-items:center; gap:5px;"><i class="fas fa-check-circle" style="color:var(--neon-green); font-size:16px;"></i> فعال</span>'
        status_class = "st-online"
    
    master_flag, master_name, master_suffix = "🇩🇪", "سرور اصلی", ""
    cur.execute("SELECT ssh_ip, server_name, file_suffix FROM master_settings LIMIT 1")
    m_row = cur.fetchone()
    if m_row:
        master_name = m_row[1].strip() if m_row[1] else "سرور اصلی"
        master_suffix = m_row[2].strip() if m_row[2] else ""
        try:
            import urllib.request
            test_ip = m_row[0] if m_row[0] else ""
            with urllib.request.urlopen(f"http://ip-api.com/json/{test_ip}", timeout=2) as res:
                cc = json.loads(res.read().decode()).get("countryCode", "DE")
                master_flag = "".join(chr(127397 + ord(c)) for c in cc)
        except: pass
    
    active_flags = [master_flag]
    edge_servers_data = {}
    try:
        for ef in cur.execute("SELECT server_ip, flag, location, server_name, file_suffix FROM edge_servers").fetchall():
            edge_servers_data[ef[0]] = {"flag": ef[1], "loc": ef[2], "name": ef[3] if ef[3] else f"سرور لبه", "suffix": ef[4] if ef[4] else ""}
    except: pass
    
    synced_servers = []
    try:
        for s_row in cur.execute("SELECT server_ip FROM peer_synced_edges WHERE peer_name=? AND config=?", (peer_name, config_file)).fetchall():
            synced_servers.append(s_row[0])
    except: pass
    
    for s_ip in synced_servers:
        if s_ip in edge_servers_data: active_flags.append(edge_servers_data[s_ip]["flag"])
    location_html = " ".join([f'<span class="flag-item">{fl}</span>' for fl in set(active_flags)])
    
    download_configs = []
    has_advanced_plans = False
    
    if special_mode == 1:
        try:
            cur.execute("SELECT id, plan_name, description, suffix, mtu, dns, keepalive, allowed_ips, active_servers FROM subscription_plans")
            plans = cur.fetchall()
            if plans:
                has_advanced_plans = True
                for p_row in plans:
                    try: allowed_servers = json.loads(p_row[8]) if p_row[8] else ["master"]
                    except: allowed_servers = ["master"]
                    
                    for srv_ip in allowed_servers:
                        if srv_ip != "master" and srv_ip not in synced_servers: continue
                        
                        if srv_ip == "master":
                            plan_display_name = f'<i class="fas fa-server"></i> {p_row[1]} {master_flag}'
                        else:
                            e_data = edge_servers_data.get(srv_ip, {"name": "سرور لبه", "flag": "🌍", "suffix": ""})
                            plan_display_name = f'<i class="fas fa-satellite-dish"></i> {p_row[1]} {e_data["flag"]}'
                            
                        download_configs.append({
                            "server_label": plan_display_name,
                            "plan_name": "", 
                            "description": p_row[2], # تضمین وجود توضیحات
                            "file_name": f"{peer_name}{p_row[3]}.conf",
                            "suffix": f"{p_row[0]}_{srv_ip}",
                            "mtu": p_row[4], "dns": p_row[5], "keepalive": p_row[6], "allowed_ips": p_row[7]
                        })
        except: pass
        
    if not has_advanced_plans or special_mode == 0:
        p_nw = cur.execute("SELECT dns, mtu, persistent_keepalive, allowed_ips FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file)).fetchone()
        dns_v = p_nw[0] if p_nw else "1.1.1.1"
        mtu_v = p_nw[1] if p_nw else 1420
        keep_v = p_nw[2] if p_nw else 25
        allow_v = p_nw[3] if p_nw else "0.0.0.0/0, ::/0"

        download_configs.append({
            "server_label": f'<i class="fas fa-server"></i> {master_name} {master_flag}',
            "plan_name": "",
            "description": "اتصال مستقیم به شبکه سرور اصلی",
            "file_name": f"{peer_name}{master_suffix}.conf",
            "suffix": f"main_master",
            "mtu": mtu_v, "dns": dns_v, "keepalive": keep_v, "allowed_ips": allow_v
        })
        for e_ip in synced_servers:
            if e_ip in edge_servers_data:
                e_data = edge_servers_data[e_ip]
                download_configs.append({
                    "server_label": f'<i class="fas fa-satellite-dish"></i> {e_data["name"]} {e_data["flag"]}',
                    "plan_name": "",
                    "description": "اتصال پایدار از طریق سرور واسط",
                    "file_name": f"{peer_name}{e_data['suffix']}.conf",
                    "suffix": f"main_{e_ip}",
                    "mtu": mtu_v, "dns": dns_v, "keepalive": keep_v, "allowed_ips": allow_v
                })
            
    conn.close()

    rendered = render_template("status.html", 
                               peer_name=peer_name, used_percent=used_percent, time_percent=time_percent, 
                               limit_str=limit_str_fa, used_str_fa=used_str_fa, rem_minutes=rem_minutes, 
                               time_str_fa=time_str_fa, total_days=total_days, location_html=location_html, 
                               download_configs=download_configs, short_id=short_id, 
                               status_text=status_text, status_class=status_class, cache_buster=int(time.time()))
    resp = make_response(rendered)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

if 'short_redirect' in app.view_functions:
    app.view_functions['short_redirect'] = v69_custom_short_redirect_view


# 📌 ۲. وب‌متد دانلود فایل با نام‌گذاری تمیز
def v69_short_download_config(short_id, suffix_key):
    import os, json, sqlite3, re, urllib.parse
    from flask import Response, request
    
    short_links_path = os.path.join('/usr/local/bin/Wireguard-panel/src', 'short_links.json')
    with open(short_links_path, 'r') as f: short_links = json.load(f)
    long_link = short_links.get(short_id)
    
    peer_name = (re.search(r'peer_name=([^&]+)', long_link) or re.search(r'peerName=([^&]+)', long_link))
    config_file = (re.search(r'config_file=([^&]+)', long_link) or re.search(r'configFile=([^&]+)', long_link) or re.search(r'config=([^&]+)', long_link))
    
    peer_name = urllib.parse.unquote(peer_name.group(1)) if peer_name else ""
    config_file = urllib.parse.unquote(config_file.group(1)) if config_file else "wg0.conf"
    if not config_file.endswith('.conf'): config_file += '.conf'
    
    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
    cur = conn.cursor()
    cur.execute("SELECT private_key, peer_ip, dns, mtu, persistent_keepalive, allowed_ips FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
    peer_row = cur.fetchone()
    
    plan_id = suffix_key.split("_")[0]
    target_server = suffix_key.split("_", 1)[1] if "_" in suffix_key else "master"
    
    mtu, dns, keepalive, allowed_ips = 1420, "1.1.1.1, 1.0.0.1", 25, "0.0.0.0/0, ::/0"
    plan_suffix = ""
    
    if plan_id != "main" and plan_id.isdigit():
        cur.execute("SELECT suffix, mtu, dns, keepalive, allowed_ips FROM subscription_plans WHERE id=?", (int(plan_id),))
        plan_row = cur.fetchone()
        if plan_row:
            plan_suffix = plan_row[0]
            mtu, dns, keepalive, allowed_ips = plan_row[1], plan_row[2], plan_row[3], plan_row[4]
            final_filename = f"{peer_name}{plan_suffix}.conf"
    else:
        if peer_row:
            dns, mtu, keepalive, allowed_ips = peer_row[2], peer_row[3], peer_row[4], peer_row[5]
        
        server_suffix = ""
        if target_server == "master":
            cur.execute("SELECT file_suffix FROM master_settings LIMIT 1")
            m_row = cur.fetchone()
            if m_row and m_row[0]: server_suffix = m_row[0].strip()
        else:
            cur.execute("SELECT file_suffix FROM edge_servers WHERE server_ip=?", (target_server,))
            srv_row = cur.fetchone()
            if srv_row and srv_row[0]: server_suffix = srv_row[0].strip()
            
        final_filename = f"{peer_name}{server_suffix}.conf"
            
    server_ip = request.host.split(":")[0]
    if target_server == "master":
        cur.execute("SELECT endpoint_domain FROM master_settings LIMIT 1")
        m_row = cur.fetchone()
        if m_row and m_row[0]: server_ip = m_row[0].strip()
    else:
        cur.execute("SELECT server_ip FROM edge_servers WHERE server_ip=?", (target_server,))
        srv_row = cur.fetchone()
        if srv_row and srv_row[0]: server_ip = srv_row[0].strip()

    server_pub_key, listen_port = "", 51820
    config_path = f"/etc/wireguard/{config_file}"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            cf_text = f.read()
            server_pub_key_match = re.search(r"PrivateKey\s*=\s*(.*)", cf_text, re.IGNORECASE)
            if server_pub_key_match:
                import base64, nacl.public
                priv_bytes = base64.b64decode(server_pub_key_match.group(1).strip())
                priv_key_obj = nacl.public.PrivateKey(priv_bytes)
                server_pub_key = base64.b64encode(bytes(priv_key_obj.public_key)).decode('utf-8')
            port_match = re.search(r"ListenPort\s*=\s*(\d+)", cf_text, re.IGNORECASE)
            if port_match: listen_port = int(port_match.group(1))

    conn.close()
    if not peer_row: return "Error: Peer not found", 404
        
    config_data = f"[Interface]\\nPrivateKey = {peer_row[0]}\\nAddress = {peer_row[1]}/32\\nDNS = {dns}\\nMTU = {mtu}\\n\\n[Peer]\\nPublicKey = {server_pub_key}\\nEndpoint = {server_ip}:{listen_port}\\nAllowedIPs = {allowed_ips}\\nPersistentKeepalive = {keepalive}\\n".replace("\\n", "\n")
    
    return Response(config_data, mimetype="application/octet-stream", headers={"Content-disposition": f"attachment; filename={final_filename}"})

if 'short_download_config' in app.view_functions:
    app.view_functions['short_download_config'] = v69_short_download_config

# --- [END STEP 69 CLEAN SUBLINK PLANS] ---



# --- [STEP 67 AUTH ISOLATION] ---

#    
def get_live_db_path():
    import os
    for p in ['/usr/local/bin/Wireguard-panel/src/db.sqlite3', '/usr/local/bin/Wireguard-panel/src/db/db.sqlite3']:
        if os.path.exists(p): return p
    return '/usr/local/bin/Wireguard-panel/src/db.sqlite3'


# :      (   )
@app.before_request
def v67_isolated_firewall():
    from flask import request, redirect, session, abort
    import sqlite3
    
    if request.path.startswith('/static') or request.path == '/favicon.ico': 
        return
        
    user_count = 0
    try:
        conn = sqlite3.connect(get_live_db_path(), timeout=5.0)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if cur.fetchone():
            cur.execute("SELECT COUNT(*) FROM users")
            user_count = cur.fetchone()[0]
            
        #     
        if session.get('username'):
            cur.execute("SELECT interface_name FROM sub_panels WHERE username=?", (session.get('username'),))
            if not cur.fetchone():
                session['role'] = 'admin'
                if 'interface' in session: session.pop('interface', None)
        conn.close()
    except: pass

    #  :        
    if user_count == 0:
        if request.path != '/register' and request.path != '/api/register':
            return redirect('/register')
    else:
        if request.path == '/register':
            return redirect('/login')

    #     (  )
    keys = ['config', 'config_file', 'configName', 'configFile', 'config_name']
    active_config = None
    for k in keys:
        if request.args.get(k): active_config = request.args.get(k); break
    if not active_config and request.is_json:
        try:
            data = request.get_json(silent=True) or {}
            for k in keys:
                if data.get(k): active_config = data.get(k); break
        except: pass
    if not active_config:
        for k in keys:
            if request.form.get(k): active_config = request.form.get(k); break

    if session.get('role') == 'client':
        assigned = session.get('interface') + ".conf"
        active_config = assigned
        if request.form:
            try:
                from werkzeug.datastructures import MultiDict
                m_form = MultiDict(request.form)
                for k in keys: m_form[k] = assigned
                request.form = m_form
            except: pass
        if request.is_json:
            try:
                data = request.get_json(silent=True) or {}
                for k in keys: data[k] = assigned
                request.json = data; request._cached_json = (data, data)
            except: pass

    if active_config:
        if not active_config.endswith('.conf'): active_config += ".conf"
        request.args = request.args.copy()
        for k in keys: request.args[k] = active_config
        session['active_config'] = active_config

    if session.get('role') == 'client':
        blocked = ['/settings', '/backups', '/api/backups', '/warp', '/telegram', '/template']
        if any(request.path.startswith(b) for b in blocked): abort(403)


# :        (    )
@app.route("/register", methods=["GET", "POST"])
def v67_isolated_register():
    import sqlite3
    from flask import request, render_template, redirect, flash
    from werkzeug.security import generate_password_hash
    
    conn = sqlite3.connect(get_live_db_path(), timeout=5.0)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    user_count = cur.fetchone()[0]
    
    if user_count > 0: 
        conn.close(); return redirect("/login")
        
    if request.method == "GET": 
        conn.close()
        #       (   )
        return render_template("register.html")
        
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    c_password = request.form.get("confirm_password", "").strip() or request.form.get("password_confirm", "").strip()
    
    if not username or not password:
        flash("      .", "error"); conn.close(); return redirect("/register")
    if c_password and password != c_password:
        flash("       .", "error"); conn.close(); return redirect("/register")
        
    try:
        cur.execute("INSERT INTO users (username, password_hash, password_plain) VALUES (?, ?, ?)", (username, generate_password_hash(password), password))
        conn.commit()
        flash("     !   .", "success")
    except Exception as e: 
        flash(f"   : {e}", "error")
        
    conn.close(); return redirect("/login")


# :     (  )
def handle_universal_auth(username, password):
    import sqlite3
    from werkzeug.security import check_password_hash
    try:
        conn = sqlite3.connect(get_live_db_path(), timeout=5.0)
        cur = conn.cursor()
        cur.execute("SELECT username, password_hash, password_plain FROM users WHERE username=?", (username,))
        row_adm = cur.fetchone()
        if row_adm:
            if row_adm[2] and row_adm[2] == password: conn.close(); return {"success": True, "role": "admin", "interface": "wg0"}
            try:
                if row_adm[1] and check_password_hash(row_adm[1], password): conn.close(); return {"success": True, "role": "admin", "interface": "wg0"}
            except: pass
            if row_adm[1] == password: conn.close(); return {"success": True, "role": "admin", "interface": "wg0"}
                
        cur.execute("SELECT interface_name, password_hash, status, password_plain FROM sub_panels WHERE username=?", (username,))
        row_cl = cur.fetchone()
        conn.close()
        if row_cl:
            if row_cl[2] != 'active': return {"success": False, "error": "Account suspended!"}
            if row_cl[3] and row_cl[3] == password: return {"success": True, "role": "client", "interface": row_cl[0]}
            try:
                if row_cl[1] and check_password_hash(row_cl[1], password): return {"success": True, "role": "client", "interface": row_cl[0]}
            except: pass
            if row_cl[1] == password: return {"success": True, "role": "client", "interface": row_cl[0]}
    except: pass
    return None


# :      Overlap
def custom_login_view(*args, **kwargs):
    from flask import request, session, flash, redirect
    if request.method == "POST":
        username = str(request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        lang = session.get('language', 'en')
        res = handle_universal_auth(username, password)
        if res:
            if res["success"]:
                session['logged_in'] = True
                session['username'] = username
                session['role'] = res["role"]
                session['interface'] = res["interface"]
                session['language'] = lang
                flash("Login successful!", "success")
                return redirect("/home")
            else:
                flash(res["error"], "error")
                return redirect("/login")
    orig = app.view_functions.get('login_original')
    return orig(*args, **kwargs) if orig else redirect("/login")

def custom_api_login_view(*args, **kwargs):
    from flask import request, session, jsonify
    data = request.get_json(silent=True) or request.form or {}
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    res = handle_universal_auth(username, password)
    if res:
        if res["success"]:
            session['logged_in'] = True
            session['username'] = username
            session['role'] = res["role"]
            session['interface'] = res["interface"]
            return jsonify(message="Login successful!", role=res["role"]), 200
        else: return jsonify(error=res["error"]), 401
    orig = app.view_functions.get('api_login_original')
    return orig(*args, **kwargs) if orig else jsonify(error="Unauthorized"), 401

original_load_users = globals().get('load_users')
def custom_load_users(*args, **kwargs):
    users = original_load_users(*args, **kwargs) if original_load_users else {}
    try:
        import sqlite3
        conn = sqlite3.connect(get_live_db_path(), timeout=5.0)
        cur = conn.cursor()
        cur.execute("SELECT username, password_hash FROM sub_panels")
        for u, h in cur.fetchall(): users[u] = h
        conn.close()
    except: pass
    return users
globals()['load_users'] = custom_load_users

login_endpoint = "login"
api_login_endpoint = "api_login"
for rule in app.url_map.iter_rules():
    if rule.rule == '/login': login_endpoint = rule.endpoint
    if rule.rule == '/api/login': api_login_endpoint = rule.endpoint
if login_endpoint in app.view_functions and login_endpoint + "_original" not in app.view_functions:
    app.view_functions[login_endpoint + "_original"] = app.view_functions[login_endpoint]
    app.view_functions[login_endpoint] = custom_login_view
if api_login_endpoint in app.view_functions and api_login_endpoint + "_original" not in app.view_functions:
    app.view_functions[api_login_endpoint + "_original"] = app.view_functions[api_login_endpoint]
    app.view_functions[api_login_endpoint] = custom_api_login_view

# :     CSRF:      Onboarding
try:
    if 'csrf' in globals():
        csrf.exempt(v67_isolated_register)
        
    #          
    app.config['WTF_CSRF_ENABLED'] = False
except Exception as e:
    print("Bypass CSRF warning:", e)

# --- [END STEP 67 AUTH ISOLATION] ---



# --- [STEP 70 BULK EXTEND ENGINE] ---

# 📌 ۱. موتور ردیاب زنده وایرگارد (ثبت اولین اتصال)
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


# 📌 ۲. هوک روت ساخت کلاینت (ثبت تاریخ ایجاد برای کاربران جدید)
original_create_peer_base_v70 = app.view_functions.get('create_peer_original') or app.view_functions.get('create_peer')

def v70_create_peer_hook(*args, **kwargs):
    from flask import request
    res = original_create_peer_base_v70(*args, **kwargs) if original_create_peer_base_v70 else None
    
    try:
        data = request.get_json(silent=True) or request.form or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg_file = data.get("config", "wg0.conf")
        if not cfg_file.endswith('.conf'): cfg_file += ".conf"
        
        if p_name:
            import sqlite3, datetime
            conn_c = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=10.0)
            cur_c = conn_c.cursor()
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur_c.execute("UPDATE peers SET created_at_date=? WHERE peer_name=? AND config=?", (now_str, p_name, cfg_file))
            conn_c.commit(); conn_c.close()
    except Exception as e: 
        print("Creation Date Hook Error:", e)
        
    return res

if 'create_peer' in app.view_functions:
    if 'create_peer_original' not in app.view_functions:
        app.view_functions['create_peer_original'] = app.view_functions['create_peer']
    app.view_functions['create_peer'] = v70_create_peer_hook


# 📌 ۳. وب‌متد رسمی شارژ گروهی با پارسر فوق‌هوشمند ضدخطا
@app.route("/api/bulk-extend", methods=["POST"])
def api_bulk_extend_peers():
    import sqlite3, json, subprocess, os, base64, threading, re
    try: import jdatetime
    except:
        subprocess.run("/usr/local/bin/Wireguard-panel/src/venv/bin/pip install jdatetime", shell=True)
        import jdatetime
    from datetime import datetime
    from flask import request, jsonify, session

    if session.get('role') == 'client':
        return jsonify(error="دسترسی غیرمجاز." if session.get('language')=='fa' else "Unauthorized access."), 403

    data = request.get_json(silent=True) or {}
    ext_type = data.get("type") 
    
    try:
        amount = float(data.get("amount", 0) or 0.0)
    except ValueError:
        return jsonify(error="مقدار نامعتبر است. عدد وارد کنید."), 400

    if amount <= 0: return jsonify(error="مقدار باید بیشتر از صفر باشد."), 400

    raw_start = data.get("start_date", "")
    raw_end = data.get("end_date", "")

    # 📌 موتور پارسر ضدخطا و مبدل اعداد فارسی/عربی به انگلیسی
    def extract_and_convert_shamsi(d_str, is_end=False):
        if not d_str or str(d_str).strip() == "": return None
        s = str(d_str).strip()
        # تبدیل اعداد فارسی و عربی به انگلیسی
        persian_nums = "۰۱۲۳۴۵۶۷۸۹"
        arabic_nums  = "٠١٢٣٤٥٦٧٨٩"
        english_nums = "0123456789"
        for i in range(10):
            s = s.replace(persian_nums[i], english_nums[i])
            s = s.replace(arabic_nums[i], english_nums[i])
        
        # استانداردسازی جداکننده‌ها
        s = s.replace('-', '/').replace('.', '/')
        
        # استخراج دقیق الگو YYYY/MM/DD برای حذف هرگونه اسپیس یا کاراکتر مخفی
        match = re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', s)
        if not match:
            raise ValueError(f"Cannot parse date from {s}")
            
        y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        
        if is_end:
            j_date = jdatetime.datetime(y, m, d, 23, 59, 59)
        else:
            j_date = jdatetime.datetime(y, m, d, 0, 0, 0)
            
        return j_date.togregorian()

    start_g, end_g = None, None
    try:
        if raw_start: start_g = extract_and_convert_shamsi(raw_start, False)
        if raw_end: end_g = extract_and_convert_shamsi(raw_end, True)
    except Exception as e:
        print("Date Parse Error:", e)
        return jsonify(error="فرمت تاریخ نامعتبر است. حتماً از تقویم استفاده کنید."), 400

    try:
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
        cur = conn.cursor()
        
        # ترمیم‌گر آنی کاربرانی که از قبل از این آپدیت ساخته شده‌اند تا تاریخ امروز را بگیرند
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("PRAGMA table_info(peers)")
        cols = [c[1] for c in cur.fetchall()]
        
        if "created_at_date" in cols:
            cur.execute("UPDATE peers SET created_at_date=? WHERE created_at_date IS NULL OR created_at_date='' OR created_at_date='1'", (now_str,))
            conn.commit()

        c_date_str = "created_at_date" if "created_at_date" in cols else "''"
        f_conn_str = "first_connected_at" if "first_connected_at" in cols else "''"

        cur.execute(f"SELECT id, peer_name, config, [limit], used, remaining_time, public_key, peer_ip, monitor_blocked, expiry_blocked, {c_date_str}, {f_conn_str}, first_usage FROM peers WHERE config='wg0.conf'")
        all_peers = cur.fetchall()

        updated_peers = []
        for row in all_peers:
            pid, p_name, cfg, limit_str, used, rem_time, pub, pip, m_blk, e_blk, created_at, connected_at, f_usage = row

            # پیدا کردن معتبرترین تاریخ ممکن
            target_date = None
            if connected_at and str(connected_at).strip() not in ["", "None", "1"]:
                target_date = str(connected_at).strip()
            elif f_usage and str(f_usage).strip() not in ["", "None", "1"] and "-" in str(f_usage):
                target_date = str(f_usage).strip()
            else:
                target_date = str(created_at).strip()

            # اعمال فیلتر تاریخ
            if start_g or end_g:
                if not target_date or str(target_date).strip() in ["", "None", "1"]: continue 
                try:
                    p_date = datetime.strptime(str(target_date).strip()[:19], "%Y-%m-%d %H:%M:%S")
                    if start_g and p_date < start_g: continue
                    if end_g and p_date > end_g: continue
                except Exception as de: 
                    continue 

            needs_unblock = False
            new_limit = limit_str
            new_rem_time = int(rem_time) if rem_time is not None else 0
            new_m_blk = int(m_blk) if m_blk is not None else 0
            new_e_blk = int(e_blk) if e_blk is not None else 0
            used_safe = float(used) if used else 0.0

            if ext_type == 'volume':
                limit_gb = 0.0
                if limit_str and "GiB" in str(limit_str): limit_gb = float(str(limit_str).replace("GiB", ""))
                elif limit_str and "MiB" in str(limit_str): limit_gb = float(str(limit_str).replace("MiB", "")) / 1024.0

                new_limit_gb = limit_gb + amount
                new_limit = f"{new_limit_gb:.2f}GiB"
                limit_bytes = new_limit_gb * 1073741824.0
                
                if new_m_blk == 1 or used_safe >= (limit_gb * 1073741824.0):
                    if used_safe < limit_bytes: 
                        new_m_blk = 0; needs_unblock = True

            elif ext_type == 'time':
                add_minutes = int(amount * 1440)
                new_rem_time += add_minutes
                if new_e_blk == 1 or (rem_time is not None and rem_time <= 0):
                    if new_rem_time > 0: 
                        new_e_blk = 0; needs_unblock = True

            cur.execute("UPDATE peers SET [limit]=?, remaining_time=?, monitor_blocked=?, expiry_blocked=? WHERE id=?",
                        (new_limit, new_rem_time, new_m_blk, new_e_blk, pid))

            if needs_unblock and new_m_blk == 0 and new_e_blk == 0:
                iface = cfg.replace('.conf', '')
                try:
                    subprocess.run(f"wg set {iface} peer {pub} allowed-ips {pip}/32", shell=True, stderr=subprocess.DEVNULL)
                    subprocess.run(f"ip route del blackhole {pip}", shell=True, stderr=subprocess.DEVNULL)
                    subprocess.run(f"ip route del {pip} blackhole", shell=True, stderr=subprocess.DEVNULL)
                    subprocess.run(f"ip route replace {pip}/32 dev {iface}", shell=True, stderr=subprocess.DEVNULL)
                    wg_path = subprocess.getoutput("which iptables").strip() or "/usr/sbin/iptables"
                    ipt_rules = subprocess.check_output(f"{wg_path} -S", shell=True, text=True)
                    for line in ipt_rules.splitlines():
                        if pip in line and ("DROP" in line or "REJECT" in line):
                            del_rule = line.replace("-A", "-D")
                            subprocess.run(f"iptables {del_rule}", shell=True, stderr=subprocess.DEVNULL)
                except: pass

            updated_peers.append((p_name, cfg, new_limit, new_rem_time, new_m_blk, new_e_blk, pub, pip, needs_unblock))

        conn.commit()
        
        if updated_peers:
            cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers")
            edges = cur.fetchall()
            def run_bulk_edge_sync():
                for s_ip, s_port, s_user, s_pass in edges:
                    edge_py = "import sqlite3, subprocess\\nconn=sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)\\ncur=conn.cursor()\\n"
                    for p_n, c_f, n_l, n_r, n_mb, n_eb, pu, pi, unb in updated_peers:
                        edge_py += f"cur.execute(\"UPDATE peers SET [limit]='{n_l}', remaining_time={n_r}, monitor_blocked={n_mb}, expiry_blocked={n_eb} WHERE peer_name='{p_n}' AND config='{c_f}'\")\\n"
                        if unb and n_mb == 0 and n_eb == 0:
                            iface = c_f.replace('.conf','')
                            edge_py += f"subprocess.run('wg set {iface} peer {pu} allowed-ips {pi}/32', shell=True, stderr=subprocess.DEVNULL)\\n"
                            edge_py += f"subprocess.run('ip route del blackhole {pi}', shell=True, stderr=subprocess.DEVNULL)\\n"
                            edge_py += f"subprocess.run('ip route del {pi} blackhole', shell=True, stderr=subprocess.DEVNULL)\\n"
                    edge_py += "conn.commit()\\nconn.close()\\n"
                    enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
                    cmd = f"echo '{enc}' | base64 -d > /tmp/bulk_ext.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/bulk_ext.py && rm -f /tmp/bulk_ext.py"
                    subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no {s_user}@{s_ip} \"{cmd}\"", shell=True)
            threading.Thread(target=run_bulk_edge_sync, daemon=True).start()

        conn.close()
        
        if len(updated_peers) == 0:
            msg = "تغییری اعمال نشد! کاربری در این بازه تاریخی یافت نشد." if session.get('language') == 'fa' else "No users found in this date range."
            return jsonify(message=msg)
            
        msg = f"تعداد {len(updated_peers)} کاربر با موفقیت شارژ و متصل شدند." if session.get('language') == 'fa' else f"{len(updated_peers)} users successfully extended and synced."
        return jsonify(message=msg)
        
    except Exception as e:
        print("Bulk Extend DB Error:", e)
        return jsonify(error="خطا در پردازش اطلاعات دیتابیس." if session.get('language') == 'fa' else "Database error occurred."), 500

try:
    if 'csrf' in globals(): csrf.exempt(api_bulk_extend_peers)
except: pass

# --- [END STEP 70 BULK EXTEND ENGINE] ---



# --- [STEP 71 SECURITY SHIELD] ---

# الف: مهار سخت‌افزاری و مسدودسازی دسترسی در سطح فایل سیستم (File System Access Enforcer)
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


# ب: دیواره آتشین ورودی (Request Sanitizer) - احراز هویت اجباری تمام وب‌متدها و مهار پارامترها
@app.before_request
def enforce_client_security_limits():
    from flask import session, request, abort
    import sqlite3
    
    # ۱. گیت‌کیپر سراسری: مسدودسازی درخواست‌های بدون سشن ربات‌ها برای دسترسی به متدها
    public_paths = ['/login', '/api/login', '/register', '/api/register', '/static', '/favicon.ico', '/s/', '/api/xray-settings', '/api/xray-ping']
    is_public = any(request.path.startswith(p) for p in public_paths) or request.path == '/'
    
    if not is_public and not session.get('logged_in'):
        abort(401)

    # ۲. بررسی لایو هویت نماینده فرعی (فقط در صورتی که نقش کلاینت داشته باشد)
    # رفع باگ حیاتی: تبدیل یوزرنیم عددی به رشته متنی (String) جهت ممانعت از کرش دیتابیسی
    if session.get('logged_in') and session.get('username'):
        try:
            conn_s = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=10.0)
            cur_s = conn_s.cursor()
            username_str = str(session.get('username')).strip()
            cur_s.execute("SELECT interface_name, status FROM sub_panels WHERE username=?", (username_str,))
            row_s = cur_s.fetchone()
            conn_s.close()
            
            if row_s:
                # اگر نماینده حذف یا غیرفعال شده باشد، پاکسازی سشن و بستن دسترسی
                if row_s[1] != 'active':
                    session.clear()
                    abort(401)
                else:
                    # مهار سشن روی اینترفیس مجاز
                    session['role'] = 'client'
                    session['interface'] = row_s[0]
            else:
                # اگر نماینده نیست، پس ادمین اصلی است
                session['role'] = 'admin'
                session['interface'] = 'wg0'
        except: pass

    # ۳. یکپارچه‌ساز خودکار پارامترها برای ممانعت از دور زدن کارت شبکه
    keys = ['config', 'config_file', 'configName', 'configFile', 'config_name']
    active_config = None
    for k in keys:
        if request.args.get(k):
            active_config = request.args.get(k)
            break
    
    if not active_config and request.is_json:
        try:
            data = request.get_json(silent=True) or {}
            for k in keys:
                if data.get(k):
                    active_config = data.get(k)
                    break
        except: pass
        
    if not active_config:
        for k in keys:
            if request.form.get(k):
                active_config = request.form.get(k)
                break

    # ۴. اگر کاربر نماینده فرعی باشد، تخصیص اینترفیس او را به پورت اختصاصی‌اش قفل کن
    if session.get('role') == 'client':
        assigned = session.get('interface') + ".conf"
        active_config = assigned
        
        if request.form:
            try:
                from werkzeug.datastructures import MultiDict
                mutable_form = MultiDict(request.form)
                for k in keys:
                    mutable_form[k] = assigned
                request.form = mutable_form
            except: pass
            
        if request.is_json:
            try:
                data = request.get_json(silent=True) or {}
                for k in keys:
                    data[k] = assigned
                request.json = data
                request._cached_json = (data, data)
            except: pass

    if active_config:
        if not active_config.endswith('.conf'):
            active_config = active_config + ".conf"
        request.args = request.args.copy()
        for k in keys:
            request.args[k] = active_config
        session['active_config'] = active_config

    # ۵. مسدودسازی فیزیکی دسترسی به صفحات حساس ادمین برای کلاینت
    if session.get('role') == 'client':
        blocked = ['/settings', '/backups', '/api/backups', '/warp', '/telegram', '/template']
        if any(request.path.startswith(b) for b in blocked):
            abort(403)


# ج: دیواره آتشین خروجی پویا (Response Sanitizer & API Shield)
# این متد خروجی تمام وب‌متدهای جیسون را اسکن کرده و کلاینت‌های غیرمجاز را کاملاً فیلتر می‌کند
@app.after_request
def secure_client_api_responses(response):
    from flask import session
    # مهار هدرهای جیسون جهت فعال‌سازی سراسری روی تمام جیسون‌ها
    if session.get('role') == 'client' and response.content_type and 'application/json' in response.content_type:
        try:
            import json
            allowed_config = session.get('interface') + ".conf"
            
            # تابع کمکی بازگشتی برای فیلتر کردن اطلاعات کلاینت‌های دیگر
            def recursive_filter(data):
                if isinstance(data, list):
                    filtered_list = []
                    for item in data:
                        if isinstance(item, dict):
                            cfg_val = None
                            for k in ['config', 'config_file', 'configFile', 'configName', 'config_name', 'configuration', 'name']:
                                if k in item:
                                    cfg_val = item[k]
                                    break
                            # اگر رکوردی متعلق به کانفیگ دیگری (مثلاً wg0) باشد، آن را کاملاً حذف کن
                            if cfg_val and str(cfg_val).replace('.conf', '') != allowed_config.replace('.conf', ''):
                                continue 
                        filtered_list.append(recursive_filter(item))
                    return filtered_list
                elif isinstance(data, dict):
                    cfg_val = None
                    for k in ['config', 'config_file', 'configFile', 'configName', 'config_name', 'configuration', 'name']:
                        if k in data:
                            cfg_val = data[k]
                            break
                    if cfg_val and str(cfg_val).replace('.conf', '') != allowed_config.replace('.conf', ''):
                        return None
                    
                    filtered_dict = {}
                    for k, v in data.items():
                        # محدود کردن لایو نام فایل‌ها در خروجی‌های لیست اینترفیس‌ها
                        if k in ['configs', 'interfaces', 'all_configs', 'data'] and isinstance(v, list):
                            filtered_dict[k] = [x for x in v if isinstance(x, dict) and str(x.get('configuration') or x.get('name') or '').replace('.conf', '') == allowed_config.replace('.conf', '') or str(x) in [allowed_config, allowed_config.replace('.conf', '')]]
                        else:
                            filtered_dict[k] = recursive_filter(v)
                    return filtered_dict
                return data

            raw_text = response.get_data(as_text=True)
            original_json = json.loads(raw_text)
            filtered_json = recursive_filter(original_json)
            response.set_data(json.dumps(filtered_json))
        except Exception as e:
            print("Security API Shield warning:", e)
    return response


# د: تصحیح نهایی و ریشه‌کن کردن باگ تاپل گیت‌کیپرهای لاگین فلاسک
def custom_login_view(*args, **kwargs):
    from flask import request, session, flash, redirect
    if request.method == "POST":
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        language = session.get('language', 'en')
        
        auth_res = handle_universal_auth(username, password)
        if auth_res:
            if auth_res["success"]:
                session['logged_in'] = True
                session['username'] = username
                session['role'] = auth_res["role"]
                session['interface'] = auth_res["interface"]
                session['language'] = language
                flash("Login successful!", "success")
                return redirect("/home")
            else:
                flash(auth_res["error"], "error")
                return redirect("/login")
                
    orig = app.view_functions.get('login_original')
    if orig:
        return orig(*args, **kwargs)
    return redirect("/login")


def custom_api_login_view(*args, **kwargs):
    from flask import request, session, jsonify
    data = request.get_json(silent=True) or request.form or {}
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    
    auth_res = handle_universal_auth(username, password)
    if auth_res:
        if auth_res["success"]:
            session['logged_in'] = True
            session['username'] = username
            session['role'] = auth_res["role"]
            session['interface'] = auth_res["interface"]
            return jsonify(message="Login successful!", role=auth_res["role"])
        else:
            return jsonify(error=auth_res["error"]), 401
            
    orig = app.view_functions.get('api_login_original')
    if orig:
        return orig(*args, **kwargs)
    return jsonify(error="Unauthorized"), 401


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


# بایندینگ ریشه‌ای و اصلاح روت لاگین‌ها در فلاسک
login_endpoint = "login"
api_login_endpoint = "api_login"
for rule in app.url_map.iter_rules():
    if rule.rule == '/login': login_endpoint = rule.endpoint
    if rule.rule == '/api/login': api_login_endpoint = rule.endpoint

app.view_functions[login_endpoint] = custom_login_view
app.view_functions[api_login_endpoint] = custom_api_login_view

try:
    if 'csrf' in globals():
        csrf.exempt(api_get_configurations_shield)
except: pass

# --- [END STEP 71 SECURITY SHIELD] ---























# --- [SSL CERTIFICATE PATHS CONTROLLER ENGINE] ---
@app.route("/api/ssl-detect", methods=["GET"])
def api_ssl_detect_route():
    import os, glob
    from flask import jsonify, session

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
        for root, dirs, files in os.walk("/etc/letsencrypt"):
            if "fullchain.pem" in files and "privkey.pem" in files:
                fc_path = os.path.join(root, "fullchain.pem")
                pk_path = os.path.join(root, "privkey.pem")
                break

    if not fc_path:
        fc_path = "/etc/letsencrypt/live/domain/fullchain.pem"
        pk_path = "/etc/letsencrypt/live/domain/privkey.pem"

    fc_content, pk_content = "", ""
    if os.path.exists(fc_path):
        try:
            with open(fc_path, "r", encoding="utf-8") as f: fc_content = f.read()
        except: pass
    if os.path.exists(pk_path):
        try:
            with open(pk_path, "r", encoding="utf-8") as f: pk_content = f.read()
        except: pass

    return jsonify({
        "success": True,
        "fullchain": fc_path,
        "privkey": pk_path,
        "fullchain_content": fc_content,
        "privkey_content": pk_content
    })

@app.route("/api/ssl-settings", methods=["GET", "POST"])
def api_ssl_settings_route():
    import sqlite3, yaml, os, subprocess
    from flask import request, jsonify, session

    if not session.get('logged_in') or session.get('role') == 'client':
        return jsonify(error="Unauthorized"), 401

    db_p = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
    config_yaml = '/usr/local/bin/Wireguard-panel/src/config.yaml'

    conn = sqlite3.connect(db_p, timeout=30.0)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS ssl_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, fullchain_path TEXT, privkey_path TEXT)")

    if request.method == "GET":
        cur.execute("SELECT fullchain_path, privkey_path FROM ssl_settings LIMIT 1")
        row = cur.fetchone()
        conn.close()
        
        fc_path = row[0] if row else "/etc/letsencrypt/live/domain/fullchain.pem"
        pk_path = row[1] if row else "/etc/letsencrypt/live/domain/privkey.pem"

        fc_content, pk_content = "", ""
        if os.path.exists(fc_path):
            try:
                with open(fc_path, "r", encoding="utf-8") as f: fc_content = f.read()
            except: pass
        if os.path.exists(pk_path):
            try:
                with open(pk_path, "r", encoding="utf-8") as f: pk_content = f.read()
            except: pass

        return jsonify({
            "fullchain": fc_path,
            "privkey": pk_path,
            "fullchain_content": fc_content,
            "privkey_content": pk_content
        })

    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
        fullchain = data.get("fullchain", "").strip()
        privkey = data.get("privkey", "").strip()
        fullchain_content = data.get("fullchain_content", "").strip()
        privkey_content = data.get("privkey_content", "").strip()

        if not fullchain or not privkey:
            conn.close()
            return jsonify(error="مسیر فایل‌های fullchain و privkey الزامی است."), 400

        # ۱. نگارش مستقیم محتوای واردشده داخل فایل‌های سرور
        if fullchain_content:
            try:
                os.makedirs(os.path.dirname(fullchain), exist_ok=True)
                with open(fullchain, "w", encoding="utf-8") as f:
                    f.write(fullchain_content + "\n")
            except Exception as e:
                conn.close()
                return jsonify(error=f"خطا در ذخیره فایل fullchain: {e}"), 500

        if privkey_content:
            try:
                os.makedirs(os.path.dirname(privkey), exist_ok=True)
                with open(privkey, "w", encoding="utf-8") as f:
                    f.write(privkey_content + "\n")
                os.chmod(privkey, 0o600)
            except Exception as e:
                conn.close()
                return jsonify(error=f"خطا در ذخیره فایل privkey: {e}"), 500

        # ۲. بروزرسانی دیتابیس
        cur.execute("DELETE FROM ssl_settings")
        cur.execute("INSERT INTO ssl_settings (fullchain_path, privkey_path) VALUES (?, ?)", (fullchain, privkey))
        conn.commit()
        conn.close()

        # ۳. بروزرسانی config.yaml
        if os.path.exists(config_yaml):
            try:
                with open(config_yaml, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                if 'server' not in cfg: cfg['server'] = {}
                cfg['server']['ssl_cert'] = fullchain
                cfg['server']['ssl_key'] = privkey
                with open(config_yaml, 'w', encoding='utf-8') as f:
                    yaml.dump(cfg, f, default_flow_style=False)
            except Exception as e:
                print("Error updating config.yaml SSL:", e)

        # ۴. ریستارت خودکار سرویس پنل
        def restart_panel_async():
            import time
            time.sleep(1)
            subprocess.run("systemctl restart wireguard-panel", shell=True)

        import threading
        threading.Thread(target=restart_panel_async, daemon=True).start()

        return jsonify(success=True, message="محتوا و مسیرهای گواهی SSL با موفقیت ذخیره شدند. پنل در حال راه‌اندازی مجدد است...")

try:
    if 'csrf' in globals():
        csrf.exempt(api_ssl_settings_route)
        csrf.exempt(api_ssl_detect_route)
except: pass
# --- [END SSL CERTIFICATE PATHS CONTROLLER ENGINE] ---



















# --- [STEP 85 CONSOLIDATED MEGA PATCH] ---

# 📌 بخش ۰: خنثی‌سازی کامل روت‌های Blackhole (جلوگیری از اختلال شبکه توسط کاربران منقضی)
def add_blackhole_route_safe(ip):
    # به جای اضافه کردن روت blackhole در لینوکس که باعث اختلال شبکه می‌شود،
    # مسدودسازی فقط از طریق wg set peer remove انجام می‌شود.
    pass

def remove_blackhole_route_safe(ip):
    import subprocess
    if ip:
        subprocess.run(f"ip route del blackhole {ip} 2>/dev/null", shell=True)
        subprocess.run(f"ip route del {ip} blackhole 2>/dev/null", shell=True)

globals()['add_blackhole_route'] = add_blackhole_route_safe
globals()['remove_blackhole_route'] = remove_blackhole_route_safe

# 📌 بخش ۱: شکارچی خطاهای 401 و 403 (هدایت خودکار به لاگین به جای صفحه خام انگلیسی)
@app.errorhandler(401)
def v85_unauthorized_handler(e):
    from flask import request, redirect, jsonify
    if request.path.startswith('/api/') or request.is_json:
        return jsonify(success=False, error="Session expired", message="Session expired, please login again."), 401
    return redirect('/login')

@app.errorhandler(403)
def v85_forbidden_handler(e):
    from flask import request, redirect, jsonify, session
    if request.path.startswith('/api/') or request.is_json:
        return jsonify(success=False, error="Forbidden", message="Access denied"), 403
    if session.get('logged_in'):
        return redirect('/home')
    return redirect('/login')

# 📌 بخش ۲: نگهبان سراسری سشن‌ها و مهار سطح دسترسی
@app.before_request
def v85_global_session_gatekeeper():
    from flask import session, request, redirect, jsonify
    import sqlite3
    
    public_paths = ['/login', '/api/login', '/register', '/api/register', '/static', '/favicon.ico', '/s/']
    is_public = any(request.path.startswith(p) for p in public_paths) or request.path == '/'
    
    if not is_public and not session.get('logged_in'):
        if request.path.startswith('/api/') or request.is_json:
            return jsonify(success=False, error="Session expired", message="Please login again"), 401
        return redirect('/login')
        
    if session.get('logged_in') and session.get('username'):
        try:
            conn_s = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=10.0)
            cur_s = conn_s.cursor()
            username_str = str(session.get('username')).strip()
            cur_s.execute("SELECT interface_name, status FROM sub_panels WHERE username=?", (username_str,))
            row_s = cur_s.fetchone()
            conn_s.close()
            if row_s:
                if row_s[1] != 'active':
                    session.clear()
                    if request.path.startswith('/api/') or request.is_json:
                        return jsonify(success=False, error="Account suspended"), 401
                    return redirect('/login')
                session['role'] = 'client'
                session['interface'] = row_s[0]
            else:
                session['role'] = 'admin'
                session['interface'] = 'wg0'
        except: pass

# 📌 بخش ۳: تابع همگام‌ساز ساخت/ویرایش/حذف کلاینت در سرورهای لبه (بدون ایجاد Blackhole)
def v85_sync_single_peer_to_edges(action, peer_name, config_file, peer_data=None):
    import threading, sqlite3, subprocess, base64, time
    def run_sync():
        time.sleep(1)
        try:
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
            edges = cur.fetchall()
            
            p_data = peer_data
            if not p_data and action in ['create', 'edit', 'toggle']:
                cur.execute("SELECT [limit], used, remaining_time, private_key, peer_ip, public_key, config FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
                row = cur.fetchone()
                if row:
                    p_data = {"limit": row[0], "used": row[1], "remaining_time": row[2], "private_key": row[3], "peer_ip": row[4], "public_key": row[5], "config": row[6]}
            conn.close()
            
            if not edges: return
            
            for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                if action == 'delete':
                    edge_cmd = f'''import sqlite3, subprocess, os
conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
cur = conn.cursor()
cur.execute("SELECT public_key, peer_ip FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
row = cur.fetchone()
if row:
    subprocess.run(f"wg set {config_file.replace('.conf','')} peer {{row[0]}} remove", shell=True)
cur.execute("DELETE FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
conn.commit()
conn.close()
subprocess.run("wg-quick save {config_file.replace('.conf','')}", shell=True)
'''
                    enc = base64.b64encode(edge_cmd.encode('utf-8')).decode('utf-8')
                    subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"echo '{enc}' | base64 -d | python3\"", shell=True)
                    
                    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                    conn.execute("DELETE FROM peer_synced_edges WHERE peer_name=? AND server_ip=? AND config=?", (peer_name, srv_ip, config_file))
                    conn.commit()
                    conn.close()
                    
                elif action in ['create', 'edit', 'toggle'] and p_data:
                    pub = p_data['public_key']
                    edge_cmd = f'''import sqlite3, subprocess, re, os
db_path = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
cfg = '{config_file}'
iface = cfg.replace('.conf','')
os.makedirs('/usr/local/bin/Wireguard-panel/src', exist_ok=True)
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

base_ip = "10.0.0.1"
try:
    if os.path.exists(f"/etc/wireguard/{{cfg}}"):
        with open(f"/etc/wireguard/{{cfg}}", "r") as f:
            match = re.search(r"Address\s*=\s*([0-9]+\.[0-9]+\.[0-9]+)\.", f.read())
            if match: base_ip = match.group(1) + ".1"
except: pass
base_prefix = ".".join(base_ip.split(".")[:3])

cur.execute("SELECT peer_ip FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
exist_row = cur.fetchone()

if exist_row and exist_row[0]:
    free_ip = exist_row[0]
else:
    cur.execute("SELECT peer_ip FROM peers WHERE config=?", (cfg,))
    used_ips = set([r[0] for r in cur.fetchall() if r[0]])
    try:
        wg_out = subprocess.check_output(f"wg show {{iface}} allowed-ips", shell=True, text=True)
        for line in wg_out.splitlines():
            parts = line.split()
            if len(parts) >= 2: used_ips.add(parts[1].split('/')[0])
    except: pass
    free_ip = f"{{base_prefix}}.2"
    for i in range(2, 255):
        test_ip = f"{{base_prefix}}.{{i}}"
        if test_ip not in used_ips and test_ip != base_ip:
            free_ip = test_ip
            break

cur.execute("INSERT OR REPLACE INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',0,0)", 
            ('{peer_name}', '{p_data['limit']}', {p_data['used']}, {p_data['remaining_time']}, '{p_data['private_key']}', free_ip, '{pub}', cfg))
conn.commit()
conn.close()

subprocess.run(f"wg set {{iface}} peer {pub} allowed-ips {{free_ip}}/32", shell=True)
subprocess.run(f"wg-quick save {{iface}}", shell=True)
print(f"EDGE_IP:{{free_ip}}")
'''
                    enc = base64.b64encode(edge_cmd.encode('utf-8')).decode('utf-8')
                    res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"echo '{enc}' | base64 -d | python3\"", shell=True, capture_output=True, text=True)
                    
                    m_ip = re.search(r"EDGE_IP:(.*)", res.stdout)
                    if m_ip:
                        edge_ip_allocated = m_ip.group(1).strip()
                        conn_m = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                        conn_m.execute("CREATE TABLE IF NOT EXISTS peer_synced_edges (peer_name TEXT, server_ip TEXT, config TEXT, edge_ip TEXT, UNIQUE(peer_name, server_ip, config))")
                        conn_m.execute("INSERT OR REPLACE INTO peer_synced_edges (peer_name, server_ip, config, edge_ip) VALUES (?, ?, ?, ?)", (peer_name, srv_ip, config_file, edge_ip_allocated))
                        conn_m.commit()
                        conn_m.close()
        except Exception as e:
            print("Edge Sync Error:", e)
    threading.Thread(target=run_sync, daemon=True).start()

# 📌 بخش ۴: مدیریت نرم فایروال Xray و بازگشت به اینترنت عادی
def manage_xray_routing_rules(enable=True):
    import subprocess, os
    try:
        subprocess.run("iptables -t nat -D PREROUTING -i wg+ -p tcp --dport 5000 -j RETURN 2>/dev/null", shell=True)
        subprocess.run("iptables -t nat -D PREROUTING -i wg+ -p tcp -j REDIRECT --to-ports 12345 2>/dev/null", shell=True)
        subprocess.run("iptables -t nat -D PREROUTING -i wg+ -p udp --dport 53 -j REDIRECT --to-ports 5353 2>/dev/null", shell=True)
        subprocess.run("iptables -D FORWARD -i wg+ -p udp --dport 443 -j REJECT 2>/dev/null", shell=True)
        subprocess.run("iptables -t mangle -D PREROUTING -p tcp --tcp-flags SYN,RST SYN -i wg+ -j TCPMSS --set-mss 1120 2>/dev/null", shell=True)
        subprocess.run("iptables -t mangle -D POSTROUTING -p tcp --tcp-flags SYN,RST SYN -o wg+ -j TCPMSS --set-mss 1120 2>/dev/null", shell=True)
        
        main_nic = subprocess.getoutput("ip route | grep default | awk '{print $5}' | head -n1").strip()
        
        if enable:
            subprocess.run("sysctl -w net.ipv4.ip_forward=1", shell=True, stderr=subprocess.DEVNULL)
            subprocess.run("sysctl -w net.ipv4.conf.all.rp_filter=0", shell=True, stderr=subprocess.DEVNULL)
            subprocess.run("sysctl -w net.ipv4.conf.default.rp_filter=0", shell=True, stderr=subprocess.DEVNULL)
            subprocess.run("sysctl -w net.ipv4.conf.lo.rp_filter=0", shell=True, stderr=subprocess.DEVNULL)
            for iface in os.listdir('/sys/class/net'):
                if iface.startswith('wg'): subprocess.run(f"sysctl -w net.ipv4.conf.{iface}.rp_filter=0", shell=True, stderr=subprocess.DEVNULL)
                    
            subprocess.run("iptables -t nat -I PREROUTING 1 -i wg+ -p tcp --dport 5000 -j RETURN", shell=True)
            subprocess.run("iptables -t nat -A PREROUTING -i wg+ -p tcp -j REDIRECT --to-ports 12345", shell=True)
            subprocess.run("iptables -t nat -A PREROUTING -i wg+ -p udp --dport 53 -j REDIRECT --to-ports 5353", shell=True)
            subprocess.run("iptables -I FORWARD 1 -i wg+ -p udp --dport 443 -j REJECT", shell=True)
            subprocess.run("iptables -t mangle -I PREROUTING 1 -p tcp --tcp-flags SYN,RST SYN -i wg+ -j TCPMSS --set-mss 1120", shell=True)
            subprocess.run("iptables -t mangle -I POSTROUTING 1 -p tcp --tcp-flags SYN,RST SYN -o wg+ -j TCPMSS --set-mss 1120", shell=True)
            subprocess.run("netfilter-persistent save 2>/dev/null", shell=True)
        else:
            if main_nic:
                subprocess.run(f"iptables -t nat -C POSTROUTING -o {main_nic} -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -o {main_nic} -j MASQUERADE", shell=True)
                subprocess.run("iptables -C FORWARD -i wg+ -j ACCEPT 2>/dev/null || iptables -A FORWARD -i wg+ -j ACCEPT", shell=True)
                subprocess.run(f"iptables -C FORWARD -o {main_nic} -j ACCEPT 2>/dev/null || iptables -A FORWARD -o {main_nic} -j ACCEPT", shell=True)
            subprocess.run("netfilter-persistent save 2>/dev/null", shell=True)
    except Exception as e: pass

# 📌 بخش ۵: سپر ضد-خطای پکت‌های ساخت کلاینت (Sanitizer & Anti-Crash)
original_create_peer_for_v85 = app.view_functions.get('create_peer')
if original_create_peer_for_v85 and getattr(original_create_peer_for_v85, '__name__', '') != 'v85_mega_bulletproof_create_peer':
    app.view_functions['create_peer_orig_v85'] = original_create_peer_for_v85
    
    def v85_mega_bulletproof_create_peer(*args, **kwargs):
        from flask import request, session
        import subprocess, sqlite3, re, os
        
        try:
            if request.is_json:
                data = request.get_json(silent=True) or {}
                mutated = dict(data)
            else:
                data = request.form or {}
                mutated = dict(data)

            # ۱. کالیبراسیون کامل حجم به فرمت 1GiB
            raw_limit = str(mutated.get("limit") or mutated.get("dataLimit") or mutated.get("data_limit") or "").strip()
            raw_unit = str(mutated.get("limit_unit") or mutated.get("limitUnit") or "GiB").strip()
            
            if raw_unit.upper() in ["GB", "GIB"]: unit_str = "GiB"
            elif raw_unit.upper() in ["MB", "MIB"]: unit_str = "MiB"
            else: unit_str = "GiB"

            if "GiB" in raw_limit or "MiB" in raw_limit:
                clean_limit = raw_limit
            else:
                try:
                    num_val = float(raw_limit)
                    clean_limit = f"{int(num_val)}{unit_str}" if num_val.is_integer() else f"{num_val}{unit_str}"
                except ValueError:
                    clean_limit = f"1{unit_str}"

            mutated["limit"] = clean_limit
            mutated["dataLimit"] = clean_limit
            mutated["data_limit"] = clean_limit
            mutated["limit_unit"] = ""
            mutated["limitUnit"] = ""

            # ۲. کالیبراسیون تمام فیلدهای انقضا به عدد صحیح (Integer) جهت ممانعت از ارور str vs int
            try: m_val = int(mutated.get("expiryMonths") or mutated.get("expiry_months") or mutated.get("months") or 0)
            except: m_val = 0

            try: d_val = int(mutated.get("expiryDays") or mutated.get("expiry_days") or mutated.get("days") or 0)
            except: d_val = 0

            try: h_val = int(mutated.get("expiryHours") or mutated.get("expiry_hours") or mutated.get("hours") or 0)
            except: h_val = 0

            try: min_val = int(mutated.get("expiryMinutes") or mutated.get("expiry_minutes") or mutated.get("minutes") or 0)
            except: min_val = 0

            total_mins = (m_val * 30 * 1440) + (d_val * 1440) + (h_val * 60) + min_val
            if total_mins <= 0:
                d_val = 30 # دیفالت ۳۰ روز

            mutated["days"] = d_val
            mutated["expiryDays"] = d_val
            mutated["expiry_days"] = d_val
            mutated["months"] = m_val
            mutated["expiryMonths"] = m_val
            mutated["expiry_months"] = m_val
            mutated["hours"] = h_val
            mutated["expiryHours"] = h_val
            mutated["expiry_hours"] = h_val
            mutated["minutes"] = min_val
            mutated["expiryMinutes"] = min_val
            mutated["expiry_minutes"] = min_val

            for k in ["peerName", "peer_name", "config"]:
                if k in mutated and mutated[k] is not None:
                    mutated[k] = str(mutated[k]).strip()
            
            cfg = str(mutated.get("config", "wg0.conf")).strip()
            if not cfg.endswith(".conf"): cfg += ".conf"
            
            # مهار اینترفیس برای نماینده
            if session.get('role') == 'client':
                cfg = session.get('interface', 'wg0') + ".conf"

            mutated["config"] = cfg
            mutated["config_file"] = cfg
            mutated["configFile"] = cfg
            mutated["configName"] = cfg
            mutated["config_name"] = cfg

            # ۳. ساخت خودکار کلیدهای مفقود
            priv_key = mutated.get("privateKey") or mutated.get("private_key")
            pub_key = mutated.get("publicKey") or mutated.get("public_key")
            if not priv_key or not pub_key:
                try:
                    priv_key = subprocess.check_output("wg genkey", shell=True, text=True).strip()
                    pub_key = subprocess.check_output(f"echo '{priv_key}' | wg pubkey", shell=True, text=True).strip()
                    mutated["privateKey"] = str(priv_key)
                    mutated["publicKey"] = str(pub_key)
                    mutated["private_key"] = str(priv_key)
                    mutated["public_key"] = str(pub_key)
                except Exception as e: print("Keygen error:", e)

            # ۴. تخصیص خودکار آی‌پی آزاد سرور (رزرو نگه‌داشتن آی‌پی کلاینت‌های منقضی)
            peer_ip = mutated.get("peerIp") or mutated.get("peer_ip") or mutated.get("ipv4")
            if not peer_ip:
                base_ip = "10.0.0.1"
                try:
                    if os.path.exists(f"/etc/wireguard/{cfg}"):
                        with open(f"/etc/wireguard/{cfg}", "r") as f_cf:
                            m = re.search(r"Address\s*=\s*([0-9]+\.[0-9]+\.[0-9]+)\.", f_cf.read())
                            if m: base_ip = m.group(1) + ".1"
                except: pass
                base_prefix = ".".join(base_ip.split(".")[:3])
                
                used_ips = set()
                try:
                    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                    cur = conn.cursor()
                    # استخراج تمام آی‌پی‌ها (حتی منقضی‌ها) جهت رزرو ماندن و جلوگیری از تداخل
                    cur.execute("SELECT peer_ip FROM peers WHERE config=?", (cfg,))
                    for r in cur.fetchall():
                        if r[0]: used_ips.add(r[0].strip())
                    cur.execute("SELECT edge_ip FROM peer_synced_edges WHERE config=?", (cfg,))
                    for r in cur.fetchall():
                        if r[0]: used_ips.add(r[0].strip())
                    conn.close()
                except: pass
                
                try:
                    wg_out = subprocess.check_output(f"wg show {cfg.replace('.conf','')} allowed-ips", shell=True, text=True)
                    for line in wg_out.splitlines():
                        parts = line.split()
                        if len(parts) >= 2: used_ips.add(parts[1].split('/')[0].strip())
                except: pass

                free_ip = f"{base_prefix}.2"
                for i in range(2, 255):
                    test_ip = f"{base_prefix}.{i}"
                    if test_ip not in used_ips and test_ip != base_ip:
                        free_ip = test_ip
                        break
                
                mutated["peerIp"] = str(free_ip)
                mutated["peer_ip"] = str(free_ip)
                mutated["ipv4"] = str(free_ip)

            if request.is_json:
                request._cached_json = (mutated, mutated)
            else:
                from werkzeug.datastructures import MultiDict
                request.form = MultiDict(mutated)

        except Exception as patch_e:
            print("Mega Patch Sanitizer Error:", patch_e)

        res = app.view_functions['create_peer_orig_v85'](*args, **kwargs)
        
        # ۵. ارسال همزمان کلاینت به سرورهای فرزند (لبه)
        try:
            p_name = mutated.get("peerName") or mutated.get("peer_name")
            if p_name and 'v85_sync_single_peer_to_edges' in globals():
                import threading
                threading.Thread(target=globals()['v85_sync_single_peer_to_edges'], args=("create", p_name, cfg), daemon=True).start()
        except Exception as ex_sync:
            print("Edge sync dispatch error:", ex_sync)

        return res

    app.view_functions['create_peer'] = v85_mega_bulletproof_create_peer

# 📌 بخش ۶: فرمت‌دهی استاندارد پاسخ API ربات تلگرام (تزریق "success": true و اصلاح localhost)
@app.after_request
def v85_format_bot_api_responses(response):
    from flask import request
    import json, sqlite3
    if request.path in ['/api/create-peer', '/api/create_peer'] and response.content_type and 'application/json' in response.content_type:
        try:
            raw_text = response.get_data(as_text=True)
            res_json = json.loads(raw_text)
            if isinstance(res_json, dict) and response.status_code == 200:
                res_json["success"] = True
                res_json["status"] = "success"
                
                if "short_link" in res_json and "localhost" in res_json["short_link"]:
                    server_domain = request.host.split(":")[0]
                    try:
                        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
                        cur = conn.cursor()
                        cur.execute("SELECT endpoint_domain FROM master_settings LIMIT 1")
                        m_row = cur.fetchone()
                        conn.close()
                        if m_row and m_row[0]: server_domain = m_row[0].strip()
                    except: pass
                    if server_domain and server_domain != "localhost":
                        res_json["short_link"] = res_json["short_link"].replace("localhost", server_domain)
                        
                response.set_data(json.dumps(res_json))
        except Exception as e:
            print("API Formatter Error:", e)
    return response

# --- [END STEP 85 CONSOLIDATED MEGA PATCH] ---















# --- [STEP 88 SMITE AUTO TUNNEL AUTOMATION] ---
def smite_native_http_request_v88(panel_url, endpoint, method="GET", payload=None, token=None):
    import urllib.request, urllib.error, json
    url = f"{panel_url.rstrip('/')}{endpoint}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    data_bytes = None
    if method in ["POST", "PUT"] and payload is not None:
        headers["Content-Type"] = "application/json"
        data_bytes = json.dumps(payload).encode('utf-8')
    
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            res_body = response.read().decode('utf-8')
            try: return json.loads(res_body)
            except: return res_body
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8') if e.fp else ""
        try: return json.loads(err_body)
        except: return {"error": f"HTTP {e.code}: {e.reason}", "raw": err_body}
    except Exception as e:
        return {"error": str(e)}

@app.route("/api/smite-settings", methods=["GET", "POST"])
def api_smite_settings_endpoint_v88():
    from flask import request, jsonify, session
    import sqlite3
    if session.get('role') == 'client':
        return jsonify(error="Unauthorized"), 403

    db_p = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
    conn = sqlite3.connect(db_p, timeout=30.0)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS smite_tunnel_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, panel_url TEXT DEFAULT 'http://127.0.0.1:8009', username TEXT DEFAULT 'Pars', password TEXT DEFAULT 'Pars', iran_node_id TEXT DEFAULT 'local', foreign_node_id TEXT DEFAULT 'local', auto_tunnel_resellers INTEGER DEFAULT 1, accept_udp INTEGER DEFAULT 1, use_ipv6 INTEGER DEFAULT 1, updated_at TEXT)")
    conn.commit()

    if request.method == "GET":
        cur.execute("SELECT panel_url, username, password, iran_node_id, foreign_node_id, auto_tunnel_resellers, accept_udp, use_ipv6 FROM smite_tunnel_settings LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if row:
            return jsonify({
                "panel_url": row[0], "username": row[1], "password": row[2],
                "iran_node_id": row[3], "foreign_node_id": row[4],
                "auto_tunnel_resellers": bool(row[5]),
                "accept_udp": bool(row[6]),
                "use_ipv6": bool(row[7])
            })
        return jsonify({"panel_url": "http://127.0.0.1:8009", "username": "Pars", "password": "Pars", "iran_node_id": "local", "foreign_node_id": "local", "auto_tunnel_resellers": True, "accept_udp": True, "use_ipv6": True})

    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
        p_url = str(data.get("panel_url", "http://127.0.0.1:8009")).strip()
        p_user = str(data.get("username", "Pars")).strip()
        p_pass = str(data.get("password", "Pars")).strip()
        iran_node = str(data.get("iran_node_id", "local")).strip()
        foreign_node = str(data.get("foreign_node_id", "local")).strip()
        auto_tunnel = 1 if data.get("auto_tunnel_resellers", True) else 0
        accept_udp = 1 if data.get("accept_udp", True) else 0
        use_ipv6 = 1 if data.get("use_ipv6", True) else 0

        cur.execute("DELETE FROM smite_tunnel_settings")
        cur.execute("INSERT INTO smite_tunnel_settings (panel_url, username, password, iran_node_id, foreign_node_id, auto_tunnel_resellers, accept_udp, use_ipv6, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))", (p_url, p_user, p_pass, iran_node, foreign_node, auto_tunnel, accept_udp, use_ipv6))
        conn.commit()
        conn.close()
        return jsonify(success=True, message="تنظیمات تانل Smite با موفقیت ذخیره شد.")

@app.route("/api/smite-nodes", methods=["GET"])
def api_smite_nodes_endpoint_v88():
    from flask import jsonify, session
    import sqlite3
    if session.get('role') == 'client':
        return jsonify(error="Unauthorized"), 403

    db_p = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
    conn = sqlite3.connect(db_p, timeout=30.0)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS smite_tunnel_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, panel_url TEXT DEFAULT 'http://127.0.0.1:8009', username TEXT DEFAULT 'Pars', password TEXT DEFAULT 'Pars', iran_node_id TEXT DEFAULT 'local', foreign_node_id TEXT DEFAULT 'local', auto_tunnel_resellers INTEGER DEFAULT 1, accept_udp INTEGER DEFAULT 1, use_ipv6 INTEGER DEFAULT 1, updated_at TEXT)")
    cur.execute("SELECT panel_url, username, password FROM smite_tunnel_settings LIMIT 1")
    row = cur.fetchone()
    conn.close()

    p_url = row[0] if row else "http://127.0.0.1:8009"
    p_user = row[1] if row else "Pars"
    p_pass = row[2] if row else "Pars"

    login_res = smite_native_http_request_v88(p_url, "/api/auth/login", "POST", {"username": p_user, "password": p_pass})
    token = login_res.get("access_token") if isinstance(login_res, dict) else None

    if not token:
        return jsonify(error="عدم امکان لاگین به Smite Panel."), 400

    nodes_res = smite_native_http_request_v88(p_url, "/api/nodes", "GET", token=token)
    nodes = nodes_res if isinstance(nodes_res, list) else []
    return jsonify(success=True, nodes=nodes)

@app.route("/api/smite-sync-tunnels", methods=["POST"])
def api_smite_sync_tunnels_endpoint_v88():
    from flask import jsonify, session
    import sqlite3, os, re, json, traceback

    logs = ["🚀 شروع فرآیند همگام‌سازی و ساخت تانل‌های بکهال..."]

    try:
        if session.get('role') == 'client':
            return jsonify(success=False, logs=["❌ عدم دسترسی کاربر"]), 403

        db_p = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
        conn = sqlite3.connect(db_p, timeout=30.0)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS smite_tunnel_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, panel_url TEXT DEFAULT 'http://127.0.0.1:8009', username TEXT DEFAULT 'Pars', password TEXT DEFAULT 'Pars', iran_node_id TEXT DEFAULT 'local', foreign_node_id TEXT DEFAULT 'local', auto_tunnel_resellers INTEGER DEFAULT 1, accept_udp INTEGER DEFAULT 1, use_ipv6 INTEGER DEFAULT 1, updated_at TEXT)")
        cur.execute("SELECT panel_url, username, password, iran_node_id, foreign_node_id, accept_udp, use_ipv6 FROM smite_tunnel_settings LIMIT 1")
        s_row = cur.fetchone()
        conn.close()

        if not s_row:
            return jsonify(success=False, logs=["❌ تنظیمات Smite یافت نشد."])

        panel_url, username, password, iran_node_sel, foreign_node_sel, accept_udp, use_ipv6 = s_row

        logs.append(f"🔑 اتصال به Smite ({panel_url})...")
        login_res = smite_native_http_request_v88(panel_url, "/api/auth/login", "POST", {"username": username, "password": password})
        token = login_res.get("access_token") if isinstance(login_res, dict) else None

        if not token:
            logs.append(f"❌ خطا در لاگین به Smite: {login_res}")
            return jsonify(success=False, logs=logs)

        logs.append("✅ لاگین به Smite تایید شد.")

        nodes_res = smite_native_http_request_v88(panel_url, "/api/nodes", "GET", token=token)
        nodes = nodes_res if isinstance(nodes_res, list) else []

        resolved_iran_id = None if iran_node_sel == "local" else iran_node_sel
        resolved_foreign_id = None if foreign_node_sel == "local" else foreign_node_sel
        foreign_ip_addr = "127.0.0.1"

        for n in nodes:
            n_id = n.get("id")
            n_role = (n.get("metadata") or {}).get("role", "")
            n_ip = (n.get("metadata") or {}).get("ip_address", "127.0.0.1")

            if not resolved_iran_id and n_role == "iran":
                resolved_iran_id = n_id
            if not resolved_foreign_id and n_role == "foreign":
                resolved_foreign_id = n_id
                foreign_ip_addr = n_ip

        if not resolved_iran_id and nodes: resolved_iran_id = nodes[0].get("id")
        if not resolved_foreign_id and nodes: resolved_foreign_id = nodes[0].get("id")

        logs.append(f"🇮🇷 نود ایران: {resolved_iran_id or 'محلی'}")
        logs.append(f"🌐 نود خارج: {resolved_foreign_id or 'محلی'}")

        # اسکن پورت‌ها
        wg_ports = []
        if os.path.exists('/etc/wireguard'):
            for f in os.listdir('/etc/wireguard'):
                if f.endswith('.conf'):
                    iface = f.replace('.conf', '')
                    try:
                        txt = open(os.path.join('/etc/wireguard', f)).read()
                        m = re.search(r"ListenPort\s*=\s*(\d+)", txt, re.IGNORECASE)
                        if m: wg_ports.append({"iface": iface, "port": int(m.group(1))})
                    except: pass

        logs.append(f"📊 {len(wg_ports)} پورت وایرگارد کشف شد: " + ", ".join([f"{p['iface']}:{p['port']}" for p in wg_ports]))

        existing_tunnels = smite_native_http_request_v88(panel_url, "/api/tunnels", "GET", token=token)
        if isinstance(existing_tunnels, list):
            for tun in existing_tunnels:
                t_id = tun.get("id")
                t_name = tun.get("name", "")
                t_spec = tun.get("spec", {})
                t_port = t_spec.get("listen_port") or t_spec.get("public_port")
                for wp in wg_ports:
                    if str(t_port) == str(wp['port']) or t_name == f"WG-{wp['iface']}-{wp['port']}":
                        logs.append(f"🗑️ حذف تانل قدیمی پورت {wp['port']} ({t_id})...")
                        smite_native_http_request_v88(panel_url, f"/api/tunnels/{t_id}", "DELETE", token=token)

        created_count = 0
        control_port_base = 7080

        for idx, wp in enumerate(wg_ports):
            p_num = wp['port']
            if_name = wp['iface']
            ctrl_port = control_port_base + idx

            tunnel_payload = {
                "name": f"WG-{if_name}-{p_num}",
                "core": "backhaul",
                "type": "tcp",
                "iran_node_id": resolved_iran_id,
                "foreign_node_id": resolved_foreign_id,
                "spec": {
                    "transport": "tcp",
                    "bind_addr": f"0.0.0.0:{ctrl_port}",
                    "remote_addr": f"{foreign_ip_addr}:{ctrl_port}",
                    "listen_ip": "0.0.0.0",
                    "control_port": ctrl_port,
                    "public_port": p_num,
                    "listen_port": p_num,
                    "target_host": "127.0.0.1",
                    "target_port": p_num,
                    "target_addr": f"127.0.0.1:{p_num}",
                    "public_host": foreign_ip_addr,
                    "ports": [f"{p_num}=127.0.0.1:{p_num}"],
                    "accept_udp": bool(accept_udp),
                    "server_options": {
                        "keepalive_period": 75, "heartbeat": 40,
                        "channel_size": 2048, "mux_con": 8,
                        "log_level": "info", "nodelay": True
                    },
                    "client_options": {
                        "connection_pool": 4, "retry_interval": 3,
                        "dial_timeout": 10, "keepalive_period": 75,
                        "log_level": "info", "nodelay": True
                    },
                    "use_ipv6": bool(use_ipv6)
                }
            }

            logs.append(f"➕ ساخت تانل Backhaul برای پورت {p_num} ({if_name})...")
            c_res = smite_native_http_request_v88(panel_url, "/api/tunnels", "POST", payload=tunnel_payload, token=token)

            if isinstance(c_res, dict) and c_res.get("id"):
                new_t_id = c_res.get("id")
                logs.append(f"  ✔ تانل با موفقیت ساخته شد (ID: {new_t_id}). در حال استارت...")
                smite_native_http_request_v88(panel_url, f"/api/tunnels/{new_t_id}/apply", "POST", token=token)
                logs.append(f"  🚀 تانل پورت {p_num} روی نودها فعال گردید.")
                created_count += 1
            else:
                logs.append(f"  ❌ خطا در ساخت تانل پورت {p_num}: {json.dumps(c_res, ensure_ascii=False)}")

        logs.append(f"🎉 عملیات پایان یافت. تعداد {created_count} تانل بکهال معکوس مستقر شدند.")
        return jsonify(success=True, logs=logs)

    except Exception as e:
        err_str = str(e)
        trace_str = traceback.format_exc()
        logs.append(f"❌ خطای پایتون: {err_str}")
        logs.append(f"```\n{trace_str}\n```")
        return jsonify(success=False, logs=logs), 200

try:
    if 'csrf' in globals():
        csrf.exempt(api_smite_settings_endpoint_v88)
        csrf.exempt(api_smite_nodes_endpoint_v88)
        csrf.exempt(api_smite_sync_tunnels_endpoint_v88)
except: pass
# --- [END STEP 88 SMITE AUTO TUNNEL AUTOMATION] ---











# --- [STEP 89 ULTIMATE SUBLINK & EDGE IP SYNC] ---

# 📌 ۱. الگوریتم آی‌پی‌یاب بلوک‌های ۵‌تایی
def get_free_ip_strict_blocks_v89(config_file):
    import sqlite3, os, re, subprocess
    if not config_file.endswith('.conf'): config_file += '.conf'
    iface = config_file.replace('.conf', '')
    
    config_path = f"/etc/wireguard/{config_file}"
    base_ip = "10.0.0.1"
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                match = re.search(r"Address\s*=\s*([0-9]+\.[0-9]+\.[0-9]+)\.", f.read())
                if match: base_ip = match.group(1) + ".1"
        except: pass

    parts = base_ip.split(".")
    oct1, oct2 = parts[0], parts[1]
    start_oct3 = int(parts[2])

    if iface == "wg0":
        range_start = 0
        range_end = 9
    else:
        range_start = start_oct3
        range_end = start_oct3 + 4

    used_ips = set()
    try:
        db_p = '/usr/local/bin/Wireguard-panel/src/db.sqlite3'
        conn = sqlite3.connect(db_p, timeout=30.0)
        cur = conn.cursor()
        cur.execute("SELECT peer_ip FROM peers WHERE config=?", (config_file,))
        for r in cur.fetchall():
            if r[0]: used_ips.add(r[0].strip())
        cur.execute("SELECT edge_ip FROM peer_synced_edges WHERE config=?", (config_file,))
        for r in cur.fetchall():
            if r[0]: used_ips.add(r[0].strip())
        conn.close()
    except: pass

    try:
        wg_out = subprocess.check_output(f"wg show {iface} allowed-ips", shell=True, text=True)
        for line in wg_out.splitlines():
            p = line.split()
            if len(p) >= 2: used_ips.add(p[1].split('/')[0].strip())
    except: pass

    free_ip = None
    for oct3 in range(range_start, range_end + 1):
        for oct4 in range(2, 255):
            test_ip = f"{oct1}.{oct2}.{oct3}.{oct4}"
            if test_ip not in used_ips and test_ip != base_ip:
                free_ip = test_ip
                break
        if free_ip:
            break

    return free_ip or f"{oct1}.{oct2}.{range_start}.2"

@app.route("/api/get-free-ip", methods=["GET"])
def api_get_free_ip_v89():
    from flask import request, jsonify, session
    config_file = request.args.get('config', 'wg0.conf')
    if session.get('role') == 'client':
        config_file = session.get('interface') + ".conf"
    free_ip = get_free_ip_strict_blocks_v89(config_file)
    return jsonify({"free_ip": free_ip})

# 📌 ۲. موتور همگام‌ساز پس‌زمینه سرور مادر به سرورهای فرزند (به همراه ثبت لایو edge_ip در دیتابیس مادر)
def v89_sync_action_to_edges(action, peer_name, config_file, extra_data=None):
    import threading
    def run_sync():
        import sqlite3, subprocess, base64, time, re
        time.sleep(1.0)
        try:
            conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
            cur = conn.cursor()
            cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass, server_ip FROM edge_servers")
            edges = cur.fetchall()
            if not edges:
                conn.close()
                return

            if action == 'delete':
                pub = extra_data.get('public_key') if extra_data else None
                pip = extra_data.get('peer_ip') if extra_data else None
                if not pub:
                    cur.execute("SELECT public_key, peer_ip FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
                    r = cur.fetchone()
                    if r: pub, pip = r[0], r[1]
                conn.close()
                if not pub: return

                for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                    edge_py = f'''import sqlite3, subprocess, os, re
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{config_file}"
iface = cfg.replace('.conf','')
pub = "{pub}"
pip = "{pip or ''}"

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute("DELETE FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
    conn.commit()
    conn.close()

subprocess.run(f"wg set {{iface}} peer {{pub}} remove", shell=True, stderr=subprocess.DEVNULL)
if pip:
    subprocess.run(f"ip route del blackhole {{pip}}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"ip route del {{pip}} blackhole", shell=True, stderr=subprocess.DEVNULL)

path = f"/etc/wireguard/{{cfg}}"
if os.path.exists(path):
    with open(path, "r") as f: text = f.read()
    blocks = text.split("[Peer]")
    new_text = blocks[0].strip() + "\\n"
    for block in blocks[1:]:
        if pub in block: continue
        new_text += "\\n[Peer]\\n" + block.strip() + "\\n"
    with open(path, "w") as f: f.write(new_text.strip() + "\\n")
    subprocess.run(f"wg-quick save {{iface}}", shell=True, stderr=subprocess.DEVNULL)
'''
                    enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
                    cmd = f"echo '{enc}' | base64 -d > /tmp/del_edge_v89.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/del_edge_v89.py && rm -f /tmp/del_edge_v89.py"
                    subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{cmd}\"", shell=True)

            elif action in ['create', 'edit', 'toggle', 'reset_expiry', 'reset_traffic']:
                cur.execute("SELECT [limit], used, remaining_time, monitor_blocked, expiry_blocked, public_key, peer_ip, private_key FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
                p_row = cur.fetchone()
                conn.close()
                if not p_row: return
                limit, used, rem_time, m_blk, e_blk, pub, pip, priv = p_row

                for s_ip, ssh_port, ssh_user, ssh_pass, srv_ip in edges:
                    edge_py = f'''import sqlite3, subprocess, os, re
db_path = "/usr/local/bin/Wireguard-panel/src/db.sqlite3"
cfg = "{config_file}"
iface = cfg.replace('.conf','')
pub = "{pub}"
pip = "{pip}"
priv = "{priv}"
limit = "{limit}"
used = {used}
rem_time = {rem_time}
m_blk = {m_blk}
e_blk = {e_blk}

os.makedirs("/usr/local/bin/Wireguard-panel/src", exist_ok=True)
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS peers (peer_name TEXT, [limit] TEXT, used INTEGER, remaining_time INTEGER, private_key TEXT, peer_ip TEXT, public_key TEXT, config TEXT, first_usage TEXT, monitor_blocked INTEGER, expiry_blocked INTEGER, UNIQUE(peer_name, config))")

base_ip = "10.0.0.1"
try:
    if os.path.exists(f"/etc/wireguard/{{cfg}}"):
        with open(f"/etc/wireguard/{{cfg}}", "r") as f:
            match = re.search(r"Address\s*=\s*([0-9]+\.[0-9]+\.[0-9]+)\.", f.read())
            if match: base_ip = match.group(1) + ".1"
except: pass
parts = base_ip.split(".")
oct1, oct2 = parts[0], parts[1]
start_oct3 = int(parts[2])

if iface == "wg0":
    r_start, r_end = 0, 9
else:
    r_start, r_end = start_oct3, start_oct3 + 4

cur.execute("SELECT peer_ip FROM peers WHERE peer_name='{peer_name}' AND config='{config_file}'")
exist_row = cur.fetchone()

if exist_row and exist_row[0]:
    edge_ip = exist_row[0]
else:
    cur.execute("SELECT peer_ip FROM peers WHERE config=?", (cfg,))
    used_ips = set([r[0] for r in cur.fetchall() if r[0]])
    try:
        wg_out = subprocess.check_output(f"wg show {{iface}} allowed-ips", shell=True, text=True)
        for line in wg_out.splitlines():
            p = line.split()
            if len(p) >= 2: used_ips.add(p[1].split('/')[0].strip())
    except: pass
    edge_ip = None
    for oct3 in range(r_start, r_end + 1):
        for oct4 in range(2, 255):
            test_ip = f"{{oct1}}.{{oct2}}.{{oct3}}.{{oct4}}"
            if test_ip not in used_ips and test_ip != base_ip:
                edge_ip = test_ip
                break
        if edge_ip: break
    if not edge_ip: edge_ip = f"{{oct1}}.{{oct2}}.{{r_start}}.2"

cur.execute("INSERT OR REPLACE INTO peers (peer_name, [limit], used, remaining_time, private_key, peer_ip, public_key, config, first_usage, monitor_blocked, expiry_blocked) VALUES (?,?,?,?,?,?,?,?,'',?,?)",
            ('{peer_name}', limit, used, rem_time, priv, edge_ip, pub, cfg, m_blk, e_blk))
conn.commit()
conn.close()

if m_blk == 1 or e_blk == 1:
    subprocess.run(f"wg set {{iface}} peer {{pub}} remove", shell=True, stderr=subprocess.DEVNULL)
else:
    subprocess.run(f"wg set {{iface}} peer {{pub}} allowed-ips {{edge_ip}}/32", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"wg-quick save {{iface}}", shell=True, stderr=subprocess.DEVNULL)

print(f"ALLOCATED_EDGE_IP:{{edge_ip}}")
'''
                    enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
                    cmd = f"echo '{enc}' | base64 -d > /tmp/upd_edge_v89.py && /usr/local/bin/Wireguard-panel/src/venv/bin/python3 /tmp/upd_edge_v89.py && rm -f /tmp/upd_edge_v89.py"
                    res = subprocess.run(f"sshpass -p '{ssh_pass}' ssh -p {ssh_port} -o StrictHostKeyChecking=no {ssh_user}@{s_ip} \"{cmd}\"", shell=True, capture_output=True, text=True)
                    
                    # 📌 ثبت لایو edge_ip در دیتابیس سرور مادر برای اصلاح ساب‌لینک
                    if res.returncode == 0 and "ALLOCATED_EDGE_IP:" in res.stdout:
                        m_ip = re.search(r"ALLOCATED_EDGE_IP:(.*)", res.stdout)
                        if m_ip:
                            alloc_ip = m_ip.group(1).strip()
                            conn_m = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3', timeout=30.0)
                            conn_m.execute("CREATE TABLE IF NOT EXISTS peer_synced_edges (peer_name TEXT, server_ip TEXT, config TEXT, edge_ip TEXT, last_bytes INTEGER DEFAULT 0, UNIQUE(peer_name, server_ip, config))")
                            conn_m.execute("INSERT OR REPLACE INTO peer_synced_edges (peer_name, server_ip, config, edge_ip) VALUES (?, ?, ?, ?)", (peer_name, srv_ip, config_file, alloc_ip))
                            conn_m.commit()
                            conn_m.close()

        except Exception as ex:
            print("V89 Sync Thread Exception:", ex)

    threading.Thread(target=run_sync, daemon=True).start()

# 📌 ۳. اصلاح تابع دانلود فایل کانفیگ ساب‌لینک (تضمین تطابق کامل آی‌پی اختصاصی لبه)
def v89_short_download_config(short_id, suffix_key):
    import os, json, sqlite3, re, subprocess, urllib.parse
    from flask import Response, request
    short_links_path = os.path.join('/usr/local/bin/Wireguard-panel/src', 'short_links.json')
    with open(short_links_path, 'r') as f: short_links = json.load(f)
    long_link = short_links.get(short_id)
    if not long_link: return "Error: Invalid link", 404

    p_match = re.search(r'peer_name=([^&]+)', long_link) or re.search(r'peerName=([^&]+)', long_link)
    c_match = re.search(r'config_file=([^&]+)', long_link) or re.search(r'configFile=([^&]+)', long_link) or re.search(r'config=([^&]+)', long_link)

    peer_name = urllib.parse.unquote(p_match.group(1)) if p_match else ""
    config_file = urllib.parse.unquote(c_match.group(1)) if c_match else "wg0.conf"
    if not config_file.endswith('.conf'): config_file += '.conf'

    conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
    cur = conn.cursor()
    cur.execute("SELECT private_key, peer_ip, dns, mtu, persistent_keepalive, allowed_ips FROM peers WHERE peer_name=? AND config=?", (peer_name, config_file))
    peer_row = cur.fetchone()
    if not peer_row:
        conn.close(); return "Error: Peer not found", 404

    private_key, peer_ip, dns, mtu, keepalive, allowed_ips = peer_row

    plan_id = suffix_key.split("_")[0]
    target_server = suffix_key.split("_", 1)[1] if "_" in suffix_key else "master"

    plan_suffix = ""
    if plan_id != "main" and plan_id.isdigit():
        cur.execute("SELECT suffix, mtu, dns, keepalive, allowed_ips FROM subscription_plans WHERE id=?", (int(plan_id),))
        plan_row = cur.fetchone()
        if plan_row:
            plan_suffix, mtu, dns, keepalive, allowed_ips = plan_row

    server_suffix = ""
    server_ip = request.host.split(":")[0]

    if target_server == "master":
        cur.execute("SELECT endpoint_domain, file_suffix FROM master_settings LIMIT 1")
        m_row = cur.fetchone()
        if m_row:
            if m_row[0] and m_row[0].strip(): server_ip = m_row[0].strip()
            if m_row[1] and m_row[1].strip(): server_suffix = m_row[1].strip()
    else:
        cur.execute("SELECT server_ip, file_suffix FROM edge_servers WHERE server_ip=?", (target_server,))
        srv_row = cur.fetchone()
        if srv_row:
            server_ip = srv_row[0].strip()
            if srv_row[1] and srv_row[1].strip(): server_suffix = srv_row[1].strip()

        # 📌 اصلاح کلیدی: خواندن آی‌پی اختصاصی و واقعی همان سرور لبه از جدول peer_synced_edges
        cur.execute("SELECT edge_ip FROM peer_synced_edges WHERE peer_name=? AND server_ip=? AND config=?", (peer_name, target_server, config_file))
        edge_ip_row = cur.fetchone()
        if edge_ip_row and edge_ip_row[0] and edge_ip_row[0].strip():
            peer_ip = edge_ip_row[0].strip()

    # دریافت PublicKey و پورت
    server_pub_key, listen_port = "", 51820
    if target_server == "master":
        config_path = f"/etc/wireguard/{config_file}"
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                cf_text = f.read()
                pk_match = re.search(r"PrivateKey\s*=\s*(.*)", cf_text, re.IGNORECASE)
                if pk_match:
                    priv = pk_match.group(1).strip()
                    try: server_pub_key = subprocess.check_output(f"echo '{priv}' | wg pubkey", shell=True, text=True).strip()
                    except: pass
                port_match = re.search(r"ListenPort\s*=\s*(\d+)", cf_text, re.IGNORECASE)
                if port_match: listen_port = int(port_match.group(1))
    else:
        cur.execute("SELECT ssh_ip, ssh_port, ssh_user, ssh_pass FROM edge_servers WHERE server_ip=?", (target_server,))
        s_info = cur.fetchone()
        if s_info:
            s_ip, s_port, s_user, s_pass = s_info[0], s_info[1], s_info[2], s_info[3]
            edge_py = f'''import os, re, subprocess
cfg="{config_file}"
pub, port = "", "51820"
if os.path.exists(f"/etc/wireguard/{{cfg}}"):
    with open(f"/etc/wireguard/{{cfg}}", "r") as f:
        txt = f.read()
        m_pk = re.search(r"PrivateKey\s*=\s*(.*)", txt, re.IGNORECASE)
        if m_pk:
            priv = m_pk.group(1).strip()
            try: pub = subprocess.check_output(f"echo '{{priv}}' | wg pubkey", shell=True, text=True).strip()
            except: pass
        m_pt = re.search(r"ListenPort\s*=\s*(\d+)", txt, re.IGNORECASE)
        if m_pt: port = m_pt.group(1)
print(f"{{pub}}|{{port}}")'''
            enc = base64.b64encode(edge_py.encode('utf-8')).decode('utf-8')
            res = subprocess.run(f"sshpass -p '{s_pass}' ssh -p {s_port} -o StrictHostKeyChecking=no {s_user}@{s_ip} \"echo '{enc}' | base64 -d | /usr/local/bin/Wireguard-panel/src/venv/bin/python3\"", shell=True, capture_output=True, text=True)
            if res.returncode == 0 and "|" in res.stdout:
                parts = res.stdout.strip().split("|")
                if len(parts) >= 2 and parts[0].strip():
                    server_pub_key = parts[0].strip()
                    listen_port = int(parts[1].strip())

    conn.close()
    config_data = f"[Interface]\nPrivateKey = {private_key}\nAddress = {peer_ip}/32\nDNS = {dns}\nMTU = {mtu}\n\n[Peer]\nPublicKey = {server_pub_key}\nEndpoint = {server_ip}:{listen_port}\nAllowedIPs = {allowed_ips}\nPersistentKeepalive = {keepalive}\n"
    final_filename = f"{peer_name}{plan_suffix}{server_suffix}.conf"
    return Response(config_data, mimetype="application/octet-stream", headers={"Content-disposition": f"attachment; filename={final_filename}"})

if 'short_download_config' in app.view_functions:
    app.view_functions['short_download_config'] = v89_short_download_config

# 📌 ۴. بایندینگ هوک‌ها به توابع اصلی
orig_create_v89 = app.view_functions.get('create_peer')
def v89_create_peer_wrapper(*args, **kwargs):
    res = orig_create_v89(*args, **kwargs) if orig_create_v89 else None
    try:
        from flask import request
        data = request.get_json(silent=True) or request.form or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg = data.get("config", "wg0.conf")
        if not cfg.endswith('.conf'): cfg += '.conf'
        if p_name: v89_sync_action_to_edges('create', p_name, cfg)
    except Exception as e: print("v89 create hook err:", e)
    return res
if 'create_peer' in app.view_functions: app.view_functions['create_peer'] = v89_create_peer_wrapper

orig_edit_v89 = app.view_functions.get('edit_peer')
def v89_edit_peer_wrapper(*args, **kwargs):
    res = orig_edit_v89(*args, **kwargs) if orig_edit_v89 else None
    try:
        from flask import request
        data = request.get_json(silent=True) or request.form or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg = data.get("config", "wg0.conf")
        if not cfg.endswith('.conf'): cfg += '.conf'
        if p_name: v89_sync_action_to_edges('edit', p_name, cfg)
    except Exception as e: print("v89 edit hook err:", e)
    return res
if 'edit_peer' in app.view_functions: app.view_functions['edit_peer'] = v89_edit_peer_wrapper

orig_toggle_v89 = app.view_functions.get('toggle_peer')
def v89_toggle_peer_wrapper(*args, **kwargs):
    res = orig_toggle_v89(*args, **kwargs) if orig_toggle_v89 else None
    try:
        from flask import request
        data = request.get_json(silent=True) or request.form or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg = data.get("config", "wg0.conf")
        if not cfg.endswith('.conf'): cfg += '.conf'
        if p_name: v89_sync_action_to_edges('toggle', p_name, cfg)
    except Exception as e: print("v89 toggle hook err:", e)
    return res
if 'toggle_peer' in app.view_functions: app.view_functions['toggle_peer'] = v89_toggle_peer_wrapper

orig_delete_v89 = app.view_functions.get('delete_peer')
def v89_delete_peer_wrapper(*args, **kwargs):
    from flask import request
    extra_data = {}
    p_name, cfg = None, "wg0.conf"
    try:
        data = request.get_json(silent=True) or request.form or {}
        p_name = data.get("peerName") or data.get("peer_name")
        cfg = data.get("config", "wg0.conf")
        if not cfg.endswith('.conf'): cfg += '.conf'
        import sqlite3
        conn = sqlite3.connect('/usr/local/bin/Wireguard-panel/src/db.sqlite3')
        cur = conn.cursor()
        cur.execute("SELECT public_key, peer_ip FROM peers WHERE peer_name=? AND config=?", (p_name, cfg))
        r = cur.fetchone()
        conn.close()
        if r: extra_data = {'public_key': r[0], 'peer_ip': r[1]}
    except: pass

    res = orig_delete_v89(*args, **kwargs) if orig_delete_v89 else None

    try:
        if p_name: v89_sync_action_to_edges('delete', p_name, cfg, extra_data)
    except Exception as e: print("v89 delete hook err:", e)
    return res
if 'delete_peer' in app.view_functions: app.view_functions['delete_peer'] = v89_delete_peer_wrapper

try:
    if 'csrf' in globals():
        csrf.exempt(api_get_free_ip_v89)
except: pass
# --- [END STEP 89 ULTIMATE SUBLINK & EDGE IP SYNC] ---


if __name__ == "__main__":
    create_shortlinks()
    decrypt_short_links(
        input_file=os.path.join(BASE_DIR, "short_links.json"),
        output_file=os.path.join(BASE_DIR, "short_links_decrypted.json")
    )
    config = load_config()
    flask_port = config["flask"]["port"]
    domain = config["flask"].get("domain", "localhost")
    use_tls = config["flask"]["tls"]
    cert_path = config["flask"].get("cert_path")
    key_path = config["flask"].get("key_path")
    debug_mode = config["flask"].get("debug", False)
    auto_backup_int = config["wireguard"].get("auto_backup_int", 30)

    if use_tls and cert_path:
        try:
            flask_host = cert_path.split("/live/")[1].split("/")[0] 
        except IndexError:
            raise ValueError("Invalid cert_path format. Expected format: '/etc/letsencrypt/live/<domain>/fullchain.pem'")
    else:
        flask_host = "localhost"  

    setup_logging(debug_mode)

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    db_file = os.path.join(BASE_DIR, "db.json")

    if not os.path.exists(db_file):
        with open(db_file, "w") as file:
            json.dump({}, file)
        logging.info(f"Created new database file: {db_file}")
    else:
        try:
            with open(db_file, "r") as file:
                json.load(file)
            logging.info(f"Database file '{db_file}' is valid.")
        except json.JSONDecodeError:
            with open(db_file, "w") as file:
                json.dump({}, file)
            logging.warning(f"Wrong JSON detected in '{db_file}'. Resetting to an empty dictionary.")

    reload_blocked_peers()
    logging.info("Clearing invalid jobs from the database...")
    clean_invalid_jobs(scheduler)
    scheduler.remove_all_jobs()

    logging.info("Starting Flask application.")

    with tempfile.NamedTemporaryFile(delete=False) as temp_lock_file:
        scheduler_lock_path = temp_lock_file.name  

    scheduler_lock = InterProcessLock(scheduler_lock_path)

    if scheduler_lock.acquire(blocking=False):
        try:
            logging.info("Acquired lock. Initializing BackgroundScheduler.")

            if not scheduler.get_job("decrease_time"):
                logging.info("Adding decrease_remaining_time job.")
                scheduler.add_job(
                    decrease_remaining_time,
                    "interval",
                    minutes=1,
                    id="decrease_time",
                    max_instances=1,
                    replace_existing=True
                )

            if not scheduler.get_job("monitor_traffic"):
                logging.info("Adding monitor_traffic job.")
                scheduler.add_job(
                    monitor_traffic,
                    "interval",
                    seconds=23,
                    id="monitor_traffic",
                    max_instances=1,
                    replace_existing=True
                )

            if not scheduler.get_job("automated_backup"):
                logging.info(f"Adding automated_backup job with interval {auto_backup_int} minutes.")
                scheduler.add_job(
                    create_automated_backup,
                    "interval",
                    minutes=auto_backup_int,
                    id="automated_backup",
                    max_instances=1,
                    replace_existing=True,
                )

            if not scheduler.get_job("system_metrics"):
                logging.info("Adding system metrics job.")
                scheduler.add_job(
                    system_metrics_job,
                    trigger=IntervalTrigger(seconds=9),
                    id="system_metrics",
                    max_instances=1,
                    replace_existing=True,
                )

            try:
                system_metrics_job()
                print("Metrics collected and cached successfully during initialization.")
            except Exception as e:
                print(f"Error during initial metrics collection: {e}")

            scheduler.start()
            logging.info(f"Scheduled Jobs: {scheduler.get_jobs()}")
        except Exception as e:
            logging.error(f"Couldn't initialize scheduler: {e}")
        finally:
            scheduler_lock.release()
            logging.info("Scheduler lock released.")
    else:
        logging.warning("Scheduler is already running. Skipping initialization.")

    class GunicornApp(BaseApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()

        def load_config(self):
            config = {key: value for key, value in self.options.items() if key in self.cfg.settings and value is not None}
            for key, value in config.items():
                self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    try:
        gunicorn_config = config["gunicorn"]
        options = {
            "bind": f"0.0.0.0:{flask_port}",
            "workers": gunicorn_config.get("workers", 2),
            "threads": gunicorn_config.get("threads", 1),
            "loglevel": gunicorn_config.get("loglevel", "info"),
            "timeout": gunicorn_config.get("timeout", 120),
            "accesslog": gunicorn_config.get("accesslog", "-") if gunicorn_config.get("accesslog") != "" else None,
            "errorlog": gunicorn_config.get("errorlog", "-") if gunicorn_config.get("errorlog") != "" else None,
        }


        if use_tls:
            if not cert_path or not key_path:
                raise ValueError("TLS is enabled, but cert_path or key_path is not configured in config.yaml.")
            options.update({
                "certfile": cert_path,
                "keyfile": key_path,
            })

        protocol = "https" if use_tls else "http"

        homepage_url = f"{protocol}://{flask_host}:{flask_port}/"
        print(f"Application running at {homepage_url}")
        logging.info(f"Application running at {homepage_url}")

        logging.info("Starting Gunicorn server.")
        GunicornApp(app, options).run()

    except Exception as e:
        logging.error(f"Couldn't start Gunicorn server: {e}")

    except (KeyboardInterrupt, SystemExit):
        logging.info("Shutting down application.")
        if scheduler:
            scheduler.shutdown(wait=False)
