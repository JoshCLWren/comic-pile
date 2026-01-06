#!/usr/bin/env bash

# Task Monitor Setup Script
#
# Usage:
#   bash scripts/monitor-tasks.sh
#
# This script creates a tmux session named "task-monitor" with 3 panes:
#   - Left: Manager agent monitoring loop (checks API health, stale tasks, blocked tasks, in-review count)
#   - Middle: Tails manager daemon logs
#   - Right: Shows coordinator dashboard URL and hints
#
# Prerequisites:
#   - tmux installed
#   - Task API running on http://localhost:8000
#   - Logs directory exists with manager logs
#
# To exit the monitoring session:
#   Press Ctrl+B then d to detach (keeps session running in background)
#   Press Ctrl+B then :kill-session to terminate the session
#
# To reattach to an existing session:
#   tmux attach-session -t task-monitor

SESSION_NAME="task-monitor"

# Check if session already exists
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo "Session '$SESSION_NAME' already exists. Attaching..."
  tmux attach-session -t "$SESSION_NAME"
  exit 0
fi

# Create new session
tmux new-session -d -s "$SESSION_NAME"

# Split into 3 panes
tmux split-window -h -t "$SESSION_NAME"  # Split right
tmux split-window -h -t "$SESSION_NAME:0.1"  # Split middle

# Left pane: Manager monitoring loop
tmux select-pane -t "$SESSION_NAME:0.0"
tmux send-keys -t "$SESSION_NAME:0.0" "while true; do
  echo \"=== Monitoring check at \$(date) ===\"
  echo \"\"

  api_health=\$(curl -s -o /dev/null -w \"%{http_code}\" http://localhost:8000/api/tasks/ready)
  if [ \"\$api_health\" != \"200\" ]; then
    echo \"🚨 TASK API UNHEALTHY: HTTP \$api_health\"
    echo \"⚠️  Unable to create tasks. Alert user and pause new task creation.\"
    echo \"\"
  else
    echo \"✅ API healthy\"
    echo \"\"
  fi

  stale_tasks=\$(curl -s http://localhost:8000/api/tasks/ 2>/dev/null | jq '[.[] | select(.status == \"in_progress\") | select((.last_heartbeat | fromiso8601) < (now - 20 * 60))]' 2>/dev/null)
  if [ \"\$stale_tasks\" != \"[]\" ] && [ -n \"\$stale_tasks\" ]; then
    echo \"⚠️  STALE TASKS FOUND (20+ min no heartbeat):\"
    echo \"\$stale_tasks\"
    echo \"\"
  else
    echo \"✅ No stale tasks\"
    echo \"\"
  fi

  blocked_tasks=\$(curl -s http://localhost:8000/api/tasks/ 2>/dev/null | jq '[.[] | select(.status == \"blocked\")]' 2>/dev/null)
  if [ \"\$blocked_tasks\" != \"[]\" ] && [ -n \"\$blocked_tasks\" ]; then
    echo \"🚫 BLOCKED TASKS FOUND:\"
    echo \"\$blocked_tasks\"
    echo \"⏱️  YOU MUST CREATE RESOLUTION TASKS WITHIN 5 MINUTES\"
    echo \"\"
  else
    echo \"✅ No blocked tasks\"
    echo \"\"
  fi

  in_review_count=\$(curl -s http://localhost:8000/api/tasks/ 2>/dev/null | jq '[.[] | select(.status == \"in_review\")] | length' 2>/dev/null)
  echo \"📊 In-review tasks count: \$in_review_count\"
  echo \"\"
  echo \"Sleeping for 2 minutes...\"
  echo \"\"
  sleep 120
done" C-m

# Middle pane: Tail manager daemon logs
tmux select-pane -t "$SESSION_NAME:0.1"
tmux send-keys -t "$SESSION_NAME:0.1" "tail -f logs/manager-*.log" C-m

# Right pane: Coordinator dashboard hints
tmux select-pane -t "$SESSION_NAME:0.2"
tmux send-keys -t "$SESSION_NAME:0.2" "cat << 'EOF'
╔═══════════════════════════════════════════════════════════╗
║  Task Coordinator Dashboard                                ║
╠═══════════════════════════════════════════════════════════╣
║  Coordinator URL: http://localhost:8000/coordinator         ║
║                                                              ║
║  Useful commands:                                            ║
║  - List all tasks: curl http://localhost:8000/api/tasks/    ║
║  - Create task: POST /api/tasks/ (see /docs)                ║
║  - Update task: PATCH /api/tasks/{id}                       ║
║  - Mark task done: PATCH with status=\"done\"                ║
║                                                              ║
║  This pane shows hints and reminders                        ║
╚═══════════════════════════════════════════════════════════╝

Press Ctrl+B then d to detach (session keeps running)
Press Ctrl+B then :kill-session to terminate
EOF" C-m

# Attach to the session
tmux attach-session -t "$SESSION_NAME"
