"""
Marketplace Server Handler - Processes authentication, pagination, and upload requests
Routes messages to appropriate handlers based on message type
Message format: KEYWORD|arg1|arg2|arg3...
"""

import json
import random
from datetime import datetime, timedelta
from DB_ORM import MarketplaceDB

# Initialize database
db = MarketplaceDB()


def handle_login(args):
    """
    Handle LOGIN request
    Format: LOGIN|username|password
    Response: OK or ERR|error_message
    """
    try:
        if len(args) < 3:
            return "ERR|Missing arguments for LOGIN"
        
        username = args[1].strip()
        password = args[2].strip()
        
        if not username or not password:
            return "ERR|Username and password required"
        
        # Verify user credentials
        if db.verify_user(username, password):
            return f"OK|{username}"
        else:
            return "ERR|Invalid username or password"
    except Exception as e:
        return f"ERR|Login error: {str(e)}"


def handle_signup(args):
    """
    Handle SIGNUP request
    Format: SIGNUP|username|password|email
    Response: OK or ERR|error_message
    """
    try:
        if len(args) < 4:
            return "ERR|Missing arguments for SIGNUP"
        
        username = args[1].strip()
        password = args[2].strip()
        email = args[3].strip()
        
        if not username or not password or not email:
            return "ERR|Username, password, and email required"
        
        # Validate username length
        if len(username) < 3:
            return "ERR|Username must be at least 3 characters"
        
        # Validate email format (basic)
        if '@' not in email or '.' not in email:
            return "ERR|Invalid email format"
        
        # Try to add user
        success, message = db.add_user(username, password, email)
        
        if success:
            return f"OK|{username}"
        else:
            return f"ERR|{message}"
    except Exception as e:
        return f"ERR|Signup error: {str(e)}"


def handle_get_items(args):
    """
    Handle GET_ITEMS request
    Format: GET_ITEMS
    Returns: OK|item1|item2|item3... (JSON encoded items)
    """
    try:
        items = db.get_all_items()
        items_json = json.dumps(items)
        return f"OK|{items_json}"
    except Exception as e:
        return f"ERR|Error getting items: {str(e)}"


def handle_get_items_by_user(args):
    """
    Handle GET_ITEMS_BY_USER request
    Format: GET_ITEMS_BY_USER|username
    Returns: OK|items_json or ERR|message
    """
    try:
        if len(args) < 2:
            return "ERR|Username required"
        username = args[1].strip()
        if not username:
            return "ERR|Username required"
        items = db.get_items_by_username(username)
        return f"OK|{json.dumps(items)}"
    except Exception as e:
        return f"ERR|Error getting items: {str(e)}"


def handle_get_item(args):
    """
    Handle GET_ITEM request (single item by ID)
    Format: GET_ITEM|item_id
    Returns: OK|item_json or ERR|message
    """
    try:
        if len(args) < 2:
            return "ERR|Item ID required"
        
        item_id = args[1].strip()
        if not item_id:
            return "ERR|Item ID required"
        
        item = db.get_item_by_id(item_id)
        if item:
            item_json = json.dumps(item)
            return f"OK|{item_json}"
        else:
            return "ERR|Item not found"
    except Exception as e:
        return f"ERR|Error getting item: {str(e)}"


def handle_get_items_paginated(args):
    """
    Handle lazy scrolling pagination
    Format: GET_ITEMS_PAGINATED|limit|last_timestamp
    Examples:
    - GET_ITEMS_PAGINATED|10  (first page, 10 items)
    - GET_ITEMS_PAGINATED|10|2026-01-16T12:00:00.000000  (next page)
    Returns: OK|items_json or ERR|message
    """
    try:
        limit = 10
        last_timestamp = None
        
        if len(args) > 1:
            try:
                limit = int(args[1].strip())
            except ValueError:
                limit = 10
        
        if len(args) > 2:
            last_timestamp = args[2].strip()
        
        items = db.get_items_paginated(limit=limit, last_timestamp=last_timestamp)
        items_json = json.dumps(items)
        return f"OK|{items_json}"
    except Exception as e:
        return f"ERR|Error getting paginated items: {str(e)}"


