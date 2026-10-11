"""Apply the public 4-file patch to a fresh ignored copy; preserve original checkout."""
from pathlib import Path
import ast
import shutil
import subprocess
ROOT=Path(__file__).resolve().parent.parent
original=ROOT/'cmdbox';dest=ROOT/'app-lab'/'cmdbox-public'
pin='a429260512035aa358d49e7b319c2bfc56532742'
assert subprocess.check_output(['git','-C',str(original),'rev-parse','HEAD'],text=True).strip()==pin
assert not subprocess.check_output(['git','-C',str(original),'status','--porcelain'],text=True).strip()
assert not dest.exists(), 'Refuse to overwrite an existing independent copy'
shutil.copytree(original,dest,ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc'))
patch=ROOT/'patches'/'cmdbox-uid-gateway.diff'
subprocess.run(['git','apply','--check',str(patch)],cwd=dest,check=True)
subprocess.run(['git','apply',str(patch)],cwd=dest,check=True)
for name in ('web/cmdbox_web_agent.py','cli/cmdbox_agent_chat.py',
             'cli/cmdbox_agent_session_list.py','cli/cmdbox_agent_session_del.py'):
    ast.parse((dest/'cmdbox'/'app'/'features'/name).read_text(encoding='utf8'))
print('Independent public cmdbox copy prepared; original checkout unchanged.')
