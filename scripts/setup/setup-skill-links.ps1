# setup-skill-links.ps1 -- Windows
#
# Recreate the per-machine links each CLI tester agent uses to read the shared
# skills that live (canonically, git-tracked) at the repo-root skills/. The links
# sit under each CLI's own config dir in its seat folder -- outside the repo, under
# the seat root (Get-SeatRoot in scripts/lib/spawn-agents.ps1) -- so they are
# never committed and every clone makes its own. Run once per fresh clone, after
# the seat folders exist (add_agent_seat.py --materialize, or any launch).
# Idempotent; safe to re-run.
#
# Junctions need no admin rights or Developer Mode, and the CLIs read through them
# transparently. Other (unshared) skills already present in those dirs are left
# untouched -- this only manages the <name>s that exist under repo-root skills/.
#
# Modelled on AI-Automation-Library/script/setup/setup-skill-links.ps1; the only
# differences are this repo's per-agent folder names and config-dir conventions.

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path   # scripts/setup/ -> repo root
$skillsDir = Join-Path $repo "skills"
if (-not (Test-Path $skillsDir)) { throw "No skills/ directory at $skillsDir" }

# Each skills directory a CLI natively discovers. The repo-root .claude/skills is
# this project's own Claude Code session config dir -- linking there lets the
# developer driving this repo use the same skills. The rest are seat 1 of each
# CLI, under the seat root.
. (Join-Path $repo "scripts" "lib" "spawn-agents.ps1")
$seatRoot = Get-SeatRoot -RepoRoot $repo
$cliSkillDirs = @(
    (Join-Path $repo ".claude" "skills"),                                   # Claude Code  (this repo's own session)
    (Join-Path $seatRoot "claude-code_agent1" ".claude" "skills"),          # Claude Code  (reads .claude/skills)
    (Join-Path $seatRoot "codex_agent1" ".codex" "skills"),                 # Codex        (reads .codex/skills)
    (Join-Path $seatRoot "antigravity_agent1" ".agents" "skills")           # Antigravity  (agent-skills standard -- .agents/skills)
)
$names = (Get-ChildItem $skillsDir -Directory).Name

foreach ($base in $cliSkillDirs) {
    New-Item -ItemType Directory -Force $base | Out-Null
    foreach ($name in $names) {
        $link = Join-Path $base $name
        $target = Join-Path $skillsDir $name
        $item = Get-Item $link -Force -ErrorAction SilentlyContinue
        if ($item) {
            if ($item.LinkType) {
                (Get-Item $link -Force).Delete()   # remove the existing junction/symlink only
            } else {
                Write-Warning "$link is a real directory (not a link) -- skipping. Remove it manually to relink."
                continue
            }
        }
        New-Item -ItemType Junction -Path $link -Target $target | Out-Null
        Write-Host "linked $base\$name -> skills\$name"
    }
}
