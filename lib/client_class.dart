/// AUREX CLIENT PROTOCOL DOCUMENTATION
/// =====================================
/// All client operations and their protocol messages:
///
/// 1. START - Connection initialization
///    Send: START|Client_Flutter_App
///    Recv: ACCPT|Connection accepted
///
/// 2. LOGIN - User authentication (by USERNAME)
///    Send: LOGIN|username|password
///    Recv: OK|username or ERR|error_message
///
/// 3. SIGNUP - User registration (by USERNAME)
///    Send: SIGNUP|username|password
///    Recv: OK or ERR|error_message
///
/// 4. SEND_CODE - Request password reset OTP code via username
///    Send: SEND_CODE|username
///    Recv: OK|otp_sent or ERR|error_message
///
/// 5. VERIFY_CODE - Verify OTP code for password reset
///    Send: VERIFY_CODE|username|otp_code
///    Recv: OK|token or ERR|error_message
///
/// 6. UPDATE_PASSWORD - Change user password (after OTP verification)
///    Send: UPDATE_PASSWORD|username|new_password
///    Recv: OK or ERR|error_message
///
/// 7. LOGOUT - User logout
///    Send: LOGOUT|username
///    Recv: OK or ERR|error_message
///
/// 8. UPLOAD_INIT - Start chunked upload session
///    Send: UPLOAD_INIT|base64(json) (includes asset_hash + mint signature)
///    Recv: OK|upload_id|chunk_size or ERR|error_message
///
/// 9. UPLOAD_CHUNK - Send binary file chunk (inline format, no base64)
///    Send: [4-byte-len][b"UPLOAD_CHUNK|"+upload_id+b"|"+4-byte-seq+raw-bytes]
///    Recv: OK|seq or ERR|error_message
///
/// 10. UPLOAD_FINISH - Finalize upload
///     Send: UPLOAD_FINISH|upload_id
///     Recv: OK|asset_name|relative_path or ERR|error_message
///
/// 11. UPLOAD_ABORT - Cancel an upload
///     Send: UPLOAD_ABORT|upload_id
///     Recv: OK|message or ERR|error_message
///
/// 12. GET_ASSET_BINARY - Binary stream download of a stored image
///     Send: GET_ASSET_BINARY|username/filename.jpg
///     Recv: ASSET_START|size_bytes (text), then one raw binary frame (JPEG bytes)
///
/// 13. GET_ITEMS - Get all marketplace items
///     Send: GET_ITEMS
///     Recv: OK|item1|item2|... or ERR|error_message
///
/// 14. GET_ITEMS_PAGINATED - Lazy scrolling with timestamp cursor
///     Send: GET_ITEMS_PAGINATED|limit[|timestamp]
///     Recv: OK|item1|item2|... or ERR|error_message
///
/// 15. BUY - Purchase an asset from marketplace
///     Send: BUY|asset_id|username|amount|tx_id|timestamp|public_key|signature
///     Recv: OK|PENDING|transaction_id or ERR|error_message
///
/// 16. SEND - Send purchased asset to another user
///     Send: SEND|asset_id|sender_username|receiver_username|tx_id|timestamp|public_key|signature
///     Recv: OK|transaction_id or ERR|error_message
///
/// 17. GET_PROFILE - Get user profile (anonymous)
///     Send: GET_PROFILE|username
///     Recv: OK|username|email|created_at or ERR|error_message
///
/// 18. GET_TX_STATUS - Check blockchain purchase status
///     Send: GET_TX_STATUS|tx_id
///     Recv: OK|STATUS|message or ERR|error_message
///
/// 19. GET_ITEMS_BY_USER - Get assets owned by a user
///     Send: GET_ITEMS_BY_USER|username
///     Recv: OK|items_json or ERR|error_message
///
/// 20. GET_WALLET - Get wallet balance for a user
///     Send: GET_WALLET|username
///     Recv: OK|balance|updated_at or ERR|error_message
///
/// 21. GET_NOTIFICATIONS - Get notifications for a user
///     Send: GET_NOTIFICATIONS|username|limit
///     Recv: OK|json_list|unread_count or ERR|error_message
///
/// 22. MARK_NOTIFICATIONS_READ - Mark all notifications as read
///     Send: MARK_NOTIFICATIONS_READ|username
///     Recv: OK|read or ERR|error_message
///
/// 23. REGISTER_DEVICE - Register push token for device
///     Send: REGISTER_DEVICE|username|platform|token
///     Recv: OK|registered or ERR|error_message
///
/// 24. LIST_ITEM - List an owned asset for sale
///     Send: LIST_ITEM|asset_id|username|price
///     Recv: OK|LISTED or ERR|error_message
///
/// 25. UNLIST_ITEM - Remove an asset from the marketplace
///     Send: UNLIST_ITEM|asset_id|username
///     Recv: OK|UNLISTED or ERR|error_message
library;
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:logging/logging.dart';
import 'config.dart';
import 'utils/app_logger.dart';
import 'models/server_event.dart';
import 'services/wallet_key_service.dart';
import 'services/tx_signing.dart';
import 'utils/tx_utils.dart';

/// Message event for debugging - tracks sent/received messages
class MessageEvent {
  final String type; // 'sent', 'received', 'system'
  final String message;
  final DateTime timestamp;
  final String status; // 'success', 'error', 'pending'

  MessageEvent({
    required this.type,
    required this.message,
    required this.status,
  }) : timestamp = DateTime.now();

  @override
  String toString() =>
      '[${timestamp.hour.toString().padLeft(2, '0')}:${timestamp.minute.toString().padLeft(2, '0')}:${timestamp.second.toString().padLeft(2, '0')}] $type: $message ($status)';
}

class BuyResult {
  final String status;
  final String? txId;
  final String? message;

  const BuyResult({
    required this.status,
    this.txId,
    this.message,
  });
}

/// Result returned from [Client.getNotifications].
///
/// The server sends a JSON-encoded list of notification maps followed by the
/// unread count in a second field.  Consumers simply need a container with
/// those two pieces of information.
class NotificationResult {
  final List<Map<String, dynamic>> items;
  final int unreadCount;

  NotificationResult({required this.items, required this.unreadCount});
}

class TxStatusResult {
  final String status;
  final String message;

  const TxStatusResult({
    required this.status,
    required this.message,
  });
}

/// Protocol message handler for Blockchain Communication Protocol
class Client extends ChangeNotifier {
  SecureSocket? _socket;
  late String host;
  late int port;
  final Logger _logger = Logger('Client');
  final AppLogger _log = AppLogger.get('client_class.dart');
  bool _isConnected = false;
  bool _isAuthenticated = false;

