"""Create a disabled stock-only manifest plus dummy flow receipts. No AP I/O."""
from pathlib import Path
import sys
import json
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / 'poc'))
from cmdbox_gateway.stock_drive import dummy_bundle

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Pass a new local output path; no import/publish is performed.')
    output = Path(sys.argv[1]).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf8',newline='\n') as file:
        file.write(json.dumps(dummy_bundle(),indent=2)+'\n')
    print('Created disabled, dummy-only stock manifest and flow receipts')
