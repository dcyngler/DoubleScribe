r"""Signs a built installer for the in-app auto-updater.

Usage:  ..\.venv\Scripts\python.exe scripts\sign_release.py installer\DoubleScribeSetup.exe
Writes installer\DoubleScribeSetup.exe.sig (base64 Ed25519 signature over the raw file
bytes) next to it. Attach BOTH files to the GitHub release -- api.py's install_update()
downloads the .sig alongside the .exe and refuses to run the installer if it's missing
or doesn't verify against UPDATE_PUBKEY_B64, falling back to the browser link instead.

Requires update-signing-key.pem in the repo root (see generate_update_key.py). That
file is gitignored and must never leave this machine / your secure backup.
"""

import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_PATH = Path(__file__).resolve().parent.parent / "update-signing-key.pem"


def main():
    if len(sys.argv) != 2:
        print("Usage: sign_release.py <path-to-installer.exe>", file=sys.stderr)
        raise SystemExit(1)

    installer_path = Path(sys.argv[1])
    if not installer_path.is_file():
        print(f"Not found: {installer_path}", file=sys.stderr)
        raise SystemExit(1)

    if not KEY_PATH.exists():
        print(f"Missing {KEY_PATH} -- run scripts/generate_update_key.py first.", file=sys.stderr)
        raise SystemExit(1)

    private_key = serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        print(f"{KEY_PATH} is not an Ed25519 key.", file=sys.stderr)
        raise SystemExit(1)

    data = installer_path.read_bytes()
    signature = private_key.sign(data)
    sig_path = installer_path.with_name(installer_path.name + ".sig")
    sig_path.write_text(base64.b64encode(signature).decode("ascii"), encoding="ascii")

    print(f"Signed {installer_path.name} -> {sig_path.name}")
    print("Attach both files to the GitHub release.")


if __name__ == "__main__":
    main()
