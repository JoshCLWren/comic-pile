"""Tests for ComicVine taste feature extraction."""

from __future__ import annotations

from app.services.comicvine_taste import extract_taste_features


def test_extract_taste_features_creators_with_roles() -> None:
    """Creator role is preserved where available."""
    issue_metadata = {
        "creator_credits": [
            {"id": 1, "name": "Writer One", "role": "writer"},
            {"id": 2, "name": "Artist One", "role": "artist"},
            {"id": 3, "name": "Writer Two", "role": "writer"},  # Different person
        ]
    }
    
    result = extract_taste_features(issue_metadata)
    
    assert len(result["creators"]) == 3
    # Check that roles are preserved
    creator_roles = {c["id"]: c.get("role") for c in result["creators"]}
    assert creator_roles[1] == "writer"
    assert creator_roles[2] == "artist"
    assert creator_roles[3] == "writer"


def test_extract_taste_features_creators_deduplication() -> None:
    """Duplicate credits do not double-count the same feature for one issue."""
    issue_metadata = {
        "creator_credits": [
            {"id": 1, "name": "Writer One", "role": "writer"},
            {"id": 1, "name": "Writer One", "role": "writer"},  # Duplicate
            {"id": 1, "name": "Writer One", "role": "penciler"},  # Same creator, different role
            {"id": 2, "name": "Writer Two"},  # No role
            {"id": 2, "name": "Writer Two"},  # Duplicate, no role
        ]
    }
    
    result = extract_taste_features(issue_metadata)
    
    # Should have 3 features:
    # - Writer One as writer
    # - Writer One as penciler
    # - Writer Two (no role)
    assert len(result["creators"]) == 3
    
    # Check the features
    creators_by_id_role = {}
    for creator in result["creators"]:
        key = (creator["id"], creator.get("role"))
        creators_by_id_role[key] = creator["name"]
    
    assert (1, "writer") in creators_by_id_role
    assert (1, "penciler") in creators_by_id_role
    assert (2, None) in creators_by_id_role


def test_extract_taste_features_characters() -> None:
    """Character features are extracted correctly."""
    issue_metadata = {
        "characters": [
            {"id": 1, "name": "Hero One"},
            {"id": 2, "name": "Hero Two"},
            {"id": 1, "name": "Hero One"},  # Duplicate
        ]
    }
    
    result = extract_taste_features(issue_metadata)
    
    assert len(result["characters"]) == 2
    character_ids = {c["id"] for c in result["characters"]}
    assert character_ids == {1, 2}


def test_extract_taste_features_teams() -> None:
    """Team features are extracted correctly."""
    issue_metadata = {
        "teams": [
            {"id": 1, "name": "Team Alpha"},
            {"id": 2, "name": "Team Beta"},
            {"id": 1, "name": "Team Alpha"},  # Duplicate
        ]
    }
    
    result = extract_taste_features(issue_metadata)
    
    assert len(result["teams"]) == 2
    team_ids = {t["id"] for t in result["teams"]}
    assert team_ids == {1, 2}


def test_extract_taste_features_publisher() -> None:
    """Publisher feature is extracted from volume metadata."""
    issue_metadata = {}  # Issue metadata doesn't contain publisher
    volume_metadata = {
        "publisher": {"id": 1, "name": "Publisher One"}
    }
    
    result = extract_taste_features(issue_metadata, volume_metadata)
    
    assert result["publisher"] is not None
    assert result["publisher"]["id"] == 1
    assert result["publisher"]["name"] == "Publisher One"


def test_extract_taste_features_publisher_missing() -> None:
    """Missing publisher yields None (no fabricated evidence)."""
    issue_metadata = {}
    volume_metadata = {}  # No publisher in volume metadata
    
    result = extract_taste_features(issue_metadata, volume_metadata)
    
    assert result["publisher"] is None


def test_extract_taste_features_publication_era_from_issue() -> None:
    """Publication era extracted from issue cover_date."""
    issue_metadata = {
        "cover_date": "2026-01-15"
    }
    volume_metadata = {}
    
    result = extract_taste_features(issue_metadata, volume_metadata)
    
    assert result["publication_era"] == "2026"


def test_extract_taste_features_publication_era_from_volume() -> None:
    """Publication era extracted from volume start_year when not in issue."""
    issue_metadata = {"store_date": ""}  # Empty string
    volume_metadata = {
        "start_year": "2025"
    }
    
    result = extract_taste_features(issue_metadata, volume_metadata)
    
    assert result["publication_era"] == "2025"


def test_extract_taste_features_publication_era_missing() -> None:
    """Missing publication date yields None (no fabricated evidence)."""
    issue_metadata = {}
    volume_metadata = {}
    
    result = extract_taste_features(issue_metadata, volume_metadata)
    
    assert result["publication_era"] is None


