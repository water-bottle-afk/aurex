import 'package:google_sign_in/google_sign_in.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../providers/client_provider.dart';
import '../providers/assets_provider.dart';
import '../providers/user_provider.dart';
import '../services/google_drive_image_loader.dart';
import '../utils/app_logger.dart';

class MarketplacePage extends StatefulWidget {
  const MarketplacePage({super.key});

  @override
  State<MarketplacePage> createState() => _MarketplacePageState();
}

class _MarketplacePageState extends State<MarketplacePage> {
  final GoogleSignIn _googleSignIn = GoogleSignIn();
  late ScrollController _scrollController;
  double? _walletBalance;
  bool _walletLoading = false;
  String? _walletError;

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

    Future.microtask(_loadWalletBalance);
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
    final log = AppLogger.get('marketplace_page.dart');
    try {
      final clientProvider = Provider.of<ClientProvider>(context, listen: false);
      await clientProvider.disconnect();
      await _googleSignIn.signOut();
      if (context.mounted) {
        final userProvider = Provider.of<UserProvider>(context, listen: false);
        await userProvider.clearUserData();
      }
      if (context.mounted) {
        context.go('/login');
      }
    } catch (e) {
      log.error('Error during logout: $e');
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error logging out: $e')),
        );
      }
    }
  }

  Future<void> _loadWalletBalance({bool force = false}) async {
    if (_walletLoading && !force) return;

    setState(() {
      _walletLoading = true;
      _walletError = null;
    });

    try {
      final userProvider = Provider.of<UserProvider>(context, listen: false);
      final username = userProvider.localUser?.username;
      if (username == null || username.isEmpty) {
        setState(() {
          _walletError = 'Not signed in';
          _walletLoading = false;
        });
        return;
      }

      final clientProvider = Provider.of<ClientProvider>(context, listen: false);
      if (!clientProvider.isConnected) {
        await clientProvider.initializeConnection();
      }

      final wallet = await clientProvider.client.getWallet(username);
      if (!mounted) return;

      if (wallet == null) {
        setState(() {
          _walletError = 'Balance unavailable';
          _walletLoading = false;
        });
        return;
      }

      setState(() {
        _walletBalance = (wallet['balance'] as double?) ?? 0.0;
        _walletLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _walletError = 'Balance unavailable';
        _walletLoading = false;
      });
    }
  }

  Widget _buildBalanceChip() {
    if (_walletLoading) {
      return const SizedBox(
        width: 20,
        height: 20,
        child: CircularProgressIndicator(strokeWidth: 2),
      );
    }

    if (_walletError != null) {
      return Text(
        _walletError!,
        style: const TextStyle(fontSize: 12, color: Colors.white70),
      );
    }

    final balanceText = _walletBalance != null
        ? _walletBalance!.toStringAsFixed(2)
        : '--';

    return Row(
      children: [
        Image.asset(
          'assets/images/bitcoin.png',
          width: 18,
          height: 18,
        ),
        const SizedBox(width: 6),
        Text(
          balanceText,
          style: const TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w600,
            color: Colors.white,
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final userProvider = Provider.of<UserProvider>(context);
    final username = userProvider.localUser?.username ?? 'User';

    return Scaffold(
      appBar: AppBar(
        title: const Text('Aurex Marketplace'),
        centerTitle: false,
        elevation: 0,
        backgroundColor: Colors.blue[600],
        foregroundColor: Colors.white,
        actions: [
          IconButton(
            tooltip: 'Refresh balance',
            onPressed: _loadWalletBalance,
            icon: const Icon(Icons.refresh),
          ),
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: _buildBalanceChip(),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {
          context.go('/upload-asset');
        },
        backgroundColor: Colors.blue.shade600,
        icon: const Icon(Icons.add),
        label: const Text('Upload'),
      ),
      drawer: Drawer(
        child: ListView(
          padding: EdgeInsets.zero,
          children: [
            DrawerHeader(
              decoration: BoxDecoration(
                color: Colors.blue.shade600,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  CircleAvatar(
                    radius: 28,
                    backgroundColor: Colors.white,
                    child: Text(
                      username[0].toUpperCase(),
                      style: TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.bold,
                        color: Colors.blue[600],
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    username,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    userProvider.localUser?.email ?? 'No email',
                    style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 12,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
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
              leading: const Icon(Icons.inventory_2),
              title: const Text('My Assets'),
              onTap: () {
                Navigator.pop(context);
                context.go('/my-assets');
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
                        padding: const EdgeInsets.all(12.0),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              item.title,
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                                fontSize: 14,
                              ),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                            const SizedBox(height: 6),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Row(
                                  children: [
                                    Image.asset(
                                      'assets/images/bitcoin.png',
                                      width: 14,
                                      height: 14,
                                    ),
                                    const SizedBox(width: 6),
                                    Text(
                                      '\$${item.price.toStringAsFixed(2)}',
                                      style: TextStyle(
                                        color: Colors.green[600],
                                        fontWeight: FontWeight.bold,
                                        fontSize: 14,
                                      ),
                                    ),
                                  ],
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 6,
                                    vertical: 2,
                                  ),
                                  decoration: BoxDecoration(
                                    color: Colors.blue[50],
                                    borderRadius: BorderRadius.circular(4),
                                  ),
                                  child: Text(
                                    'View',
                                    style: TextStyle(
                                      fontSize: 10,
                                      color: Colors.blue[600],
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'by ${item.author}',
                              style: TextStyle(
                                fontSize: 10,
                                color: Colors.grey[600],
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
