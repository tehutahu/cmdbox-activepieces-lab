"""Review-only live-shaped OAuth lifecycle with injected mocked I/O in this phase.

Network calls are outside SQLite write transactions. Leases + generation CAS prevent
late callbacks/refresh from restoring revoked authority. Cleanup never assumes HTTP200
is formal revocation. No HTTP route, real account, secret or default binding is created.
"""
from dataclasses import asdict, dataclass
import hashlib
import re
import time
from .core import Binding, BindingRegistry, FlowPolicy, GatewayError, require
from .oauth_live import IssuedTokenRejected, Tokens, pkce


@dataclass(frozen=True)
class Target:
    uid: str
    subject: str
    project: str
    flow: FlowPolicy


class LiveBindings(BindingRegistry):
    def __init__(self, store, targets):
        super().__init__([t.flow for t in targets])
        require(len({t.uid for t in targets}) == len(targets) and bool(targets), 'unique_target_manifest_required')
        require(all(re.fullmatch(r'0|[1-9][0-9]*', t.uid) and t.subject and t.project for t in targets), 'trusted_target_manifest_required')
        self.store, self.targets = store, {t.uid: t for t in targets}

    def get_record(self, uid):
        with self.store.db() as db:
            version, status, record = self.store.row(db, uid)
        if not record or not record.get('binding'):
            return None
        value = dict(record['binding'])
        value['flow'] = FlowPolicy(**value['flow'])
        binding = Binding(**value)
        target = self.targets.get(uid)
        require(target is not None and binding.uid == uid and binding.generation == version and binding.status == status
                and binding.subject == target.subject and binding.project_id == target.project and binding.flow == target.flow,
                'vault_binding_manifest_mismatch')
        return binding

    def resolve(self, uid):
        binding = self.get_record(uid)
        require(binding is not None and binding.status == 'ACTIVE', 'reconnect_required')
        return binding

    def bind(self, binding):
        raise GatewayError('atomic_lifecycle_binding_required')


