"""Load an operator script by file path, without putting it on sys.path.

The obvious approach — a `scripts/__init__.py` plus a root `conftest.py` adding
the repo to `sys.path`, so tests can `from scripts.seed_x import ...` — is what
the Ideation Engine does, and it is what this plugin copied. **It does not
survive a second plugin.**

Both plugins are vendored into `biffo-platform` as `services/<name>/`, and both
would then define a *regular* package literally named `scripts`. A regular
package does not merge across `sys.path` entries: the first one found wins and
shadows the other outright, so the aggregate test run fails with
`ModuleNotFoundError: No module named 'scripts.seed_chat_agents'` — in the other
plugin's tests, which nobody touched. See keiranholloway/biffo-template#686.

Loading by path sidesteps the package namespace entirely: nothing named
`scripts` is imported, so there is nothing to collide. The scripts stay where an
operator expects them (`python scripts/seed_x.py`).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load_script(name: str) -> ModuleType:
    """Import ``scripts/<name>.py`` under a plugin-scoped module name."""
    path = _SCRIPTS / f"{name}.py"
    # Namespaced so it cannot collide with another plugin's script of the same
    # name in the aggregate run either.
    module_name = f"idea_scout_scripts.{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover — a missing file
        raise ImportError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
