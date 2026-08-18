from pathlib import Path
import os, paramiko
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ.get('EDGE_VPS_HOST','87.232.72.137'), username='root', password=os.environ['EDGE_VPS_PASS'], timeout=45, allow_agent=False, look_for_keys=False)
cmds=[
  'journalctl -u cloudflared --no-pager -n 40 2>&1 || true',
  'ls -la /var/log/cloudflared* 2>&1; tail -30 /var/log/cloudflared.log 2>&1 || true',
  'cat /proc/18777/cwd 2>/dev/null; tr "\\0" " " < /proc/18777/cmdline 2>/dev/null; echo',
  'ls -la /proc/18777/root 2>/dev/null | head -3',
  'curl -s -o /dev/null -w "%{http_code}" --max-time 10 -H "Host: deskapi.ravindra-devireddy.com" http://127.0.0.1:8080/healthz; echo',
]
for cmd in cmds:
    print('===', cmd[:70])
    _,o,e=c.exec_command(cmd, timeout=30)
    print(o.read().decode('utf-8','replace')[:2500])
c.close()
