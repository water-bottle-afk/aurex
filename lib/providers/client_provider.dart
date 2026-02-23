import 'package:flutter/material.dart';
import '../client_class.dart';
import '../utils/app_logger.dart';

class ClientProvider with ChangeNotifier {
  final Client _client = Client();
  final AppLogger _log = AppLogger.get('client_provider.dart');
  bool _isConnecting = false;
  String? _connectionError;

  Client get client => _client;
  bool get isConnecting => _isConnecting;
  bool get isConnected => _client.isConnected;
  String? get connectionError => _connectionError;

  /// Initialize connection to server with optional discovery
  Future<bool> connect({bool discoverFirst = true}) async {
    _isConnecting = true;
    _connectionError = null;
    notifyListeners();

    try {
      // Attempt to connect (with or without discovery)
      await _client.connect(discoverFirst: discoverFirst);
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

  /// Initialize connection to server with retry logic
  Future<bool> initializeConnection() async {
    return await connect(discoverFirst: true);
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
      _log.error('Error disconnecting: $e');
    }
  }

  @override
  void dispose() {
    // DO NOT close the client connection here!
    // The connection is persistent and shared across the entire app
    // Only call close() when explicitly disconnecting
    super.dispose();
  }
}
