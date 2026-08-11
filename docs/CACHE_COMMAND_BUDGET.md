# Cache command budget

Updated: 2026-08-11

ComicPile treats Redis as an optional performance layer, not a correctness dependency. The command budget below exists to keep cache usage measurable and comfortably inside the configured Upstash free-tier allowance while preserving enough headroom for retries, diagnostics, console traffic, and future growth.

## Provider accounting assumptions

The configured production provider is Upstash Redis. As of 2026-08-11, Upstash documents a Free plan allowance of **500,000 commands per month** and prices usage by command. Operational commands such as `PING`, `AUTH`, `HELLO`, `SELECT`, `COMMAND`, `CONFIG`, `INFO`, `RESET`, and `QUIT` are not billed. See:

- https://upstash.com/pricing/redis
- https://upstash.com/docs/redis/features/restapi

Upstash REST pipelining combines multiple Redis commands into one HTTP request, but each logical Redis command remains a command for budgeting purposes. Pipeline batching therefore reduces network round trips, not this command envelope. Native multi-key commands such as `MGET` and `MSET` are each documented as one Redis command regardless of key count, so budget accounting follows the logical command issued rather than the number of keys inside it. A multi-key `DEL` is likewise one Redis command.

The application-side metrics intentionally count only aggregate command families. They never accept or retain cache keys, user IDs, values, tokens, or provider credentials. Provider console activity can add commands that the application cannot observe, so the application budget deliberately leaves substantial headroom.

## Monthly budget

| Item | Commands/month |
| --- | ---: |
| Upstash Free allowance | 500,000 |
| ComicPile application budget | **350,000** |
| Reserved headroom | **150,000 (30%)** |

The 350,000-command application ceiling is intentionally conservative. Reaching it should trigger investigation before the provider limit becomes a user-facing cache outage. The remaining 150,000 commands absorb provider-console activity, retries, unusual burst traffic, and measurement differences.

## Representative flow ceilings

These are cold-cache upper bounds for the production generation-cache command composition. Warm reads are cheaper.

| Flow | Ceiling | Command model |
| --- | ---: | --- |
| Roll bootstrap | 4 | two generation-scoped reads, each at most `EVAL + SET` |
| Queue load | 2 | one generation-scoped read, at most `EVAL + SET` |
| Roll | 5 | two cold generation-scoped reads plus one `INCR` invalidation |
| Snooze | 1 | one user-generation `INCR` invalidation |
| Rating | 1 | one deduplicated user-generation `INCR` invalidation |
| Thread mutation | 1 | one user-generation `INCR` invalidation |
| Issue mutation | 1 | one user-generation `INCR` invalidation |
| Continuity mutation | 1 | one user-generation `INCR` invalidation |

The source-of-truth ceilings live in `app/cache_metrics.py` and are exercised by `tests/test_cache_command_budget.py`. If a flow legitimately needs more cache commands, update the implementation, ceiling test, and this document together so budget growth is explicit rather than accidental.
