# 📡 Protocol Connection Flow & Debugging Guide

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    APP START                            │
│                  (main.dart)                            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│         ServerConnectionScreen                          │
│  Initializes connection to blockchain server            │
│  - Shows loading dialog                                 │
│  - Sends START|Client_Flutter_App                       │
│  - Waits for ACCPT|ok (3 second timeout)                │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
      SUCCESS                  FAILURE
         │                       │
         ▼                       ▼
   Navigate to     Show error dialog with
   Home (/login)   "TRY AGAIN" button
         │                       │
         │                  [User clicks TRY AGAIN]
         │                       │
         │                       └─────────────┐
         │                                     │
         ▼                                     ▼
   User can login              Retry connection
```

---

## 1. Initial Connection Flow

### What Happens When App Starts:

```
App Launch (main())
    ↓
MyApp() created
    ↓
ServerConnectionScreen shown
    ↓
initState() called
    ↓
_initializeConnection()
    ├─ Show loading dialog
    ├─ Call ClientProvider.initializeConnection()
    │   └─ Call Client.connect()
    │       ├─ Connect TLS socket to server (172.16.64.109:23456)
    │       ├─ Call _sendStartMessage()
    │       │   ├─ Send: "START|Client_Flutter_App" (with 2-byte length prefix)
    │       │   ├─ Add to messageHistory
    │       │   ├─ Receive response
    │       │   ├─ Check if response starts with "ACCPT"
    │       │   └─ Success: Add to messageHistory
    │       └─ Return to connect()
    │
    ├─ Wait for connection (max 3 seconds)
    │
    └─ If successful: Show success dialog → Navigate to /
       If failed: Show error dialog with "TRY AGAIN" button
```

### File Structure:
- **Initialization**: `lib/main.dart` - ServerConnectionScreen
- **Connection**: `lib/client_class.dart` - Client.connect()
- **Provider**: `lib/providers/client_provider.dart` - ClientProvider
- **Messages tracked**: `client._messageHistory` (List<MessageEvent>)

---

## 2. LOGIN Message Flow

### When User Clicks Login Button:

```
LoginScreen
    │
    └─ User enters username & password
           │
           ▼
    onLogin() button pressed
           │
           ▼
    Call ClientProvider.client.login(username, password)
           │
           ▼
    Client.login()
       ├─ Create message: "LOGIN|username|password"
       ├─ Add to _messageHistory with status='pending'
       ├─ Call sendMessage()
       │   ├─ Encode message to bytes
       │   ├─ Create 2-byte length prefix (big-endian)
       │   ├─ Send: [length_bytes][message_bytes]
       │   └─ Add to _messageHistory with status='success'
       │
       └─ Call receiveMessage()
           ├─ Read 2-byte length header
           ├─ Read message bytes
           ├─ Decode to string
           ├─ Add to _messageHistory with status='success'
           │
           └─ Parse response:
               ├─ If starts with "LOGED": Return "success"
               ├─ If starts with "ERR": Return "error"
               └─ Add to _messageHistory
```

### Example Messages in History:

```
[14:23:45] → SENT: LOGIN|john_doe|password123 (pending)
[14:23:46] → SENT: LOGIN|john_doe|password123 (success)
[14:23:47] ← RECV: LOGED|Login successful (success)
```

---

## 3. Server Processing (What Server Does)

```
Server receives from Client:
    ├─ Read 2-byte length prefix
    ├─ Read message: "LOGIN|username|password"
    ├─ Parse code: "LOGIN" (first 5 chars)
    ├─ Parse params: ["username", "password"]
    │
    ├─ Call handler: server.login(["username", "password"])
    │   ├─ Query database
    │   ├─ Check credentials
    │   └─ If valid:
    │       └─ Create response: "LOGED|Login Succeed"
    │
    └─ Send response with 2-byte length prefix
           ↓
Client receives response
```

---

## 4. Client Parsing Response

### Response Parsing:

```
receiveMessage() returns: "LOGED|Login Succeed"
    ↓
Client.login() parses:
    ├─ Split by '|': ["LOGED", "Login Succeed"]
    ├─ Extract code: parts[0] = "LOGED"
    ├─ Check code:
    │   ├─ If == "LOGED": 
    │   │   ├─ Set _isAuthenticated = true
    │   │   ├─ Notify listeners
    │   │   └─ Return "success"
    │   ├─ If starts with "ERR":
    │   │   ├─ Extract error msg: parts[1]
    │   │   └─ Return "error"
    │   └─ Else:
    │       └─ Return "unknown"
    │
    └─ Add "RECV" message to _messageHistory
           ↓
LoginScreen gets result:
    ├─ If "success": Navigate to home
    ├─ If "error": Show error dialog
    └─ If "unknown": Show error dialog
