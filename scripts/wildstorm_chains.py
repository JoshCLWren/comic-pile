"""Shared YAML loading utilities for Wildstorm reading order scripts.

Provides a single source of truth for loading chain specifications from
scripts/wildstorm_reading_order.yaml.
"""

from pathlib import Path

import yaml

YAML_PATH = Path(__file__).parent / "wildstorm_reading_order.yaml"


def load_chains() -> dict[str, list[tuple[str, str]]]:
    """Load reading order chains from the YAML spec file.

    Returns:
        Dictionary mapping chain names to lists of (title, issue_number) tuples.

    Raises:
        FileNotFoundError: If the YAML spec file does not exist.
        ValueError: If any chain has fewer than 2 edges (cannot form dependencies).
    """
    if not YAML_PATH.exists():
        raise FileNotFoundError(f"YAML spec not found: {YAML_PATH}")

    with YAML_PATH.open("r") as f:
        data = yaml.safe_load(f)

    chains: dict[str, list[tuple[str, str]]] = {}
    for chain_def in data["chains"]:
        name = chain_def["name"]
        edges = [(edge[0], edge[1]) for edge in chain_def["edges"]]
        if len(edges) < 2:
            raise ValueError(f"Chain '{name}' must have at least 2 edges, got {len(edges)}")
        chains[name] = edges

    return chains


def load_chains_as_list() -> list[list[tuple[str, str]]]:
    """Load reading order chains as an ordered list.

    Returns:
        List of chains in YAML definition order, each a list of
        (title, issue_number) tuples.
    """
    return list(load_chains().values())
