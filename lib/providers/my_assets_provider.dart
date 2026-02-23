import 'package:flutter/foundation.dart';
import '../models/item_offering.dart';
import 'client_provider.dart';
import 'user_provider.dart';

class MyAssetsProvider extends ChangeNotifier {
  final ClientProvider clientProvider;
  final UserProvider userProvider;

  final List<ItemOffering> _assets = [];
  bool _isLoading = false;
  String? _error;
  String? _lastUsername;

  List<ItemOffering> get assets => List.unmodifiable(_assets);
  bool get isLoading => _isLoading;
  String? get error => _error;

  MyAssetsProvider({
    required this.clientProvider,
    required this.userProvider,
  });

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
          return ItemOffering(
            id: item['id']?.toString() ?? 'unknown_${_assets.length}',
            title: item['asset_name'] ?? 'Asset',
            description: item['description'] ??
                item['file_type'] ??
                'No description provided.',
            imageUrl: item['url'] ?? '',
            author: item['username'] ?? 'Unknown',
            price: double.tryParse(item['cost']?.toString() ?? '0') ?? 0.0,
            token: item['id']?.toString(),
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
}
