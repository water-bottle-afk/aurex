/// AUREX CLIENT PROTOCOL DOCUMENTATION
/// =====================================
/// All client operations and their protocol messages:
///
/// 1. START - Connection initialization
///    Send: START|Client_Flutter_App
///    Recv: ACCPT|Connection accepted
///
/// 2. LOGIN - User authentication (by USERNAME)
///    Send: LOGIN|username|password
///    Recv: OK|username or ERR|error_message
///
/// 3. SIGNUP - User registration (by USERNAME)
///    Send: SIGNUP|username|password
///    Recv: OK or ERR|error_message
///
/// 4. SEND_CODE - Request password reset OTP code via username
///    Send: SEND_CODE|username
///    Recv: OK|otp_sent or ERR|error_message
///
/// 5. VERIFY_CODE - Verify OTP code for password reset
///    Send: VERIFY_CODE|username|otp_code
///    Recv: OK|token or ERR|error_message
///
/// 6. UPDATE_PASSWORD - Change user password (after OTP verification)
///    Send: UPDATE_PASSWORD|username|new_password
///    Recv: OK or ERR|error_message
///
/// 7. LOGOUT - User logout
///    Send: LOGOUT|username
///    Recv: OK or ERR|error_message
///
/// 8. UPLOAD - Upload/register marketplace item (asset)
///    Send: UPLOAD|asset_name|username|google_drive_url|file_type|cost
///    Recv: OK|asset_id or ERR|error_message
///
/// 9. GET_ITEMS - Get all marketplace items
///    Send: GET_ITEMS
///    Recv: OK|item1|item2|... or ERR|error_message
///
/// 10. GET_ITEMS_PAGINATED - Lazy scrolling with timestamp cursor
///     Send: GET_ITEMS_PAGINATED|limit[|timestamp]
///     Recv: OK|item1|item2|... or ERR|error_message
///
/// 12. BUY - Purchase an asset from marketplace
///     Send: BUY|asset_id|username|amount
///     Recv: OK|transaction_id or ERR|error_message
///
/// 13. SEND - Send purchased asset to another user
///     Send: SEND|asset_id|sender_username|receiver_username
///     Recv: OK|transaction_id or ERR|error_message
///
/// 14. GET_PROFILE - Get user profile (anonymous)
///     Send: GET_PROFILE|username
///     Recv: OK|username|email|created_at or ERR|error_message
library;

import 'dart:io';
import 'dart:async';
import 'dart:convert';
import 'package:logging/logging.dart';
import 'package:flutter/foundation.dart';
import 'config.dart';

/// Message event for debugging - tracks sent/received messages
class MessageEvent {
  final String type; // 'sent', 'received', 'system'
  final String message;
  final DateTime timestamp;
  final String status; // 'success', 'error', 'pending'

  MessageEvent({
    required this.type,
    required this.message,
    required this.status,
  }) : timestamp = DateTime.now();

  @override
  String toString() =>
      '[${timestamp.hour.toString().padLeft(2, '0')}:${timestamp.minute.toString().padLeft(2, '0')}:${timestamp.second.toString().padLeft(2, '0')}] $type: $message ($status)';
}

/// Protocol message handler for Blockchain Communication Protocol
class Client extends ChangeNotifier {
  SecureSocket? _socket;
  late String host;
  late int port;
  final Logger _logger = Logger('Client');
  bool _isConnected = false;
  bool _isAuthenticated = false;

  // Persistent socket stream and receive buffer
  StreamSubscription? _socketSubscription;
  final List<int> _receiveBuffer = [];

  // Message tracking for debugging
  final List<MessageEvent> _messageHistory = [];
  Function(MessageEvent)? onMessageEvent;

  bool get isConnected => _isConnected;
  bool get isAuthenticated => _isAuthenticated;
  List<MessageEvent> get messageHistory => List.unmodifiable(_messageHistory);

  Client({String? initialHost, int? initialPort}) {
    host = initialHost ?? ClientConfig.defaultServerHost;
    port = initialPort ?? ClientConfig.defaultServerPort;
  }

  /// Push message to screen (helper function to reduce code duplication)
  void pushMessageToScreen({
    required String type,
    required String message,
    required String status,
  }) {
    final event = MessageEvent(
      type: type,
      message: message,
      status: status,
    );
    _messageHistory.add(event);
    _logger.info(event.toString());
    onMessageEvent?.call(event);
    notifyListeners();
  }

