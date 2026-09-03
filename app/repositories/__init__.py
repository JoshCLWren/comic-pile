"""Repository layer: query construction and persistence for model families.

The house layering standard (see ``AGENTS.md``) gives this package exclusive
ownership of SQLAlchemy query construction and persistence:

- Routers (``app/api/``) validate input and call one service function.
- Services (``app/services/``) own business logic and orchestration.
- Repositories (this package) build queries, execute them, and return ORM
  models or plain tuples/dicts — never HTTP types or response schemas.

Existing routers are migrated into this package incrementally; the conformance
test ``tests/test_router_layering_conformance.py`` keeps router violations from
growing while each migration shrinks its recorded baseline.

"""

from . import continuity_repository
from . import dependency_repository
from . import issue_repository
from . import session_repository
from . import thread_repository
from . import taste_signals
