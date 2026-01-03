"""Script to create tasks from user notes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Task


def create_tasks():
    """Create tasks from predefined task data."""
    db = SessionLocal()
    try:
        tasks_data = [
            {
                "task_id": "TASK-BUG-001",
                "title": "Fix Die Rolled Display Bug",
                "description": "The die rolled value always shows 1 when switching between roll and rate views. It should persist the rolled number until a new roll occurs.",
                "priority": "HIGH",
                "estimated_effort": "2 hours",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-200 bug-fixes\n2. Work there: cd ../comic-pile-task-200\n3. Investigate roll/rate view state management\n4. Fix the rolled value persistence bug\n5. Test the fix by rolling, switching views, and verifying the rolled value persists",
            },
            {
                "task_id": "TASK-BUG-002",
                "title": "Fix Incorrect Messaging at d4 Stage",
                "description": "When rating 4+ at d4 stage, the app incorrectly states die step is going down, but d4 is already the minimum die size.",
                "priority": "HIGH",
                "estimated_effort": "1 hour",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-200 bug-fixes\n2. Work there: cd ../comic-pile-task-200\n3. Find the dice ladder messaging logic\n4. Add check to prevent step-down messaging at d4\n5. Test rating at d4 with 4+ to verify correct messaging",
            },
            {
                "task_id": "TASK-UI-001",
                "title": "Redesign Queue Screen",
                "description": "Queue screen currently shows active ladder with dice and roll pool, which is confusing. Should show all comics in queue with ability to remove, move up/down, and edit.",
                "priority": "HIGH",
                "estimated_effort": "4 hours",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-201 queue-redesign\n2. Work there: cd ../comic-pile-task-201\n3. Redesign queue template to show all comics\n4. Add controls for remove, move up, move down\n5. Add edit functionality for queue entries\n6. Test all queue operations",
            },
            {
                "task_id": "TASK-UI-002",
                "title": "Improve Roll Pool Readability",
                "description": "The numbers next to comics in the roll pool on the roll view are difficult to read. Make them more prominent and legible.",
                "priority": "MEDIUM",
                "estimated_effort": "1 hour",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-202 ui-improvements\n2. Work there: cd ../comic-pile-task-202\n3. Improve roll pool number styling\n4. Ensure good contrast and sizing\n5. Test readability on different screen sizes",
            },
            {
                "task_id": "TASK-FEAT-001",
                "title": "Add Manual Dice Control",
                "description": "Users should be able to manually change which dice they are rolling at any point, giving them control over their reading progression.",
                "priority": "MEDIUM",
                "estimated_effort": "3 hours",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-203 manual-control\n2. Work there: cd ../comic-pile-task-203\n3. Add UI controls to manually select die size\n4. Update backend to handle manual die selection\n5. Ensure manual selection persists appropriately\n6. Test manual die selection workflow",
            },
            {
                "task_id": "TASK-FEAT-002",
                "title": "Add Undo/History Functionality",
                "description": "History should allow going back to a point in history or rewriting it. Currently no undo capability exists.",
                "priority": "MEDIUM",
                "estimated_effort": "5 hours",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-204 undo-history\n2. Work there: cd ../comic-pile-task-204\n3. Design undo/rewrite model for session events\n4. Implement backend API for rolling back state\n5. Add UI controls for undo operations\n6. Test undo and rewrite scenarios",
            },
            {
                "task_id": "TASK-FEAT-003",
                "title": "Add Loading Indicator After Rating",
                "description": "There is a long pause after rating before the app renders. A loading screen or indicator would improve user experience.",
                "priority": "MEDIUM",
                "estimated_effort": "2 hours",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-205 loading-indicators\n2. Work there: cd ../comic-pile-task-205\n3. Add loading state to rating submission\n4. Implement visual loading indicator\n5. Test loading indicator shows during long operations",
            },
            {
                "task_id": "TASK-FEAT-004",
                "title": "Add Dynamic Rating Messages",
                "description": 'Change the message as user slides rating bar to different phrases matching the score (e.g., "world class", "best ever", "worst ever").',
                "priority": "MEDIUM",
                "estimated_effort": "2 hours",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-206 dynamic-messages\n2. Work there: cd ../comic-pile-task-206\n3. Create mapping of rating scores to descriptive phrases\n4. Add JavaScript to update message on slider input\n5. Test dynamic message updates across rating range",
            },
            {
                "task_id": "TASK-FEAT-005",
                "title": "Add Reroll Functionality",
                "description": "Allow users to reroll when stuck in weird loops (e.g., 1,2,1,2 at d4 step). This gives more control over the experience.",
                "priority": "MEDIUM",
                "estimated_effort": "3 hours",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-207 reroll\n2. Work there: cd ../comic-pile-task-207\n3. Add reroll UI control\n4. Implement backend reroll endpoint\n5. Ensure reroll resets appropriately\n6. Test reroll functionality",
            },
            {
                "task_id": "TASK-FEAT-006",
                "title": "Add Configurable Ladder Starting Point",
                "description": "Starting the ladder at d6 does not give enough room to climb. Allow configuration of starting die size.",
                "priority": "LOW",
                "estimated_effort": "2 hours",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-208 config\n2. Work there: cd ../comic-pile-task-208\n3. Add settings model for ladder configuration\n4. Add UI for configuring starting die size\n5. Update dice ladder to use configured starting point\n6. Test different starting configurations",
            },
            {
                "task_id": "TASK-FEAT-007",
                "title": "Improve Session Events Display",
                "description": "Session events are indecipherable with just time logs and random interspersed content. Make events clear and meaningful.",
                "priority": "HIGH",
                "estimated_effort": "4 hours",
                "instructions": "1. Create worktree: git worktree add ../comic-pile-task-209 event-display\n2. Work there: cd ../comic-pile-task-209\n3. Analyze current event structure\n4. Redesign event display to be human-readable\n5. Add context and descriptions to events\n6. Test event display clarity",
            },
        ]

        created_count = 0

        for data in tasks_data:
            existing_task = db.execute(
                select(Task).where(Task.task_id == data["task_id"])
            ).scalar_one_or_none()

            if existing_task:
                print(f"Task {data['task_id']} already exists - skipping")
            else:
                new_task = Task(
                    task_id=data["task_id"],
                    title=data["title"],
                    description=data.get("description"),
                    instructions=data.get("instructions"),
                    priority=data["priority"],
                    dependencies=data.get("dependencies"),
                    estimated_effort=data["estimated_effort"],
                    status="pending",
                    completed=False,
                )
                db.add(new_task)
                created_count += 1
                print(f"Created task: {data['task_id']} - {data['title']}")

        db.commit()
        print(f"\nTotal tasks created: {created_count}")
        print(f"Total tasks skipped (already exist): {len(tasks_data) - created_count}")

    finally:
        db.close()


if __name__ == "__main__":
    create_tasks()
