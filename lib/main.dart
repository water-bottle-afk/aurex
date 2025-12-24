import 'dart:io';
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
import 'pages/welcome_screen.dart';
import 'providers/user_provider.dart';
import 'providers/client_provider.dart';
import 'providers/settings_provider.dart';

void main() async {
  // Initialize Flutter bindings
  WidgetsFlutterBinding.ensureInitialized();
  
  // Verify server connectivity before starting app
  await _verifyServerConnection();
  
  // Initialize Firebase
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
  
  runApp(const MyApp());
}

/// Verify connection to server
Future<void> _verifyServerConnection() async {
  try {
    final result = await InternetAddress.lookup('google.com');
    if (result.isNotEmpty && result[0].rawAddress.isNotEmpty) {
      print('✅ Server connection verified');
    }
  } catch (e) {
    print('⚠️ No internet connection: $e');
  }
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
      ],
      child: MaterialApp.router(
        title: 'Aurex',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          primarySwatch: Colors.blue,
        ),
        routerConfig: _router,
      ),
    );
  }
}