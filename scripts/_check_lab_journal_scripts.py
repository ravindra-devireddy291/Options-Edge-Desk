from pathlib import Path
import os, paramiko
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ.get('EDGE_VPS_HOST','87.232.72.137'), username='root', password=os.environ['EDGE_VPS_PASS'], timeout=45, allow_agent=False, look_for_keys=False)
cmds=[
  'chroot /mnt/sys ls -la /root/Options-Nifty-Edge-Lab/scripts/run_shadow_journal.py /root/Options-Nifty-Edge-Lab/scripts/check_execution_gate.py 2>&1',
  'chroot /mnt/sys ls -la /root/Options-Edge-Lab/scripts/run_shadow_journal.py /root/Options-Edge-Lab/scripts/check_execution_gate.py 2>&1',
  'chroot /mnt/sys grep -l run_shadow_journal /root/Options-Edge-Lab/scripts/*.py 2>/dev/null | head -5',
]
for cmd in cmds:
    _,o,e=c.exec_command(cmd, timeout=30)
    out=o.read().decode('utf-8','replace')
    print('===', cmd.split('/root/')[-1][:60])
    print(out)
c.close()
