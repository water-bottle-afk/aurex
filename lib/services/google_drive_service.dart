import 'dart:io';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:googleapis/drive/v3.dart' as drive;
import 'package:http/http.dart' as http;

/// Google Drive upload service for direct file uploads from Flutter
class GoogleDriveService {
  static const String _googleDriveFolderName = 'Aurex_Marketplace';
  
  late GoogleSignIn _googleSignIn;
  GoogleSignInAccount? _currentUser;
  drive.DriveApi? _driveApi;

  GoogleDriveService() {
    _googleSignIn = GoogleSignIn(
      scopes: [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/drive.file',
      ],
    );
  }

  /// Sign in to Google
  Future<bool> signIn() async {
    try {
      _currentUser = await _googleSignIn.signIn();
      if (_currentUser == null) return false;
      
      // Initialize Drive API
      final auth = await _currentUser!.authentication;
      _driveApi = drive.DriveApi(
        _GoogleHttpClient(auth.accessToken ?? ''),
      );
      
      return true;
    } catch (e) {
      print('❌ Google Sign-In failed: $e');
      return false;
    }
  }

  /// Sign out from Google
  Future<void> signOut() async {
    try {
      await _googleSignIn.signOut();
      _currentUser = null;
      _driveApi = null;
    } catch (e) {
      print('❌ Sign out failed: $e');
    }
  }

  /// Check if user is signed in
  bool isSignedIn() => _currentUser != null;

  /// Get current user email
  String? getCurrentUserEmail() => _currentUser?.email;

  /// Upload file to Google Drive
  /// Returns the direct view URL
  Future<String?> uploadFile(File file, String fileName) async {
    try {
      if (_driveApi == null) {
        print('❌ Not signed in to Google Drive');
        return null;
      }

      // Get or create Aurex_Marketplace folder
      final folderId = await _getOrCreateFolder(_googleDriveFolderName);
      if (folderId == null) {
        print('❌ Failed to create/get folder');
        return null;
      }

      // Create file metadata
      final fileMetadata = drive.File();
      fileMetadata.name = fileName;
      fileMetadata.parents = [folderId];
      fileMetadata.description = 'Uploaded from Aurex Marketplace';

      // Upload file
      print('📤 Uploading $fileName to Google Drive...');
      final response = await _driveApi!.files.create(
        fileMetadata,
        uploadMedia: drive.Media(file.openRead(), await file.length()),
      );

      if (response.id == null) {
        print('❌ Upload failed');
        return null;
      }

      // Set sharing to "anyone with link can view"
      await _setFileSharing(response.id!);

      // Get direct view URL
      final directUrl =
          'https://drive.google.com/uc?export=view&id=${response.id}';
      
      print('✅ Upload successful: $directUrl');
      return directUrl;
    } catch (e) {
      print('❌ Upload error: $e');
      return null;
    }
  }

  /// Get or create Aurex_Marketplace folder in Google Drive
  Future<String?> _getOrCreateFolder(String folderName) async {
    try {
      // Search for existing folder
      final query =
          "name = '$folderName' and mimeType = 'application/vnd.google-apps.folder' and trashed = false";
      
      final found = await _driveApi!.files.list(
        q: query,
        spaces: 'drive',
        pageSize: 1,
      );

      if (found.files != null && found.files!.isNotEmpty) {
        return found.files!.first.id;
      }

      // Create new folder if not found
      print('📁 Creating $folderName folder...');
      final folderMetadata = drive.File();
      folderMetadata.name = folderName;
      folderMetadata.mimeType = 'application/vnd.google-apps.folder';

      final created = await _driveApi!.files.create(folderMetadata);
      
      if (created.id != null) {
        print('✅ Folder created: ${created.id}');
      }
      
      return created.id;
    } catch (e) {
      print('❌ Folder creation error: $e');
      return null;
    }
  }

  /// Set file sharing to "anyone with link can view"
  Future<void> _setFileSharing(String fileId) async {
    try {
      final permission = drive.Permission();
      permission.type = 'anyone';
      permission.role = 'reader';

      await _driveApi!.permissions.create(permission, fileId);
      print('✅ File sharing enabled');
    } catch (e) {
      print('⚠️ Error setting sharing: $e');
      // Non-critical error, continue
    }
  }

  /// Get file preview URL (high quality thumbnail)
  static String getPreviewUrl(String fileId, {int size = 400}) {
    return 'https://drive.google.com/thumbnail?id=$fileId&sz=w$size';
  }

  /// Get direct download URL
  static String getDownloadUrl(String fileId) {
    return 'https://drive.google.com/uc?export=download&id=$fileId';
  }

  /// Get direct view URL (for embedding in Image widgets)
  static String getViewUrl(String fileId) {
    return 'https://drive.google.com/uc?export=view&id=$fileId';
  }
}

/// Custom HTTP client for Google Drive API
class _GoogleHttpClient extends http.BaseClient {
  final String _accessToken;

  _GoogleHttpClient(this._accessToken);

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    request.headers['Authorization'] = 'Bearer $_accessToken';
    return http.Client().send(request);
  }
}
