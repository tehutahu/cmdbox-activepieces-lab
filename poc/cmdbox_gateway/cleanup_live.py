"""Owner-console UI witness -> purpose-bound proof -> atomic cleanup.

No AP USER cookie/token, login, network request, or public proof endpoint. This is
an explicitly human-witnessed browser-Response workflow, not automatic AP auth.
"""
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import re
import time
from urllib.parse import parse_qs, urlsplit
from .core import canonical, GatewayError, require


def no_credentials(value):
    # Reject even accidental Request headers/HAR/authentication JSON, no values
    # enter errors or audit. Only AP response data belongs in a UI witness.
    if isinstance(value, dict):
        for key, item in value.items():
            require(type(key) is str and not any(word in key.lower() for word in
                    ('token', 'cookie', 'authorization', 'password', 'secret')) and key.lower() not in ('har', 'headers'),
                    'credential_material_refused')
            no_credentials(item)
    elif isinstance(value, list):
        for item in value:
            no_credentials(item)
    elif isinstance(value, str):
        require(len(value) <= 65536 and not re.search(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.', value)
                and not re.search(r'Bearer\s+\S+', value, re.I), 'credential_material_refused')


@dataclass(frozen=True, repr=False)
class CleanupSpec:
    uid: str
    row: int
    generation: int
    digest: str
    grant: str | None
    subject: str
    project: str
    client: str
    client_name: str
    issuer: str
    attempted_at: int | None

    @property
    def fingerprint(self):
        return hashlib.sha256(canonical(asdict(self))).hexdigest()


def validate_pages(spec, pages):
    require(type(pages) is list and 0 < len(pages) <= 100, 'complete_grant_pages_required')
    expected, seen, cursors, rows = None, set(), set(), []
    for item in pages:
        require(type(item) is dict and set(item) == {'url', 'status', 'body'} and item['status'] == 200,
                'successful_browser_response_required')
        no_credentials(item)
        parsed = urlsplit(item['url'])
        base = parsed._replace(query='', fragment='').geturl()
        require(base == spec.issuer + '/api/v1/mcp-oauth/grants' and not parsed.fragment,
                'formal_response_origin_required')
        query = parse_qs(parsed.query, keep_blank_values=True)
        require(set(query) <= {'cursor', 'limit'} and all(len(x) == 1 for x in query.values()),
                'unfiltered_grant_list_required')
        require(query.get('cursor', [None])[0] == expected and expected not in cursors, 'grant_cursor_chain_incomplete')
        cursors.add(expected)
        if 'limit' in query:
            require(query['limit'][0].isdigit() and 1 <= int(query['limit'][0]) <= 1000,
                    'grant_page_limit_invalid')
        body = item['body']
        require(type(body) is dict and set(body) == {'data', 'next', 'previous'}
                and type(body['data']) is list and len(body['data']) <= 1000,
                'pinned_seek_page_required')
        require(body['previous'] is None or type(body['previous']) is str, 'grant_cursor_invalid')
        for row in body['data']:
            require(type(row) is dict and set(row) == {'id', 'clientKey', 'clientName', 'projectId',
                    'projectName', 'member', 'created', 'lastUsedAt'}
                    and type(row['id']) is str and 0 < len(row['id']) <= 100 and row['id'] not in seen,
                    'pinned_grant_row_required')
            seen.add(row['id'])
            rows.append(row)
        expected = body['next']
        require(expected is None or type(expected) is str and 0 < len(expected) <= 2000,
                'grant_cursor_invalid')
        require(expected is not None or item is pages[-1], 'unexpected_grant_page_after_end')
    require(expected is None, 'grant_cursor_chain_incomplete')
    return rows


def validate_owner(spec, user):
    require(type(user) is dict and set(user) == {'url', 'status', 'body'} and user['status'] == 200,
            'successful_browser_user_response_required')
    no_credentials(user)
    require(user['url'] == spec.issuer + '/api/v1/users/' + spec.subject and
            type(user['body']) is dict and user['body'].get('id') == spec.subject,
            'formal_user_subject_mismatch')


def matches_target(spec, row):
    return row['clientName'] == spec.client_name and row['projectId'] == spec.project and \
        type(row['member']) is dict and row['member'].get('id') == spec.subject


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None, 'grant_created_timestamp_invalid')
        return int(parsed.timestamp())
    except Exception:
        raise GatewayError('grant_created_timestamp_invalid') from None


