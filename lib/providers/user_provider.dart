import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../utils/app_logger.dart';

class UserModel {
  final String username;
  final String email;

  UserModel({
    required this.username,
    required this.email,
  });
}

class UserProvider with ChangeNotifier {
  UserModel? _localUser;
  late SharedPreferences _prefs;
  bool _isInitialized = false;
  final AppLogger _log = AppLogger.get('user_provider.dart');

  UserModel? get localUser => _localUser;
  bool get isInitialized => _isInitialized;
  String get username => _localUser?.username ?? 'Guest';
  String get email => _localUser?.email ?? '';

  /// Initialize SharedPreferences and load saved user data
  Future<void> initialize() async {
    if (_isInitialized) return;

    try {
      _prefs = await SharedPreferences.getInstance();

      final savedUsername = _prefs.getString('username');
      final savedEmail = _prefs.getString('email');

      if (savedUsername != null && savedEmail != null) {
        _localUser = UserModel(username: savedUsername, email: savedEmail);
      }

      _isInitialized = true;
      notifyListeners();
    } catch (e) {
      _log.error('Error initializing SharedPreferences: $e');
      _isInitialized = true;
      notifyListeners();
    }
  }

  void setLocalUser({required String username, required String email}) {
    _localUser = UserModel(username: username, email: email);
    _saveUserDataLocally(username, email);
    notifyListeners();
  }

  /// Save user data to local storage
  Future<void> _saveUserDataLocally(String username, String email) async {
    try {
      if (!_isInitialized) {
        await initialize();
      }
      await _prefs.setString('username', username);
      await _prefs.setString('email', email);
      _log.success('User data saved locally: $username');
    } catch (e) {
      _log.error('Error saving user data: $e');
    }
  }

  /// Update user details and save locally
  Future<void> updateUserDetails({
    required String username,
    required String email,
  }) async {
    _localUser = UserModel(username: username, email: email);
    await _saveUserDataLocally(username, email);
    notifyListeners();
  }

  /// Clear user data (for logout)
  Future<void> clearUserData() async {
    try {
      if (!_isInitialized) {
        await initialize();
      }
      await _prefs.remove('username');
      await _prefs.remove('email');
      _localUser = null;
      notifyListeners();
      _log.success('User data cleared');
    } catch (e) {
      _log.error('Error clearing user data: $e');
    }
  }
}
