"""Encrypted record storage candidate. No mkdir, ACL changes or key generation.

Caller must provision and verify an approved owner-only root before real use.
Tests exclusively use a clearly labelled noncryptographic literal sealer.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sqlite3
from .core import GatewayError, canonical, require


class WindowsDpapiSealer:
    """CurrentUser DPAPI, UI forbidden. Never invoked by mock tests."""
    def _convert(self, value, purpose, *, protect):
        require(os.name == 'nt' and type(value) is bytes and type(purpose) is bytes, 'windows_dpapi_required')
        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
        buffer = ctypes.create_string_buffer(value)
        entropy = ctypes.create_string_buffer(b'cmdbox-live-v1:' + purpose)
        source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        extra = Blob(len(entropy.raw) - 1, ctypes.cast(entropy, ctypes.POINTER(ctypes.c_ubyte)))
        output = Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        function = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
        function.restype = wintypes.BOOL
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        try:
            require(function(ctypes.byref(source), None, ctypes.byref(extra), None, None, 1, ctypes.byref(output)), 'dpapi_operation_failed')
            return ctypes.string_at(output.data, output.size)
        finally:
            ctypes.memset(buffer, 0, len(buffer))
            if output.data:
                ctypes.memset(output.data, 0, output.size)
                kernel.LocalFree(output.data)

    def seal(self, value, purpose):
        return self._convert(value, purpose, protect=True)

    def open(self, value, purpose):
        return self._convert(value, purpose, protect=False)


class EncryptedStore:
    def __init__(self, root, sealer):
        self.root = Path(root).resolve()
        require(self.root.is_dir(), 'preprovisioned_private_root_required')
        require(callable(getattr(sealer, 'seal', None)) and callable(getattr(sealer, 'open', None)), 'configured_record_sealer_required')
        self.sealer, self.path = sealer, self.root / 'vault.sqlite'
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS records (uid TEXT PRIMARY KEY, version INTEGER, status TEXT, envelope BLOB);
                CREATE TABLE IF NOT EXISTS pending (digest TEXT PRIMARY KEY, uid TEXT, expires INTEGER, base INTEGER, envelope BLOB);
                CREATE TABLE IF NOT EXISTS leases (uid TEXT PRIMARY KEY, id INTEGER, base INTEGER, expires INTEGER);
                CREATE TABLE IF NOT EXISTS cleanup (id INTEGER PRIMARY KEY, uid TEXT, envelope BLOB);
                CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY CHECK(id=1), n INTEGER);
                INSERT OR IGNORE INTO counter VALUES (1,0);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def encode(self, kind, key, value):
        return self.sealer.seal(canonical(value), (kind + ':' + str(key)).encode('utf-8'))

    def decode(self, kind, key, value):
        try:
            result = json.loads(self.sealer.open(value, (kind + ':' + str(key)).encode('utf-8')))
            require(type(result) is dict, 'vault_record_invalid')
            return result
        except Exception:
            raise GatewayError('vault_record_unavailable') from None

    def row(self, db, uid):
        row = db.execute('SELECT * FROM records WHERE uid=?', (uid,)).fetchone()
        if row is None:
            return 0, 'RECONNECT_REQUIRED', None
        return row['version'], row['status'], self.decode('record', uid, row['envelope'])

    def save(self, db, uid, version, status, record):
        db.execute('INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(uid) DO UPDATE SET version=excluded.version,status=excluded.status,envelope=excluded.envelope',
                   (uid, version, status, self.encode('record', uid, record)))

    def next_id(self, db):
        return db.execute('UPDATE counter SET n=n+1 WHERE id=1 RETURNING n').fetchone()[0]

    def queue_cleanup(self, db, uid, refresh, grant=None, *, identity=None, attempted_at=None):
        for row in db.execute('SELECT * FROM cleanup WHERE uid=?', (uid,)):
            item = self.decode('cleanup', row['id'], row['envelope'])
            if item['refresh'] == refresh:
                changed = False
                for key, value in [('grant', grant), ('identity', identity), ('attempted_at', attempted_at)]:
                    if value is not None and not item.get(key):
                        item[key], changed = value, True
                if changed:
                    db.execute('UPDATE cleanup SET envelope=? WHERE id=?', (self.encode('cleanup', row['id'], item), row['id']))
                return row['id']
        number = self.next_id(db)
        db.execute('INSERT INTO cleanup VALUES (?,?,?)',
                   (number, uid, self.encode('cleanup', number, {'refresh': refresh, 'grant': grant, 'submitted': False, 'identity': identity, 'attempted_at': attempted_at})))
        return number

    def disable(self, db, uid, client, now):
        version, _, record = self.row(db, uid)
        record = record or {'binding': None, 'tokens': None, 'deadline': 0}
        if record.get('tokens'):
            binding = record['binding']
            self.queue_cleanup(db, uid, record['tokens']['refresh'], binding['grant_id'],
                identity={'subject': binding['subject'], 'project': binding['project_id'], 'client': client},
                attempted_at=record.get('connected_at', now))
        record['tokens'] = None
        if record.get('binding'):
            record['binding']['generation'], record['binding']['status'] = version + 1, 'RECONNECT_REQUIRED'
        self.save(db, uid, version + 1, 'RECONNECT_REQUIRED', record)
        db.execute('DELETE FROM leases WHERE uid=?', (uid,))
        db.execute('DELETE FROM pending WHERE uid=?', (uid,))
