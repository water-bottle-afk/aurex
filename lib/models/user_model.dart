class UserModel {
  final String id;
  final String email;
  final String username;
  final String? password;
  final String? googleId;
  final DateTime createdAt;

  UserModel({
    required this.id,
    required this.email,
    required this.username,
    this.password,
    this.googleId,
    required this.createdAt,
  });

  // Convert to JSON
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'email': email,
      'username': username,
      'password': password,
      'googleId': googleId,
      'createdAt': createdAt.toIso8601String(),
    };
  }

  // Create from JSON
  factory UserModel.fromJson(Map<String, dynamic> json) {
    return UserModel(
      id: json['id'] as String,
      email: json['email'] as String,
      username: json['username'] as String,
      password: json['password'] as String?,
      googleId: json['googleId'] as String?,
      createdAt: DateTime.parse(json['createdAt'] as String),
    );
  }
}
