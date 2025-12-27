import 'package:flutter/material.dart';
import '../client_class.dart';

class ClientProvider with ChangeNotifier {
  final Client _client = Client();
  bool _isConnecting = false;
  String? _connectionError;

  Client get client => _client;
  bool get isConnecting => _isConnecting;
  String? get connectionError => _connectionError;

  /// Initialize connection to server with retry logic
  Future<bool> initializeConnection() async {
    _isConnecting = true;
    _connectionError = null;
    notifyListeners();

    try {
      // Attempt to connect
      await _client.connect();
      _isConnecting = false;
      notifyListeners();
      return true;
    } catch (e) {
      _connectionError = e.toString();
      _isConnecting = false;
      notifyListeners();
      return false;
    }
  }

  /// Retry connection (called by Try Again button)
  Future<bool> retryConnection() async {
    return await initializeConnection();
  }

  Future<void> disconnect() async {
    try {
      await _client.close();
      notifyListeners();
    } catch (e) {
      print('Error disconnecting: $e');
    }
  }

  @override
  void dispose() {
    _client.close();
    super.dispose();
  }
}
