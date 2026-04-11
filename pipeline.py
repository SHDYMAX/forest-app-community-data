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
    ('"Forest App" site:reddit.com',                                                "forest_app"),
    ('site:reddit.com/r/forestapp',                                                 "forest_app"),
    ('"Forest App" alternative OR subscription OR AI OR complaint site:reddit.com', "forest_app"),
    ('"Opal" app screen time focus site:reddit.com',                                "opal"),
    ('"Study Bunny" app focus site:reddit.com',                                     "study_bunny"),
    ('"Focus Friend" app site:reddit.com',                                          "focus_friend"),
    ('body doubling accountability focus app site:reddit.com',                      "focus_community"),
]

def extract_subreddit(url):
    m = re.search(r'reddit\.com/r/([^/]+)', url)
    return m.group(1) if m else ""

def extract_post_id(url):
    m = re.search(r'/comments/([a-z0-9]+)/', url)
    return m.group(1) if m else re.sub(r'[^a-z0-9]', '', url)[-10:]

# ── STEP 2A：用 Firecrawl 爬 redlib（Reddit 替代前端）──
print("=== STEP 2A: Scrape r/forestapp via Redlib ===")
all_results = []
for listing in ["new", "hot"]:
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers=FC_HEADERS,
            json={"url": f"https://redlib.catsarch.com/r/forestapp/{listing}",
                  "formats": ["markdown"], "onlyMainContent": True},
            timeout=30)
        md = r.json().get("data", {}).get("markdown", "")
        # 按分隔線切段，每段是一篇文章
        sections = re.split(r'\n\* \* \*\n', md)
        count = 0
        for section in sections:
            m = re.search(
                r'\[([^\]]+)\]\((https://redlib\.catsarch\.com/r/forestapp/comments/([a-z0-9]+)/[^\)]*)\)',
                section)
            if not m:
                continue
            title, redlib_url, post_id = m.group(1), m.group(2), m.group(3)
            reddit_url = redlib_url.replace("redlib.catsarch.com", "www.reddit.com")
            # 提取正文（去掉連結標記後的文字）
            body = re.sub(r'\[[^\]]*\]\([^\)]*\)', '', section)
            body = re.sub(r'[#\*\n]+', ' ', body).strip()[:400]
            all_results.append((
                {"url": reddit_url, "title": title, "description": body,
                 "trusted_source": True},
                "forest_app"))
            count += 1
        print(f"  {listing}: {count} posts")
        time.sleep(2)
    except Exception as e:
        print(f"  Failed {listing}: {e}")

# ── STEP 2B：Firecrawl 搜尋（抓其他 subreddit）────────
print("=== STEP 2B: Search other subreddits via Firecrawl ===")
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
        for i in reddit_items:
            # r/forestapp 的文章不需要關鍵字驗證
            if "reddit.com/r/forestapp/" in i.get("url", ""):
                i["trusted_source"] = True
            all_results.append((i, category))
        print(f"  [{category}] {len(reddit_items)} posts")
    except Exception as e:
        print(f"  Failed '{query[:40]}': {e}")
    time.sleep(1.5)

# ── STEP 3：解析文章 + 爬熱門文章留言 ───────────────
print("=== STEP 3: Parse posts + scrape comments for top 5 ===")
new_entries = []

FILTERS = {
    "forest_app":     ["forest app","forestapp","forest","focus timer","plant tree","pomodoro"],
    "opal":           ["opal"],
    "study_bunny":    ["study bunny"],
    "focus_friend":   ["focus friend"],
    "focus_community":[],
}

for result, category in all_results:
    url   = result.get("url", "")
    title = result.get("title", "").replace(" - Reddit","").replace(" : "," ").strip()
    desc  = result.get("description", "")
    pid   = extract_post_id(url)

    if not pid or pid in existing_ids:
        continue

    text = (title + " " + desc).lower()
    if not result.get("trusted_source"):  # 直接從 subreddit 抓的不需過濾
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
        "comments": [],  # 留言會在下面填入
    })
    existing_ids.add(pid)

# 只爬前 5 篇新文章的留言（省 Firecrawl 額度）
posts_to_scrape = [e for e in new_entries if e["type"] == "post"][:5]
print(f"Scraping comments for {len(posts_to_scrape)} posts...")

for post in posts_to_scrape:
    try:
        time.sleep(2)
        r = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers=FC_HEADERS,
            json={"url": post["url"], "formats": ["markdown"], "onlyMainContent": True},
            timeout=30)
        md = r.json().get("data", {}).get("markdown", "")

        # 從 markdown 提取有意義的段落作為留言
        paragraphs = [p.strip() for p in re.split(r'\n{2,}', md)
                      if 30 < len(p.strip()) < 600
                      and not p.strip().startswith("#")
                      and not p.strip().startswith("http")
                      and not p.strip().startswith("![")]

        # 去掉前幾段（通常是原文，不是留言）
        comments_raw = paragraphs[3:18]
        post["comments"] = comments_raw
        print(f"  r/{post['subreddit']}: {len(comments_raw)} comment paragraphs")
    except Exception as e:
        print(f"  Scrape error {post['id']}: {e}")

print(f"New posts: {len(new_entries)}")

# ── STEP 4：AI 摘要（Sonnet，留言分群分析）──────────
print("=== STEP 4: Generate AI summary ===")

