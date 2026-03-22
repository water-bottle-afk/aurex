import hashlib
from pathlib import Path

KEY_DIR = Path(__file__).parent / "keys"

def main():
    if not KEY_DIR.exists():
        print("No keys directory found.")
        return
    for pem in sorted(KEY_DIR.glob("*_public.pem")):
        data = pem.read_bytes()
        fp = hashlib.sha256(data).hexdigest()
        print(f"{pem.name}: {fp}")

if __name__ == "__main__":
    main()
