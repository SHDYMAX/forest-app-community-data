import json, requests, base64, os
from datetime import date
from pathlib import Path

Path("/tmp/forest_data").mkdir(exist_ok=True)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = "SHDYMAX/forest-app-community-data"
gh_headers = {"Authorization": f"token {GITHUB_TOKEN}"}

with open("/tmp/forest_data/file_sha.txt") as f: file_sha = f.read().strip()
with open("/tmp/forest_data/existing_all.json") as f: existing = json.load(f)
with open("/tmp/forest_data/new_entries.json") as f: new_entries = json.load(f)

all_data = existing + new_entries
content_b64 = base64.b64encode(json.dumps(all_data, ensure_ascii=False, indent=2).encode()).decode()

if file_sha:
    push = requests.put(f"https://api.github.com/repos/{REPO}/contents/comments.json",
        headers={**gh_headers,"Content-Type":"application/json"},
        json={"message":f"data: +{len(new_entries)} entries ({date.today()})","content":content_b64,"sha":file_sha})
else:
    push = requests.put(f"https://api.github.com/repos/{REPO}/contents/comments.json",
        headers={**gh_headers,"Content-Type":"application/json"},
        json={"message":f"data: +{len(new_entries)} entries ({date.today()})","content":content_b64})

print(f"GitHub: {push.status_code}")

totals = {"total":len(all_data),"new_today":len(new_entries),
    "forest_app":sum(1 for c in all_data if c["category"]=="forest_app"),
    "opal":sum(1 for c in all_data if c["category"]=="opal"),
    "focus_community":sum(1 for c in all_data if c["category"]=="focus_community"),
    "complaints":sum(1 for c in all_data if c["is_complaint"])}
with open("/tmp/forest_data/totals.json","w") as f: json.dump(totals, f)
