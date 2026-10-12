"""Actual production launcher/schema/bootstrap: native Web/Redis/ADK + literal stock MCP.

No toolset factory monkeypatch, stock-piece execution or Google/AP network request.
"""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtimes/app-deps'),str(ROOT/'poc'),str(ROOT/'app-lab')]
from datetime import datetime,timezone
import asyncio
import httpx
import json
import os
import socket
import sqlite3
import subprocess
import time
from contextlib import closing
from test_live_ui import turn
from test_cleanup_native import authorize,operation,operator


def history_rows(root):
    with closing(sqlite3.connect((root/'native-data/history.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        return {t:sorted(db.execute('SELECT * FROM '+t).fetchall(),key=repr)
                for t in ('sessions','events','user_states','app_states')}


def case(root, failure):
    for port in (18089,18090):
        with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',port))!=0,'Owned listener conflict'
    log=(ROOT/'local-review'/(root.name+'.log')).open('x',encoding='utf8')
    command=[sys.executable,str(ROOT/'app-lab/live_launcher.py'),'--mock-root',str(root),
             '--mock-stock-drive','--mock-test-clock']
    if failure:command.append('--mock-revoke-failure')
    proc=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    clients=[]
    try:
        for _ in range(160):
            assert proc.poll() is None,'Inspect owned stock bootstrap log'
            try:
                response=httpx.get('http://localhost:18090/status',trust_env=False,timeout=1)
                if response.json()['ready']:break
            except (httpx.HTTPError,ValueError,KeyError):pass
            time.sleep(.25)
        else:raise AssertionError('Stock bootstrap timeout')
        assert response.json()['authorizationStartedAt'] is None
        cfg=json.loads((root/'native-data/.agent/mcpsv-approved_gateway.json').read_text())
        assert cfg['mcpserver_mcp_tools']==['lab_drive_search']
        a,b=authorize('A','101'),authorize('B','202');clients=[a,b]
        for client,own,other in ((a,'A_ONLY_SYNTHETIC_FILE','B_ONLY_SYNTHETIC_FILE'),(b,'B_ONLY_SYNTHETIC_FILE','A_ONLY_SYNTHETIC_FILE')):
            text=asyncio.run(turn(client))
            assert own in text and other not in text and 'unverified-by-stock-piece' in text,text
            assert 'modifiedTime' not in text and 'policyId' not in text
        if not failure:
            assert operation(a,'refresh')['generation']==2
            assert 'A_ONLY' in asyncio.run(turn(a))
            assert 'approved_operation_budget_exhausted' in asyncio.run(turn(a))
            assert operation(a,'revoke')['cleanupPending']
            assert 'reconnect_required' in asyncio.run(turn(a))
            status=a.get('/status').json()
            before_history=history_rows(root)
            (root/'mock-clock.json').write_text(json.dumps({'now':status['authorizationStartedAt']+7201}),encoding='utf8')
        else:
            before_history=history_rows(root)
            (root/'stop-request').write_text('MOCK-ONLY',encoding='utf8')
        proc.wait(25)
        assert proc.returncode==0,'Inspect owned termination log'
        assert not (root/'settings.dpapi').exists()
        op=operator(root)
        with op.store.db() as db:
            assert db.execute('SELECT count(*) FROM pending').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM leases').fetchone()[0]==0
            for uid in ('101','202'):
                _,status,record=op.store.row(db,uid)
                assert status=='RECONNECT_REQUIRED' and record['tokens'] is None
                for row in db.execute('SELECT * FROM cleanup WHERE uid=?',(uid,)):
                    assert op.store.decode('cleanup',row['id'],row['envelope'])['refresh'] is None
        assert op.summary()['cleanupPendingCount']==2,'No formal revocation claim from HTTP result'
        retention=json.loads((root/'retention-status.json').read_text())
        assert retention['metadataRetained'] and not retention['metadataRemoved']
        assert retention['metadataScopeVerified'] and not retention['permanentDeletionPerformed']
        assert retention['localTokenMaterialRemoved'] and retention['workerStopped']
        assert retention['remoteGoogleCleanupConfirmed'] is False
        assert before_history['sessions'] and before_history['events'], 'Exercise real native history'
        assert history_rows(root)==before_history, 'Keep every history/state row unchanged at shutdown'
        for port in (18089,18090):
            with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',port))!=0
        import redis
        red=redis.Redis(host='127.0.0.1',port=18091)
        assert not red.exists('hb-cmdboxlive-approved-worker')
        assert not red.hexists('mem-cmdboxlive','signin_file_data');red.close()
        return {'name':'Native stock production bootstrap, UID separation, '+('failed-revoke stop' if failure else 'refresh/revoke/deadline stop'),
                'status':'pass','calls':2 if failure else 3,'metadataRetained':True,'historyRowsUnchanged':True,'formalCleanupStillPending':True}
    finally:
        for client in clients:client.close()
        if proc.poll() is None:
            (root/'stop-request').write_text('MOCK-ONLY',encoding='utf8')
            try:proc.wait(25)
            except subprocess.TimeoutExpired:proc.terminate();proc.wait(5)
        log.close()


if __name__=='__main__':
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f');outcomes=[];status='fail'
    try:
        for failure in (False,True):outcomes.append(case(ROOT/'app-lab/data'/('stock-native-'+str(failure)+'-'+stamp),failure))
        status='pass'
    finally:
        result={'status':status,'outcomes':outcomes,'actualApContacted':False,'actualGoogleContacted':False,
                'stockPieceExecuted':False,'realSecretOrGrantCreated':False,'actualDpapiExecuted':False}
        (ROOT/'local-review'/('stock-native-'+stamp+'-results.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print(json.dumps(result))
    sys.exit(0 if status=='pass' else 1)
