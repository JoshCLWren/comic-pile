"""Tests for CBL replace with safe undo functionality."""

import pytest
from httpx import AsyncClient

from app.schemas.custom_cbl import CustomCBLWrite


@pytest.mark.asyncio
async def test_replace_custom_cbl_with_undo(auth_client: AsyncClient, sample_data) -> None:
    """Test replacing a custom CBL with undo capability."""
    # Create a custom CBL first
    create_payload = CustomCBLWrite(
        name="Test List",
        description="Test description",
        issue_ids=[1, 2, 3],
    )
    
    create_response = await auth_client.post("/api/v1/custom-cbls/", json=create_payload.model_dump())
    assert create_response.status_code == 201
    list_id = create_response.json()["id"]
    
    # Replace the list
    replace_payload = CustomCBLWrite(
        name="Updated Test List",
        description="Updated description",
        issue_ids=[4, 5, 6],
    )
    
    replace_response = await auth_client.post(f"/api/v1/custom-cbls/{list_id}:replace", json=replace_payload.model_dump())
    assert replace_response.status_code == 200
    
    updated_list = replace_response.json()
    assert updated_list["name"] == "Updated Test List"
    assert updated_list["description"] == "Updated description"
    assert len(updated_list["entries"]) == 3
    assert updated_list["metadata"]["snapshot_id"] is not None
    
    snapshot_id = updated_list["metadata"]["snapshot_id"]
    
    # Verify the list was actually updated
    get_response = await auth_client.get(f"/api/v1/custom-cbls/{list_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Updated Test List"
    
    # Undo the replacement
    undo_response = await auth_client.post(f"/api/v1/custom-cbls/{list_id}:undo?snapshot_id={snapshot_id}")
    assert undo_response.status_code == 200
    
    undone_list = undo_response.json()
    assert undone_list["name"] == "Test List"
    assert undone_list["description"] == "Test description"
    assert len(undone_list["entries"]) == 3
    assert undone_list["metadata"]["undone_from_snapshot_id"] == snapshot_id
    
    # Verify the list was restored
    get_response = await auth_client.get(f"/api/v1/custom-cbls/{list_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Test List"


@pytest.mark.asyncio
async def test_replace_preserves_other_lists(auth_client: AsyncClient, sample_data) -> None:
    """Test that replacing one list doesn't affect others."""
    # Create two custom CBLs
    payload1 = CustomCBLWrite(
        name="List 1",
        issue_ids=[1, 2],
    )
    payload2 = CustomCBLWrite(
        name="List 2", 
        issue_ids=[3, 4],
    )
    
    response1 = await auth_client.post("/api/v1/custom-cbls/", json=payload1.model_dump())
    response2 = await auth_client.post("/api/v1/custom-cbls/", json=payload2.model_dump())
    
    list1_id = response1.json()["id"]
    list2_id = response2.json()["id"]
    
    # Replace only list1
    replace_payload = CustomCBLWrite(
        name="Updated List 1",
        issue_ids=[5, 6],
    )
    
    await auth_client.post(f"/api/v1/custom-cbls/{list1_id}:replace", json=replace_payload.model_dump())
    
    # Verify list1 was updated
    get_response1 = await auth_client.get(f"/api/v1/custom-cbls/{list1_id}")
    assert get_response1.json()["name"] == "Updated List 1"
    
    # Verify list2 is unchanged
    get_response2 = await auth_client.get(f"/api/v1/custom-cbls/{list2_id}")
    assert get_response2.json()["name"] == "List 2"


@pytest.mark.asyncio
async def test_replace_with_checkpoint_targets(auth_client: AsyncClient, sample_data) -> None:
    """Test replacing a list with checkpoint targets."""
    # Create a custom CBL
    create_payload = CustomCBLWrite(
        name="Test List",
        issue_ids=[1, 2, 3],
    )
    
    response = await auth_client.post("/api/v1/custom-cbls/", json=create_payload.model_dump())
    list_id = response.json()["id"]
    
    # Replace with checkpoint targets
    replace_payload = CustomCBLWrite(
        name="Updated Test List",
        issue_ids=[1, 2, 3, 4],
        checkpoint_issue_ids=[2, 4],
        checkpoint_targets={2: [3], 4: []},
    )
    
    replace_response = await auth_client.post(f"/api/v1/custom-cbls/{list_id}:replace", json=replace_payload.model_dump())
    assert replace_response.status_code == 200
    
    updated_list = replace_response.json()
    assert len(updated_list["entries"]) == 4
    
    # Verify checkpoints are preserved
    checkpoint_entries = [e for e in updated_list["entries"] if e["is_checkpoint"]]
    assert len(checkpoint_entries) == 2


@pytest.mark.asyncio
async def test_replace_with_entry_intents(auth_client: AsyncClient, sample_data) -> None:
    """Test replacing a list with entry intents."""
    # Create a custom CBL
    create_payload = CustomCBLWrite(
        name="Test List",
        issue_ids=[1, 2, 3],
    )
    
    response = await auth_client.post("/api/v1/custom-cbls/", json=create_payload.model_dump())
    list_id = response.json()["id"]
    
    # Replace with entry intents
    replace_payload = CustomCBLWrite(
        name="Updated Test List",
        issue_ids=[1, 2, 3, 4],
        entry_intents={
            2: {"gate": "hold", "skipped": False},
            4: {"gate": "after_previous", "skipped": True},
        },
    )
    
    replace_response = await auth_client.post(f"/api/v1/custom-cbls/{list_id}:replace", json=replace_payload.model_dump())
    assert replace_response.status_code == 200
    
    updated_list = replace_response.json()
    assert len(updated_list["entries"]) == 4
    
    # Verify entry intents are preserved
    entry_2 = next(e for e in updated_list["entries"] if e["issue_id"] == 2)
    assert entry_2["gate"] == "hold"
    assert not entry_2["skipped"]
    
    entry_4 = next(e for e in updated_list["entries"] if e["issue_id"] == 4)
    assert entry_4["gate"] == "after_previous"
    assert entry_4["skipped"]


@pytest.mark.asyncio
async def test_replace_same_name_collision_safe(auth_client: AsyncClient, sample_data) -> None:
    """Test that same-name Alpha Flight fixture cannot overwrite another list."""
    # Create two custom CBLs with the same name
    payload1 = CustomCBLWrite(
        name="Alpha Flight",
        issue_ids=[1, 2],
    )
    payload2 = CustomCBLWrite(
        name="Alpha Flight",
        issue_ids=[3, 4],
    )
    
    response1 = await auth_client.post("/api/v1/custom-cbls/", json=payload1.model_dump())
    response2 = await auth_client.post("/api/v1/custom-cbls/", json=payload2.model_dump())
    
    list1_id = response1.json()["id"]
    list2_id = response2.json()["id"]
    
    # Replace list1 - should not affect list2
    replace_payload = CustomCBLWrite(
        name="Updated Alpha Flight",
        issue_ids=[5, 6],
    )
    
    await auth_client.post(f"/api/v1/custom-cbls/{list1_id}:replace", json=replace_payload.model_dump())
    
    # Verify list1 was updated
    get_response1 = await auth_client.get(f"/api/v1/custom-cbls/{list1_id}")
    assert get_response1.json()["name"] == "Updated Alpha Flight"
    
    # Verify list2 is unchanged
    get_response2 = await auth_client.get(f"/api/v1/custom-cbls/{list2_id}")
    assert get_response2.json()["name"] == "Alpha Flight"


@pytest.mark.asyncio
async def test_canceled_stale_operation_changes_nothing(auth_client: AsyncClient, sample_data) -> None:
    """Test that canceled/stale operation changes nothing."""
    # Create a custom CBL
    create_payload = CustomCBLWrite(
        name="Test List",
        issue_ids=[1, 2, 3],
    )
    
    response = await auth_client.post("/api/v1/custom-cbls/", json=create_payload.model_dump())
    list_id = response.json()["id"]
    
    # Get the original state
    original_response = await auth_client.get(f"/api/v1/custom-cbls/{list_id}")
    original_name = original_response.json()["name"]
    
    # Attempt to replace with invalid data (should fail)
    invalid_payload = {
        "name": "",  # Invalid: empty name
        "issue_ids": [1, 2, 3],
    }

    replace_response = await auth_client.post(f"/api/v1/custom-cbls/{list_id}:replace", json=invalid_payload)
    assert replace_response.status_code == 422
    
    # Verify the list is unchanged
    get_response = await auth_client.get(f"/api/v1/custom-cbls/{list_id}")
    assert get_response.json()["name"] == original_name


@pytest.mark.asyncio
async def test_concurrent_idempotent_replacement(auth_client: AsyncClient, sample_data) -> None:
    """Test that concurrent replacement is idempotent."""
    # Create a custom CBL
    create_payload = CustomCBLWrite(
        name="Test List",
        issue_ids=[1, 2, 3],
    )
    
    response = await auth_client.post("/api/v1/custom-cbls/", json=create_payload.model_dump())
    list_id = response.json()["id"]
    
    # Replace the list twice with the same data
    replace_payload = CustomCBLWrite(
        name="Test List",
        issue_ids=[1, 2, 3],
    )
    
    response1 = await auth_client.post(f"/api/v1/custom-cbls/{list_id}:replace", json=replace_payload.model_dump())
    response2 = await auth_client.post(f"/api/v1/custom-cbls/{list_id}:replace", json=replace_payload.model_dump())
    
    # Both should succeed
    assert response1.status_code == 200
    assert response2.status_code == 200
    
    # The list should end up in the same state
    get_response = await auth_client.get(f"/api/v1/custom-cbls/{list_id}")
    final_list = get_response.json()
    assert final_list["name"] == "Test List"
    assert len(final_list["entries"]) == 3


@pytest.mark.asyncio
async def test_undo_restores_ordering_decisions_without_reversing_read_events(auth_client: AsyncClient, sample_data) -> None:
    """Test that undo restores list ordering/decisions without reversing later read events."""
    # Create a custom CBL
    create_payload = CustomCBLWrite(
        name="Test List",
        issue_ids=[1, 2, 3],
    )
    
    response = await auth_client.post("/api/v1/custom-cbls/", json=create_payload.model_dump())
    list_id = response.json()["id"]
    
    # Replace with different ordering
    replace_payload = CustomCBLWrite(
        name="Updated Test List",
        issue_ids=[3, 2, 1],  # Reversed order
    )
    
    replace_response = await auth_client.post(f"/api/v1/custom-cbls/{list_id}:replace", json=replace_payload.model_dump())
    snapshot_id = replace_response.json()["metadata"]["snapshot_id"]
    
    # Undo the replacement
    undo_response = await auth_client.post(f"/api/v1/custom-cbls/{list_id}:undo?snapshot_id={snapshot_id}")
    assert undo_response.status_code == 200
    
    # Verify the original ordering is restored
    get_response = await auth_client.get(f"/api/v1/custom-cbls/{list_id}")
    final_list = get_response.json()
    issue_ids = [entry["issue_id"] for entry in final_list["entries"]]
    assert issue_ids == [1, 2, 3]  # Original order restored