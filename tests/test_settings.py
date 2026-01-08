"""Settings API integration tests."""

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_get_settings(client, db):
    """Test GET /admin/settings returns settings with defaults."""
    response = await client.get("/admin/settings")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == 1
    assert data["session_gap_hours"] == 6
    assert data["start_die"] == 6
    assert data["rating_min"] == 0.5
    assert data["rating_max"] == 5.0
    assert data["rating_step"] == 0.5
    assert data["rating_threshold"] == 4.0
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_get_settings_returns_existing_settings(client, db):
    """Test GET /admin/settings returns existing settings."""
    from app.models import Settings

    settings = Settings(
        session_gap_hours=12,
        start_die=20,
        rating_min=1.0,
        rating_max=10.0,
        rating_step=0.25,
        rating_threshold=8.0,
    )
    db.add(settings)
    db.commit()
    db.refresh(settings)

    response = await client.get("/admin/settings")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == settings.id
    assert data["session_gap_hours"] == 12
    assert data["start_die"] == 20
    assert data["rating_min"] == 1.0
    assert data["rating_max"] == 10.0
    assert data["rating_step"] == 0.25
    assert data["rating_threshold"] == 8.0


@pytest.mark.asyncio
async def test_get_settings_form(client, db):
    """Test GET /admin/settings/form returns HTML form."""
    response = await client.get("/admin/settings/form")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"session_gap_hours" in response.content
    assert b"start_die" in response.content
    assert b"rating_min" in response.content
    assert b"rating_max" in response.content
    assert b"rating_step" in response.content
    assert b"rating_threshold" in response.content


@pytest.mark.asyncio
async def test_get_settings_form_with_existing_settings(client, db):
    """Test GET /admin/settings/form renders with existing settings."""
    from app.models import Settings

    settings = Settings(
        session_gap_hours=24,
        start_die=10,
        rating_min=0.5,
        rating_max=5.0,
        rating_step=0.5,
        rating_threshold=4.0,
    )
    db.add(settings)
    db.commit()
    db.refresh(settings)

    response = await client.get("/admin/settings/form")
    assert response.status_code == 200
    assert b"24" in response.content or b'value="24"' in response.content
    assert b"10" in response.content or b'value="10"' in response.content


@pytest.mark.asyncio
async def test_update_settings_all_fields(client, db):
    """Test PUT /admin/settings updates all settings fields."""
    update_data = {
        "session_gap_hours": 12,
        "start_die": 20,
        "rating_min": 1.0,
        "rating_max": 10.0,
        "rating_step": 0.25,
        "rating_threshold": 8.0,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    from app.models import Settings

    settings = db.execute(select(Settings)).scalar_one()
    assert settings.session_gap_hours == 12
    assert settings.start_die == 20
    assert settings.rating_min == 1.0
    assert settings.rating_max == 10.0
    assert settings.rating_step == 0.25
    assert settings.rating_threshold == 8.0


@pytest.mark.asyncio
async def test_update_settings_partial_fields(client, db):
    """Test PUT /admin/settings updates only provided fields."""
    from app.models import Settings

    settings = Settings()
    db.add(settings)
    db.commit()

    update_data = {
        "session_gap_hours": 24,
        "start_die": 8,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 200

    db.refresh(settings)
    assert settings.session_gap_hours == 24
    assert settings.start_die == 8
    assert settings.rating_min == 0.5
    assert settings.rating_max == 5.0
    assert settings.rating_step == 0.5
    assert settings.rating_threshold == 4.0


@pytest.mark.asyncio
async def test_update_settings_creates_if_not_exists(client, db):
    """Test PUT /admin/settings creates settings record if it doesn't exist."""
    from app.models import Settings

    existing = db.execute(select(Settings)).scalar_one_or_none()
    assert existing is None

    update_data = {
        "session_gap_hours": 6,
        "start_die": 6,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 200

    settings = db.execute(select(Settings)).scalar_one()
    assert settings.session_gap_hours == 6
    assert settings.start_die == 6


@pytest.mark.asyncio
async def test_update_settings_validation_session_gap_hours_too_low(client):
    """Test PUT /admin/settings validates session_gap_hours minimum."""
    update_data = {
        "session_gap_hours": 0,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_validation_session_gap_hours_too_high(client):
    """Test PUT /admin/settings validates session_gap_hours maximum."""
    update_data = {
        "session_gap_hours": 169,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_validation_start_die_too_low(client):
    """Test PUT /admin/settings validates start_die minimum."""
    update_data = {
        "start_die": 3,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_validation_start_die_too_high(client):
    """Test PUT /admin/settings validates start_die maximum."""
    update_data = {
        "start_die": 21,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_validation_rating_min_too_low(client):
    """Test PUT /admin/settings validates rating_min minimum."""
    update_data = {
        "rating_min": -0.1,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_validation_rating_min_too_high(client):
    """Test PUT /admin/settings validates rating_min maximum."""
    update_data = {
        "rating_min": 5.1,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_validation_rating_max_too_high(client):
    """Test PUT /admin/settings validates rating_max maximum."""
    update_data = {
        "rating_max": 10.1,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_validation_rating_step_too_low(client):
    """Test PUT /admin/settings validates rating_step minimum."""
    update_data = {
        "rating_step": 0.0,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_validation_rating_step_too_high(client):
    """Test PUT /admin/settings validates rating_step maximum."""
    update_data = {
        "rating_step": 1.1,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_validation_rating_threshold_too_high(client):
    """Test PUT /admin/settings validates rating_threshold maximum."""
    update_data = {
        "rating_threshold": 10.1,
    }

    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_valid_die_options(client, db):
    """Test PUT /admin/settings accepts all valid die options."""
    valid_dice = [4, 6, 8, 10, 12, 20]

    for die_value in valid_dice:
        update_data = {"start_die": die_value}

        response = await client.put("/admin/settings", json=update_data)
        assert response.status_code == 200

        from app.models import Settings

        settings = db.execute(select(Settings)).scalar_one()
        assert settings.start_die == die_value


@pytest.mark.asyncio
async def test_update_settings_updated_at_timestamp(client, db):
    """Test PUT /admin/settings updates updated_at timestamp."""
    from app.models import Settings

    settings = Settings()
    db.add(settings)
    db.commit()
    db.refresh(settings)

    original_updated_at = settings.updated_at

    import asyncio

    await asyncio.sleep(0.01)

    update_data = {"session_gap_hours": 24}
    response = await client.put("/admin/settings", json=update_data)
    assert response.status_code == 200

    db.refresh(settings)
    assert settings.updated_at > original_updated_at
