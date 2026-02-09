"""
Seed alice and bob users + wallets in marketplace.db (DB/marketplace.db).
Run once: python seed_alice_bob.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from DB_ORM import MarketplaceDB

def main():
    print("Seeding alice and bob in marketplace.db ...")
    db = MarketplaceDB()
    db.seed_alice_bob()
    print("Done.")

if __name__ == "__main__":
    main()
