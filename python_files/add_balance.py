"""
Add funds to a user's wallet in DB/marketplace.db.

Usage:
  python add_balance.py --username user --amount 100
"""

import argparse

from DB_ORM import MarketplaceDB


def main():
    """CLI entrypoint for crediting a user's wallet."""
    parser = argparse.ArgumentParser(description="Add funds to a user's wallet.")
    parser.add_argument("--username", default="user", help="Username to credit.")
    parser.add_argument("--amount", type=float, default=100.0, help="Amount to add.")
    args = parser.parse_args()

    db = MarketplaceDB()
    user = db.get_user(args.username)
    if not user:
        print(f"User not found: {args.username}")
        return 1

    db.ensure_wallet(args.username, 0)
    wallet = db.get_wallet(args.username)
    if not wallet:
        print(f"Wallet not found: {args.username}")
        return 1

    new_balance = float(wallet.get("balance", 0.0)) + float(args.amount)
    ok = db.update_balance(args.username, new_balance)
    if not ok:
        print(f"Failed to update balance for {args.username}")
        return 1

    wallet = db.get_wallet(args.username)
    balance = wallet["balance"] if wallet else "N/A"
    print(f"Credited {args.amount:.2f} to {args.username}. New balance: {balance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
