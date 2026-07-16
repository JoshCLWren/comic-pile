"""Bug report request/response schemas."""

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticScreen(BaseModel):
    """Screen diagnostic information."""

    model_config = ConfigDict(populate_by_name=True)

    width: int
    height: int
    pixel_ratio: float = Field(alias="pixelRatio")


class DiagnosticViewport(BaseModel):
    """Viewport diagnostic information."""

    width: int
    height: int


class DiagnosticScroll(BaseModel):
    """Scroll position diagnostic information."""

    x: int
    y: int


class DiagnosticPerformance(BaseModel):
    """Performance timing diagnostic information."""

    model_config = ConfigDict(populate_by_name=True)

    dom_content_loaded: float | None = Field(default=None, alias="domContentLoaded")
    load_complete: float | None = Field(default=None, alias="loadComplete")


class DiagnosticError(BaseModel):
    """A captured console error entry."""

    message: str
    timestamp: str


class BugReportDiagnostics(BaseModel):
    """Structured diagnostics collected from the browser."""

    model_config = ConfigDict(populate_by_name=True)

    timestamp: str
    url: str
    user_agent: str = Field(alias="userAgent")
    screen: DiagnosticScreen
    viewport: DiagnosticViewport
    scroll: DiagnosticScroll
    performance: DiagnosticPerformance
    errors: list[DiagnosticError]


class BugReportCreate(BaseModel):
    """Request schema for creating a bug report."""

    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=2000)
    diagnostics: BugReportDiagnostics | None = None


class BugReportResponse(BaseModel):
    """Response after successfully creating a bug report issue."""

    issue_url: str
