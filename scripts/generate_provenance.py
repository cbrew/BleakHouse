"""Generate provenance badges for webapp pages based on git history."""
import json
import subprocess
import os

PAGES_DIR = "webapp/pages"
GITHUB_BASE = "https://github.com/cbrew/BleakHouse"

# Pages to badge (exclude podcast scripts/reports — those are fully AI)
PAGES = {}
for f in sorted(os.listdir(PAGES_DIR)):
    if f.endswith(".html"):
        PAGES[f.replace(".html", "")] = os.path.join(PAGES_DIR, f)

# Known human-edit commits (from conversation evidence)
HUMAN_EDIT_COMMITS = {
    "2f0ab7e",  # "update blog post per user edits" (Non-expert experts rename)
}

# Pages where user provided significant editorial direction
HUMAN_DIRECTED = {
    "landing",  # user directed structure, motivation, professional framing
    "blog",     # user renamed sections, directed content additions
    "research", # user directed honest qualification of claims
    "help",     # user requested references move, In Our Time fix
}

results = {}
for name, path in PAGES.items():
    log = subprocess.run(
        ["git", "log", "--format=%H", "--", path],
        capture_output=True, text=True
    ).stdout.strip().split("\n")
    total = len([h for h in log if h])

    # Check each commit for co-authorship
    ai_count = 0
    for h in log:
        if not h:
            continue
        body = subprocess.run(
            ["git", "log", "-1", "--format=%b", h],
            capture_output=True, text=True
        ).stdout
        if "Co-Authored-By" in body and "Claude" in body:
            ai_count += 1

    human_edits = sum(1 for h in log if h[:7] in HUMAN_EDIT_COMMITS)
    human_directed = name in HUMAN_DIRECTED

    if total == 0:
        badge = "unknown"
        color = "grey"
    elif human_directed:
        badge = "AI-drafted, human-directed"
        color = "yellow"
    elif human_edits > 0:
        badge = "AI-drafted, human-edited"
        color = "yellow"
    else:
        badge = "AI-drafted"
        color = "red"

    results[name] = {
        "badge": badge,
        "color": color,
        "total_commits": total,
        "ai_commits": ai_count,
        "human_edits": human_edits,
        "github_url": f"{GITHUB_BASE}/commits/main/{path}",
    }

# Output as JSON
print(json.dumps(results, indent=2))
