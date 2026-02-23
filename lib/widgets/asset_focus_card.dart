import 'package:flutter/material.dart';
import '../models/item_offering.dart';
import '../services/google_drive_image_loader.dart';

class AssetFocusCard extends StatelessWidget {
  final ItemOffering asset;
  final VoidCallback? onPrimaryAction;
  final String primaryActionLabel;

  const AssetFocusCard({
    super.key,
    required this.asset,
    this.onPrimaryAction,
    this.primaryActionLabel = 'Buy Now',
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final price = '\$${asset.price.toStringAsFixed(2)}';

    return Card(
      elevation: 6,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AspectRatio(
            aspectRatio: 4 / 3,
            child: Stack(
              fit: StackFit.expand,
              children: [
                GoogleDriveImageLoader.buildCachedImage(
                  imageUrl: asset.imageUrl,
                  fit: BoxFit.cover,
                ),
                Container(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [
                        Colors.transparent,
                        Colors.black.withOpacity(0.35),
                      ],
                    ),
                  ),
                ),
                Positioned(
                  left: 16,
                  bottom: 16,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: Colors.white.withOpacity(0.9),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Text(
                      price,
                      style: theme.textTheme.labelLarge?.copyWith(
                        color: Colors.green[700],
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(20.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  asset.title,
                  style: theme.textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  asset.description.isNotEmpty
                      ? asset.description
                      : 'No description provided.',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: Colors.grey[700],
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: 16),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.blueGrey[50],
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.blueGrey[100]!),
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.verified_user, color: Colors.blueGrey[600]),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'Owner ID: ${asset.author}',
                          style: theme.textTheme.bodySmall?.copyWith(
                            fontWeight: FontWeight.w600,
                            color: Colors.blueGrey[800],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 18),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green[600],
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                    onPressed: onPrimaryAction,
                    child: Text(primaryActionLabel),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
