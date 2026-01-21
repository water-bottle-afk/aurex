import 'package:flutter/foundation.dart';
import '../models/item_offering.dart';
import 'client_provider.dart';

class AssetsProvider extends ChangeNotifier {
  final ClientProvider clientProvider;
  
  final List<ItemOffering> _assets = [];
  bool _isLoading = false;
  bool _hasMoreAssets = true;
  String? _lastTimestamp; // Use timestamp-based pagination
  final int _itemsPerPage = 10;
  String? _error;

  List<ItemOffering> get assets => List.unmodifiable(_assets);
  bool get isLoading => _isLoading;
  bool get hasMoreAssets => _hasMoreAssets;
  String? get error => _error;

  AssetsProvider({required this.clientProvider});

  /// Request next page of assets from server using timestamp-based pagination
  Future<void> loadNextPage() async {
    if (_isLoading || !_hasMoreAssets) return;

    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
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
            description: item['file_type'] ?? 'Marketplace item',
            imageUrl: item['url'] ?? 'assets/images/leather_jacket.png',
            author: item['username'] ?? 'Unknown',
            price: double.tryParse(item['cost']?.toString() ?? '0') ?? 0.0,
            token: item['id']?.toString() ?? '',
          );

          _assets.add(asset);
          
          // Update last timestamp for next page - convert to string if needed
          if (item['timestamp'] != null) {
            _lastTimestamp = item['timestamp'].toString();
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

  /// Get asset by ID
  ItemOffering? getAssetById(String id) {
    try {
      return _assets.firstWhere((asset) => asset.id == id);
    } catch (e) {
      return null;
    }
  }

  /// Download image for asset (placeholder for now)
  Future<String> downloadAssetImage(String token) async {
    try {
      // In production:
      // 1. Send DNLOD|token to server
      // 2. Server returns image URL or direct image data
      // 3. Cache image locally
      // 4. Return local path

      // For now, return placeholder
      return 'assets/images/leather_jacket.png';
    } catch (e) {
      print('Error downloading asset image: $e');
      rethrow;
    }
  }
}
