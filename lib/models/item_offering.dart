class ItemOffering {
  final String id;
  final String title;
  final String description;
  final String imageUrl;
  final String author;
  final double price;
  final bool isListed;
  final String? token; // Blockchain asset token
  final String? assetHash;

  ItemOffering({
    required this.id,
    required this.title,
    required this.description,
    required this.imageUrl,
    required this.author,
    required this.price,
    this.isListed = true,
    this.token,
    this.assetHash,
  });

  /// Maps server JSON keys to model fields.
  /// Server sends: id, asset_name, description, username, url, cost, is_listed, asset_hash
  factory ItemOffering.fromJson(Map<String, dynamic> json) {
    final rawId = json['id']?.toString() ?? '';
    return ItemOffering(
      id: rawId,
      title: json['asset_name']?.toString() ?? 'Unnamed Asset',
      description: json['description']?.toString() ??
          json['file_type']?.toString() ??
          'No description provided.',
      imageUrl: json['url']?.toString() ?? '',
      author: json['username']?.toString() ?? 'Unknown',
      price: double.tryParse(json['cost']?.toString() ?? '0') ?? 0.0,
      isListed: (json['is_listed']?.toString() ?? '1') == '1',
      token: rawId,
      assetHash: json['asset_hash']?.toString(),
    );
  }
}
