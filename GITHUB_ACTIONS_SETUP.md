# Forest App Community Intelligence Agent - GitHub Actions Setup

此自動化管道每天會自動蒐集 Reddit 上的 Forest App 討論，生成 AI 分析報告，並上傳至 GitHub。

## 📋 需要的設置步驟

### 1. **在 GitHub 上設置 Secrets**

進入妳的倉庫 `SHDYMAX/forest-app-community-data`：
- 點擊 **Settings** → **Secrets and variables** → **Actions**
- 新增以下 3 個 secrets：

| Secret 名稱 | 值 | 說明 |
|-----------|-----|------|
| `FOREST_GITHUB_TOKEN` | 妳的 GitHub token | GitHub token（寫入權限） |
| `ANTHROPIC_API_KEY` | 妳的 Anthropic API key | Anthropic API key |
| `SLACK_WEBHOOK` | 妳的 Slack webhook URL | Slack webhook URL |

### 2. **把檔案推送到 GitHub**

在妳的本地倉庫執行：

```bash
# 複製 workflow 和 scripts
mkdir -p .github/workflows scripts

# 複製檔案（妳已經有了）
cp /tmp/.github/workflows/forest-report.yml .github/workflows/
cp /tmp/scripts/*.py scripts/
cp /tmp/scripts/step2.sh scripts/

# 提交並推送
git add .github/ scripts/
git commit -m "Add GitHub Actions automation for Forest App report"
git push origin main
```

### 3. **啟用 GitHub Actions**

- 進入倉庫的 **Actions** 分頁
- 妳應該會看到 "Forest App Daily Report" workflow
- 點擊 **Enable workflow** 啟用

### 4. **測試自動化**

可以手動觸發 workflow：
- 進入 **Actions** → **Forest App Daily Report**
- 點擊 **Run workflow** → **Run workflow**

## 🕐 自動執行時間

目前設定為每天 **早上 8 點 UTC** 執行。

要修改時間，編輯 `.github/workflows/forest-report.yml` 的 `cron` 值：

```yaml
schedule:
  - cron: '0 8 * * *'  # 改成妳想要的時間
```

Cron 格式：`分 小時 日 月 星期幾` (UTC)

常見設定：
- `0 8 * * *` = 每天早上 8 點 UTC
- `0 0 * * *` = 每天午夜 UTC
- `0 12 * * *` = 每天中午 UTC

## ✅ 成功標誌

當自動化正常運行時，妳會看到：

1. ✅ GitHub Actions 執行完成（綠色勾勾）
2. ✅ `comments.json` 檔案更新
3. ✅ Slack 頻道收到新報告

## 🚨 troubleshooting

**如果 workflow 失敗：**

1. 檢查 GitHub Actions 的 Logs
2. 驗證所有 secrets 是否正確設置
3. 確認 API tokens 仍然有效且沒有過期

**如果 Slack 沒有收到報告：**
- 驗證 Slack webhook URL 是否正確
- 檢查 Slack workspace 設定是否允許 incoming webhooks

---

完成以上步驟後，妳的 Forest App 社群情報蒐集就會完全自動化了！🎉
