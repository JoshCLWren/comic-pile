"""Test that all modules in app and comic_pile can be imported without errors."""

import importlib
import pkgutil
import app
import comic_pile


def _import_submodules(package):
    """Recursively import all submodules of a package."""
    for _, name, ispkg in pkgutil.iter_modules(package.__path__):
        full_name = f"{package.__name__}.{name}"
        importlib.import_module(full_name)
        if ispkg:
            sub_pkg = importlib.import_module(full_name)
            _import_submodules(sub_pkg)

def test_import_all() -> None:
    """Verify all submodules import successfully."""
    _import_submodules(app)
    _import_submodules(comic_pile)
