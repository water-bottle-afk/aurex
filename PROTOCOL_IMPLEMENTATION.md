# Blockchain Communication Protocol Implementation

## Overview
This document describes the implementation of the communication protocol for the Blockchain Image Ownership System. The protocol uses TLS (Transport Layer Security) for encrypted communication between clients and servers.

## Implementation Files

### 1. `python_files/proto.py` - PROTO Class
The PROTO class handles all message communication over TLS.

#### Key Features:
- **TLS Encryption**: Automatic TLS wrapping for secure communication
- **Message Framing**: 2-byte length prefix for message boundaries
- **Thread-Safe**: Uses locks for concurrent access
- **Logging**: Integrated logging for debugging and monitoring

#### Main Methods:
- `connect(ip, port, use_tls=True)`: Establish TLS connection to server
- `send_one_message(data, encryption=True)`: Send message with length prefix
- `recv_one_message(encryption=True)`: Receive message with length prefix
- `close()`: Gracefully close connection

### 2. `python_files/client_class.py` - Client Implementation
The Client class handles all client-side operations and protocol communication.

#### Connection Initialization:
1. Creates PROTO instance
2. Connects to server with TLS
3. Sends START message (Protocol #1)
4. Receives ACCPT acknowledgment (Protocol #2)
5. Starts receive loop for incoming messages

#### Authentication Methods:

##### Login (Protocol #6: LOGIN)
```
MESSAGE FORMAT: LOGIN|username|password
RESPONSE: LOGED|success_message or ERR01|error_message
```

##### Sign Up (Protocol #5: SGNUP)
```
MESSAGE FORMAT: SGNUP|username|password|verify_password|email
RESPONSE: SIGND|success_message or ERR10|error_message
```

##### Send Verification Code (Protocol #9: SCODE)
```
MESSAGE FORMAT: SCODE|email
RESPONSE: SENTM|success_message or ERR04|error_message
```

##### Verify Code (Protocol #10: VRFYC)
```
MESSAGE FORMAT: VRFYC|email|code
RESPONSE: VRFYD|success_message or ERR08|error_message
```

##### Update Password (Protocol #11: UPDTE)
```
MESSAGE FORMAT: UPDTE|email|new_password|confirm_password
RESPONSE: UPDTD|success_message or ERR07|error_message
```

## Protocol Message Structure

All messages follow the format:
```
[CODE]|[param1]|[param2]|...|[paramN]
```

Where:
- **CODE**: 5-byte message code (e.g., LOGIN, SGNUP, VRFYC)
- **|**: Separator character
- **Parameters**: Variable number of pipe-separated parameters

## Message Flow

### Connection Establishment
```
Client                                Server
  |                                    |
  |----------- START|... ------------>|
  |<--------- ACCPT|ok -----------|
  |                                    |
  |  (Connection established, can exchange messages)
  |
```

### Authentication Example (Login)
```
Client                                Server
  |                                    |
  |-- LOGIN|user|pass ------->|
  |<---- LOGED|success ------|
  |                                    |
```

## Error Handling

Error messages use code format: `ERR[XX]` where XX is the error number.

Common errors:
- `ERR01`: Authentication error (invalid username/password)
- `ERR04`: Error sending code
- `ERR05`: Missing required parameters
- `ERR07`: Invalid password change
- `ERR08`: Invalid verification code
- `ERR10`: Server error

## Threading Model

- **Main Thread**: GUI event loop
- **Receive Thread**: Dedicated thread for receiving messages from server
- **Handler Threads**: Daemon threads created for each incoming message to prevent blocking

## Message Reception Flow

```
recv_loop()
    ↓
recv_one_message() → Parse query code
    ↓
Check if error (ERR prefix)
    ↓
Dispatch to handler function in dict_of_operations
    ↓
Handler executes in daemon thread
```

## Security

### TLS Implementation
- Uses SSL/TLS for all communications
- Self-signed certificate support (CERT_NONE verification)
- Automatic encryption/decryption by the OS

### Message Size Limits
- Maximum message size: 65,535 bytes (2-byte length field)
- Client validates message size before sending

## Installation Requirements

```bash
pip install customtkinter cryptography
```

## Usage Example

```python
from client_class import Client
import logging

# Create client instance with TLS connection
client = Client(
    ip="192.168.1.100",
    port=5000,
    logging_level=logging.DEBUG
)

# Client automatically:
# 1. Connects with TLS
# 2. Sends START message
# 3. Receives ACCPT
# 4. Starts receive loop
# 5. Displays GUI for login/signup
```

## Notes

- All message codes are exactly 5 bytes (padded with spaces if needed)
- The pipe separator (|) is required between code and first parameter
- Message dispatch is case-sensitive
- Connection automatically uses TLS - no manual encryption key exchange needed
- Server responses must follow protocol format for client to correctly parse them

## Testing

To test the implementation:

1. Ensure server is running and listening on specified IP:port
2. Start client with correct server details
3. Client should establish TLS connection automatically
4. Test each operation (login, signup, etc.) through the GUI
5. Monitor logs for any connection/protocol errors
