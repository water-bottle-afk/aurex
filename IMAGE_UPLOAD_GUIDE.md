# Image Handling & Asset Upload System

## Overview
The Aurex app uses **Google Drive as the primary image storage** and implements a **server-based upload protocol** for managing marketplace assets.

---

## Image Loading Strategy

### 1. **Google Drive Image Loading**
All images are stored in Google Drive and loaded with **cached network image** for optimal performance.

#### Image URL Handling
```
Original Share URL:
https://drive.google.com/file/d/FILE_ID/view?usp=sharing

Converted to Direct View URL:
https://drive.google.com/uc?export=view&id=FILE_ID

Thumbnail URL (for faster loading in grids):
https://drive.google.com/thumbnail?id=FILE_ID&sz=w200
```

#### Implementation: `GoogleDriveImageLoader`
Located in: `lib/services/google_drive_image_loader.dart`

**Features:**
- Converts share URLs to direct view URLs automatically
- Generates thumbnail URLs for grid displays
- Uses `CachedNetworkImage` for caching and offline support
- Automatic loading indicator while image fetches
- Error widget for failed image loads
- Border radius support for rounded corners

**Usage:**
```dart
GoogleDriveImageLoader.buildCachedImage(
  imageUrl: 'https://drive.google.com/file/d/FILE_ID/view',
  fit: BoxFit.cover,
  borderRadius: BorderRadius.circular(12),
)
```

### 2. **Image Display Locations**

#### Marketplace Grid
- Uses `GoogleDriveImageLoader.buildCachedImage()` 
- Displays cached image with loading spinner
- Fallback error icon on failed load
- Fast loading with thumbnail URLs

#### Asset Details Page
- Uses `GoogleDriveImageLoader.buildCachedImage()` for hero image
- Full-sized image from Google Drive
- Gradient overlay for visual depth
- Smooth transitions

---

## Asset Upload Mechanism

### Architecture

```
User Input (Upload Page)
    ↓
Select/Upload File to Google Drive
    ↓
Get Google Drive URL & File ID
    ↓
Send UPLOAD Protocol to Server
    ↓
Server Registers Asset in Marketplace
    ↓
Asset Visible in Marketplace
```

### Protocol Communication

**Protocol Message Format:**
```
UPLOAD|asset_name|username|google_drive_url|file_type|cost
```

**Example:**
```
UPLOAD|Blockchain Asset|john_doe|https://drive.google.com/uc?export=view&id=ABC123|image|49.99
```

**Server Response:**
```
OK          (Success)
ERR|reason  (Failure with reason)
```

### Upload Flow in Dart

#### Step 1: File Selection (`_pickFile()`)
```dart
Future<void> _pickFile() async {
  final result = await FilePicker.platform.pickFiles(
    type: FileType.image,
    allowMultiple: false,
  );
  
  // File stored in _selectedFile
  // File type extracted and stored in _fileType
}
```

#### Step 2: Upload to Google Drive (`_uploadToGoogleDrive()`)
```dart
Future<String> _uploadToGoogleDrive(File file) async {
  // 1. Read file as bytes
  final bytes = await file.readAsBytes();
  
  // 2. Create multipart request
  final request = http.MultipartRequest('POST', googleAppsScriptUrl);
  
  // 3. Add file bytes to request
  request.files.add(
    http.MultipartFile.fromBytes('file', bytes, filename: assetName)
  );
  
  // 4. Send to Google Apps Script
  final response = await request.send();
  
  // 5. Extract file ID from response
  final fileId = _extractFileId(responseBody);
  
  // 6. Return direct view URL
  return 'https://drive.google.com/uc?export=view&id=$fileId';
}
```

#### Step 3: Register with Server (`_uploadAssetViaServer()`)
```dart
Future<void> _uploadAssetViaServer() async {
  // 1. Validate input (name, file/URL, cost)
  
  // 2. Upload file to Google Drive (if not URL)
  final googleDriveUrl = await _uploadToGoogleDrive(file);
  
  // 3. Send UPLOAD protocol to server
  final result = await client.uploadMarketplaceItem(
    assetName: _assetName,
    username: username,
    googleDriveUrl: googleDriveUrl,
    fileType: _fileType,
    cost: _assetCost,
  );
  
  // 4. Handle server response
  if (result == "success") {
    // Asset registered successfully
    // Update UI and navigate back
  }
}
```

### Client Protocol Method

**File:** `lib/client_class.dart`

```dart
Future<String> uploadMarketplaceItem({
  required String assetName,
  required String username,
  required String googleDriveUrl,
  required String fileType,
  required double cost,
}) async {
  // Send message: UPLOAD|assetName|username|googleDriveUrl|fileType|cost
  final message = "UPLOAD|$assetName|$username|$googleDriveUrl|$fileType|$cost";
  
  await sendMessage(message);
  final response = await receiveMessage();
  
  // Parse response and return "success" or "error"
  if (response.startsWith("OK")) {
    return "success";
  } else {
    return "error";
  }
}
```

---

## Upload Asset Page UI

### Form Fields
1. **Asset Name** - Required
   - Text input with label validation
   - Shown in both Google Drive and marketplace

