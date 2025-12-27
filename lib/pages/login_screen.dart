import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:provider/provider.dart';
import '../main.dart';
import '../providers/user_provider.dart';
import '../providers/client_provider.dart';
import '../services/user_service.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  bool _isLoading = false;
  final GoogleSignIn _googleSignIn = GoogleSignIn();
  final TextEditingController _emailController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  bool _obscurePassword = true;

  Future<void> _signInWithGoogle() async {
    if (!mounted) return;
    setState(() {
      _isLoading = true;
    });

    try {
      final GoogleSignInAccount? googleUser = await _googleSignIn.signIn();

      if (googleUser == null) {
        if (mounted) setState(() => _isLoading = false);
        return;
      }

      final GoogleSignInAuthentication googleAuth = await googleUser.authentication;

      // Get both tokens with null-safety checks
      if (googleAuth.idToken == null && googleAuth.accessToken == null) {
        throw Exception('Failed to get authentication tokens from Google. Please check Firebase configuration.');
      }

      // Prefer idToken, fallback to accessToken if needed
      final idToken = googleAuth.idToken ?? googleAuth.accessToken;
      
      if (idToken == null) {
        throw Exception('No valid token received from Google Sign-In');
      }

      final AuthCredential credential = GoogleAuthProvider.credential(
        idToken: idToken,
      );

      final UserCredential userCredential =
          await FirebaseAuth.instance.signInWithCredential(credential);

      if (mounted) {
        // Clear cache on successful login
        await clearAppCache();

        // Check if user exists in local database
        final userService = UserService();
        final existingUser = await userService.getUserByGoogleId(googleUser.id);

        if (existingUser == null) {
          // New user - create an entry in the database
          await userService.createUserWithGoogle(
            email: googleUser.email,
            username: googleUser.displayName ?? 'User',
            googleId: googleUser.id,
          );
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Welcome! New account created.')),
          );
        } else {
          // Existing user
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Welcome back!')),
          );
        }

        // Initialize client connection to server
        try {
          final clientProvider = Provider.of<ClientProvider>(context, listen: false);
          await clientProvider.initializeConnection();
          print('✅ Client connected to TLS server');
        } catch (e) {
          print('⚠️ Client connection failed: $e');
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Server connection issue: $e')),
          );
        }

        Provider.of<UserProvider>(context, listen: false).setUser(userCredential.user);
        context.go('/marketplace');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error signing in: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          image: DecorationImage(
            image: AssetImage('assets/images/welcome_background.png'),
            fit: BoxFit.cover,
          ),
        ),
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24.0),
            child: Card(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
              child: Padding(
                padding: const EdgeInsets.all(32.0),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      'Welcome Back',
                      style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                            fontWeight: FontWeight.bold,
                            fontSize: 28,
                          ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Sign in to continue',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            color: Colors.grey[600],
                          ),
                    ),
                    const SizedBox(height: 32),
                    TextField(
                      controller: _emailController,
                      decoration: InputDecoration(
                        hintText: 'Email',
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(color: Colors.grey[300]!),
                        ),
                        contentPadding: const EdgeInsets.all(16),
                      ),
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _passwordController,
                      obscureText: _obscurePassword,
                      decoration: InputDecoration(
                        hintText: 'Password',
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(color: Colors.grey[300]!),
                        ),
                        contentPadding: const EdgeInsets.all(16),
                        suffixIcon: IconButton(
                          icon: Icon(
                            _obscurePassword ? Icons.visibility_off : Icons.visibility,
                            color: Colors.grey,
                          ),
                          onPressed: () {
                            setState(() => _obscurePassword = !_obscurePassword);
                          },
                        ),
                      ),
                    ),
                    const SizedBox(height: 24),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.blue[600],
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                          padding: const EdgeInsets.symmetric(vertical: 16),
                        ),
                        onPressed: _isLoading ? null : () {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text('Email login not yet implemented')),
                          );
                        },
                        child: _isLoading
                            ? const SizedBox(
                                height: 20,
                                width: 20,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Text(
                                'Login',
                                style: TextStyle(color: Colors.white, fontSize: 16),
                              ),
                      ),
                    ),
                    const SizedBox(height: 24),
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        style: OutlinedButton.styleFrom(
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                          padding: const EdgeInsets.symmetric(vertical: 16),
                        ),
                        icon: Image.asset('assets/images/google_logo.png', height: 20),
                        label: const Text('Sign in with Google'),
                        onPressed: _isLoading ? null : _signInWithGoogle,
                      ),
                    ),
                    const SizedBox(height: 16),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Text("Don't have an account? "),
                        TextButton(
                          onPressed: () => context.go('/signup'),
                          child: const Text(
                            'Sign Up',
                            style: TextStyle(color: Colors.blue),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    TextButton(
                      onPressed: () => context.go('/forgot-password'),
                      child: const Text('Forgot Password?'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
