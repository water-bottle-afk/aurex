import 'dart:io';
import 'dart:convert';
import 'dart:typed_data';
import 'package:logging/logging.dart';
import 'package:flutter/foundation.dart';

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
  final String host;
  final int port;
  final Logger _logger = Logger('Client');
  bool _isConnected = false;
  bool _isAuthenticated = false;

  // Message tracking for debugging
  final List<MessageEvent> _messageHistory = [];
  Function(MessageEvent)? onMessageEvent;

  bool get isConnected => _isConnected;
  bool get isAuthenticated => _isAuthenticated;
  List<MessageEvent> get messageHistory => List.unmodifiable(_messageHistory);

  Client({this.host = "172.16.64.109", this.port = 23456});

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

  /// Connect to server via TLS with START/ACCPT handshake
  Future<void> connect() async {
    try {
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
        const Duration(seconds: 3),
        onTimeout: () {
          throw Exception('Connection timeout after 3 seconds');
        },
      );

      _isConnected = true;
      notifyListeners();

      pushMessageToScreen(
        type: 'system',
        message: 'TLS Connected to server',
        status: 'success',
      );

      // Send START message for connection initialization
      await _sendStartMessage();
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

      // Wait for ACCPT response
      final response = await receiveMessage();

      if (response.startsWith("ACCPT")) {
        pushMessageToScreen(
          type: 'received',
          message: response,
          status: 'success',
        );
      } else {
        throw Exception("Unexpected response to START: $response");
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'START message failed: $e',
        status: 'error',
      );
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
      final messageBytes = utf8.encode(message);
      final lengthPrefix = ByteData(2);
      lengthPrefix.setUint16(0, messageBytes.length, Endian.big);

      _socket!.add(lengthPrefix.buffer.asUint8List());
      _socket!.add(messageBytes);
      await _socket!.flush();

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'success',
      );
    } catch (e) {
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

      pushMessageToScreen(
        type: 'received',
        message: message,
        status: 'success',
      );

      return message;
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error receiving message: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Read exact number of bytes from socket
  Future<Uint8List> _readExact(int numBytes) async {
    final buffer = BytesBuilder();
    int remaining = numBytes;

    try {
      await for (final data in _socket!) {
        buffer.add(data);
        remaining -= data.length;
        if (remaining <= 0) break;
      }
    } catch (e) {
      _logger.severe("Error in _readExact: $e");
      return Uint8List(0);
    }

    return buffer.toBytes();
  }

  // ====== AUTHENTICATION METHODS ======

  /// Protocol Message 6: LOGIN
  /// Send: LOGIN|username|password
  /// Receive: LOGED|success_message or ERR01|error_message
  Future<String> login(String username, String password) async {
    try {
      final message = "LOGIN|$username|$password";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code = parts[0];

      if (code == "LOGED") {
        _isAuthenticated = true;
        notifyListeners();
        return "success";
      } else if (code.startsWith("ERR")) {
        return "error";
      }
      return "unknown";
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Login error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Protocol Message 5: SGNUP
  /// Send: SGNUP|username|password|verify_password|email
  /// Receive: SIGND|success_message or ERR10|error_message
  Future<String> signUp(
    String username,
    String password,
    String verifyPassword,
    String email,
  ) async {
    try {
      final message = "SGNUP|$username|$password|$verifyPassword|$email";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code = parts[0];

      if (code == "SIGND") {
        return "success";
      } else if (code.startsWith("ERR")) {
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

  /// Protocol Message 9: SCODE
  /// Send: SCODE|email
  /// Receive: SENTM|success_message or ERR04|error_message
  Future<String> sendVerificationCode(String email) async {
    try {
      final message = "SCODE|$email";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code = parts[0];

      if (code == "SENTM") {
        return "success";
      } else if (code.startsWith("ERR")) {
        return "error";
      }
      return "unknown";
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Send message error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Protocol Message 10: VRFYC
  /// Send: VRFYC|email|code
  /// Receive: VRFYD|success_message or ERR08|error_message
  Future<String> verifyCode(String email, String code) async {
    try {
      final message = "VRFYC|$email|$code";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code2 = parts[0];

      if (code2 == "VRFYD") {
        return "success";
      } else if (code2.startsWith("ERR")) {
        return "error";
      }
      return "unknown";
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Receive message error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Protocol Message 11: UPDTE
  /// Send: UPDTE|email|new_password|confirm_password
  /// Receive: UPDTD|success_message or ERR07|error_message
  Future<String> updatePassword(
    String email,
    String newPassword,
    String confirmPassword,
  ) async {
    try {
      final message = "UPDTE|$email|$newPassword|$confirmPassword";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code = parts[0];

      if (code == "UPDTD") {
        return "success";
      } else if (code.startsWith("ERR")) {
        return "error";
      }
      return "unknown";
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Update password error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Protocol Message 7: LGOUT
  /// Send: LGOUT|empty
  /// Receive: EXTLG|success_message
  Future<String> logout() async {
    try {
      const message = "LGOUT|";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      if (response.startsWith("EXTLG")) {
        _isAuthenticated = false;
        notifyListeners();
        return "success";
      }
      return "error";
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Logout error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Protocol Message 12: LGAST
  /// Send: LGAST|asset_id|asset_name
  /// Receive: SAVED|success_message or ERR##|error_message
  Future<String> logAsset(String assetId, String assetName) async {
    try {
      final message = "LGAST|$assetId|$assetName";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code = parts[0];

      if (code == "SAVED") {
        return "success";
      } else if (code.startsWith("ERR")) {
        return "error";
      }
      return "unknown";
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Asset logging error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Protocol Message 13: ASKLST
  /// Send: ASKLST|page|limit (page starts at 0, limit items per page)
  /// Receive: ASLIST|token1,token2,token3|total_count or ERR##|error_message
  Future<List<String>> requestAssetList(int page, int limit) async {
    try {
      final message = "ASKLST|$page|$limit";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code = parts[0];

      if (code == "ASLIST") {
        // Parse: ASLIST|token1,token2,token3|total_count
        if (parts.length >= 2) {
          final tokens = parts[1].split(',').where((t) => t.isNotEmpty).toList();
          return tokens;
        }
        return [];
      } else if (code.startsWith("ERR")) {
        throw Exception("Server error: ${parts.length > 1 ? parts[1] : 'Unknown error'}");
      }
      return [];
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Asset list request error: $e',
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
}