  /// Discover server via broadcast message WHRSRV
  /// Listens for SRVRSP|ip|port response
  Future<bool> discoverServer({
    Duration timeout = ClientConfig.broadcastTimeout,
    int broadcastPort = ClientConfig.broadcastPort,
  }) async {
    try {
      pushMessageToScreen(
        type: 'system',
        message: 'Discovering server via broadcast...',
        status: 'pending',
      );

      final discoveredServer = await _broadcastWhereIsServer(
        broadcastPort: broadcastPort,
        timeout: timeout,
      );

      if (discoveredServer != null) {
        host = discoveredServer['ip']!;
        port = discoveredServer['port']!;
        notifyListeners();

        pushMessageToScreen(
          type: 'system',
          message: '🔍 Server discovered at $host:$port',
          status: 'success',
        );
        return true;
      } else {
        pushMessageToScreen(
          type: 'system',
          message: 'Server discovery timeout - using default server',
          status: 'pending',
        );
        return false;
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Server discovery failed: $e',
        status: 'error',
      );
      return false;
    }
  }

  /// Broadcast WHRSRV message and wait for SRVRSP response
  Future<Map<String, dynamic>?> _broadcastWhereIsServer({
    int broadcastPort = ClientConfig.broadcastPort,
    Duration timeout = ClientConfig.broadcastTimeout,
  }) async {
    try {
      final socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
      socket.broadcastEnabled = true;

      // Send WHRSRV broadcast
      const message = "WHRSRV";
      final broadcastAddr = InternetAddress("255.255.255.255");

      socket.send(
        utf8.encode(message),
        broadcastAddr,
        broadcastPort,
      );

      print('📡 Broadcast WHRSRV sent');

      // Listen for response with timeout
      final future = socket.timeout(timeout);

      try {
        await for (final event in future) {
          if (event == RawSocketEvent.read) {
            final datagram = socket.receive();
            if (datagram != null) {
              final response = utf8.decode(datagram.data);
              print('📡 Received broadcast response: $response');

              if (response.startsWith("SRVRSP|")) {
                final parts = response.split('|');
                if (parts.length >= 3) {
                  socket.close();
                  return {
                    'ip': parts[1],
                    'port': int.parse(parts[2]),
                  };
                }
              }
            }
          }
        }
      } on TimeoutException {
        print('📡 Broadcast discovery timeout');
      }

      socket.close();
      return null;
    } catch (e) {
      print('📡 Broadcast error: $e');
      return null;
    }
  }

