import 'dart:convert';
import 'dart:io';
import 'package:path_provider/path_provider.dart';
import '../models/user_model.dart';

class UserService {
  static final UserService _instance = UserService._internal();

  factory UserService() {
    return _instance;
  }

  UserService._internal();

  Future<Directory> _getDbDirectory() async {
    // Get app documents directory
    final appDir = await getApplicationDocumentsDirectory();
    // Create 'db' folder in root of app documents
    final dbDir = Directory('${appDir.parent.path}/db');
    
    if (!await dbDir.exists()) {
      await dbDir.create(recursive: true);
    }
    
    return dbDir;
  }

  Future<File> _getUsersFile() async {
    final dbDir = await _getDbDirectory();
    return File('${dbDir.path}/users.json');
  }

  Future<List<UserModel>> _loadUsers() async {
    try {
      final file = await _getUsersFile();
      if (!await file.exists()) {
        return [];
      }
      final contents = await file.readAsString();
      final jsonData = jsonDecode(contents) as List;
      return jsonData.map((user) => UserModel.fromJson(user as Map<String, dynamic>)).toList();
    } catch (e) {
      print('Error loading users: $e');
      return [];
    }
  }

  Future<void> _saveUsers(List<UserModel> users) async {
    try {
      final file = await _getUsersFile();
      final jsonData = users.map((user) => user.toJson()).toList();
      await file.writeAsString(jsonEncode(jsonData));
    } catch (e) {
      print('Error saving users: $e');
    }
  }

  /// Check if user exists by email
  Future<UserModel?> getUserByEmail(String email) async {
    final users = await _loadUsers();
    try {
      return users.firstWhere((user) => user.email.toLowerCase() == email.toLowerCase());
    } catch (e) {
      return null;
    }
  }

  /// Check if user exists by Google ID
  Future<UserModel?> getUserByGoogleId(String googleId) async {
    final users = await _loadUsers();
    try {
      return users.firstWhere((user) => user.googleId == googleId);
    } catch (e) {
      return null;
    }
  }

  /// Verify email/password login
  Future<UserModel?> loginWithEmailPassword(String email, String password) async {
    final user = await getUserByEmail(email);
    if (user != null && user.password == password) {
      return user;
    }
    return null;
  }

  /// Create new user with email/password
  Future<UserModel> createUser({
    required String email,
    required String username,
    required String password,
  }) async {
    final users = await _loadUsers();
    
    // Check if user already exists
    final existingUser = await getUserByEmail(email);
    if (existingUser != null) {
      throw Exception('User with this email already exists');
    }

    final newUser = UserModel(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      email: email,
      username: username,
      password: password,
      createdAt: DateTime.now(),
    );

    users.add(newUser);
    await _saveUsers(users);
    return newUser;
  }

  /// Create or get user from Google sign-in (PASSWORD MANDATORY)
  Future<UserModel> createOrGetGoogleUser({
    required String email,
    required String username,
    required String googleId,
    required String password, // PASSWORD IS NOW MANDATORY
  }) async {
    // Check if user exists by email
    var user = await getUserByEmail(email);
    
    if (user != null) {
      // User exists, update Google ID if not set
      if (user.googleId != googleId) {
        final users = await _loadUsers();
        final index = users.indexWhere((u) => u.email == email);
        if (index != -1) {
          users[index] = UserModel(
            id: user.id,
            email: user.email,
            username: user.username,
            password: user.password,
            googleId: googleId,
            createdAt: user.createdAt,
          );
          await _saveUsers(users);
          user = users[index];
        }
      }
      return user;
    }

    // Create new user
    final newUser = UserModel(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      email: email,
      username: username,
      password: password,
      googleId: googleId,
      createdAt: DateTime.now(),
    );

    final users = await _loadUsers();
    users.add(newUser);
    await _saveUsers(users);
    return newUser;
  }

  /// Update user password
  Future<void> updateUserPassword(String email, String newPassword) async {
    final users = await _loadUsers();
    final index = users.indexWhere((u) => u.email == email);
    
    if (index != -1) {
      final user = users[index];
      users[index] = UserModel(
        id: user.id,
        email: user.email,
        username: user.username,
        password: newPassword,
        googleId: user.googleId,
        createdAt: user.createdAt,
      );
      await _saveUsers(users);
    }
  }

  /// Clear all session data (called on logout)
  Future<void> clearSession() async {
    // Nothing to clear from local DB, but can be extended
    print('Session cleared');
  }
}
