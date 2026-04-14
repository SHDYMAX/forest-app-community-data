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
                  "formats": ["markdown"], "onlyMainContent": True,
                  "maxAge": 0},  # 強制不用快取，確保抓到最新文章
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

# 先算出今日要進報告的文章（含資料庫裡已存的），再爬留言
# 必須在 new_entries 建完後、STEP 4 前做
all_data_so_far = existing + [{k: v for k, v in e.items() if k != "comments"}
                              for e in new_entries]
today_forest_ids = {e["id"] for e in all_data_so_far
                    if e["category"] == "forest_app" and e["date_collected"] == TODAY}

# 建一個 id -> entry 的 lookup，new_entries 優先（有 comments 欄位）
entry_lookup = {e["id"]: e for e in existing}
for e in new_entries:
    entry_lookup[e["id"]] = e

posts_to_scrape = [entry_lookup[pid] for pid in today_forest_ids
                   if not entry_lookup[pid].get("comments")]
# 確保有 comments 欄位
for e in entry_lookup.values():
    if "comments" not in e:
        e["comments"] = []

print(f"Scraping comments for {len(posts_to_scrape)} today's forest posts via Redlib...")

def extract_comments_from_redlib(md):
    """從 redlib markdown 提取留言，用 u/ 作為留言分界"""
    comments = []
    # 每個留言以 u/username 開頭
    blocks = re.split(r'\n\[u/', md)
    for block in blocks[1:]:  # 跳過第一段（原文）
        # 去掉用戶名那行
        lines = block.split('\n')
        # 找到留言內容（跳過用戶名、時間、投票數等短行）
        body_lines = []
        for line in lines[1:]:
            line = line.strip()
            if not line or line.startswith('>') or len(line) < 10:
                continue
            if re.match(r'^\d+$', line):  # 純數字（投票數）跳過
                continue
            if line.startswith('[u/') or line.startswith('http'):
                continue
            body_lines.append(line)
            if len('\n'.join(body_lines)) > 400:
                break
        text = ' '.join(body_lines).strip()
        if len(text) > 20:
            comments.append(text[:400])
    return comments

for post in posts_to_scrape:
    try:
        time.sleep(2)
        redlib_url = post["url"].replace("www.reddit.com", "redlib.catsarch.com")
        r = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers=FC_HEADERS,
            json={"url": redlib_url, "formats": ["markdown"], "onlyMainContent": True},
            timeout=30)
        md = r.json().get("data", {}).get("markdown", "")
        comments_raw = extract_comments_from_redlib(md)
        post["comments"] = comments_raw
        print(f"  {post['id']}: {len(comments_raw)} comments")
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
# 從 entry_lookup 撈（確保含有留言資料）
new_forest = [entry_lookup[pid] for pid in today_forest_ids]
new_others = [e for e in (list(entry_lookup.values()))
              if e["category"] != "forest_app" and e["date_collected"] == TODAY]
bg_forest  = [e for e in existing if e["category"] == "forest_app"
              and CUTOFF <= e["date_collected"] < TODAY][:10]

def fmt_post_for_report(e):
    """把單篇文章格式化給 AI 分析"""
    block = f"標題：<{e['url']}|{e['title']}>\n原文：{e['body'][:300]}"
    if e.get("comments"):
        comments_text = "\n".join([f"  [{i+1}] {c[:250]}" for i, c in enumerate(e["comments"][:8])])
        block += f"\n用戶留言：\n{comments_text}"
    else:
        block += "\n用戶留言：（無留言）"
    return block

# 若今日無新文章，往前找最近一天有資料的日期
if not new_forest:
    latest_date = max((e["date_collected"] for e in existing
                       if e["category"] == "forest_app"), default=None)
    if latest_date:
        new_forest = [e for e in existing if e["category"] == "forest_app"
                      and e["date_collected"] == latest_date]
        print(f"No new posts today, falling back to {latest_date} ({len(new_forest)} posts)")

if not new_forest and not new_others:
    summary = "近期 r/forestapp 無討論資料。"
else:
    # Part 1：今日 r/forestapp 每篇文章固定輸出
    forest_blocks = "\n\n".join([f"【{i+1}】{fmt_post_for_report(e)}"
                                 for i, e in enumerate(new_forest[:20])])

    # Part 2：其他 subreddit（競品相關）
    others_text = fmt_simple(new_others) if new_others else "（今日無）"

    prompt = f"""你是 Forest App 的產品策略顧問。以下是今日 r/forestapp 的所有文章，每篇都附有用戶留言。

格式規則：標題已是 Slack 可點擊連結格式，直接原樣輸出不要修改。

請對每一篇文章輸出以下固定格式（{len(new_forest)} 篇全部都要，不可跳過）：

【有留言的文章】
*標題連結*（直接複製原始 <URL|標題> 格式）
留言風向：[正面/負面/混合] — 用 1 句話描述整體氣氛
💬 不同視角：
  • 主流聲音：「最多人認同的觀點原句」
  • 不同聲音：「與主流相反或補充的觀點原句」（若有）
  • 值得注意：「少數但有趣的獨特聲音」（若有）

【無留言的文章】
*標題連結*（直接複製原始 <URL|標題> 格式）
留言風向：無留言
📝 原文重點：
  • [原文核心訴求或問題，1句]
  • [第二個重點，1句]
  • [第三個重點，1句]（依原文內容整理 2-4 個要點，讓讀者不看全文也能理解核心論點）

篇與篇之間用 --- 分隔。

最後加一個簡短的「⚔️ 今日競品提及」區塊，整理其他 subreddit 的競品動態（若無則略過）。

---
今日 r/forestapp 文章（{len(new_forest)} 篇）：

{forest_blocks}

---
其他 subreddit 競品動態：
{others_text}"""

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







