# Aurex App - Image & Upload Implementation

## Summary of Implementation

### ✅ Image Loading Strategy

**The app uses FULL RESOLUTION images, not thumbnails**

- **Image Source**: Google Drive storage
- **Loading Method**: Direct view URLs with full resolution
  - Format: `https://drive.google.com/uc?export=view&id=FILE_ID`
  - This provides full-quality images for the marketplace
- **Caching**: Implemented via `cached_network_image` package for performance
- **Fallback**: Error handling for missing/broken image URLs

**Why full images vs thumbnails?**
- Full images provide better visual quality in the marketplace
- User experience is improved with high-quality assets
- Google Drive's direct view is fast enough for most connections
- Thumbnail option exists (`getThumbnailUrl`) but not used by default

---

### ✅ Asset Upload Flow (Dart)

**Complete upload pipeline via Dart (NO external Python needed)**

#### Step 1: File Selection
```dart
_pickFile() → User selects image from device
  ↓
File is loaded into memory as bytes
```

#### Step 2: Upload to Google Drive
```dart
_uploadToGoogleDrive(file)
  1. Read file as bytes
  2. Create multipart request
  3. Send to Google Apps Script
  4. Receive Google Drive file ID
  5. Convert to direct view URL
  ↓
Example: https://drive.google.com/uc?export=view&id=ABC123DEF
```

#### Step 3: Register with Server (via Protocol)
```dart
uploadMarketplaceItem() → Sends to TLS Server
  
Protocol format:
  UPLOAD|asset_name|username|google_drive_url|file_type|cost
  
Example:
  UPLOAD|MyAsset|john_doe|https://drive.google.com/uc?export=view&id=ABC123|png|99.99

Server response:
  OK|Asset 'MyAsset' uploaded successfully
  OR
  ERR03|Error message if failed
```

---

### ✅ Server-Side Upload Handler (Python)

**Server Protocol Implementation**

#### In `server_moudle.py`:
```python
def handle_UPLOAD(self, params):
    """
    Handle UPLOAD protocol message
    
    Receives:
      params[0] = asset_name
      params[1] = username
      params[2] = google_drive_url
      params[3] = file_type
      params[4] = cost
    
    Steps:
      1. Parse and validate parameters
      2. Check cost is numeric
      3. Add to MarketplaceDB via marketplace_db.py
      4. Return success/error response
    """
```

#### Database Storage:
- **MarketplaceDB** (SQLite via marketplace_db.py)
  - Stores asset metadata
  - Links Google Drive URLs
  - Tracks ownership (username)
  - Stores pricing

---

### ✅ Database Fixes

**Fixed FileNotFoundError: Database initialization now uses SQLite**

#### Issue:
```
FileNotFoundError: [Errno 2] No such file or directory: 'Database/users.pickle'
```

#### Solution:
1. Updated `classes.py` to use SQLite instead of pickle files
2. Automatically creates `Database` directory if missing
3. Creates SQLite tables on first run
4. All user data stored in `Database/users.db`

#### What Changed:
```python
# OLD (broken):
with open(USERS_FILE_PATH, 'rb') as file:
    self.users = pickle.load(file)  # ❌ File doesn't exist

# NEW (working):
self.conn = sqlite3.connect(str(DATABASE_PATH))  # ✅ Creates if missing
self.create_table()  # ✅ Creates tables automatically
```

---

### ✅ Fixed Syntax Warning

**Fixed escape sequence in server output:**
```python
# OLD:
self.Print(f"✅ Asset uploaded: {asset_name} by {username} - \${cost}", 20)
# Warning: "\$" is invalid

# NEW:
self.Print(f"✅ Asset uploaded: {asset_name} by {username} - \\${cost}", 20)
# ✅ Proper escape sequence
```

---

## How to Test

### 1. Start the Server
```bash
cd C:\dev\aurex\python_files
python server_moudle.py
```

Expected output:
```
✅ Config loaded: Server running on 192.168.1.61:23456
✅ Database initialized (SQLite)
[Server listening for connections...]
```

