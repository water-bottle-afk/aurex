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
BLOCKCHAIN_DB_PATH = '../DB/database.sqlite3'

# Logging
LOGGING_LEVEL = 10  # 10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR, 50=CRITICAL

print("✅ Config loaded: Server running on {server_ip}:{server_port}".format(
    server_ip=SERVER_IP,
    server_port=SERVER_PORT
))
