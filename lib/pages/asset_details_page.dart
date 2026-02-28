import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../models/item_offering.dart';
import '../providers/assets_provider.dart';
import '../providers/client_provider.dart';
import '../providers/my_assets_provider.dart';
import '../providers/user_provider.dart';
import '../widgets/asset_focus_card.dart';

class AssetDetailsPage extends StatefulWidget {
  final ItemOffering asset;

  const AssetDetailsPage({super.key, required this.asset});

  @override
  State<AssetDetailsPage> createState() => _AssetDetailsPageState();
}

class _AssetDetailsPageState extends State<AssetDetailsPage> {
  bool _isProcessing = false;

  Future<void> _startPurchase() async {
    if (_isProcessing) return;
    setState(() => _isProcessing = true);

    final clientProvider = Provider.of<ClientProvider>(context, listen: false);
    final assetsProvider = Provider.of<AssetsProvider>(context, listen: false);
    final userProvider = Provider.of<UserProvider>(context, listen: false);
    final username = userProvider.localUser?.username;

    if (username == null || username.isEmpty) {
      setState(() => _isProcessing = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please log in with a valid account.')),
      );
      return;
    }

    if (!clientProvider.isConnected) {
      final connected = await clientProvider.initializeConnection();
      if (!connected) {
        setState(() => _isProcessing = false);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Server connection failed')),
          );
        }
        return;
      }
    }

    var success = false;
    var finalMessage = '';
    var snackColor = Colors.blueGrey.shade700;

    try {
      final buyResult = await clientProvider.client.buyAsset(
        assetId: widget.asset.id,
        username: username,
        amount: widget.asset.price,
      );

      if (buyResult.status == 'PENDING') {
        assetsProvider.markPurchasePending(widget.asset.id);
        finalMessage =
            'Purchase submitted. You can keep using the app while it processes.';
      } else if (buyResult.status == 'ERROR') {
        finalMessage = buyResult.message ?? 'Purchase failed.';
        snackColor = Colors.red.shade600;
      } else {
        success = true;
        finalMessage = 'Purchase confirmed!';
        snackColor = Colors.green.shade600;
      }
    } catch (e) {
      finalMessage = 'Purchase failed: $e';
      snackColor = Colors.red.shade600;
    } finally {
      if (mounted) {
        setState(() => _isProcessing = false);
        if (success) {
          Provider.of<MyAssetsProvider>(context, listen: false).refreshAssets();
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(finalMessage),
            backgroundColor: snackColor,
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.blueGrey[50],
      appBar: AppBar(
        title: const Text('Focus Mode'),
        backgroundColor: Colors.blueGrey[900],
        foregroundColor: Colors.white,
        elevation: 0,
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
      body: LayoutBuilder(
        builder: (context, constraints) {
          final maxWidth = constraints.maxWidth < 700
              ? constraints.maxWidth
              : 700.0;
          final assetsProvider = Provider.of<AssetsProvider>(context);
          final isPending =
              assetsProvider.isPurchasePending(widget.asset.id) ||
                  _isProcessing;
          return Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: ConstrainedBox(
                constraints: BoxConstraints(maxWidth: maxWidth),
                child: AssetFocusCard(
                  asset: widget.asset,
                  primaryActionLabel:
                      isPending ? 'In Process' : 'Buy Now',
                  isPrimaryDisabled: isPending,
                  onPrimaryAction: isPending ? null : _startPurchase,
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