  /// Connect to server via TLS with START/ACCPT handshake
  /// Can optionally discover server first
  Future<void> connect({bool discoverFirst = true}) async {
    try {
      // Try to discover server first if requested
      if (discoverFirst) {
        await discoverServer();
      }

      pushMessageToScreen(
        type: 'system',
        message: 'Attempting to connect to $host:$port',
        status: 'pending',
      );

      _socket = await SecureSocket.connect(
        host,
        port,
        onBadCertificate: (_) => true,
      ).timeout(
        const Duration(seconds: 10),
        onTimeout: () {
          throw Exception('Connection timeout after 10 seconds - server may be offline');
        },
      );

      _isConnected = true;
      notifyListeners();

      pushMessageToScreen(
        type: 'system',
        message: '🔒 TLS Connected to server',
        status: 'success',
      );

      // Start persistent socket listener BEFORE sending any messages
      _startSocketListener();

      // Send START message for connection initialization
      await _sendStartMessage();
      
      print('✅ Connection successful and handshake complete');
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Connection failed: $e',
        status: 'error',
      );

      _isConnected = false;
      notifyListeners();
      rethrow;
    }
  }

  /// Manually set server address
  void setServerAddress(String newHost, int newPort) {
    host = newHost;
    port = newPort;
    notifyListeners();

    pushMessageToScreen(
      type: 'system',
      message: 'Server address changed to $host:$port',
      status: 'success',
    );
  }

  /// Send START message for protocol initialization
  /// Protocol Message 1: START (client → server)
  /// Receives: ACCPT (server → client)
  Future<void> _sendStartMessage() async {
    try {
      const startMsg = "START|Client_Flutter_App";

      pushMessageToScreen(
        type: 'sent',
        message: startMsg,
        status: 'pending',
      );

      await sendMessage(startMsg);
      print('📤 START message sent');

      // Wait for ACCPT response
      final response = await receiveMessage();
      print('📥 Received response: $response');

      if (response.startsWith("ACCPT")) {
        pushMessageToScreen(
          type: 'received',
          message: response,
          status: 'success',
        );
        print('✅ ACCPT received - connection established!');
      } else {
        throw Exception("Unexpected response to START: $response");
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'START message failed: $e',
        status: 'error',
      );
      print('❌ START handshake failed: $e');
      rethrow;
    }
  }

  /// Send a message with 2-byte length prefix
  /// Format: [2-byte length][message]
  Future<void> sendMessage(String message) async {
    if (_socket == null || !_isConnected) {
      throw Exception("Not connected to server");
    }

    try {
      final timestamp = DateTime.now().toIso8601String().split('.')[0].split('T')[1];
      
      final messageBytes = utf8.encode(message);
      final lengthPrefix = ByteData(2);
      lengthPrefix.setUint16(0, messageBytes.length, Endian.big);

      _socket!.add(lengthPrefix.buffer.asUint8List());
      _socket!.add(messageBytes);
      await _socket!.flush();

      // Extract protocol preview for cleaner logging
      final preview = message.length > 50 ? '${message.substring(0, 50)}...' : message;
      
      print('$timestamp - Client - INFO - [SEND] $preview');

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'success',
      );
    } catch (e) {
      final timestamp = DateTime.now().toIso8601String().split('.')[0].split('T')[1];
      print('$timestamp - Client - ERROR - [SEND FAILED] $e');
      
      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'error',
      );
      rethrow;
    }
  }

  /// Receive a message with 2-byte length prefix
  /// Returns: Decoded message string
  Future<String> receiveMessage() async {
    if (_socket == null || !_isConnected) {
      throw Exception("Not connected to server");
    }

    try {
      final timestamp = DateTime.now().toIso8601String().split('.')[0].split('T')[1];
      
      // Read 2-byte length header
      final lengthBytes = await _readExact(2);
      if (lengthBytes.isEmpty) {
        throw Exception("Connection closed by server");
      }

      final byteData = ByteData.view(lengthBytes.buffer);
      final messageLength = byteData.getUint16(0, Endian.big);

      // Read message
      final messageBytes = await _readExact(messageLength);
      if (messageBytes.isEmpty) {
        throw Exception("Connection closed while receiving message");
      }

      final message = utf8.decode(messageBytes);
      
      // Extract protocol command and log
      final preview = message.length > 50 ? '${message.substring(0, 50)}...' : message;
      print('$timestamp - Client - INFO - [RECV] $preview');

      pushMessageToScreen(
        type: 'received',
        message: message,
        status: 'success',
      );

      return message;
    } catch (e) {
      final timestamp = DateTime.now().toIso8601String().split('.')[0].split('T')[1];
      print('$timestamp - Client - ERROR - [RECV FAILED] $e');
      
      pushMessageToScreen(
        type: 'system',
        message: 'Error receiving message: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Start persistent socket listener that buffers all incoming data
  void _startSocketListener() {
    if (_socket == null) return;

    // Cancel any existing subscription
    _socketSubscription?.cancel();

    // Start listening to socket and buffer all data
    _socketSubscription = _socket!.listen(
      (data) {
        // Add incoming data to buffer
        _receiveBuffer.addAll(data);
      },
      onError: (error) {
        _logger.severe("Socket error: $error");
        _isConnected = false;
        notifyListeners();
      },
      onDone: () {
        _logger.info("Socket closed by server");
        _isConnected = false;
        notifyListeners();
      },
    );
  }

  /// Validate signup fields - returns error message or null if valid
  String? _validateSignupFields(String username, String password) {
    // Check for empty fields
    if (username.isEmpty) return "Username cannot be empty";
    if (password.isEmpty) return "Password cannot be empty";

    // Check for pipe characters
    if (username.contains('|')) return "Username cannot contain '|'";
    if (password.contains('|')) return "Password cannot contain '|'";

    // Check for leading/trailing spaces
    if (username != username.trim()) return "Username cannot have leading/trailing spaces";
    if (password != password.trim()) return "Password cannot have leading/trailing spaces";

    // Username validation: alphanumeric + underscore
    if (!RegExp(r'^[a-zA-Z0-9_]{3,20}$').hasMatch(username)) {
      return "Username: 3-20 chars, alphanumeric + underscore only";
    }

    // Password validation: min 6 chars
    if (password.length < 6) {
      return "Password must be at least 6 characters";
    }

    return null; // All valid
  }

  /// Read exact number of bytes from buffered socket data
  Future<Uint8List> _readExact(int numBytes) async {
    if (_socket == null) {
      throw Exception("Socket not connected");
    }

    // Wait until we have enough bytes in buffer
    while (_receiveBuffer.length < numBytes) {
      if (!_isConnected) {
        throw Exception("Connection closed by server");
      }
      // Small delay to avoid busy waiting
      await Future.delayed(const Duration(milliseconds: 10));
    }

    // Extract bytes from buffer
    final bytes = Uint8List.fromList(_receiveBuffer.sublist(0, numBytes));
    _receiveBuffer.removeRange(0, numBytes);

    return bytes;
  }

  // ====== AUTHENTICATION METHODS ======

  /// Protocol Message: LOGIN (Email-based authentication)
  /// Send: LOGIN|email|password
  /// Receive: OK|username|email or ERR|error_message
  Future<String?> login(String username, String password) async {
    try {
      // Validate username format
      if (username.isEmpty || username.contains('|') || username.contains(' ')) {
        throw Exception("Invalid username format");
      }
      if (password.isEmpty || password.contains('|')) {
        throw Exception("Invalid password format");
      }

      final message = "LOGIN|$username|$password";

      pushMessageToScreen(
        type: 'sent',
        message: "LOGIN|$username|***",
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code = parts[0];

      if (code == "OK" && parts.length >= 2) {
        final returnedUsername = parts[1];
        
        _isAuthenticated = true;
        notifyListeners();
        pushMessageToScreen(
          type: 'received',
          message: "Login successful as $returnedUsername",
          status: 'success',
        );
        return returnedUsername;
      } else if (code == "ERR") {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Login failed: $errorMsg",
          status: 'error',
        );
        return null;
      }
      return null;
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Login error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Protocol Message: SIGNUP (User Registration with field validation)
  /// Send: SIGNUP|username|password
  /// Receive: OK|username or ERR|error_message
  /// 
  /// Field validation rules:
  /// - No '|' or leading/trailing spaces
  /// - Username: alphanumeric (can contain underscore), 3-20 chars
  /// - Password: min 6 chars
  Future<String> signUp({
    required String username,
    required String password,
  }) async {
    try {
      // Client-side field validation
      final validation = _validateSignupFields(username, password);
      if (validation != null) {
        pushMessageToScreen(
          type: 'system',
          message: validation,
          status: 'error',
        );
        throw Exception(validation);
      }

      final message = "SIGNUP|$username|$password";

      pushMessageToScreen(
        type: 'sent',
        message: "SIGNUP|$username|***",
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code = parts[0];

      if (code == "OK") {
        final returnedUsername = parts.length > 1 ? parts[1] : username;
        pushMessageToScreen(
          type: 'received',
          message: "Signup successful! Welcome $returnedUsername",
          status: 'success',
        );
        return "success";
      } else if (code == "ERR") {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Signup failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
      return "unknown";
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Signup error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Close connection to server
  Future<void> close() async {
    try {
      await _socket?.close();
      _isConnected = false;
      _isAuthenticated = false;
      notifyListeners();

      pushMessageToScreen(
        type: 'system',
        message: 'Connection closed',
        status: 'success',
      );
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error closing connection: $e',
        status: 'error',
      );
    }
  }

  /// Lazy load marketplace items with pagination
  /// Send: GET_ITEMS_PAGINATED|limit|last_timestamp (optional)
  /// Receive: OK|items_json or ERR|error_message
  Future<List<dynamic>> getMarketplaceItemsPaginated({
    int limit = 10,
    String? lastTimestamp,
  }) async {
    try {
      final message = lastTimestamp != null
          ? "GET_ITEMS_PAGINATED|$limit|$lastTimestamp"
          : "GET_ITEMS_PAGINATED|$limit";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK" && parts.length > 1) {
        final itemsJson = jsonDecode(parts[1]) as List;
        pushMessageToScreen(
          type: 'received',
          message: "Loaded ${itemsJson.length} items",
          status: 'success',
        );
        return itemsJson;
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Failed to load items: $errorMsg",
          status: 'error',
        );
        return [];
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error loading items: $e',
        status: 'error',
      );
      return [];
    }
  }

  /// Send email verification code
  /// Send: SEND_CODE|email
  /// Receive: OK or ERR|error_message
  Future<String> sendVerificationCode(String email) async {
    try {
      final message = "SEND_CODE|$email";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Verification code sent to $email",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Failed to send code: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error sending code: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Verify email with code
  /// Send: VERIFY_CODE|email|code
  /// Receive: OK or ERR|error_message
  Future<String> verifyEmailCode(String email, String code) async {
    try {
      final message = "VERIFY_CODE|$email|$code";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Email verified successfully",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Verification failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error verifying code: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Upload marketplace item
  /// Send: UPLOAD|asset_name|username|google_drive_url|file_type|cost
  /// Receive: OK or ERR|error_message
  Future<String> uploadMarketplaceItem({
    required String assetName,
    required String username,
    required String googleDriveUrl,
    required String fileType,
    required double cost,
  }) async {
    try {
      final message =
          "UPLOAD|$assetName|$username|$googleDriveUrl|$fileType|$cost";

      pushMessageToScreen(
        type: 'sent',
        message: "UPLOAD|$assetName|$username|...|$fileType|$cost",
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Item uploaded successfully",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Upload failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error uploading item: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Request password reset code via email
  /// Send: SEND_CODE|email
  /// Receive: OK or ERR|error_message
  Future<String> requestPasswordReset(String email) async {
    try {
      final message = "SEND_CODE|$email";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Reset code sent to $email",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Reset failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error requesting reset: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Verify password reset code
  /// Send: VERIFY_CODE|email|code
  /// Receive: OK or ERR|error_message
  Future<String> verifyPasswordResetCode(String email, String code) async {
    try {
      final message = "VERIFY_CODE|$email|$code";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Code verified",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Verification failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error verifying code: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Update password after OTP verification
  /// Send: UPDATE_PASSWORD|email|new_password
  /// Receive: OK or ERR|error_message
  Future<String> updatePassword(String email, String newPassword) async {
    try {
      if (email.isEmpty || newPassword.isEmpty) {
        throw Exception("Email and password cannot be empty");
      }
      if (email.contains('|') || newPassword.contains('|')) {
        throw Exception("Fields cannot contain '|'");
      }

      final message = "UPDATE_PASSWORD|$email|$newPassword";

      pushMessageToScreen(
        type: 'sent',
        message: "UPDATE_PASSWORD|$email|***",
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Password updated successfully",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Password update failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error updating password: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Buy marketplace asset
  /// Send: BUY|asset_id|username|amount
  /// Receive: OK|transaction_id or ERR|error_message
  Future<String> buyAsset({
    required String assetId,
    required String username,
    required double amount,
  }) async {
    try {
      final message = "BUY|$assetId|$username|$amount";

      pushMessageToScreen(
        type: 'sent',
        message: "BUY|$assetId|$username|$amount",
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        final transactionId = parts.length > 1 ? parts[1] : "unknown";
        pushMessageToScreen(
          type: 'received',
          message: "Asset purchased: $transactionId",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Purchase failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error purchasing asset: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Send purchased asset to another user
  /// Send: SEND|asset_id|sender_username|receiver_username
  /// Receive: OK|transaction_id or ERR|error_message
  Future<String> sendAssetToUser({
    required String assetId,
    required String senderUsername,
    required String receiverUsername,
  }) async {
    try {
      final message = "SEND|$assetId|$senderUsername|$receiverUsername";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        final transactionId = parts.length > 1 ? parts[1] : "unknown";
        pushMessageToScreen(
          type: 'received',
          message: "Asset sent to $receiverUsername: $transactionId",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Failed to send asset: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error sending asset: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Get user profile (anonymous - username only)
  /// Send: GET_PROFILE|username
  /// Receive: OK|username|email|created_at or ERR|error_message
  Future<Map<String, String>?> getUserProfile(String username) async {
    try {
      if (username.isEmpty || username.contains('|')) {
        throw Exception("Invalid username");
      }

      final message = "GET_PROFILE|$username";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK" && parts.length >= 4) {
        return {
          'username': parts[1],
          'email': parts[2],
          'created_at': parts[3],
        };
      } else {
        throw Exception(parts.length > 1 ? parts[1] : "User not found");
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error getting user profile: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Disconnect from server and clean up resources
  void disconnect() {
    _socketSubscription?.cancel();
    _socket?.close();
    _socket = null;
    _isConnected = false;
    _isAuthenticated = false;
    notifyListeners();

    pushMessageToScreen(
      type: 'system',
      message: 'Disconnected from server',
      status: 'success',
    );
  }

  @override
  void dispose() {
    disconnect();
    super.dispose();
  }
}
