import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/item_offering.dart';

class MarketplacePage extends StatelessWidget {
  const MarketplacePage({super.key});

  @override
  Widget build(BuildContext context) {
    final List<ItemOffering> items = [
      ItemOffering(
        id: '1',
        title: 'Vintage Leather Jacket',
        description: 'A stylish vintage leather jacket from the 80s.',
        imageUrl: 'assets/images/leather_jacket.png',
        author: 'Cool Finds',
        price: 75.00,
      ),
      ItemOffering(
        id: '2',
        title: 'Retro Sunglasses',
        description: 'Fashionable sunglasses with a retro vibe.',
        imageUrl: 'assets/images/sunglasses.png',
        author: 'Sunny Styles',
        price: 25.00,
      ),
      ItemOffering(
        id: '3',
        title: 'Classic Wristwatch',
        description: 'An elegant and timeless wristwatch.',
        imageUrl: 'assets/images/wristwatch.png',
        author: 'Timepieces Co.',
        price: 120.00,
      ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text('Marketplace'),
      ),
      body: GridView.builder(
        padding: const EdgeInsets.all(10.0),
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 2,
          crossAxisSpacing: 10.0,
          mainAxisSpacing: 10.0,
          childAspectRatio: 0.8,
        ),
        itemCount: items.length,
        itemBuilder: (context, index) {
          final item = items[index];
          return GestureDetector(
            onTap: () => context.go('/marketplace/item/${item.id}', extra: item),
            child: Card(
              clipBehavior: Clip.antiAlias,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Image.asset(
                      item.imageUrl,
                      fit: BoxFit.cover,
                      width: double.infinity,
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.all(8.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          item.title,
                          style: const TextStyle(
                            fontWeight: FontWeight.bold,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '\$${item.price.toStringAsFixed(2)}',
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.primary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}
