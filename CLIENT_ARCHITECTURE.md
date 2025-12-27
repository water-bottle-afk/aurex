# Client Architecture - Python + Dart

## Overview

Your Blockchain project has **TWO complementary clients** that both use the same protocol:

### 1. **Python Client** (`python_files/client_class.py`)
- **Use Case**: Backend testing, automation, desktop applications
- **Platform**: Windows, Linux, macOS
- **Features**: Full GUI with Tkinter, can run standalone

### 2. **Dart/Flutter Client** (`lib/client_class.dart`)
- **Use Case**: Mobile and web frontend
- **Platform**: iOS, Android, Web
- **Features**: Native mobile/web UI with Flutter

Both clients implement the **same protocol specification** and can connect to the same server!

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                   Blockchain Server                         │
│            (python_files/run_server.py)                     │
│                  TLS Port: 5000                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
    ┌────────┐   ┌──────────┐   ┌──────────┐
    │ Python │   │ Python   │   │  Dart/   │
    │Client 1│   │ Client 2 │   │ Flutter  │
    │        │   │          │   │  Client  │
    └────────┘   └──────────┘   └──────────┘
```

---

## How to Use Each Client

### **Using the Python Client**

```bash
# Install dependencies
pip install customtkinter cryptography

# Run the client
cd python_files
python client_class.py
```

**Features:**
- GUI for login/signup
- Email verification
- Password reset
- Game functionality
- Full error handling

### **Using the Dart/Flutter Client**

```bash
# Install dependencies
flutter pub get

# Run on device/emulator
flutter run

# Or build for production
flutter build apk      # Android
flutter build ios      # iOS
flutter build web      # Web
```

**Features:**
- Native mobile UI
- Smooth animations
- Device-specific optimizations
- Same protocol support

---

## Protocol Compatibility Matrix

Both clients support **ALL** protocol messages:

| Message | Python Client | Dart Client | Status |
|---------|---------------|-------------|--------|
| START   | ✅            | ✅          | Implemented |
| ACCPT   | ✅            | ✅          | Implemented |
| LOGIN   | ✅            | ✅          | Implemented |
| SGNUP   | ✅            | ✅          | Implemented |
| SCODE   | ✅            | ✅          | Implemented |
| VRFYC   | ✅            | ✅          | Implemented |
| UPDTE   | ✅            | ✅          | Implemented |
| LGOUT   | ✅            | ✅          | Implemented |

---

## Code Comparison

### Sending a LOGIN message

**Python:**
```python
def login_clicked(self):
    msg = f"LOGIN|{self.username.get()}|{self.password.get()}"
    self.PROTO.send_one_message(msg.encode())
```

**Dart:**
```dart
Future<String> login(String username, String password) async {
    final message = "LOGIN|$username|$password";
    await sendMessage(message);
    final response = await receiveMessage();
    // Parse and return result
}
```

Both implement the **same protocol format**!

### Message Framing

Both clients use identical framing:
```
[2-byte length (big-endian)] [message data]
```

---

## Configuration

### Python Client
Edit in `python_files/client_class.py`:
```python
logging_level = 10  # 10=DEBUG, 20=INFO, etc.
tcp_ip = "192.168.1.100"  # Server IP
tcp_port = 5000  # Server port
```

### Dart Client
Edit in `lib/client_class.dart`:
```dart
Client({
    this.host = "172.16.64.109",  // Server IP
    this.port = 23456              // Server port
});
```

---

## Deployment Options

### Option 1: Python + Dart (Recommended)
- **Backend Testing**: Use Python client for automation/testing
- **User Mobile App**: Use Dart/Flutter for iOS/Android
- **User Web App**: Use Dart/Flutter web build

### Option 2: Python Only
- Run desktop Python client on Windows/Linux
- For testing and backend automation

### Option 3: Dart Only
- Use Flutter web version in browsers
- Use native mobile apps

---

## Testing Multiple Clients

Since both clients use the same protocol, you can test with **multiple clients simultaneously**:

```bash
# Terminal 1: Run Python client
cd python_files
python client_class.py

# Terminal 2: Run another Python client
cd python_files
python client_class.py

# Terminal 3: Run Flutter app (on emulator/device)
cd ..
flutter run
```

The server handles multiple concurrent connections!

---

## Troubleshooting

### Connection Issues

**Python Client Connection Error:**
```python
# Check server IP and port in __init__
self.PROTO.connect("192.168.1.100", 5000, use_tls=True)
```

**Dart Client Connection Error:**
```dart
// Check server IP and port in Client constructor
Client(host: "192.168.1.100", port: 5000)
```

### Protocol Mismatch

Both clients expect:
- Server sends/receives with 2-byte length prefix
- Messages in format: `CODE|param1|param2|...`
- TLS encryption for all data

### Logging

**Python:**
```python
logging_level = 10  # Set to DEBUG
# Logs will show all sent/received messages
```

**Dart:**
```dart
final logger = Logger('Client');
logger.info("message");  // Enable logging in your IDE
```

---

## Summary

| Aspect | Python | Dart |
|--------|--------|------|
| **Platform** | Desktop | Mobile/Web |
| **Protocol** | ✅ Same | ✅ Same |
| **Message Format** | ✅ Identical | ✅ Identical |
| **TLS Support** | ✅ Yes | ✅ Yes |
| **Concurrent Users** | ✅ Yes | ✅ Yes |
| **Best For** | Testing/Backend | Production Users |

Both clients are **production-ready** and fully compatible with your server!
