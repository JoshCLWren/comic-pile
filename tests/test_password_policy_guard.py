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
AUTH_SCHEMA_MODULE = APP_ROOT / "schemas" / "auth.py"
CONSTANTS_MODULE = APP_ROOT / "constants.py"
PASSWORD_RESET_SERVICE_MODULE = APP_ROOT / "services" / "password_reset_service.py"

PASSWORD_HASHING_CALL = "hash_password"
POLICY_VALIDATOR_CALL = "validate_password_length"
MINIMUM_CONSTANT = "MIN_PASSWORD_LENGTH"
ADVERTISED_MINIMUM = 6
RESET_COMPLETION_FUNCTION = "complete_reset"

# Request schemas that accept a new password. Each one must gate length through
# the shared constant so the advertised minimum has exactly one definition.
GATED_SCHEMA_FIELDS = (
    ("UserRegisterRequest", "password"),
    ("ResetPasswordRequest", "new_password"),
)

# Statements in the reset-completion flow that persist credential state. The
# policy check must run before all of them so a refused attempt leaves both the
# stored password and the single-use token untouched.
RESET_MUTATION_CALLS = ("mark_used", "commit", PASSWORD_HASHING_CALL)
RESET_MUTATION_ATTRIBUTES = ("password_hash", "password_changed_at")


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


def _annotated_fields(tree: ast.Module, class_name: str) -> dict[str, ast.expr]:
    """Map a class body's annotated attributes to their assigned expressions.

    Args:
        tree: Parsed module tree.
        class_name: Class to inspect.

    Returns:
        Attribute name to assigned expression for every annotated assignment.
    """
    fields: dict[str, ast.expr] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if (
                isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and item.value is not None
            ):
                fields[item.target.id] = item.value
    return fields


def _min_length_argument(value: ast.expr) -> str | None:
    """Return the ``min_length`` argument of a ``Field(...)`` assignment.

    Args:
        value: Assigned expression for an annotated schema field.

    Returns:
        The unparsed ``min_length`` value, or ``None`` when the field does not
        declare one through ``Field``.
    """
    if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name):
        return None
    if value.func.id != "Field":
        return None
    for keyword in value.keywords:
        if keyword.arg == "min_length":
            return ast.unparse(keyword.value)
    return None


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Return the named function definition from a module.

    Args:
        tree: Parsed module tree.
        name: Function to locate.

    Returns:
        The matching function definition.

    Raises:
        AssertionError: When the module no longer declares that function.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"expected a {name}() definition")


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


def test_password_schemas_gate_length_through_the_shared_constant() -> None:
    """Register and reset-password schemas must gate on the shared minimum.

    A literal minimum in a schema would let the advertised policy drift away from
    the constant the services enforce, which is the class of defect #3103 fixed.
    """
    tree = _parse(AUTH_SCHEMA_MODULE)

    imports_shared_constant = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "app.constants"
        and any(alias.name == MINIMUM_CONSTANT for alias in node.names)
        for node in ast.walk(tree)
    )
    assert imports_shared_constant, (
        f"app/schemas/auth.py must import {MINIMUM_CONSTANT} from app.constants"
    )

    for class_name, field_name in GATED_SCHEMA_FIELDS:
        fields = _annotated_fields(tree, class_name)
        assert field_name in fields, f"{class_name} must still declare {field_name}"
        min_length = _min_length_argument(fields[field_name])
        assert min_length == MINIMUM_CONSTANT, (
            f"{class_name}.{field_name} must declare "
            f"Field(..., min_length={MINIMUM_CONSTANT}); found {min_length!r}"
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


def test_reset_completion_validates_before_touching_credential_state() -> None:
    """The reset service must check the minimum before any credential mutation.

    Validation that runs after ``mark_used()`` or after the new hash is assigned
    would refuse the request only after burning the single-use token and writing
    the rejected hash, leaving the account unrecoverable from that link.
    """
    function = _find_function(_parse(PASSWORD_RESET_SERVICE_MODULE), RESET_COMPLETION_FUNCTION)

    validation_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and _call_target_name(node) == POLICY_VALIDATOR_CALL
    ]
    mutation_lines = [
        node.lineno
        for node in ast.walk(function)
        if (
            isinstance(node, ast.Call)
            and _call_target_name(node) in RESET_MUTATION_CALLS
        )
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute) and target.attr in RESET_MUTATION_ATTRIBUTES
                for target in node.targets
            )
        )
    ]

    assert validation_lines, (
        f"{RESET_COMPLETION_FUNCTION}() must call {POLICY_VALIDATOR_CALL}() "
        "(issue #3112)"
    )
    assert mutation_lines, (
        f"{RESET_COMPLETION_FUNCTION}() must still persist the new password hash"
    )
    assert min(validation_lines) < min(mutation_lines), (
        f"{RESET_COMPLETION_FUNCTION}() must validate the minimum password length before "
        "consuming the reset token or writing the new hash (issue #3112)"
    )