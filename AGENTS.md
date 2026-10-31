# Beacon Innovations - Codex Context

**Project:** Django 5.x parent company website + financial tracker
**Repo:** C:\beaconinnovation | GitHub: djenkins452/beaconinnovation

---

## Standing Constraints (MUST follow — override convenience)

1. **PostgreSQL only, every environment.** Local dev, automated tests, staging, and production all use PostgreSQL. SQLite is not permitted anywhere — no configuration, no fallback. `DATABASE_URL` is required and must be a PostgreSQL URL; missing/invalid config must fail loudly. The aegis `platform` database stays separate via `PlatformRouter`; never merge the databases.
2. **No hosted CI.** Do not add GitHub Actions, GitHub-hosted testing, or any other hosted/cloud CI. Run the test suite **locally** against PostgreSQL (`docker compose up -d` provides a free local database; see `.env.example`).
3. **No paid services or cost-increasing infrastructure without prior approval.** Before provisioning or changing anything that creates one-time, recurring, or usage-based charges — managed PostgreSQL, persistent storage/volumes, backups, storefronts, payment services, deployment previews, etc. — first explain the expected one-time, recurring, and usage-based costs and obtain explicit approval. If pricing is unknown, resolve that first. PostgreSQL remains mandatory; satisfy it with a free local setup.
4. **No deploys/cutovers without explicit instruction.** Deploys are on `main` only. Do not push to `main`, merge, enable auto-merge, or perform a production cutover unless told to. Before pushing any branch or opening a PR, verify it cannot trigger a deployment or a (possibly paid) preview environment; if that cannot be established, stop and ask.

---

## Quick Reference

| Item | Value |
|------|-------|
| **API Key** | `beacon-Codex-api-key-replace-me-with-real-key` |
| **Ready Tasks** | `GET /admin-console/api/Codex/ready-tasks/?auto_start=true` |
| **Update Status** | `POST /admin-console/api/Codex/tasks/<id>/status/` |
| **Test Count** | 0 (starting fresh) |
| **Push From** | Main repo (C:\beaconinnovation), NOT worktrees |

**Commands:**
```bash
# Fetch next task (marks as in_progress automatically)
curl -s -H "X-Codex-API-Key: beacon-Codex-api-key-replace-me-with-real-key" "https://beacon-innovation.com/admin-console/api/Codex/ready-tasks/?limit=1&auto_start=true"

# Mark task done
curl -s -X POST -H "X-Codex-API-Key: beacon-Codex-api-key-replace-me-with-real-key" -H "Content-Type: application/json" -d '{"status": "done"}' "https://beacon-innovation.com/admin-console/api/Codex/tasks/<ID>/status/"
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

- Django 5.x | PostgreSQL (ALL environments — no SQLite anywhere)
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
| `.Codex/commands/README.md` | **Slash commands** (`/next`, `/run-task`, `/troubleshoot`, `/log-change`) |
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
1. **Context:** AGENTS.md is already loaded (don't re-read)
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

**IMPORTANT:** After completing ANY phase or task with code changes, you MUST:

1. **Update Changelog:**
   - Append to `docs/beacon_claude_changelog.md`
   - Include: date, what changed, files modified, migration names

2. **Commit Changes:**
   - `git add -A && git commit -m "Description..."`

3. **Merge/deploy only on explicit authorization (NOT part of "completion").**
   Do not merge to `main`, push to `main`, or deploy to finish a task. Completion
   means: changelog updated, changes committed to a **feature branch**, and — when
   explicitly told to — pushed to that feature branch. Merging to `main`
   auto-deploys to Railway, so it happens only on explicit instruction and only
   after verifying the push/PR cannot trigger an unwanted deployment or a paid
   preview (see Standing Constraints).

**Note:** When explicitly authorized to push a feature branch, SSH over port 443
works (`GIT_SSH_COMMAND="ssh -p 443"` via `ssh.github.com`) if port 22 times out.

---

## "What's Next?" Protocol

Use `/next` slash command or say "What's Next?"

1. Output: `Fetching next task...`
2. Run curl with `auto_start=true`
3. Output: `**Session: <Task Title>**`
4. Show the task objective and actions
5. Output: `Run /run-task to execute.`

**DO NOT:** Read AGENTS.md again, execute the task automatically.

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

# Database (REQUIRED in every environment — PostgreSQL only, no SQLite)
DATABASE_URL=postgresql://...

# Cloudinary (shared with WLJ)
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# Admin Console
CLAUDE_API_KEY=beacon-Codex-api-key-replace-me-with-real-key

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
