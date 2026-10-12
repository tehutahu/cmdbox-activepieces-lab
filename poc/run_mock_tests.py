"""Offline only: no real AP, Redis, provider, private-file access or grant creation."""
import asyncio
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
class EvidenceResult(unittest.TextTestResult):
    outcomes = []
    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes.append({'name': test.id(), 'status': 'pass'})
    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes.append({'name': test.id(), 'status': 'fail', 'errorType': err[0].__name__})
    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes.append({'name': test.id(), 'status': 'fail', 'errorType': err[0].__name__})

def main():
    # The custom-piece experiment is preserved but is no longer the selected path.
    suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(ROOT / 'poc'), pattern=p.name)
        for p in sorted((ROOT / 'poc').glob('test_*.py')) if p.name != 'test_metadata_drive.py')
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    outcomes = list(result.outcomes); blocked = []; status = 'fail'
    if result.wasSuccessful():
        try:
            from adk_offline_exercise import exercise
            extra, blocked = asyncio.run(exercise()); outcomes += extra
            status = 'pass'
        except Exception as error:
            outcomes.append({'name': 'Actual ADK offline exercise', 'status': 'fail', 'errorType': type(error).__name__})
            print('ADK offline exercise failed: ' + type(error).__name__)
    evidence = dict(at=datetime.now(timezone.utc).isoformat(), mode='OFFLINE-IN-PROCESS-DUMMY', status=status,
                    python=sys.version.split()[0], googleAdk=importlib.metadata.version('google-adk'),
                    unitTestsRun=result.testsRun, outcomes=outcomes, socketConnectionAttemptsBlocked=blocked,
                    actualApContacted=False, actualRedisUsed=False, privateFilesRead=False,
                    realCredentialUsed=False, newGrantCreated=False, providerInferenceUsed=False,
                    model='Local scripted BaseLlm', cmdboxPublicPatchApplied=False,
                    limitations=['Review-only public cmdbox patch, not a booted cmdbox application',
                                 'Memory replay guard fixture; deployment needs shared atomic Redis guard',
                                 'No actual AP validation of this new adapter'])
    (ROOT / 'evidence').mkdir(exist_ok=True)
    (ROOT / 'evidence' / 'cmdbox-adapter-mock-results.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf8')
    return 0 if status == 'pass' else 1
if __name__ == '__main__':
    sys.exit(main())
