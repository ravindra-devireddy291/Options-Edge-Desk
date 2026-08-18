from pathlib import Path
import os, paramiko
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ.get('EDGE_VPS_HOST','87.232.72.137'), username='root', password=os.environ['EDGE_VPS_PASS'], timeout=45, allow_agent=False, look_for_keys=False)
cmds=[
  "journalctl -u cloudflared --no-pager --since '2026-08-17 11:00' 2>&1 | grep ERR | tail -25",
  "grep -E 'connection refused|Unable to reach|dial tcp|502' /var/log/cloudflared-quick.log 2>/dev/null | tail -15",
  "grep originService /var/log/cloudflared-quick.log 2>/dev/null | tail -5",
]
for cmd in cmds:
    print('===', cmd[:70])
    _,o,e=c.exec_command(cmd, timeout=30)
    print(o.read().decode('utf-8','replace')[:3500])
c.close()
