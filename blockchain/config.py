"""
Blockchain Configuration and Constants
"""

# ============================================================================
# NETWORK CONFIGURATION
# ============================================================================
POW_DEFAULT_PORT = 13245
POA_DEFAULT_PORT = 13246
DEFAULT_SOCKET_TIMEOUT = 5
DEFAULT_LISTEN_BACKLOG = 5
SOCKET_BUFFER_SIZE = 4096

# ============================================================================
# CONSENSUS CONFIGURATION
# ============================================================================
POW_MODE = "POW"
POA_MODE = "POA"
DEFAULT_POW_DIFFICULTY = 2
MINING_PROGRESS_INTERVAL = 100000  # Log progress every N attempts

# ============================================================================
# MESSAGE TYPES
# ============================================================================
MSG_TYPE_BLOCK_FOUND = "BLOCK_FOUND"
MSG_TYPE_BLOCK_COMMITTED = "BLOCK_COMMITTED"
MSG_TYPE_NEW_TRANSACTION = "NEW_TRANSACTION"

# ============================================================================
# BLOCK FIELDS
# ============================================================================
BLOCK_FIELD_INDEX = 'index'
BLOCK_FIELD_TIMESTAMP = 'timestamp'
BLOCK_FIELD_DATA = 'data'
BLOCK_FIELD_PREVIOUS_HASH = 'previous_hash'
BLOCK_FIELD_HASH = 'hash'
BLOCK_FIELD_NONCE = 'nonce'
BLOCK_FIELD_MINER = 'miner'
BLOCK_FIELD_SIGNER_ID = 'signer_id'
BLOCK_FIELD_SIGNATURE = 'signature'

# ============================================================================
# MESSAGE FIELDS
# ============================================================================
MSG_FIELD_TYPE = 'type'
MSG_FIELD_CONTENT = 'content'
MSG_FIELD_SENDER = 'sender'
MSG_FIELD_DATA = 'data'
MSG_FIELD_TIMESTAMP = 'timestamp'
MSG_FIELD_ID = 'id'
MSG_FIELD_SIG = 'sig'

# ============================================================================
# VALIDATION CONSTANTS
# ============================================================================
MIN_NONCE = 0
HASH_ALGORITHM = 'sha256'
SIGNATURE_PREFIX = "SIG_"
SIGNATURE_ALGORITHM = 'md5'

# ============================================================================
# ERROR MESSAGES
# ============================================================================
ERROR_INVALID_DATA = "Invalid or missing data"
ERROR_INVALID_BLOCK = "Invalid block format"
ERROR_MISSING_BLOCK_FIELD = "Block missing required field"
ERROR_INVALID_PEER = "Invalid peer address"
ERROR_EMPTY_BLOCK = "Cannot process empty block"
ERROR_EMPTY_TRANSACTION = "Cannot send empty transaction"
ERROR_INVALID_MODE = "Unknown consensus mode"
ERROR_UNAUTHORIZED_NODE = "Node is not authorized"
ERROR_INVALID_SIGNATURE = "Invalid signature format or content"
