"""Replay patch in a disposable ignored directory; never overwrite an existing copy."""
from pathlib import Path
import ast
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parent.parent
source = ROOT/'cmdbox'
assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()=='a429260512035aa358d49e7b319c2bfc56532742'
assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True).strip()
patch = ROOT/'patches/cmdbox-uid-gateway.diff'
names = [line[6:] for line in patch.read_text(encoding='utf8').splitlines() if line.startswith('+++ b/')]
expected = {'cmdbox/app/features/web/cmdbox_web_agent.py','cmdbox/app/features/cli/cmdbox_agent_chat.py',
            'cmdbox/app/features/cli/cmdbox_agent_session_list.py','cmdbox/app/features/cli/cmdbox_agent_session_del.py'}
assert len(names)==4 and set(names)==expected, 'Refuse patch paths outside the four reviewed public files'
(ROOT/'local-review').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=ROOT/'local-review',prefix='patch-check-') as tmp:
    dest = Path(tmp)
    assert dest.resolve().is_relative_to((ROOT/'local-review').resolve())
    for name in names:
        (dest/name).parent.mkdir(parents=True,exist_ok=True)
        (dest/name).write_bytes((source/name).read_bytes())
    subprocess.run(['git','apply','--check','--whitespace=error',str(patch)],cwd=dest,check=True)
    subprocess.run(['git','apply',str(patch)],cwd=dest,check=True)
    for name in names:
        ast.parse((dest/name).read_text(encoding='utf8'))
        assert (dest/name).read_text(encoding='utf8') == (ROOT/'app-lab/cmdbox-public'/name).read_text(encoding='utf8')
print('PASS pinned-source patch replay, AST and independent-copy equality: '+str(len(names))+' files')