def handle_send_verification_code(args):
    """
    Handle email verification code request
    Format: SEND_CODE|email
    Returns: OK|Code sent or ERR|message
    """
    try:
        if len(args) < 2:
            return "ERR|Email required"
        
        email = args[1].strip()
        if not email:
            return "ERR|Email required"
        
        user = db.get_user_by_email(email)
        if not user:
            return "ERR|User not found"
        
        # Generate verification code (6 digits)
        verification_code = str(random.randint(100000, 999999))
        
        # Set expiration time (5 minutes)
        reset_time = (datetime.now() + timedelta(minutes=5)).isoformat()
        user.set_verification_code(verification_code)
        user.set_reset_time(reset_time)
        
        # Update user in database
        db.update_user(user.username, user)
        
        # TODO: Send email in production
        # For now, return the code (in production, email it)
        print(f"[EMAIL] Verification code for {email}: {verification_code}")
        
        return "OK|Verification code sent"
    except Exception as e:
        return f"ERR|Error sending code: {str(e)}"


def handle_verify_code(args):
    """
    Handle email verification code verification
    Format: VERIFY_CODE|email|code
    Returns: OK|Code verified or ERR|message
    """
    try:
        if len(args) < 3:
            return "ERR|Email and code required"
        
        email = args[1].strip()
        code = args[2].strip()
        
        user = db.get_user_by_email(email)
        if not user:
            return "ERR|User not found"
        
        if user.is_code_match_and_available(datetime.now(), code):
            user.is_verified = True
            db.update_user(user.username, user)
            return "OK|Email verified"
        else:
            return "ERR|Invalid or expired code"
    except Exception as e:
        return f"ERR|Error verifying code: {str(e)}"


def handle_upload_item(args):
    """
    Handle item upload
    Format: UPLOAD|asset_name|username|google_drive_url|file_type|cost
    Returns: OK or ERR|message
    """
    try:
        if len(args) < 6:
            return "ERR|Missing arguments for UPLOAD"
        
        asset_name = args[1].strip()
        username = args[2].strip()
        url = args[3].strip()
        file_type = args[4].strip()
        
        try:
            cost = float(args[5].strip())
        except ValueError:
            return "ERR|Invalid cost format"
        
        if not asset_name or not username or not url or not file_type or cost < 0:
            return "ERR|Invalid item data"
        
        # Verify file type
        normalized_type = file_type.lower()
        if normalized_type == 'image':
            normalized_type = 'jpg'
        if normalized_type not in ['jpg', 'png', 'gif', 'jpeg']:
            return "ERR|File type must be jpg, png, gif, or jpeg"
        
        success, message = db.add_marketplace_item(asset_name, username, url, normalized_type, cost)
        
        if success:
            return "OK"
        else:
            return f"ERR|{message}"
    except Exception as e:
        return f"ERR|Upload error: {str(e)}"


