class NotificationItem {
  final int id;
  final String username;
  final String title;
  final String body;
  final String type;
  final bool isRead;
  final DateTime createdAt;
  final String? assetId;
  final String? txId;

  const NotificationItem({
    required this.id,
    required this.username,
    required this.title,
    required this.body,
    required this.type,
    required this.isRead,
    required this.createdAt,
    this.assetId,
    this.txId,
  });

  factory NotificationItem.fromMap(Map<String, dynamic> map) {
    final rawId = map['id'];
    final rawRead = map['is_read'];
    final created = map['created_at']?.toString();

    return NotificationItem(
      id: int.tryParse(rawId?.toString() ?? '') ?? 0,
      username: map['username']?.toString() ?? '',
      title: map['title']?.toString() ?? 'Notification',
      body: map['body']?.toString() ?? '',
      type: map['type']?.toString() ?? 'system',
      isRead: rawRead == 1 || rawRead == true || rawRead == '1',
      createdAt: DateTime.tryParse(created ?? '') ?? DateTime.now(),
      assetId: map['asset_id']?.toString(),
      txId: map['tx_id']?.toString(),
    );
  }

  NotificationItem copyWith({bool? isRead}) {
    return NotificationItem(
      id: id,
      username: username,
      title: title,
      body: body,
      type: type,
      isRead: isRead ?? this.isRead,
      createdAt: createdAt,
      assetId: assetId,
      txId: txId,
    );
  }
}
