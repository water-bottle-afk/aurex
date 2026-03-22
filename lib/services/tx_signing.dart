import 'dart:collection';
import 'dart:convert';

List<int> canonicalTxMessage(String sender, Map<String, dynamic> data) {
  final payload = <String, dynamic>{
    'sender': sender,
    'data': _sortJson(data),
  };
  final sorted = _sortJson(payload);
  final jsonStr = jsonEncode(sorted);
  return utf8.encode(jsonStr);
}

dynamic _sortJson(dynamic value) {
  if (value is Map) {
    final sorted = SplayTreeMap<String, dynamic>();
    value.forEach((key, val) {
      sorted[key.toString()] = _sortJson(val);
    });
    return sorted;
  }
  if (value is List) {
    return value.map(_sortJson).toList();
  }
  return value;
}
