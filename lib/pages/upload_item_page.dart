import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'dart:io';
import '../services/google_drive_service.dart';

/// Upload/Sell Page - Direct upload to Google Drive from phone
class UploadItemPage extends StatefulWidget {
  const UploadItemPage({super.key});

  @override
  State<UploadItemPage> createState() => _UploadItemPageState();
}

class _UploadItemPageState extends State<UploadItemPage> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _priceController = TextEditingController();
  final _descriptionController = TextEditingController();

  late GoogleDriveService _googleDriveService;
  File? _selectedFile;
  String? _selectedFileType;
  String? _googleDriveUrl;
  bool _isUploading = false;
  bool _isAuthenticatingGoogle = false;

  @override
  void initState() {
    super.initState();
    _googleDriveService = GoogleDriveService();
  }

  @override
  void dispose() {
    _nameController.dispose();
    _priceController.dispose();
    _descriptionController.dispose();
    super.dispose();
  }

  Future<void> _authenticateGoogle() async {
    setState(() => _isAuthenticatingGoogle = true);
    final success = await _googleDriveService.signIn();
    if (mounted) {
      setState(() => _isAuthenticatingGoogle = false);
      if (success) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Signed in as ${_googleDriveService.getCurrentUserEmail()}'),
            backgroundColor: Colors.green,
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Google Sign-In failed'), backgroundColor: Colors.red),
        );
      }
    }
  }

  Future<void> _selectFile() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.image,
        allowedExtensions: ['jpg', 'jpeg', 'png'],
      );

      if (result != null && result.files.single.path != null) {
        final file = File(result.files.single.path!);
        final extension = result.files.single.extension?.toLowerCase();

        if (extension == 'jpg' || extension == 'jpeg' || extension == 'png') {
          setState(() {
            _selectedFile = file;
            _selectedFileType = extension == 'jpeg' ? 'jpg' : extension;
          });
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e')),
        );
      }
    }
  }

  Future<void> _uploadToGoogleDrive() async {
    if (_selectedFile == null || !_googleDriveService.isSignedIn()) return;

    setState(() => _isUploading = true);

    final fileName = _nameController.text.isEmpty
        ? _selectedFile!.path.split('/').last
        : '${_nameController.text}.$_selectedFileType';

    final url = await _googleDriveService.uploadFile(_selectedFile!, fileName);

    if (mounted) {
      setState(() => _isUploading = false);
      if (url != null) {
        setState(() => _googleDriveUrl = url);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('✅ Uploaded to Google Drive!'), backgroundColor: Colors.green),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Upload failed'), backgroundColor: Colors.red),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Sell on Marketplace'), centerTitle: true, elevation: 0),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Google Sign-In
              if (!_googleDriveService.isSignedIn()) ...[
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.amber[50],
                    border: Border.all(color: Colors.amber[300]!),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.warning, color: Colors.amber[700]),
                          const SizedBox(width: 12),
                          const Expanded(child: Text('Sign in to Google to upload')),
                        ],
                      ),
                      const SizedBox(height: 12),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          onPressed: _isAuthenticatingGoogle ? null : _authenticateGoogle,
                          icon: const Icon(Icons.account_circle),
                          label: Text(_isAuthenticatingGoogle ? 'Signing in...' : 'Sign in with Google'),
                          style: ElevatedButton.styleFrom(backgroundColor: Colors.blue),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
              ] else ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.green[50],
                    border: Border.all(color: Colors.green[300]!),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.check_circle, color: Colors.green[700]),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('Signed in', style: TextStyle(fontWeight: FontWeight.bold)),
                            Text(_googleDriveService.getCurrentUserEmail() ?? '', style: const TextStyle(fontSize: 12)),
                          ],
                        ),
                      ),
                      TextButton(
                        onPressed: () async {
                          await _googleDriveService.signOut();
                          setState(() {});
                        },
                        child: const Text('Sign out'),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
              ],

              // File Selection
              Text('Upload Image', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 12),
              InkWell(
                onTap: _isUploading || !_googleDriveService.isSignedIn() ? null : _selectFile,
                child: Container(
                  width: double.infinity,
                  height: 200,
                  decoration: BoxDecoration(
                    border: Border.all(color: _selectedFile != null ? Colors.green : Colors.grey[300]!, width: 2),
                    borderRadius: BorderRadius.circular(12),
                    color: _selectedFile != null ? Colors.green[50] : Colors.grey[50],
                  ),
                  child: Center(
                    child: _selectedFile == null
                        ? Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.cloud_upload_outlined, size: 48, color: Colors.grey[400]),
                              const SizedBox(height: 8),
                              Text('Tap to select image', style: TextStyle(color: Colors.grey[600])),
                            ],
                          )
                        : Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              const Icon(Icons.check_circle, size: 48, color: Colors.green),
                              const SizedBox(height: 8),
                              Text(_selectedFile!.path.split('/').last, style: const TextStyle(fontWeight: FontWeight.bold), overflow: TextOverflow.ellipsis),
                            ],
                          ),
                  ),
                ),
              ),
              const SizedBox(height: 24),

              // Asset Name
              Text('Asset Name', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              TextFormField(
                controller: _nameController,
                decoration: InputDecoration(
                  hintText: 'e.g., Beautiful Sunset Photo',
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                  prefixIcon: const Icon(Icons.label),
                ),
                validator: (value) => (value?.isEmpty ?? true) ? 'Please enter asset name' : null,
              ),
              const SizedBox(height: 16),

              // Price
              Text('Price (USD)', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              TextFormField(
                controller: _priceController,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  hintText: '0.00',
                  prefixText: '\$ ',
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                  prefixIcon: const Icon(Icons.attach_money),
                ),
                validator: (value) {
                  if (value?.isEmpty ?? true) return 'Please enter price';
                  if (double.tryParse(value!) == null) return 'Invalid price';
                  return null;
                },
              ),
              const SizedBox(height: 24),

              // Upload Button
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: _isUploading || _selectedFile == null ? null : _uploadToGoogleDrive,
                  icon: const Icon(Icons.cloud_upload),
                  label: Text(_isUploading ? 'Uploading...' : 'Upload to Google Drive'),
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    backgroundColor: Colors.blue,
                  ),
                ),
              ),

              // Success
              if (_googleDriveUrl != null) ...[
                const SizedBox(height: 16),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.green[50],
                    border: Border.all(color: Colors.green[300]!),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.check, color: Colors.green[700]),
                      const SizedBox(width: 8),
                      const Expanded(child: Text('Image ready to list')),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: () {
                      if (!_formKey.currentState!.validate()) return;
                      showDialog(
                        context: context,
                        builder: (context) => AlertDialog(
                          title: const Text('Item Listed!'),
                          content: Text('"${_nameController.text}" is now on marketplace!'),
                          actions: [
                            TextButton(
                              onPressed: () {
                                Navigator.pop(context);
                                Navigator.pop(context);
                              },
                              child: const Text('Done'),
                            ),
                          ],
                        ),
                      );
                    },
                    icon: const Icon(Icons.shopping_bag),
                    label: const Text('List on Marketplace'),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      backgroundColor: Colors.green,
                    ),
                  ),
                ),
              ],

              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _isUploading ? null : () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                  label: const Text('Cancel'),
                  style: OutlinedButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
