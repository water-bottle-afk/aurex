import 'package:firebase_auth/firebase_auth.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../providers/client_provider.dart';
import '../providers/assets_provider.dart';
import '../providers/user_provider.dart';

class MarketplacePage extends StatefulWidget {
  const MarketplacePage({super.key});

  @override
  State<MarketplacePage> createState() => _MarketplacePageState();
}

class _MarketplacePageState extends State<MarketplacePage> {
  final GoogleSignIn _googleSignIn = GoogleSignIn();
  late ScrollController _scrollController;

  @override
  void initState() {
    super.initState();
    _scrollController = ScrollController();
    _scrollController.addListener(_onScroll);

    // Load initial assets on page load
    Future.microtask(() {
      final assetsProvider = Provider.of<AssetsProvider>(context, listen: false);
      if (assetsProvider.assets.isEmpty) {
        assetsProvider.loadNextPage();
      }
    });
  }

  @override
  void dispose() {
    _scrollController.removeListener(_onScroll);
    _scrollController.dispose();
    super.dispose();
  }

  /// Detect when user scrolls near the bottom and load more assets
  void _onScroll() {
    if (_scrollController.position.pixels >=
        _scrollController.position.maxScrollExtent - 500) {
      final assetsProvider = Provider.of<AssetsProvider>(context, listen: false);
      if (assetsProvider.hasMoreAssets && !assetsProvider.isLoading) {
        assetsProvider.loadNextPage();
      }
    }
  }

  Future<void> _handleLogout(BuildContext context) async {
    try {
      // Disconnect from TLS server
      final clientProvider = Provider.of<ClientProvider>(context, listen: false);
      await clientProvider.disconnect();
      
      // Sign out from Firebase
      await FirebaseAuth.instance.signOut();
      
      // Sign out from Google (clears cached account)
      await _googleSignIn.signOut();
      
      // Clear user provider
      if (context.mounted) {
        Provider.of<UserProvider>(context, listen: false).setUser(null);
      }
      
      // Clear navigation stack and go to login
      if (context.mounted) {
        context.go('/login');
      }
    } catch (e) {
      print('Error during logout: $e');
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error logging out: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Marketplace'),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () {
          context.go('/upload-asset');
        },
        backgroundColor: Colors.blue.shade600,
        child: const Icon(Icons.add),
      ),
      drawer: Drawer(
        child: ListView(
          padding: EdgeInsets.zero,
          children: [
            DrawerHeader(
              decoration: BoxDecoration(
                color: Colors.blue.shade600,
              ),
              child: const Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    'Aurex',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 28,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  SizedBox(height: 8),
                  Text(
                    'Marketplace App',
                    style: TextStyle(
                      color: Colors.white70,
                      fontSize: 14,
                    ),
                  ),
                ],
              ),
            ),
            ListTile(
              leading: const Icon(Icons.shopping_bag),
              title: const Text('Marketplace'),
              onTap: () {
                Navigator.pop(context);
              },
            ),
            ListTile(
              leading: const Icon(Icons.info),
              title: const Text('About'),
              onTap: () {
                Navigator.pop(context);
                context.go('/about');
              },
            ),
            ListTile(
              leading: const Icon(Icons.person),
              title: const Text('Profile'),
              onTap: () {
                Navigator.pop(context);
              },
            ),
            ListTile(
              leading: const Icon(Icons.settings),
              title: const Text('Settings'),
              onTap: () {
                Navigator.pop(context);
                context.go('/settings');
              },
            ),
            const Divider(),
            ListTile(
              leading: const Icon(Icons.logout),
              title: const Text('Logout'),
              onTap: () {
                Navigator.pop(context);
                _handleLogout(context);
              },
            ),
          ],
        ),
      ),
      body: Consumer<AssetsProvider>(
        builder: (context, assetsProvider, child) {
          // Error state
          if (assetsProvider.error != null && assetsProvider.assets.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.error_outline, size: 64, color: Colors.red),
                  const SizedBox(height: 16),
                  Text(
                    assetsProvider.error!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 16),
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton(
                    onPressed: () => assetsProvider.refreshAssets(),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            );
          }

          // Empty state
          if (assetsProvider.assets.isEmpty && !assetsProvider.isLoading) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.inbox, size: 64, color: Colors.grey),
                  const SizedBox(height: 16),
                  const Text(
                    'No assets available',
                    style: TextStyle(fontSize: 18, color: Colors.grey),
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton.icon(
                    onPressed: () => assetsProvider.refreshAssets(),
                    icon: const Icon(Icons.refresh),
                    label: const Text('Refresh'),
                  ),
                ],
              ),
            );
          }

          return GridView.builder(
            controller: _scrollController,
            padding: const EdgeInsets.all(10.0),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 2,
              crossAxisSpacing: 10.0,
              mainAxisSpacing: 10.0,
              childAspectRatio: 0.8,
            ),
            itemCount: assetsProvider.assets.length +
                (assetsProvider.isLoading ? 1 : 0),
            itemBuilder: (context, index) {
              // Loading indicator at the end
              if (index >= assetsProvider.assets.length) {
                return const Center(
                  child: CircularProgressIndicator(),
                );
              }

              final item = assetsProvider.assets[index];
              return GestureDetector(
                onTap: () =>
                    context.go('/marketplace/item/${item.id}', extra: item),
                child: Card(
                  clipBehavior: Clip.antiAlias,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Image.asset(
                          item.imageUrl,
                          fit: BoxFit.cover,
                          width: double.infinity,
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.all(8.0),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              item.title,
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '\$${item.price.toStringAsFixed(2)}',
                              style: TextStyle(
                                color: Theme.of(context).colorScheme.primary,
                              ),
                            ),
                            if (item.token != null)
                              Text(
                                'Token: ${item.token!.substring(0, 8)}...',
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: Colors.grey,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                          ],
                        ),
                      ),
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
