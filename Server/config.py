"""
Aurex Server Configuration
Update these settings when you change physical locations or network configuration
"""

import logging
import os

from aurex_logging import AurexLogger


def _env_flag(name: str, default: str = "1") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}

# Server Configuration
SERVER_HOST = os.getenv("AUREX_SERVER_HOST", "0.0.0.0")  # Bind address
SERVER_PORT = int(os.getenv("AUREX_SERVER_PORT", "23456"))  # Main TLS connection port
# Broadcast response IP for discovery. Leave empty to auto-detect at runtime.
SERVER_IP = os.getenv("AUREX_SERVER_IP", "")
# Block confirmation listener (RPC server sends block_confirmation here)
BLOCK_CONFIRMATION_PORT = 23457

# Gateway (RPC) server for PoW submissions
GATEWAY_HOST = '127.0.0.1'
GATEWAY_PORT = 5000

# Broadcast Discovery Configuration
BROADCAST_PORT = 12345   # UDP port for WHRSRV discovery
BROADCAST_TIMEOUT = 5    # Seconds to wait for discovery response
ENABLE_UDP_DISCOVERY = os.getenv("AUREX_ENABLE_UDP_DISCOVERY", "0") == "1"

# SSL/TLS Configuration
SSL_CERT_FILE = '../HTTPS/server.crt'
SSL_KEY_FILE = '../HTTPS/server.key'

# Database Configuration (ORM: DB/marketplace.db)
DATABASE_FOLDER = '../DB'
MARKETPLACE_DB_PATH = '../DB/marketplace.db'
BLOCKCHAIN_DB_PATH = '../blockchain/database.sqlite3'

# Marketplace wallet defaults
REGISTERED_USER_STARTING_BALANCE = 100  # currency units

# Google Drive Upload (Apps Script endpoint)
# This script should accept form fields: name, description, timestamp, file (multipart).
GOOGLE_APPS_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbzwVFRyAb1d0dXGm2Xmjz8aemXivoAzK2-OWyRmywt4_Sw1IH8g2YmlSlQnoLkPq1a/exec'

# Google Drive Upload (Service Account)
# Share the parent folder with the service account (or the upload account below).
GOOGLE_DRIVE_PARENT_FOLDER_ID = '17oD5gbtCfoMbnI15gV-TDwXREWUGHtqp'
GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE = 'credentials.json'  # Path to service account JSON
GOOGLE_DRIVE_UPLOAD_ACCOUNT_EMAIL = 'aurex.main.service@gmail.com'
GOOGLE_DRIVE_UPLOADS_FOLDER_NAME = 'uploads'

# Local Asset Storage (replaces Google Drive)
UPLOADS_DIR = '../assets/uploads'

# Upload Settings
UPLOAD_TMP_DIR = '../DB/upload_tmp'
UPLOAD_CHUNK_SIZE = 2048

# Transaction security
TX_TIME_WINDOW_SECONDS = 600

# Push notifications (FCM)
# Set FCM_ENABLED=True and provide FCM_SERVER_KEY to enable push delivery.
FCM_ENABLED = False
FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY", "")

# Logging
DEBUG_MODE = _env_flag("AUREX_DEBUG_MODE", os.getenv("DEBUG_MODE", "1"))
LOGGING_LEVEL = logging.DEBUG if DEBUG_MODE else logging.WARNING
LOG_FORMAT = "%(asctime)s | %(filename)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

AurexLogger.configure(DEBUG_MODE)

logger = AurexLogger.get_logger(__name__)

logger.info(
    "Config loaded: Server running on %s:%s (broadcast ip: %s)",
    SERVER_HOST,
    SERVER_PORT,
    SERVER_IP or "auto",
)
