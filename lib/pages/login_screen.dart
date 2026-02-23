import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:provider/provider.dart';
import '../providers/user_provider.dart';
import '../providers/client_provider.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  bool _isLoading = false;
  final GoogleSignIn _googleSignIn = GoogleSignIn();
  final TextEditingController _usernameController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  bool _obscurePassword = true;

  Future<void> _signInWithUsername() async {
    if (!mounted) return;

    final username = _usernameController.text.trim();
    final password = _passwordController.text;

    if (username.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Username cannot be empty')),
      );
      return;
    }
    if (password.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Password cannot be empty')),
      );
      return;
    }
    if (username.contains('|') || username.contains(' ')) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Invalid username format')),
      );
      return;
    }

    setState(() => _isLoading = true);

    try {
      final clientProvider = Provider.of<ClientProvider>(context, listen: false);

      if (!clientProvider.isConnected) {
        final connected = await clientProvider.initializeConnection();
        if (!connected) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Server connection failed')),
            );
          }
          return;
        }
      }

      final result = await clientProvider.client.login(username, password);

      if (result != null) {
        Provider.of<UserProvider>(context, listen: false).setLocalUser(
          username: result,
          email: '',
        );

        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Welcome, $result!')),
          );
          context.go('/marketplace');
        }
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('user not found')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  /// Sign in with Google: get email, then look up user by email on server (ORM get_user_by_email).
  Future<void> _signInWithGoogle() async {
    if (!mounted) return;
    setState(() => _isLoading = true);

    try {
      final GoogleSignInAccount? googleUser = await _googleSignIn.signIn();

      if (googleUser == null) {
        if (mounted) setState(() => _isLoading = false);
        return;
      }

      final googleEmail = googleUser.email;
      if (googleEmail.isEmpty) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Could not get email from Google')),
          );
        }
        setState(() => _isLoading = false);
        return;
      }

      final clientProvider = Provider.of<ClientProvider>(context, listen: false);
      await clientProvider.initializeConnection();

      final username = await clientProvider.client.getUserByEmail(googleEmail);
      if (username != null && mounted) {
        final displayName = googleUser.displayName ?? googleEmail.split('@')[0];
        Provider.of<UserProvider>(context, listen: false).setLocalUser(
          username: username,
          email: googleEmail,
        );
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Welcome, $displayName!')),
        );
        context.go('/marketplace');
      } else if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('No account with this email. Sign up with email first.'),
          ),
        );
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
    _usernameController.dispose();
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
                      controller: _usernameController,
                      decoration: InputDecoration(
                        hintText: 'Username',
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
                        onPressed: _isLoading ? null : _signInWithUsername,
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
