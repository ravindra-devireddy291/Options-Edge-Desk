"""RFC 6238 TOTP from a base32 secret. Stdlib only."""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time


def totp_now(secret: str, *, step: int = 30, digits: int = 6) -> str:
    padded = secret.strip().upper().replace(" ", "")
    padded += "=" * ((8 - len(padded) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    counter = int(time.time()) // step
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)
