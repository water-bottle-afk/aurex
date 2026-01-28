"""
Test script to fetch 10 images from the marketplace database using ORM
"""

import sys
from pathlib import Path

# Add python_files to path to import marketplace_db
sys.path.insert(0, str(Path(__file__).parent / "python_files"))

from marketplace_db import MarketplaceDB

# Initialize the database
db = MarketplaceDB()

# Get 10 images from the marketplace
images = db.get_latest_items(limit=10)

# Print the output
print("\n" + "="*80)
print("FETCHED 10 IMAGES FROM MARKETPLACE")
print("="*80 + "\n")

if images:
    print(f"Total images fetched: {len(images)}\n")
    for i, image in enumerate(images, 1):
        print(f"Image #{i}:")
        print(f"  ID: {image.get('id')}")
        print(f"  Asset Name: {image.get('asset_name')}")
        print(f"  Username: {image.get('username')}")
        print(f"  URL: {image.get('url')}")
        print(f"  File Type: {image.get('file_type')}")
        print(f"  Cost: {image.get('cost')}")
        print(f"  Created At: {image.get('created_at')}")
        print()
else:
    print("No images found in the marketplace database.")

print("="*80)
