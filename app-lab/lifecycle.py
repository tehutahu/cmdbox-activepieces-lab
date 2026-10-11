"""Durable lifecycle CONTRACT for literal fake provider/vault only; never real OAuth.

SQLite serializes fake refresh/revoke and state consumption across Web/worker processes.
An actual vault must implement the same checks without storing plaintext credentials here.
"""
import base64
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json
import sqlite3
import time
from cmdbox_gateway.core import Binding, BindingRegistry, GatewayError, require

IDENTITIES = {'101':('A','DUMMY-AP-SUBJECT-A','DUMMY-PROJECT-A'),
              '202':('B','DUMMY-AP-SUBJECT-B','DUMMY-PROJECT-B')}

def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')

class FakeProvider:
    def exchange(self, code, verifier, expected_challenge, identity):
        require(code.startswith('LITERAL-DUMMY-CODE-') and challenge(verifier) == expected_challenge,
                'fake_pkce_or_code_invalid')
        label, subject, project = identity
        return {'subject':subject, 'project':project, 'grant':'DUMMY-GRANT-'+label,
                'access':'LITERAL-DUMMY-AP-'+label, 'refresh':'LITERAL-DUMMY-REFRESH-'+label}
    def refresh(self, refresh, identity):
        require(refresh == 'LITERAL-DUMMY-REFRESH-' + identity[0], 'fake_refresh_invalid')
        return self.exchange('LITERAL-DUMMY-CODE-REFRESH','LITERAL_DUMMY_PKCE_VERIFIER_REFRESH_000000000000',
                             challenge('LITERAL_DUMMY_PKCE_VERIFIER_REFRESH_000000000000'),identity)
    def revoke(self, grant):
        require(grant.startswith('DUMMY-GRANT-'), 'fake_grant_required')

