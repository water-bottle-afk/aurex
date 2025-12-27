import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:http/http.dart' as http;
import '../providers/client_provider.dart';

class UploadAssetPage extends StatefulWidget {
  const UploadAssetPage({super.key});

  @override
  State<UploadAssetPage> createState() => _UploadAssetPageState();
}

class _UploadAssetPageState extends State<UploadAssetPage> {
  bool _isUploading = false;
  String? _uploadedAssetId;
  String? _statusMessage;
  String _assetName = '';

  final String _googleAppsScriptUrl =
      'https://script.google.com/macros/s/AKfycbzwVFRyAb1d0dXGm2Xmjz8aemXivoAzK2-OWyRmywt4_Sw1IH8g2YmlSlQnoLkPq1a/exec';

  Future<void> _uploadAssetToGoogle() async {
    if (_assetName.isEmpty) {
      _showErrorSnackBar('Please enter an asset name');
      return;
    }

    setState(() {
      _isUploading = true;
      _statusMessage = 'Uploading to cloud storage...';
    });

    try {
      final http.MultipartRequest request =
          http.MultipartRequest('POST', Uri.parse(_googleAppsScriptUrl));

      request.fields['name'] = _assetName;
      request.fields['timestamp'] = DateTime.now().toString();

      // In a real implementation, you would add the actual image file here
      // request.files.add(http.MultipartFile.fromBytes(...))

      final http.StreamedResponse response = await request.send();

      if (response.statusCode == 200) {
        final String responseBody = await response.stream.bytesToString();
        print('Google Apps Script Response: $responseBody');

        // Parse response to get asset ID
        final assetId = _parseAssetId(responseBody);

        if (assetId.isNotEmpty) {
          setState(() {
            _uploadedAssetId = assetId;
            _statusMessage = 'Image uploaded successfully!';
          });

          // Send LGAST message to server with asset ID
          await _sendAssetToServer(assetId);
        } else {
          throw Exception('No asset ID in response');
        }
      } else {
        _showErrorSnackBar(
            'Upload failed: ${response.statusCode} ${response.reasonPhrase}');
        setState(() => _isUploading = false);
      }
    } catch (e) {
      _showErrorSnackBar('Upload error: $e');
      setState(() => _isUploading = false);
    }
  }

  String _parseAssetId(String response) {
    try {
      // Try to extract ID from common response formats
      if (response.contains('"id"')) {
        final startIndex = response.indexOf('"id"') + 5;
        final endIndex = response.indexOf('"', startIndex);
        return response.substring(startIndex, endIndex).trim().replaceAll('"', '');
      }
      // If response is just the ID
      return response.trim().replaceAll('"', '');
    } catch (e) {
      print('Error parsing asset ID: $e');
      return '';
    }
  }

  Future<void> _sendAssetToServer(String assetId) async {
    try {
      final clientProvider =
          Provider.of<ClientProvider>(context, listen: false);
      final client = clientProvider.client;

      setState(() {
        _statusMessage = 'Registering asset with blockchain server...';
      });

      final result = await client.logAsset(assetId, _assetName);

      if (result == "success") {
        setState(() {
          _isUploading = false;
          _statusMessage = 'Asset successfully registered on blockchain!';
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
      _showErrorSnackBar('Error registering asset: $e');
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
                crossAxisAlignment: CrossAxisAlignment.center,
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
                    'Upload an image to register on blockchain',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: Colors.white70,
                        ),
                  ),

                  const SizedBox(height: 40),

                  // Asset Name Input
                  TextField(
                    style: const TextStyle(color: Colors.white),
                    decoration: InputDecoration(
                      hintText: 'Enter asset name',
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
                        onPressed: _assetName.isEmpty ? null : _uploadAssetToGoogle,
                        icon: const Icon(Icons.cloud_upload),
                        label: const Text('Upload & Register Asset'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: _assetName.isEmpty
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
                            'Asset ID',
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
                                  fontFamily: 'monospace',
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
