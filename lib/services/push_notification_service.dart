import 'dart:io';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../client_class.dart';
import '../utils/app_logger.dart';
import 'notification_service.dart';

const _fcmTokenKey = 'fcm_token';

Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
}

class PushNotificationService {
  static bool _initialized = false;
  static String? _cachedToken;
  static final AppLogger _log = AppLogger.get('push_notification_service.dart');

  static Future<void> init() async {
    if (_initialized) return;
    try {
      await Firebase.initializeApp();
      await NotificationService.init();
      await FirebaseMessaging.instance.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );

      FirebaseMessaging.onMessage.listen((RemoteMessage message) {
        final title = message.notification?.title ??
            message.data['title']?.toString() ??
            'Aurex';
        final body = message.notification?.body ??
            message.data['body']?.toString() ??
            '';
        if (body.isNotEmpty) {
          NotificationService.show(title: title, body: body);
        }
      });

      FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
        _log.info('Push notification opened: ${message.messageId}');
      });

      _cachedToken = await FirebaseMessaging.instance.getToken();
      if (_cachedToken != null) {
        await _saveToken(_cachedToken!);
      }

      FirebaseMessaging.instance.onTokenRefresh.listen((token) async {
        _cachedToken = token;
        await _saveToken(token);
      });

      _initialized = true;
    } catch (e) {
      _log.error('Push init failed: $e');
    }
  }

  static Future<String?> getToken() async {
    if (_cachedToken != null) return _cachedToken;
    final prefs = await SharedPreferences.getInstance();
    _cachedToken = prefs.getString(_fcmTokenKey);
    return _cachedToken;
  }

  static Future<void> _saveToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_fcmTokenKey, token);
  }

  static String _platformLabel() {
    if (Platform.isAndroid) return 'android';
    if (Platform.isIOS) return 'ios';
    return 'unknown';
  }

  static Future<bool> registerTokenForUser({
    required Client client,
    required String username,
  }) async {
    try {
      final token = await getToken();
      if (token == null || token.isEmpty) {
        return false;
      }
      final platform = _platformLabel();
      final message = "REGISTER_DEVICE|$username|$platform|$token";
      await client.sendMessage(
        message,
        logPreview: "REGISTER_DEVICE|$username|$platform|<token>",
      );
      final response = await client.receiveMessage();
      return response.startsWith('OK');
    } catch (e) {
      _log.error('Failed to register token: $e');
      return false;
    }
  }
}
