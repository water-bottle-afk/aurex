import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../models/item_offering.dart';
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

    final statusNotifier = ValueNotifier<String>('Submitting purchase...');
    var dialogOpen = false;

    if (mounted) {
      dialogOpen = true;
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (context) {
          return AlertDialog(
            title: const Text('Blockchain Purchase'),
            content: ValueListenableBuilder<String>(
              valueListenable: statusNotifier,
              builder: (context, value, child) {
                return Row(
                  children: [
                    const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    const SizedBox(width: 12),
                    Expanded(child: Text(value)),
                  ],
                );
              },
            ),
          );
        },
      );
    }

    var success = false;
    var finalMessage = '';

    try {
      final buyResult = await clientProvider.client.buyAsset(
        assetId: widget.asset.id,
        username: username,
        amount: widget.asset.price,
      );

      if (buyResult.status == 'PENDING' && buyResult.txId != null) {
        statusNotifier.value = 'Mining started. Waiting for confirmation...';
        final txId = buyResult.txId!;
        final deadline = DateTime.now().add(const Duration(minutes: 10));

        while (DateTime.now().isBefore(deadline)) {
          await Future.delayed(const Duration(seconds: 3));
          final status = await clientProvider.client.getTransactionStatus(txId);

          if (status.status == 'CONFIRMED') {
            success = true;
            finalMessage = 'Purchase confirmed!';
            break;
          }
          if (status.status == 'QUEUED') {
            statusNotifier.value = 'Queued for mining...';
          }
          if (status.status == 'SUBMITTED') {
            statusNotifier.value = 'Mining in progress...';
          }
          if (status.status == 'FAILED') {
            finalMessage = status.message.isNotEmpty
                ? status.message
                : 'Transaction failed.';
            break;
          }
          if (status.status == 'TIMEOUT') {
            finalMessage = status.message.isNotEmpty
                ? status.message
                : 'PoW Timeout after 10 mins';
            break;
          }
          if (status.status == 'ERROR') {
            finalMessage = status.message;
            break;
          }
        }

        if (!success && finalMessage.isEmpty) {
          finalMessage = 'PoW Timeout after 10 mins';
        }
      } else if (buyResult.status == 'PENDING' && buyResult.txId == null) {
        finalMessage = 'Purchase queued, but no transaction ID was returned.';
      } else if (buyResult.status == 'ERROR') {
        finalMessage = buyResult.message ?? 'Purchase failed.';
      } else {
        success = true;
        finalMessage = 'Purchase confirmed!';
      }
    } catch (e) {
      finalMessage = 'Purchase failed: $e';
    } finally {
      if (dialogOpen && mounted) {
        Navigator.of(context, rootNavigator: true).pop();
      }
      statusNotifier.dispose();
      if (mounted) {
        setState(() => _isProcessing = false);
        if (success) {
          Provider.of<MyAssetsProvider>(context, listen: false).refreshAssets();
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(finalMessage),
            backgroundColor: success ? Colors.green[600] : Colors.red[600],
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
          return Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: ConstrainedBox(
                constraints: BoxConstraints(maxWidth: maxWidth),
                child: AssetFocusCard(
                  asset: widget.asset,
                  primaryActionLabel:
                      _isProcessing ? 'Processing...' : 'Buy Now',
                  onPrimaryAction: _isProcessing ? null : _startPurchase,
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
