import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_sign_in/google_sign_in.dart';

class SignupScreen extends StatefulWidget {
  final String? prefillUsername;
  final String? prefillEmail;

  const SignupScreen({
    super.key,
    this.prefillUsername,
    this.prefillEmail,
  });

  @override
  State<SignupScreen> createState() => _SignupScreenState();
}

class _SignupScreenState extends State<SignupScreen> {
  bool _isLoading = false;
  final GoogleSignIn _googleSignIn = GoogleSignIn();
  late final TextEditingController _usernameController;
  late final TextEditingController _emailController;
  final TextEditingController _passwordController = TextEditingController();
  bool _obscurePassword = true;

  @override
  void initState() {
    super.initState();
    _usernameController = TextEditingController(
      text: widget.prefillUsername ?? '',
    );
    _emailController = TextEditingController(
      text: widget.prefillEmail ?? '',
    );
  }

  Future<void> _signUpWithEmail() async {
    if (!mounted) return;

    final username = _usernameController.text.trim();
    final email = _emailController.text.trim();
    final password = _passwordController.text;

    if (username.isEmpty || email.isEmpty || password.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please fill in all fields')),
      );
      return;
    }

    if (!email.contains('@')) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter a valid email')),
      );
      return;
    }

    if (password.length < 6) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Password must be at least 6 characters')),
      );
      return;
    }

    setState(() => _isLoading = true);

    try {
      final clientProvider = Provider.of<ClientProvider>(context, listen: false);

      final result = await clientProvider.client.signUp(
        username: username,
        password: password,
        email: email,
      );

      if (result == "success") {
        Provider.of<UserProvider>(context, listen: false).setLocalUser(
          email: email,
          username: username,
        );

        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Account created successfully!')),
          );
          context.go('/login');
        }
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Signup failed. Please try again.')),
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

  /// Google sign-up: get email/name, then prefill fields for manual signup.
  Future<void> _signUpWithGoogle() async {
    if (!mounted) return;
    setState(() => _isLoading = true);

    try {
      final GoogleSignInAccount? googleUser = await _googleSignIn.signIn();

      if (googleUser == null) {
        setState(() => _isLoading = false);
        return;
      }

      final googleEmail = googleUser.email;
      final displayName =
          googleUser.displayName ?? googleEmail.split('@')[0];
      if (googleEmail.isEmpty) {
        setState(() => _isLoading = false);
        return;
      }

      if (!mounted) return;
      _usernameController.text = displayName.replaceAll(' ', '_');
      _emailController.text = googleEmail;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Google details loaded. Please set a password to sign up.'),
        ),
      );
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

  @override
  void dispose() {
    _usernameController.dispose();
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
            padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 32.0),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                GestureDetector(
                  onTap: () => context.go('/login'),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Container(
                      width: 50,
                      height: 50,
                      decoration: const BoxDecoration(
                        color: Colors.white,
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(Icons.arrow_back, color: Colors.black),
                    ),
                  ),
                ),
                const SizedBox(height: 32),
                Card(
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                  child: Padding(
                    padding: const EdgeInsets.all(32.0),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          'Create Account',
                          style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                                fontWeight: FontWeight.bold,
                                fontSize: 28,
                              ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Sign up to get started',
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
                            onPressed: _isLoading ? null : _signUpWithEmail,
                            child: _isLoading
                                ? const SizedBox(
                                    height: 20,
                                    width: 20,
                                    child: CircularProgressIndicator(strokeWidth: 2),
                                  )
                                : const Text(
                                    'Sign Up',
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
                            label: const Text('Sign up with Google'),
                            onPressed: _isLoading ? null : _signUpWithGoogle,
                          ),
                        ),
                        const SizedBox(height: 16),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const Text('Already have an account? '),
                            TextButton(
                              onPressed: () => context.go('/login'),
                              child: const Text(
                                'Login',
                                style: TextStyle(color: Colors.blue),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
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
