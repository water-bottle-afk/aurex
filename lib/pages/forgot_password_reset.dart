import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:go_router/go_router.dart';
import '../providers/client_provider.dart';

class ForgotPasswordFlow extends StatefulWidget {
  const ForgotPasswordFlow({super.key});

  @override
  State<ForgotPasswordFlow> createState() => _ForgotPasswordFlowState();
}

class _ForgotPasswordFlowState extends State<ForgotPasswordFlow> {
  late PageController _pageController;
  final _emailController = TextEditingController();
  final _codeController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  bool _isLoading = false;
  String? _devOtp;

  @override
  void initState() {
    super.initState();
    _pageController = PageController();
  }

  @override
  void dispose() {
    _pageController.dispose();
    _emailController.dispose();
    _codeController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  Future<void> _requestResetCode() async {
    if (_emailController.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter your email')),
      );
      return;
    }

    setState(() => _isLoading = true);

    try {
      final clientProvider = context.read<ClientProvider>();
      if (!clientProvider.isConnected) {
        final connected = await clientProvider.initializeConnection();
        if (!connected) {
          throw Exception('Server connection failed');
        }
      }
      final result = await clientProvider.client.requestPasswordReset(_emailController.text);

      if (mounted) {
        setState(() => _isLoading = false);
        if (result.startsWith("success")) {
          if (result.contains(':')) {
            final parts = result.split(':');
            if (parts.length == 2 && parts[1].trim().isNotEmpty) {
              _devOtp = parts[1].trim();
              _codeController.text = _devOtp!;
            }
          }
          _pageController.nextPage(duration: const Duration(milliseconds: 300), curve: Curves.easeInOut);
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e')),
        );
      }
    }
  }

  Future<void> _verifyResetCode() async {
    if (_codeController.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter the code')),
      );
      return;
    }

    setState(() => _isLoading = true);

    try {
      final clientProvider = context.read<ClientProvider>();
      if (!clientProvider.isConnected) {
        final connected = await clientProvider.initializeConnection();
        if (!connected) {
          throw Exception('Server connection failed');
        }
      }
      final result = await clientProvider.client.verifyPasswordResetCode(
        _emailController.text,
        _codeController.text,
      );

      if (mounted) {
        setState(() => _isLoading = false);
        if (result == "success") {
          _pageController.nextPage(duration: const Duration(milliseconds: 300), curve: Curves.easeInOut);
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e')),
        );
      }
    }
  }

  Future<void> _resetPassword() async {
    if (_passwordController.text.isEmpty || _confirmPasswordController.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter both passwords')),
      );
      return;
    }

    if (_passwordController.text != _confirmPasswordController.text) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Passwords do not match')),
      );
      return;
    }

    if (_passwordController.text.length < 6) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Password must be at least 6 characters')),
      );
      return;
    }

    setState(() => _isLoading = true);

    try {
      final clientProvider = context.read<ClientProvider>();
      if (!clientProvider.isConnected) {
        final connected = await clientProvider.initializeConnection();
        if (!connected) {
          throw Exception('Server connection failed');
        }
      }
      final result = await clientProvider.client.updatePassword(
        _emailController.text.trim(),
        _passwordController.text,
      );

      if (!mounted) return;
      if (result == "success") {
        showDialog(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Success!'),
            content: const Text('Your password has been reset. Please log in with your new password.'),
            actions: [
              TextButton(
                onPressed: () {
                  Navigator.pop(context);
                  Navigator.pop(context); // Go back to login
                },
                child: const Text('OK'),
              ),
            ],
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Password reset failed. Please try again.')),
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Reset Password'),
        centerTitle: true,
        backgroundColor: Colors.blue[700],
        foregroundColor: Colors.white,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/login');
            }
          },
        ),
      ),
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              Colors.blue.shade700,
              Colors.blue.shade900,
            ],
          ),
        ),
        child: SafeArea(
          child: PageView(
            controller: _pageController,
            physics: const NeverScrollableScrollPhysics(),
            children: [
              _buildEmailStep(),
              _buildCodeStep(),
              _buildPasswordStep(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildEmailStep() {
    return _wrapStepContent(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 20),
          Text(
            'Enter your email',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          Text(
            'We\'ll send a reset code to your email',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Colors.grey),
          ),
          const SizedBox(height: 32),
          TextFormField(
            controller: _emailController,
            keyboardType: TextInputType.emailAddress,
            decoration: InputDecoration(
              labelText: 'Email',
              hintText: 'you@example.com',
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
              prefixIcon: const Icon(Icons.email),
            ),
          ),
          const SizedBox(height: 32),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _isLoading ? null : _requestResetCode,
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
              ),
              child: Text(_isLoading ? 'Sending...' : 'Send Code'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCodeStep() {
    return _wrapStepContent(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 20),
          Text(
            'Enter verification code',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          if (_devOtp != null) ...[
            const SizedBox(height: 8),
            Text(
              'Dev OTP: $_devOtp',
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: Colors.orange[700]),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            'Check your email for the 6-digit code',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Colors.grey),
          ),
          const SizedBox(height: 32),
          TextFormField(
            controller: _codeController,
            keyboardType: TextInputType.number,
            maxLength: 6,
            decoration: InputDecoration(
              labelText: 'Verification Code',
              hintText: '000000',
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
              prefixIcon: const Icon(Icons.confirmation_number),
            ),
          ),
          const SizedBox(height: 32),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _isLoading ? null : _verifyResetCode,
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
              ),
              child: Text(_isLoading ? 'Verifying...' : 'Verify Code'),
            ),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              onPressed: _isLoading ? null : () {
                _pageController.previousPage(duration: const Duration(milliseconds: 300), curve: Curves.easeInOut);
              },
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
              ),
              child: const Text('Back'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPasswordStep() {
    return _wrapStepContent(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 20),
          Text(
            'Create new password',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 32),
          TextFormField(
            controller: _passwordController,
            obscureText: true,
            decoration: InputDecoration(
              labelText: 'New Password',
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
              prefixIcon: const Icon(Icons.lock),
            ),
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: _confirmPasswordController,
            obscureText: true,
            decoration: InputDecoration(
              labelText: 'Confirm Password',
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
              prefixIcon: const Icon(Icons.lock),
            ),
          ),
          const SizedBox(height: 32),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _isLoading ? null : _resetPassword,
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
                backgroundColor: Colors.green,
              ),
              child: Text(_isLoading ? 'Resetting...' : 'Reset Password'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _wrapStepContent(Widget child) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Card(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: child,
          ),
        ),
      ),
    );
  }
}
