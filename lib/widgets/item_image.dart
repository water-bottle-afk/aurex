import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/assets_provider.dart';

/// Renders a server-stored image from [AssetsProvider.imageCache].
///
/// Shows a [CircularProgressIndicator] while the background queue has not yet
/// fetched [relPath], and a grey placeholder for empty paths or failed fetches.
/// If [relPath] is not already queued, this widget kicks off the download via
/// [AssetsProvider.enqueueUrl] in a post-frame callback.
class ItemImage extends StatelessWidget {
  final String relPath;
  final BoxFit fit;
  final double? width;
  final double? height;

  const ItemImage({
    super.key,
    required this.relPath,
    this.fit = BoxFit.cover,
    this.width,
    this.height,
  });

  @override
  Widget build(BuildContext context) {
    if (relPath.isEmpty) return _placeholder(width, height);

    final bytes = context.select<AssetsProvider, Uint8List?>(
      (p) => p.imageCache[relPath],
    );

    if (bytes == null) {
      Provider.of<AssetsProvider>(context, listen: false).enqueueUrl(relPath);
      return _loading(width, height);
    }

    if (bytes.isEmpty) {
      // Empty sentinel inserted by AssetsProvider on download failure.
      return _placeholder(width, height);
    }

    return Image.memory(
      bytes,
      fit: fit,
      width: width,
      height: height,
      errorBuilder: (_, __, ___) => _placeholder(width, height),
    );
  }
}

Widget _placeholder(double? width, double? height) => Container(
      width: width,
      height: height,
      color: Colors.grey[200],
      child: const Center(
        child: Icon(Icons.image_not_supported_outlined, size: 40, color: Colors.grey),
      ),
    );

Widget _loading(double? width, double? height) => Container(
      width: width,
      height: height,
      color: Colors.grey[300],
      child: Center(
        child: Icon(Icons.image, color: Colors.grey[600]),
      ),
    );
