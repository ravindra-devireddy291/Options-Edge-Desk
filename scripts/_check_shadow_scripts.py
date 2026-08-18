from pathlib import Path
import os, paramiko
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ.get('EDGE_VPS_HOST','87.232.72.137'), username='root', password=os.environ['EDGE_VPS_PASS'], timeout=45, allow_agent=False, look_for_keys=False)
cmds=[
  "chroot /mnt/sys find /root/Options-Nifty-Edge-Lab/scripts -maxdepth 1 -name '*shadow*' -o -name '*gate*' 2>/dev/null",
  "chroot /mnt/sys find /root/Options-Edge-Lab/scripts -maxdepth 1 -name '*shadow*' -o -name '*gate*' 2>/dev/null",
  "chroot /mnt/sys tail -5 /root/Options-Edge-Desk/logs/desk.out 2>/dev/null",
]
for cmd in cmds:
    _,o,e=c.exec_command(cmd, timeout=20)
    print('===', cmd)
    print(o.read().decode('utf-8','replace')[:2000])
c.close()
