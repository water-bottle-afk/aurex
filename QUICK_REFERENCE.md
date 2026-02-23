# Aurex App - Quick Reference Guide

## Answer to Your Questions

### 1. Image Loading Strategy
**Question**: "Does it use img thumbnail or just the images itself?"

**Answer**: 
- ✅ Uses **FULL RESOLUTION IMAGES** from Google Drive
- Format: `https://drive.google.com/uc?export=view&id=FILE_ID`
- NOT using thumbnails - better quality for marketplace
- Thumbnails method available but not used by default
- Images cached locally for fast repeated loading

---

### 2. Server Upload Implementation
**Question**: "I want user to tell server to upload asset through server via protocol"

**Answer**:
- ✅ **DONE** - Uses UPLOAD protocol
- Protocol: `UPLOAD|asset_name|username|google_drive_url|file_type|cost`
- Server receives hex-formatted data and processes it
- No Python code running in app (pure Dart)
- All file operations in Dart, just sends metadata to server

**Flow**:
```
1. User picks file in app
2. App reads file as bytes
3. App uploads to Google Drive (gets URL back)
4. App sends UPLOAD protocol to server with Google Drive URL
5. Server stores metadata in SQLite DB
6. Asset appears in marketplace
```

---

### 3. Python or Dart for Upload?
**Question**: "Should I use Python in app or Dart?"

**Answer**: 
- ✅ **PURE DART** - No Python in the app
- Dart handles:
  - File picking from device
  - Reading bytes from file
  - Uploading to Google Drive
  - Sending protocol to server
- Server (Python) handles:
  - Receiving UPLOAD protocol
  - Storing metadata in SQLite
  - Responding to client

**Why Dart?**
- No external dependencies
- Faster execution
- No serialization needed
- Easier debugging
- Cleaner codebase

---

### 4. Existing Assets Test
**Question**: "When I run should I see 5-10 assets already existing?"

**Answer**:
- ✅ **YES** - Should see existing assets
- 5-10 assets already uploaded to Google Drive
- Marketplace loads them via server pagination
- Assets load from MarketplaceDB
- Click marketplace → see asset grid

**If assets don't appear**:
1. Check marketplace_db.py is running
2. Verify assets exist in Google Drive
3. Ensure server fetches from DB correctly
4. Check MarketplaceDB has asset records

---

## Quick Start (Testing)

### Terminal 1: Start Server
```bash
cd C:\dev\aurex\python_files
python server_moudle.py
```

Expected:
```
✅ Config loaded: Server running on 192.168.1.61:23456
✅ Database initialized (SQLite)
```

### Terminal 2: Start Flutter App
```bash
cd C:\dev\aurex
flutter run
```

Expected:
```
Connected to device (Android/iOS)
Running app...
```

### In App:
1. **Welcome** → Sign up/Login
2. **Marketplace** → See 5-10 existing assets
3. **Click asset** → See elegant details page
4. **Upload button** → Upload new asset
5. **Refresh** → New asset appears

---

## Fixed Issues

### ✅ Database Error Fixed
**Before**: `FileNotFoundError: 'Database/users.pickle' not found`
**After**: SQLite database auto-creates tables

### ✅ Syntax Warning Fixed
**Before**: `"\$" is invalid escape sequence`
**After**: Proper `\\$` escape

### ✅ Unused Import Removed
**Before**: Importing unused google_drive_image_loader
**After**: Removed, code is cleaner

---

## File Structure

```
C:\dev\aurex\
├── lib\
│   ├── pages\
│   │   ├── upload_asset.dart      ← Upload via Dart
│   │   ├── marketplace_page.dart   ← Shows assets
│   │   └── asset_details_page.dart ← Details view
│   │
│   ├── services\
│   │   └── google_drive_image_loader.dart  ← Full image loading
│   │
│   └── client_class.dart           ← uploadMarketplaceItem()
│
└── python_files\
    ├── classes.py                  ← SQLite DB (FIXED)
    ├── server_moudle.py            ← UPLOAD handler
    ├── marketplace_db.py           ← Asset storage
    └── Database\
        └── users.db                ← SQLite database (auto-created)
```

---

## Protocol Flow

### Upload Asset
```
App                          Server
│                            │
├─ Select file               │
├─ Upload to Google Drive    │
├─ Get URL                   │
│                            │
├─ Send UPLOAD protocol ────→ │
│  Format:                   │
│  UPLOAD|name|user|url      │
│  |type|cost                │
│                            │
│                  Parse ← ─ ┤
│                  Validate ─ ┤
│                  Store in DB
│                            │
│ ← ──── OK response ─────── │
│                            │
✓ Asset registered           │
```

### Fetch Assets
```
App                          Server
│                            │
├─ Request assets ──────────→ │
│  (with pagination)         │
│                            │
│                  Query DB ─ ┤
│                  Build list
│                            │
│ ← ────── Assets list ───── │
│  With Google Drive URLs    │
│                            │
├─ Load images from URLs     │
│  (cached)                  │
│                            │
✓ Marketplace displays       │
```

---

## Testing Checklist

- [ ] Server starts without errors
- [ ] App connects to server
- [ ] Marketplace loads existing assets
- [ ] Asset images display properly
- [ ] Click asset shows details page
- [ ] Can expand asset features
- [ ] Upload button functional
- [ ] Can select image file
- [ ] Upload to Google Drive works
- [ ] Server receives UPLOAD protocol
- [ ] New asset appears in marketplace
- [ ] Can view uploaded asset details

---

## Common Commands

### Run Server
```bash
python server_moudle.py
```

### Run App
```bash
flutter run -d <device_id>
```

### Check Database
```bash
sqlite3 Database/users.db ".tables"
```

### View Server Logs
```
Real-time in terminal output
[Server] INFO: ...
[Server] ERROR: ...
```

---

## No Further Action Needed ✅

- Database issue: **FIXED** (SQLite)
- Upload protocol: **IMPLEMENTED** (UPLOAD command)
- Image loading: **USING FULL RESOLUTION**
- Syntax warnings: **FIXED**
- Dart errors: **NONE**

**Ready to test!** 🚀
