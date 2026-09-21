#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Ensure fixture starts buggy
cat > examples/broken/buggy_math.py << 'PY'
def add(a: int, b: int) -> int:
    return a - b  # intentional bug — HealLoop must change to a + b
PY

export HEALLOOP_MOCK=1
python -m healloop run examples/broken --max-iter 3 --token-budget 5000 --root "$ROOT"
python - <<'PY'
import json
from pathlib import Path
p = Path(".healloop/last_scorecard.json")
if not p.is_file():
    raise SystemExit("scorecard missing at .healloop/last_scorecard.json")
data = json.loads(p.read_text())
print("scorecard status:", data.get("status"))
if data.get("status") != "green":
    raise SystemExit(f"expected green, got {data.get('status')}")
src = Path("examples/broken/buggy_math.py").read_text()
if "return a + b" not in src:
    raise SystemExit("buggy_math.py was not fixed to a + b")
print("selftest_mock: PASS")
PY
