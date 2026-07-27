"""Make `idea_scout` and the test-local `fakes` module importable.

This template is a standalone repo (not part of the biffo-template
monorepo's uv workspace — see README's "Standalone repo" note), so
`idea_scout` is installed normally via the project's own
[build-system]/hatchling config when `uv sync` runs. This conftest only
needs to put `tests/` itself on sys.path so `tests/test_idea_scout.py`
can `import fakes` as a plain sibling module (pytest's rootdir insertion
already covers this in most configurations, but the explicit path insert
keeps this working from any cwd, matching the RBAC reference plugin's
`services/rbac/tests/conftest.py` pattern in the biffo-template monorepo).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Test modules are named test_idea_scout_*.py, not test_*.py.
#
# Every plugin is vendored into biffo-platform as services/<name>/, and these
# tests/ directories carry no __init__.py, so pytest's default import mode gives
# each module its bare basename. Two plugins both shipping tests/test_manifest.py
# then collide at collection with "import file mismatch" — in the *other*
# plugin's tests, which nobody touched. That is exactly what installing this
# plugin alongside the Ideation Engine did.
#
# --import-mode=importlib fixes the class properly but breaks other suites in the
# instance that rely on the prepend behaviour, so the narrow fix wins: unique
# basenames. See keiranholloway/biffo-template#686.
