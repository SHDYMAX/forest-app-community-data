import json, anthropic, os
from pathlib import Path

Path("/tmp/forest_data").mkdir(exist_ok=True)

with open("/tmp/forest_data/new_entries.json") as f:
    new_entries = json.load(f)

if not new_entries:
    with open("/tmp/forest_data/ai_summary.txt","w") as f: f.write("本日 Reddit 無新增相關討論。")
else:
    def fmt(entries):
        return "\n\n---\n\n".join([f"[{e['type']}] r/{e['subreddit']} score:{e['score']}\n{e['title']}\n{e['body'][:300]}" for e in entries[:30]]) or "（無資料）"

    forest = [e for e in new_entries if e["category"]=="forest_app"]
    opal = [e for e in new_entries if e["category"]=="opal"]
    focus = [e for e in new_entries if e["category"]=="focus_community"]

    prompt = f"""你是 Forest App 的產品策略顧問。以下是今日從 Reddit 收集到的用戶討論（包含原始貼文與留言）。

請產出一份深度分析報告，包含以下四個部分。每個論點都必須附上最能代表該觀點的用戶原話 1-2 句（保留英文原文，加引號）：

---

*🗣️ 多元觀點整理*

從討論中整理出 3-5 個不同的用戶聲音或立場。每個觀點包含：
- 是哪類用戶（e.g. ADHD 學生、自律型工作者、試圖戒手機的人）
- 他們的核心主張
- 代表性原話 1-2 句（英文保留，加引號）
- 這個觀點與其他觀點的張力或衝突在哪

---

*⚔️ 競品與市場定位分析*

- 用戶如何在心裡區分 Forest 和競品？各自代表什麼？
- 有哪些用戶正在考慮離開 Forest？原因是什麼？
- 競品哪些功能讓用戶覺得 Forest 不足？
- Forest 目前的差異化優勢還站得住腳嗎？

每個論點附上最能代表該觀點的用戶原話 1-2 句（英文保留，加引號）。

---

*🚨 風險識別*

**短期風險（需立即關注）**
列出 2-3 個正在發酵的問題，說明：問題是什麼、幾則討論提及、用戶情緒強度。
每項附上最能說明嚴重性的用戶原話 1 句（英文保留，加引號）。

**長期策略風險**
列出 2-3 個目前不緊迫但若不處理會影響市場地位的趨勢。
每項附上最能說明趨勢方向的用戶原話 1 句（英文保留，加引號）。

---

*🧭 下一步策略思考*

提出 3 個值得團隊討論的策略方向，每個包含：
- 機會點是什麼（從哪裡看出來的）＋讓你判斷這是機會點的用戶原話 1 句（英文保留，加引號）
- 如果做了，可能的風險或代價
- 建議的第一步行動

---

沒有資料的分類直接跳過。報告可以長，重點是實質洞察加上用戶原聲。直接輸出報告內容，不要加前言或結語。

=== Forest App 討論（{len(forest)}則）===
{fmt(forest)}

=== Opal 競品討論（{len(opal)}則）===
{fmt(opal)}

=== Focus 社群討論（{len(focus)}則）===
{fmt(focus)}"""

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    msg = client.messages.create(model="claude-sonnet-4-6", max_tokens=2000,
                                  messages=[{"role":"user","content":prompt}])
    summary = msg.content[0].text
    with open("/tmp/forest_data/ai_summary.txt","w") as f: f.write(summary)
    print("Summary done")
