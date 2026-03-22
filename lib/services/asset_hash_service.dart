import 'dart:io';
import 'package:crypto/crypto.dart';

class AssetHashService {
  static Future<String> sha256File(File file) async {
    final digest = await sha256.bind(file.openRead()).first;
    return digest.toString();
  }
}
