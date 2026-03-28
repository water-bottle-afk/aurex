import 'dart:async';
import 'package:flutter/foundation.dart';
import '../models/item_offering.dart';
import 'client_provider.dart';
import 'user_provider.dart';
import '../models/server_event.dart';
import '../services/google_drive_image_loader.dart';

class MyAssetsProvider extends ChangeNotifier {
  final ClientProvider clientProvider;
  final UserProvider userProvider;

  final List<ItemOffering> _assets = [];
  bool _isLoading = false;
  String? _error;
  String? _lastUsername;
  StreamSubscription<ServerEvent>? _eventSub;

  List<ItemOffering> get assets => List.unmodifiable(_assets);
  bool get isLoading => _isLoading;
  String? get error => _error;

  MyAssetsProvider({
    required this.clientProvider,
    required this.userProvider,
  }) {
    _eventSub = clientProvider.client.serverEvents.listen(_handleServerEvent);
  }

  Future<void> loadAssets({bool force = false}) async {
    final username = userProvider.username;
    if (username == 'Guest' || username.isEmpty) {
      _assets.clear();
      _error = 'Please sign in to view your assets.';
      notifyListeners();
      return;
    }
    if (!force && _lastUsername == username && _assets.isNotEmpty) {
      return;
    }

    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      if (!clientProvider.isConnected) {
        final connected = await clientProvider.initializeConnection();
        if (!connected) {
          _error = 'Server connection failed';
          _isLoading = false;
          notifyListeners();
          return;
        }
      }

      final items = await clientProvider.client.getUserAssets(username);

      _assets
        ..clear()
        ..addAll(items.map((item) {
          final rawUrl = item['url']?.toString() ?? '';
          final imageUrl = rawUrl.isEmpty
              ? ''
              : GoogleDriveImageLoader.convertShareUrl(rawUrl);
          return ItemOffering(
            id: item['id']?.toString() ?? 'unknown_${_assets.length}',
            title: item['asset_name'] ?? 'Asset',
            description: item['description'] ??
                item['file_type'] ??
                'No description provided.',
            imageUrl: imageUrl,
            author: item['username'] ?? 'Unknown',
            price: double.tryParse(item['cost']?.toString() ?? '0') ?? 0.0,
            isListed: (item['is_listed']?.toString() ?? '1') == '1',
            token: item['id']?.toString(),
            assetHash: item['asset_hash']?.toString(),
          );
        }).toList());

      _lastUsername = username;
    } catch (e) {
      _error = 'Failed to load assets: $e';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> refreshAssets() async {
    _assets.clear();
    _lastUsername = null;
    await loadAssets(force: true);
  }

  void _handleServerEvent(ServerEvent event) {
    if (event.event != 'notification') return;
    final payload = event.payload;
    final type = payload['type']?.toString();
    final username = payload['username']?.toString();
    final current = userProvider.localUser?.username;
    if (type == 'purchase_confirmed' ||
        type == 'asset_received' ||
        type == 'asset_sent' ||
        type == 'asset_sold' ||
        type == 'asset_uploaded') {
      if (username != null && username == current) {
        refreshAssets();
      }
      return;
    }
  }

  @override
  void dispose() {
    _eventSub?.cancel();
    super.dispose();
  }
}
