"""Admin API routes."""

from fastapi import APIRouter

router = APIRouter()


@router.post("/import/csv")
async def import_csv():
    """Import threads from CSV."""
    return {"message": "CSV import endpoint - to be implemented"}


@router.get("/export/json")
async def export_json():
    """Export database as JSON."""
    return {"message": "JSON export endpoint - to be implemented"}


@router.get("/export/csv")
async def export_csv():
    """Export threads as CSV."""
    return {"message": "CSV export endpoint - to be implemented"}
