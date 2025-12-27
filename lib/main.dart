import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:path_provider/path_provider.dart';
import 'package:provider/provider.dart';
import 'firebase_options.dart';
import 'pages/about_page.dart';
import 'pages/forgot_password.dart';
import 'pages/login_screen.dart';
import 'pages/marketplace_page.dart';
import 'pages/settings_page.dart';
import 'pages/signup_screen.dart';
import 'pages/upload_asset.dart';
import 'pages/welcome_screen.dart';
import 'providers/user_provider.dart';
import 'providers/client_provider.dart';
import 'providers/settings_provider.dart';
import 'providers/assets_provider.dart';

void main() async {
  // Initialize Flutter bindings
  WidgetsFlutterBinding.ensureInitialized();

  // Initialize Firebase
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );

  runApp(const MyApp());
}

/// Clear app cache
Future<void> clearAppCache() async {
  try {
    final appDir = await getApplicationCacheDirectory();
    if (await appDir.exists()) {
      appDir.deleteSync(recursive: true);
      await appDir.create(recursive: true);
      print('✅ Cache cleared successfully');
    }
  } catch (e) {
    print('⚠️ Error clearing cache: $e');
  }
}

final _router = GoRouter(
  initialLocation: '/',
  routes: [
    GoRoute(
      path: '/',
      builder: (context, state) => const WelcomeScreen(),
    ),
    GoRoute(
      path: '/login',
      builder: (context, state) => const LoginScreen(),
    ),
    GoRoute(
      path: '/signup',
      builder: (context, state) => const SignupScreen(),
    ),
    GoRoute(
      path: '/forgot-password',
      builder: (context, state) => const ForgotPasswordPage(),
    ),
    GoRoute(
      path: '/about',
      builder: (context, state) => const AboutPage(),
    ),
    GoRoute(
      path: '/marketplace',
      builder: (context, state) => const MarketplacePage(),
    ),
    GoRoute(
      path: '/upload-asset',
      builder: (context, state) => const UploadAssetPage(),
    ),
    GoRoute(
      path: '/settings',
      builder: (context, state) => const SettingsPage(),
    ),
  ],
);

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (context) => UserProvider()),
        ChangeNotifierProvider(create: (context) => ClientProvider()),
        ChangeNotifierProvider(create: (context) => SettingsProvider()),
        ChangeNotifierProvider(
          create: (context) => AssetsProvider(
            clientProvider: Provider.of<ClientProvider>(context, listen: false),
          ),
        ),
      ],
      child: MaterialApp.router(
        title: 'Aurex - Blockchain Image Ownership',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          primarySwatch: Colors.blue,
        ),
        routerConfig: _router,
      ),
    );
  }
}

/// Server connection initialization screen
/// Shows before the app loads - establishes connection to blockchain server
class ServerConnectionScreen extends StatefulWidget {
  const ServerConnectionScreen({super.key});

  @override
  State<ServerConnectionScreen> createState() => _ServerConnectionScreenState();
}

class _ServerConnectionScreenState extends State<ServerConnectionScreen> {
  late ClientProvider _clientProvider;

  @override
  void initState() {
    super.initState();
    _initializeConnection();
  }

  /// Initialize connection to server on app start
  Future<void> _initializeConnection() async {
    _clientProvider = context.read<ClientProvider>();

    // Show loading dialog
    if (mounted) {
      _showLoadingDialog();
    }

    // Wait 3 seconds for connection attempt
    final connected = await Future.any([
      _clientProvider.initializeConnection(),
      Future.delayed(const Duration(seconds: 3), () => false),
    ]).catchError((_) => false);

    if (mounted) {
      Navigator.pop(context); // Close loading dialog

      if (connected) {
        // Connection successful - proceed to app
        if (mounted) {
          _showSuccessAndNavigate();
        }
      } else {
        // Connection failed - show error dialog
        if (mounted) {
          _showConnectionErrorDialog();
        }
      }
    }
  }

  /// Show loading dialog while connecting
  void _showLoadingDialog() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text(
          'Connecting to Server',
          style: TextStyle(color: Colors.white),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 20),
            const CircularProgressIndicator(color: Colors.blue),
            const SizedBox(height: 20),
            Text(
              'Looking for blockchain server...',
              style: TextStyle(color: Colors.grey[300]),
            ),
          ],
        ),
      ),
    );
  }

  /// Show success and navigate to home screen
  void _showSuccessAndNavigate() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text(
          '✅ Connected',
          style: TextStyle(color: Colors.green),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 20),
            Text(
              'Successfully connected to server!',
              style: TextStyle(color: Colors.grey[300]),
            ),
          ],
        ),
      ),
    );

    Future.delayed(const Duration(seconds: 2), () {
      if (mounted) {
        Navigator.pop(context);
        Navigator.pushReplacementNamed(context, '/');
      }
    });
  }

  /// Show connection error dialog with retry button
  void _showConnectionErrorDialog() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text(
          'Connection Error',
          style: TextStyle(color: Colors.red),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 20),
            Text(
              'Unable to connect with the server.\nCheck your internet connection and try again.',
              style: TextStyle(color: Colors.grey[300]),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 20),
            // Debug info - show error message
            if (_clientProvider.connectionError != null)
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.black,
                  border: Border.all(color: Colors.red),
                  borderRadius: BorderRadius.circular(5),
                ),
                child: Text(
                  'Error: ${_clientProvider.connectionError}',
                  style: const TextStyle(color: Colors.orange, fontSize: 10),
                ),
              ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _initializeConnection();
            },
            child: const Text(
              'TRY AGAIN',
              style: TextStyle(color: Colors.blue),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey[900],
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const CircularProgressIndicator(color: Colors.blue),
            const SizedBox(height: 20),
            Text(
              'Initializing Blockchain Connection...',
              style: TextStyle(color: Colors.grey[300]),
            ),
          ],
        ),
      ),
    );
  }
}