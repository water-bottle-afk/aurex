import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../providers/client_provider.dart';

class WelcomeScreen extends StatefulWidget {
  const WelcomeScreen({super.key});

  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen> {
  bool _showLogo = true;
  bool _connectionFailed = false;

  @override
  void initState() {
    super.initState();
    _initializeConnection();
  }

  Future<void> _initializeConnection() async {
    // Show logo for 1 second
    await Future.delayed(const Duration(seconds: 1));

    if (!mounted) return;

    // Try to connect with 5-second timeout
    try {
      final clientProvider = Provider.of<ClientProvider>(context, listen: false);
      final success = await clientProvider.initializeConnection().timeout(
        const Duration(seconds: 5),
        onTimeout: () => false,
      );

      if (mounted) {
        if (success) {
          // Connection successful - navigate to login after 2 seconds
          await Future.delayed(const Duration(seconds: 2));
          if (mounted) {
            context.go('/login');
          }
        } else {
          // Connection failed - show retry dialog
          setState(() => _connectionFailed = true);
        }
      }
    } catch (e) {
      print('❌ Connection error: $e');
      if (mounted) {
        setState(() => _connectionFailed = true);
      }
    }
  }

  Future<void> _retryConnection() async {
    setState(() => _connectionFailed = false);

    try {
      final clientProvider = Provider.of<ClientProvider>(context, listen: false);
      
      // Show loading
      if (!mounted) return;
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (context) => const Dialog(
          child: Padding(
            padding: EdgeInsets.all(20),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircularProgressIndicator(),
                SizedBox(width: 20),
                Text('Connecting...'),
              ],
            ),
          ),
        ),
      );

      // Attempt connection with 5-second timeout
      final success = await clientProvider.retryConnection().timeout(
        const Duration(seconds: 5),
        onTimeout: () => false,
      );

      if (mounted) {
        Navigator.pop(context); // Close loading dialog

        if (success) {
          // Connection successful - navigate to login
          await Future.delayed(const Duration(seconds: 1));
          if (mounted) {
            context.go('/login');
          }
        } else {
          // Connection failed again - show retry dialog
          setState(() => _connectionFailed = true);
        }
      }
    } catch (e) {
      print('❌ Retry error: $e');
      if (mounted) {
        Navigator.pop(context, null); // Close loading dialog if still open
        setState(() => _connectionFailed = true);
      }
    }
  }

  void _showConnectionErrorDialog() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Connection Failed'),
        content: const Text(
          'Unable to connect to the server. Please check your internet connection and try again.',
        ),
        actions: [
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              _retryConnection();
            },
            child: const Text('Retry'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_connectionFailed) {
      Future.microtask(() => _showConnectionErrorDialog());
    }

    return Scaffold(
      body: Center(
        child: _showLogo
            ? Image.asset('assets/icons/icon_white.png')
            : const SizedBox.shrink(),
      ),
    );
  }
}
