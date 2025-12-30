"""CSV import/export tests."""

import io

import pytest


@pytest.mark.asyncio
async def test_import_valid_csv(client, db):
    """Test POST /admin/import/csv/ succeeds with valid data."""
    csv_content = """title,format,issues_remaining
Superman,Comic,10
Batman,Comic,5
Wonder Woman,Trade Paperback,3"""
    csv_file = io.BytesIO(csv_content.encode())
    files = {"file": ("test.csv", csv_file, "text/csv")}

    response = await client.post("/admin/import/csv/", files=files)
    assert response.status_code == 200

    data = response.json()
    assert data["imported"] == 3
    assert len(data["errors"]) == 0

    from sqlalchemy import select

    from app.models import Thread

    threads = db.execute(select(Thread).order_by(Thread.queue_position)).scalars().all()
    assert len(threads) == 3

    assert threads[0].title == "Wonder Woman"
    assert threads[0].queue_position == 1
    assert threads[0].issues_remaining == 3

    assert threads[1].title == "Batman"
    assert threads[1].queue_position == 2
    assert threads[1].issues_remaining == 5

    assert threads[2].title == "Superman"
    assert threads[2].queue_position == 3
    assert threads[2].issues_remaining == 10


@pytest.mark.asyncio
async def test_import_invalid_format_missing_columns(client):
    """Test POST /admin/import/csv/ returns error for missing required columns."""
    csv_content = """title,format
Superman,Comic
Batman,Trade"""
    csv_file = io.BytesIO(csv_content.encode())
    files = {"file": ("test.csv", csv_file, "text/csv")}

    response = await client.post("/admin/import/csv/", files=files)
    assert response.status_code == 200

    data = response.json()
    assert data["imported"] == 0
    assert len(data["errors"]) == 2
    assert "Missing issues_remaining" in data["errors"][0]


@pytest.mark.asyncio
async def test_import_invalid_format_missing_title(client):
    """Test POST /admin/import/csv/ returns error for missing title."""
    csv_content = """title,format,issues_remaining
,Comic,10
Batman,Comic,5"""
    csv_file = io.BytesIO(csv_content.encode())
    files = {"file": ("test.csv", csv_file, "text/csv")}

    response = await client.post("/admin/import/csv/", files=files)
    assert response.status_code == 200

    data = response.json()
    assert data["imported"] == 1
    assert len(data["errors"]) == 1
    assert "Missing title" in data["errors"][0]


@pytest.mark.asyncio
async def test_import_invalid_format_missing_format(client):
    """Test POST /admin/import/csv/ returns error for missing format."""
    csv_content = """title,format,issues_remaining
Superman,,10
Batman,Comic,5"""
    csv_file = io.BytesIO(csv_content.encode())
    files = {"file": ("test.csv", csv_file, "text/csv")}

    response = await client.post("/admin/import/csv/", files=files)
    assert response.status_code == 200

    data = response.json()
    assert data["imported"] == 1
    assert len(data["errors"]) == 1
    assert "Missing format" in data["errors"][0]


@pytest.mark.asyncio
async def test_import_invalid_data_not_a_number(client):
    """Test POST /admin/import/csv/ returns error for non-integer issues_remaining."""
    csv_content = """title,format,issues_remaining
Superman,Comic,ten
Batman,Comic,5"""
    csv_file = io.BytesIO(csv_content.encode())
    files = {"file": ("test.csv", csv_file, "text/csv")}

    response = await client.post("/admin/import/csv/", files=files)
    assert response.status_code == 200

    data = response.json()
    assert data["imported"] == 1
    assert len(data["errors"]) == 1
    assert "must be an integer" in data["errors"][0]


@pytest.mark.asyncio
async def test_import_invalid_data_negative_issues(client):
    """Test POST /admin/import/csv/ returns error for negative issues_remaining."""
    csv_content = """title,format,issues_remaining
Superman,Comic,-5
Batman,Comic,5"""
    csv_file = io.BytesIO(csv_content.encode())
    files = {"file": ("test.csv", csv_file, "text/csv")}

    response = await client.post("/admin/import/csv/", files=files)
    assert response.status_code == 200

    data = response.json()
    assert data["imported"] == 1
    assert len(data["errors"]) == 1
    assert "must be >= 0" in data["errors"][0]


