"""
Aurex Server Configuration
Update these settings when you change physical locations or network configuration
"""

# Server Configuration
SERVER_HOST = '0.0.0.0'  # Listen on all interfaces
SERVER_PORT = 23456      # Main TLS connection port
SERVER_IP = '10.100.102.58'  # Local network IP (update this when you change location)

# Broadcast Discovery Configuration
BROADCAST_PORT = 12345   # UDP port for WHRSRV discovery
BROADCAST_TIMEOUT = 5    # Seconds to wait for discovery response

# SSL/TLS Configuration
SSL_CERT_FILE = 'cert.pem'
SSL_KEY_FILE = 'key.pem'

# Database Configuration
DATABASE_TYPE = 'sqlite'  # or 'firebase'
DATABASE_FOLDER = '../DB'  # All database files stored here
MARKETPLACE_DB_PATH = '../DB/marketplace.db'
BLOCKCHAIN_DB_PATH = '../DB/database.sqlite3'

# Logging
LOGGING_LEVEL = 10  # 10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR, 50=CRITICAL

# Firebase (if enabled)
FIREBASE_ENABLED = False
FIREBASE_CREDENTIALS = 'serviceAccountKey.json'
FIREBASE_DATABASE_URL = 'https://your-project.firebaseio.com'

print("✅ Config loaded: Server running on {server_ip}:{server_port}".format(
    server_ip=SERVER_IP,
    server_port=SERVER_PORT
))
