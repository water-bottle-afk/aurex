import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/client_provider.dart';

/// Password Reset Flow:
/// 1. Enter email → Request OTP
/// 2. Enter OTP code (6 digits)
/// 3. Enter new password
/// 4. Confirm success

class PasswordResetPage extends StatefulWidget {
  const PasswordResetPage({super.key});

  @override
  State<PasswordResetPage> createState() => _PasswordResetPageState();
}

class _PasswordResetPageState extends State<PasswordResetPage> {
  int _currentStep = 0; // 0=email, 1=otp, 2=password, 3=success

  // Step 1: Email Entry
  final _emailController = TextEditingController();
  String? _emailError;

  // Step 2: OTP Entry
  final _otpController = TextEditingController();
  String? _otpError;
  int _otpTimeRemaining = 0;

  // Step 3: New Password
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();
  String? _passwordError;
  bool _showPassword = false;

  // General
  bool _isLoading = false;
  String? _generalError;
  String? _successMessage;

  @override
  void dispose() {
    _emailController.dispose();
    _otpController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  /// Step 1: Request OTP via email
  void _requestOTP() async {
    setState(() {
      _emailError = null;
      _generalError = null;
    });

    final email = _emailController.text.trim();

    // Validate email
    if (email.isEmpty) {
      setState(() => _emailError = "Email cannot be empty");
      return;
    }
    if (email.contains('|') || email.contains(' ')) {
      setState(() => _emailError = "Invalid email format");
      return;
    }
    if (!RegExp(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        .hasMatch(email)) {
      setState(() => _emailError = "Invalid email format");
      return;
    }

    setState(() => _isLoading = true);

    try {
      final client = context.read<ClientProvider>().client;
      await client.requestPasswordReset(email);

      setState(() {
        _currentStep = 1;
        _isLoading = false;
        _otpTimeRemaining = 300; // 5 minutes
        _startOTPTimer();
      });
    } catch (e) {
      setState(() {
        _isLoading = false;
        _generalError = "Failed to send OTP: $e";
      });
    }
  }

  /// Start OTP countdown timer
  void _startOTPTimer() {
    Future.doWhile(() async {
      await Future.delayed(const Duration(seconds: 1));
      setState(() => _otpTimeRemaining--);
      return _otpTimeRemaining > 0;
    });
  }

  /// Step 2: Verify OTP
  void _verifyOTP() async {
    setState(() {
      _otpError = null;
      _generalError = null;
    });

    final otp = _otpController.text.trim();

    if (otp.isEmpty) {
      setState(() => _otpError = "OTP cannot be empty");
      return;
    }
    if (otp.length != 6 || !RegExp(r'^[0-9]{6}$').hasMatch(otp)) {
      setState(() => _otpError = "OTP must be 6 digits");
      return;
    }

    setState(() => _isLoading = true);

    try {
      final client = context.read<ClientProvider>().client;
      final email = _emailController.text.trim();
      await client.verifyPasswordResetCode(email, otp);

      setState(() {
        _currentStep = 2;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _isLoading = false;
        _otpError = "Invalid or expired OTP";
        _generalError = e.toString();
      });
    }
  }

  /// Step 3: Update password
  void _updatePassword() async {
    setState(() {
      _passwordError = null;
      _generalError = null;
    });

    final password = _passwordController.text;
    final confirmPassword = _confirmPasswordController.text;

    // Validate passwords
    if (password.isEmpty) {
      setState(() => _passwordError = "Password cannot be empty");
      return;
    }
    if (password.contains('|')) {
      setState(() => _passwordError = "Password cannot contain '|'");
      return;
    }
    if (password.length < 6) {
      setState(() => _passwordError = "Password must be at least 6 characters");
      return;
    }
    if (password != confirmPassword) {
      setState(() => _passwordError = "Passwords do not match");
      return;
    }

    setState(() => _isLoading = true);

    try {
      final client = context.read<ClientProvider>().client;
      final email = _emailController.text.trim();
      await client.updatePassword(email, password);

      setState(() {
        _currentStep = 3;
        _isLoading = false;
        _successMessage = "Password updated successfully!";
      });
    } catch (e) {
      setState(() {
        _isLoading = false;
        _generalError = "Failed to update password: $e";
      });
    }
  }

  /// Build Step 1: Email Entry
  Widget _buildEmailStep() {
    return Column(
      children: [
        const Text(
          "Enter your email",
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 20),
        TextField(
          controller: _emailController,
          decoration: InputDecoration(
            labelText: "Email",
            hintText: "user@example.com",
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
            ),
            errorText: _emailError,
            prefixIcon: const Icon(Icons.email),
          ),
          keyboardType: TextInputType.emailAddress,
        ),
        const SizedBox(height: 20),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _isLoading ? null : _requestOTP,
            child: _isLoading
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text("Send OTP"),
          ),
        ),
      ],
    );
  }

  /// Build Step 2: OTP Entry
  Widget _buildOTPStep() {
    final minutes = _otpTimeRemaining ~/ 60;
    final seconds = _otpTimeRemaining % 60;

    return Column(
      children: [
        const Text(
          "Enter OTP Code",
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 10),
        Text(
          "Code sent to ${_emailController.text}",
          style: const TextStyle(color: Colors.grey),
        ),
        const SizedBox(height: 20),
        TextField(
          controller: _otpController,
          decoration: InputDecoration(
            labelText: "6-digit OTP",
            hintText: "000000",
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
            ),
            errorText: _otpError,
            prefixIcon: const Icon(Icons.security),
          ),
          keyboardType: TextInputType.number,
          maxLength: 6,
        ),
        const SizedBox(height: 10),
        Text(
          "Code expires in ${minutes}m ${seconds}s",
          style: TextStyle(
            color: _otpTimeRemaining < 60 ? Colors.red : Colors.grey,
          ),
        ),
        const SizedBox(height: 20),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _isLoading ? null : _verifyOTP,
            child: _isLoading
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text("Verify OTP"),
          ),
        ),
        const SizedBox(height: 10),
        TextButton(
          onPressed: () => setState(() => _currentStep = 0),
          child: const Text("Back to email"),
        ),
      ],
    );
  }

  /// Build Step 3: New Password
  Widget _buildPasswordStep() {
    return Column(
      children: [
        const Text(
          "Create New Password",
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 20),
        TextField(
          controller: _passwordController,
          obscureText: !_showPassword,
          decoration: InputDecoration(
            labelText: "New Password",
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
            ),
            errorText: _passwordError,
            prefixIcon: const Icon(Icons.lock),
            suffixIcon: IconButton(
              icon: Icon(_showPassword ? Icons.visibility : Icons.visibility_off),
              onPressed: () => setState(() => _showPassword = !_showPassword),
            ),
          ),
        ),
        const SizedBox(height: 15),
        TextField(
          controller: _confirmPasswordController,
          obscureText: !_showPassword,
          decoration: InputDecoration(
            labelText: "Confirm Password",
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
            ),
            prefixIcon: const Icon(Icons.lock),
          ),
        ),
        const SizedBox(height: 20),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _isLoading ? null : _updatePassword,
            child: _isLoading
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text("Update Password"),
          ),
        ),
      ],
    );
  }

  /// Build Step 4: Success
  Widget _buildSuccessStep() {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const Icon(Icons.check_circle, color: Colors.green, size: 80),
        const SizedBox(height: 20),
        const Text(
          "Password Updated!",
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 10),
        Text(_successMessage ?? ""),
        const SizedBox(height: 30),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("Back to Login"),
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Reset Password"),
        centerTitle: true,
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            // Progress indicator
            Row(
              children: [
                _buildProgressDot(0, "Email"),
                _buildProgressDot(1, "OTP"),
                _buildProgressDot(2, "Password"),
                _buildProgressDot(3, "Done"),
              ],
            ),
            const SizedBox(height: 30),
            Expanded(
              child: _currentStep == 0
                  ? _buildEmailStep()
                  : _currentStep == 1
                      ? _buildOTPStep()
                      : _currentStep == 2
                          ? _buildPasswordStep()
                          : _buildSuccessStep(),
            ),
            // Error messages
            if (_generalError != null)
              Padding(
                padding: const EdgeInsets.only(top: 20),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.red[100],
                    border: Border.all(color: Colors.red),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _generalError!,
                    style: const TextStyle(color: Colors.red),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  /// Build progress dot
  Widget _buildProgressDot(int step, String label) {
    final isActive = step <= _currentStep;
    return Expanded(
      child: Column(
        children: [
          Container(
            height: 40,
            width: 40,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: isActive ? Colors.blue : Colors.grey[300],
            ),
            child: Center(
              child: Text(
                "${step + 1}",
                style: TextStyle(
                  color: isActive ? Colors.white : Colors.grey,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
          const SizedBox(height: 5),
          Text(label, style: const TextStyle(fontSize: 12)),
        ],
      ),
    );
  }
}