2. **Description** - Optional
   - Multi-line text input
   - Stored with Google Drive file metadata

3. **Price (USD)** - Required
   - Number input with decimal support
   - Must be > 0
   - Shown in marketplace

4. **File Selection** - Required (if not using URL)
   - File picker for image files
   - Drag-and-drop area
   - Shows selected file name

5. **Google Drive URL** - Alternative (if not selecting file)
   - Paste existing Google Drive URL
   - Automatically converted to direct view URL
   - Disabled if file is selected

### Upload States

#### Initial State
- All fields empty and enabled
- Upload button disabled
- No status messages

#### Validating
- Check all required fields filled
- Validate cost > 0
- Enable upload button if valid

#### Uploading
- Show circular progress indicator
- Display status: "Uploading file to Google Drive..."
- Then: "Registering asset with server..."
- All inputs disabled

#### Success
- Show green success card
- Display asset name
- Auto-navigate back after 2 seconds

#### Error
- Show red error snackbar
- Display error message
- Re-enable inputs for retry

---

## Existing Assets from Google Drive

### How to Add Initial Assets

1. **Create folders in Google Drive:**
   ```
   Aurex Marketplace/
   ├── Leather Jacket/
   ├── Digital Art/
   ├── Software License/
   └── ...
   ```

2. **Upload images to each folder**

3. **Share images and get file IDs**

4. **Add to marketplace server** via the Upload page:
   - Asset Name: "Leather Jacket"
   - Price: 49.99
   - URL: `https://drive.google.com/file/d/FILE_ID/view`
   - Click Upload

5. **Images will appear in marketplace**
   - Cached for fast loading
   - Thumbnail shown in grid
   - Full image in details page

### Direct Database Entry (Alternative)

Instead of uploading via app, server admin can directly insert into marketplace database:

```sql
INSERT INTO marketplace_items (
  asset_name,
  username,
  url,
  file_type,
  cost,
  timestamp
) VALUES (
  'Leather Jacket',
  'admin',
  'https://drive.google.com/uc?export=view&id=ABC123XYZ',
  'image',
  49.99,
  NOW()
);
```

Then the assets will appear when loading marketplace items.

---

## Image Quality & Performance

### Thumbnail vs Full Image

**Thumbnail (Grid Display)**
```
Size: ~200px width
Usage: Marketplace grid cards
Speed: Fast (~100KB)
Quality: Good for thumbnails
URL: https://drive.google.com/thumbnail?id=FILE_ID&sz=w200
```

**Full Image (Details Page)**
```
Size: Original resolution
Usage: Asset details page
Speed: Medium (varies by file)
Quality: Full quality for detailed view
URL: https://drive.google.com/uc?export=view&id=FILE_ID
```

### Caching Strategy

Using `cached_network_image` package:
- Downloaded images cached locally
- Automatic cache invalidation after 30 days
- Offline access to previously loaded images
- Shared cache across app

### File Size Recommendations

**Optimal:**
- Images: PNG/JPG, 500KB - 2MB
- Avoid: BMP, uncompressed files > 5MB
- Recommended resolution: 1200x800px

---

## Error Handling

### Image Load Failures
```dart
// Automatic retry with exponential backoff
// Shows error icon if persistent failure
// User can refresh or re-upload
```

### Upload Failures
```dart
// Network error → Show error message, allow retry
// Server error → Display server error reason
// Google Drive error → Check credentials/quota
```

### File Size Issues
```dart
// Google Drive max: 5TB per file
// No hard limit in app, but recommend < 100MB
// Large files may timeout (add timeout handling)
```

---

## Configuration

### Google Apps Script URL
```dart
const String _googleAppsScriptUrl =
  'https://script.google.com/macros/s/AKfycbzwVFRyAb1d0dXGm2Xmjz8aemXivoAzK2-OWyRmywt4_Sw1IH8g2YmlSlQnoLkPq1a/exec';
```

Replace with your own Google Apps Script deployment URL.

### Server Connection
Ensure server is running and listening on configured host/port (from `config.dart`).

---

## Future Enhancements

1. **Batch Upload**
   - Upload multiple assets at once
   - Progress tracking for each file

2. **Image Optimization**
   - Auto-resize on upload
   - Convert to WebP for smaller size
   - Generate thumbnails server-side

3. **Direct File Upload to Server**
   - Instead of Google Drive
   - Store locally on server
   - Chunked upload for large files

4. **Video Support**
   - Upload and display videos
   - Video thumbnails
   - Streaming playback

5. **CDN Integration**
   - Faster image delivery
   - Global caching
   - Bandwidth optimization

---

## Testing Checklist

✅ Images from Google Drive load in marketplace grid
✅ Thumbnails display correctly and fast
✅ Full images load in asset details page
✅ File picker works and reads file bytes correctly
✅ Upload to Google Drive via Apps Script succeeds
✅ Server receives UPLOAD protocol message
✅ Asset registered in marketplace database
✅ Newly uploaded asset appears in marketplace
✅ Existing 5-10 assets display on startup
✅ Error handling works for failed uploads
✅ Retry mechanism works
✅ Image caching functions properly
✅ Offline image viewing works
✅ URL conversion handles all URL formats
