import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/client_provider.dart';
import '../client_class.dart';

/// Debug overlay widget - shows all sent/received messages
/// Use this by wrapping your app/pages with it
class DebugOverlay extends StatefulWidget {
  final Widget child;

  const DebugOverlay({
    required this.child,
    super.key,
  });

  @override
  State<DebugOverlay> createState() => _DebugOverlayState();
}

class _DebugOverlayState extends State<DebugOverlay> {
  bool _showDebug = false;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        widget.child,
        // Debug toggle button (bottom right corner)
        Positioned(
          bottom: 20,
          right: 20,
          child: FloatingActionButton(
            mini: true,
            backgroundColor: Colors.black87,
            onPressed: () {
              setState(() {
                _showDebug = !_showDebug;
              });
            },
            tooltip: 'Toggle Debug Console',
            child: Icon(
              _showDebug ? Icons.close : Icons.bug_report,
              color: _showDebug ? Colors.red : Colors.cyan,
            ),
          ),
        ),
        // Debug console overlay
        if (_showDebug)
          Positioned(
            bottom: 0,
            left: 0,
            right: 0,
            child: Container(
              height: MediaQuery.of(context).size.height * 0.4,
              decoration: const BoxDecoration(
                color: Colors.black87,
                border: Border(
                  top: BorderSide(color: Colors.cyan, width: 2),
                ),
              ),
              child: Column(
                children: [
                  // Header
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    color: Colors.grey[900],
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          '📡 Protocol Debug Console',
                          style: TextStyle(
                            color: Colors.cyan,
                            fontWeight: FontWeight.bold,
                            fontSize: 12,
                          ),
                        ),
                        Consumer<ClientProvider>(
                          builder: (context, provider, _) {
                            return Text(
                              provider.client.isConnected ? '🟢 CONNECTED' : '🔴 DISCONNECTED',
                              style: TextStyle(
                                color: provider.client.isConnected ? Colors.green : Colors.red,
                                fontSize: 11,
                                fontWeight: FontWeight.bold,
                              ),
                            );
                          },
                        ),
                      ],
                    ),
                  ),
                  // Messages list
                  Expanded(
                    child: Consumer<ClientProvider>(
                      builder: (context, provider, _) {
                        final messages = provider.client.messageHistory;
                        return ListView.builder(
                          reverse: true,
                          itemCount: messages.length,
                          itemBuilder: (context, index) {
                            final msg = messages[messages.length - 1 - index];
                            return _buildMessageTile(msg);
                          },
                        );
                      },
                    ),
                  ),
                  // Clear button
                  Container(
                    padding: const EdgeInsets.all(8),
                    color: Colors.grey[900],
                    child: SizedBox(
                      width: double.infinity,
                      child: ElevatedButton.icon(
                        onPressed: () {
                          // Note: You might want to add a clearHistory method to Client
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text('Message history cleared'),
                              duration: Duration(seconds: 2),
                            ),
                          );
                        },
                        icon: const Icon(Icons.delete_sweep, size: 16),
                        label: const Text('Clear History', style: TextStyle(fontSize: 11)),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.red[700],
                          padding: const EdgeInsets.symmetric(vertical: 8),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }

  /// Build a single message tile
  Widget _buildMessageTile(MessageEvent msg) {
    Color statusColor;
    String statusIcon;

    switch (msg.status) {
      case 'success':
        statusColor = Colors.green;
        statusIcon = '✓';
        break;
      case 'error':
        statusColor = Colors.red;
        statusIcon = '✗';
        break;
      case 'pending':
        statusColor = Colors.yellow;
        statusIcon = '⏳';
        break;
      default:
        statusColor = Colors.grey;
        statusIcon = '•';
    }

    Color typeColor;
    String typeLabel;

    switch (msg.type) {
      case 'sent':
        typeColor = Colors.blue;
        typeLabel = '→ SENT';
        break;
      case 'received':
        typeColor = Colors.green;
        typeLabel = '← RECV';
        break;
      case 'system':
        typeColor = Colors.orange;
        typeLabel = '⚙ SYS';
        break;
      default:
        typeColor = Colors.grey;
        typeLabel = 'UNK';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(color: Colors.grey[800]!, width: 0.5),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Status icon
          Text(
            statusIcon,
            style: TextStyle(color: statusColor, fontSize: 10),
          ),
          const SizedBox(width: 4),
          // Time
          Text(
            '[${msg.timestamp.hour.toString().padLeft(2, '0')}:${msg.timestamp.minute.toString().padLeft(2, '0')}:${msg.timestamp.second.toString().padLeft(2, '0')}]',
            style: const TextStyle(color: Colors.grey, fontSize: 9),
          ),
          const SizedBox(width: 6),
          // Type label
          Text(
            typeLabel,
            style: TextStyle(
              color: typeColor,
              fontSize: 9,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(width: 6),
          // Message (with overflow handling)
          Expanded(
            child: Text(
              msg.message.length > 60
                  ? '${msg.message.substring(0, 60)}...'
                  : msg.message,
              style: const TextStyle(
                color: Colors.white70,
                fontSize: 9,
                fontFamily: 'Courier',
              ),
              overflow: TextOverflow.ellipsis,
              maxLines: 2,
            ),
          ),
        ],
      ),
    );
  }
}

/// Helper widget to show a message debug dialog
/// Call this when a message is about to be sent/received
class MessageDebugDialog extends StatelessWidget {
  final String title;
  final String message;
  final String type; // 'sent', 'received', 'error'

  const MessageDebugDialog({
    required this.title,
    required this.message,
    required this.type,
    super.key,
  });

  @override
  Widget build(BuildContext context) {
    Color bgColor;
    Color titleColor;
    IconData icon;

    switch (type) {
      case 'sent':
        bgColor = Colors.blue[900]!;
        titleColor = Colors.blue;
        icon = Icons.send;
        break;
      case 'received':
        bgColor = Colors.green[900]!;
        titleColor = Colors.green;
        icon = Icons.inbox;
        break;
      case 'error':
        bgColor = Colors.red[900]!;
        titleColor = Colors.red;
        icon = Icons.error;
        break;
      default:
        bgColor = Colors.grey[900]!;
        titleColor = Colors.grey;
        icon = Icons.info;
    }

    return Dialog(
      backgroundColor: bgColor,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Title with icon
            Row(
              children: [
                Icon(icon, color: titleColor),
                const SizedBox(width: 10),
                Text(
                  title,
                  style: TextStyle(
                    color: titleColor,
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            // Message in monospace font
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: Colors.black54,
                border: Border.all(color: titleColor),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                message,
                style: const TextStyle(
                  color: Colors.white,
                  fontFamily: 'Courier',
                  fontSize: 12,
                ),
              ),
            ),
            const SizedBox(height: 12),
            // Close button
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('OK'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
