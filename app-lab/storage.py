"""SQLite persistence for NONSECRET synthetic binding records only."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
from cmdbox_gateway.core import BindingRegistry, Binding, FlowPolicy, require

class SyntheticSqliteBindings(BindingRegistry):
    def __init__(self, path, approved_flows):
        super().__init__(approved_flows)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS bindings (uid TEXT PRIMARY KEY, generation INTEGER NOT NULL, record TEXT NOT NULL)')
    def _db(self):
        return sqlite3.connect(self.path, timeout=10)
    def _read(self, row):
        if row is None: return None
        record = json.loads(row[0]); record['flow'] = FlowPolicy(**record['flow'])
        return Binding(**record)
    def get_record(self, uid):
        with self._db() as db:
            return self._read(db.execute('SELECT record FROM bindings WHERE uid=?', (uid,)).fetchone())
    def bind(self, binding):
        # SQLite in this lab MUST NOT accept actual AP identities or credential references.
        require(all(x.startswith('DUMMY-') for x in (binding.subject, binding.project_id, binding.grant_id))
                and binding.credential_ref.startswith('dummy-ref-'), 'synthetic_binding_only')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = self._read(db.execute('SELECT record FROM bindings WHERE uid=?', (binding.uid,)).fetchone())
            # Reuse core manifest/generation validation, while locking the durable row.
            self._rows = {} if previous is None else {binding.uid: previous}
            super().bind(binding)
            db.execute('INSERT INTO bindings VALUES (?, ?, ?) ON CONFLICT(uid) DO UPDATE SET generation=excluded.generation, record=excluded.record',
                       (binding.uid, binding.generation, json.dumps(asdict(binding))))
    def resolve(self, uid):
        binding = self.get_record(uid)
        require(binding is not None and binding.status == 'ACTIVE' and binding.flow in self._approved, 'reconnect_required')
        return binding
    def disable(self, uid):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = self._read(db.execute('SELECT record FROM bindings WHERE uid=?', (uid,)).fetchone())
            if previous:
                updated = replace(previous, generation=previous.generation + 1, status='RECONNECT_REQUIRED')
                db.execute('UPDATE bindings SET generation=?, record=? WHERE uid=?',
                           (updated.generation, json.dumps(asdict(updated)), uid))
