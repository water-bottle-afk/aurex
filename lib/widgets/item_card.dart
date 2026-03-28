import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../models/item_offering.dart';
import '../services/google_drive_image_loader.dart';

class ItemCard extends StatelessWidget {
  final ItemOffering item;

  const ItemCard({super.key, required this.item});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () {
        context.go('/marketplace/item/${item.id}', extra: item);
      },
      child: Card(
        elevation: 4.0,
        margin: const EdgeInsets.all(10.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            GoogleDriveImageLoader.buildCachedImage(
              imageUrl: item.imageUrl,
              height: 200,
              width: double.infinity,
              fit: BoxFit.cover,
            ),
            Padding(
              padding: const EdgeInsets.all(12.0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    item.author,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  Text(
                    '\$${item.price.toStringAsFixed(2)}',
                    style: Theme.of(
                      context,
                    ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
