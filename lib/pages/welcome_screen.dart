import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../providers/client_provider.dart';

class WelcomeScreen extends StatefulWidget {
  const WelcomeScreen({super.key});

  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen>
    with SingleTickerProviderStateMixin {
  late AnimationController _animationController;
  late Animation<double> _fadeAnimation;
  late Animation<double> _scaleAnimation;
  bool _connectionFailed = false;

  @override
  void initState() {
    super.initState();
    _setupAnimations();
    _initializeConnection();
  }

  void _setupAnimations() {
    _animationController = AnimationController(
      duration: const Duration(milliseconds: 1500),
      vsync: this,
    );

    _fadeAnimation = Tween<double>(begin: 0, end: 1).animate(
      CurvedAnimation(parent: _animationController, curve: Curves.easeIn),
    );

    _scaleAnimation = Tween<double>(begin: 0.8, end: 1).animate(
      CurvedAnimation(parent: _animationController, curve: Curves.easeOutCubic),
    );

    _animationController.forward();
  }

  Future<void> _initializeConnection() async {
    // Wait for animation to complete
    await Future.delayed(const Duration(milliseconds: 1500));

    if (!mounted) return;

    try {
      final clientProvider = Provider.of<ClientProvider>(context, listen: false);
      
      // Check if already connected (connection started at app level)
      if (clientProvider.isConnected) {
        print('✅ Already connected to server');
        if (mounted) {
          context.go('/login');
        }
        return;
      }
      
      // Wait for connection to complete (started in main.dart)
      final success = await Future.any([
        _waitForConnection(clientProvider),
        Future.delayed(const Duration(seconds: 10), () => false),
      ]);

      if (mounted) {
        if (success) {
          await Future.delayed(const Duration(seconds: 1));
          if (mounted) {
            context.go('/login');
          }
        } else {
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

  Future<bool> _waitForConnection(ClientProvider clientProvider) async {
    // Wait up to 10 seconds for connection to be established
    final startTime = DateTime.now();
    while (DateTime.now().difference(startTime).inSeconds < 10) {
      if (clientProvider.isConnected) {
        return true;
      }
      await Future.delayed(const Duration(milliseconds: 500));
    }
    return false;
  }

  Future<void> _retryConnection() async {
    setState(() => _connectionFailed = false);

    try {
      final clientProvider = Provider.of<ClientProvider>(context, listen: false);

      if (!mounted) return;
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (context) => Dialog(
          backgroundColor: Colors.transparent,
          child: Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircularProgressIndicator(
                  strokeWidth: 3,
                  valueColor: AlwaysStoppedAnimation(Color(0xFF6366F1)),
                ),
                SizedBox(height: 20),
                Text(
                  'Reconnecting...',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ),
      );

      final success = await clientProvider.retryConnection().timeout(
        const Duration(seconds: 10),
        onTimeout: () => false,
      );

      if (mounted) {
        Navigator.pop(context);

        if (success) {
          await Future.delayed(const Duration(seconds: 1));
          if (mounted) {
            context.go('/login');
          }
        } else {
          setState(() => _connectionFailed = true);
        }
      }
    } catch (e) {
      print('❌ Retry error: $e');
      if (mounted) {
        Navigator.pop(context);
        setState(() => _connectionFailed = true);
      }
    }
  }

  void _showConnectionErrorDialog() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => Dialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.red.withOpacity(0.1),
                  shape: BoxShape.circle,
                ),
                child: const Icon(
                  Icons.wifi_off,
                  color: Colors.red,
                  size: 32,
                ),
              ),
              const SizedBox(height: 20),
              const Text(
                'Connection Failed',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 12),
              Text(
                'Unable to connect to the server. Please check your internet connection.',
                style: TextStyle(
                  fontSize: 14,
                  color: Colors.grey[600],
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: () {
                    Navigator.pop(context);
                    _retryConnection();
                  },
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    backgroundColor: const Color(0xFF6366F1),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                  child: const Text(
                    'Try Again',
                    style: TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w600,
                      fontSize: 16,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _animationController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_connectionFailed) {
      Future.microtask(() => _showConnectionErrorDialog());
    }

    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              const Color(0xFF6366F1),
              const Color(0xFF6366F1).withOpacity(0.8),
              const Color(0xFF4F46E5),
            ],
          ),
        ),
        child: Center(
          child: ScaleTransition(
            scale: _scaleAnimation,
            child: FadeTransition(
              opacity: _fadeAnimation,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      color: Colors.white.withOpacity(0.95),
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withOpacity(0.15),
                          blurRadius: 20,
                          offset: const Offset(0, 10),
                        ),
                      ],
                    ),
                    child: Image.asset(
                      'assets/icons/icon_black.png',
                      width: 120,
                      height: 120,
                    ),
                  ),
                  const SizedBox(height: 32),
                  const Text(
                    'Aurex',
                    style: TextStyle(
                      fontSize: 36,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                      letterSpacing: 1.2,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'Blockchain Marketplace',
                    style: TextStyle(
                      fontSize: 16,
                      color: Colors.white.withOpacity(0.8),
                      letterSpacing: 0.5,
                    ),
                  ),
                  const SizedBox(height: 48),
                  SizedBox(
                    width: 50,
                    height: 50,
                    child: CircularProgressIndicator(
                      strokeWidth: 4,
                      valueColor: AlwaysStoppedAnimation(
                        Colors.white.withOpacity(0.8),
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                  Text(
                    'Connecting to server...',
                    style: TextStyle(
                      fontSize: 14,
                      color: Colors.white.withOpacity(0.7),
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
