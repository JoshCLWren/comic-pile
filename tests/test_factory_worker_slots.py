"""Worker identity is independent of live provider/model catalogs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
from factory_worker_slots import offer, resolve, slot_count, slots, sources, worker_id


def test_provider_additions_do_not_renumber_existing_sources() -> None:
    existing = sources()
    source = existing[0]
    first = worker_id(source, 0)
    assert first == worker_id(source, 0)
    assert first.isdecimal()
    assert int(first) > 1_000_000_000
    assert resolve(first, {"MAX_WORKERS_PER_TICK": "2"}).source == source


def test_slots_are_unique_and_model_agnostic() -> None:
    all_slots = slots({"MAX_WORKERS_PER_TICK": "3"})
    assert len(all_slots) == 3 * len(sources())
    assert len({item.worker for item in all_slots}) == len(all_slots)
    assert {item.source for item in all_slots} == set(sources())
    assert all("model" not in item.as_record() for item in all_slots)


def test_source_diverse_offer_and_rotation() -> None:
    env = {"MAX_WORKERS_PER_TICK": "2"}
    first, second = offer(0, env), offer(1, env)
    assert set(first) == set(second)
    assert first != second
    assert len({resolve(worker, env).source for worker in first[:len(sources())]}) == len(sources())


def test_invalid_slots_do_not_resolve() -> None:
    env = {"MAX_WORKERS_PER_TICK": "2"}
    with pytest.raises(ValueError):
        resolve("42", env)
    with pytest.raises(ValueError):
        worker_id("not-a-real-provider", 0)
    with pytest.raises(ValueError):
        slot_count({"MAX_WORKERS_PER_TICK": "0"})
    with pytest.raises(ValueError):
        slot_count({"FACTORY_SLOTS_PER_PROVIDER": "invalid"})
