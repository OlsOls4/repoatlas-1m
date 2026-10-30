"""Resume wrapper for the interrupted extension run (does NOT modify frozen scripts/ext_run.py).

Imports scripts/ext_run.py unchanged and wraps ablation_triage.call() with a guard:
  * if the raw output for a call already exists, it must be the cached record for the identical payload
    (payload_sha256 match) and is returned as-is; otherwise the run aborts -> no item already in raw/ is ever re-called.
  * --check: no API key, no saving; reports for every selected call whether it is cached (sha match), would be a NEW
    call, or mismatched.
Usage: python resume_guard.py [--check] <ext_run.py args...>
"""
import hashlib, json, sys
from pathlib import Path
CHECK = "--check" in sys.argv
if CHECK:
    sys.argv.remove("--check")
sys.path.insert(0, "/workspace/ablation/matched_cost_ext/scripts")
import ext_run as R  # noqa: E402
A = R.A
_orig_call = A.call
report = []

def guarded_call(kind, label, payload, est, cap, api_key, raw_file, nonce=""):
    key = hashlib.sha256(json.dumps([A.H.BASE_URL, payload, nonce], sort_keys=True).encode()).hexdigest()
    if raw_file.exists():
        rec = json.loads(raw_file.read_text())
        if rec.get("payload_sha256") == key and rec.get("body"):
            report.append(("cached", kind, label))
            return rec
        report.append(("MISMATCH", kind, label))
        raise RuntimeError(f"GUARD: {raw_file} exists but payload differs; refusing to re-call {kind} {label}")
    report.append(("NEW", kind, label, est))
    if CHECK:
        return None
    return _orig_call(kind, label, payload, est, cap, api_key, raw_file, nonce)

A.call = guarded_call
if CHECK:
    R._save = lambda *a, **k: None
    sys.argv.append("--dry-run")
try:
    R.main()
finally:
    for r in report:
        print("GUARD", *r, flush=True)
