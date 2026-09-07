"""Every workflow file must parse, and the jobs must reference real modules.

A malformed workflow does not fail loudly. GitHub reports "this run likely failed
because of a workflow file issue" and there is NO log to read -- the run never started.
That is what a nested Python heredoc inside a `run:` block did here: the quoting broke
the YAML, and two pushes went green on tests while the ingest job silently never ran.
"""
import re
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

WORKFLOWS = sorted(Path(".github/workflows").glob("*.yml"))

needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml not installed")


def test_there_are_workflows_to_check():
    assert WORKFLOWS, "no workflow files found"


@needs_yaml
@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_parses(path):
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict), path.name
    assert doc.get("jobs"), f"{path.name} defines no jobs"


@needs_yaml
@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_python_module_it_runs_exists(path):
    """`python -m pipeline.x.y` against a module that is not there fails at runtime,
    on a schedule, where nobody is watching."""
    text = path.read_text()
    for mod in set(re.findall(r"python -m (pipeline\.[A-Za-z0-9_.]+)", text)):
        rel = Path(mod.replace(".", "/") + ".py")
        assert rel.exists(), f"{path.name} runs {mod}, which does not exist"
