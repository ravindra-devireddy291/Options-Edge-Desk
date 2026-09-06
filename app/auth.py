"""Auth + settings for Options Edge Desk."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException, WebSocket


def _load_dotenv() -> None:
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    if not env_path.exists():
        # also try parent labs' .env for local Dhan creds
        for alt in (
            Path(os.environ.get("NIFTY_LAB_ROOT", "D:/Options-Nifty-Edge-Lab")) / ".env",
            Path(os.environ.get("BN_LAB_ROOT", "D:/Options-Edge-Lab")) / ".env",
        ):
            if alt.exists():
                env_path = alt
                break
        else:
            return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if not k:
            continue
        if k in os.environ:
            continue
        os.environ[k] = v


@dataclass(frozen=True)
class Settings:
    desk_api_key: str
    desk_mode: str
    nifty_lab_root: Path
    bn_lab_root: Path
    nifty_config: str
    bn_config: str
    live_nifty: bool
    live_banknifty: bool
    live_enabled: bool
    mock_loop: bool
    audit_dir: Path
    bff_secret: str


def _secrets_match(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    a, b = provided.encode("utf-8"), expected.encode("utf-8")
    if len(a) != len(b):
        secrets.compare_digest(b, b)
        return False
    return secrets.compare_digest(a, b)


def cors_allowed_origins() -> list[str]:
    """Empty when BFF secret is set — browsers must not call deskapi."""
    _load_dotenv()
    if (os.environ.get("DESK_BFF_SECRET") or "").strip():
        return []
    raw = (os.environ.get("CORS_ALLOWED_ORIGINS") or "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "https://desk.ravindra-devireddy.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    key = (os.environ.get("DESK_API_KEY") or "").strip()
    if not key:
        # local-dev fallback so scaffold boots; production must set DESK_API_KEY
        key = "dev-desk-key-" + secrets.token_hex(4)
        os.environ["DESK_API_KEY"] = key
    root = Path(__file__).resolve().parents[1]
    # Windows laptop vs Linux VPS defaults
    if os.name == "nt":
        nifty_default = "D:/Options-Nifty-Edge-Lab"
        bn_default = "D:/Options-Edge-Lab"
    else:
        nifty_default = "/root/Options-Nifty-Edge-Lab"
        bn_default = "/root/Options-Edge-Lab"
    return Settings(
        desk_api_key=key,
        desk_mode=(os.environ.get("DESK_MODE") or "paper").strip().lower(),
        nifty_lab_root=Path(os.environ.get("NIFTY_LAB_ROOT") or nifty_default),
        bn_lab_root=Path(os.environ.get("BN_LAB_ROOT") or bn_default),
        nifty_config=os.environ.get("NIFTY_CONFIG")
        or "config/rungs/nifty_alpha.yaml",
        bn_config=os.environ.get("BN_CONFIG") or "config/rungs/bn_alpha.yaml",
        live_nifty=os.environ.get("LIVE_NIFTY", "0").strip() in ("1", "true", "yes"),
        live_banknifty=os.environ.get("LIVE_BANKNIFTY", "0").strip() in ("1", "true", "yes"),
        live_enabled=os.environ.get("DESK_LIVE_ENABLED", "0").strip().lower() in ("1", "true", "yes"),
        mock_loop=os.environ.get("DESK_MOCK_LOOP", "0").strip().lower() in ("1", "true", "yes"),
        audit_dir=root / "data" / "audit",
        bff_secret=(os.environ.get("DESK_BFF_SECRET") or "").strip(),
    )


def require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    x_desk_bff: Optional[str] = Header(default=None, alias="X-Desk-BFF"),
) -> None:
    settings = get_settings()
    provided = (x_api_key or "").strip()
    if not _secrets_match(provided, settings.desk_api_key):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    if settings.bff_secret and not _secrets_match((x_desk_bff or "").strip(), settings.bff_secret):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def http_client_authorized(api_key: str, bff: str) -> bool:
    settings = get_settings()
    if not _secrets_match((api_key or "").strip(), settings.desk_api_key):
        return False
    if settings.bff_secret and not _secrets_match((bff or "").strip(), settings.bff_secret):
        return False
    return True


async def require_ws_api_key(websocket: WebSocket) -> bool:
    settings = get_settings()
    key = (
        (websocket.headers.get("x-api-key") or "")
        or (websocket.query_params.get("api_key") or "")
    ).strip()
    if not _secrets_match(key, settings.desk_api_key):
        await websocket.close(code=4401)
        return False
    if settings.bff_secret:
        bff = (websocket.headers.get("x-desk-bff") or "").strip()
        if not _secrets_match(bff, settings.bff_secret):
            await websocket.close(code=4401)
            return False
    return True