  // Send synchronization to prevent concurrent socket operations
  bool _isSending = false;

  // Persistent socket stream and receive buffer
  StreamSubscription? _socketSubscription;
  final List<int> _receiveBuffer = [];

  // Server event handling --------------------------------------------------
  /// Controller that publishes server-initiated events ("EVENT|...")
  /// to listeners.  Providers listen to [serverEvents] and react accordingly.
  final StreamController<ServerEvent> _serverEventsController =
      StreamController<ServerEvent>.broadcast();

  /// Exposed stream of asynchronous server events.
  Stream<ServerEvent> get serverEvents => _serverEventsController.stream;

  // Internal queue used by [receiveMessage] so that events can be
  // separated from normal responses.  When the socket listener reads a
  // non-event message it is either delivered immediately to a pending
  // completer or queued here for later retrieval.
  final List<String> _messageQueue = [];
  Completer<String>? _messageCompleter;

  // Binary frame queue — populated when a framed message cannot be decoded
  // as UTF-8 (e.g. raw JPEG data from GET_ASSET responses).
  final List<Uint8List> _binaryQueue = [];
  Completer<Uint8List>? _binaryCompleter;
  int? _expectedBinaryFrameLength;

  // Serializes concurrent downloadAsset calls over the shared socket.
  // Caching is the caller's responsibility (e.g. AssetsProvider.imageCache).
  Future<dynamic> _serializedDownloadFuture = Future<void>.value();
  // -----------------------------------------------------------------------

  // Message tracking for debugging
  final List<MessageEvent> _messageHistory = [];
  Function(MessageEvent)? onMessageEvent;
  Function(String username)? onAuthenticated;
  VoidCallback? onDisconnected;

  bool get isConnected => _isConnected;
  bool get isAuthenticated => _isAuthenticated;
  List<MessageEvent> get messageHistory => List.unmodifiable(_messageHistory);

  Client({String? initialHost, int? initialPort}) {
    host = initialHost ?? ClientConfig.defaultServerHost;
    port = initialPort ?? ClientConfig.defaultServerPort;
  }


  /// Push message to screen (helper function to reduce code duplication)
  void pushMessageToScreen({
    required String type,
    required String message,
    required String status,
  }) {
    final event = MessageEvent(
      type: type,
      message: message,
      status: status,
    );
    _messageHistory.add(event);
    _logger.info(event.toString());
    onMessageEvent?.call(event);
    notifyListeners();
  }

  /// Discover server via broadcast message WHRSRV
  /// Listens for SRVRSP|ip|port response
  Future<bool> discoverServer({
    Duration timeout = ClientConfig.broadcastTimeout,
    int broadcastPort = ClientConfig.broadcastPort,
  }) async {
    try {
      pushMessageToScreen(
        type: 'system',
        message: 'Discovering server via broadcast...',
        status: 'pending',
      );

      final discoveredServer = await _broadcastWhereIsServer(
        broadcastPort: broadcastPort,
        timeout: timeout,
      );

      if (discoveredServer != null) {
        host = discoveredServer['ip']!;
        port = discoveredServer['port']!;
        notifyListeners();

        pushMessageToScreen(
          type: 'system',
          message: '🔍 Server discovered at $host:$port',
          status: 'success',
        );
        return true;
      } else {
        pushMessageToScreen(
          type: 'system',
          message: 'Server discovery timeout - using default server',
          status: 'pending',
        );
        return false;
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Server discovery failed: $e',
        status: 'error',
      );
      return false;
    }
  }

  /// Broadcast WHRSRV message and wait for SRVRSP response
  Future<Map<String, dynamic>?> _broadcastWhereIsServer({
    int broadcastPort = ClientConfig.broadcastPort,
    Duration timeout = ClientConfig.broadcastTimeout,
  }) async {
    try {
      final socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
      socket.broadcastEnabled = true;

      // Send WHRSRV broadcast
      const message = "WHRSRV";
      final broadcastAddr = InternetAddress("255.255.255.255");

      socket.send(
        utf8.encode(message),
        broadcastAddr,
        broadcastPort,
      );

      _log.info('Broadcast WHRSRV sent');

      // Listen for response with timeout
      final future = socket.timeout(timeout);

      try {
        await for (final event in future) {
          if (event == RawSocketEvent.read) {
            final datagram = socket.receive();
            if (datagram != null) {
              final response = utf8.decode(datagram.data);
              _log.info('Received broadcast response: $response');

              if (response.startsWith("SRVRSP|")) {
                final parts = response.split('|');
                if (parts.length >= 3) {
                  socket.close();
                  return {
                    'ip': parts[1],
                    'port': int.parse(parts[2]),
                  };
                }
              }
            }
          }
        }
      } on TimeoutException {
        _log.warn('Broadcast discovery timeout');
      }

      socket.close();
      return null;
    } catch (e) {
      _log.error('Broadcast error: $e');
      return null;
    }
  }

