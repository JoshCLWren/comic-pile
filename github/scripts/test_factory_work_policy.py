# Functionality Documentation
#
# Parameters
- labels(*names: str) -> list[dict[str, str]]: Convert names to label objects
- factory_pr(number: int, ...) -> dict: Create PR with status
- issue(number: int, ...) -> dict: Create issue with labels
- build_candidates(...) -> list[Candidate]: Sort candidates
- CompletionFirstOrderingTests: PR ordering tests
- WipCapTests: WIP capacity constraints

Classes:
- CompletionFirstOrderingTests: Test PR ordering logic
- WipCapTests: Test WIP capacity constraints