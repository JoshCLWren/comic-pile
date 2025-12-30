"""Example module demonstrating Python best practices."""

from dataclasses import dataclass


@dataclass
class ExampleData:
    """Example dataclass with type hints."""

    name: str
    value: int


def process_data(data: ExampleData) -> str:
    """Process example data and return formatted string."""
    return f"Processed: {data.name} = {data.value}"
