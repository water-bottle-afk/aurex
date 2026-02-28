"""
Aurex Server Configuration
Update these settings when you change physical locations or network configuration
"""

# Server Configuration
SERVER_HOST = '0.0.0.0'  # Listen on all interfaces
SERVER_PORT = 23456      # Main TLS connection port
SERVER_IP = '192.168.1.61'  # Local network IP (update this when you change location)
# Block confirmation listener (RPC server sends block_confirmation here)
BLOCK_CONFIRMATION_PORT = 23457

# Gateway (RPC) server for PoW submissions
GATEWAY_HOST = '127.0.0.1'
GATEWAY_PORT = 5000

# Broadcast Discovery Configuration
BROADCAST_PORT = 12345   # UDP port for WHRSRV discovery
BROADCAST_TIMEOUT = 5    # Seconds to wait for discovery response

# SSL/TLS Configuration
SSL_CERT_FILE = 'cert.pem'
SSL_KEY_FILE = 'key.pem'

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

# Upload Settings
UPLOAD_TMP_DIR = '../DB/upload_tmp'
UPLOAD_CHUNK_SIZE = 32768  # 32 KB raw bytes per chunk (safe for 2-byte length + base64)

# Logging
LOGGING_LEVEL = 10  # 10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR, 50=CRITICAL

print(" Config loaded: Server running on {server_ip}:{server_port}".format(
    server_ip=SERVER_IP,
    server_port=SERVER_PORT
))
