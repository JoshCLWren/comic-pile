#!/usr/bin/env python3

"""Script to run Alembic migrations."""

import subprocess
import sys
import os

def main():
    # Change to the alembic directory
    os.chdir("alembic")
    
    try:
        # Run alembic upgrade head
        result = subprocess.run([
            sys.executable, "-m", "alembic", "upgrade", "head"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print("Error running alembic migration:")
            print(result.stderr)
            sys.exit(1)
        else:
            print("Migration completed successfully")
            print(result.stdout)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()