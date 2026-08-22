#!/usr/bin/env python3

"""Test script to verify Taste Bank API functionality."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
import taste_bank
from typing import Literal

# Define the Taste Bank signal schema
class TasteBankSignalRequest(BaseModel):
    signal_type: str = Field(..., description="Type of Taste Bank signal")
    verdict: Literal["confirmed", "sometimes", "rejected"] = Field(..., description="Verdict to set")
    evidence: str | None = Field(None, description="Optional evidence or affinity information")

class TasteBankSignalResponse(BaseModel):
    """Response containing the updated Taste Bank signal."""
    signal_type: str
    verdict: Literal["confirmed", "sometimes", "rejected"]
    evidence: str | None = None
    recorded_at: str

# Create a minimal FastAPI app for testing
app = FastAPI(title="Taste Bank Test API")

# Create a simple in-memory store for testing
taste_bank_signals = {}

def test_taste_bank_api():
    """Test the Taste Bank API endpoints."""
    client = TestClient(app)
    
    # Test getting Taste Bank signal (should return empty since none exists)
    response = client.get("/users/me/taste-bank/signals")
    print("GET /users/me/taste-bank/signals:")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    # Test updating Taste Bank signal
    payload = taste_bank.TasteBankSignalRequest(
        signal_type="recommendation",
        verdict="confirmed",
        evidence="test evidence"
    )
    
    response = client.patch("/users/me/taste-bank/signals", json=payload.dict())
    print("\nPATCH /users/me/taste-bank/signals:")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

def test_api():
    """Run the API tests."""
    test_taste_bank_api()

if __name__ == "__main__":
    test_taste_bank_api()