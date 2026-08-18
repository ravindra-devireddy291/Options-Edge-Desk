from pathlib import Path
import json, os, paramiko

for line in Path(".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

py = r"""
import json, urllib.request
from pathlib import Path
key = next((ln.split('=',1)[1].strip().strip('"') for ln in Path('/root/Options-Edge-Desk/.env').read_text().splitlines() if ln.startswith('DESK_API_KEY=')), '')
req = urllib.request.Request('http://127.0.0.1:8080/api/v1/desk/status', headers={'X-API-Key': key})
with urllib.request.urlopen(req, timeout=20) as r:
    d = json.loads(r.read()).get('data') or {}
out = {
    'mode': d.get('mode'),
    'execution': d.get('execution'),
    'trading_active': d.get('trading_active'),
    'runner_state': d.get('runner_state'),
    'replay': d.get('replay'),
    'paper_saved': d.get('paper_saved'),
    'open_positions': d.get('open_positions'),
    'signals_today': d.get('signals_today'),
    'trades_today': d.get('trades_today'),
}
print(json.dumps(out, indent=2, default=str))
"""
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ.get("EDGE_VPS_HOST", "87.232.72.137"), username="root", password=os.environ["EDGE_VPS_PASS"], timeout=45, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/mnt/sys/root/Options-Edge-Desk/scripts/_status_probe.py", "w") as f:
    f.write(py)
sftp.close()
_, o, e = c.exec_command(
    "chroot /mnt/sys /root/Options-Edge-Lab/.venv/bin/python3 /root/Options-Edge-Desk/scripts/_status_probe.py",
    timeout=40,
)
print(o.read().decode("utf-8", "replace"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("ERR", err[:500])
c.close()
