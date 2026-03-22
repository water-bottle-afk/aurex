import 'dart:math';

String generateTxId(String prefix, String username, {String? assetId}) {
  final now = DateTime.now().toUtc().millisecondsSinceEpoch;
  final rand = Random.secure().nextInt(1 << 32).toRadixString(16);
  final parts = <String>[
    prefix,
    username,
    if (assetId != null && assetId.isNotEmpty) assetId,
    now.toString(),
    rand,
  ];
  return parts.join('_').replaceAll(RegExp(r'[^A-Za-z0-9_]'), '');
}