### 2. Run the Flutter App
```bash
flutter run
```

### 3. Test Asset Viewing (Already Exists)
- Login with credentials
- Navigate to Marketplace
- Should see 5-10 existing assets from Google Drive
- Click on any asset → Opens elegant details page
- Expand features → Smooth animation

### 4. Test Asset Upload
- From Marketplace, click floating action button (Upload)
- Select an image from device
- Enter asset details:
  - Name: "My Asset"
  - Description: "Test asset"
  - Cost: 49.99
- Click "Upload"
- App uploads to Google Drive
- App sends UPLOAD protocol to server
- Server stores metadata
- Asset appears in marketplace

### 5. View New Asset
- New asset appears in marketplace
- Full resolution image loads
- Asset details page works
- Can expand and view all features

---

## File Changes

### Dart (Flutter):
1. `lib/pages/upload_asset.dart` - Uses UPLOAD protocol ✅
2. `lib/services/google_drive_image_loader.dart` - Full image URLs ✅
3. `lib/client_class.dart` - Has uploadMarketplaceItem() method ✅

### Python (Server):
1. `python_files/classes.py`:
   - Changed from pickle to SQLite
   - DB.__init__() now creates tables
   - Fixed all get/set methods for SQL
   
2. `python_files/server_moudle.py`:
   - Fixed syntax warning (\$)
   - Uses DB() with SQLite
   - UPLOAD handler exists

---

## Architecture Overview

```
┌─────────────┐
│ Flutter App │
└──────┬──────┘
       │
       │ 1. File picker
       │    ↓
       ├─→ Google Drive Upload (HTTP multipart)
       │    ↓
       │ 2. Get Google Drive URL
       │    ↓
       │ 3. Send UPLOAD protocol to server
       │
       ↓
┌──────────────────────────┐
│ TLS Server (23456)       │
├──────────────────────────┤
│ • Parse UPLOAD protocol  │
│ • Validate parameters    │
│ • Store in SQLite DB     │
│ • Return response        │
└────────────┬─────────────┘
             │
             ↓
        ┌────────────┐
        │ SQLite DB  │
        │ (Metadata) │
        └────────────┘
             
             ↓
        ┌──────────────┐
        │ Google Drive │
        │ (Images)     │
        └──────────────┘
```

---

## Key Features

✅ **Full Resolution Images** - No thumbnail compromise
✅ **Cached Loading** - Fast repeated views
✅ **Server-Side Protocol** - UPLOAD command for asset registration
✅ **SQLite Database** - Persists all user data
✅ **Google Drive Integration** - Unlimited image storage
✅ **Error Handling** - Graceful fallbacks for missing images
✅ **No Python in App** - Pure Dart/Flutter implementation

---

## Common Issues & Solutions

### Issue: "Database/users.pickle not found"
**Solution**: Already fixed in updated `classes.py` - uses SQLite

### Issue: Assets not appearing in marketplace
**Solution**: 
1. Check server is running
2. Verify assets exist in Google Drive
3. Check marketplace_db.py has proper connection
4. Refresh app (pull-to-refresh on marketplace)

### Issue: Upload fails
**Solution**:
1. Check internet connection
2. Verify Google Apps Script URL is valid
3. Check asset name/cost are valid
4. Look at server logs for UPLOAD protocol response

### Issue: Image not loading
**Solution**:
1. Check image URL in database
2. Verify it's in format: `https://drive.google.com/uc?export=view&id=...`
3. Try manual URL in browser
4. Check Google Drive file sharing permissions

---

## Next Steps

1. ✅ Run server - should use SQLite now
2. ✅ Start app - should see existing assets
3. ✅ Test upload - should work via protocol
4. ✅ View marketplace - should show new assets
5. Future: Add search, filtering, shopping cart

**Version**: 1.1.0 - Fixed SQLite Database & Upload Protocol
**Status**: Ready for Testing ✅
