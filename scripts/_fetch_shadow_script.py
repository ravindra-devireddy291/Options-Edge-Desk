from pathlib import Path
import os, paramiko
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ.get('EDGE_VPS_HOST','87.232.72.137'), username='root', password=os.environ['EDGE_VPS_PASS'], timeout=45, allow_agent=False, look_for_keys=False)
sftp=c.open_sftp()
sftp.get('/mnt/sys/root/Options-Nifty-Edge-Lab/scripts/run_shadow_daily.py', 'scripts/_vps_run_shadow_daily.py')
sftp.close(); c.close()
print('downloaded')
