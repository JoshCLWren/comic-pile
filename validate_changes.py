#!/usr/bin/env python3
"""
Simple validation script for the creator comparison denominator ambiguity fix.
This script validates the basic syntax and structure of the changes.
"""

import sys
import os

def validate_python_syntax():
    """Validate Python syntax of the changed files."""
    files_to_check = [
        'app/schemas/creator_comparison.py',
        'app/services/creator_comparison.py',
    ]
    
    for file_path in files_to_check:
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Try to compile the Python code
            compile(content, file_path, 'exec')
            print(f"✓ {file_path}: Python syntax is valid")
        except SyntaxError as e:
            print(f"✗ {file_path}: Syntax error - {e}")
            return False
        except Exception as e:
            print(f"✗ {file_path}: Error - {e}")
            return False
    
    return True

def validate_schema_structure():
    """Validate that the schema has the required fields by checking the file content."""
    try:
        with open('app/schemas/creator_comparison.py', 'r') as f:
            content = f.read()
        
        # Check if the schema has the required fields
        if 'rated_issue_count: int = Field(' not in content:
            print("✗ Schema missing rated_issue_count field")
            return False
        
        print("✓ Schema has rated_issue_count field")
        return True
    except Exception as e:
        print(f"✗ Schema validation error: {e}")
        return False

def validate_service_changes():
    """Validate that the service has the required changes."""
    try:
        with open('app/services/creator_comparison.py', 'r') as f:
            content = f.read()
        
        # Check if the service calculates rated_issue_count
        if 'rated_issue_count=len(role_ratings)' not in content:
            print("✗ Service missing rated_issue_count calculation")
            return False
        
        print("✓ Service has rated_issue_count calculation")
        return True
    except Exception as e:
        print(f"✗ Service validation error: {e}")
        return False

def validate_frontend_changes():
    """Validate that the frontend has the required changes."""
    try:
        with open('frontend/src/types/index.ts', 'r') as f:
            content = f.read()
        
        # Check if the interface has the required fields
        if 'rated_issue_count: number' not in content:
            print("✗ Frontend types missing rated_issue_count field")
            return False
        
        # Check if the RoleStatRow component uses the new field
        with open('frontend/src/pages/CreatorComparisonPage.tsx', 'r') as f:
            frontend_content = f.read()
        
        if 'rated_issue_count' not in frontend_content:
            print("✗ Frontend component missing rated_issue_count usage")
            return False
        
        print("✓ Frontend has rated_issue_count field and usage")
        return True
    except Exception as e:
        print(f"✗ Frontend validation error: {e}")
        return False

def validate_test_changes():
    """Validate that the tests have been updated."""
    try:
        with open('tests/test_creator_comparison_api.py', 'r') as f:
            content = f.read()
        
        # Check if the test expects the new field
        if 'rated_issue_count' not in content:
            print("✗ Tests missing rated_issue_count expectations")
            return False
        
        print("✓ Tests have rated_issue_count expectations")
        return True
    except Exception as e:
        print(f"✗ Test validation error: {e}")
        return False

def main():
    print("Validating creator comparison denominator ambiguity fix...")
    print("=" * 60)
    
    all_valid = True
    
    # Validate Python syntax
    print("\n1. Validating Python syntax...")
    all_valid &= validate_python_syntax()
    
    # Validate schema structure
    print("\n2. Validating schema structure...")
    all_valid &= validate_schema_structure()
    
    # Validate service changes
    print("\n3. Validating service changes...")
    all_valid &= validate_service_changes()
    
    # Validate frontend changes
    print("\n4. Validating frontend changes...")
    all_valid &= validate_frontend_changes()
    
    # Validate test changes
    print("\n5. Validating test changes...")
    all_valid &= validate_test_changes()
    
    print("\n" + "=" * 60)
    if all_valid:
        print("✓ All validations passed!")
        print("\nSummary of changes:")
        print("- Added rated_issue_count field to CreatorComparisonRoleStat schema")
        print("- Updated service to calculate rated_issue_count for role stats")
        print("- Updated RoleStatRow component to display both credited and rated counts")
        print("- Updated tests to expect the new rated_issue_count field")
        print("- Updated TypeScript types to match the backend schema")
        return 0
    else:
        print("✗ Some validations failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())