"""`volume_metric` must be assigned before it is read.

It was assigned about 120 lines *after* its own first use, both inside the per-market
loop. The consequences were invisible at runtime:

- the first market of every run raised UnboundLocalError into a bare `except`, losing
  recent form, target share, defensive detail, clearance rate and the entire
  usage-trend adjustment for that market;
- every market after it silently inherited the PREVIOUS market's driver, so a rushing
  prop following a receiving prop had its "carries trend" computed from targets and
  then fed straight into the projection.

Nothing raised and no counter caught it -- `with_adjustments` still incremented,
because the adjustment did fire, just off the wrong metric.

This is checked statically because the failure is an ordering property of the source.
Exercising it at runtime would need a live database and a market ordering that happens
to interleave families.
"""
import ast
import inspect

from pipeline.model import project


def _run_function() -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(project))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            return node
    raise AssertionError("project.run not found")


def test_volume_metric_is_assigned_before_it_is_used():
    fn = _run_function()

    first_assign = None
    first_use = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id == "volume_metric":
            if isinstance(node.ctx, ast.Store):
                if first_assign is None or node.lineno < first_assign:
                    first_assign = node.lineno
            else:
                if first_use is None or node.lineno < first_use:
                    first_use = node.lineno

    assert first_assign is not None, "volume_metric is never assigned in run()"
    assert first_use is not None, "volume_metric is never read in run()"
    assert first_assign < first_use, (
        f"volume_metric is read at line {first_use} but not assigned until "
        f"{first_assign} -- the first market of every run will raise "
        f"UnboundLocalError and every market after it inherits the previous "
        f"market's volume driver"
    )


def test_context_failures_are_counted_rather_than_swallowed():
    """The bare `except` around load_context is what hid the above.

    A failure must land in the skip counts so it is visible in the run record.
    """
    src = inspect.getsource(project.run)
    assert "context_failed" in src, (
        "load_context failures must be recorded as a skip reason, not silently "
        "discarded -- that is how the volume_metric bug survived"
    )
