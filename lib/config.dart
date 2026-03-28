/// Aurex Client Configuration
/// Update these settings to match your server configuration
class ClientConfig {
  // Server Connection
  static const String defaultServerHost =
      String.fromEnvironment('AUREX_SERVER_HOST', defaultValue: '127.0.0.1');
  static const int defaultServerPort =
      int.fromEnvironment('AUREX_SERVER_PORT', defaultValue: 23456);
  
  // Broadcast Discovery
  static const int broadcastPort = 12345;
  static const Duration broadcastTimeout = Duration(seconds: 5);
  
  // Connection Timeouts
  static const Duration connectionTimeout = Duration(seconds: 10);
  static const Duration messageTimeout = Duration(seconds: 10);
  
  // Logging
  static const bool enableLogging = true;
}
