"""Regression coverage for dispatcher-only mutation authorization (#2859)."""
from __future__ import annotations
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Controller must be importable from its hyphenated script path
import importlib.util
_spec = importlib.util.spec_from_file_location('factory_work_controller', '.github/scripts/factory-work-controller.py')
fc = importlib.util.module_from_spec(_spec)
# Dependent policy modules must be on path for controller init
sys.path.insert(0, '.github/scripts')
_spec.loader.exec_module(fc)


class DispatcherAuthorizationTests(unittest.TestCase):
    """Authorized dispatcher, unauthorized workflow, spoofed display name, missing identity."""

    def test_authorized_dispatcher_path(self) -> None:
        """Canonical dispatcher file path passes."""
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '12345'}, clear=False):
            with patch.object(fc, 'gh_json', return_value={'path': '.github/workflows/fixed-model-factory-dispatch.yml'}):
                self.assertTrue(fc.dispatcher_identity_verified())

    def test_unauthorized_workflow_path(self) -> None:
        """Non-dispatcher workflow file fails closed."""
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '99999'}, clear=False):
            with patch.object(fc, 'gh_json', return_value={'path': '.github/workflows/free-model-factory-entry.yml'}):
                self.assertFalse(fc.dispatcher_identity_verified())

    def test_spoofed_display_name_still_denied(self) -> None:
        """Matching display name without correct file path must not spoof."""
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '11111'}, clear=False):
            with patch.object(fc, 'gh_json', return_value={'name': 'Fixed Model Factory Dispatcher', 'path': '.github/workflows/free-model-factory-entry.yml'}):
                self.assertFalse(fc.dispatcher_identity_verified())

    def test_missing_workflow_identity_denied(self) -> None:
        """Missing or ambiguous run identity fails closed."""
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': ''}, clear=False):
            self.assertFalse(fc.dispatcher_identity_verified())

    def test_local_invocation_allowed(self) -> None:
        """Outside Actions invocation remains possible."""
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}, clear=True):
            self.assertTrue(fc.dispatcher_identity_verified())

    def test_assign_candidate_denied_for_unauthorized(self) -> None:
        """Mutation boundary denies assignment when identity missing."""
        from factory_work_policy import Candidate
        cand = Candidate(number=1, kind='issue', lane=1, priority=1, created_at='2026-01-01T00:00:00Z', conflicted=False)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '99999'}, clear=False):
            with patch.object(fc, 'gh_json', return_value={'path': '.github/workflows/free-model-factory-entry.yml'}):
                # Should return False without attempting mutation
                result = fc.assign_candidate(cand, '53')
                self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
