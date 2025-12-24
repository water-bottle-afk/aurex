"""
Blockchain Utilities and Helper Functions
"""

import json
import socket
import logging
import time
from config import *

logger = logging.getLogger(__name__)


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def is_valid_data(data):
    """Check if data is valid for processing"""
    return data is not None and isinstance(data, str) and len(data) > 0


def is_valid_block(block, required_fields=None):
    """
    Validate block structure
    
    Args:
        block: Block dictionary to validate
        required_fields: List of required field names
        
    Returns:
        tuple: (is_valid, missing_fields)
    """
    if not block or not isinstance(block, dict):
        return False, ["block_structure"]
    
    if required_fields is None:
        required_fields = [BLOCK_FIELD_HASH, BLOCK_FIELD_NONCE]
    
    missing = [field for field in required_fields if field not in block]
    return len(missing) == 0, missing


def is_valid_peer_address(ip, port):
    """Validate peer IP and port"""
    return ip is not None and port is not None and isinstance(port, int) and port > 0


def is_valid_mode(mode):
    """Check if consensus mode is valid"""
    return mode in [POW_MODE, POA_MODE]


# ============================================================================
# HASH AND CRYPTO HELPERS
# ============================================================================

def create_hash_target(data, nonce):
    """Create hash target from data and nonce"""
    return f"{data}{nonce}".encode()


def check_hash_difficulty(hash_value, difficulty):
    """Check if hash meets difficulty requirement (leading zeros)"""
    required_prefix = '0' * difficulty
    return hash_value.startswith(required_prefix)


def create_signature(node_id, data):
    """Create a signature string for data"""
    import hashlib
    data_hash = hashlib.md5(str(data).encode()).hexdigest()
    return f"{SIGNATURE_PREFIX}{node_id}_{data_hash}"


def validate_signature_format(node_id, signature):
    """Validate signature format for a node"""
    expected_prefix = f"{SIGNATURE_PREFIX}{node_id}"
    return signature is not None and signature.startswith(expected_prefix)


# ============================================================================
# BLOCK CREATION HELPERS
# ============================================================================

def create_pow_block(data, nonce, hash_value, miner_id, index=0):
    """Create a PoW block with standard fields"""
    return {
        BLOCK_FIELD_INDEX: index,
        BLOCK_FIELD_TIMESTAMP: time.time(),
        BLOCK_FIELD_DATA: data,
        BLOCK_FIELD_PREVIOUS_HASH: None,
        BLOCK_FIELD_NONCE: nonce,
        BLOCK_FIELD_HASH: hash_value,
        BLOCK_FIELD_MINER: miner_id,
    }


def create_poa_block(data, signer_id, signature, index=0):
    """Create a PoA block with standard fields"""
    import hashlib
    return {
        BLOCK_FIELD_INDEX: index,
        BLOCK_FIELD_TIMESTAMP: time.time(),
        BLOCK_FIELD_DATA: data,
        BLOCK_FIELD_PREVIOUS_HASH: None,
        BLOCK_FIELD_SIGNER_ID: signer_id,
        BLOCK_FIELD_SIGNATURE: signature,
        BLOCK_FIELD_HASH: hashlib.sha256(str(data).encode()).hexdigest(),
    }


# ============================================================================
# MESSAGE HELPERS
# ============================================================================

def create_message(msg_type, content, sender_id):
    """Create a standard message"""
    return {
        MSG_FIELD_TYPE: msg_type,
        MSG_FIELD_CONTENT: content,
        MSG_FIELD_SENDER: sender_id,
        MSG_FIELD_TIMESTAMP: time.time(),
    }


def create_transaction_message(data, sender_id, node_signature=None):
    """Create a transaction message"""
    message = {
        MSG_FIELD_TYPE: MSG_TYPE_NEW_TRANSACTION,
        MSG_FIELD_DATA: data,
        MSG_FIELD_SENDER: sender_id,
        MSG_FIELD_TIMESTAMP: time.time(),
    }
    
    # Add signature if provided (for PoA nodes)
    if node_signature:
        message[MSG_FIELD_ID] = sender_id
        message[MSG_FIELD_SIG] = node_signature
    
    return message


def parse_message(data_str):
    """
    Parse JSON message from string
    
    Returns:
        tuple: (message_dict, error_message)
    """
    try:
        if not data_str or not isinstance(data_str, str):
            return None, "Invalid message string"
        
        message = json.loads(data_str)
        if not isinstance(message, dict):
            return None, "Message must be a dictionary"
        
        return message, None
    except json.JSONDecodeError as e:
        return None, f"JSON decode error: {e}"
    except Exception as e:
        return None, f"Message parsing error: {e}"


# ============================================================================
# SOCKET HELPERS
# ============================================================================

def create_socket():
    """Create and configure a TCP socket"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(DEFAULT_SOCKET_TIMEOUT)
    return sock


def send_to_peer(ip, port, message):
    """
    Send message to a peer
    
    Returns:
        tuple: (success, error_message)
    """
    if not is_valid_peer_address(ip, port):
        return False, f"Invalid peer address: {ip}:{port}"
    
    try:
        sock = create_socket()
        sock.connect((ip, port))
        sock.send(json.dumps(message).encode())
        sock.close()
        return True, None
    except socket.timeout:
        return False, f"Connection timeout to {ip}:{port}"
    except ConnectionRefusedError:
        return False, f"Connection refused by {ip}:{port}"
    except Exception as e:
        return False, str(e)


# ============================================================================
# LOGGING HELPERS
# ============================================================================

def log_block_solution(node_id, hash_value, nonce, elapsed_time):
    """Log mining solution details"""
    logger.info(f"[{node_id}] Mining solution found!")
    logger.info(f"[{node_id}] Hash: {hash_value}")
    logger.info(f"[{node_id}] Nonce: {nonce}")
    logger.info(f"[{node_id}] Time: {elapsed_time:.2f}s")


def log_mining_progress(node_id, attempts):
    """Log mining progress"""
    logger.debug(f"[{node_id}] Mining attempts: {attempts:,}")


def log_block_added(node_id, chain_length):
    """Log when block is added to chain"""
    logger.info(f"[{node_id}] Block added to chain. Length: {chain_length}")


def log_peer_connection(node_id, ip, port):
    """Log peer connection"""
    logger.info(f"[{node_id}] Connected to peer: {ip}:{port}")


def log_broadcast_result(node_id, success_count, total_peers):
    """Log broadcast results"""
    logger.info(f"[{node_id}] Broadcast: {success_count}/{total_peers} peers")
