"""Regression coverage for the canonical browser authentication contract."""

from pathlib import Path


def test_frontend_does_not_use_legacy_auth_surface() -> None:
    """Maintained frontend code must use the canonical auth family.

    Returns:
        None: Assertion fails if legacy /auth/ routes are found in maintained code.
    """
    frontend_root = Path("frontend/src")
    offenders: list[str] = []
    for path in frontend_root.rglob("*"):
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8")
        if any(f"{quote}/auth/" in text for quote in ("'", '"', "`")):
            offenders.append(str(path))

    assert offenders == [], f"Legacy auth routes found in maintained frontend: {offenders}"
