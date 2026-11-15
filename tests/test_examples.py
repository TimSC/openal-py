"""Execute every example script; examples are documentation and must stay green."""
import os
import os
import pathlib
import subprocess
import sys

EXAMPLES = sorted(
    (pathlib.Path(__file__).parent.parent / "examples").glob("*.py"),
    key=lambda p: p.name,
)


def test_examples_exist():
    assert EXAMPLES, "no examples found"
    assert len(EXAMPLES) >= 6


def test_examples_run():
    failures = []
    for ex in EXAMPLES:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        proc = subprocess.run(
            [sys.executable, str(ex)],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if proc.returncode != 0:
            failures.append(f"{ex.name}:\n{proc.stderr}")
    assert not failures, "\n\n".join(failures)
