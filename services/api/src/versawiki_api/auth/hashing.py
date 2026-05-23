"""Token hashing.

Primary path: argon2-cffi at library defaults. Argon2id is the modern
default for password / token hashing — memory-hard, side-channel
resistant, and well-supported.

Sandbox fallback: stdlib ``hashlib.scrypt``. Documented as a v1
stopgap; production environments install argon2-cffi (it's in
``pyproject.toml``'s dependency list — see BE-01's session notes).

Public API:

- :func:`hash_token` — hash a raw token; returns a self-describing
  encoded string suitable for DB storage.
- :func:`verify_token` — constant-time verify a raw token against an
  encoded hash. Returns ``False`` on any error rather than raising; the
  caller treats verification failures and shape errors identically
  (auth fails closed).

The encoded hash format is self-describing so we can swap algorithms
without a migration: argon2-cffi emits ``$argon2id$...``; the stdlib
fallback emits ``$scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`` so the
hasher used at issue time is also the hasher used at verify time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Final

# ---------------------------------------------------------------------------
# argon2 vs stdlib fallback selection
# ---------------------------------------------------------------------------

try:
    from argon2 import PasswordHasher
    from argon2 import exceptions as argon2_exceptions

    _ARGON2_AVAILABLE: Final[bool] = True
    _hasher = PasswordHasher()
except ImportError:  # pragma: no cover
    _ARGON2_AVAILABLE = False
    _hasher = None  # type: ignore[assignment]
    argon2_exceptions = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# scrypt fallback parameters (v1 stopgap)
# ---------------------------------------------------------------------------

_SCRYPT_PREFIX: Final[str] = "$scrypt$"
_SCRYPT_N: Final[int] = 2**14
_SCRYPT_R: Final[int] = 8
_SCRYPT_P: Final[int] = 1
_SCRYPT_DKLEN: Final[int] = 32
_SCRYPT_SALT_LEN: Final[int] = 16


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _scrypt_hash(raw: str) -> str:
    salt = os.urandom(_SCRYPT_SALT_LEN)
    derived = hashlib.scrypt(
        raw.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"{_SCRYPT_PREFIX}{_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64e(salt)}${_b64e(derived)}"


def _scrypt_verify(raw: str, encoded: str) -> bool:
    try:
        if not encoded.startswith(_SCRYPT_PREFIX):
            return False
        body = encoded[len(_SCRYPT_PREFIX):]
        n_s, r_s, p_s, salt_b64, hash_b64 = body.split("$")
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = _b64d(salt_b64)
        expected = _b64d(hash_b64)
        derived = hashlib.scrypt(
            raw.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
        return hmac.compare_digest(derived, expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def hash_token(raw: str) -> str:
    """Hash a raw token. Returns an encoded, self-describing string."""
    if not isinstance(raw, str) or not raw:
        raise ValueError("hash_token requires a non-empty string.")
    if _ARGON2_AVAILABLE:
        return _hasher.hash(raw)
    return _scrypt_hash(raw)


def verify_token(raw: str, encoded: str) -> bool:
    """Constant-time verify a raw token against an encoded hash."""
    if not isinstance(raw, str) or not isinstance(encoded, str):
        return False
    if not raw or not encoded:
        return False

    if encoded.startswith(_SCRYPT_PREFIX):
        return _scrypt_verify(raw, encoded)

    if _ARGON2_AVAILABLE and encoded.startswith("$argon2"):
        try:
            _hasher.verify(encoded, raw)
            return True
        except argon2_exceptions.VerifyMismatchError:
            return False
        except argon2_exceptions.InvalidHashError:
            return False
        except Exception:
            return False

    return False


# Lengths chosen so the token is short enough to be readable but provides
# >= 128 bits of entropy in the secret. Hex alphabet [0-9a-f] guarantees
# the on-wire token vw_<prefix>_<secret> is unambiguously splittable on '_'.
TOKEN_PREFIX_LEN: Final[int] = 12   # 48 bits, plenty for lookup uniqueness
TOKEN_SECRET_LEN: Final[int] = 32   # 128 bits


def generate_token_parts() -> tuple[str, str]:
    """Generate (prefix, secret) for a new API key.

    Both parts are lowercase hex strings — alphabet ``[0-9a-f]``. This
    guarantees the on-wire token ``vw_<prefix>_<secret>`` is
    unambiguously splittable on ``_`` (the underlying bug fixed in this
    revision: ``secrets.token_urlsafe()`` includes ``_`` in its alphabet
    and produced tokens that parsed back into the wrong prefix/secret).
    """
    # token_hex(n) returns 2n hex chars.
    prefix = secrets.token_hex(TOKEN_PREFIX_LEN // 2)
    secret = secrets.token_hex(TOKEN_SECRET_LEN // 2)
    return prefix, secret


__all__ = [
    "hash_token",
    "verify_token",
    "generate_token_parts",
    "TOKEN_PREFIX_LEN",
    "TOKEN_SECRET_LEN",
]
