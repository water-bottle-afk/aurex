import 'dart:convert';
import 'package:cryptography/cryptography.dart';
import 'package:shared_preferences/shared_preferences.dart';

class WalletKeyService {
  static const _privateKeyKey = 'wallet_private_key';
  static const _publicKeyKey = 'wallet_public_key';
  static final _algo = Ed25519();

  static Future<SimpleKeyPairData> _loadKeyPairData() async {
    final prefs = await SharedPreferences.getInstance();
    final privB64 = prefs.getString(_privateKeyKey);
    final pubB64 = prefs.getString(_publicKeyKey);

    if (privB64 != null && pubB64 != null) {
      final priv = base64Decode(privB64);
      final pub = base64Decode(pubB64);
      return SimpleKeyPairData(
        priv,
        publicKey: SimplePublicKey(pub, type: KeyPairType.ed25519),
        type: KeyPairType.ed25519,
      );
    }

    final keyPair = await _algo.newKeyPair();
    final data = await keyPair.extract();
    await prefs.setString(_privateKeyKey, base64Encode(data.bytes));
    await prefs.setString(_publicKeyKey, base64Encode(data.publicKey.bytes));
    return data;
  }

  static Future<String> getPublicKeyBase64() async {
    final data = await _loadKeyPairData();
    return base64Encode(data.publicKey.bytes);
  }

  static Future<String> signMessage(List<int> messageBytes) async {
    final data = await _loadKeyPairData();
    final signature = await _algo.sign(messageBytes, keyPair: data);
    return base64Encode(signature.bytes);
  }
}
