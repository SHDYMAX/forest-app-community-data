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

# ── STEP 2：用 Firecrawl 搜尋 Reddit ────────────────
print("=== STEP 2: Search Reddit via Firecrawl ===")

search_queries = [
    ('"Forest App" focus timer site:reddit.com',         "forest_app"),
    ('"Forest App" productivity site:reddit.com',        "forest_app"),
    ('site:reddit.com/r/forestapp',                      "forest_app"),
    ('"Forest App" study site:reddit.com',               "forest_app"),
    ('"Forest App" alternative site:reddit.com',         "forest_app"),
    ('Opal app screen time blocker site:reddit.com',     "opal"),
    ('Opal app focus site:reddit.com',                   "opal"),
    ('focus friend app virtual study site:reddit.com',   "focus_community"),
    ('body doubling focus app site:reddit.com',          "focus_community"),
    ('Study Bunny app site:reddit.com',                  "focus_community"),
    ('Studychick app focus site:reddit.com',             "focus_community"),
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
        print(f"  [{category}] '{query[:50]}': {len(reddit_items)} posts")
    except Exception as e:
        print(f"  Failed: {e}")
    time.sleep(2)

# ── STEP 3：解析文章 + 抓留言 ───────────────────────
print("=== STEP 3: Parse + fetch comments ===")
new_entries = []

for result, category in all_results:
    url   = result.get("url", "")
    title = result.get("title", "").replace(" : ", " ").replace(" - Reddit", "").strip()
    desc  = result.get("description", "")
    pid   = extract_post_id(url)

    if not pid or pid in existing_ids:
        continue

    text = (title + " " + desc).lower()
    if category == "forest_app" and not any(k in text for k in
        ["forest app", "forestapp", "forest", "focus timer", "plant tree", "pomodoro"]):
        continue
    if category == "opal" and "opal" not in text:
        continue

    flagged = [k for k in COMPLAINT_KW if k in text]
    entry = {
        "id": pid, "type": "post", "date_collected": TODAY,
        "category": category, "subreddit": extract_subreddit(url),
        "title": title, "body": desc[:400], "author": "", "score": 0,
        "url": url, "is_complaint": bool(flagged), "complaint_keywords": flagged,
    }
    new_entries.append(entry)
    existing_ids.add(pid)

# 抓留言（前 8 篇）
for post in [e for e in new_entries if e["type"] == "post"][:8]:
    try:
        time.sleep(2)
        r = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers=FC_HEADERS,
            json={"url": post["url"], "formats": ["markdown"], "onlyMainContent": True},
            timeout=30)
        md = r.json().get("data", {}).get("markdown", "")
        paragraphs = [p.strip() for p in re.split(r'\n{2,}', md)
                      if 40 < len(p.strip()) < 500
                      and not p.strip().startswith("#")
                      and not p.strip().startswith("http")][:10]
        for i, para in enumerate(paragraphs):
            cid = f"{post['id']}_c{i}"
            if cid in existing_ids:
                continue
            cflagged = [k for k in COMPLAINT_KW if k in para.lower()]
            new_entries.append({
                "id": cid, "type": "comment", "date_collected": TODAY,
                "category": post["category"], "subreddit": post["subreddit"],
                "title": f"[留言] {post['title']}", "body": para[:400],
                "author": "", "score": 0, "url": post["url"],
                "is_complaint": bool(cflagged), "complaint_keywords": cflagged,
                "parent_post_id": post["id"],
            })
            existing_ids.add(cid)
        print(f"  Scraped {len(paragraphs)} comments: r/{post['subreddit']}")
    except Exception as e:
        print(f"  Scrape error {post['id']}: {e}")

print(f"New: {len(new_entries)} "
      f"(posts:{sum(1 for e in new_entries if e['type']=='post')}, "
      f"comments:{sum(1 for e in new_entries if e['type']=='comment')})")

# ── STEP 4：AI 摘要（Sonnet）────────────────────────
print("=== STEP 4: Generate AI summary ===")

# 只取最近 3 天的資料送給 AI 分析
recent = [e for e in new_entries if e["date_collected"] >= CUTOFF]
forest = [e for e in recent if e["category"] == "forest_app"]
opal   = [e for e in recent if e["category"] == "opal"]
focus  = [e for e in recent if e["category"] == "focus_community"]
print(f"Recent (3d): forest={len(forest)}, opal={len(opal)}, focus={len(focus)}")