def process_message(message_str):
    """
    Process incoming message from Dart client (pipe-delimited format)
    
    Format: KEYWORD|arg1|arg2|arg3...
    
    Supported commands:
    - LOGIN|username|password
    - SIGNUP|username|password|email
    - GET_ITEMS
    - GET_ITEM|item_id
    - GET_ITEMS_PAGINATED|limit|last_timestamp
    - GET_ITEMS_BY_USER|username
    - SEND_CODE|email
    - VERIFY_CODE|email|code
    - UPLOAD|asset_name|username|google_drive_url|file_type|cost
    
    Response format: OK|data or ERR|error_message
    """
    try:
        parts = message_str.strip().split('|')
        keyword = parts[0].upper()
        
        if keyword == 'LOGIN':
            return handle_login(parts)
        elif keyword == 'SIGNUP':
            return handle_signup(parts)
        elif keyword == 'GET_ITEMS':
            return handle_get_items(parts)
        elif keyword == 'GET_ITEM':
            return handle_get_item(parts)
        elif keyword == 'GET_ITEMS_PAGINATED':
            return handle_get_items_paginated(parts)
        elif keyword == 'GET_ITEMS_BY_USER':
            return handle_get_items_by_user(parts)
        elif keyword == 'SEND_CODE':
            return handle_send_verification_code(parts)
        elif keyword == 'VERIFY_CODE':
            return handle_verify_code(parts)
        elif keyword == 'UPLOAD':
            return handle_upload_item(parts)
        else:
            return f"ERR|Unknown command: {keyword}"
    
    except Exception as e:
        return f"ERR|Server error: {str(e)}"


if __name__ == "__main__":
    print("=" * 60)
    print("INITIALIZING MARKETPLACE WITH SAMPLE DATA")
    print("=" * 60 + "\n")
    
    # Sample data to insert
    sample_assets = [
        {
            "asset_name": "deer",
            "url": "https://drive.google.com/file/d/1Ixi3AvnhT1-gcQ-hMlEs6NzDKbZo9utH/view?usp=drive_link",
            "file_type": "image",
            "cost": 9.99
        },
        {
            "asset_name": "honeybird",
            "url": "https://drive.google.com/file/d/165BGZAhaZktLEWBoh_9hH4Y3HL1tUFhj/view?usp=drive_link",
            "file_type": "image",
            "cost": 7.99
        },
        {
            "asset_name": "jerusalem",
            "url": "https://drive.google.com/file/d/1lyXgwhcrIS_kXojaRxez_yR_QTGQi1xA/view?usp=drive_link",
            "file_type": "image",
            "cost": 12.99
        },
        {
            "asset_name": "lion",
            "url": "https://drive.google.com/file/d/1MksCKh0shfHfw4fMcY1vkoZ0WIEeUHzG/view?usp=drive_link",
            "file_type": "image",
            "cost": 10.99
        },
        {
            "asset_name": "tiger",
            "url": "https://drive.google.com/file/d/1tGPKxi8ivjNwoNCirgeEBhTeW47qQWcE/view?usp=drive_link",
            "file_type": "image",
            "cost": 11.99
        },
        {
            "asset_name": "wolf",
            "url": "https://drive.google.com/file/d/17BLlyH7BY_T0-7Rxp6ciM59JrURfww7i/view?usp=drive_link",
            "file_type": "image",
            "cost": 10.99
        }
    ]
    
    # Create demo admin user if doesn't exist
    print("1. Creating demo admin user...")
    result = process_message("SIGNUP|admin|admin123|admin@aurex.com")
    print(f"   {result}\n")
    
    # Insert sample assets
    print("2. Inserting sample marketplace assets...\n")
    for asset in sample_assets:
        success, message = db.add_marketplace_item(
            asset_name=asset["asset_name"],
            username="admin",
            url=asset["url"],
            file_type=asset["file_type"],
            cost=asset["cost"]
        )
        status = "✓" if success else "✗"
        print(f"   {status} {asset['asset_name'].capitalize():15} - ${asset['cost']} - {message}")
    
    print("\n" + "=" * 60)
    print("3. Fetching all marketplace items...")
    print("=" * 60 + "\n")
    
    # Get and display all items
    all_items = db.get_all_items()
    if all_items:
        print(f"Total items in marketplace: {len(all_items)}\n")
        for item in all_items:
            print(f"  ID: {item['id']}")
            print(f"  Asset: {item['asset_name']}")
            print(f"  Seller: {item['username']}")
            print(f"  Price: ${item['cost']}")
            print(f"  Type: {item['file_type']}")
            print(f"  URL: {item['url'][:60]}...")
            print(f"  Created: {item['created_at']}")
            print()
