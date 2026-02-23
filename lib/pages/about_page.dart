import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

class AboutPage extends StatelessWidget {
  const AboutPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('About'),
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/marketplace');
            }
          },
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 16),
            // Title
            Text(
              'About Aurex',
              style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.bold,
                    fontSize: 36,
                  ),
            ),
            const SizedBox(height: 16),
            // Description
            Text(
              'Aurex is a modern marketplace application that connects buyers and sellers.',
              style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                    color: Colors.grey[700],
                    fontSize: 16,
                    height: 1.5,
                  ),
            ),
            const SizedBox(height: 40),
            // Features Section
            Text(
              'Features',
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                    fontSize: 24,
                  ),
            ),
            const SizedBox(height: 20),
            // Feature 1
            _buildFeatureItem(
              context,
              icon: Icons.verified_user,
              title: 'Easy Authentication',
              description: 'Sign up and log in with email or Google',
            ),
            const SizedBox(height: 20),
            // Feature 2
            _buildFeatureItem(
              context,
              icon: Icons.shopping_bag,
              title: 'Browse Marketplace',
              description: 'Discover amazing items from sellers',
            ),
            const SizedBox(height: 20),
            // Feature 3
            _buildFeatureItem(
              context,
              icon: Icons.security,
              title: 'Secure Profile',
              description: 'Manage your account and settings',
            ),
            const SizedBox(height: 40),
            // Version Section
            Text(
              'Version',
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                    fontSize: 24,
                  ),
            ),
            const SizedBox(height: 16),
            Text(
              '1.0.0',
              style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                    fontSize: 18,
                    color: Colors.grey[700],
                  ),
            ),
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }

  Widget _buildFeatureItem(
    BuildContext context, {
    required IconData icon,
    required String title,
    required String description,
  }) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 50,
          height: 50,
          decoration: const BoxDecoration(
            color: Colors.green,
            shape: BoxShape.circle,
          ),
          child: Icon(
            icon,
            color: Colors.white,
            size: 28,
          ),
        ),
        const SizedBox(width: 16),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                    ),
              ),
              const SizedBox(height: 4),
              Text(
                description,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Colors.grey[600],
                      fontSize: 14,
                    ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
