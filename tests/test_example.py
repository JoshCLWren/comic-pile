"""Example tests demonstrating pytest patterns."""

from example_module.core import ExampleData, process_data


def test_process_data_basic():
    """Test basic data processing."""
    data = ExampleData(name="test", value=42)
    result = process_data(data)
    assert result == "Processed: test = 42"


def test_process_data_edge_cases():
    """Test edge cases."""
    data = ExampleData(name="", value=0)
    result = process_data(data)
    assert result == "Processed:  = 0"
