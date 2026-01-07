# OpenCode Permission Setup for Ralph Wiggum

## Quick Start

```bash
# Run the setup script
./scripts/opencode-permission-setup.sh

# Restart OpenCode to apply changes
# TUI mode (for interactive use)
opencode

# Server mode (for Ralph orchestrator)
opencode serve --port 4096
```

## Permission Strategies

### Option 1: Full Allow (YOLO Mode)
```json
{
  "permission": "allow"
}
```
**Effect:** All operations run without approval  
**Use:** When you completely trust the environment and want zero interruption  
**Risk:** Highest - no guardrails

---

### Option 2: Ralph-Optimized (Recommended)
```json
{
  "permission": {
    "*": "ask",
    "bash": "allow",
    "edit": "allow",
    "read": "allow",
    "task": "allow"
  }
}
```
**Effect:**
- `bash` commands: ALLOW (git, pytest, make, npm, etc.)
- `edit` operations: ALLOW (write files)
- `read` operations: ALLOW (read files)
- `task` spawning: ALLOW (create subagents)
- Everything else: ASK (web fetch, web search, etc.)

**Use:** Ralph loops with controlled autonomy  
**Risk:** Medium - autonomous bash/edit, but verification still asks

---

### Option 3: Safe Ralph
```json
{
  "permission": {
    "*": "ask",
    "bash": {
      "*": "ask",
      "git *": "allow",
      "pytest": "allow",
      "make": "allow",
      "npm *": "allow",
      "uv *": "allow"
    },
    "edit": {
      "*": "ask",
      "*.py": "allow",
      "*.md": "allow",
      "*.txt": "allow",
      "*.json": "allow"
    },
    "read": {
      "*": "allow"
    }
  }
}
```
**Effect:**
- Whitelisted: `git *`, `pytest`, `make`, `npm *`, `uv *`
- Whitelisted edits: `*.py`, `*.md`, `*.txt`, `*.json`
- Everything else: ASK

**Use:** Ralph loops with maximum safety  
**Risk:** Low - only known safe operations autonomous

---

## For Your Manager-Daemon System

### Recommended Config: Ralph-Optimized (Option 2)

This gives workers autonomy to:
- ✅ Run bash commands (git, pytest, make dev, etc.)
- ✅ Edit files (write code, update plan.md)
- ✅ Read files (scan codebase, read docs)
- ✅ Spawn subagents (if needed for complex tasks)
- ✅ Still ask for web searches (verification steps)

### Backup & Restore

The script automatically backs up your current config before changes:
```bash
# Backups stored at:
~/.config/opencode/opencode.json.backup.YYYYMMDD_HHMMSS

# To restore manually:
cp ~/.config/opencode/opencode.json.backup.YYYYMMDD_HHMMSS \
   ~/.config/opencode/opencode.json
```

---

## Integration with Ralph Orchestrator

### Step 1: Configure OpenCode
```bash
cd /home/josh/code/comic-pile
./scripts/opencode-permission-setup.sh
# Select: Option 2 (Ralph-Optimized)
```

### Step 2: Start OpenCode Server
```bash
# Terminal 1
opencode serve --port 4096
```

### Step 3: Create Ralph Orchestrator
```python
# ralph_orchestrator.py
import asyncio
from opencode_ai import AsyncOpencode

class RalphOrchestrator:
    def __init__(self, server_url="http://localhost:4096"):
        self.client = AsyncOpencode(baseUrl=server_url)
        self.plan_file = Path("plan.md")
    
    async def run(self):
        """Main Ralph loop"""
        while not self.is_complete():
            session = await self.client.session.create({
                "title": f"Ralph iteration {self.iteration}"
            })
            
            await self.client.session.prompt({
                "id": session.id,
                "agent": "build",
                "parts": [{
                    "type": "text",
                    "text": self.build_prompt()
                }]
            })
            
            # Wait for completion via events
            await self.wait_for_idle(session.id)
            self.iteration += 1
    
    def build_prompt(self) -> str:
        return f"""READ plan.md. Pick ONE unchecked task.
        Complete task (use code search to verify patterns).
        Commit change (NEVER push).
        Update plan.md.
        If all tasks done, exit.
        Iteration {self.iteration}."""
    
    def is_complete(self) -> bool:
        if not self.plan_file.exists():
            return False
        content = self.plan_file.read_text()
        return "- [ ]" not in content

if __name__ == "__main__":
    orchestrator = RalphOrchestrator()
    asyncio.run(orchestrator.run())
```

### Step 4: Run Orchestrator
```bash
# Terminal 2
python ralph_orchestrator.py
```

---

## Current Config Check

```bash
# View current config
cat ~/.config/opencode/opencode.json

# Test if OpenCode respects config
opencode --version
# Or check logs for permission prompts
```

---

## Security Considerations

### When to Use Full Allow
- ✅ Local development environment
- ✅ Git worktrees (isolated by design)
- ✅ Non-production codebase
- ✅ You trust the model's judgment

### When to Use Ralph-Optimized
- ✅ Production-like workflows
- ✅ Want some guardrails (web/search)
- ✅ Autonomous but with verification

### When to Use Safe Ralph
- ✅ Production code
- ✅ Maximum security needed
- ✅ Learning/unknown codebase

---

## Troubleshooting

### Permissions Not Working
```bash
# 1. Check config syntax
cat ~/.config/opencode/opencode.json | python -m json.tool

# 2. Check OpenCode is reading config
opencode --version
# Look for config path in output

# 3. Restart OpenCode
pkill -f opencode
opencode serve --port 4096
```

### Backup Not Found
```bash
# List all backups
ls -lt ~/.config/opencode/opencode.json.backup.*

# Restore from specific backup
cp ~/.config/opencode/opencode.json.backup.20260106_120000 \
   ~/.config/opencode/opencode.json
```

### Reset to Defaults
```bash
# Remove config (OpenCode will use defaults)
rm ~/.config/opencode/opencode.json

# Or set to permissive default
echo '{"permission": {"*": "ask"}}' > ~/.config/opencode/opencode.json
```

---

## Next Steps

After configuring permissions:

1. **Test with simple task**
   ```bash
   echo "# Test Task\n- [ ] Write hello.py" > plan.md
   opencode run -m "opencode/claude-opus-4-5" "Complete plan.md"
   ```

2. **Build Ralph orchestrator** (see Integration section)

3. **Start orchestrator + server** in parallel terminals

4. **Monitor logs** for permission prompts (should be minimized)

5. **Adjust permissions** if too restrictive or permissive

---

## Related Documentation

- [OpenCode Permissions](https://opencode.ai/docs/permissions/)
- [Ralph Wiggum Research](IMPROVEMENTS_SUMMARY.md#ralph-wiggum-research)
- [Manager System](AGENTS.md)
- [Worker Workflow](WORKER_WORKFLOW.md)