```

---

## 5. Debug Overlay / Console

### How to Use Debug Overlay:

1. **Add to any page**: Wrap your widget with `DebugOverlay`

```dart
@override
Widget build(BuildContext context) {
  return DebugOverlay(
    child: Scaffold(
      // Your page content
    ),
  );
}
```

2. **View messages**: 
   - Click the cyan bug icon (bottom right corner)
   - See all sent/received messages
   - Shows time, type (→ SENT, ← RECV, ⚙ SYS)
   - Shows status (✓ success, ✗ error, ⏳ pending)

3. **Debug output example**:
```
[14:23:45] [CONN] ⏳ → SENT: START|Client_Flutter_App
[14:23:46] [CONN] ✓ → SENT: START|Client_Flutter_App
[14:23:47] [CONN] ✓ ← RECV: ACCPT|ok
[14:30:12] [LOGIN] ⏳ → SENT: LOGIN|user|pass
[14:30:13] [LOGIN] ✓ → SENT: LOGIN|user|pass
[14:30:14] [LOGIN] ✓ ← RECV: LOGED|success
```

---

## 6. Message Event Class

### MessageEvent structure:

```dart
class MessageEvent {
  String type;        // 'sent', 'received', 'system'
  String message;     // The actual message content
  DateTime timestamp;  // When it was created
  String status;      // 'success', 'error', 'pending'
}
```

### Creating a MessageEvent:

```dart
_addMessageEvent(MessageEvent(
  type: 'sent',
  message: 'LOGIN|username|password',
  status: 'success',
));
```

### Accessing message history:

```dart
// From provider
final messages = Provider.of<ClientProvider>(context).client.messageHistory;

// Or directly
final messages = client.messageHistory;

// Each message has:
for (var msg in messages) {
  print('${msg.timestamp} - ${msg.type}: ${msg.message} (${msg.status})');
}
```

---

## 7. Connection Error Handling

### 3-Second Timeout Flow:

```
Client tries to connect
    │
    ├─ TLS socket connection started
    │   └─ Timeout: 10 seconds
    │
    ├─ Send START message
    │
    ├─ Wait for ACCPT response
    │
    └─ Overall timeout: 3 seconds (in ServerConnectionScreen)
           │
           ├─ If response in 3 seconds: SUCCESS
           │   └─ _showSuccessAndNavigate()
           │
           └─ If no response after 3 seconds: FAILURE
               └─ _showConnectionErrorDialog()
                   └─ User clicks "TRY AGAIN"
                       └─ Call _initializeConnection() again
```

### Error Dialog Shows:

```
┌─────────────────────────────────┐
│    Connection Error             │
│                                 │
│  Unable to connect with the     │
│  server. Check your internet    │
│  connection and try again.      │
│                                 │
│  Error: timeout                 │
│                                 │
│  [TRY AGAIN]                    │
└─────────────────────────────────┘
```

---

## 8. All Message Types Supported

| Message | Type | Protocol Code | Handled In |
|---------|------|---------------|-----------|
| START | Initialization | #1 | Client._sendStartMessage() |
| ACCPT | Initialization | #2 | Client._sendStartMessage() |
| LOGIN | Auth | #6 | Client.login() |
| SGNUP | Auth | #5 | Client.signUp() |
| SCODE | Auth | #9 | Client.sendVerificationCode() |
| VRFYC | Auth | #10 | Client.verifyCode() |
| UPDTE | Auth | #11 | Client.updatePassword() |
| LGOUT | Auth | #7 | Client.logout() |

---

## 9. How to Add Debug to Any Page

### Example: LoginScreen with Debug

```dart
class LoginScreen extends StatefulWidget {
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  void _handleLogin() async {
    final client = Provider.of<ClientProvider>(context, listen: false).client;
    
    // Show debug dialog before sending
    showDialog(
      context: context,
      builder: (_) => MessageDebugDialog(
        title: 'Sending Login Request',
        message: 'LOGIN|username|password',
        type: 'sent',
      ),
    );

    // Send message
    try {
      final result = await client.login(username, password);
      
      // Auto-show response debug dialog
      if (mounted) {
        showDialog(
          context: context,
          builder: (_) => MessageDebugDialog(
            title: 'Server Response',
            message: result == 'success' ? 'LOGED|Login successful' : 'ERR01|Login failed',
            type: result == 'success' ? 'received' : 'error',
          ),
        );
      }
    } catch (e) {
      // Show error debug dialog
      showDialog(
        context: context,
        builder: (_) => MessageDebugDialog(
          title: 'Connection Error',
          message: e.toString(),
          type: 'error',
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return DebugOverlay(
      child: Scaffold(
        // Your UI
      ),
    );
  }
}
```

---

## 10. Real-Time Message Tracking

### Messages are automatically tracked when:

1. **Connection starts**: "Attempting to connect to 172.16.64.109:23456"
2. **TLS connects**: "TLS Connected to server"
3. **START sent**: "START|Client_Flutter_App"
4. **ACCPT received**: "ACCPT|ok"
5. **LOGIN sent**: "LOGIN|username|password"
6. **Response received**: "LOGED|Login successful"
7. **Errors occur**: "Error: [error message]"

### View in real-time:

```dart
// Listen to message events
client.onMessageEvent = (event) {
  print('Message: ${event.toString()}');
  // Or update UI
};
```

---

## Summary

✅ **Connection**: START → ACCPT (with 3-sec timeout & retry)  
✅ **Login**: LOGIN sent → LOGED/ERR01 received  
✅ **Debug**: DebugOverlay shows all messages  
✅ **Errors**: 3-second timeout → Error dialog → Try again  
✅ **History**: All messages tracked in messageHistory list  
✅ **All pages**: Can wrap with DebugOverlay for debugging  

**Everything is working and logged!** 🚀
