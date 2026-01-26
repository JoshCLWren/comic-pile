# Thread Queue Management Scripts

This directory contains scripts for auditing and fixing thread queue consistency issues.

## Scripts

### `audit_thread_positions.py`

A comprehensive audit script that checks:
- Thread 210 details (owner, current position, status)
- All threads for testuser123 with their positions
- Gaps or inconsistencies in position numbering
- Active vs total thread counts
- Sequential position verification
- Duplicate position detection

**Usage:**
```bash
python -m scripts.audit_thread_positions
```

**Output:**
- Detailed thread information for Thread 210
- Complete listing of testuser123's threads
- Position gap analysis
- Duplicate position detection
- Thread statistics by user
- Overall audit summary with recommendations

### `fix_thread_positions.py`

A script to fix duplicate positions by reorganizing all active threads into sequential positions starting from 1.

**Usage:**
```bash
python -m scripts.fix_thread_positions
```

**What it does:**
- Gets all active threads ordered by current position (and by ID as tiebreaker)
- Reorganizes them to have sequential positions: 1, 2, 3, etc.
- Updates the database with the corrected positions
- Verifies that no duplicates remain

**⚠️ Warning:** This script will modify thread positions in the database. It's designed to be safe, but consider backing up your database first.

## Example Workflow

### 1. Diagnose Issues
Run the audit script to identify problems:
```bash
python -m scripts.audit_thread_positions
```

### 2. Fix Issues (if found)
If the audit finds duplicate positions, run the fix script:
```bash
python -m scripts.fix_thread_positions
```

### 3. Verify Fixes
Run the audit again to confirm issues are resolved:
```bash
python -m scripts.audit_thread_positions
```

## Common Issues Detected

### Duplicate Positions
**Problem:** Multiple threads have the same `queue_position` value.
**Solution:** Run `fix_thread_positions.py` to reorganize positions sequentially.

### Position Gaps
**Problem:** Missing positions in the sequence (e.g., positions 1, 2, 4, 5 but no 3).
**Note:** The fix script will automatically resolve gaps when reorganizing.

### Thread 210 Specific Issues
The audit script pays special attention to Thread 210 because this is often used for testing position moves. It will:
- Show Thread 210's current position and status
- Indicate if moving to position 11 should be possible
- Check for conflicts at the target position

## Database Connection

Both scripts use the same database configuration as the main application:
- Uses `SessionLocal` from `app.database`
- Follows the project's existing patterns and conventions
- Properly handles database sessions and transactions

## Error Handling

- Scripts include comprehensive error handling
- Database transactions are rolled back on error
- Clear error messages are provided for debugging

## Type Safety

Both scripts follow the project's type annotation standards:
- Use `|` union syntax instead of `Optional[]` or `Union[]`
- Avoid `Any` types
- Provide precise type hints for better code quality