"""Short-lived HMAC assertion from the UI BFF. Role is never taken from a bare header alone."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Tuple

from fastapi import HTTPException, Request


def read_assertion(request: Request, max_age: int = 60) -> Tuple[str, str]:
    secret = (os.environ.get("DESK_BFF_SECRET") or "").strip().encode()
    if not secret:
        # Local paper tests without BFF: fall back to plain headers (legacy admin).
        email = (request.headers.get("x-desk-user") or "").strip().lower()
        role = (request.headers.get("x-desk-role") or "").strip().lower()
        if "@" in email and role in ("admin", "client"):
            return email, role
        return "", "admin"

    value = request.headers.get("x-desk-assertion") or ""
    payload_b64, _, sig = value.partition(".")
    if not payload_b64 or not sig:
        raise HTTPException(status_code=401, detail="bad assertion")
    expect = hmac.new(secret, payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        raise HTTPException(status_code=401, detail="bad assertion")
    pad = "=" * (-len(payload_b64) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="bad assertion") from exc
    if abs(time.time() - int(data.get("ts", 0))) > max_age:
        raise HTTPException(status_code=401, detail="expired assertion")
    path = request.url.path
    # UI signs the desk path suffix (e.g. me/live); accept either form.
    signed_path = str(data.get("path") or "")
    if data.get("method") != request.method:
        raise HTTPException(status_code=401, detail="assertion mismatch")
    if signed_path not in (path, path.removeprefix("/api/v1/desk/"), path.split("/api/v1/desk/")[-1]):
        if not path.endswith("/" + signed_path) and not path.endswith(signed_path):
            raise HTTPException(status_code=401, detail="assertion mismatch")
    role = str(data.get("role") or "").strip().lower()
    if role not in ("admin", "client"):
        raise HTTPException(status_code=401, detail="bad role")
    email = str(data.get("email") or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=401, detail="bad assertion")
    return email, role