class FakeLifecycle:
    def __init__(self, registry, *, provider=None, clock=time.time):
        self.registry, self.provider, self.clock = registry, provider or FakeProvider(), clock
        self.path = registry.path
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS fake_pending (
                    state TEXT PRIMARY KEY, uid TEXT, session TEXT, expires INTEGER,
                    verifier TEXT, challenge TEXT, code TEXT, generation INTEGER);
                CREATE TABLE IF NOT EXISTS fake_vault (
                    uid TEXT PRIMARY KEY, reference TEXT, grant_id TEXT, generation INTEGER,
                    access TEXT, refresh TEXT, expires INTEGER, refresh_count INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS fake_counter (id INTEGER PRIMARY KEY CHECK(id=1), n INTEGER);
                INSERT OR IGNORE INTO fake_counter VALUES (1,0);
                CREATE TABLE IF NOT EXISTS fake_audit (operation TEXT, uid TEXT, generation INTEGER);
            ''')
    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()
    def _record(self, db, uid):
        row = db.execute('SELECT record FROM bindings WHERE uid=?',(uid,)).fetchone()
        return self.registry._read(row)
    def _save(self, db, binding):
        previous = self._record(db,binding.uid)
        validator = BindingRegistry(self.registry._approved)
        if previous: validator._rows[binding.uid] = previous
        validator.bind(binding)
        require(all(x.startswith('DUMMY-') for x in (binding.subject,binding.project_id,binding.grant_id))
                and binding.credential_ref.startswith('dummy-ref-'), 'synthetic_binding_only')
        db.execute('INSERT INTO bindings VALUES (?,?,?) ON CONFLICT(uid) DO UPDATE SET generation=excluded.generation,record=excluded.record',
                   (binding.uid,binding.generation,json.dumps(asdict(binding))))
    def start(self, uid, session):
        require(uid in IDENTITIES and session.startswith('LITERAL_DUMMY_WEBSESSION_'), 'fake_identity_required')
        now = int(self.clock())
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM fake_pending WHERE expires<=?',(now,))
            n = db.execute('UPDATE fake_counter SET n=n+1 WHERE id=1 RETURNING n').fetchone()[0]
            state, code = 'LITERAL-DUMMY-STATE-'+str(n), 'LITERAL-DUMMY-CODE-'+str(n)
            verifier = 'LITERAL_DUMMY_PKCE_VERIFIER_MOCK_ONLY_00000000_'+str(n)
            proof = challenge(verifier)
            old = self._record(db,uid)
            db.execute('INSERT INTO fake_pending VALUES (?,?,?,?,?,?,?,?)',
                       (state,uid,session,now+120,verifier,proof,code,old.generation if old else 0))
        return {'state':state,'challenge':proof,'method':'S256','fakeCode':code,'expiresIn':120,'mode':'FAKE-ONLY'}
    def complete(self, uid, session, state, code):
        failure = None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = db.execute('SELECT * FROM fake_pending WHERE state=?',(state,)).fetchone()
            require(pending is not None, 'state_missing_or_consumed')
            # Wrong principal cannot consume another principal's state.
            require(pending['uid'] == uid and pending['session'] == session, 'state_session_mismatch')
            db.execute('DELETE FROM fake_pending WHERE state=?',(state,))
            try:
                require(pending['expires'] > int(self.clock()), 'state_expired')
                old = self._record(db,uid)
                require((old.generation if old else 0) == pending['generation'], 'stale_connect_state')
                require(code == pending['code'], 'fake_code_invalid')
                identity = IDENTITIES[uid]
                result = self.provider.exchange(code,pending['verifier'],pending['challenge'],identity)
                require((result['subject'],result['project'],result['grant']) == (identity[1],identity[2],'DUMMY-GRANT-'+identity[0]),
                        'subject_project_grant_mismatch')
                require(result['access'] == 'LITERAL-DUMMY-AP-'+identity[0] and result['refresh'] == 'LITERAL-DUMMY-REFRESH-'+identity[0],
                        'literal_fake_tokens_required')
                flow = next(f for f in self.registry._approved if f.owner == identity[0])
                generation = pending['generation']+1
                ref = 'dummy-ref-'+identity[0].lower()
            except Exception as error:
                failure = error if isinstance(error,GatewayError) else GatewayError('fake_callback_failed')
            if failure is None:
                self._save(db,Binding(uid,result['subject'],result['project'],result['grant'],ref,generation,flow))
                db.execute('INSERT INTO fake_vault VALUES (?,?,?,?,?,?,?,0) ON CONFLICT(uid) DO UPDATE SET reference=excluded.reference,grant_id=excluded.grant_id,generation=excluded.generation,access=excluded.access,refresh=excluded.refresh,expires=excluded.expires',
                           (uid,ref,result['grant'],generation,result['access'],result['refresh'],int(self.clock())+60))
                db.execute('INSERT INTO fake_audit VALUES (?,?,?)',('connect',uid,generation))
        if failure: raise failure
        return self.status(uid)
    def status(self, uid):
        record = self.registry.get_record(uid)
        with self.db() as db:
            vault = db.execute('SELECT generation,expires,refresh_count FROM fake_vault WHERE uid=?',(uid,)).fetchone()
        return {'status': record.status if record and vault and vault['generation']==record.generation else 'RECONNECT_REQUIRED',
                'generation':record.generation if record else 0,'mode':'FAKE-ONLY',
                'refreshCount':vault['refresh_count'] if vault else 0}
    def renew(self, uid, expected_generation, *, force=False):
        failure = None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            binding = self._record(db,uid)
            vault = db.execute('SELECT * FROM fake_vault WHERE uid=?',(uid,)).fetchone()
            require(binding is not None and binding.status == 'ACTIVE' and vault is not None,
                    'reconnect_required')
            require(vault['generation'] == binding.generation and vault['grant_id'] == binding.grant_id,
                    'reconnect_required')
            if binding.generation != expected_generation:
                # Another worker already rotated this exact connection. Reuse its active result.
                require(binding.generation > expected_generation, 'invalid_refresh_generation')
                return self.status(uid)
            if not force and vault['expires'] > int(self.clock()): return self.status(uid)
            try:
                result = self.provider.refresh(vault['refresh'],IDENTITIES[uid])
                require((result['subject'],result['project'],result['grant']) == (binding.subject,binding.project_id,binding.grant_id),
                        'subject_project_grant_mismatch')
                require(result['access'] == 'LITERAL-DUMMY-AP-'+IDENTITIES[uid][0] and result['refresh'] == vault['refresh'],
                        'literal_fake_tokens_required')
            except Exception:
                failure = GatewayError('reconnect_required')
            binding = replace(binding,generation=binding.generation+1,status='RECONNECT_REQUIRED' if failure else 'ACTIVE')
            self._save(db,binding)
            if failure:
                db.execute('DELETE FROM fake_vault WHERE uid=?',(uid,))
            else:
                db.execute('UPDATE fake_vault SET generation=?,access=?,expires=?,refresh_count=refresh_count+1 WHERE uid=?',
                           (binding.generation,result['access'],int(self.clock())+60,uid))
            db.execute('INSERT INTO fake_audit VALUES (?,?,?)',('refresh_failed' if failure else 'refresh',uid,binding.generation))
        if failure: raise failure
        return self.status(uid)
    def revoke(self, uid):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = self._record(db,uid)
            if old:
                self.provider.revoke(old.grant_id)
                self._save(db,replace(old,generation=old.generation+1,status='RECONNECT_REQUIRED'))
            db.execute('DELETE FROM fake_vault WHERE uid=?',(uid,))
            db.execute('DELETE FROM fake_pending WHERE uid=?',(uid,))
            db.execute('INSERT INTO fake_audit VALUES (?,?,?)',('revoke',uid,old.generation+1 if old else 0))
        return self.status(uid)
    def ensure_active(self, binding):
        self.renew(binding.uid,binding.generation)
    async def get_active(self, reference, grant_id, generation):
        # No credential cache; every execution rechecks the durable generation and expiry.
        with self.db() as db:
            row = db.execute('SELECT * FROM fake_vault WHERE reference=?',(reference,)).fetchone()
            require(row is not None and row['grant_id'] == grant_id and row['generation'] == generation and row['expires'] > int(self.clock()),
                    'reconnect_required')
            binding = self._record(db,row['uid'])
            require(binding is not None and binding.status == 'ACTIVE' and binding.generation == generation, 'reconnect_required')
            require(row['access'] == 'LITERAL-DUMMY-AP-'+IDENTITIES[row['uid']][0], 'literal_fake_tokens_required')
            return row['access']
