"""Feature extraction for ComicVine taste discovery from confirmed metadata."""

from __future__ import annotations

from typing import Any


def _extract_creator_features(creator_credits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract and deduplicate creator features from credits.
    
    Args:
        creator_credits: List of creator credit dictionaries from normalized issue metadata.
        
    Returns:
        List of deduplicated creator features with id, name, and role (if available).
    """
    seen = set()
    features = []
    
    for credit in creator_credits:
        if not isinstance(credit, dict):
            continue
            
        creator_id = credit.get("id")
        name = credit.get("name")
        role = credit.get("role")
        
        # Skip if missing required fields
        if creator_id is None or not name:
            continue
            
        # Create deduplication key: (id, role) if role available, else (id, None)
        dedup_key = (creator_id, role if role is not None else None)
        
        if dedup_key in seen:
            continue
            
        seen.add(dedup_key)
        
        feature = {"id": creator_id, "name": str(name)}
        if role is not None:
            feature["role"] = str(role)
            
        features.append(feature)
        
    return features


def _extract_reference_features(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract and deduplicate reference features (characters, teams, etc.).
    
    Args:
        references: List of reference dictionaries from normalized metadata.
        
    Returns:
        List of deduplicated reference features with id and name.
    """
    seen = set()
    features = []
    
    for ref in references:
        if not isinstance(ref, dict):
            continue
            
        ref_id = ref.get("id")
        name = ref.get("name")
        
        # Skip if missing required fields
        if ref_id is None or not name:
            continue
            
        dedup_key = ref_id
        
        if dedup_key in seen:
            continue
            
        seen.add(dedup_key)
        
        features.append({"id": ref_id, "name": str(name)})
        
    return features


def _extract_publisher_feature(volume_metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract publisher feature from volume metadata.
    
    Args:
        volume_metadata: Normalized volume metadata dictionary.
        
    Returns:
        Publisher feature dict with id and name, or None if not available.
    """
    if not isinstance(volume_metadata, dict):
        return None
        
    publisher = volume_metadata.get("publisher")
    
    if not isinstance(publisher, dict):
        return None
        
    publisher_id = publisher.get("id")
    name = publisher.get("name")
    
    # Skip if missing required fields
    if publisher_id is None or not name:
        return None
        
    return {"id": publisher_id, "name": str(name)}


def _extract_publication_era(
    issue_metadata: dict[str, Any],
    volume_metadata: dict[str, Any] | None = None
) -> str | None:
    """Extract publication era/date bucket from issue or volume metadata.
    
    Args:
        issue_metadata: Normalized issue metadata dictionary.
        volume_metadata: Optional normalized volume metadata dictionary.
        
    Returns:
        Publication era bucket (year as string) or None if not available.
    """
    # Try issue cover_date or store_date first
    date_source = issue_metadata.get("cover_date") or issue_metadata.get("store_date")
    
    # If not in issue, try volume start_year
    if not date_source and volume_metadata:
        date_source = volume_metadata.get("start_year")
        
    if not isinstance(date_source, str) or not date_source:
        return None
        
    # Extract year from date string (YYYY-MM-DD format or just YYYY)
    try:
        # Handle ISO format dates
        if "T" in date_source:
            date_part = date_source.split("T")[0]
        else:
            date_part = date_source
            
        # Extract YYYY from YYYY-MM-DD
        if "-" in date_part:
            year_str = date_part.split("-")[0]
        else:
            year_str = date_part
            
        # Validate year is 4 digits
        if len(year_str) == 4 and year_str.isdigit():
            return year_str
    except (IndexError, AttributeError):
        pass
        
    return None


def extract_taste_features(
    issue_metadata: dict[str, Any],
    volume_metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Extract normalized taste features from confirmed ComicVine issue metadata.
    
    This function creates a stable feature-extraction layer for taste discovery
    using confirmed external metadata. It extracts normalized evidence for:
    - creators (preserving role when available)
    - characters
    - teams
    - publisher (requires volume_metadata)
    - publication era/date bucket
    
    Args:
        issue_metadata: Normalized issue metadata from ExternalIdentity.metadata_json.
                        Must be the result of comicvine_hydration.normalize_issue.
        volume_metadata: Optional normalized volume metadata from 
                        ExternalIdentity.metadata_json for the issue's volume.
                        Required for publisher extraction.
        
    Returns:
        Dictionary containing normalized taste features:
        {
            "creators": list of {"id": int, "name": str, "role": str|None},
            "characters": list of {"id": int, "name": str},
            "teams": list of {"id": int, "name": str},
            "publisher": dict{"id": int, "name": str} or None,
            "publication_era": str (year) or None
        }
        
    Note:
        - Uses stable external IDs (ComicVine IDs) for deduplication
        - Preserves creator roles where available
        - Deduplicates features to prevent double-counting
        - Returns None for missing/unconfirmed metadata (no fabrication)
        - Does not store whole ComicVine payloads
    """
    # Validate input
    if not isinstance(issue_metadata, dict):
        raise ValueError("issue_metadata must be a dictionary")
        
    # Extract features
    creators = _extract_creator_features(
        issue_metadata.get("creator_credits", [])
    )
    characters = _extract_reference_features(
        issue_metadata.get("characters", [])
    )
    teams = _extract_reference_features(
        issue_metadata.get("teams", [])
    )
    publisher = _extract_publisher_feature(volume_metadata)
    publication_era = _extract_publication_era(issue_metadata, volume_metadata)
    
    return {
        "creators": creators,
        "characters": characters,
        "teams": teams,
        "publisher": publisher,
        "publication_era": publication_era,
    }