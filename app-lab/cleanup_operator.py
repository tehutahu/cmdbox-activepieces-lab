"""Interactive owner-only AP UI witness. No AP USER token import or network.

Run from the protected private root's Cleanup-A/B.cmd in a real owner console.
Paste only GET Response JSON/URL, never headers, HAR, cookie, token or login data.
"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'runtimes/app-deps'), str(ROOT / 'poc'), str(ROOT / 'app-lab')]
import argparse
import json
from cmdbox_gateway.core import FlowPolicy, GatewayError, require
from cmdbox_gateway.cleanup_live import CleanupOperator, TrustedUiGrantChecker, discover_revoke_target, no_credentials, validate_owner
from cmdbox_gateway.lifecycle_live import LiveBindings, Target
from cmdbox_gateway.oauth_live import OAuthConfig
from cmdbox_gateway.vault_live import EncryptedStore, WindowsDpapiSealer


def context(root):
    from live_launcher import verify_owner_root
    verify_owner_root(root)
    sealer = WindowsDpapiSealer()
    filename = root / ('cleanup-settings.dpapi' if (root / 'cleanup-settings.dpapi').exists() else 'settings.dpapi')
    cfg = json.loads(sealer.open(filename.read_bytes(), b'approved-settings-v1'))
    require(cfg['mode'] in ('APPROVED-LOCAL-AP', 'CLEANUP-ONLY'), 'approved_operator_manifest_required')
    config = OAuthConfig(**cfg['oauth'])
    require(config.issuer == 'http://localhost:18088', 'approved_operator_issuer_required')
    targets = [Target(t['uid'], t['subject'], t['project'], FlowPolicy(**t['flow'])) for t in cfg['targets']]
    # Do not retain application passwords/keys in the operator context.
    cfg.clear()
    return CleanupOperator(LiveBindings(EncryptedStore(root, sealer), targets), config)


def read_json(prompt):
    print(prompt + '\nJSONを貼り、次の単独行に END と入力してください。')
    lines, size = [], 0
    while True:
        line = input()
        if line == 'END':
            break
        size += len(line)
        require(size <= 1000000, 'operator_response_too_large')
        lines.append(line)
    try:
        value = json.loads('\n'.join(lines))
        no_credentials(value)
        return value
    except GatewayError:
        raise
    except Exception:
        raise GatewayError('operator_response_json_invalid') from None


def read_pages(spec, stage):
    print(stage + ': AP Connectionsのfilter/cursorをclearしてreload。NetworkのGET grants Responseだけを使用。')
    result, cursor = [], None
    for _ in range(100):
        url = input('Request URL（queryにcursor/limit以外があれば中止）: ').strip()
        body = read_json('HTTP200であることを確認した一覧のResponse JSON')
        result.append({'url': url, 'status': 200, 'body': body})
        require(type(body) is dict and 'next' in body, 'pinned_seek_page_required')
        cursor = body['next']
        if cursor is None:
            return result
        print('nextがnullではありません。UIで次ページへ移り、続くResponseを入力してください。')
    raise GatewayError('grant_page_limit_exceeded')


def main(root, label):
    # The caller must be the OS owner, directly witnessing the existing AP UI.
    # No --yes, proof Boolean, token argument, clipboard scraping or login helper.
    require(sys.stdin.isatty() and sys.stdout.isatty(), 'interactive_owner_console_required')
    operator = context(root)
    uid = {'A': '101', 'B': '202'}[label]
    rows = operator.rows(uid)
    if not rows:
        print('このUIDのpending cleanupはありません。')
        return
    try:
        for row in rows:
            spec = operator.spec(uid, row)
            print('既存AP USERで http://localhost:18088/mcp-server/connections を開いてください。')
            print('照合対象（このprivate console内のみ）:', 'subject=', spec.subject,
                  'project=', spec.project, 'client=', spec.client_name, 'grant=', spec.grant or 'UNKNOWN')
            print('全体/複数行Revokeは使わず、当該1行だけ。cookie/token/HAR/Request headersは渡さないでください。')
            user_url = input('現在ログイン本人のGET /api/v1/users/<id> Request URL: ').strip()
            user = {'url': user_url, 'status': 200, 'body': read_json('同じ本人画面・HTTP200のuser Response JSON')}
            validate_owner(spec, user)
            before = None
            active = 'yes' if not spec.grant else input('該当行は現在active一覧にありますか [yes/no]: ').strip()
            require(active in ('yes', 'no'), 'explicit_active_row_answer_required')
            if active == 'yes':
                before = read_pages(spec, '削除前')
                resolved = discover_revoke_target(spec, user, before)
                print('削除対象grant IDを検証しました:', resolved)
                print('Network ResponseのこのIDとclient/project/memberを照合した1行のみ、')
                print('本人が Revoke → Revoke access → Revoke を実行してください。')
                require(input('該当1行だけを削除したら REVOKED と入力: ').strip() == 'REVOKED',
                        'manual_revoke_not_witnessed')
            after = read_pages(spec, '削除後/通常revoke後')
            print('同一本人session、正しいAP origin、HTTP200、fresh reload、全ページを実際に確認した場合だけ次を入力。')
            print('確認文字列: AP-UI ' + spec.subject)
            checker = TrustedUiGrantChecker(spec, user, before, after, owner_ack=input().strip())
            operator.publish(checker)
            operator.apply()
        print(json.dumps(operator.summary(), ensure_ascii=False))
        print('FORMAL-UI-CONFIRMED。AP recordの物理削除や自動API認証の証明ではなく、本人UI witnessによるactive grant不在確認です。')
    except (Exception, KeyboardInterrupt):
        operator.quarantine('manual_review_failed')
        print('後処理を保留し、専用appを停止隔離します。対象を推測・再認可せず親へ戻してください。')
        raise GatewayError('manual_review_quarantined') from None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--label', choices=['A', 'B'], required=True)
    args = parser.parse_args()
    try:
        main(args.private_root.resolve(), args.label)
    except GatewayError as error:
        print(error.code)
        sys.exit(1)
