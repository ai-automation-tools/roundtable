#!/usr/bin/env bash
# setup-skill-links.sh -- Linux / macOS
#
# Recreate the per-machine symlinks each CLI tester agent uses to read the shared
# skills that live (canonically, git-tracked) at the repo-root skills/. The links
# sit under each CLI's own config dir in its seat folder -- outside the repo, under
# the seat root (orchestrator.seats.seat_root()) -- so they are never committed and
# every clone makes its own. Run once per fresh clone.
# Idempotent; safe to re-run.
#
# Other (unshared) skills already present in those dirs are left untouched -- this
# only manages the <name>s that exist under repo-root skills/.
#
# Modelled on AI-Automation-Library/script/setup/setup-skill-links.sh; the only
# differences are this repo's per-agent folder names and config-dir conventions.
set -euo pipefail

repo="$(cd "$(dirname "$0")/../.." && pwd)"   # scripts/setup/ -> repo root
skills_dir="$repo/skills"
[ -d "$skills_dir" ] || { echo "No skills/ directory at $skills_dir" >&2; exit 1; }

# Each skills directory a CLI natively discovers. The repo-root .claude/skills is
# this project's own Claude Code session config dir -- linking there lets the
# developer driving this repo use the same skills. The rest are seat 1 of each
# CLI, under the seat root, which Python resolves (one resolver, not a copy).
py="$repo/.venv/bin/python"; [ -x "$py" ] || py=python3
seat_root="$(cd "$repo/src" && "$py" -c 'from orchestrator import seats; print(seats.seat_root())')"
cli_skill_dirs=(
  "$repo/.claude/skills"                              # Claude Code  (this repo's own session)
  "$seat_root/claude-code_agent1/.claude/skills"      # Claude Code  (reads .claude/skills)
  "$seat_root/codex_agent1/.codex/skills"             # Codex        (reads .codex/skills)
  "$seat_root/antigravity_agent1/.agents/skills"      # Antigravity  (agent-skills standard -- .agents/skills)
)

for base in "${cli_skill_dirs[@]}"; do
  mkdir -p "$base"
  for target in "$skills_dir"/*/; do
    name="$(basename "$target")"
    link="$base/$name"
    if [ -L "$link" ]; then
      rm "$link"
    elif [ -e "$link" ]; then
      echo "skip: $link is a real directory (not a link) -- remove it manually to relink."
      continue
    fi
    ln -s "$skills_dir/$name" "$link"
    echo "linked $base/$name -> skills/$name"
  done
done
