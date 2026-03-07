import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../models/item_offering.dart';
import '../providers/client_provider.dart';
import '../providers/my_assets_provider.dart';
import '../providers/user_provider.dart';
import '../services/google_drive_image_loader.dart';

class MyAssetsPage extends StatefulWidget {
  const MyAssetsPage({super.key});

  @override
  State<MyAssetsPage> createState() => _MyAssetsPageState();
}

class _MyAssetsPageState extends State<MyAssetsPage> {
  final Set<String> _actionInProgress = {};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      context.read<MyAssetsProvider>().loadAssets(force: true);
    });
  }

  Future<bool> _ensureConnection() async {
    final clientProvider = context.read<ClientProvider>();
    if (clientProvider.isConnected) return true;
    final connected = await clientProvider.initializeConnection();
    if (!connected && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Server connection failed')),
      );
    }
    return connected;
  }

  Future<void> _listAssetForSale(ItemOffering item, double price) async {
    if (_actionInProgress.contains(item.id)) return;
    setState(() => _actionInProgress.add(item.id));

    try {
      if (!await _ensureConnection()) return;

      final username = context.read<UserProvider>().username;
      if (username.isEmpty || username == 'Guest') {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please sign in first')),
        );
        return;
      }

      final clientProvider = context.read<ClientProvider>();
      final result = await clientProvider.client.listAssetForSale(
        assetId: item.id,
        username: username,
        price: price,
      );

      if (mounted) {
        final isSuccess = result == 'success';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(isSuccess ? 'Asset listed for sale' : 'Failed to list asset'),
            backgroundColor: isSuccess ? Colors.green[700] : Colors.red[700],
          ),
        );
      }

      await context.read<MyAssetsProvider>().refreshAssets();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error listing asset: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _actionInProgress.remove(item.id));
      }
    }
  }

  Future<void> _unlistAsset(ItemOffering item) async {
    if (_actionInProgress.contains(item.id)) return;
    setState(() => _actionInProgress.add(item.id));

    try {
      if (!await _ensureConnection()) return;

      final username = context.read<UserProvider>().username;
      if (username.isEmpty || username == 'Guest') {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please sign in first')),
        );
        return;
      }

      final clientProvider = context.read<ClientProvider>();
      final result = await clientProvider.client.unlistAsset(
        assetId: item.id,
        username: username,
      );

      if (mounted) {
        final isSuccess = result == 'success';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(isSuccess ? 'Asset unlisted' : 'Failed to unlist asset'),
            backgroundColor: isSuccess ? Colors.green[700] : Colors.red[700],
          ),
        );
      }

      await context.read<MyAssetsProvider>().refreshAssets();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error unlisting asset: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _actionInProgress.remove(item.id));
      }
    }
  }

  Future<void> _promptSell(ItemOffering item) async {
    final controller =
        TextEditingController(text: item.price.toStringAsFixed(2));
    final result = await showDialog<double>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Set Sale Price'),
          content: TextField(
            controller: controller,
            keyboardType:
                const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(
              labelText: 'Price',
              prefixText: '\$',
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: () {
                final text = controller.text.trim();
                final price = double.tryParse(text);
                if (price == null || price <= 0) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Enter a valid price')),
                  );
                  return;
                }
                Navigator.pop(context, price);
              },
              child: const Text('List'),
            ),
          ],
        );
      },
    );

    if (result != null) {
      await _listAssetForSale(item, result);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('My Assets'),
        backgroundColor: Colors.blueGrey[900],
        foregroundColor: Colors.white,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/marketplace');
            }
          },
        ),
      ),
      body: Consumer<MyAssetsProvider>(
        builder: (context, assetsProvider, child) {
          if (assetsProvider.isLoading) {
            return const Center(child: CircularProgressIndicator());
          }

          if (assetsProvider.error != null) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.error_outline, size: 64, color: Colors.red),
                  const SizedBox(height: 12),
                  Text(
                    assetsProvider.error!,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 16),
                  ElevatedButton(
                    onPressed: () => assetsProvider.refreshAssets(),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            );
          }

          if (assetsProvider.assets.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.inbox, size: 64, color: Colors.grey),
                  const SizedBox(height: 12),
                  const Text(
                    'No assets owned yet',
                    style: TextStyle(color: Colors.grey, fontSize: 16),
                  ),
                  const SizedBox(height: 16),
                  ElevatedButton(
                    onPressed: () => context.go('/marketplace'),
                    child: const Text('Browse Marketplace'),
                  ),
                ],
              ),
            );
          }

          return RefreshIndicator(
            onRefresh: () => assetsProvider.refreshAssets(),
            child: GridView.builder(
              padding: const EdgeInsets.all(12),
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 2,
                crossAxisSpacing: 12,
                mainAxisSpacing: 12,
                childAspectRatio: 0.8,
              ),
              itemCount: assetsProvider.assets.length,
              itemBuilder: (context, index) {
                final item = assetsProvider.assets[index];
                return GestureDetector(
                  onTap: () =>
                      context.go('/marketplace/asset/${item.id}', extra: item),
                  child: Card(
                    elevation: 2,
                    clipBehavior: Clip.antiAlias,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Container(
                            color: Colors.grey[200],
                            child: GoogleDriveImageLoader.buildCachedImage(
                              imageUrl: item.imageUrl,
                              fit: BoxFit.cover,
                              width: double.infinity,
                            ),
                          ),
                        ),
                        Padding(
                          padding: const EdgeInsets.all(10),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                item.title,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 13,
                                ),
                              ),
                              const SizedBox(height: 6),
                              Text(
                                '\$${item.price.toStringAsFixed(2)}',
                                style: TextStyle(
                                  color: Colors.green[700],
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              const SizedBox(height: 6),
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Text(
                                    item.isListed ? 'Listed' : 'Not listed',
                                    style: TextStyle(
                                      fontSize: 11,
                                      color: item.isListed
                                          ? Colors.green[700]
                                          : Colors.grey[600],
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  _actionInProgress.contains(item.id)
                                      ? const SizedBox(
                                          width: 16,
                                          height: 16,
                                          child: CircularProgressIndicator(strokeWidth: 2),
                                        )
                                      : TextButton(
                                          onPressed: item.isListed
                                              ? () => _unlistAsset(item)
                                              : () => _promptSell(item),
                                          style: TextButton.styleFrom(
                                            padding: EdgeInsets.zero,
                                            minimumSize: const Size(40, 24),
                                            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                                          ),
                                          child: Text(
                                            item.isListed ? 'Unlist' : 'Sell',
                                            style: TextStyle(
                                              fontSize: 12,
                                              color: item.isListed
                                                  ? Colors.red[600]
                                                  : Colors.blue[700],
                                              fontWeight: FontWeight.w600,
                                            ),
                                          ),
                                        ),
                                ],
                              ),
                            ],
                          ),
                        )
                      ],
                    ),
                  ),
                );
              },
            ),
          );
        },
      ),
    );
  }
}
