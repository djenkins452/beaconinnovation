# Beacon Innovations - Claude Code Slash Commands

This directory contains custom slash commands for Claude Code integration.

## Available Commands

| Command | Purpose | Model |
|---------|---------|-------|
| `/next` | Fetch next ready task from API | Default |
| `/run-task` | Execute current task with full context | Sonnet |
| `/troubleshoot` | Match error to known issues | Haiku |
| `/log-change <desc>` | Append entry to changelog | Haiku |

---

## /next

**Purpose:** Fetch the next ready task from the admin console API and mark it as in_progress.

**Usage:**
```
/next
```

**Behavior:**
1. Calls `GET /admin-console/api/claude/ready-tasks/?limit=1&auto_start=true`
2. Displays task title and objective
3. Shows required actions
4. Prompts to run `/run-task` to execute

**Output:**
```
Fetching next task...

**Session: [Task Title]**

Objective: [task objective]

Actions:
1. [action 1]
2. [action 2]
...

Run /run-task to execute.
```

---

## /run-task

**Purpose:** Execute the current task following the actions exactly as specified.

**Usage:**
```
/run-task
```

**Behavior:**
1. Validates task has objective, inputs, actions, output
2. Executes each action in order
3. Verifies output criteria met
4. Logs changes to changelog
5. Marks task as done via API

**Contract:**
- HALT on any failure
- Do NOT mark complete unless 100% successful
- Always update changelog after code changes

---

## /troubleshoot

**Purpose:** Match an error message to known issues in the troubleshooting guide.

**Usage:**
```
/troubleshoot [error message or description]
```

**Behavior:**
1. Reads `docs/beacon_claude_troubleshoot.md`
2. Searches for matching issue
3. Returns solution if found
4. Suggests next steps if not found

---

## /log-change

**Purpose:** Append an entry to the changelog after making changes.

**Usage:**
```
/log-change <description of what changed>
```

**Behavior:**
1. Opens `docs/beacon_claude_changelog.md`
2. Appends new entry with:
   - Current date
   - Description provided
   - Files modified (auto-detected if possible)
3. Saves file

**Format:**
```markdown
## 2026-01-08

### [Description]
- Files: [list of files]
- Migrations: [if any]
- Notes: [additional context]
```

---

## Setup

These commands require the admin console API to be built and running. See Phase 1 of `docs/BeaconInnovationFinance.md`.

**API Key Configuration:**
Set `CLAUDE_API_KEY` in environment variables. The API validates this key on every request via the `X-Claude-API-Key` header.

---

## Command Files

Each command should have a corresponding file in `.claude/commands/`:

```
.claude/
└── commands/
    ├── README.md (this file)
    ├── next.md
    ├── run-task.md
    ├── troubleshoot.md
    └── log-change.md
```

---

*Last updated: 2026-01-08*
