"""Run the complete baseline/candidate suite and emit an acceptance report."""

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / '.modernize-reports' / 'desktop-contracts.json'


def main():
    sys.path.insert(0, str(ROOT))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    # Remove stale success before discovery or execution can fail.
    REPORT.unlink(missing_ok=True)
    try:
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(ROOT / 'tests' / 'modernization'),
            pattern='test_*.py',
            top_level_dir=str(ROOT),
        )
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        failures = [
            {'test': test.id(), 'detail': detail}
            for test, detail in result.failures + result.errors + result.expectedFailures
        ]
        failures.extend(
            {'test': test.id(), 'detail': 'Unexpected success'}
            for test in result.unexpectedSuccesses
        )
        skipped = [{'test': test.id(), 'reason': reason} for test, reason in result.skipped]
        failed_count = len(failures)
        total = result.testsRun
        accepted = total > 0 and result.wasSuccessful() and not failures and not skipped
        report = {
            'numTotalTests': total,
            'numPassedTests': max(0, total - failed_count - len(skipped)),
            'numFailedTests': failed_count,
            'numPendingTests': len(skipped),
            'success': accepted,
            'failures': failures,
            'skipped': skipped,
        }
        if total == 0:
            report['harnessError'] = 'No tests were discovered; empty suites are not acceptance.'
    except Exception as exc:
        accepted = False
        report = {
            'numTotalTests': 0,
            'numPassedTests': 0,
            'numFailedTests': 0,
            'numPendingTests': 0,
            'success': False,
            'harnessError': f'{type(exc).__name__}: {exc}',
        }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
