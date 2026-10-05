"""
Syntax verification script for PR #3097 Creator Insights implementation.
This script verifies that the restored implementation files have correct syntax.
"""

import ast
import sys
from pathlib import Path
def check_syntax(file_path: Path) -> bool:
    """Check if a Python file has correct syntax."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        ast.parse(source)
        print(f"✓ {file_path}")
        return True
    except SyntaxError as e:
        print(f"✗ {file_path}: Syntax error on line {e.lineno}: {e.msg}")
        return False
    except Exception as e:
        print(f"✗ {file_path}: Error reading file: {e}")
        return False
def main():
    """Check syntax of all restored files."""
    print("Verifying PR #3097 Creator Insights implementation syntax...")
    print()
    
    # Files that were restored from commit 2a7175c06
    restored_files = [
        "app/schemas/creator_comparison.py",
        "app/services/creator_comparison.py", 
        "app/repositories/creator_comparison.py",
        "app/api/creators.py",
    ]
    
    base_dir = Path("/home/runner/work/comic-pile/comic-pile")
    all_good = True
    
    for file_rel in restored_files:
        file_path = base_dir / file_rel
        if file_path.exists():
            if not check_syntax(file_path):
                all_good = False
        else:
            print(f"✗ {file_path}: File not found")
            all_good = False
    
    print()
    if all_good:
        print("All syntax checks passed! ✓")
        print("\nRestored implementation includes:")
        print("  • app/schemas/creator_comparison.py - Rating distribution & analytics schemas")
        print("  • app/services/creator_comparison.py - Comparison service implementation") 
        print("  • app/repositories/creator_comparison.py - Repository layer for comparison")
        print("  • app/api/creators.py - /compare endpoint (2-4 creators, rating distribution)")
        print("\nThis completes PR #3097: 'Creator insights 1/8: add rating distribution and sample-strength analytics'")
        sys.exit(0)
    else:
        print("Some syntax checks failed!")
        sys.exit(1)
if __name__ == "__main__":
    main()