"""
Engine kind executors — one module per `kind` discriminator.

Each module exports an `execute(engine, step, definition, context, workflow_run, ...)`
function that returns a `StepResult`. The engine's `_execute_one_step` dispatches
on `step.kind` to the matching module.

This split was carved out of `workflow_engine.py` (2907 lines, 6
`_execute_*_step` methods) to keep the engine shell focused on dispatch,
hook-bus assembly, telemetry, and persistence — and to let each kind's
logic live in a file you can actually open without scrolling for ten
minutes. Pure refactor; behavior is preserved and proven by the existing
test suite (see tests/integration/test_*.py per kind).
"""
