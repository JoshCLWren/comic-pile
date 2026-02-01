#!/bin/bash

# Configurable ports with defaults
BACKEND_PORT=${BACKEND_PORT:-8000}
FRONTEND_PORT=${FRONTEND_PORT:-5173}

# PID file for tracking this script's processes
PID_FILE="/tmp/comic-pile-dev.pids"

cleanup() {
    echo ""
    echo "Stopping servers..."
    
    # Read all PIDs into array before processing
    local pids=()
    if [[ -f "$PID_FILE" ]]; then
        while read -r pid; do
            [[ -n "$pid" ]] && pids+=("$pid")
        done < "$PID_FILE"
    fi
    
    # Graceful kill with process name verification
    for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            local cmd
            cmd=$(ps -p "$pid" -o comm= 2>/dev/null)
            if [[ "$cmd" =~ (uvicorn|node|npm|vite) ]]; then
                echo "Killing $cmd (PID: $pid)"
                kill "$pid" 2>/dev/null || true
            fi
        fi
    done
    
    # Wait for graceful shutdown
    sleep 2
    
    # Force kill any remaining processes
    for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            local cmd
            cmd=$(ps -p "$pid" -o comm= 2>/dev/null)
            if [[ "$cmd" =~ (uvicorn|node|npm|vite) ]]; then
                echo "Force killing $cmd (PID: $pid)"
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
    done
    
    # Clean up PID file last
    rm -f "$PID_FILE"
}

# Only trap interrupt signals, NOT exit
trap cleanup INT TERM

echo "Cleaning up old comic-pile servers from previous runs..."
cleanup

echo "Starting backend on port ${BACKEND_PORT}..."
uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" --reload &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$PID_FILE"

echo "Starting frontend on port ${FRONTEND_PORT}..."
cd frontend && npm run dev &
FRONTEND_PID=$!
echo "$FRONTEND_PID" >> "$PID_FILE"

echo ""
echo "Backend: http://localhost:${BACKEND_PORT} (PID: $BACKEND_PID)"
echo "Frontend: http://localhost:${FRONTEND_PORT} (PID: $FRONTEND_PID)"
echo ""
echo "Press Ctrl+C to stop"
echo ""

wait
