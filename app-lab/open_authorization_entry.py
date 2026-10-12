"""Human-invoked owner helper. Does not open AP consent or generate PKCE itself.

Decrypts private fixture password, performs native local password login, and opens
a 30-second single-use browser handoff. No password/cookie/ticket/URL is printed.
"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'runtimes/app-deps'), str(ROOT / 'poc'), str(ROOT / 'app-lab')]
import argparse
import json
import webbrowser
import httpx
from live_launcher import verify_owner_root
from cmdbox_gateway.vault_live import WindowsDpapiSealer
from cmdbox_gateway.core import require

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--label', choices=['A', 'B'], required=True)
    args = parser.parse_args()
    root = args.private_root.resolve()
    verify_owner_root(root)
    settings = json.loads(WindowsDpapiSealer().open((root / 'settings.dpapi').read_bytes(), b'approved-settings-v1'))
    require(settings['mode'] == 'APPROVED-LOCAL-AP', 'approved_test_settings_required')
    with httpx.Client(base_url='http://localhost:18090', trust_env=False, follow_redirects=False, timeout=15) as client:
        response = client.post('/dosignin/connect', data={'name': 'alice' if args.label == 'A' else 'bob', 'password': settings['passwords'][args.label]})
        require(response.headers.get('signin') == 'success', 'native_fixture_login_failed')
        csrf = client.get('/connection').json()['csrf']
        response = client.post('/handoff/' + args.label, json={'csrf': csrf}, headers={'Origin': 'http://localhost:18090'})
        require(response.status_code == 200, 'owner_handoff_failed')
        require(webbrowser.open(response.json()['url'], new=1), 'browser_open_failed')