def fmt(entries):
    items = [f"[{e['type']}] r/{e['subreddit']}\n{e['title']}\n{e['body'][:300]}"
             for e in entries[:30]]
    return "\n\n---\n\n".join(items) if items else "（無資料）"

if not recent:
    summary = "本日 Reddit 無新增相關討論。"
else:
    prompt = f"""你是 Forest App 的產品策略顧問。以下是最近 3 天從 Reddit 收集到的用戶討論。
請產出一份結構清晰的每日情報報告，分為四個部分：

---

*📢 今日用戶在討論什麼*

用 3-5 個條列，說明今天 Reddit 社群的主要討論主題。
每個條列格式：**主題名稱** — 一句話說明用戶在討論什麼、情緒傾向如何（正面/負面/中性）、大約幾則討論涉及這個主題。
附上每個主題最能代表的用戶原話 1 句（英文保留，加引號）。

目標：讓產品團隊在 30 秒內看懂今天社群的狀態。

---

*⚔️ 競品雷達*

根據討論內容，分析被提及的競品，用以下四個類別分類：

**直接競品**（同樣的用戶、同樣的需求）
列出被提及的直接競品，每個說明：
- 用戶為什麼考慮它？Forest 哪裡輸給它？
- 用戶原話 1 句（英文保留，加引號）
- So what：這對 Forest 意味著什麼？
- Now what：建議的回應動作是什麼？

**間接競品**（同樣的用戶、不同的解法）
例如：手機內建螢幕時間、番茄鐘 App 等

**替代品**（不同產品、達到同樣目的）
例如：紙本計時器、自製系統、習慣打卡 App

**未來潛在威脅**（目前不構成競爭，但值得追蹤）
例如：AI 整合的生產力工具、社群讀書 App

每個類別只列有被討論到的項目，沒有就跳過。

---

*🚨 需要注意的事項*

列出 3-5 個今日討論中值得產品團隊特別關注的訊號，優先度由高到低排列。
每項格式：
**[HIGH/MED/LOW]** 標題
- 狀況：發生了什麼？幾則討論涉及？用戶情緒強度？
- 用戶原話 1 句（英文保留，加引號）
- 如果不處理，可能的後果是什麼？

---

*🧭 策略建議*

根據以上三個部分，提出 3 個具體的策略行動建議。
每個建議格式：
**建議標題**
- 機會點：從哪個討論訊號看出來的？
- So what：為什麼現在重要？
- Now what：第一步具體行動是什麼（越具體越好）？
- 風險：如果採取這個行動，可能的代價或副作用？
- 用戶原話 1 句（英文保留，加引號）

---

沒有資料的分類直接跳過。直接輸出報告，不要加前言或結語。

=== Forest App 討論（{len(forest)}則，含文章與留言）===
{fmt(forest)}
=== 競品相關討論（{len(opal)}則）===
{fmt(opal)}
=== Focus 社群討論（{len(focus)}則）===
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
                   f"Forest App：{len(forest)} 則 ／ 競品：{len(opal)} 則 ／ Focus：{len(focus)} 則\n"
                   f"投訴相關：{sum(1 for e in recent if e['is_complaint'])} 則\n\n"
                   + "\n".join(f"• [{e['type']}] r/{e['subreddit']}: {e['title'][:80]}"
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
    "total":           len(all_data),
    "new_today":       len(new_entries),
    "forest_app":      sum(1 for c in all_data if c["category"] == "forest_app"),
    "opal":            sum(1 for c in all_data if c["category"] == "opal"),
    "focus_community": sum(1 for c in all_data if c["category"] == "focus_community"),
    "complaints":      sum(1 for c in all_data if c["is_complaint"]),
}

# ── STEP 6：發送 Slack 報告 ──────────────────────────
print("=== STEP 6: Send Slack report ===")
msg = f"""🌲 *Forest App Daily Community Report*
📅 {date.today()} | 今日新增 {totals['new_today']} 則 | 累計 {totals['total']} 則（Forest {totals['forest_app']} / 競品 {totals['opal']} / Focus {totals['focus_community']} / 投訴 {totals['complaints']}）
━━━━━━━━━━━━━━━━━━━━━━━━━━

{summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━
_由 Forest App Community Intelligence Agent 自動生成_
_資料庫：github.com/SHDYMAX/forest-app-community-data_"""

r = requests.post(SLACK_WEBHOOK, json={"text": msg})
print(f"Slack: {r.status_code}")
if r.status_code == 200:
    print("DONE — Report sent successfully ✓")
