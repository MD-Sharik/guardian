"""Migration 0007: add a `plan` field to every user record.

Rewrites data/users.json in place. Run with --apply to write changes;
without it, prints what would change.
"""

import json
import sys

PATH = "data/users.json"

with open(PATH, encoding="utf-8") as f:
    users = json.load(f)

for user in users:
    user.setdefault("plan", "free")

if "--apply" in sys.argv:
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    print(f"migrated {len(users)} user records: added 'plan'")
else:
    print(f"dry run: would add 'plan' to {len(users)} user records")
