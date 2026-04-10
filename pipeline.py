import os, json, requests, base64, time, anthropic, re
from datetime import datetime, timezone, date, timedelta

GITHUB_TOKEN  = os.environ["GITHUB_TOKEN"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK"]
FIRECRAWL_KEY = os.environ["FIRECRAWL_API_KEY"]
REPO          = "SHDYMAX/forest-app-community-data"
GH_HEADERS    = {"Authorization": f"token {GITHUB_TOKEN}"}
FC_HEADERS    = {"Authorization": f"Bearer {FIRECRAWL_KEY}", "Content-Type": "application/json"}
COMPLAINT_KW  = ["bug","broken","crash","doesn't work","not working","glitch",
                  "issue","problem","refund","expensive","hate","annoying",
                  "disappointed","freeze","stuck","won't open","lost data","deleted"]
TODAY         = datetime.now(timezone.utc).strftime("%Y-%m-%d")
CUTOFF        = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")

# ── STEP 1：讀取歷史資料 ──────────────────────────────
print("=== STEP 1: Load existing data ===")
r = requests.get(f"https://api.github.com/repos/{REPO}/contents/comments.json", headers=GH_HEADERS)
file_data    = r.json()
file_sha     = file_data["sha"]
existing     = json.loads(base64.b64decode(file_data["content"]).decode())
existing_ids = {c["id"] for c in existing}
print(f"Loaded {len(existing)} existing entries")

# ── STEP 2：用 Firecrawl 搜尋（7 個精準 query）────────
print("=== STEP 2: Search Reddit via Firecrawl ===")

search_queries = [
    # Forest App（3 個 query，涵蓋一般討論、專屬版、負面聲音）
    ('"Forest App" site:reddit.com',                                        "forest_app"),
    ('site:reddit.com/r/forestapp',                                         "forest_app"),
    ('"Forest App" alternative OR subscription OR AI OR complaint site:reddit.com', "forest_app"),
    # 三個競品（各 1 個精準 query）
    ('"Opal" app screen time focus site:reddit.com',                        "opal"),
    ('"Study Bunny" app focus site:reddit.com',                             "study_bunny"),
    ('"Focus Friend" app site:reddit.com',                                  "focus_friend"),
    # Focus 社群需求
    ('body doubling accountability focus app site:reddit.com',              "focus_community"),
]

def extract_subreddit(url):
    m = re.search(r'reddit\.com/r/([^/]+)', url)
    return m.group(1) if m else ""

def extract_post_id(url):
    m = re.search(r'/comments/([a-z0-9]+)/', url)
    return m.group(1) if m else re.sub(r'[^a-z0-9]', '', url)[-10:]

all_results = []
for query, category in search_queries:
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v1/search",
            headers=FC_HEADERS,
            json={"query": query, "limit": 10},
            timeout=30)
        items = r.json().get("data", [])
        reddit_items = [i for i in items
                        if "reddit.com/r/" in i.get("url", "")
                        and "/comments/" in i.get("url", "")]
        all_results.extend([(i, category) for i in reddit_items])
        print(f"  [{category}] {len(reddit_items)} posts")
    except Exception as e:
        print(f"  Failed '{query[:40]}': {e}")
    time.sleep(1.5)

# ── STEP 3：解析、過濾、去重（不再單獨爬留言）────────
print("=== STEP 3: Parse + deduplicate ===")
new_entries = []

FILTERS = {
    "forest_app":     ["forest app","forestapp","forest","focus timer","plant tree","pomodoro"],
    "opal":           ["opal"],
    "study_bunny":    ["study bunny"],
    "focus_friend":   ["focus friend"],
    "focus_community":[], # 不過濾，靠 query 本身的精準度
}

for result, category in all_results:
    url   = result.get("url", "")
    title = result.get("title", "").replace(" - Reddit","").replace(" : "," ").strip()
    desc  = result.get("description", "")
    pid   = extract_post_id(url)

    if not pid or pid in existing_ids:
        continue

    text = (title + " " + desc).lower()
    keywords = FILTERS.get(category, [])
    if keywords and not any(k in text for k in keywords):
        continue

    flagged = [k for k in COMPLAINT_KW if k in text]
    new_entries.append({
        "id": pid, "type": "post", "date_collected": TODAY,
        "category": category, "subreddit": extract_subreddit(url),
        "title": title, "body": desc[:400],
        "author": "", "score": 0, "url": url,
        "is_complaint": bool(flagged), "complaint_keywords": flagged,
    })
    existing_ids.add(pid)

print(f"New entries: {len(new_entries)}")

# ── STEP 4：AI 摘要（Sonnet，只看最近 3 天）─────────
print("=== STEP 4: Generate AI summary ===")

recent       = [e for e in new_entries if e["date_collected"] >= CUTOFF]
forest       = [e for e in recent if e["category"] == "forest_app"]
opal         = [e for e in recent if e["category"] == "opal"]
study_bunny  = [e for e in recent if e["category"] == "study_bunny"]
focus_friend = [e for e in recent if e["category"] == "focus_friend"]
focus        = [e for e in recent if e["category"] == "focus_community"]
print(f"Recent 3d: forest={len(forest)}, opal={len(opal)}, study_bunny={len(study_bunny)}, focus_friend={len(focus_friend)}, focus={len(focus)}")

