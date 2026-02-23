import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:go_router/go_router.dart';
import '../providers/client_provider.dart';

/// Connection Loading Page - Discovers server and establishes connection
class ConnectionLoadingPage extends StatefulWidget {
  final String? nextRoute;

  const ConnectionLoadingPage({
    this.nextRoute = '/home',
    super.key,
  });

  @override
  State<ConnectionLoadingPage> createState() => _ConnectionLoadingPageState();
}

class _ConnectionLoadingPageState extends State<ConnectionLoadingPage> {
  String _status = 'Discovering server...';
  bool _discoveryFailed = false;
  final _ipController = TextEditingController();
  final _portController = TextEditingController(text: '23456');

  @override
  void initState() {
    super.initState();
    _startConnection();
  }

  Future<void> _startConnection() async {
    try {
      final clientProvider =
          Provider.of<ClientProvider>(context, listen: false);

      // Try automatic discovery first
      setState(() => _status = '📡 Discovering server via broadcast...');

      final discovered = await clientProvider.client.discoverServer(
        timeout: const Duration(seconds: 5),
        broadcastPort: 12345,
      );

      if (discovered && mounted) {
        // Server discovered, connect to it
        setState(() => _status = '🔗 Connecting to server...');
        await clientProvider.connect();

        if (mounted) {
          context.go(widget.nextRoute ?? '/home');
        }
      } else {
        // Discovery failed, show manual entry option
        if (mounted) {
          setState(() {
            _discoveryFailed = true;
            _status = 'Server discovery failed. Enter server IP manually.';
          });
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _discoveryFailed = true;
          _status = 'Connection error: $e';
        });
      }
    }
  }

  Future<void> _connectWithManualIP() async {
    if (_ipController.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter server IP')),
      );
      return;
    }

    try {
      final clientProvider =
          Provider.of<ClientProvider>(context, listen: false);

      final port = int.tryParse(_portController.text) ?? 23456;
      clientProvider.client.setServerAddress(_ipController.text, port);

      setState(() => _status = '🔗 Connecting to ${_ipController.text}:$port...');

      await clientProvider.connect(discoverFirst: false);

      if (mounted) {
        context.go(widget.nextRoute ?? '/home');
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Connection failed: $e')),
      );
    }
  }

  @override
  void dispose() {
    _ipController.dispose();
    _portController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return WillPopScope(
      onWillPop: () async => false, // Prevent back button during connection
      child: Scaffold(
        backgroundColor: const Color(0xFF1A1A2E),
        body: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // Logo
                Image.asset(
                  'assets/icons/icon_white.png',
                  width: 80,
                  height: 80,
                ),
                const SizedBox(height: 32),

                // Title
                const Text(
                  'Aurex Marketplace',
                  style: TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 32),

                // Status message
                Text(
                  _status,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontSize: 16,
                    color: Colors.white70,
                  ),
                ),
                const SizedBox(height: 32),

                // Loading spinner (if discovering)
                if (!_discoveryFailed)
                  const SizedBox(
                    width: 50,
                    height: 50,
                    child: CircularProgressIndicator(
                      valueColor: AlwaysStoppedAnimation<Color>(
                        Colors.blueAccent,
                      ),
                      strokeWidth: 3,
                    ),
                  ),

                // Manual IP entry (if discovery failed)
                if (_discoveryFailed) ...[
                  const SizedBox(height: 24),
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.white10,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white30),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Enter Server Address',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.bold,
                            color: Colors.white,
                          ),
                        ),
                        const SizedBox(height: 16),

                        // IP Input
                        TextField(
                          controller: _ipController,
                          decoration: InputDecoration(
                            hintText: '192.168.1.61',
                            hintStyle: const TextStyle(color: Colors.white30),
                            prefixIcon: const Icon(
                              Icons.language,
                              color: Colors.white54,
                            ),
                            filled: true,
                            fillColor: Colors.white10,
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(8),
                              borderSide: BorderSide.none,
                            ),
                          ),
                          style: const TextStyle(color: Colors.white),
                        ),
                        const SizedBox(height: 12),

                        // Port Input
                        TextField(
                          controller: _portController,
                          decoration: InputDecoration(
                            hintText: '23456',
                            hintStyle: const TextStyle(color: Colors.white30),
                            prefixIcon: const Icon(
                              Icons.settings,
                              color: Colors.white54,
                            ),
                            filled: true,
                            fillColor: Colors.white10,
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(8),
                              borderSide: BorderSide.none,
                            ),
                          ),
                          style: const TextStyle(color: Colors.white),
                          keyboardType: TextInputType.number,
                        ),
                        const SizedBox(height: 16),

                        // Connect button
                        SizedBox(
                          width: double.infinity,
                          child: ElevatedButton(
                            onPressed: _connectWithManualIP,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: Colors.blueAccent,
                              padding: const EdgeInsets.symmetric(vertical: 12),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                            ),
                            child: const Text(
                              'Connect',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.bold,
                                color: Colors.white,
                              ),
                            ),
                          ),
                        ),

                        const SizedBox(height: 12),

                        // Retry discovery button
                        SizedBox(
                          width: double.infinity,
                          child: OutlinedButton(
                            onPressed: () {
                              setState(() => _discoveryFailed = false);
                              _startConnection();
                            },
                            style: OutlinedButton.styleFrom(
                              side: const BorderSide(color: Colors.white30),
                              padding: const EdgeInsets.symmetric(vertical: 12),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                            ),
                            child: const Text(
                              'Try Auto-Discovery Again',
                              style: TextStyle(
                                fontSize: 14,
                                color: Colors.white,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],

                const SizedBox(height: 32),

                // Help text
                const Text(
                  'Make sure the server is running on your local network',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 12,
                    color: Colors.white30,
                    fontStyle: FontStyle.italic,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
