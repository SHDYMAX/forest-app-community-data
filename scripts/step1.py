import requests, json, base64, os
from pathlib import Path

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = "SHDYMAX/forest-app-community-data"
gh_headers = {"Authorization": f"token {GITHUB_TOKEN}"}

# Create temp directory for storing intermediate files
Path("/tmp/forest_data").mkdir(exist_ok=True)

r = requests.get(f"https://api.github.com/repos/{REPO}/contents/comments.json", headers=gh_headers)
if r.status_code == 404:
    existing = []
    file_sha = None
    print("File not found, starting fresh")
else:
    file_data = r.json()
    file_sha = file_data.get("sha")
    existing = json.loads(base64.b64decode(file_data["content"]).decode()) if "content" in file_data else []

existing_ids = {c["id"] for c in existing}
with open("/tmp/forest_data/file_sha.txt","w") as f: f.write(file_sha or "")
with open("/tmp/forest_data/existing_ids.json","w") as f: json.dump(list(existing_ids), f)
with open("/tmp/forest_data/existing_all.json","w") as f: json.dump(existing, f)
print(f"Loaded {len(existing)} existing entries")
