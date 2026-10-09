"""Write the owner's sign-in secrets file (release T private mode).

    python scripts/owner_auth_setup.py --out /home/alvin/services/melos/secrets/owner_auth.env --username Alvin

The password is read from standard input (or an interactive prompt), never from the command
line, so it stays out of shell history and process listings. Only an argon2id hash is written,
with a fresh random session-signing key, to a file created with mode 600. Running it again
replaces both (and so signs out every session after the next restart).
"""
from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.private_auth import hash_password, verify_password  # noqa: E402


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--username", required=True)
    args = parser.parse_args(argv)
    password = getpass.getpass("Owner password: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\r\n")
    if len(password) < 8:
        raise SystemExit("refusing a password shorter than 8 characters")
    hashed = hash_password(password)
    assert hashed.startswith("$argon2id$") and verify_password(hashed, password)
    body = (f"# Melos owner sign-in (release T). argon2id hash only; never the password.\n"
            f"MELOS_OWNER_USERNAME={args.username}\nMELOS_OWNER_PASSWORD_HASH={hashed}\n"
            f"MELOS_OWNER_SESSION_KEY={secrets.token_hex(32)}\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(args.out.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.chmod(tmp, 0o600)
    os.replace(tmp, args.out)
    print(f"wrote {args.out} (argon2id hash, mode 600)")


if __name__ == "__main__":
    main()