def unknown_target(spec, rows):
    require(spec.attempted_at is not None, 'unknown_grant_requires_ui_discovery')
    candidates = [r for r in rows if matches_target(spec, r) and
                  spec.attempted_at - 5 <= timestamp(r['created']) <= spec.attempted_at + 60]
    require(len(candidates) == 1, 'unknown_grant_ambiguous_or_unresolved')
    return candidates[0]['id']


def discover_revoke_target(spec, user, before):
    """Validate the fresh USER and exact row BEFORE suggesting UI mutation."""
    validate_owner(spec, user)
    rows = validate_pages(spec, before)
    if spec.grant:
        candidates = [r for r in rows if r['id'] == spec.grant]
        require(len(candidates) == 1 and matches_target(spec, candidates[0]),
                'formal_grant_target_mismatch')
        return spec.grant
    return unknown_target(spec, rows)


class TrustedUiGrantChecker:
    """Construct only inside the ACL-checked interactive CurrentUser operator.

    AP browser credentials remain in that browser. Source provenance/current
    login is the human's explicit witness; this does not cryptographically prove
    a pasted response came from AP. Ordinary app callers cannot publish proofs.
    """
    def __init__(self, spec, user, before, after, *, owner_ack):
        validate_owner(spec, user)
        require(owner_ack == 'AP-UI ' + spec.subject,
                'interactive_current_user_witness_required')
        first = validate_pages(spec, before) if before is not None else []
        last = validate_pages(spec, after)
        resolved = spec.grant
        if resolved:
            same = [r for r in first if r['id'] == resolved]
            require(not same or len(same) == 1 and matches_target(spec, same[0]),
                    'formal_grant_target_mismatch')
            require(not any(r['id'] == resolved for r in last), 'formal_grant_still_active')
        else:
            # Response loss may leave no known ID/refresh token. Resolve only a
            # unique, matching, newly-created row witnessed before manual Revoke.
            require(before is not None, 'unknown_grant_requires_ui_discovery')
            resolved = unknown_target(spec, first)
            require(not any(r['id'] == resolved for r in last), 'formal_grant_still_active')
        self.spec, self.resolved = spec, resolved
        self.page_count = len(after)
        self.response_digest = hashlib.sha256(canonical({'user': user, 'before': before, 'after': after})).hexdigest()

    def verdict(self):
        return {'mode': 'MANUAL-AP-UI-WITNESS', 'spec': self.spec.fingerprint,
                'resolved_grant': self.resolved, 'all_pages': self.page_count,
                'response_digest': self.response_digest}


