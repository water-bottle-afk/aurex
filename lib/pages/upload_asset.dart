import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:http/http.dart' as http;
import 'dart:io';
import 'package:file_picker/file_picker.dart';
import '../providers/client_provider.dart';
import '../providers/user_provider.dart';
import '../utils/app_logger.dart';

class UploadAssetPage extends StatefulWidget {
  const UploadAssetPage({super.key});

  @override
  State<UploadAssetPage> createState() => _UploadAssetPageState();
}

class _UploadAssetPageState extends State<UploadAssetPage> {
  final AppLogger _log = AppLogger.get('upload_asset.dart');
  bool _isUploading = false;
  String? _uploadedAssetId;
  String? _statusMessage;
  String _assetName = '';
  String _assetDescription = '';
  double _assetCost = 0.0;
  String? _googleDriveUrl;
  File? _selectedFile;
  String _fileType = 'image';

  final String _googleAppsScriptUrl =
      'https://script.google.com/macros/s/AKfycbzwVFRyAb1d0dXGm2Xmjz8aemXivoAzK2-OWyRmywt4_Sw1IH8g2YmlSlQnoLkPq1a/exec';

  /// Pick a file from device and get it ready for upload
  Future<void> _pickFile() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.image,
        allowMultiple: false,
      );

      if (result != null && result.files.single.path != null) {
        setState(() {
          _selectedFile = File(result.files.single.path!);
          _fileType = result.files.single.extension ?? 'image';
          _statusMessage = 'File selected: ${result.files.single.name}';
        });
      }
    } catch (e) {
      _showErrorSnackBar('Error picking file: $e');
    }
  }

  /// Upload file to Google Drive via Apps Script, then register with server
  Future<void> _uploadAssetViaServer() async {
    // Validation
    if (_assetName.isEmpty) {
      _showErrorSnackBar('Please enter an asset name');
      return;
    }
    if (_selectedFile == null && _googleDriveUrl == null) {
      _showErrorSnackBar('Please select a file or enter Google Drive URL');
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
      
      String googleDriveUrl = _googleDriveUrl ?? '';

      // If file was selected, upload to Google Drive first
      if (_selectedFile != null && _googleDriveUrl == null) {
        setState(() {
          _statusMessage = 'Uploading file to Google Drive...';
        });

        googleDriveUrl = await _uploadToGoogleDrive(_selectedFile!);
        if (googleDriveUrl.isEmpty) {
          throw Exception('Failed to upload file to Google Drive');
        }

        setState(() {
          _googleDriveUrl = googleDriveUrl;
          _statusMessage = 'File uploaded to Google Drive';
        });
      }

      // Now register with marketplace server via protocol
      setState(() {
        _statusMessage = 'Registering asset with server...';
      });

      final clientProvider = Provider.of<ClientProvider>(context, listen: false);
      final client = clientProvider.client;

      // Send UPLOAD protocol message to server
      // UPLOAD|asset_name|username|google_drive_url|file_type|cost
      final result = await client.uploadMarketplaceItem(
        assetName: _assetName,
        username: username,
        googleDriveUrl: googleDriveUrl,
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

  /// Upload file to Google Drive and return the direct view URL
  Future<String> _uploadToGoogleDrive(File file) async {
    try {
      final http.MultipartRequest request =
          http.MultipartRequest('POST', Uri.parse(_googleAppsScriptUrl));

      request.fields['name'] = _assetName;
      request.fields['description'] = _assetDescription;
      request.fields['timestamp'] = DateTime.now().toString();

      // Read file as bytes
      final bytes = await file.readAsBytes();
      request.files.add(
        http.MultipartFile.fromBytes(
          'file',
          bytes,
          filename: _assetName,
        ),
      );

      final http.StreamedResponse response = await request.send();

      if (response.statusCode == 200) {
        final responseBody = await response.stream.bytesToString();
        _log.info('Google Apps Script Response: $responseBody');

        // Extract Google Drive file ID from response
        final fileId = _extractFileId(responseBody);
        if (fileId.isEmpty) {
          throw Exception('Could not extract file ID from response');
        }

        // Return direct view URL (uses thumbnail for faster load)
        return 'https://drive.google.com/uc?export=view&id=$fileId';
      } else {
        throw Exception(
          'Google Drive upload failed: ${response.statusCode} ${response.reasonPhrase}',
        );
      }
    } catch (e) {
      _log.error('Error uploading to Google Drive: $e');
      rethrow;
    }
  }

  /// Extract file ID from Google Apps Script response
  String _extractFileId(String response) {
    try {
      // Handle JSON response format
      if (response.contains('"id"')) {
        final startIndex = response.indexOf('"id"') + 5;
        final endIndex = response.indexOf('"', startIndex);
        return response.substring(startIndex, endIndex).trim().replaceAll('"', '');
      }
      // If response is just the ID
      return response.trim().replaceAll('"', '');
    } catch (e) {
      _log.error('Error extracting file ID: $e');
      return '';
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
                      fillColor: Colors.white.withOpacity(0.1),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withOpacity(0.3),
                        ),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withOpacity(0.3),
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
                      fillColor: Colors.white.withOpacity(0.1),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withOpacity(0.3),
                        ),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withOpacity(0.3),
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
                      fillColor: Colors.white.withOpacity(0.1),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withOpacity(0.3),
                        ),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withOpacity(0.3),
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
                    'Upload Image',
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
                            color: Colors.white.withOpacity(0.3),
                            style: BorderStyle.solid,
                            width: 2,
                          ),
                          borderRadius: BorderRadius.circular(12),
                          color: Colors.white.withOpacity(0.05),
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
                            Text(
                              'or paste Google Drive URL below',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(
                                    color: Colors.white54,
                                  ),
                            ),
                          ],
                        ),
                      ),
                    )
                  else
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.green.shade900.withOpacity(0.3),
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

                  const SizedBox(height: 24),

                  // Google Drive URL Alternative
                  Text(
                    'Or paste Google Drive URL',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Colors.white70,
                          fontWeight: FontWeight.w600,
                        ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    style: const TextStyle(color: Colors.white),
                    enabled: !_isUploading && _selectedFile == null,
                    decoration: InputDecoration(
                      hintText: 'https://drive.google.com/...',
                      hintStyle: const TextStyle(color: Colors.white60),
                      filled: true,
                      fillColor: Colors.white.withOpacity(0.1),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withOpacity(0.3),
                        ),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: Colors.white.withOpacity(0.3),
                        ),
                      ),
                      prefixIcon: const Icon(
                        Icons.link,
                        color: Colors.white60,
                      ),
                    ),
                    onChanged: (value) {
                      setState(() => _googleDriveUrl = value.isEmpty ? null : value);
                    },
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
                            ? Colors.green.shade400.withOpacity(0.2)
                            : Colors.orange.shade400.withOpacity(0.2),
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
                                (_selectedFile == null && _googleDriveUrl == null) ||
                                _assetCost <= 0)
                            ? null
                            : _uploadAssetViaServer,
                        icon: const Icon(Icons.cloud_upload),
                        label: const Text('Upload & Register Asset'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: (_assetName.isEmpty ||
                                  (_selectedFile == null && _googleDriveUrl == null) ||
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
                        color: Colors.green.shade900.withOpacity(0.3),
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
