"""Candidate and every reachable local Git blob/commit; values are never printed."""
from pathlib import Path
import ast
import hashlib
import json
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parent.parent
PATTERNS=[
 ('private-key',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
 ('jwt',r'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'),
 ('github-token',r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b'),
 ('slack-token',r'\bxox[baprs]-[A-Za-z0-9-]{12,}\b'),
 ('aws-key',r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
 ('google-oauth-id',r'[A-Za-z0-9-]{10,}\.apps\.googleusercontent\.com'),
 ('personal-windows-path',r'[A-Za-z]:[\\/]Users[\\/][^\s<>\x22]+'),
 ('personal-unix-path',r'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
 ('actual-bearer',r'Bearer\s+(?!LITERAL[-_]DUMMY)[A-Za-z0-9_+./=-]{18,}'),
]
DISALLOWED_COMPONENTS={'private','node_modules','runtimes','evidence','local-review','cmdbox','activepieces','__pycache__','.venv','venv','data','tokenizer-cache','python-deps','cmdbox-public'}
DISALLOWED_SUFFIXES={'.log','.zip','.whl','.tgz','.vhdx','.sqlite','.db','.png','.jpg','.pem','.key','.p12','.pfx','.pyc'}
DISALLOWED_FILES={'live-internal-http-check.mjs','check-ap-loopback.cjs','check-ap-loopback-host.mjs','check-ap-egress.cjs','run-ap-boundary-readchecks.mjs','Initialize-AP.ps1','oauth-consent-server.mjs','oauth-cli.mjs','install-offline-http.mjs','install-offline-mcp.mjs'}
findings=[]
def inspect(name,data):
    p=Path(name)
    if any(x in DISALLOWED_COMPONENTS for x in p.parts) or p.suffix.lower() in DISALLOWED_SUFFIXES or p.name in DISALLOWED_FILES or (p.name.startswith('.env') and p.name!='.env.example'):
        findings.append(dict(file=name,rule='excluded-artifact'))
    if len(data)>1024*1024:findings.append(dict(file=name,rule='large-file'))
    try:text=data.decode('utf8')
    except UnicodeDecodeError:
        findings.append(dict(file=name,rule='binary-file'));return
    for label,pattern in PATTERNS:
        for m in re.finditer(pattern,text):
            findings.append(dict(file=name,rule=label,line=text.count('\n',0,m.start())+1))
    for m in re.finditer(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',text):
        domain=m.group(0).rsplit('@',1)[1].lower()
        if domain not in ('example.invalid','invalid') and not domain.endswith('.invalid'):
            findings.append(dict(file=name,rule='non-synthetic-email',line=text.count('\n',0,m.start())+1))
    if p.suffix=='.py':
        try:ast.parse(text)
        except SyntaxError:findings.append(dict(file=name,rule='python-ast'))

candidate=subprocess.check_output(['git','-C',str(ROOT),'ls-files','--cached','--others','--exclude-standard','-z']).decode('utf8').split('\0')
candidate=sorted(set(x for x in candidate if x))
manifest=[]
for name in candidate:
    data=(ROOT/name).read_bytes();inspect(name,data)
    manifest.append(dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
history=subprocess.run(['git','-C',str(ROOT),'rev-list','--objects','--all'],capture_output=True,text=True)
objects=[]
if history.returncode==0:
    for entry in history.stdout.splitlines():
        oid,_,name=entry.partition(' ')
        kind=subprocess.check_output(['git','-C',str(ROOT),'cat-file','-t',oid],text=True).strip()
        if kind not in ('blob','commit'):continue
        data=subprocess.check_output(['git','-C',str(ROOT),'cat-file','-p',oid])
        if kind=='blob':inspect('HISTORY:'+name,data)
        else:
            # Inspect commit authors/message, but do not treat the commit as a file.
            for label,pattern in PATTERNS:
                if re.search(pattern,data.decode('utf8')):findings.append(dict(file='HISTORY:commit',rule=label))
            for email in re.findall(r'<([^<>]+@[^<>]+)>',data.decode('utf8')):
                if not email.endswith('@example.invalid'):findings.append(dict(file='HISTORY:commit',rule='non-synthetic-email'))
        objects.append(dict(type=kind,object=oid))
report=dict(status='pass' if not findings else 'fail',candidateCount=len(manifest),totalBytes=sum(x['bytes'] for x in manifest),
    files=manifest,historyObjectsChecked=len(objects),findings=findings,
    limits='Pattern scan plus explicit allowlist/manual review; not a guarantee that every possible secret is detectable')
directory=ROOT/'local-review';directory.mkdir(exist_ok=True)
(directory/'publication-scan.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps(dict(status=report['status'],candidateCount=report['candidateCount'],totalBytes=report['totalBytes'],historyObjectsChecked=len(objects),findings=findings)))
sys.exit(0 if not findings else 1)
