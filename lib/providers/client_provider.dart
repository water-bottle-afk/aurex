import 'package:flutter/material.dart';
import '../client_class.dart';

class ClientProvider with ChangeNotifier {
  final Client _client = Client();

  Client get client => _client;

  Future<void> initializeConnection() async {
    try {
      await _client.initializeConnection();
      notifyListeners();
    } catch (e) {
      print('Error initializing client connection: $e');
      rethrow;
    }
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
