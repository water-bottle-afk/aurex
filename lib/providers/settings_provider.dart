import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class SettingsProvider extends ChangeNotifier {
  String _consensus = 'POA'; // Default to Proof of Authority

  String get consensus => _consensus;

  SettingsProvider() {
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      _consensus = prefs.getString('consensus') ?? 'POA';
      notifyListeners();
    } catch (e) {
      print('[SettingsProvider] Error loading settings: $e');
    }
  }

  Future<void> setConsensus(String value) async {
    try {
      if (value != 'POA' && value != 'POW') {
        print('[SettingsProvider] Invalid consensus value: $value');
        return;
      }

      _consensus = value;
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('consensus', value);
      notifyListeners();
      print('[SettingsProvider] Consensus set to: $value');
    } catch (e) {
      print('[SettingsProvider] Error setting consensus: $e');
    }
  }
}