def test_extract_taste_features_publication_era_invalid_date() -> None:
    """Invalid date format yields None (no fabricated evidence)."""
    issue_metadata = {
        "cover_date": "not-a-date"
    }
    volume_metadata = {}
    
    result = extract_taste_features(issue_metadata, volume_metadata)
    
    assert result["publication_era"] is None


def test_extract_taste_features_empty_input() -> None:
    """Handle empty metadata gracefully."""
    issue_metadata = {}
    volume_metadata = None
    
    result = extract_taste_features(issue_metadata, volume_metadata)
    
    assert result["creators"] == []
    assert result["characters"] == []
    assert result["teams"] == []
    assert result["publisher"] is None
    assert result["publication_era"] is None


def test_extract_taste_features_confirmed_metadata_produces_stable_keys() -> None:
    """Confirmed issue metadata produces stable normalized feature keys."""
    # This is a structural test - we check that the output has the expected structure
    issue_metadata = {
        "creator_credits": [{"id": 1, "name": "Test Creator", "role": "writer"}],
        "characters": [{"id": 2, "name": "Test Character"}],
        "teams": [{"id": 3, "name": "Test Team"}],
        "cover_date": "2026-01-01",
    }
    volume_metadata = {
        "publisher": {"id": 4, "name": "Test Publisher"}
    }
    
    result = extract_taste_features(issue_metadata, volume_metadata)
    
    # Check structure
    assert isinstance(result, dict)
    assert "creators" in result
    assert "characters" in result
    assert "teams" in result
    assert "publisher" in result
    assert "publication_era" in result
    
    # Check types
    assert isinstance(result["creators"], list)
    assert isinstance(result["characters"], list)
    assert isinstance(result["teams"], list)
    assert result["publisher"] is None or isinstance(result["publisher"], dict)
    assert result["publication_era"] is None or isinstance(result["publication_era"], str)
    
    # Check content
    assert len(result["creators"]) == 1
    assert result["creators"][0]["id"] == 1
    assert result["creators"][0]["name"] == "Test Creator"
    assert result["creators"][0]["role"] == "writer"
    
    assert len(result["characters"]) == 1
    assert result["characters"][0]["id"] == 2
    assert result["characters"][0]["name"] == "Test Character"
    
    assert len(result["teams"]) == 1
    assert result["teams"][0]["id"] == 3
    assert result["teams"][0]["name"] == "Test Team"
    
    assert result["publisher"] is not None
    assert result["publisher"]["id"] == 4
    assert result["publisher"]["name"] == "Test Publisher"
    
    assert result["publication_era"] == "2026"


def test_extract_taste_features_use_confirmed_mappings_only_by_default() -> None:
    """Use confirmed mappings only by default - tested by ignoring unconfirmed/malformed data."""
    issue_metadata = {
        "creator_credits": [
            {"id": 1, "name": "Valid Creator", "role": "writer"},
            {"id": None, "name": "Invalid Creator", "role": "writer"},  # Missing ID
            {"id": 2, "name": "", "role": "artist"},  # Missing name
            "not-a-dict",  # Wrong type
            {},  # Empty dict
        ],
        "characters": [
            {"id": 1, "name": "Valid Character"},
            {"id": None, "name": "Invalid Character"},  # Missing ID
            {"id": 2, "name": ""},  # Missing name
            "not-a-dict",
            {},
        ],
        "teams": [
            {"id": 1, "name": "Valid Team"},
            {"id": None, "name": "Invalid Team"},  # Missing ID
            {"id": 2, "name": ""},  # Missing name
            "not-a-dict",
            {},
        ],
    }
    volume_metadata = {
        "publisher": {"id": 1, "name": "Valid Publisher"}
        # Intentionally omitting invalid publisher data to test that we don't fabricate
    }
    
    result = extract_taste_features(issue_metadata, volume_metadata)
    
    # Should only have valid entries
    assert len(result["creators"]) == 1
    assert result["creators"][0]["id"] == 1
    assert result["creators"][0]["name"] == "Valid Creator"
    assert result["creators"][0]["role"] == "writer"
    
    assert len(result["characters"]) == 1
    assert result["characters"][0]["id"] == 1
    assert result["characters"][0]["name"] == "Valid Character"
    
    assert len(result["teams"]) == 1
    assert result["teams"][0]["id"] == 1
    assert result["teams"][0]["name"] == "Valid Team"
    
    assert result["publisher"] is not None
    assert result["publisher"]["id"] == 1
    assert result["publisher"]["name"] == "Valid Publisher"