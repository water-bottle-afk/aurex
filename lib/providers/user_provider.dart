import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

class UserModel {
  final String username;
  final String email;

  UserModel({
    required this.username,
    required this.email,
  });
}

class UserProvider with ChangeNotifier {
  User? _firebaseUser;
  UserModel? _localUser;

  User? get user => _firebaseUser;
  UserModel? get localUser => _localUser;

  void setUser(User? user) {
    _firebaseUser = user;
    notifyListeners();
  }

  void setLocalUser({required String username, required String email}) {
    _localUser = UserModel(username: username, email: email);
    notifyListeners();
  }

  void refreshUser() {
    _firebaseUser = FirebaseAuth.instance.currentUser;
    notifyListeners();
  }
}
