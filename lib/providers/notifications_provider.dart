import 'dart:async';
import 'package:flutter/foundation.dart';
import '../client_class.dart';
import '../models/notification_item.dart';
import '../services/notification_service.dart';
import '../utils/app_logger.dart';
import 'client_provider.dart';
import 'user_provider.dart';

class NotificationsProvider extends ChangeNotifier {
  final ClientProvider clientProvider;
  final UserProvider userProvider;
  final AppLogger _log = AppLogger.get('notifications_provider.dart');

  final List<NotificationItem> _items = [];
  bool _isLoading = false;
  String? _error;
  int _unreadCount = 0;
  StreamSubscription<ServerEvent>? _eventSub;

  NotificationsProvider({
    required this.clientProvider,
    required this.userProvider,
  }) {
    _eventSub = clientProvider.client.serverEvents.listen(_handleServerEvent);
  }

  List<NotificationItem> get items => List.unmodifiable(_items);
  bool get isLoading => _isLoading;
  String? get error => _error;
  int get unreadCount => _unreadCount;

  Future<void> refresh({int limit = 50}) async {
    final username = userProvider.localUser?.username;
    if (username == null || username.isEmpty) {
      _items.clear();
      _unreadCount = 0;
      notifyListeners();
      return;
    }

    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      if (!clientProvider.isConnected) {
        await clientProvider.initializeConnection();
      }
      final result = await clientProvider.client.getNotifications(
        username: username,
        limit: limit,
      );
      _items
        ..clear()
        ..addAll(result.items.map(NotificationItem.fromMap));
      _unreadCount = result.unreadCount;
    } catch (e) {
      _error = 'Failed to load notifications: $e';
      _log.error('refresh failed: $e');
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> markAllRead() async {
    final username = userProvider.localUser?.username;
    if (username == null || username.isEmpty) return;

    try {
      if (!clientProvider.isConnected) {
        await clientProvider.initializeConnection();
      }
      final ok = await clientProvider.client.markNotificationsRead(username);
      if (ok) {
        _unreadCount = 0;
        for (var i = 0; i < _items.length; i++) {
          _items[i] = _items[i].copyWith(isRead: true);
        }
        notifyListeners();
      }
    } catch (e) {
      _log.error('markAllRead failed: $e');
    }
  }

  void _handleServerEvent(ServerEvent event) {
    if (event.event != 'notification') {
      return;
    }

    final item = NotificationItem.fromMap(event.payload);
    final username = userProvider.localUser?.username;
    if (username == null || username.isEmpty) {
      return;
    }
    if (item.username != username) {
      return;
    }

    _items.insert(0, item);
    if (!item.isRead) {
      _unreadCount += 1;
    }
    notifyListeners();

    NotificationService.show(title: item.title, body: item.body);
  }

  @override
  void dispose() {
    _eventSub?.cancel();
    super.dispose();
  }
}
