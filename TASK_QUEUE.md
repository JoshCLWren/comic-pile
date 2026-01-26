# Code Quality Fixes - Task Queue

## Status Key
- [ ] TODO
- [ ] IN_PROGRESS
- [x] COMPLETED

## File 1: test_reposition.py
- [x] COMPLETED Add return type annotation (-> None) and Google-style docstring to test_thread_reposition (lines 12-14)
- [x] COMPLETED Replace blanket Exception catch with specific DB exceptions (SQLAlchemyError, NoResultFound, IntegrityError) around DB operations (lines 75-80)

## File 2: tests_e2e/test_comprehensive_qol_demo.py
- [x] COMPLETED Replace ℹ️ with "i" in print messages (lines 256-289)
- [x] COMPLETED Add type annotations to test_comprehensive_qol_features_demo, mark unused variables with _ (lines 87-92)
- [x] COMPLETED Add type annotations to test_user_with_threads fixture (lines 9-69)
- [x] COMPLETED Add type annotations to login_with_test_user helper, remove default password, update docstring (lines 72-85)
- [x] COMPLETED Add type annotations to test_repositioning_via_api, mark user_id as _user_id (lines 545-550)
- [x] COMPLETED Replace broad Exception with specific Playwright exceptions (TimeoutError, Error) (lines 163-260)

## File 3: tests_e2e/test_thread_repositioning_demo.py
- [x] COMPLETED Add type annotations to test_thread_repositioning_fix_demo, mark user_id as _user_id (lines 101-106)
- [x] COMPLETED Add type annotations to test_thread_repositioning_edge_cases, mark user_id as _user_id (lines 290-295)
- [x] COMPLETED Add type annotations to test_user_with_spider_man fixture (lines 9-83)
- [x] COMPLETED Add type annotations to login_with_test_user helper (lines 86-99)

## File 4: workflow_test.py
- [x] COMPLETED Add return type annotation and Args/Returns docstring sections to simulate_complete_workflow (lines 16-18)
- [x] COMPLETED Replace bare Exception handlers with specific exception types (ValueError, TimeoutError, MotionError, DatabaseError, etc.) (lines 107-118)

## File 5: tests/test_queue_edge_cases.py
- [x] COMPLETED Remove unused sample_data parameter from test_move_to_position_thread_not_in_active_list (lines 183-184)

## File 6: tests/test_session.py
- [x] COMPLETED Update mock_commit to use underscored parameter names (*_args, **_kwargs) (line 1216)

## Overall Status: ALL TASKS COMPLETED ✅
