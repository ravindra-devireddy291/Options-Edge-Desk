from pathlib import Path


def parse(p: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


nifty = parse(Path(r"D:\Options-Nifty-Edge-Lab\.env"))
desk_path = Path(r"D:\Options-Edge-Desk\.env")
desk = parse(desk_path)

for k in ("DHAN_CLIENT_ID", "DHAN_PIN", "DHAN_TOTP_SECRET"):
    if nifty.get(k):
        desk[k] = nifty[k]

# keep structure with comments via rewrite of known keys
lines = desk_path.read_text(encoding="utf-8").splitlines()
out_lines = []
seen = set()
for line in lines:
    if "=" in line and not line.strip().startswith("#"):
        k = line.split("=", 1)[0].strip()
        if k in desk:
            out_lines.append(f"{k}={desk[k]}")
            seen.add(k)
            continue
    out_lines.append(line)
for k in ("DHAN_CLIENT_ID", "DHAN_PIN", "DHAN_TOTP_SECRET"):
    if k in desk and k not in seen:
        out_lines.append(f"{k}={desk[k]}")
desk_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
print(
    "synced desk .env from nifty:",
    f"pin_len={len(desk.get('DHAN_PIN') or '')}",
    f"totp_len={len(desk.get('DHAN_TOTP_SECRET') or '')}",
)
