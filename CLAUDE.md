# Beacon Innovations - Claude Code Context

**Project:** Django 5.x parent company website + financial tracker
**Repo:** C:\beaconinnovation | GitHub: djenkins452/beaconinnovation

---

## Quick Reference

| Item | Value |
|------|-------|
| **API Key** | `beacon-claude-api-key-replace-me-with-real-key` |
| **Ready Tasks** | `GET /admin-console/api/claude/ready-tasks/?auto_start=true` |
| **Update Status** | `POST /admin-console/api/claude/tasks/<id>/status/` |
| **Test Count** | 0 (starting fresh) |
| **Push From** | Main repo (C:\beaconinnovation), NOT worktrees |

**Commands:**
```bash
# Fetch next task (marks as in_progress automatically)
curl -s -H "X-Claude-API-Key: beacon-claude-api-key-replace-me-with-real-key" "https://beacon-innovation.com/admin-console/api/claude/ready-tasks/?limit=1&auto_start=true"

# Mark task done
curl -s -X POST -H "X-Claude-API-Key: beacon-claude-api-key-replace-me-with-real-key" -H "Content-Type: application/json" -d '{"status": "done"}' "https://beacon-innovation.com/admin-console/api/claude/tasks/<ID>/status/"
```

## Testing & Migrations

**Testing:**
```bash
# Test specific app module
python manage.py test finance.tests.test_models -v 1 --failfast

# Run all tests
python manage.py test -v 1

# Check for issues
python manage.py check
```

**Migrations:**
```bash
# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate
```

---

## Worktree Setup

When working in a git worktree, activate the venv from the main repo:

```bash
source /Users/dannyjenkins/Projects/beaconinnovation/venv/bin/activate
```

---

## Tech Stack

- Django 5.x | PostgreSQL (prod) / SQLite (dev)
- Railway deployment | Gunicorn WSGI
- Cloudinary for file storage (shared with WLJ)
- Tesseract for OCR

## Key Architecture

- **Apps:** beaconinnovation (settings), website, admin_console (to build), finance (to build)
- **User model:** Django default auth.User (verify on first task)
- **Avoid:** `wlj/` folder — legacy, do not modify

---

## Reference Documentation

| Doc | Purpose |
|-----|---------|
| `.claude/commands/README.md` | **Slash commands** (`/next`, `/run-task`, `/troubleshoot`, `/log-change`) |
| `docs/beacon_claude_troubleshoot.md` | Known issues & solutions (CHECK FIRST) |
| `docs/beacon_claude_deploy.md` | Railway deployment, migrations |
| `docs/beacon_claude_changelog.md` | Historical changes and fixes |
| `docs/BeaconInnovationFinance.md` | **Financial tracker design spec** |

## Slash Commands

| Command | Model | Purpose |
|---------|-------|---------|
| `/next` | Default | Fetch next ready task, mark in_progress |
| `/run-task` | Sonnet | Execute task with full context, auto-changelog |
| `/troubleshoot` | Haiku | Match error to known issues |
| `/log-change <desc>` | Haiku | Append entry to changelog |

---

## Executable Task Standard

All AdminTask `description` fields MUST be JSON with these keys:

```json
{
    "objective": "What the task should accomplish",
    "inputs": ["Required context (can be empty [])"],
    "actions": ["Step 1", "Step 2 (at least one required)"],
    "output": "Expected deliverable"
}
```

**Validation:** All 4 fields required. Empty objective/output/actions = FAIL.

---

## Run Task Mode Contract

When executing tasks from the API:
1. **Context:** CLAUDE.md is already loaded (don't re-read)
2. **Validate:** Task has objective, inputs, actions, output
3. **Execute:** Actions in order, exactly as written
4. **Verify:** Output criteria met
5. **Complete:** Mark `done` only on full success

**On failure:** HALT, log error, do NOT mark complete.

---

## When Something Isn't Working

**READ FIRST:** `docs/beacon_claude_troubleshoot.md`

Common issues will be documented as they arise during development.

---

## On Task Completion

After ANY code changes:

1. Append to `docs/beacon_claude_changelog.md`:
   - Date, what changed, files modified, why
   - Include migration names if created

2. **Merge and Deploy:**
   - Go to main repo: `cd /Users/dannyjenkins/Projects/beaconinnovation`
   - Fetch worktree branch: `GIT_SSH_COMMAND="ssh -p 443" git fetch git@ssh.github.com:djenkins452/beaconinnovation.git <branch>:refs/remotes/origin/<branch>`
   - Checkout main and merge: `git checkout main && git merge origin/<branch> --no-edit`
   - Push to GitHub: `GIT_SSH_COMMAND="ssh -p 443" git push git@ssh.github.com:djenkins452/beaconinnovation.git main`

**Note:** Use SSH on port 443 (`ssh -p 443` via `ssh.github.com`) as port 22 may timeout.

---

## "What's Next?" Protocol

Use `/next` slash command or say "What's Next?"

1. Output: `Fetching next task...`
2. Run curl with `auto_start=true`
3. Output: `**Session: <Task Title>**`
4. Show the task objective and actions
5. Output: `Run /run-task to execute.`

**DO NOT:** Read CLAUDE.md again, execute the task automatically.

---

## Project-Specific Notes

### Financial Tracker

The primary development focus is building the financial tracker. See `docs/BeaconInnovationFinance.md` for complete design spec.

**Key Features:**
- Multi-account tracking (checking, credit cards)
- Receipt upload with OCR (Tesseract)
- CSV import from Amex statements
- Quarterly tax alerts ($1,000 threshold)
- Full audit logging

**Cloudinary Configuration:**
- Same account as WLJ
- Folder: `beacon-innovations/receipts/`
- Max file size: 10MB
- Allowed types: PDF, JPG, PNG

### Apps to Build

1. **admin_console** — Task management API (Phase 1)
2. **finance** — Financial tracker (Phases 2-14)

### Apps to Avoid

- **wlj/** — Legacy folder, do not touch

---

## Environment Variables Required

```bash
# Django
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,beacon-innovation.com

# Database (prod only)
DATABASE_URL=postgresql://...

# Cloudinary (shared with WLJ)
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# Admin Console
CLAUDE_API_KEY=beacon-claude-api-key-replace-me-with-real-key

# Finance
FINANCE_TAX_ALERT_THRESHOLD=1000
FINANCE_RECEIPT_MAX_SIZE_MB=10
```

---

## Dependencies to Add

When building the finance app, add to `requirements.txt`:

```
pytesseract>=0.3.10
Pillow>=10.0.0
cloudinary>=1.36.0
```

For Railway deployment, Tesseract must be installed via nixpacks or Dockerfile.

---

*Last updated: 2026-01-08*
