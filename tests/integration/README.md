# Playwright Integration Tests

This directory contains integration tests using Playwright to test comic-pile application workflows.

## Tests Overview

- **Roll Workflow**: Page load, dice roll, and thread display
- **Rating Workflow**: Rating submission, display updates, validation
- **Queue Operations**: Page loading, thread display, reordering
- **Session Management**: Session display, persistence, health checks
- **Navigation**: Page loading, navigation speed
- **Roll Pool**: Thread display, loading performance
- **Error Handling**: Empty queue, input validation

## Performance Goals

- Roll operation: < 100ms
- Rate operation: < 100ms
- Thread creation: < 200ms
- Page load: < 500ms

## Running Tests

```bash
# Run integration tests
pytest tests/integration/ -m integration

# Run with Playwright plugin (requires compatible Python version)
pytest tests/integration/ -m integration --browser chromium --headed=false
```

## Known Issues

### Python 3.13 Compatibility

Playwright 1.57.0 has syntax errors when running on Python 3.13 due to incompatible syntax in the package:

```python
raise cast(BaseException, fut.exception() from e
```

This is a known issue with the Playwright package. As of now, Playwright does not have a version fully compatible with Python 3.13.

**Workarounds:**
1. Use Python 3.12 for running integration tests
2. Wait for Playwright to release a Python 3.13 compatible version
3. Run integration tests in CI with Python 3.12

The integration test suite is ready to run once Playwright releases a compatible version.

## CI Integration

Integration tests are configured in `.github/workflows/ci.yml` and will run automatically on pull requests once the Python compatibility issue is resolved.
