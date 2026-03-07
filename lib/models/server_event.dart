import 'dart:convert';

/// Represents an async event pushed from the server.
///
/// The server sends messages in the form `EVENT|<json>` where the JSON
/// payload contains two top‑level fields:
///
/// ```json
/// { "event": "some_event_name", "payload": { ... } }
/// ```
///
/// Providers in the app listen to the [Client.serverEvents] stream and
/// react based on the `event` string and the associated `payload` map.
class ServerEvent {
  /// Name of the event, e.g. `notification`, `marketplace_remove`, etc.
  final String event;

  /// Arbitrary JSON payload associated with the event.
  final Map<String, dynamic> payload;

  ServerEvent({required this.event, required this.payload});

  factory ServerEvent.fromMap(Map<String, dynamic> map) {
    return ServerEvent(
      event: map['event']?.toString() ?? '',
      payload: Map<String, dynamic>.from(map['payload'] ?? {}),
    );
  }

  factory ServerEvent.fromJson(String jsonStr) {
    final dynamic decoded = json.decode(jsonStr);
    if (decoded is Map<String, dynamic>) {
      return ServerEvent.fromMap(decoded);
    }
    throw FormatException('Invalid ServerEvent JSON: $jsonStr');
  }

  @override
  String toString() => 'ServerEvent(event: $event, payload: $payload)';
}
