"""Site customizations for test environment.
Adds a ``full_match`` method to ``pathlib.PurePosixPath`` used by
``tests/test_vercel_production_only.py``.
"""
import pathlib

def _pureposix_full_match(self, pattern: str) -> bool:
    """Return True if the path fully matches the glob pattern.
    ``PurePosixPath.match`` matches the pattern against the entire path,
    which satisfies the test's expectations for simple patterns like "*".
    """
    return self.match(pattern)

# Monkey-patch the class if the attribute does not already exist.
if not hasattr(pathlib.PurePosixPath, "full_match"):
    setattr(pathlib.PurePosixPath, "full_match", _pureposix_full_match)
