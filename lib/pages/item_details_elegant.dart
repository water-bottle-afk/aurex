import 'package:flutter/material.dart';
import '../services/google_drive_image_loader.dart';
import 'marketplace_page_v2.dart';

/// Item Details Page - Elegant display
class ItemDetailsPage extends StatefulWidget {
  final MarketplaceItem item;

  const ItemDetailsPage({super.key, required this.item});

  @override
  State<ItemDetailsPage> createState() => _ItemDetailsPageState();
}

class _ItemDetailsPageState extends State<ItemDetailsPage> {
  bool isFavorite = false;
  int quantity = 1;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          // App bar with image
          SliverAppBar(
            expandedHeight: 300,
            pinned: true,
            flexibleSpace: FlexibleSpaceBar(
              background: GoogleDriveImageLoader.buildCachedImage(
                imageUrl: widget.item.url,
                fit: BoxFit.cover,
              ),
            ),
            actions: [
              Container(
                margin: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: IconButton(
                  icon: Icon(
                    isFavorite ? Icons.favorite : Icons.favorite_border,
                    color: isFavorite ? Colors.red : Colors.grey,
                  ),
                  onPressed: () {
                    setState(() => isFavorite = !isFavorite);
                  },
                ),
              ),
            ],
          ),
          
          // Details
          SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Asset name and rating
                Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Expanded(
                            child: Text(
                              widget.item.assetName,
                              style: const TextStyle(
                                fontSize: 28,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                          const SizedBox(width: 16),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                              Text(
                                '\$${widget.item.cost.toStringAsFixed(2)}',
                                style: const TextStyle(
                                  fontSize: 32,
                                  fontWeight: FontWeight.bold,
                                  color: Colors.green,
                                ),
                              ),
                              const Text(
                                'USD',
                                style: TextStyle(fontSize: 12, color: Colors.grey),
                              ),
                            ],
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      const Row(
                        children: [
                          Icon(Icons.star, color: Colors.orange, size: 20),
                          SizedBox(width: 4),
                          Text('4.8', style: TextStyle(fontWeight: FontWeight.bold)),
                          Text(' (124 reviews)', style: TextStyle(color: Colors.grey)),
                        ],
                      ),
                    ],
                  ),
                ),
                
                // Creator info
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.grey[100],
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 50,
                          height: 50,
                          decoration: BoxDecoration(
                            color: Colors.blue,
                            borderRadius: BorderRadius.circular(25),
                          ),
                          child: Center(
                            child: Text(
                              widget.item.username[0].toUpperCase(),
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 24,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'by ${widget.item.username}',
                                style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 14,
                                ),
                              ),
                              Text(
                                'Verified Creator ✓',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: Colors.grey[600],
                                ),
                              ),
                            ],
                          ),
                        ),
                        ElevatedButton(
                          onPressed: () {},
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.blue,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(8),
                            ),
                          ),
                          child: const Text('Follow'),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                
                // Description
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'About',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'This is a beautiful digital asset. Created with attention to detail and professional quality.',
                        style: TextStyle(
                          fontSize: 14,
                          color: Colors.grey[700],
                          height: 1.6,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 20),
                
                // Details
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Details',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 12),
                      _buildDetailRow('File Type', widget.item.fileType.toUpperCase()),
                      _buildDetailRow('Created', widget.item.timestamp),
                      _buildDetailRow('Format', 'Digital Asset'),
                      _buildDetailRow('License', 'Personal Use'),
                    ],
                  ),
                ),
                const SizedBox(height: 30),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: Colors.white,
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.1),
              blurRadius: 10,
            ),
          ],
        ),
        child: Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: () {
                  setState(() {
                    if (quantity > 1) quantity--;
                  });
                },
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                ),
                child: const Text('-', style: TextStyle(fontSize: 20)),
              ),
            ),
            const SizedBox(width: 12),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
              decoration: BoxDecoration(
                color: Colors.grey[200],
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                quantity.toString(),
                style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: OutlinedButton(
                onPressed: () {
                  setState(() => quantity++);
                },
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                ),
                child: const Text('+', style: TextStyle(fontSize: 20)),
              ),
            ),
            const SizedBox(width: 20),
            Expanded(
              flex: 2,
              child: ElevatedButton(
                onPressed: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(
                        'Added $quantity item(s) to cart!',
                      ),
                      duration: const Duration(seconds: 2),
                    ),
                  );
                },
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.green,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8),
                  ),
                ),
                child: const Text(
                  'Buy Now',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDetailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: TextStyle(color: Colors.grey[600]),
          ),
          Text(
            value,
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        ],
      ),
    );
  }
}
