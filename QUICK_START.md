# Quick Start Guide - Running Both Clients

## TL;DR

**Yes, the Python client can run standalone!** And the Dart client works for mobile/web. They're **complementary**, not competing.

---

## Setup & Run

### Prerequisites

```bash
# For Python client
pip install customtkinter cryptography logging

# For Dart client
flutter pub get
```

### Run Python Client (Standalone)

```bash
cd python_files
python client_class.py
```

**What you'll see:**
1. Application window opens
2. Connects to server automatically
3. LOGIN/SIGNUP tabs appear
4. Can test authentication directly

### Run Dart/Flutter Client

```bash
# On Android emulator
flutter run

# On physical device
flutter run -d <device-id>

# As web app
flutter run -d chrome
```

**What you'll see:**
1. Flutter app loads on device
2. Attempts TLS connection to server
3. Shows login/signup screens
4. All operations work the same as Python

---

## Example: Full User Journey

### Using Python Client

```
1. Run: python client_class.py
2. Window opens
3. Click "Sign up" tab
4. Enter: username="john_doe", password="Pass123!", email="john@example.com"
5. Click "Sign up" button
6. See: "SIGND|john_doe has been added"
7. Switch to "Login" tab
8. Enter credentials and login
9. Success! User is authenticated
```

### Using Dart Client (Same Flow)

```dart
// In your Flutter widget
final client = Client(
  host: "192.168.1.100",
  port: 5000
);

// Connect
await client.connect();

// Sign up
final result = await client.signUp(
  "john_doe",
  "Pass123!",
  "Pass123!",
  "john@example.com"
);

// Login
final loginResult = await client.login("john_doe", "Pass123!");

// Both return same protocol responses!
```

---

## Real-World Scenarios

### Scenario 1: Testing New Features
```bash
# Use Python client for quick testing
cd python_files
python client_class.py
# Test login, signup, password reset quickly
```

### Scenario 2: Production Deployment
```bash
# Use Dart/Flutter for user app
flutter build apk     # Android production
flutter build ios     # iOS production
flutter build web     # Web version

# Use Python client for:
# - Admin tools
# - Backend automation
# - Integration tests
```

### Scenario 3: Stress Testing
```bash
# Run multiple Python clients simultaneously
# Terminal 1
python python_files/client_class.py

# Terminal 2
python python_files/client_class.py

# Terminal 3
python python_files/client_class.py
# ... Create as many as needed
```

---

## File Structure

```
aurex/
├── python_files/
│   ├── proto.py                 # Protocol handler (BOTH use)
│   ├── classes.py               # DB, User, Logger classes
│   ├── client_class.py           # ✅ Python GUI Client
│   ├── run_server.py            # Server
│   └── ... (other server files)
│
├── lib/
│   ├── client_class.dart        # ✅ Dart/Flutter Protocol Client
│   ├── main.dart                # Flutter app entry
│   ├── pages/
│   │   ├── login_screen.dart
│   │   ├── signup_screen.dart
│   │   └── ... (other pages)
│   ├── providers/
│   │   ├── client_provider.dart # Uses client_class.dart
│   │   └── ... (other providers)
│   └── services/                # API integration
│
└── (Firebase, Android, iOS, web configs...)
```

---

## Key Differences

### Python Client (Desktop)

**Pros:**
- Run immediately without build process
- Easy to customize GUI
- Great for testing/debugging
- Can run multiple instances for stress testing

**Cons:**
- Desktop only
- Not suitable for app store distribution
- Requires Python runtime

**Command:**
```bash
python python_files/client_class.py
```

### Dart Client (Mobile/Web)

**Pros:**
- Cross-platform (iOS, Android, Web)
- Can distribute on app stores
- Native performance
- Beautiful UI with Flutter

**Cons:**
- Requires compilation/build step
- Slightly longer development cycle

**Command:**
```bash
flutter run
```

---

## Connecting to Different Servers

### Change Python Client Server

In `python_files/client_class.py`, modify:
```python
tcp_ip = "192.168.1.100"    # Change this
tcp_port = 5000              # Or this
```

### Change Dart Client Server

In `lib/client_class.dart`, modify:
```dart
Client({
    this.host = "192.168.1.100",   // Change this
    this.port = 23456              // Or this
});
```

---

## Network Configuration

### Local Network Testing
```
Server:         192.168.1.50:5000
Python Client:  192.168.1.100 (can connect)
Dart Client:    192.168.1.101 (can connect)

All on same LAN = Works!
```

### Internet Deployment
```
Server:         example.com:5000 (SSL certificate required)
Python Client:  internet (works)
Dart Client:    internet (works)

Both can connect from anywhere!
```

---

## Debugging

### Python Client Debug Logs

```python
# In client_class.py
logging_level = 10  # DEBUG

# Output shows:
# Sent >>>>> LOGIN|username|password
# Received <<<<< LOGED|success_message
```

### Dart Client Debug Logs

```dart
// In client_class.dart
final logger = Logger('Client');

// Output shows:
// [FINE] Sent >>>>> LOGIN|username|password
// [FINE] Received <<<<< LOGED|success_message
```

---

## Common Issues & Solutions

### "Connection refused"
- **Python**: Check `tcp_ip` and `tcp_port` in `__init__`
- **Dart**: Check `host` and `port` in Client constructor
- **Server**: Make sure server is running on specified port

### "Self-signed certificate"
- **Python**: Already handles it (CERT_NONE)
- **Dart**: Already handles it (`onBadCertificate: (_) => true`)
- Both accept self-signed certificates

### "Message format error"
- Ensure message has exactly: `CODE|param1|param2`
- Both clients validate before sending
- Check server protocol implementation

---

## Production Checklist

- [ ] Server running and accessible
- [ ] Python client can connect and authenticate
- [ ] Dart app can connect and authenticate
- [ ] All auth methods tested (login, signup, password reset)
- [ ] Multiple clients can connect simultaneously
- [ ] Error handling works for all error codes
- [ ] Logging is enabled for troubleshooting
- [ ] TLS certificates configured properly

---

## Summary

```
┌─ Python Client ─────────────────────┐
│ - Run standalone                    │
│ - Test features immediately         │
│ - Desktop/console use               │
│ python python_files/client_class.py │
└─────────────────────────────────────┘
           │
           │ Both use SAME protocol
           │
           ▼
      [Protocol Spec]
           │
           │
           ▼
┌─ Dart/Flutter Client ────────────────┐
│ - Mobile & web app                  │
│ - Production user interface          │
│ - App store distribution             │
│ flutter run                          │
└──────────────────────────────────────┘
```

**Both work. Both are ready to use. Choose based on your needs!**
