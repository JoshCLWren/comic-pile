"""Public CBL repository sanitization for reader-facing API responses."""

from app.services.cbl_source_public import public_cbl_repository


def test_public_cbl_repository_maps_production_mirror_path() -> None:
    """The local CBL mirror path must not be returned to browsers."""
    assert (
        public_cbl_repository("/mnt/bigdata/CBL-ReadingLists")
        == "JoshCLWren/CBL-ReadingLists"
    )


def test_public_cbl_repository_keeps_github_style_names() -> None:
    """Already-public repository identities pass through unchanged."""
    assert public_cbl_repository("example/cbl") == "example/cbl"
