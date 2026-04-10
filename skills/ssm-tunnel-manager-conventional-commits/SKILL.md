---
name: ssm-tunnel-manager-conventional-commits
description: >
  Enforces conventional commit messages for ssm-tunnel-manager.
  Trigger: preparing a git commit, drafting a commit message, or being asked to commit changes.
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## When to Use

- The user asks to create a git commit
- The assistant drafts a commit message
- The assistant reviews whether a commit message is appropriate for the change

## Critical Patterns

- ALWAYS use Conventional Commits
- Format: `<type>: <description>`
- Keep the subject concise and imperative
- Prefer lowercase subjects
- Do NOT add trailing periods
- Do NOT add `Co-Authored-By` or AI attribution
- Choose the type that matches the intent of the change, not just the files touched

### Type Selection

| Change intent | Commit type |
| --- | --- |
| Bug fix or regression fix | `fix` |
| New user-facing behavior or capability | `feat` |
| Documentation-only changes | `docs` |
| Test-only changes | `test` |
| Refactor without user-facing behavior change | `refactor` |
| Tooling, maintenance, chores | `chore` |
| CI workflow updates | `ci` |

### Commit Message Examples

- `fix: restore timed-out tunnels on restart`
- `feat: replace install command with upgrade flow`
- `docs: document GitHub bootstrap workflow`
- `test: cover desired tunnel state persistence`

## Commands

```bash
git commit -m "fix: concise imperative summary"
```
