#!/bin/bash

cleanup() {
    echo ""
    echo "Stopping servers..."
    # Kill all uvicorn and vite processes
    pkill -f "uvicorn app.main:app" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
    # Wait for graceful shutdown
    sleep 2
    # Force kill if still running
    pkill -9 -f "uvicorn app.main:app" 2>/dev/null || true
    pkill -9 -f "vite" 2>/dev/null || true
}

# Trap signals and run cleanup
trap cleanup EXIT INT TERM

echo "Cleaning up old comic-pile servers..."
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
sleep 1

echo "Starting backend on port 8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

echo "Starting frontend on port 5173..."
cd frontend && npm run dev &
FRONTEND_PID=$!

echo ""
echo "Backend: http://localhost:8000 (PID: $BACKEND_PID)"
echo "Frontend: http://localhost:5173 (PID: $FRONTEND_PID)"
echo ""
echo "Press Ctrl+C to stop"
echo ""

wait
