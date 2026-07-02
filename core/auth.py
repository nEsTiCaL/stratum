"""API-Key-Generierung und Hashing fuer das Ownership-System (I-REST.2).

Schluessel werden NICHT im Klartext gespeichert. generate_api_key() gibt den
Schluessel einmalig aus; ab dann ist nur der Hash in der DB. Verwaltung per CLI:
  python -m core.auth create <owner>
"""

from __future__ import annotations

import hashlib
import secrets

_PREFIX = "sk-stratum-"
_PREFIX_DISPLAY_LEN = len(_PREFIX) + 8  # "sk-stratum-" + erste 8 Hex-Zeichen


def generate_api_key() -> str:
    """Erzeugt einen neuen API-Schluessel. Nur einmalig lesbar."""
    return _PREFIX + secrets.token_hex(32)


def hash_key(key: str) -> str:
    """SHA-256-Hash des Schluessels — wird in der DB gespeichert."""
    return hashlib.sha256(key.encode()).hexdigest()


def key_prefix_display(key: str) -> str:
    """Kurzform fuer die Anzeige (nie der volle Schluessel)."""
    return key[:_PREFIX_DISPLAY_LEN]


if __name__ == "__main__":
    import sys

    from core.db import connect
    from core.repository import Repository

    def _usage() -> None:
        print("Verwendung: python -m core.auth create <owner>", file=sys.stderr)
        sys.exit(2)

    if len(sys.argv) < 3 or sys.argv[1] != "create":
        _usage()

    owner = sys.argv[2].strip()
    if not owner:
        _usage()

    key = generate_api_key()
    conn = connect(autocommit=True)
    repo = Repository(conn)
    repo.register_capability(owner, hash_key(key), key_prefix_display(key))

    print(f"Owner  : {owner}")
    print(f"API-Key: {key}")
    print("(Schluessel einmalig sichtbar — sicher verwahren.)")
