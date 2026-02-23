import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../utils/app_logger.dart';

class SettingsProvider extends ChangeNotifier {
  String _consensus = 'POA'; // Default to Proof of Authority
  final AppLogger _log = AppLogger.get('settings_provider.dart');

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
      _log.error('Error loading settings: $e');
    }
  }

  Future<void> setConsensus(String value) async {
    try {
      if (value != 'POA' && value != 'POW') {
        _log.warn('Invalid consensus value: $value');
        return;
      }

      _consensus = value;
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('consensus', value);
      notifyListeners();
      _log.success('Consensus set to: $value');
    } catch (e) {
      _log.error('Error setting consensus: $e');
    }
  }
}
