"""Static contracts for fixed-model worker machine-readable outputs."""

from __future__ import annotations

import re
from pathlib import Path


WORKER = Path('.github/scripts/free-model-factory-worker.sh')


def _function_body(name: str) -> str:
    """Extract the function body from the worker script.

    Args:
        name: The name of the function to extract from the worker script.

    Returns:
        The function body text as a string.
    """
    text = WORKER.read_text(encoding='utf-8')
    match = re.search(rf'(?ms)^{re.escape(name)}\(\) \{{\n(.*?)^\}}$', text)
    assert match is not None, f'{name} function not found'
    return match.group(1)


def test_persist_issue_pr_stdout_is_reserved_for_pr_number() -> None:
    """Command substitution must capture only the numeric PR identifier."""
    body = _function_body('persist_issue_pr')

    assert 'git commit -m "factory: advance #${number} with ${DISPLAY}" >&2' in body
    assert 'git push --set-upstream origin "$branch" >&2' in body
    assert re.search(r'(?m)^  echo "\$pr"$', body)

    stdout_commands = [
        line.strip()
        for line in body.splitlines()
        if line.strip().startswith(('echo ', 'printf '))
        and not line.rstrip().endswith('>&2')
    ]
    assert stdout_commands == ['echo "$pr"']