class CleanupOperator:
    def __init__(self, registry, config, *, clock=time.time):
        self.registry, self.store, self.config, self.clock = registry, registry.store, config, clock
        with self.store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS formal_proofs
                (id INTEGER PRIMARY KEY, uid TEXT, row_id INTEGER, generation INTEGER, envelope BLOB);
                CREATE TABLE IF NOT EXISTS cleanup_audit
                (id INTEGER PRIMARY KEY, uid TEXT, outcome TEXT, at INTEGER, envelope BLOB);
                CREATE TABLE IF NOT EXISTS operator_control
                (id INTEGER PRIMARY KEY CHECK(id=1), reason TEXT);''')

    def spec(self, uid, row_id):
        with self.store.db() as db:
            generation, status, record = self.store.row(db, uid)
            require(status == 'RECONNECT_REQUIRED' and not (record or {}).get('tokens'),
                    'local_revoke_before_formal_review_required')
            row = db.execute('SELECT * FROM cleanup WHERE uid=? AND id=?', (uid, row_id)).fetchone()
            require(row is not None, 'cleanup_record_required')
            item = self.store.decode('cleanup', row_id, row['envelope'])
        target = self.registry.targets[uid]
        identity = item.get('identity') or {'subject': target.subject, 'project': target.project,
                                            'client': self.config.client_id}
        require(identity['client'] == self.config.client_id and any(
                t.subject == identity['subject'] and t.project == identity['project'] for t in self.registry.targets.values()),
                'cleanup_identity_outside_approved_targets')
        return CleanupSpec(uid, row_id, generation, hashlib.sha256(row['envelope']).hexdigest(), item['grant'],
                           identity['subject'], identity['project'], identity['client'], self.config.client_name,
                           self.config.issuer, item.get('attempted_at'))

    def rows(self, uid):
        require(uid in self.registry.targets, 'approved_local_uid_required')
        with self.store.db() as db:
            return [r[0] for r in db.execute('SELECT id FROM cleanup WHERE uid=? ORDER BY id', (uid,))]

    def publish(self, checker):
        require(type(checker) is TrustedUiGrantChecker, 'trusted_ui_checker_required')
        spec = checker.spec
        require(self.spec(spec.uid, spec.row).fingerprint == spec.fingerprint, 'stale_formal_review')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            require(db.execute('SELECT count(*) FROM formal_proofs WHERE uid=? AND row_id=?', (spec.uid, spec.row)).fetchone()[0] == 0, 'formal_review_already_pending')
            number = self.store.next_id(db)
            value = {**checker.verdict(), 'created': int(self.clock()), 'expires': int(self.clock()) + 300}
            db.execute('INSERT INTO formal_proofs VALUES (?,?,?,?,?)', (number, spec.uid, spec.row, spec.generation,
                       self.store.encode('formal-proof', number, value)))
        return number

    def apply(self):
        with self.store.db() as db:
            rows = list(db.execute('SELECT * FROM formal_proofs ORDER BY id'))
        cleared = 0
        for proof in rows:
            value = None
            try:
                value = self.store.decode('formal-proof', proof['id'], proof['envelope'])
                spec = self.spec(proof['uid'], proof['row_id'])
                require(set(value) == {'mode', 'spec', 'resolved_grant', 'all_pages', 'response_digest', 'created', 'expires'}
                        and value['mode'] == 'MANUAL-AP-UI-WITNESS' and value['spec'] == spec.fingerprint
                        and proof['generation'] == spec.generation and int(self.clock()) <= value['expires']
                        and 0 <= int(self.clock()) - value['created'] <= 300 and type(value['all_pages']) is int
                        and value['all_pages'] > 0 and type(value['resolved_grant']) is str
                        and (spec.grant is None or value['resolved_grant'] == spec.grant), 'formal_proof_invalid_or_stale')
                with self.store.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    version, status, record = self.store.row(db, spec.uid)
                    current = db.execute('SELECT envelope FROM cleanup WHERE uid=? AND id=?', (spec.uid, spec.row)).fetchone()
                    require(version == spec.generation and status == 'RECONNECT_REQUIRED' and not (record or {}).get('tokens')
                            and current is not None and hashlib.sha256(current[0]).hexdigest() == spec.digest,
                            'stale_formal_review')
                    db.execute('DELETE FROM cleanup WHERE uid=? AND id=?', (spec.uid, spec.row))
                    db.execute('DELETE FROM formal_proofs WHERE id=?', (proof['id'],))
                    audit = self.store.encode('cleanup-audit', proof['id'], value)
                    db.execute('INSERT INTO cleanup_audit VALUES (?,?,?,?,?)',
                               (proof['id'], spec.uid, 'FORMAL-UI-CONFIRMED', int(self.clock()), audit))
                    cleared += 1
            except Exception:
                # Console and runtime watcher may consume the same proof. A
                # matching encrypted audit is idempotent success, not quarantine.
                with self.store.db() as db:
                    done = db.execute('SELECT envelope FROM cleanup_audit WHERE id=? AND uid=?',
                                      (proof['id'], proof['uid'])).fetchone()
                    if done is not None and value is not None:
                        audit = self.store.decode('cleanup-audit', proof['id'], done[0])
                        if audit == value:
                            continue
                    db.execute('DELETE FROM formal_proofs WHERE id=?', (proof['id'],))
                self.quarantine('formal_proof_invalid_or_stale')
                raise GatewayError('formal_review_quarantined') from None
        return cleared

    def quarantine(self, reason):
        require(reason in ('formal_proof_invalid_or_stale', 'manual_review_failed', 'connection_verification_failed'), 'operator_stop_reason_required')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO operator_control VALUES (1,?) ON CONFLICT(id) DO UPDATE SET reason=excluded.reason', (reason,))
            for uid in self.registry.targets:
                self.store.disable(db, uid, self.config.client_id, int(self.clock()))

    def blocked(self):
        with self.store.db() as db:
            return db.execute('SELECT reason FROM operator_control WHERE id=1').fetchone() is not None

    def summary(self):
        with self.store.db() as db:
            pending = db.execute('SELECT count(*) FROM cleanup').fetchone()[0]
            proofs = db.execute('SELECT count(*) FROM formal_proofs').fetchone()[0]
            confirmed = db.execute('SELECT count(*) FROM cleanup_audit').fetchone()[0]
        return {'cleanupPendingCount': pending, 'formalProofPendingCount': proofs,
                'formalUiConfirmedCount': confirmed, 'operatorBlocked': self.blocked(),
                'formalMode': 'OWNER-UI-WITNESS-NO-AP-USER-CREDENTIAL-TRANSFER'}
