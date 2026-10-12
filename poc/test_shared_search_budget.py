"""Exercise the actual native Window class without importing/starting the app."""
from pathlib import Path
import ast
from contextlib import contextmanager
import sqlite3
import tempfile
import time
import unittest
from cmdbox_gateway.core import require, GatewayError

ROOT = Path(__file__).resolve().parents[1]

class Store:
    def __init__(self, path): self.path = path
    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path)
        try:
            with db: yield db
        finally: db.close()

class SharedSearchBudgetTests(unittest.TestCase):
    def test_original_ledger_survives_new_oauth_window_and_refuses_third_search(self):
        tree = ast.parse((ROOT/'app-lab/live_app.py').read_text(encoding='utf8'))
        node = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'Window')
        scope = {'time': time, 'require': require}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'native-Window', 'exec'), scope)
        with tempfile.TemporaryDirectory() as directory:
            old, new = Store(Path(directory)/'old.sqlite'), Store(Path(directory)/'new.sqlite')
            with old.db() as db:
                db.execute('CREATE TABLE app_budget(uid TEXT, operation TEXT, n INTEGER, PRIMARY KEY(uid,operation))')
                db.execute("INSERT INTO app_budget VALUES ('202','flow',1)")
                db.execute("INSERT INTO app_budget VALUES ('202','exchange',1)")
            with new.db() as db:
                db.execute('CREATE TABLE operator_control(id INTEGER PRIMARY KEY,reason TEXT)')
            window = scope['Window'](new, clock=lambda: 1000, flow_budget_store=old)
            window.begin(); window.spend('202', 'flow', 2)
            with old.db() as db:
                self.assertEqual(db.execute("SELECT n FROM app_budget WHERE operation='flow'").fetchone()[0], 2)
            with new.db() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM app_budget WHERE operation='flow'").fetchone()[0], 0)
            with self.assertRaisesRegex(GatewayError, 'approved_operation_budget_exhausted'):
                window.spend('202', 'flow', 2)
            window.spend('202', 'exchange', 1)
            with new.db() as db:
                self.assertEqual(db.execute("SELECT n FROM app_budget WHERE operation='exchange'").fetchone()[0], 1)
            with old.db() as db:
                self.assertEqual(db.execute("SELECT n FROM app_budget WHERE operation='exchange'").fetchone()[0], 1)

if __name__ == '__main__': unittest.main()
