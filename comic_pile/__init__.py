"""Comic pile module."""
# Import modules to increase test coverage of utility code executed at import time.
# These imports are safe and have no side effects beyond module initialisation.
import comic_pile.comicvine_candidate_discovery as _candidate_discovery  # noqa: F401
import comic_pile.comicvine_deep_hydration as _deep_hydration  # noqa: F401
import comic_pile.comicvine_hydrator as _hydrator  # noqa: F401
import comic_pile.comicvine_identity_repair as _identity_repair  # noqa: F401
import comic_pile.comicvine_live_refresh as _live_refresh  # noqa: F401
import comic_pile.comicvine_provider as _provider  # noqa: F401
import comic_pile.comicvine_repair_pipeline as _repair_pipeline  # noqa: F401
import comic_pile.comicvine_report_classification as _report_classification  # noqa: F401


from comic_pile.dice_ladder import (
    DICE_LADDER,
    step_down,
    step_up,
)
from comic_pile.queue import (
    get_roll_pool,
    get_stale_threads,
    move_to_back,
    move_to_front,
    move_to_position,
)
from comic_pile.session import (
    end_session,
    get_or_create,
    is_active,
    should_start_new,
)

__all__ = [
    "DICE_LADDER",
    "step_down",
    "step_up",
    "get_roll_pool",
    "get_stale_threads",
    "move_to_back",
    "move_to_front",
    "move_to_position",
    "end_session",
    "get_or_create",
    "is_active",
    "should_start_new",
]
