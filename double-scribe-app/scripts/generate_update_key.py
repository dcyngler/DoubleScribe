r"""One-time setup for the in-app auto-updater's signature check.

Generates an Ed25519 keypair:
  - the PRIVATE key is written to update-signing-key.pem (repo root) -- gitignored,
    used by scripts/sign_release.py to sign each release's installer.
  - the PUBLIC key is printed as a base64 string -- paste it into UPDATE_PUBKEY_B64
    in app/api.py. It's safe to commit; it only lets the app *verify* signatures,
    not create them.

Run once with:  ..\.venv\Scripts\python.exe scripts\generate_update_key.py
Re-running overwrites the existing key -- don't, unless you intend to rotate it
(which invalidates the ability to verify any update signed with the old key, so
every installed copy would need the new pubkey shipped to it first via an update
signed with the OLD key).
"""

import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_PATH = Path(__file__).resolve().parent.parent / "update-signing-key.pem"


def main():
    if KEY_PATH.exists():
        print(f"{KEY_PATH} already exists -- refusing to overwrite. Delete it first if you", file=sys.stderr)
        print("really mean to rotate the signing key.", file=sys.stderr)
        raise SystemExit(1)

    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    KEY_PATH.write_bytes(pem)

    public_key = private_key.public_key()
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pubkey_b64 = base64.b64encode(raw).decode("ascii")

    print(f"Wrote private key: {KEY_PATH}")
    print()
    print("Back this file up somewhere safe OUTSIDE the repo (password manager, offline")
    print("drive, etc). It never gets committed -- it's the only thing that can produce")
    print("a signature the shipped app will accept.")
    print()
    print("Now paste this into UPDATE_PUBKEY_B64 in app/api.py:")
    print()
    print(f'    UPDATE_PUBKEY_B64 = "{pubkey_b64}"')


if __name__ == "__main__":
    main()
