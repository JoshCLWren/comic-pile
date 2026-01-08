# Rate Limiting

This document describes the rate limiting implementation for the Comic Pile API.

## Overview

Rate limiting is implemented using [slowapi](https://github.com/laurentS/slowapi), a rate limiting extension for FastAPI based on Flask-Limiter. It prevents API abuse and ensures fair resource usage.

## Configuration

Rate limiting is configured in `app/middleware/rate_limit.py` and uses IP-based tracking by default.

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
```

## Rate Limits by Endpoint

### Task API

| Endpoint | Limit | Description |
|----------|-------|-------------|
| `GET /api/tasks/` | 200/minute | List all tasks |
| `POST /api/tasks/` | 60/minute | Create new task |
| `GET /api/tasks/ready` | 200/minute | Get ready tasks (high frequency for workers) |
| `GET /api/tasks/{task_id}` | 200/minute | Get task details |
| `PATCH /api/tasks/{task_id}` | 60/minute | Update task |

### Thread API

| Endpoint | Limit | Description |
|----------|-------|-------------|
| `GET /threads/` | 100/minute | List all threads |
| `POST /threads/` | 30/minute | Create new thread |
| `GET /threads/{thread_id}` | 200/minute | Get thread details |
| `PUT /threads/{thread_id}` | 30/minute | Update thread |
| `DELETE /threads/{thread_id}` | 10/minute | Delete thread |

### Roll API

| Endpoint | Limit | Description |
|----------|-------|-------------|
| `POST /roll/` | 30/minute | Roll dice (prevents spam) |
| `POST /roll/html` | 30/minute | Roll dice with HTML response |

### Rate API

| Endpoint | Limit | Description |
|----------|-------|-------------|
| `POST /rate/` | 60/minute | Rate a comic |

### Queue API

| Endpoint | Limit | Description |
|----------|-------|-------------|
| `PUT /queue/threads/{thread_id}/position/` | 30/minute | Move thread to position |
| `PUT /queue/threads/{thread_id}/front/` | 30/minute | Move thread to front |
| `PUT /queue/threads/{thread_id}/back/` | 30/minute | Move thread to back |

### Session API

| Endpoint | Limit | Description |
|----------|-------|-------------|
| `GET /sessions/current/` | 200/minute | Get current session (high frequency polling) |
| `POST /sessions/` | 30/minute | Create new session |

## Response Headers

When rate limiting is active, the following headers are included in API responses:

- `X-RateLimit-Limit`: The rate limit ceiling for the request
- `X-RateLimit-Remaining`: The number of requests remaining in the current rate limit window
- `X-RateLimit-Reset`: The UTC Unix timestamp when the rate limit window resets

Example:

```http
HTTP/1.1 200 OK
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 99
X-RateLimit-Reset: 1704100800
```

## Rate Limit Exceeded Response

When a rate limit is exceeded, the API returns a `429 Too Many Requests` status code:

```json
{
  "detail": "Rate limit exceeded: 100 per 1 minute"
}
```

## Implementation Details

### Applying Rate Limits

Rate limits are applied using the `@limiter.limit()` decorator on endpoint functions:

```python
from fastapi import Request
from app.middleware import limiter

@router.get("/threads/", response_model=list[ThreadResponse])
@limiter.limit("100/minute")
def list_threads(request: Request, db: Session = Depends(get_db)) -> list[ThreadResponse]:
    """List all threads ordered by position."""
    # ...
```

**Important**: When using the rate limiter decorator, the endpoint function must accept a `request: Request` parameter as the first argument (after `self` for class-based views).

### Rate Limit Syntax

Rate limits are specified using the format `"N/period"` where:
- `N` is the number of requests
- `period` is one of: `second`, `minute`, `hour`, `day`, `month`, `year`

Examples:
- `"100/minute"` - 100 requests per minute
- `"1000/hour"` - 1000 requests per hour
- `"10000/day"` - 10000 requests per day

### Rate Limit Storage

Rate limits are stored in-memory using the default slowapi storage backend. This means:
- Rate limits are per-server instance
- Rate limits reset on server restart
- For distributed deployments, consider using Redis or another distributed storage backend

## Testing

Rate limiting tests are in `tests/test_rate_limit.py` and verify:
- Rate limits are enforced correctly
- 429 responses are returned when limits are exceeded
- Rate limit headers are present
- Rate limits reset after the time window expires
- Rate limits are applied per IP address

Run tests with:

```bash
pytest tests/test_rate_limit.py -v
```

## Bypassing Rate Limits

Rate limits can be bypassed in development mode by setting the environment variable:

```bash
export RATE_LIMIT_ENABLED=false
```

This is useful for:
- Local development
- Load testing
- Automated testing at scale

## Best Practices

### For API Consumers

1. **Respect rate limit headers**: Check `X-RateLimit-Remaining` and pause before hitting the limit
2. **Implement exponential backoff**: If you receive a 429 response, wait and retry with increasing delays
3. **Use webhooks where available**: Instead of polling, use webhooks for real-time updates
4. **Cache responses**: Cache GET responses to reduce unnecessary API calls

### For API Developers

1. **Choose appropriate limits**: Balance between preventing abuse and allowing legitimate use
2. **Document limits clearly**: Include rate limit information in API documentation
3. **Monitor usage**: Track rate limit violations to identify abuse patterns
4. **Provide guidance**: Include helpful error messages with suggestions for rate-limited clients

## Troubleshooting

### Common Issues

**Issue**: Receiving 429 responses for legitimate traffic

**Solutions**:
- Increase the rate limit for that endpoint
- Implement caching for frequently accessed data
- Use batch operations instead of individual requests

**Issue**: Rate limits not working as expected

**Solutions**:
- Verify the `@limiter.limit()` decorator is applied correctly
- Check that `request: Request` parameter is present in the endpoint function
- Ensure the limiter is registered in `app/main.py`

**Issue**: Rate limits causing issues in tests

**Solutions**:
- Use `RATE_LIMIT_ENABLED=false` environment variable
- Mock the rate limiter in tests
- Use separate test endpoints without rate limits

## Future Enhancements

Potential improvements to the rate limiting system:

1. **Redis-backed storage**: For distributed rate limiting across multiple server instances
2. **API key-based limits**: Different limits for authenticated vs anonymous users
3. **Burst allowances**: Allow short bursts beyond the base rate limit
4. **Per-endpoint customization**: Fine-tuned limits based on endpoint complexity
5. **Rate limit dashboard**: Monitor rate limit usage across all endpoints
6. **Dynamic limits**: Adjust limits based on system load or user tier
