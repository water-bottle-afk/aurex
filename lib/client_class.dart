import 'dart:io';
import 'dart:convert';
import 'package:logging/logging.dart';
import 'package:flutter/foundation.dart'; // For ChangeNotifier

class Client extends ChangeNotifier {
  SecureSocket? _socket;
  final String host = "10.100.102.50";  // Server IP on local network
  final int port = 23456;
  final Logger _logger = Logger('Client');
  bool _isConnected = false;

  bool get isConnected => _isConnected;

  Future<void> connect() async {
    try {
      print("Attempting to connect...");  // Temporary debug print
      // Create a secure socket connection for TLS, ignoring cert errors for self-signed
      _socket = await SecureSocket.connect(host, port, onBadCertificate: (certificate) => true);
      _isConnected = true;
      notifyListeners();
      _logger.info("Connected to server");
    } catch (e) {
      _logger.severe("Connection failed: $e");
      rethrow;
    }
  }

  Future<void> sendMessage(String message) async {
    if (_socket != null) {
      _socket!.write(message);
      await _socket!.flush();
    }
  }

  Future<String> receiveMessage() async {
    if (_socket != null) {
      final data = await _socket!.first; // Read first chunk
      return utf8.decode(data);
    }
    return "";
  }

  Future<void> close() async {
    await _socket?.close();
    _isConnected = false;
    notifyListeners();
  }

  // New method to initialize connection and send "hello" on app open
  Future<void> initializeConnection() async {
    print("DEBUG: initializeConnection called");
    try {
      await connect();
      await sendMessage("hello");
      _logger.info("Sent 'hello' to server");
      print("DEBUG: 'hello' sent successfully");
    } catch (e) {
      print("DEBUG: initializeConnection failed: $e");
      _logger.severe("initializeConnection failed: $e");
    }
  }

  // Example usage in a loop (can be called from main or provider)
  Future<void> startChat() async {
    await connect();
    while (true) {
      String msg = "test message"; // Replace with input logic
      if (msg.toLowerCase() == "exit") break;
      await sendMessage(msg);
      String response = await receiveMessage();
      _logger.info("Server: $response");
    }
    await close();
  }
}
