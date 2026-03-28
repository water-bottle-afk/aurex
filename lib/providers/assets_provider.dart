import 'dart:async';
import 'dart:io';
import 'package:flutter/foundation.dart';
import '../models/item_offering.dart';
import '../models/server_event.dart';
import 'client_provider.dart';

class AssetsProvider extends ChangeNotifier {
  final ClientProvider clientProvider;

  final List<ItemOffering> _assets = [];
  final Set<String> _pendingPurchases = {};
  bool _isLoading = false;
  bool _hasMoreAssets = true;
  String? _lastTimestamp;
  final int _itemsPerPage = 10;
  String? _error;
  StreamSubscription? _eventSub;

  // --- Image cache & download queue ---
  /// Reactive image cache: relPath → raw JPEG bytes.
  /// [ItemImage] widgets read from this map via context.select.
  final Map<String, Uint8List> imageCache = {};

  final List<String> _downloadQueue = [];
  bool _isProcessingQueue = false;
  bool _disposed = false;

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
        final newItems = <ItemOffering>[];
        for (int i = 0; i < items.length; i++) {
          final raw = items[i];
          if (raw is! Map<String, dynamic>) continue;
          try {
            final asset = ItemOffering.fromJson(raw);
            _assets.add(asset);
            newItems.add(asset);
          } catch (_) {
            continue;
          }

          // Update last timestamp for next page - created_at is the server cursor
          final ts = raw['created_at'] ?? raw['timestamp'];
          if (ts != null) {
            _lastTimestamp = ts.toString();
          }
        }

        notifyListeners();
        _enqueueItems(newItems);

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

  /// Upload an asset file using the binary streaming protocol.
  /// Delegates entirely to [client.uploadMarketplaceItemBinary]; returns "success" or throws.
  Future<String> streamUpload({
    required File file,
    required String assetName,
    required String description,
    required String username,
    required String fileType,
    required double cost,
    required String assetHash,
    required String mintTxId,
    required String mintTimestamp,
    required String publicKey,
    required String mintSignature,
  }) async {
    final client = clientProvider.client;
    final result = await client.uploadMarketplaceItemBinary(
      file: file,
      assetName: assetName,
      description: description,
      username: username,
      fileType: fileType,
      cost: cost,
      assetHash: assetHash,
      mintTxId: mintTxId,
      mintTimestamp: mintTimestamp,
      publicKey: publicKey,
      mintSignature: mintSignature,
    );
    if (result == "success") {
      scheduleMicrotask(refreshAssets);
    }
    return result;
  }

  /// Get asset by ID
  ItemOffering? getAssetById(String id) {
    try {
      return _assets.firstWhere((asset) => asset.id == id);
    } catch (e) {
      return null;
    }
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

  // ---------------------------------------------------------------------------
  // Image queue helpers
  // ---------------------------------------------------------------------------

  /// Public entry point: enqueue a single URL for background download.
  /// Safe to call from [ItemImage] for URLs not yet queued by [loadNextPage].
  void enqueueUrl(String url) {
    if (url.isEmpty || imageCache.containsKey(url)) return;
    if (!_downloadQueue.contains(url)) _downloadQueue.add(url);
    if (!_isProcessingQueue) _processQueue();
  }

  void _enqueueItems(List<ItemOffering> items) {
    bool added = false;
    for (final item in items) {
      final url = item.imageUrl;
      if (url.isEmpty || imageCache.containsKey(url)) continue;
      if (!_downloadQueue.contains(url)) {
        _downloadQueue.add(url);
        added = true;
      }
    }
    if (added && !_isProcessingQueue) _processQueue();
  }

  Future<void> _processQueue() async {
    if (_isProcessingQueue || _disposed) return;
    _isProcessingQueue = true;
    final client = clientProvider.client;
    while (_downloadQueue.isNotEmpty && !_disposed) {
      final path = _downloadQueue.removeAt(0);
      if (imageCache.containsKey(path)) continue;
      try {
        final bytes = await client.downloadAsset(path);
        if (_disposed) break;
        // Uint8List(0) acts as a "failed" sentinel so ItemImage shows a
        // broken-image placeholder instead of spinning indefinitely.
        imageCache[path] = (bytes != null && bytes.isNotEmpty) ? bytes : Uint8List(0);
        notifyListeners();
      } catch (_) {
        if (!_disposed) {
          imageCache[path] = Uint8List(0); // sentinel: failed, stop spinner
          notifyListeners();
        }
      }
    }
    _isProcessingQueue = false;
  }

  // ---------------------------------------------------------------------------

  @override
  void dispose() {
    _disposed = true;
    _downloadQueue.clear();
    _eventSub?.cancel();
    super.dispose();
  }
}
