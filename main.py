"""Entrypoint demonstrating argparse and clean architecture."""

import argparse

from example_module.core import ExampleData, process_data


def main() -> None:
    """Run the example."""
    parser = argparse.ArgumentParser(description="Example CLI tool")
    parser.add_argument("name", help="Name to process")
    parser.add_argument("--value", type=int, default=0, help="Value to process")
    args = parser.parse_args()

    data = ExampleData(name=args.name, value=args.value)
    result = process_data(data)
    print(result)


if __name__ == "__main__":
    main()
