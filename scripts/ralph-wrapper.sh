#!/bin/bash

RALPH_WRAPPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RALPH_WRAPPER_DIR"

trap cleanup EXIT

cleanup() {
    if [[ -n "$RALPH_PID" ]]; then
        kill $RALPH_PID 2>/dev/null
    fi
    if [[ -n "$MANAGER_PID" ]]; then
        kill $MANAGER_PID 2>/dev/null
    fi
}

check_server() {
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "running"
    else
        echo "stopped"
    fi
}

get_ralph_mode() {
    if [[ "${RALPH_MODE:-false}" == "true" ]]; then
        echo "true"
    else
        echo "false"
    fi
}

show_status() {
    local ralph_mode=$(get_ralph_mode)
    local server_status=$(check_server)
    
    echo ""
    echo "╔════════════════════════════════════╗"
    echo "║     OpenCode Agent System Launcher ║"
    echo "╠════════════════════════════════════╣"
    echo "║                                    ║"
    echo "║  Mode Status:                      ║"
    printf "║  • RALPH_MODE: %-17s ║\n" "$ralph_mode"
    printf "║  • Server: %-22s ║\n" "$server_status"
    echo "║                                    ║"
    
    local manager_running=$(pgrep -f "manager_daemon.py" | wc -l)
    local ralph_running=$(pgrep -f "ralph_orchestrator.py" | wc -l)
    
    if [[ $manager_running -gt 0 ]]; then
        echo "║  • Manager: running               ║"
    else
        echo "║  • Manager: stopped               ║"
    fi
    
    if [[ $ralph_running -gt 0 ]]; then
        echo "║  • Ralph: running                 ║"
    else
        echo "║  • Ralph: stopped                 ║"
    fi
    
    echo "║                                    ║"
    
    if [[ -f "tasks.json" ]]; then
        local pending_tasks=$(python3 -c "import json; data=json.load(open('tasks.json')); print(sum(1 for t in data.get('tasks', []) if t.get('status') != 'done'))" 2>/dev/null || echo "?")
        printf "║  • Pending tasks (Ralph): %-10s ║\n" "$pending_tasks"
    fi
    
    if [[ "$server_status" == "running" ]]; then
        local pending_api=$(curl -s http://localhost:8000/api/tasks 2>/dev/null | python3 -c "import sys, json; data=json.load(sys.stdin); print(sum(1 for t in data if t.get('status') not in ['done', 'cancelled']))" 2>/dev/null || echo "?")
        printf "║  • Pending tasks (API): %-11s ║\n" "$pending_api"
    fi
    
    echo "║                                    ║"
    echo "╚════════════════════════════════════╝"
}

start_ralph_mode() {
    echo ""
    echo "✓ Ralph mode active. Working from tasks.json"
    
    if [[ ! -f "tasks.json" ]]; then
        echo "⚠ tasks.json not found. Creating empty tasks file..."
        echo '{"tasks": []}' > tasks.json
    fi
    
    export RALPH_MODE=true
    python3 scripts/ralph_orchestrator.py
}

start_manager_worker_mode() {
    echo ""
    echo "✓ Manager/worker mode active. Using Task API"
    
    export RALPH_MODE=false
    
    local server_status=$(check_server)
    if [[ "$server_status" != "running" ]]; then
        echo "⚠ Task API server not running. Starting server..."
        make dev > /dev/null 2>&1 &
        sleep 3
        echo "✓ Server started on port 8000"
    fi
    
    if [[ ! -d "logs" ]]; then
        mkdir -p logs
    fi
    
    echo "✓ Starting manager daemon..."
    python3 -u agents/manager_daemon.py > logs/manager-$(date +%Y%m%d).log 2>&1 &
    MANAGER_PID=$!
    echo "✓ Manager daemon started (PID: $MANAGER_PID)"
    
    echo ""
    echo "Workers can be launched manually or via Worker Pool Manager."
    echo ""
    read -p "Press Enter to return to menu or Ctrl+C to exit..."
}

start_server_only() {
    echo ""
    echo "✓ Task API server running on port 8000"
    
    make dev
}

show_menu() {
    clear
    show_status
    echo ""
    echo "  Quick Actions:"
    echo "  [1] Ralph Mode"
    echo "  [2] Manager/Worker Mode"
    echo "  [3] Start Server"
    echo "  [4] Status"
    echo "  [5] Exit"
    echo ""
}

main() {
    while true; do
        show_menu
        read -p "Select mode: " choice
        
        case $choice in
            1)
                start_ralph_mode
                ;;
            2)
                start_manager_worker_mode
                ;;
            3)
                start_server_only
                ;;
            4)
                show_status
                read -p "Press Enter to continue..."
                ;;
            5)
                echo ""
                echo "Exiting..."
                exit 0
                ;;
            *)
                echo "Invalid option. Please try again."
                sleep 1
                ;;
        esac
    done
}

main
