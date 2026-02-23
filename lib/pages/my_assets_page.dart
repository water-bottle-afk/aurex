import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../providers/my_assets_provider.dart';
import '../services/google_drive_image_loader.dart';

class MyAssetsPage extends StatefulWidget {
  const MyAssetsPage({super.key});

  @override
  State<MyAssetsPage> createState() => _MyAssetsPageState();
}

class _MyAssetsPageState extends State<MyAssetsPage> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() {
      final provider = Provider.of<MyAssetsProvider>(context, listen: false);
      provider.loadAssets(force: true);
    });
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

          return GridView.builder(
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
                          ],
                        ),
                      )
                    ],
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}
