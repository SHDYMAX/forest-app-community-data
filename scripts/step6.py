import json, requests, os
from datetime import date
from pathlib import Path

Path("/tmp/forest_data").mkdir(exist_ok=True)

with open("/tmp/forest_data/totals.json") as f: t = json.load(f)
with open("/tmp/forest_data/ai_summary.txt") as f: summary = f.read()

msg = f"""🌲 *Forest App Daily Community Report*
📅 {date.today()} | 今日新增 {t['new_today']} 則 | 累計 {t['total']} 則（Forest {t['forest_app']} / Opal {t['opal']} / Focus {t['focus_community']} / 投訴紀錄 {t['complaints']}）
━━━━━━━━━━━━━━━━━━━━━━━━━━

{summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━
_由 Forest App Community Intelligence Agent 自動生成_
_資料庫：github.com/SHDYMAX/forest-app-community-data_"""

r = requests.post(os.getenv("SLACK_WEBHOOK"), json={"text":msg})
print(f"Slack: {r.status_code}")
if r.status_code == 200: print("DONE — Report sent successfully")
