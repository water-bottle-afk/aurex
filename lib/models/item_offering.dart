class ItemOffering {
  final String id;
  final String title;
  final String description;
  final String imageUrl;
  final String author;
  final double price;
  final String? token; // Blockchain asset token

  ItemOffering({
    required this.id,
    required this.title,
    required this.description,
    required this.imageUrl,
    required this.author,
    required this.price,
    this.token,
  });
}
