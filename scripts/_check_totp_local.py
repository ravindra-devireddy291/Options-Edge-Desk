from pathlib import Path


def check(p: Path) -> dict:
    print(f"--- {p}")
    if not p.exists():
        print("  MISSING FILE")
        return {}
    keys: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        keys[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN", "DHAN_PIN", "DHAN_TOTP_SECRET"):
        v = keys.get(k)
        if v is None:
            print(f"  {k}: absent")
        elif not v:
            print(f"  {k}: empty")
        elif k == "DHAN_CLIENT_ID":
            print(f"  {k}: set ({v})")
        elif k == "DHAN_PIN":
            print(f"  {k}: set (len={len(v)}, digits={v.isdigit()})")
        elif k == "DHAN_TOTP_SECRET":
            clean = v.replace(" ", "").upper()
            print(
                f"  {k}: set (len={len(clean)}, "
                f"base32ish={clean.replace('=', '').isalnum()})"
            )
        else:
            print(f"  {k}: set (len={len(v)})")
    return keys


desk = check(Path(r"D:\Options-Edge-Desk\.env"))
nifty = check(Path(r"D:\Options-Nifty-Edge-Lab\.env"))
bn = check(Path(r"D:\Options-Edge-Lab\.env"))

pin = desk.get("DHAN_PIN") or nifty.get("DHAN_PIN") or bn.get("DHAN_PIN") or ""
totp = (
    desk.get("DHAN_TOTP_SECRET")
    or nifty.get("DHAN_TOTP_SECRET")
    or bn.get("DHAN_TOTP_SECRET")
    or ""
)
cid = (
    desk.get("DHAN_CLIENT_ID")
    or nifty.get("DHAN_CLIENT_ID")
    or bn.get("DHAN_CLIENT_ID")
    or ""
)
ready = bool(cid and pin and totp)
print("--- READY FOR VPS PUSH" if ready else "--- NOT READY (need CLIENT_ID + PIN + TOTP_SECRET)")
print(f"will_use_client={bool(cid)} will_use_pin={bool(pin)} will_use_totp={bool(totp)}")
