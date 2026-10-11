"""Offline, operator-owned migration of synthetic ADK2.8 SQLite histories only.

Stop this lab's Web/worker before applying or rolling back. No online username alias.
Backup and exact post-migration fingerprint prevent rollback from discarding new work.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from cmdbox_gateway.core import require

TABLES = ('sessions','events','user_states','app_states','adk_internal_metadata')

def fingerprint(db):
    rows = {t: sorted(db.execute('SELECT * FROM '+t).fetchall(),key=repr) for t in TABLES}
    return hashlib.sha256(json.dumps(rows,sort_keys=True).encode('utf8')).hexdigest()

def migrate(path, mappings, rollback_path):
    path, rollback_path = Path(path), Path(rollback_path)
    require(path.is_file() and not rollback_path.exists() and path.resolve()!=rollback_path.resolve(), 'migration_backup_required')
    require(type(mappings) is list and bool(mappings), 'explicit_uid_mapping_required')
    require(all(type(n) is str and n.startswith('legacy-') and type(u) is int and u in (101,202) for n,u in mappings),
            'synthetic_migration_only')
    require(len({n for n,u in mappings}) == len(mappings) and len({u for n,u in mappings}) == len(mappings), 'ambiguous_uid_mapping')
    with closing(sqlite3.connect(path,timeout=10)) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        db.execute('PRAGMA defer_foreign_keys=ON')
        # Version-specific schema contract: refuse another layout before any write.
        require([r[1] for r in db.execute('PRAGMA table_info(sessions)')] == ['app_name','user_id','id','state','create_time','update_time'],
                'unsupported_adk_schema')
        for name,uid in mappings:
            owner = 'cmdbox_uid_'+str(uid)
            for table in ('sessions','events','user_states'):
                require(db.execute('SELECT 1 FROM '+table+' WHERE user_id=?',(owner,)).fetchone() is None, 'migration_collision')
            require(db.execute('SELECT 1 FROM sessions WHERE user_id=?',(name,)).fetchone() is not None, 'legacy_owner_missing')
        # SQLite readers can take a consistent backup while our write reservation prevents concurrent mutations.
        with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(rollback_path)) as backup:
            source.backup(backup)
        for name,uid in mappings:
            for table in ('sessions','events','user_states'):
                db.execute('UPDATE '+table+' SET user_id=? WHERE user_id=?',('cmdbox_uid_'+str(uid),name))
        require(not db.execute('PRAGMA foreign_key_check').fetchall(), 'migration_foreign_key_failure')
        after = fingerprint(db)
    return {'after':after,'mappings':len(mappings),'mode':'SYNTHETIC-OFFLINE-ONLY'}

def rollback(path, rollback_path, expected_after):
    require(Path(rollback_path).is_file(), 'migration_backup_required')
    with closing(sqlite3.connect(path,timeout=10)) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        require(fingerprint(db) == expected_after, 'rollback_new_work_detected')
        db.execute('ATTACH DATABASE ? AS rollback_copy',(str(rollback_path),))
        db.execute('PRAGMA defer_foreign_keys=ON')
        for table in ('events','sessions','user_states','app_states','adk_internal_metadata'):
            db.execute('DELETE FROM '+table)
        for table in ('sessions','events','user_states','app_states','adk_internal_metadata'):
            db.execute('INSERT INTO '+table+' SELECT * FROM rollback_copy.'+table)
        require(not db.execute('PRAGMA foreign_key_check').fetchall(), 'rollback_foreign_key_failure')
    return {'status':'rolled_back','mode':'SYNTHETIC-OFFLINE-ONLY'}
