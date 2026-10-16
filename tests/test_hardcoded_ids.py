"""Guard against hardcoded test IDs and user_id=1 coupling."""

import ast
from pathlib import Path

# Baseline of known hardcoded IDs that are allowed to exist
# This should only shrink over time, never grow
KNOWN_HARDCODED_IDS = {
    # These are legitimate uses that should remain
    "tests/conftest.py": {
        "_sync_id_sequence",  # Function name is OK
        "user_id=user.id",   # Using dynamic user ID is OK
    },
    "app/services/admin_service.py": {
        "user_id=user_id",    # Using parameter is OK
    },
    # Other test files that have hardcoded IDs but are not part of this issue
    "tests/test_thread_api.py": {"User(id=999)"},
    "tests/test_queue_api.py": {"User(id=123)"},
    "tests/test_tags.py": {"User(id=2)", "User(id=3)"},
    "tests/test_legacy_reading_order_production_migration.py": {"User(id=1)"},
    "tests/test_tag_inheritance.py": {"User(id=2)", "User(id=3)", "User(id=4)"},
    "tests/test_session_bandwidth_inference.py": {"User(id=1)", "User(id=2)", "User(id=3)", "User(id=4)", "User(id=5)", "User(id=6)"},
    "tests/test_test_data_management.py": {"User(id=1)"},
    "archive/scripts-oneoff/import_reading_orders.py": {"User(id=1)"},
}


def check_hardcoded_ids_in_file(file_path: Path) -> list[str]:
    """Check a Python file for hardcoded IDs that should be removed."""
    issues = []
    
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()
        
        # Parse the AST to analyze the code
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Skip files that can't be parsed
            return issues
        
        # Check for hardcoded User(id=...) patterns
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for User(id=...) patterns
                if (isinstance(node.func, ast.Name) and node.func.id == 'User'):
                    for keyword in node.keywords:
                        if keyword.arg == 'id' and isinstance(keyword.value, ast.Constant):
                            id_value = keyword.value.value
                            if isinstance(id_value, int) and id_value > 0:
                                issues.append(
                                    f"Hardcoded User(id={id_value}) found at line {node.lineno}"
                                )
                
                # Check for user_id=1 patterns in app code
                if file_path.parts[0] == 'app':  # Only check app/ directory
                    for keyword in node.keywords:
                        if keyword.arg == 'user_id' and isinstance(keyword.value, ast.Constant):
                            id_value = keyword.value.value
                            if id_value == 1:
                                issues.append(
                                    f"Hardcoded user_id=1 found at line {node.lineno}"
                                )
        
        # Check for hardcoded ID patterns in string literals (for cases not caught by AST)
        lines = content.split('\n')
        for line_num, line in enumerate(lines, 1):
            # Skip comments and allow known patterns
            line = line.strip()
            if line.startswith('#') or line.startswith('"""') or line.startswith("'''"):
                continue
                
            # Check for User(id=NUMBER) in strings (fallback)
            if 'User(id=' in line and any(char.isdigit() for char in line):
                # More specific check to avoid false positives
                if 'User(id=' in line and 'id=' in line and any(c.isdigit() for c in line):
                    # Only flag if it's not in the allowed patterns
                    if 'user_id=user.id' not in line and 'user_id=user_id' not in line:
                        issues.append(f"Potential hardcoded User(id=NUMBER) at line {line_num}")
            
            # Check for user_id=1 in app code
            if file_path.parts[0] == 'app' and 'user_id=1' in line:
                # Skip if it's part of a comment or allowed pattern
                if not line.startswith('#') and 'user_id=user_id' not in line:
                    issues.append(f"Hardcoded user_id=1 at line {line_num}")
                    
    except Exception as e:
        issues.append(f"Error parsing {file_path}: {e}")
    
    return issues


def test_no_hardcoded_ids():
    """Test that no problematic hardcoded IDs exist in the codebase."""
    all_issues = []
    
    # Check all Python files in the repository
    repo_root = Path(__file__).parent.parent
    python_files = list(repo_root.rglob('*.py'))
    
    for file_path in python_files:
        # Skip test files that are specifically about checking hardcoded IDs
        if 'test_hardcoded_ids' in file_path.name:
            continue
            
        relative_path = str(file_path.relative_to(repo_root))
        
        # Skip files in the allowed baseline
        if relative_path in KNOWN_HARDCODED_IDS:
            continue
        
        issues = check_hardcoded_ids_in_file(file_path)
        if issues:
            all_issues.extend([f"{relative_path}: {issue}" for issue in issues])
    
    # If there are issues, fail the test with detailed output
    if all_issues:
        error_msg = "Found hardcoded IDs that should be removed:\n"
        for issue in all_issues:
            error_msg += f"  {issue}\n"
        assert False, error_msg


if __name__ == '__main__':
    test_no_hardcoded_ids()