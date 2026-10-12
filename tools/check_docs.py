"""Static docs/JSON/SVG checks. No app, container, network or credential access."""
from pathlib import Path
import json
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
names = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', '-z']).decode().split('\0')
markdown = links = json_files = svg_files = 0
for name in sorted(set(names)-{''}):
    path = ROOT/name
    if path.suffix == '.json':
        json.loads(path.read_text(encoding='utf8')); json_files += 1
    if path.suffix == '.svg':
        tree = ET.fromstring(path.read_text(encoding='utf8'))
        assert tree.tag == '{http://www.w3.org/2000/svg}svg'
        assert not any(node.tag.rsplit('}', 1)[-1] in ('script', 'foreignObject') for node in tree.iter())
        assert not any(value.startswith(('http:', 'https:')) for node in tree.iter() for key, value in node.attrib.items() if key.rsplit('}', 1)[-1] == 'href')
        svg_files += 1
    if path.suffix != '.md': continue
    text = path.read_text(encoding='utf8'); assert '\r' not in text
    assert text.count('```') % 2 == 0, name
    for match in re.finditer(r'\[[^\]]*\]\(([^\s)]+)\)', text):
        target = match[1]
        if target.startswith(('https:', 'http:', 'mailto:', '#')): continue
        target = target.split('#', 1)[0]
        if target: assert (path.parent/target).resolve().exists(), (name, target)
        links += 1
    markdown += 1
summary = json.loads((ROOT/'docs/google-drive-e2e-summary.json').read_text())
assert summary['realFlowAttempts'] == 2 and summary['realFlowSuccesses'] == 1 and summary['remainingFlowAttempts'] == 0
assert summary['modelMode'] == 'scripted' and not summary['naturalLanguageAutonomousSelectionValidated']
assert summary['managementToolsObserved'] == 42 and summary['googleConnectionRemainsActive']
assert not summary['googleProviderGrantRevocationConfirmed'] and summary['appAndWorkerStopped']
print(json.dumps({'status': 'pass', 'markdown': markdown, 'localLinks': links, 'json': json_files, 'svg': svg_files, 'runtimeStarted': False}))
