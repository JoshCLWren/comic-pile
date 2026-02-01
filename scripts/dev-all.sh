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

# Health check function
wait_for_server() {
    local url=$1
    local name=$2
    local max_attempts=30
    local attempt=1

    echo "Waiting for $name to start..."

    while [[ $attempt -le $max_attempts ]]; do
        if curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null | grep -q "200\|404"; then
            echo "✓ $name is responding"
            return 0
        fi

        # Check if process is still running
        local pid_var="${name^^}_PID"
        pid_var="${pid_var// /_}"
        local pid
        pid=$(eval echo "\$$pid_var")

        if ! kill -0 "$pid" 2>/dev/null; then
            echo "✗ $name process died during startup (PID: $pid)"
            return 1
        fi

        sleep 1
        ((attempt++))
    done

    echo "✗ $name failed to start within ${max_attempts}s"
    return 1
}

# Wait for servers to start and verify they're responding
if ! wait_for_server "http://localhost:${BACKEND_PORT}/docs" "backend"; then
    echo "ERROR: Backend failed to start. Check logs above."
    cleanup
    exit 1
fi

if ! wait_for_server "http://localhost:${FRONTEND_PORT}" "frontend"; then
    echo "ERROR: Frontend failed to start. Check logs above."
    cleanup
    exit 1
fi

echo ""
echo "Backend: http://localhost:${BACKEND_PORT} (PID: $BACKEND_PID)"
echo "Frontend: http://localhost:${FRONTEND_PORT} (PID: $FRONTEND_PID)"
echo ""
echo "Press Ctrl+C to stop"
echo ""

wait