class LiveLifecycle:
    def __init__(self, registry, provider, entropy, *, clock=time.time, lease_seconds=30, retention_seconds=7200):
        require(isinstance(registry, LiveBindings) and callable(entropy), 'configured_live_lifecycle_required')
        require(type(lease_seconds) is int and 0 < lease_seconds <= 30 and type(retention_seconds) is int
                and 0 < retention_seconds <= 7200, 'bounded_lifecycle_required')
        self.registry, self.store, self.provider, self.entropy = registry, registry.store, provider, entropy
        self.clock, self.lease_seconds, self.retention_seconds = clock, lease_seconds, retention_seconds

    def _target(self, uid):
        require(uid in self.registry.targets, 'approved_local_uid_required')
        return self.registry.targets[uid]

    def status(self, uid):
        self._target(uid)
        with self.store.db() as db:
            version, status, record = self.store.row(db, uid)
            pending = db.execute('SELECT count(*) FROM cleanup WHERE uid=?', (uid,)).fetchone()[0]
        if status == 'ACTIVE' and record['deadline'] <= int(self.clock()):
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                current, _, _ = self.store.row(db, uid)
                if current == version:
                    self._disable(db, uid)
            return self.status(uid)
        return {'status': status, 'generation': version, 'cleanupPending': bool(pending), 'mode': 'LIVE-CONTRACT-CANDIDATE'}

    def start(self, uid, session):
        self._target(uid)
        require(type(session) is str and 16 <= len(session) <= 200, 'verified_server_session_required')
        state, verifier, challenge = pkce(self.entropy)
        digest, session_digest = hashlib.sha256(state.encode()).hexdigest(), hashlib.sha256(session.encode()).hexdigest()
        now = int(self.clock())
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            version, _, _ = self.store.row(db, uid)
            db.execute('DELETE FROM pending WHERE expires<=?', (now,))
            try:
                db.execute('INSERT INTO pending VALUES (?,?,?,?,?)', (digest, uid, now + 120, version,
                           self.store.encode('pending', digest, {'session': session_digest, 'verifier': verifier})))
            except Exception:
                raise GatewayError('oauth_state_collision') from None
        return {'state': state, 'challenge': challenge, 'method': 'S256', 'expiresIn': 120,
                'authorizationUrl': self.provider.authorization_url(state, challenge)}

    def _lease(self, db, uid, base):
        now = int(self.clock())
        old = db.execute('SELECT * FROM leases WHERE uid=?', (uid,)).fetchone()
        require(old is None or old['expires'] <= now, 'connection_busy')
        number = self.store.next_id(db)
        db.execute('INSERT INTO leases VALUES (?,?,?,?) ON CONFLICT(uid) DO UPDATE SET id=excluded.id,base=excluded.base,expires=excluded.expires',
                   (uid, number, base, now + self.lease_seconds))
        return number

    def _claim_callback(self, uid, session, state):
        require(type(state) is str and 40 <= len(state) <= 100 and type(session) is str, 'oauth_callback_invalid')
        digest = hashlib.sha256(state.encode()).hexdigest()
        failure = None
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM pending WHERE digest=?', (digest,)).fetchone()
            require(row is not None and row['uid'] == uid, 'oauth_state_missing_or_wrong_uid')
            value = self.store.decode('pending', digest, row['envelope'])
            require(value['session'] == hashlib.sha256(session.encode()).hexdigest(), 'oauth_state_wrong_session')
            version, _, _ = self.store.row(db, uid)
            try:
                require(row['expires'] > int(self.clock()) and row['base'] == version, 'oauth_state_expired_or_stale')
                lease = self._lease(db, uid, version)
            except GatewayError as error:
                failure = error
            db.execute('DELETE FROM pending WHERE digest=?', (digest,))
        if failure:
            raise failure
        return version, lease, value['verifier']

    def _approve_identity(self, identity, target, *, grant=None):
        require(identity.subject == target.subject and identity.project == target.project
                and identity.client == self.provider.config.client_id and (grant is None or identity.grant == grant),
                'subject_project_client_grant_mismatch')
        return identity

    def _finish(self, uid, base, lease, tokens, identity, *, deadline):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            version, _, previous = self.store.row(db, uid)
            current = db.execute('SELECT * FROM leases WHERE uid=?', (uid,)).fetchone()
            require(version == base and current is not None and current['id'] == lease
                    and current['expires'] > int(self.clock()) and deadline > int(self.clock()), 'stale_lifecycle_result')
            binding = Binding(uid, identity.subject, identity.project, identity.grant, 'live-ref-' + uid,
                              base + 1, self._target(uid).flow)
            if previous and previous.get('tokens') and previous['binding']['grant_id'] != identity.grant:
                self.store.queue_cleanup(db, uid, previous['tokens']['refresh'], previous['binding']['grant_id'])
            record = {'binding': asdict(binding), 'tokens': asdict(tokens), 'deadline': deadline,
                      'connected_at': (previous or {}).get('connected_at', int(self.clock()))}
            self.store.save(db, uid, base + 1, 'ACTIVE', record)
            db.execute('DELETE FROM leases WHERE uid=?', (uid,))
            db.execute('DELETE FROM pending WHERE uid=?', (uid,))

    def _disable(self, db, uid):
        self.store.disable(db, uid, self.provider.config.client_id, int(self.clock()))

    def _failed(self, uid, base, lease, tokens=None, error=None, identity=None, issued_from_refresh=None):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM leases WHERE uid=?', (uid,)).fetchone()
            version, _, old = self.store.row(db, uid)
            old_refresh = old['tokens']['refresh'] if old and old.get('tokens') else None
            attempted_at = current['expires'] - self.lease_seconds if current is not None else int(self.clock())
            cleanup_identity = asdict(identity) if identity else None
            if cleanup_identity is None and issued_from_refresh and old and old.get('binding'):
                cleanup_identity = {'subject': old['binding']['subject'], 'project': old['binding']['project_id'],
                                    'client': self.provider.config.client_id}
            if current is not None and current['id'] == lease and version == base:
                self._disable(db, uid)
            # Same refresh token from an obsolete refresh is already queued by revoke.
            refresh = tokens.refresh if tokens else error.refresh if isinstance(error, IssuedTokenRejected) else issued_from_refresh[0] if issued_from_refresh else None
            if refresh and refresh != old_refresh:
                self.store.queue_cleanup(db, uid, refresh, identity.grant if identity else issued_from_refresh[1] if issued_from_refresh else None,
                                         identity=cleanup_identity, attempted_at=attempted_at)
            elif not refresh and not old_refresh:
                # Exchange may have succeeded upstream before response loss/redirect.
                # No refresh token means only an approved formal USER grant review
                # can resolve this cleanup; never claim that no grant was issued.
                self.store.queue_cleanup(db, uid, None, attempted_at=attempted_at)

    def complete(self, uid, session, state, code):
        target = self._target(uid)
        base, lease, verifier = self._claim_callback(uid, session, state)
        tokens = identity = None
        try:
            tokens = self.provider.exchange(code, verifier)
            identity = self.provider.authenticate(tokens)
            self._approve_identity(identity, target)
            self._finish(uid, base, lease, tokens, identity, deadline=int(self.clock()) + self.retention_seconds)
        except Exception as error:
            self._failed(uid, base, lease, tokens, error, identity)
            raise GatewayError('oauth_connect_failed') from None
        return self.status(uid)

    def renew(self, uid, expected_generation, *, force=False):
        target = self._target(uid)
        require(type(expected_generation) is int and expected_generation > 0, 'expected_generation_required')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            base, status, record = self.store.row(db, uid)
            require(status == 'ACTIVE' and record and record.get('tokens') and record['deadline'] > int(self.clock()), 'reconnect_required')
            require(base >= expected_generation, 'invalid_refresh_generation')
            if base != expected_generation or not force and record['tokens']['expires'] > int(self.clock()) + 5:
                return self.status(uid)
            lease = self._lease(db, uid, base)
        tokens = identity = None
        try:
            tokens = self.provider.refresh(record['tokens']['refresh'])
            identity = self.provider.authenticate(tokens)
            self._approve_identity(identity, target, grant=record['binding']['grant_id'])
            self._finish(uid, base, lease, tokens, identity, deadline=record['deadline'])
        except Exception as error:
            self._failed(uid, base, lease, tokens, error, identity,
                         issued_from_refresh=(record['tokens']['refresh'], record['binding']['grant_id']))
            raise GatewayError('reconnect_required') from None
        return self.status(uid)

    def revoke(self, uid):
        self._target(uid)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._disable(db, uid)
        self.attempt_cleanup(uid)
        return self.status(uid)

    def attempt_cleanup(self, uid):
        self._target(uid)
        with self.store.db() as db:
            rows = [(r['id'], self.store.decode('cleanup', r['id'], r['envelope']))
                    for r in db.execute('SELECT * FROM cleanup WHERE uid=?', (uid,))]
        for number, item in rows:
            if item['submitted'] or not item['refresh']:
                continue
            try:
                self.provider.revoke(item['refresh'])
            except Exception:
                continue
            with self.store.db() as db:
                item['submitted'] = True
                db.execute('UPDATE cleanup SET envelope=? WHERE id=? AND uid=?',
                           (self.store.encode('cleanup', number, item), number, uid))
        return self.status(uid)

    def confirm_cleanup(self, uid, formal_grant_checker):
        # Server-only compatibility entry; generic callables/Booleans cannot
        # clear cleanup. The owner console uses this same purpose/CAS operator.
        from .cleanup_live import CleanupOperator, TrustedUiGrantChecker
        self._target(uid)
        require(type(formal_grant_checker) is TrustedUiGrantChecker and
                formal_grant_checker.spec.uid == uid, 'trusted_ui_checker_required')
        operator = CleanupOperator(self.registry, self.provider.config, clock=self.clock)
        operator.publish(formal_grant_checker)
        operator.apply()
        return self.status(uid)

    def ensure_active(self, binding):
        self.renew(binding.uid, binding.generation)

    async def get_active(self, reference, grant_id, generation):
        require(type(reference) is str and reference.startswith('live-ref-'), 'reconnect_required')
        uid = reference.removeprefix('live-ref-')
        binding = self.registry.resolve(uid)
        require(binding.credential_ref == reference and binding.grant_id == grant_id and binding.generation == generation, 'reconnect_required')
        with self.store.db() as db:
            base, status, record = self.store.row(db, uid)
            require(base == generation and status == 'ACTIVE' and record and record.get('tokens')
                    and record['tokens']['expires'] > int(self.clock()) and record['deadline'] > int(self.clock()), 'reconnect_required')
            return Tokens(**record['tokens']).access