def fmt(entries):
    items = [f"[r/{e['subreddit']}] {e['title']}\n{e['body'][:250]}"
             for e in entries[:20]]
    return "\n\n---\n\n".join(items) if items else "（本期無資料）"

if not recent:
    summary = "本日 Reddit 無新增相關討論。"
else:
    prompt = f"""你是 Forest App 的產品策略顧問。以下是最近 3 天從 Reddit 收集到的用戶討論，包含 Forest App 本身以及三個競品（Opal、Study Bunny、Focus Friend）。

請產出一份結構清晰的每日情報報告，分為四個部分：

---

*📢 今日用戶在討論什麼*

用 3-5 個條列說明最近 Reddit 社群的主要討論主題。
格式：**主題名稱** — 討論內容一句話、情緒傾向（正面/負面/中性）、涉及幾則。
每個主題附用戶原話 1 句（英文保留，加引號）。
目標：讓產品團隊 30 秒內看懂社群狀態。

---

*⚔️ 競品雷達*

針對以下三個競品，各自分析：

**Opal App**
- 用戶在討論什麼？對它的評價如何？
- 與 Forest 相比，用戶覺得它哪裡更好或更差？
- 用戶原話 1 句（英文保留，加引號）
- So what / Now what：Forest 應該如何回應？

**Study Bunny**
- 用戶在討論什麼？對它的評價如何？
- 與 Forest 相比，用戶覺得它哪裡更好或更差？
- 用戶原話 1 句（英文保留，加引號）
- So what / Now what：Forest 應該如何回應？

**Focus Friend**
- 用戶在討論什麼？對它的評價如何？
- 與 Forest 相比，用戶覺得它哪裡更好或更差？
- 用戶原話 1 句（英文保留，加引號）
- So what / Now what：Forest 應該如何回應？

沒有被討論到的競品直接跳過。

---

*🚨 需要注意的事項*

3-5 個值得產品團隊關注的訊號，優先度由高到低：
**[HIGH/MED/LOW]** 標題
- 狀況：幾則討論、情緒強度？
- 用戶原話 1 句（英文保留，加引號）
- 若不處理，可能的後果？

---

*🧭 策略建議*

3 個具體策略行動：
**建議標題**
- 機會點 + 用戶原話 1 句（英文保留，加引號）
- So what：為什麼現在重要？
- Now what：第一步具體行動？
- 風險：可能的代價？

---

直接輸出報告，不要加前言或結語。

=== Forest App（{len(forest)}則）===
{fmt(forest)}

=== Opal App（{len(opal)}則）===
{fmt(opal)}

=== Study Bunny（{len(study_bunny)}則）===
{fmt(study_bunny)}

=== Focus Friend（{len(focus_friend)}則）===
{fmt(focus_friend)}

=== Focus 社群（{len(focus)}則）===
{fmt(focus)}"""

    try:
        client  = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg     = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=2500,
            messages=[{"role": "user", "content": prompt}])
        summary = msg.content[0].text
        print("Summary generated ✓")
    except Exception as e:
        print(f"Sonnet failed: {e}, using fallback")
        summary = (f"*今日新增討論（AI 摘要暫時無法使用）*\n\n"
                   f"Forest：{len(forest)} ／ Opal：{len(opal)} ／ "
                   f"Study Bunny：{len(study_bunny)} ／ Focus Friend：{len(focus_friend)} ／ "
                   f"Focus 社群：{len(focus)} 則\n\n"
                   + "\n".join(f"• r/{e['subreddit']}: {e['title'][:80]}"
                               for e in recent[:5]))

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
    "total":        len(all_data),
    "new_today":    len(new_entries),
    "forest_app":   sum(1 for c in all_data if c["category"] == "forest_app"),
    "opal":         sum(1 for c in all_data if c["category"] == "opal"),
    "study_bunny":  sum(1 for c in all_data if c["category"] == "study_bunny"),
    "focus_friend": sum(1 for c in all_data if c["category"] == "focus_friend"),
    "focus":        sum(1 for c in all_data if c["category"] == "focus_community"),
    "complaints":   sum(1 for c in all_data if c["is_complaint"]),
}

# ── STEP 6：發送 Slack 報告 ──────────────────────────
print("=== STEP 6: Send Slack report ===")
msg = f"""🌲 *Forest App Daily Community Report*
📅 {date.today()} | 今日新增 {totals['new_today']} 則 | 累計 {totals['total']} 則
Forest {totals['forest_app']} / Opal {totals['opal']} / Study Bunny {totals['study_bunny']} / Focus Friend {totals['focus_friend']} / 投訴 {totals['complaints']}
━━━━━━━━━━━━━━━━━━━━━━━━━━

{summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━
_由 Forest App Community Intelligence Agent 自動生成_
_資料庫：github.com/SHDYMAX/forest-app-community-data_"""

r = requests.post(SLACK_WEBHOOK, json={"text": msg})
print(f"Slack: {r.status_code}")
if r.status_code == 200:
    print("DONE — Report sent successfully ✓")
