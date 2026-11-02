"""Make a signing key for one probe network.

  python scripts/genkey.py --network github

Prints the PRIVATE key once (store it as a secret, e.g. GitHub secret PROBE_SIGNING_KEY_GITHUB, and nowhere else)
and writes the PUBLIC key to keys/<network>.pub, which is committed so anyone can verify the results.
Use a different key for every network.
"""
import argparse
import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

ap = argparse.ArgumentParser()
ap.add_argument("--network", required=True)
ap.add_argument("--keys", default="keys")
a = ap.parse_args()
pub_path = Path(a.keys) / f"{a.network}.pub"
if pub_path.exists():
    sys.exit(f"{pub_path} already exists. Delete it first if you really mean to replace this network's key.")
k = Ed25519PrivateKey.generate()
seed = base64.b64encode(k.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
pub = base64.b64encode(k.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
pub_path.parent.mkdir(parents=True, exist_ok=True)
pub_path.write_text(pub + "\n")
print(f"Public key written to {pub_path} (commit this).")
print("PRIVATE key, shown once. Save it as a secret now, never in the repo:")
print(seed)
