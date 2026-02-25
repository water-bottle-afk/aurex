import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'dart:io';
import 'package:file_picker/file_picker.dart';
import '../providers/client_provider.dart';
import '../providers/user_provider.dart';

class UploadAssetPage extends StatefulWidget {
  const UploadAssetPage({super.key});

  @override
  State<UploadAssetPage> createState() => _UploadAssetPageState();
}

class _UploadAssetPageState extends State<UploadAssetPage> {
  static const int _alpha05 = 13;
  static const int _alpha10 = 26;
  static const int _alpha20 = 51;
  static const int _alpha30 = 77;
  bool _isUploading = false;
  String? _uploadedAssetId;
  String? _statusMessage;
  String _assetName = '';
  String _assetDescription = '';
  double _assetCost = 0.0;
  File? _selectedFile;
  String _fileType = 'jpg';

  /// Pick a file from device and get it ready for upload
  Future<void> _pickFile() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['jpg', 'jpeg', 'png'],
        allowMultiple: false,
      );

      if (result != null && result.files.single.path != null) {
        final extension = result.files.single.extension?.toLowerCase();
        if (extension != 'jpg' && extension != 'jpeg' && extension != 'png') {
          _showErrorSnackBar('Only JPG and PNG images are supported');
          return;
        }

        setState(() {
          _selectedFile = File(result.files.single.path!);
          _fileType = extension == 'jpeg' ? 'jpg' : (extension ?? 'jpg');
          _statusMessage = 'File selected: ${result.files.single.name}';
        });
      }
    } catch (e) {
      _showErrorSnackBar('Error picking file: $e');
    }
  }

  /// Upload file to server (chunked) and register on marketplace
  Future<void> _uploadAssetViaServer() async {
    // Validation
    if (_assetName.isEmpty) {
      _showErrorSnackBar('Please enter an asset name');
      return;
    }
    if (_selectedFile == null) {
      _showErrorSnackBar('Please select a file');
      return;
    }
    if (_assetCost <= 0) {
      _showErrorSnackBar('Please enter a valid cost (> 0)');
      return;
    }

    setState(() {
      _isUploading = true;
      _statusMessage = 'Preparing upload...';
    });

    try {
      final userProvider = Provider.of<UserProvider>(context, listen: false);
      final username = userProvider.username;

      // Upload file to server via chunked protocol
      setState(() {
        _statusMessage = 'Uploading file to server...';
      });

      final clientProvider = Provider.of<ClientProvider>(context, listen: false);
      final client = clientProvider.client;

      final result = await client.uploadMarketplaceItemChunked(
        file: _selectedFile!,
        assetName: _assetName,
        description: _assetDescription,
        username: username,
        fileType: _fileType,
        cost: _assetCost,
      );

      if (result == "success") {
        setState(() {
          _isUploading = false;
          _statusMessage = '✅ Asset successfully registered on marketplace!';
          _uploadedAssetId = _assetName; // Use asset name as ID display
        });

        _showSuccessSnackBar('Asset uploaded and registered successfully!');

        // Clear form after successful upload
        Future.delayed(const Duration(seconds: 2), () {
          if (mounted) {
            Navigator.of(context).pop();
          }
        });
      } else {
        throw Exception('Server returned: $result');
      }
    } catch (e) {
      _showErrorSnackBar('Error uploading asset: $e');
      setState(() => _isUploading = false);
    }
  }

  void _showErrorSnackBar(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.red.shade600,
        duration: const Duration(seconds: 3),
      ),
    );
  }

  void _showSuccessSnackBar(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.green.shade600,
        duration: const Duration(seconds: 3),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Upload Asset'),
        elevation: 0,
        backgroundColor: Colors.blue.shade700,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            Navigator.of(context).maybePop();
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
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Title Section
                  const SizedBox(height: 20),
                  Text(
                    'Create New Asset',
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Upload an image and register on marketplace',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: Colors.white70,
                        ),
                  ),

                  const SizedBox(height: 40),

                  // Asset Name Input
                  Text(
                    'Asset Name',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Colors.white70,
                          fontWeight: FontWeight.w600,
                        ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    style: const TextStyle(color: Colors.white),
                    decoration: InputDecoration(
                      hintText: 'e.g., Blockchain Asset',
                      hintStyle: const TextStyle(color: Colors.white60),
                      filled: true,
                      fillColor: Colors.white.withAlpha(_alpha10),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withAlpha(_alpha30),
                        ),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withAlpha(_alpha30),
                        ),
                      ),
                      prefixIcon: const Icon(
                        Icons.label,
                        color: Colors.white60,
                      ),
                    ),
                    onChanged: (value) {
                      setState(() => _assetName = value);
                    },
                  ),

                  const SizedBox(height: 24),

                  // Asset Description Input
                  Text(
                    'Description',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Colors.white70,
                          fontWeight: FontWeight.w600,
                        ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    style: const TextStyle(color: Colors.white),
                    maxLines: 3,
                    decoration: InputDecoration(
                      hintText: 'Describe your asset...',
                      hintStyle: const TextStyle(color: Colors.white60),
                      filled: true,
                      fillColor: Colors.white.withAlpha(_alpha10),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withAlpha(_alpha30),
                        ),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withAlpha(_alpha30),
                        ),
                      ),
                      prefixIcon: const Icon(
                        Icons.description,
                        color: Colors.white60,
                      ),
                    ),
                    onChanged: (value) {
                      setState(() => _assetDescription = value);
                    },
                  ),

                  const SizedBox(height: 24),

                  // Cost Input
                  Text(
                    'Price (USD)',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Colors.white70,
                          fontWeight: FontWeight.w600,
                        ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    style: const TextStyle(color: Colors.white),
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(
                      hintText: 'Enter price',
                      hintStyle: const TextStyle(color: Colors.white60),
                      filled: true,
                      fillColor: Colors.white.withAlpha(_alpha10),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withAlpha(_alpha30),
                        ),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withAlpha(_alpha30),
                        ),
                      ),
                      prefixIcon: const Icon(
                        Icons.attach_money,
                        color: Colors.white60,
                      ),
                    ),
                    onChanged: (value) {
                      setState(() {
                        _assetCost = double.tryParse(value) ?? 0.0;
                      });
                    },
                  ),

                  const SizedBox(height: 24),

                  // File Selection Section
                  Text(
                    'Upload Image (JPG/PNG)',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Colors.white70,
                          fontWeight: FontWeight.w600,
                        ),
                  ),
                  const SizedBox(height: 8),
                  if (_selectedFile == null)
                    GestureDetector(
                      onTap: _isUploading ? null : _pickFile,
                      child: Container(
                        padding: const EdgeInsets.all(24),
                        decoration: BoxDecoration(
                          border: Border.all(
                            color: Colors.white.withAlpha(_alpha30),
                            style: BorderStyle.solid,
                            width: 2,
                          ),
                          borderRadius: BorderRadius.circular(12),
                          color: Colors.white.withAlpha(_alpha05),
                        ),
                        child: Column(
                          children: [
                            const Icon(
                              Icons.cloud_upload_outlined,
                              size: 48,
                              color: Colors.white70,
                            ),
                            const SizedBox(height: 12),
                            Text(
                              'Tap to select image',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodyMedium
                                  ?.copyWith(
                                    color: Colors.white70,
                                    fontWeight: FontWeight.w600,
                                  ),
                            ),
                            const SizedBox(height: 4),
                          ],
                        ),
                      ),
                    )
                  else
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.green.shade900.withAlpha(_alpha30),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: Colors.green.shade400,
                        ),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            Icons.check_circle,
                            color: Colors.green.shade400,
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              'File: ${_selectedFile!.path.split('/').last}',
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 13,
                              ),
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                          GestureDetector(
                            onTap: () {
                              setState(() => _selectedFile = null);
                            },
                            child: const Icon(
                              Icons.close,
                              color: Colors.white70,
                              size: 20,
                            ),
                          ),
                        ],
                      ),
                    ),

                  const SizedBox(height: 30),

                  // Upload Progress
                  if (_isUploading) ...[
                    Column(
                      children: [
                        const CircularProgressIndicator(
                          valueColor:
                              AlwaysStoppedAnimation<Color>(Colors.white),
                        ),
                        const SizedBox(height: 16),
                        Text(
                          _statusMessage ?? 'Processing...',
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 14,
                          ),
                        ),
                      ],
                    ),
                  ],

                  // Status Message
                  if (_statusMessage != null && !_isUploading) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: _uploadedAssetId != null
                            ? Colors.green.shade400.withAlpha(_alpha20)
                            : Colors.orange.shade400.withAlpha(_alpha20),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(
                          color: _uploadedAssetId != null
                              ? Colors.green.shade400
                              : Colors.orange.shade400,
                        ),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            _uploadedAssetId != null
                                ? Icons.check_circle
                                : Icons.info,
                            color: _uploadedAssetId != null
                                ? Colors.green.shade400
                                : Colors.orange.shade400,
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              _statusMessage!,
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 13,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 30),
                  ],

                  // Upload Button
                  if (!_isUploading)
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: ElevatedButton.icon(
                        onPressed: (_assetName.isEmpty ||
                                (_selectedFile == null) ||
                                _assetCost <= 0)
                            ? null
                            : _uploadAssetViaServer,
                        icon: const Icon(Icons.cloud_upload),
                        label: const Text('Upload & Register Asset'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: (_assetName.isEmpty ||
                                  (_selectedFile == null) ||
                                  _assetCost <= 0)
                              ? Colors.grey.shade400
                              : Colors.white,
                          foregroundColor: Colors.blue.shade700,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                        ),
                      ),
                    ),

                  // Success State
                  if (_uploadedAssetId != null && !_isUploading) ...[
                    const SizedBox(height: 24),
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: Colors.green.shade900.withAlpha(_alpha30),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: Colors.green.shade400,
                        ),
                      ),
                      child: Column(
                        children: [
                          Icon(
                            Icons.verified_user,
                            size: 48,
                            color: Colors.green.shade400,
                          ),
                          const SizedBox(height: 12),
                          Text(
                            'Asset Registered',
                            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                  color: Colors.white70,
                                ),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            _uploadedAssetId!,
                            textAlign: TextAlign.center,
                            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                  color: Colors.green.shade300,
                                  fontWeight: FontWeight.bold,
                                ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
