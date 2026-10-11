"""Correctness lint of the public candidate, excluding ignored upstream/deps/data."""
from pathlib import Path
import ast
import os
import sys
import subprocess
ROOT = Path(__file__).resolve().parent.parent
RUNTIME = Path(os.environ.get('CMDBOX_LAB_RUNTIME_ROOT',ROOT/'runtimes'))
ruff = RUNTIME/'lint-deps'/'bin'/'ruff.exe'
assert ruff.is_file(), 'Install the hash-pinned optional lint-requirements.lock in runtimes/lint-deps'
output = subprocess.check_output(['git','-C',str(ROOT),'ls-files','--cached','--others','--exclude-standard','-z'])
names = sorted({n for n in output.decode('utf8').split('\0') if n.endswith('.py')})
for name in names: ast.parse((ROOT/name).read_text(encoding='utf8'))
subprocess.run([str(ruff),'check','--no-cache','--select','E9,F821,F823,F811,F841',*names],cwd=ROOT,check=True)
subprocess.run(['git','-C',str(ROOT),'diff','HEAD','--check','--','.',':(exclude)patches/*.diff'],check=True)
# A unified diff contains a single space on blank context lines; check its ADDED
# source whitespace through Git apply instead of treating format markers as code.
subprocess.run([sys.executable,str(ROOT/'tools/check_public_patch.py')],check=True)
print('PASS public Python AST, pinned Ruff correctness lint and diff whitespace: '+str(len(names))+' files')
