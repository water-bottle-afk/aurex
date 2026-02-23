import 'package:flutter/material.dart';
import '../services/google_drive_image_loader.dart';
import 'item_details_elegant.dart';
import 'upload_item_page.dart';
import '../utils/app_logger.dart';

/// Model for marketplace item
class MarketplaceItem {
  final int id;
  final String assetName;
  final String username;
  final String url;
  final String fileType;
  final double cost;
  final String timestamp;
  final String createdAt;

  MarketplaceItem({
    required this.id,
    required this.assetName,
    required this.username,
    required this.url,
    required this.fileType,
    required this.cost,
    required this.timestamp,
    required this.createdAt,
  });

  factory MarketplaceItem.fromJson(Map<String, dynamic> json) {
    return MarketplaceItem(
      id: json['id'] ?? 0,
      assetName: json['asset_name'] ?? '',
      username: json['username'] ?? '',
      url: json['url'] ?? '',
      fileType: json['file_type'] ?? 'jpg',
      cost: (json['cost'] ?? 0).toDouble(),
      timestamp: json['timestamp'] ?? '',
      createdAt: json['created_at'] ?? '',
    );
  }
}

/// Enhanced Marketplace Page with scrolling/pagination
class MarketplacePageV2 extends StatefulWidget {
  const MarketplacePageV2({super.key});

  @override
  State<MarketplacePageV2> createState() => _MarketplacePageV2State();
}

class _MarketplacePageV2State extends State<MarketplacePageV2> {
  final AppLogger _log = AppLogger.get('marketplace_page_v2.dart');
  final ScrollController _scrollController = ScrollController();
  List<MarketplaceItem> items = [];
  bool isLoading = true;
  bool hasError = false;
  String errorMessage = '';

  @override
  void initState() {
    super.initState();
    _loadMarketplaceItems();
    _scrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scrollController.removeListener(_onScroll);
    _scrollController.dispose();
    super.dispose();
  }

  /// Load items from server
  void _loadMarketplaceItems() async {
    try {
      setState(() {
        isLoading = true;
        hasError = false;
      });

      // TODO: Replace with actual server call
      // final response = await clientProvider.client.getMarketplaceItems();
      
      // For now, mock data
      await Future.delayed(const Duration(seconds: 1));
      
      // In real implementation, parse response and update items
      setState(() {
        isLoading = false;
      });
    } catch (e) {
      setState(() {
        isLoading = false;
        hasError = true;
        errorMessage = e.toString();
      });
    }
  }

  /// Called when scrolling near bottom - load more items
  void _onScroll() {
    if (_scrollController.position.pixels ==
        _scrollController.position.maxScrollExtent) {
      _log.info('Reached bottom - loading older items...');
      // TODO: Load more items from server
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('🛍️ Marketplace'),
        elevation: 0,
      ),
      body: isLoading
          ? const Center(child: CircularProgressIndicator())
          : hasError
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.error, size: 48, color: Colors.red),
                      const SizedBox(height: 16),
                      Text('Error: $errorMessage'),
                      const SizedBox(height: 16),
                      ElevatedButton(
                        onPressed: _loadMarketplaceItems,
                        child: const Text('Retry'),
                      )
                    ],
                  ),
                )
              : items.isEmpty
                  ? const Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.shopping_bag, size: 48, color: Colors.grey),
                          SizedBox(height: 16),
                          Text('No items yet'),
                        ],
                      ),
                    )
                  : RefreshIndicator(
                      onRefresh: () async {
                        _loadMarketplaceItems();
                        await Future.delayed(const Duration(seconds: 1));
                      },
                      child: GridView.builder(
                        controller: _scrollController,
                        padding: const EdgeInsets.all(12),
                        gridDelegate:
                            const SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: 2,
                          crossAxisSpacing: 12,
                          mainAxisSpacing: 12,
                          childAspectRatio: 0.75,
                        ),
                        itemCount: items.length,
                        itemBuilder: (context, index) {
                          final item = items[index];
                          return _buildItemCard(context, item);
                        },
                      ),
                    ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {
          Navigator.push(
            context,
            MaterialPageRoute(builder: (context) => const UploadItemPage()),
          );
        },
        icon: const Icon(Icons.add),
        label: const Text('Sell'),
        backgroundColor: Colors.green,
      ),
    );
  }

  /// Build individual item card
  Widget _buildItemCard(BuildContext context, MarketplaceItem item) {
    return Card(
      elevation: 4,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Image with overlay buttons
          Expanded(
            child: Stack(
              children: [
                GoogleDriveImageLoader.buildCachedImage(
                  imageUrl: item.url,
                  borderRadius: const BorderRadius.only(
                    topLeft: Radius.circular(12),
                    topRight: Radius.circular(12),
                  ),
                ),
                // Overlay with buttons
                Positioned(
                  top: 8,
                  right: 8,
                  child: Row(
                    children: [
                      // Info button
                      GestureDetector(
                        onTap: () {
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (context) => ItemDetailsPage(item: item),
                            ),
                          );
                        },
                        child: Container(
                          decoration: BoxDecoration(
                            color: Colors.white,
                            shape: BoxShape.circle,
                            boxShadow: [
                              BoxShadow(
                                color: Colors.black.withOpacity(0.3),
                                blurRadius: 8,
                              ),
                            ],
                          ),
                          padding: const EdgeInsets.all(8),
                          child: const Icon(Icons.info, color: Colors.blue, size: 20),
                        ),
                      ),
                      const SizedBox(width: 8),
                      // Buy button
                      GestureDetector(
                        onTap: () {
                          showDialog(
                            context: context,
                            builder: (context) => AlertDialog(
                              title: const Text('Buy Item'),
                              content: Text('Buy "${item.assetName}" for \$${item.cost}?'),
                              actions: [
                                TextButton(
                                  onPressed: () => Navigator.pop(context),
                                  child: const Text('Cancel'),
                                ),
                                TextButton(
                                  onPressed: () {
                                    Navigator.pop(context);
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(
                                        content: Text('Added to cart: ${item.assetName}'),
                                        backgroundColor: Colors.green,
                                      ),
                                    );
                                  },
                                  child: const Text('Buy'),
                                ),
                              ],
                            ),
                          );
                        },
                        child: Container(
                          decoration: BoxDecoration(
                            color: Colors.green,
                            shape: BoxShape.circle,
                            boxShadow: [
                              BoxShadow(
                                color: Colors.black.withOpacity(0.3),
                                blurRadius: 8,
                              ),
                            ],
                          ),
                          padding: const EdgeInsets.all(8),
                          child: const Icon(Icons.shopping_bag, color: Colors.white, size: 20),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          // Item info
          Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.assetName,
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 14,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 4),
                Text(
                  'by ${item.username}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: Colors.grey,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 8),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      '\$${item.cost.toStringAsFixed(2)}',
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                        color: Colors.green,
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: Colors.blue[100],
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        item.fileType.toUpperCase(),
                        style: const TextStyle(fontSize: 10),
                      ),
                    )
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
