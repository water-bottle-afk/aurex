import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:provider/provider.dart';
import '../providers/user_provider.dart';
import '../services/user_service.dart';
import 'marketplace_page.dart';
import 'profile_page.dart';
import 'about_page.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _currentPageIndex = 0;
  final UserService _userService = UserService();
  final GoogleSignIn _googleSignIn = GoogleSignIn();

  late List<Widget> _pages;

  @override
  void initState() {
    super.initState();
    _pages = [
      const MarketplacePage(),
      const ProfilePage(),
      const AboutPage(),
    ];
  }

  Future<void> _logout() async {
    // Clear session
    await _userService.clearSession();
    await _googleSignIn.signOut();

    if (mounted) {
      // Clear user from provider
      Provider.of<UserProvider>(context, listen: false).setUser(null);

      // Navigate to login
      context.go('/login');

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Logged out successfully')),
      );
    }
  }

  void _showMenu(BuildContext context) {
    showModalBottomSheet(
      context: context,
      builder: (BuildContext context) {
        return Container(
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(height: 16),
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey[300],
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(height: 24),
              _buildMenuItem(
                icon: Icons.shopping_bag,
                label: 'Marketplace',
                onTap: () {
                  Navigator.pop(context);
                  setState(() => _currentPageIndex = 0);
                },
              ),
              _buildMenuItem(
                icon: Icons.person,
                label: 'Profile',
                onTap: () {
                  Navigator.pop(context);
                  setState(() => _currentPageIndex = 1);
                },
              ),
              _buildMenuItem(
                icon: Icons.info,
                label: 'About',
                onTap: () {
                  Navigator.pop(context);
                  setState(() => _currentPageIndex = 2);
                },
              ),
              const Divider(),
              _buildMenuItem(
                icon: Icons.logout,
                label: 'Logout',
                onTap: () {
                  Navigator.pop(context);
                  _logout();
                },
                isDestructive: true,
              ),
              const SizedBox(height: 24),
            ],
          ),
        );
      },
    );
  }

  Widget _buildMenuItem({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
    bool isDestructive = false,
  }) {
    return ListTile(
      leading: Icon(
        icon,
        color: isDestructive ? Colors.red : Colors.black,
      ),
      title: Text(
        label,
        style: TextStyle(
          color: isDestructive ? Colors.red : Colors.black,
          fontWeight: FontWeight.w500,
        ),
      ),
      onTap: onTap,
    );
  }

  @override
  Widget build(BuildContext context) {
    final userProvider = Provider.of<UserProvider>(context);
    final user = userProvider.user;

    return Scaffold(
      // Top Profile Section
      appBar: AppBar(
        elevation: 0,
        backgroundColor: Colors.white,
        toolbarHeight: 100,
        leading: const SizedBox.shrink(),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16.0),
            child: IconButton(
              icon: const Icon(Icons.menu, color: Colors.black, size: 28),
              onPressed: () => _showMenu(context),
            ),
          ),
        ],
        title: Row(
          children: [
            CircleAvatar(
              radius: 30,
              backgroundImage: user?.photoURL != null
                  ? NetworkImage(user!.photoURL!)
                  : null,
              child: user?.photoURL == null
                  ? const Icon(Icons.person, size: 30)
                  : null,
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    user?.displayName ?? 'Guest',
                    style: const TextStyle(
                      color: Colors.black,
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                  Text(
                    user?.email ?? 'Not logged in',
                    style: const TextStyle(
                      color: Colors.grey,
                      fontSize: 12,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
          ],
        ),
        centerTitle: false,
      ),
      body: _pages[_currentPageIndex],
    );
  }
}
