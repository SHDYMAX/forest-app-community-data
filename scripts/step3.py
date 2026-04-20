import json, requests, time
from datetime import datetime, timezone
from pathlib import Path

COMPLAINT_KW = ["bug","broken","crash","doesn't work","not working","glitch","issue","problem","refund","expensive","hate","annoying","disappointed","freeze","stuck","won't open","lost data","deleted","subscription"]
UA = {"User-Agent": "ForestApp-Report/1.0"}

Path("/tmp/forest_data").mkdir(exist_ok=True)

with open("/tmp/forest_data/existing_ids.json") as f:
    existing_ids = set(json.load(f))

file_configs = [
    ("/tmp/forest_data/s1.json","forest_app"),("/tmp/forest_data/s2.json","forest_app"),
    ("/tmp/forest_data/s3.json","forest_app"),("/tmp/forest_data/s4.json","forest_app"),
    ("/tmp/forest_data/s5.json","forest_app"),("/tmp/forest_data/s6.json","opal"),
    ("/tmp/forest_data/s7.json","focus_community"),("/tmp/forest_data/s8.json","focus_community"),
]

new_entries = []
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

for filepath, category in file_configs:
    try:
        with open(filepath) as f: data = json.load(f)
    except: continue
    for p in data.get("data",{}).get("children",[]):
        post = p.get("data",{})
        pid = post.get("id","")
        if not pid or pid in existing_ids: continue
        title = post.get("title","")
        body = post.get("selftext","")[:500]
        text = (title+" "+body).lower()
        if category=="forest_app" and not any(k in text for k in ["forest app","forestapp","forest - stay","pomodoro","focus timer","plant tree","grow tree"]): continue
        if category=="opal" and not any(k in text for k in ["opal app","opal screen","opal block","opal focus"]): continue
        flagged = [k for k in COMPLAINT_KW if k in text]
        entry = {"id":pid,"type":"post","date_collected":today,"category":category,
                 "subreddit":post.get("subreddit",""),"title":title,"body":body[:400],
                 "author":post.get("author",""),"score":post.get("score",0),
                 "url":"https://reddit.com"+post.get("permalink",""),
                 "is_complaint":bool(flagged),"complaint_keywords":flagged}
        new_entries.append(entry)
        existing_ids.add(pid)
        time.sleep(1.5)
        try:
            cr = requests.get(f"https://www.reddit.com{post.get('permalink','')}.json?limit=15&sort=top", headers=UA, timeout=10)
            comments = cr.json()[1].get("data",{}).get("children",[])
            for c in comments[:10]:
                cd = c.get("data",{})
                cid = cd.get("id","")
                cbody = cd.get("body","")
                if not cid or not cbody or cbody in ["[deleted]","[removed]"] or cid in existing_ids: continue
                cflagged = [k for k in COMPLAINT_KW if k in cbody.lower()]
                new_entries.append({"id":cid,"type":"comment","date_collected":today,"category":category,
                    "subreddit":post.get("subreddit",""),"title":f"[留言] {title}","body":cbody[:400],
                    "author":cd.get("author",""),"score":cd.get("score",0),
                    "url":"https://reddit.com"+post.get("permalink","")+cd.get("id",""),
                    "is_complaint":bool(cflagged),"complaint_keywords":cflagged,"parent_post_id":pid})
                existing_ids.add(cid)
        except Exception as e: print(f"Comment error {pid}: {e}")

print(f"New: {len(new_entries)} (posts:{sum(1 for e in new_entries if e['type']=='post')}, comments:{sum(1 for e in new_entries if e['type']=='comment')})")
with open("/tmp/forest_data/new_entries.json","w") as f: json.dump(new_entries, f, ensure_ascii=False, indent=2)