  /// Connect to server via TLS with START/ACCPT handshake
  /// Can optionally discover server first
  Future<void> connect({bool discoverFirst = true}) async {
    try {
      // Try to discover server first if requested
      if (discoverFirst) {
        await discoverServer();
      }

      pushMessageToScreen(
        type: 'system',
        message: 'Attempting to connect to $host:$port',
        status: 'pending',
      );

      _socket = await SecureSocket.connect(
        host,
        port,
        onBadCertificate: (_) => true,
      ).timeout(
        const Duration(seconds: 10),
        onTimeout: () {
          throw Exception('Connection timeout after 10 seconds - server may be offline');
        },
      );

      _isConnected = true;
      notifyListeners();

      pushMessageToScreen(
        type: 'system',
        message: '🔒 TLS Connected to server',
        status: 'success',
      );

      // Start persistent socket listener BEFORE sending any messages
      _startSocketListener();

      // Send START message for connection initialization
      await _sendStartMessage();
      
      _log.success('Connection successful and handshake complete');
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Connection failed: $e',
        status: 'error',
      );

      _isConnected = false;
      notifyListeners();
      rethrow;
    }
  }

  /// Manually set server address
  void setServerAddress(String newHost, int newPort) {
    host = newHost;
    port = newPort;
    notifyListeners();

    pushMessageToScreen(
      type: 'system',
      message: 'Server address changed to $host:$port',
      status: 'success',
    );
  }

  /// Send START message for protocol initialization
  /// Protocol Message 1: START (client → server)
  /// Receives: ACCPT (server → client)
  Future<void> _sendStartMessage() async {
    try {
      const startMsg = "START|Client_Flutter_App";

      pushMessageToScreen(
        type: 'sent',
        message: startMsg,
        status: 'pending',
      );

      await sendMessage(startMsg);
      _log.info('START message sent');

      // Wait for ACCPT response
      final response = await receiveMessage();
      _log.info('Received response: $response');

      if (response.startsWith("ACCPT")) {
        pushMessageToScreen(
          type: 'received',
          message: response,
          status: 'success',
        );
        _log.success('ACCPT received - connection established');
      } else {
        throw Exception("Unexpected response to START: $response");
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'START message failed: $e',
        status: 'error',
      );
      _log.error('START handshake failed: $e');
      rethrow;
    }
  }

  /// Send a message with 4-byte length prefix
  /// Format: [4-byte length][message]
  Future<void> sendMessage(
    String message, {
    String? logPreview,
    bool logToScreen = true,
  }) async {
    if (_socket == null || !_isConnected) {
      throw Exception("Not connected to server");
    }

    // Wait for any ongoing send to complete
    while (_isSending) {
      await Future.delayed(const Duration(milliseconds: 10));
    }

    _isSending = true;
    try {
      final messageBytes = utf8.encode(message);
      final lengthPrefix = ByteData(4);
      lengthPrefix.setUint32(0, messageBytes.length, Endian.big);

      _socket!.add(lengthPrefix.buffer.asUint8List());
      _socket!.add(messageBytes);
      await _socket!.flush();

      // Extract protocol preview for cleaner logging
      final preview = logPreview ??
          (message.length > 50 ? '${message.substring(0, 50)}...' : message);
      final displayMessage = logPreview ?? message;

      _log.info('[SEND] $preview');

      if (logToScreen) {
        pushMessageToScreen(
          type: 'sent',
          message: displayMessage,
          status: 'success',
        );
      }
    } on SocketException catch (e) {
      _handleSocketDisconnected(
        'Disconnected from server: ${e.message}',
        error: e,
      );
      rethrow;
    } catch (e) {
      _log.error('[SEND FAILED] $e');
      
      if (logToScreen) {
        pushMessageToScreen(
          type: 'sent',
          message: message,
          status: 'error',
        );
      }
      rethrow;
    } finally {
      _isSending = false;
    }
  }

  /// Receive a message with 4-byte length prefix
  /// Returns: Decoded message string
  /// Called from [_startSocketListener] whenever fresh bytes arrive.
  ///
  /// Splits the buffer into complete messages, dispatching `EVENT|`
  /// notifications to [_serverEventsController] and queueing other responses
  /// for consumption by [receiveMessage].
  void _processBuffer() {
    while (_receiveBuffer.length >= 4) {
      final header = ByteData.view(Uint8List.fromList(_receiveBuffer.sublist(0, 4)).buffer);
      final length = header.getUint32(0, Endian.big);
      if (_receiveBuffer.length < 4 + length) {
        // wait for full message
        break;
      }
      final messageBytes = _receiveBuffer.sublist(4, 4 + length);
      _receiveBuffer.removeRange(0, 4 + length);

      if (_expectedBinaryFrameLength != null) {
        final bytes = Uint8List.fromList(messageBytes);
        _expectedBinaryFrameLength = null;
        if (_binaryCompleter != null && !_binaryCompleter!.isCompleted) {
          _binaryCompleter!.complete(bytes);
          _binaryCompleter = null;
        } else {
          _binaryQueue.add(bytes);
        }
        continue;
      }

      // Try UTF-8 decode; binary frames (e.g. raw JPEG) will throw.
      String? message;
      try {
        message = utf8.decode(messageBytes, allowMalformed: false);
      } catch (_) {
        // Binary frame — route to binary queue.
        final bytes = Uint8List.fromList(messageBytes);
        if (_binaryCompleter != null && !_binaryCompleter!.isCompleted) {
          _binaryCompleter!.complete(bytes);
          _binaryCompleter = null;
        } else {
          _binaryQueue.add(bytes);
        }
        continue;
      }

      if (message.startsWith('EVENT|')) {
        try {
          final jsonStr = message.substring(6);
          final event = ServerEvent.fromJson(jsonStr);
          _serverEventsController.add(event);
        } catch (_) {}
        continue;
      }

      if (message.startsWith('ASSET_START|')) {
        _expectedBinaryFrameLength = int.tryParse(
          message.substring('ASSET_START|'.length).trim(),
        );
      }

      // Regular response — satisfy a pending completer or queue it.
      if (_messageCompleter != null && !_messageCompleter!.isCompleted) {
        _messageCompleter!.complete(message);
        _messageCompleter = null;
      } else {
        _messageQueue.add(message);
      }
    }
  }

  /// Receive the next binary frame from the server.
  /// Resolves when a frame that could not be decoded as UTF-8 arrives.
  Future<Uint8List> receiveBinaryFrame() async {
    if (_socket == null || !_isConnected) {
      throw Exception('Not connected to server');
    }
    if (_binaryQueue.isNotEmpty) return _binaryQueue.removeAt(0);
    _binaryCompleter = Completer<Uint8List>();
    return _binaryCompleter!.future;
  }

  Uint8List _uint32ToBytes(int value) {
    final data = ByteData(4);
    data.setUint32(0, value, Endian.big);
    return data.buffer.asUint8List();
  }

  int _indexOfSignature(Uint8List bytes, List<int> signature) {
    if (bytes.length < signature.length) return -1;
    for (var i = 0; i <= bytes.length - signature.length; i++) {
      var matches = true;
      for (var j = 0; j < signature.length; j++) {
        if (bytes[i + j] != signature[j]) {
          matches = false;
          break;
        }
      }
      if (matches) return i;
    }
    return -1;
  }

  bool _hasSupportedImageSignature(Uint8List bytes) {
    return bytes.length >= 2 &&
        ((bytes[0] == 0xFF && bytes[1] == 0xD8) ||
            (bytes[0] == 0x89 && bytes[1] == 0x50));
  }

  Uint8List? _sanitizeAssetBytes(Uint8List raw) {
    if (raw.isEmpty) return null;

    var bytes = raw;
    final assetStartPrefix = utf8.encode('ASSET_START');
    var startsWithAssetStart = bytes.length >= assetStartPrefix.length;
    if (startsWithAssetStart) {
      for (var i = 0; i < assetStartPrefix.length; i++) {
        if (bytes[i] != assetStartPrefix[i]) {
          startsWithAssetStart = false;
          break;
        }
      }
    }

    if (startsWithAssetStart) {
      final newlineIndex = bytes.indexOf(0x0A);
      final pipeIndex = bytes.indexOf(0x7C);
      if (newlineIndex >= 0 && newlineIndex + 1 < bytes.length) {
        bytes = Uint8List.fromList(bytes.sublist(newlineIndex + 1));
      } else if (pipeIndex >= 0 && pipeIndex + 1 < bytes.length) {
        bytes = Uint8List.fromList(bytes.sublist(pipeIndex + 1));
      }
    }

    if (!_hasSupportedImageSignature(bytes)) {
      final jpegIndex = _indexOfSignature(bytes, const [0xFF, 0xD8]);
      final pngIndex = _indexOfSignature(bytes, const [0x89, 0x50]);
      var signatureIndex = -1;
      if (jpegIndex >= 0 && pngIndex >= 0) {
        signatureIndex = jpegIndex < pngIndex ? jpegIndex : pngIndex;
      } else if (jpegIndex >= 0) {
        signatureIndex = jpegIndex;
      } else if (pngIndex >= 0) {
        signatureIndex = pngIndex;
      }
      if (signatureIndex >= 0) {
        bytes = Uint8List.fromList(bytes.sublist(signatureIndex));
      }
    }

    return _hasSupportedImageSignature(bytes) ? bytes : null;
  }

  void _failPendingSocketWaiters(Object error) {
    if (_messageCompleter != null && !_messageCompleter!.isCompleted) {
      _messageCompleter!.completeError(error);
    }
    _messageCompleter = null;

    if (_binaryCompleter != null && !_binaryCompleter!.isCompleted) {
      _binaryCompleter!.completeError(error);
    }
    _binaryCompleter = null;
  }

  void _handleSocketDisconnected(
    String message, {
    Object? error,
    String status = 'error',
  }) {
    final hadActiveSocket = _socket != null || _socketSubscription != null || _isConnected;
    final disconnectError = error ?? SocketException(message);

    _failPendingSocketWaiters(disconnectError);
    _messageQueue.clear();
    _binaryQueue.clear();
    _receiveBuffer.clear();
    _expectedBinaryFrameLength = null;

    final subscription = _socketSubscription;
    _socketSubscription = null;
    subscription?.cancel();

    final socket = _socket;
    _socket = null;
    try {
      socket?.destroy();
    } catch (_) {
      try {
        socket?.close();
      } catch (_) {}
    }

    _isConnected = false;
    _isAuthenticated = false;
    _isSending = false;

    if (hadActiveSocket) {
      pushMessageToScreen(
        type: 'system',
        message: message,
        status: status,
      );
      notifyListeners();
      onDisconnected?.call();
    }
  }

  /// Download an asset image by relative server path (e.g. "alice/abc123_photo.jpg").
  /// Serialized to prevent concurrent socket message corruption.
  /// Callers are responsible for caching the result.
  Future<Uint8List?> downloadAsset(String relPath) {
    if (relPath.isEmpty) return Future.value(null);
    // Chain onto the serialized future so only one download runs at a time.
    final completer = Completer<Uint8List?>();
    _serializedDownloadFuture = _serializedDownloadFuture.then((_) async {
      try {
        await sendMessage('GET_ASSET_BINARY|$relPath', logToScreen: false);
        final header = await receiveMessage()
            .timeout(const Duration(seconds: 20),
                onTimeout: () => throw TimeoutException('GET_ASSET_BINARY header timed out'));
        final hParts = header.split('|');
        if (hParts[0] != 'ASSET_START') {
          completer.complete(null);
          return;
        }
        Uint8List raw = await receiveBinaryFrame()
            .timeout(const Duration(seconds: 30),
                onTimeout: () => throw TimeoutException('GET_ASSET_BINARY data timed out'));
        final sanitized = _sanitizeAssetBytes(raw);
        completer.complete(sanitized);
      } catch (e) {
        completer.completeError(e);
      }
    });
    return completer.future;
  }

  /// Send raw binary data with 4-byte length prefix (no UTF-8 encoding).
  /// Used for binary chunk streaming during file upload.
  Future<void> sendRawBytes(Uint8List bytes) async {
    if (_socket == null || !_isConnected) {
      throw Exception("Not connected to server");
    }
    while (_isSending) {
      await Future.delayed(const Duration(milliseconds: 10));
    }
    _isSending = true;
    try {
      final lengthPrefix = ByteData(4);
      lengthPrefix.setUint32(0, bytes.length, Endian.big);
      _socket!.add(lengthPrefix.buffer.asUint8List());
      _socket!.add(bytes);
      await _socket!.flush();
    } on SocketException catch (e) {
      _handleSocketDisconnected(
        'Disconnected from server: ${e.message}',
        error: e,
      );
      rethrow;
    } finally {
      _isSending = false;
    }
  }

  Future<String> receiveMessage() async {
    if (_socket == null || !_isConnected) {
      throw Exception("Not connected to server");
    }

    // check queue first
    if (_messageQueue.isNotEmpty) {
      return _messageQueue.removeAt(0);
    }

    _messageCompleter = Completer<String>();
    return _messageCompleter!.future;
  }

  /// Start persistent socket listener that buffers all incoming data
  void _startSocketListener() {
    if (_socket == null) return;

    // Cancel any existing subscription
    _socketSubscription?.cancel();

    // Start listening to socket and buffer all data; processed data gets
    // pushed either to the message queue or into the serverEvents stream.
    _socketSubscription = _socket!.listen(
      (data) {
        try {
          _receiveBuffer.addAll(data);
          _processBuffer();
        } on SocketException catch (e) {
          if (e.message.contains('closed socket')) {
            _handleSocketDisconnected(
              'Disconnected from server: ${e.message}',
              error: e,
            );
            return;
          }
          _handleSocketDisconnected(
            'Socket error: ${e.message}',
            error: e,
          );
        } catch (e) {
          _handleSocketDisconnected(
            'Socket listener failed: $e',
            error: e,
          );
        }
      },
      onError: (error) {
        _logger.severe("Socket error: $error");
        _handleSocketDisconnected(
          error is SocketException && error.message.contains('closed socket')
              ? 'Disconnected from server: ${error.message}'
              : 'Socket error: $error',
          error: error,
        );
      },
      onDone: () {
        _logger.info("Socket closed by server");
        _handleSocketDisconnected('Socket closed by server');
      },
    );
  }

  /// Validate signup fields - returns error message or null if valid
  String? _validateSignupFields(String username, String password) {
    // Check for empty fields
    if (username.isEmpty) return "Username cannot be empty";
    if (password.isEmpty) return "Password cannot be empty";

    // Check for pipe characters
    if (username.contains('|')) return "Username cannot contain '|'";
    if (password.contains('|')) return "Password cannot contain '|'";

    // Check for leading/trailing spaces
    if (username != username.trim()) return "Username cannot have leading/trailing spaces";
    if (password != password.trim()) return "Password cannot have leading/trailing spaces";

    // Username validation: alphanumeric + underscore
    if (!RegExp(r'^[a-zA-Z0-9_]{3,20}$').hasMatch(username)) {
      return "Username: 3-20 chars, alphanumeric + underscore only";
    }

    // Password validation: min 6 chars
    if (password.length < 6) {
      return "Password must be at least 6 characters";
    }

    return null; // All valid
  }


  // ====== AUTHENTICATION METHODS ======

  /// Protocol Message: LOGIN (Email-based authentication)
  /// Send: LOGIN|email|password
  /// Receive: OK|username|email or ERR|error_message
  Future<String?> login(String username, String password) async {
    try {
      // Validate username format
      if (username.isEmpty || username.contains('|') || username.contains(' ')) {
        throw Exception("Invalid username format");
      }
      if (password.isEmpty || password.contains('|')) {
        throw Exception("Invalid password format");
      }

      final message = "LOGIN|$username|$password";

      pushMessageToScreen(
        type: 'sent',
        message: "LOGIN|$username|***",
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code = parts[0];

      if (code == "OK" && parts.length >= 2) {
        final returnedUsername = parts[1];
        
        _isAuthenticated = true;
        notifyListeners();
        onAuthenticated?.call(returnedUsername);
        pushMessageToScreen(
          type: 'received',
          message: "Login successful as $returnedUsername",
          status: 'success',
        );
        return returnedUsername;
      } else if (code.startsWith("ERR")) {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Login failed: $errorMsg",
          status: 'error',
        );
        return null;
      }
      return null;
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Login error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// LOGIN_GOOGLE - Authenticate via Google-verified email (no password needed).
  /// Send: LOGIN_GOOGLE|email
  /// Receive: OK|username or ERR|error_message
  Future<String?> loginWithGoogle(String email) async {
    try {
      if (email.isEmpty || email.contains('|')) {
        throw Exception("Invalid email format");
      }
      final message = "LOGIN_GOOGLE|$email";
      pushMessageToScreen(
        type: 'sent',
        message: "LOGIN_GOOGLE|$email",
        status: 'pending',
      );
      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');
      if (parts[0] == "OK" && parts.length >= 2) {
        final returnedUsername = parts[1];
        _isAuthenticated = true;
        notifyListeners();
        onAuthenticated?.call(returnedUsername);
        pushMessageToScreen(
          type: 'received',
          message: "Google login successful as $returnedUsername",
          status: 'success',
        );
        return returnedUsername;
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Google login failed: $errorMsg",
          status: 'error',
        );
        return null;
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Google login error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// GET_USER_BY_EMAIL - Look up username by email (e.g. for Google sign-in).
  /// Send: GET_USER_BY_EMAIL|email
  /// Receive: OK|username or ERR|error_message
  Future<String?> getUserByEmail(String email) async {
    try {
      if (email.isEmpty || email.contains('|')) {
        throw Exception("Invalid email format");
      }
      final message = "GET_USER_BY_EMAIL|$email";
      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');
      if (parts[0] == "OK" && parts.length >= 2) {
        return parts[1];
      }
      return null;
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'getUserByEmail error: $e',
        status: 'error',
      );
      return null;
    }
  }

  /// Protocol Message: SIGNUP (User Registration with field validation)
  /// Send: SIGNUP|username|password|email
  /// Receive: OK|username or ERR|error_message
  /// 
  /// Field validation rules:
  /// - No '|' or leading/trailing spaces
  /// - Username: alphanumeric (can contain underscore), 3-20 chars
  /// - Password: min 6 chars
  Future<String> signUp({
    required String username,
    required String password,
    required String email,
  }) async {
    try {
      // Client-side field validation
      final validation = _validateSignupFields(username, password);
      if (validation != null) {
        pushMessageToScreen(
          type: 'system',
          message: validation,
          status: 'error',
        );
        throw Exception(validation);
      }
      if (email.isEmpty || email.contains('|')) {
        throw Exception("Invalid email format");
      }

      final message = "SIGNUP|$username|$password|$email";

      pushMessageToScreen(
        type: 'sent',
        message: "SIGNUP|$username|***",
        status: 'pending',
      );

      await sendMessage(message);

      final response = await receiveMessage();
      final parts = response.split('|');
      final code = parts[0];

      if (code == "OK") {
        final returnedUsername = parts.length > 1 ? parts[1] : username;
        pushMessageToScreen(
          type: 'received',
          message: "Signup successful! Welcome $returnedUsername",
          status: 'success',
        );
        return "success";
      } else if (code.startsWith("ERR")) {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Signup failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
      return "unknown";
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Signup error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Close connection to server
  Future<void> close() async {
    try {
      await _socket?.close();
      _isConnected = false;
      _isAuthenticated = false;
      notifyListeners();

      pushMessageToScreen(
        type: 'system',
        message: 'Connection closed',
        status: 'success',
      );
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error closing connection: $e',
        status: 'error',
      );
    }
  }

  /// Lazy load marketplace items with pagination
  /// Send: GET_ITEMS_PAGINATED|limit|last_timestamp (optional)
  /// Receive: OK|items_json or ERR|error_message
  Future<List<dynamic>> getMarketplaceItemsPaginated({
    int limit = 10,
    String? lastTimestamp,
  }) async {
    try {
      final message = lastTimestamp != null
          ? "GET_ITEMS_PAGINATED|$limit|$lastTimestamp"
          : "GET_ITEMS_PAGINATED|$limit";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final sepIdx = response.indexOf('|');

      if (response.startsWith('OK') && sepIdx != -1) {
        final jsonStr = response.substring(sepIdx + 1);
        final itemsJson = jsonDecode(jsonStr) as List;
        pushMessageToScreen(
          type: 'received',
          message: "Loaded ${itemsJson.length} items",
          status: 'success',
        );
        return itemsJson;
      } else {
        final errorMsg = sepIdx != -1 ? response.substring(sepIdx + 1) : response;
        pushMessageToScreen(
          type: 'received',
          message: "Failed to load items: $errorMsg",
          status: 'error',
        );
        return [];
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error loading items: $e',
        status: 'error',
      );
      return [];
    }
  }

  /// Send email verification code
  /// Send: SEND_CODE|email
  /// Receive: OK or ERR|error_message
  Future<String> sendVerificationCode(String email) async {
    try {
      final message = "SEND_CODE|$email";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Verification code sent to $email",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Failed to send code: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error sending code: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Verify email with code
  /// Send: VERIFY_CODE|email|code
  /// Receive: OK or ERR|error_message
  Future<String> verifyEmailCode(String email, String code) async {
    try {
      final message = "VERIFY_CODE|$email|$code";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Email verified successfully",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Verification failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error verifying code: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Upload marketplace item (legacy: URL already on Drive)
  /// Send: UPLOAD|asset_name|username|google_drive_url|file_type|cost
  /// Receive: OK or ERR|error_message
  Future<String> uploadMarketplaceItem({
    required String assetName,
    required String username,
    required String googleDriveUrl,
    required String fileType,
    required double cost,
  }) async {
    try {
      final message =
          "UPLOAD|$assetName|$username|$googleDriveUrl|$fileType|$cost";

      pushMessageToScreen(
        type: 'sent',
        message: "UPLOAD|$assetName|$username|...|$fileType|$cost",
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Item uploaded successfully",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Upload failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error uploading item: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Upload marketplace item using raw binary chunked streaming.
  /// Flow: UPLOAD_INIT → [UPLOAD_CHUNK inline binary frames] → UPLOAD_FINISH
  /// Chunk frame layout: [4-byte len][b"UPLOAD_CHUNK|"+uploadId+b"|"+4-byte-seq+raw-data]
  Future<String> uploadMarketplaceItemBinary({
    required File file,
    required String assetName,
    required String description,
    required String username,
    required String fileType,
    required double cost,
    required String assetHash,
    required String mintTxId,
    required String mintTimestamp,
    required String publicKey,
    required String mintSignature,
  }) async {
    String? uploadId;
    const requestedChunkSize = 2048;
    try {
      final normalizedType =
          fileType.toLowerCase() == 'jpeg' ? 'jpg' : fileType.toLowerCase();
      final fileSize = await file.length();
      final originalName = file.path.split(Platform.pathSeparator).last;
      final totalChunks = ((fileSize + requestedChunkSize - 1) ~/ requestedChunkSize);

      // ── Phase A: UPLOAD_INIT ─────────────────────────────────────────────
      final initPayload = {
        "asset_name": assetName,
        "username": username,
        "description": description,
        "file_type": normalizedType,
        "cost": cost,
        "file_size": fileSize,
        "original_name": originalName,
        "total_chunks": totalChunks,
        "asset_hash": assetHash,
        "mint_tx_id": mintTxId,
        "mint_timestamp": mintTimestamp,
        "public_key": publicKey,
        "mint_signature": mintSignature,
      };
      await sendMessage(
        "UPLOAD_INIT|${base64Encode(utf8.encode(jsonEncode(initPayload)))}",
        logPreview: "UPLOAD_INIT|<payload>",
      );
      final initResponse = await receiveMessage();
      final initParts = initResponse.split('|');
      if (initParts.isEmpty || initParts[0] != "OK") {
        final errMsg = initParts.length > 1 ? initParts[1] : "Init failed";
        pushMessageToScreen(type: 'received', message: "Upload init failed: $errMsg", status: 'error');
        return "error";
      }
      uploadId = initParts.length > 1 ? initParts[1] : null;
      if (uploadId == null || uploadId.isEmpty || uploadId == '[]') {
        throw Exception("Invalid upload_id from server: ${uploadId ?? 'null'}");
      }
      final advertisedChunkSize =
          initParts.length > 2 ? int.tryParse(initParts[2]) : null;
      if (advertisedChunkSize == null || advertisedChunkSize <= 0) {
        throw Exception("Invalid chunk_size from server: ${initParts.length > 2 ? initParts[2] : 'missing'}");
      }
      if (advertisedChunkSize != requestedChunkSize) {
        throw Exception(
          "Unexpected server chunk size: $advertisedChunkSize (expected $requestedChunkSize)",
        );
      }
      final chunkSize = advertisedChunkSize;

      // ── Phase B: inline binary chunk streaming ───────────────────────────
      // Payload layout per chunk: b"UPLOAD_CHUNK|"+uploadId+b"|"+[4-byte seq big-endian]+raw-data
      final raf = await file.open();
      try {
        for (var seq = 0; seq < totalChunks; seq++) {
          final chunkBytes = await raf.read(chunkSize);
          if (chunkBytes.isEmpty) throw Exception("Unexpected end of file at chunk $seq");

          final builder = BytesBuilder(copy: false);
          builder.add(utf8.encode('UPLOAD_CHUNK|'));
          builder.add(utf8.encode('$uploadId|'));
          builder.add(_uint32ToBytes(seq));
          builder.add(chunkBytes);
          final payload = builder.toBytes();
          await sendRawBytes(payload);

          final ackResponse = await receiveMessage()
              .timeout(const Duration(seconds: 30),
                  onTimeout: () => throw TimeoutException('ACK timed out for chunk $seq'));
          if (ackResponse != 'OK|$seq') {
            final ackParts = ackResponse.split('|');
            final errMsg = ackParts.length > 1 ? ackParts[1] : ackResponse;
            throw Exception("Chunk $seq rejected: $errMsg");
          }
        }
      } finally {
        await raf.close();
      }

      // ── Phase C: finalize ────────────────────────────────────────────────
      await sendMessage("UPLOAD_FINISH|$uploadId");
      final finishResponse = await receiveMessage()
          .timeout(const Duration(seconds: 30),
              onTimeout: () => throw TimeoutException('UPLOAD_FINISH timed out'));
      final finishParts = finishResponse.split('|');
      if (finishParts.isNotEmpty && finishParts[0] == "OK") {
        pushMessageToScreen(type: 'received', message: "Item uploaded successfully", status: 'success');
        return "success";
      }
      final errMsg = finishParts.length > 1 ? finishParts[1] : "Upload failed";
      pushMessageToScreen(type: 'received', message: "Upload failed: $errMsg", status: 'error');
      return "error";
    } catch (e) {
      if (uploadId != null) {
        try {
          await sendMessage("UPLOAD_ABORT|$uploadId");
          await receiveMessage();
        } catch (_) {}
      }
      pushMessageToScreen(type: 'system', message: 'Upload error: $e', status: 'error');
      rethrow;
    }
  }

  /// Request password reset code via email
  /// Send: SEND_CODE|email
  /// Receive: OK or ERR|error_message
  Future<String> requestPasswordReset(String email) async {
    try {
      final message = "SEND_CODE|$email";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        final otp = parts.length >= 3 ? parts[2] : null;
        pushMessageToScreen(
          type: 'received',
          message: "Reset code sent to $email",
          status: 'success',
        );
        return otp != null && otp.isNotEmpty ? "success:$otp" : "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Reset failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error requesting reset: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Verify password reset code
  /// Send: VERIFY_CODE|email|code
  /// Receive: OK or ERR|error_message
  Future<String> verifyPasswordResetCode(String email, String code) async {
    try {
      final message = "VERIFY_CODE|$email|$code";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Code verified",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Verification failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error verifying code: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Update password after OTP verification
  /// Send: UPDATE_PASSWORD|email|new_password
  /// Receive: OK or ERR|error_message
  Future<String> updatePassword(String email, String newPassword) async {
    try {
      if (email.isEmpty || newPassword.isEmpty) {
        throw Exception("Email and password cannot be empty");
      }
      if (email.contains('|') || newPassword.contains('|')) {
        throw Exception("Fields cannot contain '|'");
      }

      final message = "UPDATE_PASSWORD|$email|$newPassword";

      pushMessageToScreen(
        type: 'sent',
        message: "UPDATE_PASSWORD|$email|***",
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Password updated successfully",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Password update failed: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error updating password: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Buy marketplace asset
  /// Send: BUY|asset_id|username|amount|tx_id|timestamp|public_key|signature
  /// Receive: OK|PENDING|transaction_id or ERR|error_message
  Future<BuyResult> buyAsset({
    required String assetId,
    required String username,
    required double amount,
    required String assetName,
    required String seller,
    required String assetHash,
  }) async {
    try {
      if (assetHash.isEmpty) {
        throw Exception("Missing asset hash");
      }
      final txId = generateTxId('TXN', username, assetId: assetId);
      final timestamp = DateTime.now().toUtc().toIso8601String();
      final publicKey = await WalletKeyService.getPublicKeyBase64();
      final payload = {
        'action': 'purchase',
        'tx_id': txId,
        'asset_id': assetId,
        'asset_hash': assetHash,
        'asset_name': assetName,
        'price': amount,
        'from': username,
        'to': seller,
        'amount': amount,
        'timestamp': timestamp,
      };
      final messageBytes = canonicalTxMessage(username, payload);
      final signature = await WalletKeyService.signMessage(messageBytes);
      final message =
          "BUY|$assetId|$username|$amount|$txId|$timestamp|$publicKey|$signature";

      pushMessageToScreen(
        type: 'sent',
        message: "BUY|$assetId|$username|$amount|$txId|$timestamp|<public_key>|<signature>",
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        final status = parts.length > 1 ? parts[1].toUpperCase() : "OK";
        final transactionId = parts.length > 2 ? parts[2] : null;
        pushMessageToScreen(
          type: 'received',
          message: "Purchase status: $status",
          status: 'success',
        );
        return BuyResult(status: status, txId: transactionId);
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Purchase failed: $errorMsg",
          status: 'error',
        );
        return BuyResult(status: "ERROR", message: errorMsg);
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error purchasing asset: $e',
        status: 'error',
      );
      return BuyResult(status: "ERROR", message: e.toString());
    }
  }

  /// Check blockchain transaction status
  /// Send: GET_TX_STATUS|tx_id
  /// Receive: OK|STATUS|message or ERR|error_message
  Future<TxStatusResult> getTransactionStatus(String txId) async {
    try {
      final message = "GET_TX_STATUS|$txId";
      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK" && parts.length >= 2) {
        final status = parts[1].toUpperCase();
        final msg = parts.length > 2 ? parts.sublist(2).join('|') : '';
        return TxStatusResult(status: status, message: msg);
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        return TxStatusResult(status: "ERROR", message: errorMsg);
      }
    } catch (e) {
      return TxStatusResult(status: "ERROR", message: e.toString());
    }
  }

  /// Get assets owned by a user
  /// Send: GET_ITEMS_BY_USER|username
  /// Receive: OK|items_json or ERR|error_message
  Future<List<dynamic>> getUserAssets(String username) async {
    try {
      if (username.isEmpty || username.contains('|')) {
        throw Exception("Invalid username");
      }
      final message = "GET_ITEMS_BY_USER|$username";
      await sendMessage(message);
      final response = await receiveMessage();
      final sepIdx = response.indexOf('|');
      if (response.startsWith('OK') && sepIdx != -1) {
        return jsonDecode(response.substring(sepIdx + 1)) as List;
      }
      final errorMsg = sepIdx != -1 ? response.substring(sepIdx + 1) : response;
      throw Exception(errorMsg);
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'getUserAssets error: $e',
        status: 'error',
      );
      return [];
    }
  }

  /// Get wallet balance for a user
  /// Send: GET_WALLET|username
  /// Receive: OK|balance|updated_at or ERR|error_message
  Future<Map<String, dynamic>?> getWallet(String username) async {
    try {
      if (username.isEmpty || username.contains('|')) {
        throw Exception("Invalid username");
      }
      final message = "GET_WALLET|$username";
      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK" && parts.length >= 2) {
        final balance = double.tryParse(parts[1]) ?? 0.0;
        final updatedAt = parts.length > 2 ? parts[2] : '';
        return {
          'balance': balance,
          'updated_at': updatedAt,
        };
      }
      if (parts[0] == "ERR02") {
        return null;
      }
      final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
      throw Exception(errorMsg);
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'getWallet error: $e',
        status: 'error',
      );
      return null;
    }
  }

  /// Fetch notifications for the given user.  Returns a [NotificationResult]
  /// containing the list of maps returned by the server as well as the
  /// unread count.
  Future<NotificationResult> getNotifications({
    required String username,
    int limit = 20,
  }) async {
    try {
      if (username.isEmpty || username.contains('|')) {
        throw Exception("Invalid username");
      }
      final message = "GET_NOTIFICATIONS|$username|$limit";
      await sendMessage(message);
      final response = await receiveMessage();
      if (response.startsWith('ERR02')) {
        return NotificationResult(items: const [], unreadCount: 0);
      }
      final firstPipe = response.indexOf('|');
      if (response.startsWith('OK') && firstPipe != -1) {
        final lastPipe = response.lastIndexOf('|');
        final jsonStr = firstPipe == lastPipe
            ? response.substring(firstPipe + 1)
            : response.substring(firstPipe + 1, lastPipe);
        final unreadStr = firstPipe == lastPipe
            ? '0'
            : response.substring(lastPipe + 1);
        final decoded = jsonDecode(jsonStr);
        final rawList = decoded is List ? decoded : <dynamic>[];
        final items = <Map<String, dynamic>>[];
        for (final entry in rawList) {
          if (entry is Map) {
            items.add(Map<String, dynamic>.from(entry));
          }
        }
        final unreadCount = int.tryParse(unreadStr) ??
            double.tryParse(unreadStr)?.toInt() ?? 0;
        return NotificationResult(
          items: items,
          unreadCount: unreadCount,
        );
      }
      final errSep = response.indexOf('|');
      final errorMsg = errSep != -1 ? response.substring(errSep + 1) : response;
      throw Exception(errorMsg);
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'getNotifications error: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Mark all notifications read for the specified user.  Returns `true`
  /// when the server replies OK.
  Future<bool> markNotificationsRead(String username) async {
    try {
      if (username.isEmpty || username.contains('|')) {
        throw Exception("Invalid username");
      }
      final message = "MARK_NOTIFICATIONS_READ|$username";
      await sendMessage(message);
      final response = await receiveMessage();
      return response.startsWith('OK');
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'markNotificationsRead error: $e',
        status: 'error',
      );
      return false;
    }
  }

  /// Register a device push token for the user.
  /// Send: REGISTER_DEVICE|username|platform|token
  /// Receive: OK|registered or ERR|error_message
  Future<bool> registerDeviceToken({
    required String username,
    required String platform,
    required String token,
  }) async {
    try {
      if (username.isEmpty || username.contains('|')) {
        throw Exception("Invalid username");
      }
      if (token.isEmpty || token.contains('|')) {
        throw Exception("Invalid token");
      }
      final message = "REGISTER_DEVICE|$username|$platform|$token";
      await sendMessage(message, logPreview: "REGISTER_DEVICE|$username|$platform|<token>");
      final response = await receiveMessage();
      return response.startsWith('OK');
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'registerDeviceToken error: $e',
        status: 'error',
      );
      return false;
    }
  }

  /// Send purchased asset to another user
  /// Send: SEND|asset_id|sender_username|receiver_username|tx_id|timestamp|public_key|signature
  /// Receive: OK|transaction_id or ERR|error_message
  Future<String> sendAssetToUser({
    required String assetId,
    required String senderUsername,
    required String receiverUsername,
    required String assetName,
    required String assetHash,
  }) async {
    try {
      if (assetHash.isEmpty) {
        throw Exception("Missing asset hash");
      }
      final txId = generateTxId('SEND', senderUsername, assetId: assetId);
      final timestamp = DateTime.now().toUtc().toIso8601String();
      final publicKey = await WalletKeyService.getPublicKeyBase64();
      final payload = {
        'action': 'asset_transfer',
        'tx_id': txId,
        'asset_id': assetId,
        'asset_hash': assetHash,
        'asset_name': assetName,
        'from': senderUsername,
        'to': receiverUsername,
        'amount': 0,
        'timestamp': timestamp,
      };
      final messageBytes = canonicalTxMessage(senderUsername, payload);
      final signature = await WalletKeyService.signMessage(messageBytes);
      final message =
          "SEND|$assetId|$senderUsername|$receiverUsername|$txId|$timestamp|$publicKey|$signature";

      pushMessageToScreen(
        type: 'sent',
        message:
            "SEND|$assetId|$senderUsername|$receiverUsername|$txId|$timestamp|<public_key>|<signature>",
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        final transactionId = parts.length > 1 ? parts[1] : "unknown";
        pushMessageToScreen(
          type: 'received',
          message: "Asset sent to $receiverUsername: $transactionId",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Failed to send asset: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error sending asset: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// List an owned asset for sale
  /// Send: LIST_ITEM|asset_id|username|price
  /// Receive: OK|LISTED or ERR|error_message
  Future<String> listAssetForSale({
    required String assetId,
    required String username,
    required double price,
  }) async {
    try {
      if (assetId.isEmpty || username.isEmpty) {
        throw Exception("Invalid asset or username");
      }
      if (price <= 0) {
        throw Exception("Price must be positive");
      }
      final message = "LIST_ITEM|$assetId|$username|$price";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Asset listed successfully",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Failed to list asset: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error listing asset: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Unlist an owned asset from marketplace
  /// Send: UNLIST_ITEM|asset_id|username
  /// Receive: OK|UNLISTED or ERR|error_message
  Future<String> unlistAsset({
    required String assetId,
    required String username,
  }) async {
    try {
      if (assetId.isEmpty || username.isEmpty) {
        throw Exception("Invalid asset or username");
      }
      final message = "UNLIST_ITEM|$assetId|$username";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK") {
        pushMessageToScreen(
          type: 'received',
          message: "Asset unlisted successfully",
          status: 'success',
        );
        return "success";
      } else {
        final errorMsg = parts.length > 1 ? parts[1] : "Unknown error";
        pushMessageToScreen(
          type: 'received',
          message: "Failed to unlist asset: $errorMsg",
          status: 'error',
        );
        return "error";
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error unlisting asset: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Get user profile (anonymous - username only)
  /// Send: GET_PROFILE|username
  /// Receive: OK|username|email|created_at or ERR|error_message
  Future<Map<String, String>?> getUserProfile(String username) async {
    try {
      if (username.isEmpty || username.contains('|')) {
        throw Exception("Invalid username");
      }

      final message = "GET_PROFILE|$username";

      pushMessageToScreen(
        type: 'sent',
        message: message,
        status: 'pending',
      );

      await sendMessage(message);
      final response = await receiveMessage();
      final parts = response.split('|');

      if (parts[0] == "OK" && parts.length >= 4) {
        return {
          'username': parts[1],
          'email': parts[2],
          'created_at': parts[3],
        };
      } else {
        throw Exception(parts.length > 1 ? parts[1] : "User not found");
      }
    } catch (e) {
      pushMessageToScreen(
        type: 'system',
        message: 'Error getting user profile: $e',
        status: 'error',
      );
      rethrow;
    }
  }

  /// Disconnect from server and clean up resources
  void disconnect() {
    _handleSocketDisconnected(
      'Disconnected from server',
      status: 'success',
    );
  }

  @override
  void dispose() {
    // make sure any open streams are closed
    _serverEventsController.close();
    disconnect();
    super.dispose();
  }
}
