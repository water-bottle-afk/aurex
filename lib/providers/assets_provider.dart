import 'package:flutter/foundation.dart';
import '../models/item_offering.dart';
import 'client_provider.dart';

class AssetsProvider extends ChangeNotifier {
  final ClientProvider clientProvider;
  
  List<ItemOffering> _assets = [];
  bool _isLoading = false;
  bool _hasMoreAssets = true;
  int _currentPage = 0;
  final int _itemsPerPage = 10;
  String? _error;

  List<ItemOffering> get assets => List.unmodifiable(_assets);
  bool get isLoading => _isLoading;
  bool get hasMoreAssets => _hasMoreAssets;
  String? get error => _error;

  AssetsProvider({required this.clientProvider});

  /// Request next page of assets from server
  Future<void> loadNextPage() async {
    if (_isLoading || !_hasMoreAssets) return;

    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final client = clientProvider.client;

      // Request asset list: ASKLST|page|limit
      final tokens = await client.requestAssetList(_currentPage, _itemsPerPage);

      if (tokens.isEmpty) {
        _hasMoreAssets = false;
      } else {
        // Convert tokens to ItemOffering objects
        for (int i = 0; i < tokens.length; i++) {
          final token = tokens[i];
          final assetId = token;
          
          // In production, you would download actual image from URL
          // For now, create a placeholder asset
          final asset = ItemOffering(
            id: assetId,
            title: 'Asset #${_assets.length + 1}',
            description: 'Blockchain-registered asset',
            imageUrl: 'assets/images/leather_jacket.png', // Placeholder
            author: 'Blockchain User',
            price: 99.99,
            token: token,
          );

          _assets.add(asset);
        }

        _currentPage++;

        // Check if we got fewer items than requested = last page
        if (tokens.length < _itemsPerPage) {
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
    _currentPage = 0;
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
