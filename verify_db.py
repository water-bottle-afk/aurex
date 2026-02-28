#!/usr/bin/env python
"""Verify database contents"""
from python_files.DB_ORM import MarketplaceDB

db = MarketplaceDB()
items = db.get_all_items()

print("\n" + "=" * 100)
print("MARKETPLACE DATABASE VERIFICATION")
print("=" * 100)
print(f"\nTotal Items in Database: {len(items)}\n")

for item in items:
    print(f"   ID {item['id']:2} | Asset: {item['asset_name'].capitalize():12} | Price: ${item['cost']:6.2f}")
    print(f"    Seller: {item['username']} | Type: {item['file_type']}")
    print(f"    URL: {item['url'][:70]}...")
    print(f"    Created: {item['created_at']}\n")

print("=" * 100)
print("All items ready for asset cards in the app!")
print("=" * 100)
