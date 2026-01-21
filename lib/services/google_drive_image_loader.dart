import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';

/// Utility class for loading Google Drive images
class GoogleDriveImageLoader {
  /// Convert share URL to direct view URL (if needed)
  static String convertShareUrl(String url) {
    // If already converted, return as is
    if (url.contains('export=view')) {
      return url;
    }
    
    // Convert share URL to direct view URL
    if (url.contains('/file/d/')) {
      final regex = RegExp(r'/file/d/([a-zA-Z0-9-_]+)');
      final match = regex.firstMatch(url);
      if (match != null) {
        final fileId = match.group(1);
        return 'https://drive.google.com/uc?export=view&id=$fileId';
      }
    }
    
    return url;
  }
  
  /// Get thumbnail URL from Google Drive file ID
  static String getThumbnailUrl(String url) {
    // Extract file ID
    final regex = RegExp(r'id=([a-zA-Z0-9-_]+)');
    final match = regex.firstMatch(url);
    if (match != null) {
      final fileId = match.group(1);
      return 'https://drive.google.com/thumbnail?id=$fileId&sz=w200';
    }
    return url;
  }
  
  /// Build a cached image widget for Google Drive images
  static Widget buildCachedImage({
    required String imageUrl,
    double? width,
    double? height,
    BoxFit fit = BoxFit.cover,
    BorderRadius? borderRadius,
  }) {
    final url = convertShareUrl(imageUrl);
    
    return Container(
      decoration: BoxDecoration(
        borderRadius: borderRadius ?? BorderRadius.circular(0),
      ),
      child: ClipRRect(
        borderRadius: borderRadius ?? BorderRadius.circular(0),
        child: CachedNetworkImage(
          imageUrl: url,
          width: width,
          height: height,
          fit: fit,
          placeholder: (context, url) => Container(
            color: Colors.grey[300],
            child: const Center(
              child: CircularProgressIndicator(),
            ),
          ),
          errorWidget: (context, url, error) => Container(
            color: Colors.grey[300],
            child: const Center(
              child: Icon(Icons.broken_image, color: Colors.grey),
            ),
          ),
        ),
      ),
    );
  }
}
