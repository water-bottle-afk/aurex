import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:go_router/go_router.dart';
import '../models/notification_item.dart';
import '../providers/notifications_provider.dart';

class NotificationsPage extends StatefulWidget {
  const NotificationsPage({super.key});

  @override
  State<NotificationsPage> createState() => _NotificationsPageState();
}

class _NotificationsPageState extends State<NotificationsPage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      final provider = context.read<NotificationsProvider>();
      await provider.refresh();
      await provider.markAllRead();
    });
  }

  String _formatTimestamp(DateTime dt) {
    final y = dt.year.toString().padLeft(4, '0');
    final m = dt.month.toString().padLeft(2, '0');
    final d = dt.day.toString().padLeft(2, '0');
    final h = dt.hour.toString().padLeft(2, '0');
    final min = dt.minute.toString().padLeft(2, '0');
    return '$y-$m-$d $h:$min';
  }

  IconData _iconForType(String type) {
    switch (type) {
      case 'purchase_confirmed':
        return Icons.check_circle;
      case 'purchase_failed':
        return Icons.error;
      case 'asset_sold':
        return Icons.shopping_bag;
      case 'asset_uploaded':
        return Icons.cloud_upload;
      case 'asset_received':
        return Icons.call_received;
      case 'asset_sent':
        return Icons.call_made;
      default:
        return Icons.notifications;
    }
  }

  Color _iconColor(String type) {
    switch (type) {
      case 'purchase_confirmed':
        return Colors.green;
      case 'purchase_failed':
        return Colors.red;
      case 'asset_sold':
        return Colors.blue;
      case 'asset_uploaded':
        return Colors.teal;
      case 'asset_received':
        return Colors.green;
      case 'asset_sent':
        return Colors.orange;
      default:
        return Colors.blueGrey;
    }
  }

  Widget _buildItem(NotificationItem item) {
    final baseColor = _iconColor(item.type);
    final bgColor = baseColor.withAlpha((0.15 * 255).round());
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: bgColor,
        child: Icon(_iconForType(item.type), color: baseColor),
      ),
      title: Text(
        item.title,
        style: TextStyle(
          fontWeight: item.isRead ? FontWeight.w600 : FontWeight.w700,
        ),
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 4),
          Text(item.body),
          const SizedBox(height: 6),
          Text(
            _formatTimestamp(item.createdAt),
            style: const TextStyle(fontSize: 12, color: Colors.black54),
          ),
        ],
      ),
      isThreeLine: true,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        backgroundColor: Colors.blue[600],
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
      body: Consumer<NotificationsProvider>(
        builder: (context, provider, child) {
          if (provider.isLoading) {
            return const Center(child: CircularProgressIndicator());
          }
          if (provider.error != null) {
            return Center(
              child: Text(provider.error!),
            );
          }
          if (provider.items.isEmpty) {
            return const Center(
              child: Text('No notifications yet'),
            );
          }
          return ListView.separated(
            itemCount: provider.items.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, index) {
              return _buildItem(provider.items[index]);
            },
          );
        },
      ),
    );
  }
}
