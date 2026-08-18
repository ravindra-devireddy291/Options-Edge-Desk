import os, paramiko
from pathlib import Path
for line in Path(__file__).resolve().parents[1].joinpath(".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ.get("EDGE_VPS_HOST", "87.232.72.137"), username="root", password=os.environ["EDGE_VPS_PASS"], timeout=45, allow_agent=False, look_for_keys=False)
script = """
from pathlib import Path
import os
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k.strip(), v.strip())
from app.schedule import env_paper_auto, in_cash_window, paused_today
from app.session import now_ist, market_session
from app.runners.state import RUNNER
n=now_ist()
print("NOW", n.strftime("%H:%M IST %a"), "session", market_session(), "in_cash", in_cash_window(), "paper_auto_env", env_paper_auto())
print("RUNNER", RUNNER.mode, RUNNER.execution, RUNNER.state, "paused_day", RUNNER.paused_day, "kill", RUNNER.kill.active)
audit=Path("data/audit")
files=sorted(audit.glob("events_*.jsonl"))
if files:
    for ln in files[-1].read_text().splitlines()[-10:]:
        if ln.strip(): print("AUDIT", ln[:180])
"""
sftp = c.open_sftp()
with sftp.file("/mnt/sys/root/Options-Edge-Desk/scripts/_audit_check.py", "w") as f:
    f.write(script)
sftp.close()
_, o, e = c.exec_command("chroot /mnt/sys bash -lc 'cd /root/Options-Edge-Desk && /root/Options-Edge-Lab/.venv/bin/python3 scripts/_audit_check.py'", timeout=60)
print(o.read().decode())
c.close()
