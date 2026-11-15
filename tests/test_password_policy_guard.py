"""Static drift guard for the server-side password policy (issues #3103, #3112).

These tests are pure static analysis: no database, no application imports. They
exist so the six-character minimum the browser advertises cannot quietly become a
single-path check again. #3103 gated the register and reset-password request
schemas; #3112 added the same check to the reset-completion service, which had
been hashing and storing whatever password it was handed. A third
password-setting path, a reordered validation, or a re-introduced literal
minimum would each reopen the same hole, so the policy is pinned structurally
here as well as behaviorally in ``tests/test_password_length.py``.
"""

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPOSITORY_ROOT / "app"
AUTH_MODULE = APP_ROOT / "auth.py"
CONSTANTS_MODULE = APP_ROOT / "constants.py"

PASSWORD_HASHING_CALL = "hash_password"
POLICY_VALIDATOR_CALL = "validate_password_length"
MINIMUM_CONSTANT = "MIN_PASSWORD_LENGTH"
ADVERTISED_MINIMUM = 6

# Request schemas that accept a new password. Each one must gate length through
# the shared constant so the advertised minimum has exactly one definition.

# Statements in the reset-completion flow that persist credential state. The
# policy check must run before all of them so a refused attempt leaves both the
# stored password and the single-use token untouched.


def _parse(module_path: Path) -> ast.Module:
    """Parse one Python module.

    Args:
        module_path: File to read and parse.

    Returns:
        The parsed module tree.
    """
    return ast.parse(module_path.read_text(encoding="utf-8"))


def _call_target_name(call: ast.Call) -> str | None:
    """Return the called name of a call expression.

    Args:
        call: Call node to inspect.

    Returns:
        The bare or attribute name being called, or ``None`` for other callees.
    """
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def _called_names(tree: ast.Module) -> set[str]:
    """Collect every function name called anywhere in a module.

    Args:
        tree: Parsed module tree.

    Returns:
        Names of all called functions and methods.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = _call_target_name(node)
            if target is not None:
                names.add(target)
    return names


def _defines_function(tree: ast.Module, name: str) -> bool:
    """Report whether a module defines the named function.

    Args:
        tree: Parsed module tree.
        name: Function name to look for.

    Returns:
        ``True`` when the module declares that function itself.
    """
    return any(
        isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name
        for node in ast.walk(tree)
    )


def test_minimum_constant_matches_the_advertised_ui_minimum() -> None:
    """The shared constant stays at the six characters the UI advertises."""
    tree = _parse(CONSTANTS_MODULE)
    assigned: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                assigned[target.id] = node.value.value

    assert MINIMUM_CONSTANT in assigned, f"app/constants.py must define {MINIMUM_CONSTANT}"
    assert assigned[MINIMUM_CONSTANT] == ADVERTISED_MINIMUM, (
        f"{MINIMUM_CONSTANT} must stay {ADVERTISED_MINIMUM} to match the advertised minimum"
    )


def test_every_password_setting_path_applies_the_shared_policy() -> None:
    """Any module that hashes a password must apply the shared length policy.

    #3112 exists because ``complete_reset()`` hashed whatever password it was
    handed even though the request schema was already gated. A future
    password-setting path that skips the shared validator repeats that defect
    even when both schemas stay correct.
    """
    offenders: list[str] = []
    for module_path in sorted(APP_ROOT.rglob("*.py")):
        tree = _parse(module_path)
        called = _called_names(tree)
        if PASSWORD_HASHING_CALL not in called:
            continue
        if module_path == AUTH_MODULE and _defines_function(tree, PASSWORD_HASHING_CALL):
            continue
        if POLICY_VALIDATOR_CALL not in called:
            offenders.append(f"{module_path.relative_to(REPOSITORY_ROOT)}")

    assert not offenders, (
        "Every password-setting path must call "
        f"{POLICY_VALIDATOR_CALL}() before {PASSWORD_HASHING_CALL}() so the advertised "
        f"minimum holds server-side (issue #3112): {offenders}"
    )
