"""Effective versions and declared wheel licenses only; no paths/authors/emails."""
from pathlib import Path
import importlib.metadata
import json
import os
import re
import sys
ROOT=Path(__file__).resolve().parent.parent
runtime=Path(os.environ.get('CMDBOX_LAB_RUNTIME_ROOT',ROOT/'runtimes')).resolve()
effective={}
for directory in (runtime/'app-deps',runtime/'python312'/'Lib'/'site-packages'):
    for d in importlib.metadata.distributions(path=[str(directory)]):
        name=re.sub(r'[-_.]+','-',d.metadata['Name']).lower()
        if name in effective:continue
        expression=d.metadata.get('License-Expression')
        classifiers=[x.split(' :: ')[-1] for x in d.metadata.get_all('Classifier',[]) if x.startswith('License ::')]
        legacy=(d.metadata.get('License') or '').strip()
        legacy=legacy.splitlines()[0][:160] if legacy else None
        declared=expression or (' / '.join(classifiers) if classifiers else legacy) or 'UNKNOWN'
        effective[name]=dict(name=name,version=d.version,declaredLicense=declared,
            source='Installed official wheel metadata',pypi=f'https://pypi.org/project/{name}/{d.version}/')
record=dict(scope='Effective isolated Python runtime; packages not vendored',
    legalCompletenessGuaranteed=False,packages=sorted(effective.values(),key=lambda x:x['name']),
    unknown=[x['name'] for x in effective.values() if x['declaredLicense']=='UNKNOWN'])
(ROOT/'docs'/'dependency-licenses.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
print(f"Recorded {len(effective)} effective package licenses; UNKNOWN={len(record['unknown'])}.")
