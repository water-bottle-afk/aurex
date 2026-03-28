# Aurex - Blockchain Image Ownership Marketplace

Aurex is a Flutter marketplace where users upload images, sell them, and transfer ownership. Ownership is anchored to a PoW blockchain using content hashes and client-signed transactions.

## What You Can Do
- Run the blockchain network (nodes + gateway)
- Run the marketplace server
- Run the Flutter app
- Upload an asset (mint on-chain)
- Purchase an asset (on-chain transfer)

## Prerequisites
- Python 3.10+
- Flutter SDK (stable channel)
- Android SDK / emulator or iOS Simulator (for mobile testing)
- Google Drive setup for uploads (see below)

## Install
### Python deps
```powershell
cd c:\dev\aurex
python -m pip install -r python_files\requirements.txt
```

### Flutter deps
```powershell
cd c:\dev\aurex
flutter pub get
```

## Configuration
### Server discovery IP
- The server binds to `SERVER_HOST` in `python_files/config.py` (default `0.0.0.0`).
- The broadcast reply IP is auto-detected at runtime. If auto-detect is wrong, set it explicitly:

```powershell
$env:AUREX_SERVER_IP = "192.168.1.50"
```

### Mobile connection notes
- Android emulator: use `10.0.2.2` as the host.
- iOS simulator: use `127.0.0.1` as the host.
- Real device: use your machine LAN IP and allow TCP `23456` and UDP `12345` through the firewall.

The app tries broadcast discovery first. If that fails, it lets you enter the IP/port manually.

You can also hardcode a default host/port at build time:
```powershell
flutter run --dart-define=AUREX_SERVER_HOST=10.0.2.2 --dart-define=AUREX_SERVER_PORT=23456
```

### Google Drive upload
Uploads require one of the following:

1. Service account (recommended)
- Create a service account in Google Cloud and download the JSON key file.
- Set `GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE` in `python_files/config.py` to that JSON path.
- Create a Drive folder and set `GOOGLE_DRIVE_PARENT_FOLDER_ID` in `python_files/config.py`.
- Share the folder with the service account email.

2. Apps Script endpoint (legacy)
- Set `GOOGLE_APPS_SCRIPT_URL` in `python_files/config.py`.
- Leave `GOOGLE_DRIVE_PARENT_FOLDER_ID` and `GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE` empty.

## Run
1. Start nodes
```powershell
cd c:\dev\aurex\blockchain
python launcher.py --nodes 3 --difficulty 2
```

2. Start gateway
```powershell
cd c:\dev\aurex\blockchain
python gateway_server.py
```

3. Start marketplace server
```powershell
cd c:\dev\aurex
python python_files\server_module.py
```

4. Run Flutter app
```powershell
cd c:\dev\aurex
flutter run
```

## Upload And Purchase Walkthrough
1. Launch the app and connect to the server (broadcast discovery or manual IP).
2. Sign up two users: a seller and a buyer.
3. Seller uploads an asset with a price.
4. Buyer purchases the asset from the marketplace.
5. Wait for the blockchain confirmation; the app will show a notification when the purchase is confirmed.

## Notes
- Starting wallet balance is `100` by default. Change it in `python_files/config.py`.
- TLS certs are loaded from `python_files/cert.pem` and `python_files/key.pem` by default.

## License
Private/internal project. All rights reserved.
