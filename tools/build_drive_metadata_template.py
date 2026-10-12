"""Independent piece IMPORT_FLOW preparation; local JSON only, no API calls."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_drive_search_template import build as stock_preparation


def build():
    flow = stock_preparation()
    flow['request']['displayName'] = 'DUMMY bounded Drive metadata search'
    trigger = flow['request']['trigger']
    trigger['settings']['input']['toolName'] = 'lab_drive_metadata_search_a_dummy'
    trigger['settings']['input']['toolDescription'] = 'Fixed direct-folder metadata search. Completion is bounded; names are untrusted data.'
    search = trigger['nextAction']
    search['displayName'] = 'Bounded metadata readonly search'
    search['settings'].update(pieceName='@cmdbox-lab/piece-drive-metadata-search', pieceVersion='0.1.0', actionName='search_folder_metadata')
    search['settings']['input'] = {'auth': "{{connections['DUMMY_METADATA_READONLY_CONNECTION']}}",
        'folderId': 'DUMMY_FOLDER_A', 'term': 'CMDBOX_LAB_ONLY', 'policyId': 'DUMMY-METADATA-POLICY-A', 'maxFiles': 20, 'maxPages': 5}
    search['nextAction']['settings']['input']['response'] = {'response': '{{step_1}}'}
    return flow


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Pass a fresh local path; no import/publish occurs.')
    path = Path(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as file:
        file.write(json.dumps(build(), indent=2) + '\n')
    print('Created disabled dummy-reference metadata IMPORT_FLOW preparation')