recent       = [e for e in (existing + new_entries) if e["date_collected"] >= CUTOFF]
forest       = [e for e in recent if e["category"] == "forest_app"]
opal         = [e for e in recent if e["category"] == "opal"]
study_bunny  = [e for e in recent if e["category"] == "study_bunny"]
focus_friend = [e for e in recent if e["category"] == "focus_friend"]
focus        = [e for e in recent if e["category"] == "focus_community"]

def fmt_with_comments(entries):
    """格式化文章 + 留言，讓 AI 能做分群分析（含 URL 供行內連結）"""
    items = []
    for e in entries[:15]:
        block = f"【文章】r/{e['subreddit']}\n標題：{e['title']}\nURL：{e['url']}\n摘要：{e['body'][:200]}"
        if e.get("comments"):
            comments_text = "\n".join([f"  - {c[:200]}" for c in e["comments"][:10]])
            block += f"\n留言：\n{comments_text}"
        items.append(block)
    return "\n\n═══\n\n".join(items) if items else "（本期無資料）"

def fmt_simple(entries):
    items = [f"[r/{e['subreddit']}] {e['title']}\nURL：{e['url']}\n{e['body'][:200]}"
             for e in entries[:10]]
    return "\n\n---\n\n".join(items) if items else "（本期無資料）"

    # 今日新增 vs 近期背景（用於 prompt 分層）
    new_forest   = [e for e in new_entries if e["category"] == "forest_app"]
    new_others   = [e for e in new_entries if e["category"] != "forest_app"]
    bg_forest    = [e for e in existing if e["category"] == "forest_app"
                    and e["date_collected"] >= CUTOFF][:10]

if not recent and not new_entries:
    summary = "過去 3 天 Reddit 無相關討論資料。"
else:
    prompt = f"""你是 Forest App 的產品策略顧問。

重要格式規則：每篇文章資料都附有 URL。當你在報告中提到某篇文章時，請用 Slack 連結格式 <URL|文章標題> 將標題變成可點擊連結。例如：<https://reddit.com/r/forestapp/comments/abc123/|Unpopular opinion: I LOVE the pause feature>

**核心原則：今日新增的文章全部都要出現在報告中，不能遺漏或取捨。** 舊的背景資料只是補充脈絡用。

請產出一份每日情報報告，分為五個部分：

---

*🆕 新功能用戶回饋*

專門報告用戶對 Forest 近期新功能（如暫停功能、新介面、新訂閱制等）的反應。即使是正面回饋也要納入。

格式：
**功能名稱**
- 用戶原話 1-2 句（英文保留，加引號，附 Slack 連結）
- 主流反應：正面 / 負面 / 混合？比例大概是？
- 值得注意的聲音（若有）

若本期無相關討論，寫「本期無新功能討論」。

---

*📢 今日用戶在討論什麼*

針對每個主要討論主題，用以下格式呈現（不要只寫一句話，要讓人感覺像看過討論串）：

**📌 主題名稱**

主流聲音（約 N 則類似留言）
> "最能代表這個聲音的用戶原話"
→ 這群人的核心訴求或情緒是什麼？用 1-2 句說明。

不同觀點（若有，N 則）
> "代表不同立場的原話"
→ 這個聲音和主流有什麼張力？

值得注意的獨特聲音（若有）
> "少數但有趣的觀點"
→ 為什麼值得注意？

討論走向：這個討論目前是在升溫、降溫、還是僵持？

每個主題之間空一行。目標：讓人不用去讀原討論串，就能理解討論的全貌與溫度。

---

*⚔️ 競品雷達*

針對有被討論到的競品（Opal、Study Bunny、Focus Friend），各自分析：

**競品名稱**
- 用戶為什麼提到它？在什麼情境下被拿來和 Forest 比較？
- 用戶原話 1 句（英文保留，加引號）
- So what：對 Forest 的意義？
- Now what：建議的具體回應？

沒有被討論到的競品跳過。

---

*🚨 需要注意的事項*

3-5 個訊號，優先度由高到低：
**[HIGH/MED/LOW]** 標題
- 狀況：幾則討論、情緒強度？
- 用戶原話 1 句（英文保留，加引號）
- 若不處理，可能的後果？

---

*🧭 策略建議*

3 個具體行動：
**建議標題**
- 機會點 + 用戶原話 1 句（英文保留，加引號）
- So what：為什麼現在重要？
- Now what：第一步具體行動？
- 風險：可能的代價？

---

直接輸出報告，不要加前言或結語。

━━━ 今日新抓到的 r/forestapp 文章（{len(new_forest)} 則，全部都要報）━━━
{fmt_with_comments(new_forest) if new_forest else "（今日無新增）"}

━━━ 今日其他 subreddit 新文章（{len(new_others)} 則）━━━
{fmt_simple(new_others) if new_others else "（今日無新增）"}

━━━ 近 3 天舊資料（背景參考，{len(bg_forest)} 則）━━━
{fmt_simple(bg_forest) if bg_forest else "（無）"}"""

    try:
        client  = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg     = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=3000,
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

# ── STEP 5：存回 GitHub（不存 comments 欄位，省空間）
print("=== STEP 5: Save to GitHub ===")

# 存檔前移除 comments 欄位（那是暫時的，不需要永久保存）
entries_to_save = [{k: v for k, v in e.items() if k != "comments"}
                   for e in new_entries]

all_data    = existing + entries_to_save
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





