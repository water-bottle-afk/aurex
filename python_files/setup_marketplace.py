"""
Populate marketplace with Google Drive image links
No downloads needed - using Drive URLs directly
"""

from marketplace_db import MarketplaceDB

# Google Drive links (in alphabetical order: deer, honeybird, jerusalem, lion, tiger, wolf)
MARKETPLACE_ITEMS = [
    {
        'asset_name': 'deer',
        'url': 'https://drive.google.com/file/d/165BGZAhaZktLEWBoh_9hH4Y3HL1tUFhj/view?usp=sharing',
        'file_type': 'jpg',
        'cost': 25.00
    },
    {
        'asset_name': 'honeybird',
        'url': 'https://drive.google.com/file/d/17BLlyH7BY_T0-7Rxp6ciM59JrURfww7i/view?usp=sharing',
        'file_type': 'jpg',
        'cost': 30.00
    },
    {
        'asset_name': 'jerusalem',
        'url': 'https://drive.google.com/file/d/1Ixi3AvnhT1-gcQ-hMlEs6NzDKbZo9utH/view?usp=sharing',
        'file_type': 'jpg',
        'cost': 40.00
    },
    {
        'asset_name': 'lion',
        'url': 'https://drive.google.com/file/d/1MksCKh0shfHfw4fMcY1vkoZ0WIEeUHzG/view?usp=sharing',
        'file_type': 'jpg',
        'cost': 35.00
    },
    {
        'asset_name': 'tiger',
        'url': 'https://drive.google.com/file/d/1lyXgwhcrIS_kXojaRxez_yR_QTGQi1xA/view?usp=sharing',
        'file_type': 'jpg',
        'cost': 45.00
    },
    {
        'asset_name': 'wolf',
        'url': 'https://drive.google.com/file/d/1tGPKxi8ivjNwoNCirgeEBhTeW47qQWcE/view?usp=sharing',
        'file_type': 'jpg',
        'cost': 50.00
    }
]

UPLOAD_USER = 'admin'


def populate_marketplace():
    """Populate marketplace with items using Google Drive links"""
    print("\n" + "="*70)
    print("💾 POPULATING MARKETPLACE DATABASE")
    print("="*70 + "\n")
    
    db = MarketplaceDB()
    
    # Add admin user if not exists
    print("✅ Setting up admin account...")
    db.add_user(UPLOAD_USER, 'admin_password_123', 'admin@aurex.local')
    
    # Add marketplace items
    print("\n📦 Adding marketplace items:\n")
    
    added_count = 0
    for item in MARKETPLACE_ITEMS:
        success, message = db.add_marketplace_item(
            asset_name=item['asset_name'],
            username=UPLOAD_USER,
            url=item['url'],
            file_type=item['file_type'],
            cost=item['cost']
        )
        
        if success:
            print(f"   ✅ {item['asset_name']:12} - ${item['cost']:6.2f}")
            added_count += 1
        else:
            print(f"   ⚠️  {item['asset_name']:12} - {message}")
    
    # Show all items
    print("\n" + "="*70)
    print("📋 MARKETPLACE INVENTORY")
    print("="*70 + "\n")
    
    items = db.get_all_items()
    for item in items:
        print(f"   {item['asset_name']:12} | ${item['cost']:6.2f} | {item['username']:10} | {item['file_type']}")
    
    print(f"\n✅ Total items: {len(items)}")
    print("✅ Marketplace setup complete!\n")


if __name__ == "__main__":
    populate_marketplace()
