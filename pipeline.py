import os, json, requests, base64, time, subprocess
from datetime import datetime, timezone, date

# ── 設定（從環境變數讀取）──────────────────────────
GITHUB_TOKEN   = os.environ["GITHUB_TOKEN"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
SLACK_WEBHOOK  = os.environ["SLACK_WEBHOOK"]
REPO           = "SHDYMAX/forest-app-community-data"
GH_HEADERS     = {"Authorization": f"token {GITHUB_TOKEN}"}
UA             = {"User-Agent": "ForestApp-Report/1.0"}
COMPLAINT_KW   = ["bug","broken","crash","doesn't work","not working","glitch",
                   "issue","problem","refund","expensive","hate","annoying",
                   "disappointed","freeze","stuck","won't open","lost data","deleted"]
TODAY          = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ── STEP 1：從 GitHub 讀取歷史資料 ──────────────────
print("=== STEP 1: Load existing data ===")
r = requests.get(f"https://api.github.com/repos/{REPO}/contents/comments.json", headers=GH_HEADERS)
file_data  = r.json()
file_sha   = file_data["sha"]
existing   = json.loads(base64.b64decode(file_data["content"]).decode())
existing_ids = {c["id"] for c in existing}
print(f"Loaded {len(existing)} existing entries")

# ── STEP 2：搜尋 Reddit ──────────────────────────────
print("=== STEP 2: Search Reddit ===")
searches = [
    ("https://www.reddit.com/search.json?q=Forest+App+productivity&sort=new&limit=25&t=week",       "forest_app"),
    ("https://www.reddit.com/r/productivity/search.json?q=Forest+App&sort=new&limit=25&t=week&restrict_sr=1", "forest_app"),
    ("https://www.reddit.com/r/nosurf/search.json?q=Forest&sort=new&limit=25&t=week&restrict_sr=1", "forest_app"),
    ("https://www.reddit.com/r/ADHD/search.json?q=Forest+App&sort=new&limit=25&t=week&restrict_sr=1","forest_app"),
    ("https://www.reddit.com/r/getdisciplined/search.json?q=Forest+App&sort=new&limit=25&t=week&restrict_sr=1","forest_app"),
    ("https://www.reddit.com/search.json?q=Opal+app+screen+time&sort=new&limit=25&t=week",          "opal"),
    ("https://www.reddit.com/search.json?q=focus+friend+app&sort=new&limit=25&t=week",              "focus_community"),
    ("https://www.reddit.com/search.json?q=body+doubling+focus+app&sort=new&limit=25&t=week",       "focus_community"),
]

raw_results = []
for url, category in searches:
    try:
        res = requests.get(url, headers=UA, timeout=15)
        posts = res.json().get("data", {}).get("children", [])
        raw_results.append((posts, category))
        print(f"  {category}: {len(posts)} posts from {url.split('?')[0]}")
    except Exception as e:
        print(f"  Search failed: {e}")
    time.sleep(2)

# ── STEP 3：解析文章 + 抓留言 ───────────────────────
print("=== STEP 3: Parse posts + fetch comments ===")
new_entries = []

for posts, category in raw_results:
    for p in posts:
        post = p.get("data", {})
        pid  = post.get("id", "")
        if not pid or pid in existing_ids:
            continue

        title = post.get("title", "")
        body  = post.get("selftext", "")[:500]
        text  = (title + " " + body).lower()

        if category == "forest_app" and not any(k in text for k in
            ["forest app","forestapp","forest - stay","pomodoro","focus timer","plant tree","grow tree"]):
            continue
        if category == "opal" and not any(k in text for k in
            ["opal app","opal screen","opal block","opal focus"]):
            continue

        flagged = [k for k in COMPLAINT_KW if k in text]
        entry = {
            "id": pid, "type": "post", "date_collected": TODAY,
            "category": category, "subreddit": post.get("subreddit", ""),
            "title": title, "body": body[:400],
            "author": post.get("author", ""), "score": post.get("score", 0),
            "url": "https://reddit.com" + post.get("permalink", ""),
            "is_complaint": bool(flagged), "complaint_keywords": flagged,
        }
        new_entries.append(entry)
        existing_ids.add(pid)

        # 抓留言
        time.sleep(1.5)
        try:
            cr = requests.get(
                f"https://www.reddit.com{post.get('permalink','')}.json?limit=15&sort=top",
                headers=UA, timeout=15)
            comments = cr.json()[1].get("data", {}).get("children", [])
            for c in comments[:10]:
                cd   = c.get("data", {})
                cid  = cd.get("id", "")
                cbody = cd.get("body", "")
                if not cid or not cbody or cbody in ["[deleted]","[removed]"] or cid in existing_ids:
                    continue
                cflagged = [k for k in COMPLAINT_KW if k in cbody.lower()]
                new_entries.append({
                    "id": cid, "type": "comment", "date_collected": TODAY,
                    "category": category, "subreddit": post.get("subreddit", ""),
                    "title": f"[留言] {title}", "body": cbody[:400],
                    "author": cd.get("author", ""), "score": cd.get("score", 0),
                    "url": "https://reddit.com" + post.get("permalink", "") + cd.get("id", ""),
                    "is_complaint": bool(cflagged), "complaint_keywords": cflagged,
                    "parent_post_id": pid,
                })
                existing_ids.add(cid)
        except Exception as e:
            print(f"  Comment fetch error {pid}: {e}")

print(f"New entries: {len(new_entries)} "
      f"(posts:{sum(1 for e in new_entries if e['type']=='post')}, "
      f"comments:{sum(1 for e in new_entries if e['type']=='comment')})")

# ── STEP 4：AI 摘要（Sonnet）────────────────────────
print("=== STEP 4: Generate AI summary ===")
import anthropic

def fmt(entries):
    items = [f"[{e['type']}] r/{e['subreddit']} score:{e['score']}\n{e['title']}\n{e['body'][:300]}"
             for e in entries[:30]]
    return "\n\n---\n\n".join(items) if items else "（無資料）"

forest = [e for e in new_entries if e["category"] == "forest_app"]
opal   = [e for e in new_entries if e["category"] == "opal"]
focus  = [e for e in new_entries if e["category"] == "focus_community"]

if not new_entries:
    summary = "本日 Reddit 無新增相關討論。"
else:
    prompt = f"""你是 Forest App 的產品策略顧問。以下是今日從 Reddit 收集到的用戶討論（包含原始貼文與留言）。

請產出一份深度分析報告，包含以下四個部分。每個論點都必須附上最能代表該觀點的用戶原話 1-2 句（保留英文原文，加引號）：

*🗣️ 多元觀點整理*
從討論中整理出 3-5 個不同的用戶聲音或立場。每個觀點包含：
- 是哪類用戶、他們的核心主張、代表性原話 1-2 句（英文保留，加引號）
- 這個觀點與其他觀點的張力或衝突在哪

*⚔️ 競品與市場定位分析*
- 用戶如何區分 Forest 和競品？各自代表什麼？
- 有哪些用戶正在考慮離開 Forest？原因是什麼？
- Forest 目前的差異化優勢還站得住腳嗎？
每個論點附上用戶原話 1-2 句（英文保留，加引號）。

*🚨 風險識別*
**短期風險（需立即關注）**：2-3 個正在發酵的問題 + 用戶原話 1 句
**長期策略風險**：2-3 個趨勢性弱點 + 用戶原話 1 句

*🧭 下一步策略思考*
3 個策略方向，每個包含：
- 機會點 + 用戶原話 1 句（英文保留，加引號）
- 可能風險或代價
- 建議的第一步行動

沒有資料的分類直接跳過。報告可以長，重點是實質洞察加上用戶原聲。直接輸出報告內容，不要加前言。

=== Forest App 討論（{len(forest)}則）===
{fmt(forest)}
=== Opal 競品討論（{len(opal)}則）===
{fmt(opal)}
=== Focus 社群討論（{len(focus)}則）===
{fmt(focus)}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg    = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=2000,
            messages=[{"role": "user", "content": prompt}])
        summary = msg.content[0].text
        print("Summary generated ✓")
    except Exception as e:
        print(f"Sonnet failed: {e}, using fallback summary")
        summary = (f"*今日新增討論（AI 摘要暫時無法使用）*\n\n"
                   f"Forest App：{len(forest)} 則 ／ Opal：{len(opal)} 則 ／ Focus：{len(focus)} 則\n"
                   f"投訴相關：{sum(1 for e in new_entries if e['is_complaint'])} 則\n\n"
                   + "\n".join(f"• [{e['type']}] r/{e['subreddit']}: {e['title'][:80]}"
                               for e in new_entries[:5]))

# ── STEP 5：存回 GitHub ──────────────────────────────
print("=== STEP 5: Save to GitHub ===")
all_data    = existing + new_entries
content_b64 = base64.b64encode(
    json.dumps(all_data, ensure_ascii=False, indent=2).encode()).decode()
push = requests.put(
    f"https://api.github.com/repos/{REPO}/contents/comments.json",
    headers={**GH_HEADERS, "Content-Type": "application/json"},
    json={"message": f"data: +{len(new_entries)} entries ({TODAY})",
          "content": content_b64, "sha": file_sha})
print(f"GitHub push: {push.status_code}")

totals = {
    "total":          len(all_data),
    "new_today":      len(new_entries),
    "forest_app":     sum(1 for c in all_data if c["category"] == "forest_app"),
    "opal":           sum(1 for c in all_data if c["category"] == "opal"),
    "focus_community":sum(1 for c in all_data if c["category"] == "focus_community"),
    "complaints":     sum(1 for c in all_data if c["is_complaint"]),
}

# ── STEP 6：發送 Slack 報告 ──────────────────────────
print("=== STEP 6: Send Slack report ===")
msg = f"""🌲 *Forest App Daily Community Report*
📅 {date.today()} | 今日新增 {totals['new_today']} 則 | 累計 {totals['total']} 則（Forest {totals['forest_app']} / Opal {totals['opal']} / Focus {totals['focus_community']} / 投訴紀錄 {totals['complaints']}）
━━━━━━━━━━━━━━━━━━━━━━━━━━

{summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━
_由 Forest App Community Intelligence Agent 自動生成_
_資料庫：github.com/SHDYMAX/forest-app-community-data_"""

r = requests.post(SLACK_WEBHOOK, json={"text": msg})
print(f"Slack: {r.status_code}")
if r.status_code == 200:
    print("DONE — Report sent successfully ✓")
