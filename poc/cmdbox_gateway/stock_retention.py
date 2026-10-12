"""Owned stock runtime retention. Does not hold/delete Google credentials.

AP/Google formal revocation is separate from local token removal. Failed revoke
keeps nonsecret operator cleanup records; no cleanup refresh token survives stop.
"""
from pathlib import Path
from contextlib import closing
import sqlite3
from .core import GatewayError, require


def purge_local_tokens(registry):
    approved = set(registry.targets)
    store = registry.store
    with store.db() as db:
        db.execute('PRAGMA secure_delete=ON')
        db.execute('BEGIN IMMEDIATE')
        require(all({r[0] for r in db.execute('SELECT uid FROM '+table)} <= approved
                    for table in ('records','cleanup','pending','leases')), 'stock_retention_scope_mismatch')
        for uid in approved:
            version, status, record = store.row(db, uid)
            if record:
                require(status == 'RECONNECT_REQUIRED', 'stock_disable_before_purge_required')
                record['tokens'] = None
                store.save(db, uid, version, status, record)
            for row in db.execute('SELECT * FROM cleanup WHERE uid=?', (uid,)).fetchall():
                item = store.decode('cleanup', row['id'], row['envelope'])
                item['refresh'] = None
                db.execute('UPDATE cleanup SET envelope=? WHERE id=?', (store.encode('cleanup',row['id'],item),row['id']))
            db.execute('DELETE FROM pending WHERE uid=?', (uid,))
            db.execute('DELETE FROM leases WHERE uid=?', (uid,))
    with store.db() as db:
        db.execute('VACUUM')
    return {'localTokenMaterialRemoved': True, 'formalRevocationConfirmed': False}


def purge_owned_metadata(data, private_root, uids):
    """Only this run's native-data history, after worker/listener shutdown."""
    data, private_root = Path(data).resolve(), Path(private_root).resolve()
    require(data == private_root / 'native-data', 'stock_metadata_root_mismatch')
    path = data / 'history.sqlite'
    if not path.exists():
        return {'metadataRemoved': True}
    approved = {'cmdbox_uid_' + str(uid) for uid in uids}
    allowed = {'sessions','events','app_states','user_states','adk_internal_metadata'}
    try:
        require(path.resolve()==path and path.stat().st_nlink==1, 'stock_metadata_link_not_owned')
        with closing(sqlite3.connect(path, timeout=2)) as db, db:
            db.execute('PRAGMA secure_delete=ON')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            require(tables <= allowed, 'stock_metadata_schema_mismatch')
            for table in tables - {'adk_internal_metadata'}:
                columns = {r[1] for r in db.execute('PRAGMA table_info(' + table + ')')}
                require('app_name' in columns and {r[0] for r in db.execute('SELECT DISTINCT app_name FROM ' + table)} <= {'adapter_lab'},
                        'stock_metadata_scope_mismatch')
                if 'user_id' in columns:
                    require({r[0] for r in db.execute('SELECT DISTINCT user_id FROM ' + table)} <= approved, 'stock_metadata_scope_mismatch')
                db.execute('DELETE FROM ' + table)
        with closing(sqlite3.connect(path, timeout=2)) as db, db:
            db.execute('VACUUM')
    except (OSError, sqlite3.Error, GatewayError):
        return {'metadataRemoved': False, 'operatorReviewRequired': True}
    return {'metadataRemoved': True, 'physicalEraseClaimed': False}


def retain_owned_metadata(data, private_root, uids):
    """Read-only ownership validation; keep history when deletion is unauthorized."""
    data, private_root = Path(data).resolve(), Path(private_root).resolve()
    require(data == private_root / 'native-data', 'stock_metadata_root_mismatch')
    path = data / 'history.sqlite'
    result = {'metadataRemoved': False, 'metadataRetained': True,
              'permanentDeletionPerformed': False, 'metadataPresent': path.exists()}
    if not path.exists():
        return {**result, 'metadataScopeVerified': True, 'metadataRowCounts': {}}
    approved = {'cmdbox_uid_' + str(uid) for uid in uids}
    allowed = {'sessions', 'events', 'app_states', 'user_states', 'adk_internal_metadata'}
    try:
        require(path.resolve() == path and path.stat().st_nlink == 1, 'stock_metadata_link_not_owned')
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            require(tables <= allowed, 'stock_metadata_schema_mismatch')
            counts = {}
            for table in tables:
                if table != 'adk_internal_metadata':
                    columns = {r[1] for r in db.execute('PRAGMA table_info(' + table + ')')}
                    require('app_name' in columns and {r[0] for r in db.execute('SELECT DISTINCT app_name FROM ' + table)} <= {'adapter_lab'},
                            'stock_metadata_scope_mismatch')
                    if 'user_id' in columns:
                        require({r[0] for r in db.execute('SELECT DISTINCT user_id FROM ' + table)} <= approved,
                                'stock_metadata_scope_mismatch')
                counts[table] = db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
    except (OSError, sqlite3.Error, GatewayError):
        return {**result, 'metadataScopeVerified': False, 'operatorReviewRequired': True}
    return {**result, 'metadataScopeVerified': True, 'metadataRowCounts': counts}
