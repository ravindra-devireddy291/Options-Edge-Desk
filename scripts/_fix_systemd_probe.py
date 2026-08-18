from pathlib import Path
import os, paramiko
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ.get('EDGE_VPS_HOST','87.232.72.137'), username='root', password=os.environ['EDGE_VPS_PASS'], timeout=45, allow_agent=False, look_for_keys=False)
cmds=[
  'mountpoint /mnt/sys/proc 2>&1; ls -la /mnt/sys/proc 2>&1 | head -5',
  'journalctl -u edge-desk --no-pager -n 15 2>&1',
  'which chroot; ls -la /usr/sbin/chroot /bin/chroot 2>&1',
]
for cmd in cmds:
    print('===', cmd)
    _,o,e=c.exec_command(cmd, timeout=20)
    print(o.read().decode('utf-8','replace')[:2000])
c.close()
