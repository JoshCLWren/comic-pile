#!/usr/bin/env python3
"""Test script to verify error logging functionality."""

import asyncio
import subprocess
import time
import sys
from pathlib import Path


async def test_error_logging():
    """Test error logging with various error scenarios."""
    # Start the dev server
    print("Starting dev server...")
    server_process = subprocess.Popen(
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"],
        text=True,
        cwd=Path(__file__).parent,
    )

    try:
        # Wait for server to start
        time.sleep(3)

        import httpx

        async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
            print("\n=== Testing 404 Not Found ===")
            response = await client.get("/invalid-endpoint")
            print(f"Status: {response.status_code}")
            print(f"Response: {response.json()}")

            print("\n=== Testing 404 for non-existent thread ===")
            response = await client.get("/threads/99999")
            print(f"Status: {response.status_code}")
            print(f"Response: {response.json()}")

            print("\n=== Testing 422 Validation Error ===")
            response = await client.post("/threads/", json={"invalid": "data"})
            print(f"Status: {response.status_code}")
            print(f"Response: {response.json()}")

            print("\n=== Testing successful request (should not log error) ===")
            response = await client.get("/threads/")
            print(f"Status: {response.status_code}")
            print(f"Threads count: {len(response.json())}")

        print("\n=== Test completed successfully! ===")
        print("Check server logs above for error logging output.")

    finally:
        print("\nStopping dev server...")
        server_process.terminate()
        server_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(test_error_logging())
