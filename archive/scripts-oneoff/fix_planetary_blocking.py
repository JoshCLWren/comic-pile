#!/usr/bin/env python3
"""Create Stormwatch Vol. 2 #11 → Planetary #10 dependency."""

import requests

TOKEN = requests.post(
    "https://app-production-72b9.up.railway.app/api/auth/login",
    json={"username": "Josh_Digital_Comics", "password": "Emily4412"},
).json()["access_token"]

# Get issue IDs
sw2_issues = requests.get(
    "https://app-production-72b9.up.railway.app/api/v1/threads/368/issues",
    headers={"Authorization": f"Bearer {TOKEN}"},
).json()["issues"]

planetary_issues = requests.get(
    "https://app-production-72b9.up.railway.app/api/v1/threads/250/issues",
    headers={"Authorization": f"Bearer {TOKEN}"},
).json()["issues"]

sw2_11_id = next(i["id"] for i in sw2_issues if i["issue_number"] == "11")
planetary_10_id = next(i["id"] for i in planetary_issues if i["issue_number"] == "10")

print(
    f"Creating dependency: Stormwatch Vol. 2 #11 ({sw2_11_id}) → Planetary #10 ({planetary_10_id})"
)

# Create dependency
response = requests.post(
    "https://app-production-72b9.up.railway.app/api/v1/dependencies/",
    headers={"Authorization": f"Bearer {TOKEN}"},
    json={
        "source_type": "issue",
        "source_id": sw2_11_id,
        "target_type": "issue",
        "target_id": planetary_10_id,
    },
)

print(f"Response: {response.status_code}")
print(response.json())

# Verify blocking info
blocking = requests.post(
    "https://app-production-72b9.up.railway.app/api/v1/threads/250:getBlockingInfo",
    headers={"Authorization": f"Bearer {TOKEN}"},
).json()

print(f"\nPlanetary is_blocked: {blocking.get('is_blocked')}")
print(f"Blocking reasons: {blocking.get('blocking_reasons')}")
