"""Repository layer for query construction and persistence by model family.

The house layering (router → service → repository, see ``docs/ARCHITECTURE.md``)
gives this package exclusive ownership of SQLAlchemy query construction and
persistence:

- Routers (``app/api/``) validate input and call one service function.
- Services (``app/services/``) own business logic and orchestration and own
  transaction boundaries (commit/rollback/retry) plus cache invalidation.
- Repositories (this package) build queries, execute them, and return ORM
  models or plain tuples/dicts — never HTTP types or response schemas.
"""