@pytest.mark.asyncio
async def test_import_zero_issues_remaining(client, db):
    """Test POST /admin/import/csv/ allows zero issues_remaining."""
    csv_content = """title,format,issues_remaining
Superman,Comic,0"""
    csv_file = io.BytesIO(csv_content.encode())
    files = {"file": ("test.csv", csv_file, "text/csv")}

    response = await client.post("/admin/import/csv/", files=files)
    assert response.status_code == 200

    data = response.json()
    assert data["imported"] == 1
    assert len(data["errors"]) == 0

    from sqlalchemy import select

    from app.models import Thread

    thread = db.execute(select(Thread).where(Thread.title == "Superman")).scalar_one()
    assert thread.issues_remaining == 0
    assert thread.status == "active"


@pytest.mark.asyncio
async def test_import_empty_file(client):
    """Test POST /admin/import/csv/ handles empty CSV gracefully."""
    csv_content = """title,format,issues_remaining"""
    csv_file = io.BytesIO(csv_content.encode())
    files = {"file": ("test.csv", csv_file, "text/csv")}

    response = await client.post("/admin/import/csv/", files=files)
    assert response.status_code == 200

    data = response.json()
    assert data["imported"] == 0
    assert len(data["errors"]) == 0


@pytest.mark.asyncio
async def test_import_non_csv_file(client):
    """Test POST /admin/import/csv/ returns error for non-CSV file."""
    txt_content = "This is not a CSV file"
    txt_file = io.BytesIO(txt_content.encode())
    files = {"file": ("test.txt", txt_file, "text/plain")}

    response = await client.post("/admin/import/csv/", files=files)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_export_csv(client, sample_data):
    """Test GET /admin/export/csv/ returns valid CSV."""
    response = await client.get("/admin/export/csv/")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"

    content = response.text
    lines = content.strip().split("\n")

    assert lines[0] == "title,format,issues_remaining"
    assert "Superman" in content
    assert "Batman" in content
    assert "Comic" in content


@pytest.mark.asyncio
async def test_export_csv_only_active(client, sample_data):
    """Test GET /admin/export/csv/ only exports active threads."""
    response = await client.get("/admin/export/csv/")
    assert response.status_code == 200

    content = response.text
    assert "Superman" in content
    assert "Batman" in content
    assert "Flash" in content
    assert "Aquaman" in content
    assert "Wonder Woman" not in content


@pytest.mark.asyncio
async def test_export_csv_empty(client):
    """Test GET /admin/export/csv/ returns empty CSV when no threads."""
    response = await client.get("/admin/export/csv/")
    assert response.status_code == 200

    content = response.text
    lines = content.strip().split("\n")
    assert len(lines) == 1
    assert lines[0] == "title,format,issues_remaining"


@pytest.mark.asyncio
async def test_export_json(client, sample_data):
    """Test GET /admin/export/json/ returns all data."""
    response = await client.get("/admin/export/json/")
    assert response.status_code == 200

    data = response.json()
    assert "users" in data
    assert "threads" in data
    assert "sessions" in data
    assert "events" in data

    assert len(data["users"]) == 1
    assert len(data["threads"]) == 5
    assert len(data["sessions"]) == 2
    assert len(data["events"]) == 2

    assert data["users"][0]["username"] == "test_user"
    assert data["threads"][0]["title"] == "Superman"
    assert data["sessions"][0]["start_die"] == 6
    assert data["events"][0]["type"] == "roll"


@pytest.mark.asyncio
async def test_export_json_includes_completed(client, sample_data):
    """Test GET /admin/export/json/ includes completed threads."""
    response = await client.get("/admin/export/json/")
    assert response.status_code == 200

    data = response.json()
    thread_titles = [t["title"] for t in data["threads"]]
    assert "Wonder Woman" in thread_titles


@pytest.mark.asyncio
async def test_import_then_export_roundtrip(client, db):
    """Test import then export returns equivalent data."""
    csv_content = """title,format,issues_remaining
Superman,Comic,10
Batman,Comic,5
Wonder Woman,Trade Paperback,3"""
    csv_file = io.BytesIO(csv_content.encode())
    files = {"file": ("test.csv", csv_file, "text/csv")}

    import_response = await client.post("/admin/import/csv/", files=files)
    assert import_response.status_code == 200

    export_response = await client.get("/admin/export/csv/")
    assert export_response.status_code == 200

    exported_content = export_response.text
    lines = exported_content.strip().split("\n")

    assert len(lines) == 4
    assert lines[0] == "title,format,issues_remaining"

    exported_threads = {}
    for line in lines[1:]:
        parts = line.split(",")
        exported_threads[parts[0]] = {
            "format": parts[1],
            "issues_remaining": int(parts[2]),
        }

    assert "Superman" in exported_threads
    assert "Batman" in exported_threads
    assert "Wonder Woman" in exported_threads
