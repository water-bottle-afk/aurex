/// Aurex Client Configuration
/// Update these settings to match your server configuration

library;

class ClientConfig {
  // Server Connection
  static const String defaultServerHost = '10.100.102.58';
  static const int defaultServerPort = 23456;
  
  // Broadcast Discovery
  static const int broadcastPort = 12345;
  static const Duration broadcastTimeout = Duration(seconds: 5);
  
  // Connection Timeouts
  static const Duration connectionTimeout = Duration(seconds: 10);
  static const Duration messageTimeout = Duration(seconds: 10);
  
  // Logging
  static const bool enableLogging = true;
}
