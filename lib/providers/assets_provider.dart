import 'dart:async';
import 'package:flutter/foundation.dart';
import '../models/item_offering.dart';
import '../models/server_event.dart';
import 'client_provider.dart';
import '../utils/app_logger.dart';
import '../services/google_drive_image_loader.dart';

class AssetsProvider extends ChangeNotifier {
  final ClientProvider clientProvider;
  final AppLogger _log = AppLogger.get('assets_provider.dart');
  
  final List<ItemOffering> _assets = [];
  final Set<String> _pendingPurchases = {};
  bool _isLoading = false;
  bool _hasMoreAssets = true;
  String? _lastTimestamp; // Use timestamp-based pagination
  final int _itemsPerPage = 10;
  String? _error;
  StreamSubscription? _eventSub;

  List<ItemOffering> get assets => List.unmodifiable(_assets);
  bool get isLoading => _isLoading;
  bool get hasMoreAssets => _hasMoreAssets;
  String? get error => _error;
  bool isPurchasePending(String assetId) => _pendingPurchases.contains(assetId);

  AssetsProvider({required this.clientProvider}) {
    // subscribe to asynchronous server events; the stream is broadcast so
    // multiple listeners can listen simultaneously.
    _eventSub = clientProvider.client.serverEvents.listen(_handleServerEvent);
  }

  /// Request next page of assets from server using timestamp-based pagination
  Future<void> loadNextPage() async {
    if (_isLoading || !_hasMoreAssets) return;

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

      final client = clientProvider.client;

      // Request asset list with pagination
      final items = await client.getMarketplaceItemsPaginated(
        limit: _itemsPerPage,
        lastTimestamp: _lastTimestamp,
      );

      if (items.isEmpty) {
        _hasMoreAssets = false;
      } else {
        // Convert items to ItemOffering objects
        for (int i = 0; i < items.length; i++) {
          final item = items[i];
          
          final asset = ItemOffering(
            id: item['id']?.toString() ?? 'unknown_${_assets.length}',
            title: item['asset_name'] ?? 'Asset #${_assets.length + 1}',
            description: item['description'] ??
                item['file_type'] ??
                'No description provided.',
            imageUrl: item['url'] ?? 'assets/images/leather_jacket.png',
            author: item['username'] ?? 'Unknown',
            price: double.tryParse(item['cost']?.toString() ?? '0') ?? 0.0,
            isListed: (item['is_listed']?.toString() ?? '1') == '1',
            token: item['id']?.toString() ?? '',
            assetHash: item['asset_hash']?.toString(),
          );

          _assets.add(asset);
          
          // Update last timestamp for next page - created_at is the server cursor
          final ts = item['created_at'] ?? item['timestamp'];
          if (ts != null) {
            _lastTimestamp = ts.toString();
          }
        }

        notifyListeners();

        // Check if we got fewer items than requested = last page
        if (items.length < _itemsPerPage) {
          _hasMoreAssets = false;
        }
      }

      notifyListeners();
    } catch (e) {
      _error = 'Failed to load assets: $e';
      _isLoading = false;
      notifyListeners();
      rethrow;
    }

    _isLoading = false;
    notifyListeners();
  }

  /// Reset and reload assets from page 0
  Future<void> refreshAssets() async {
    _assets.clear();
    _lastTimestamp = null;
    _hasMoreAssets = true;
    _error = null;
    notifyListeners();

    await loadNextPage();
  }

  void markPurchasePending(String assetId) {
    if (assetId.isEmpty) return;
    _pendingPurchases.add(assetId);
    notifyListeners();
  }

  void clearPurchasePending(String assetId) {
    if (_pendingPurchases.remove(assetId)) {
      notifyListeners();
    }
  }

  void removeAssetById(String assetId) {
    final before = _assets.length;
    _assets.removeWhere((asset) => asset.id == assetId);
    if (_assets.length != before) {
      notifyListeners();
    }
  }

  /// Get asset by ID
  ItemOffering? getAssetById(String id) {
    try {
      return _assets.firstWhere((asset) => asset.id == id);
    } catch (e) {
      return null;
    }
  }

  /// Resolve a Drive share URL or raw file id to a view URL usable by [Image.network].
  Future<String> downloadAssetImage(String urlOrFileId) async {
    final t = urlOrFileId.trim();
    if (t.isEmpty) {
      throw ArgumentError('downloadAssetImage: empty input');
    }
    if (t.startsWith('http')) {
      return GoogleDriveImageLoader.convertShareUrl(t);
    }
    return GoogleDriveImageLoader.convertShareUrl(
      'https://drive.google.com/uc?export=view&id=$t',
    );
  }

  void _handleServerEvent(ServerEvent event) {
    if (event.event == 'marketplace_remove') {
      final assetId = event.payload['asset_id']?.toString();
      if (assetId != null && assetId.isNotEmpty) {
        removeAssetById(assetId);
        clearPurchasePending(assetId);
      }
      return;
    }

    if (event.event == 'notification') {
      final payload = event.payload;
      final type = payload['type']?.toString();
      final assetId = payload['asset_id']?.toString();
      if (assetId != null &&
          assetId.isNotEmpty &&
          (type == 'purchase_failed' || type == 'purchase_confirmed')) {
        clearPurchasePending(assetId);
      }
      if (type == 'purchase_confirmed' ||
          type == 'purchase_failed' ||
          type == 'asset_sold') {
        scheduleMicrotask(() {
          refreshAssets();
        });
      }
    }
  }

  @override
  void dispose() {
    _eventSub?.cancel();
    super.dispose();
  }
}
