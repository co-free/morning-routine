# 🌅 朝刊ダイジェスト（個人事業用）

毎朝7:00 JSTに、今日の予定＋ニュース3カテゴリをSlackへ自動配信。

## 配信内容

| セクション | 内容 |
|---|---|
| 📅 今日の予定 | Googleカレンダーから当日の予定を取得 |
| 📰 国内ニュース | NHK・朝日・毎日・読売・ITmedia等 |
| 🤖 AIニュース | TechCrunch・The Verge・VentureBeat・ITmedia AI+ |
| 🔭 理科トピック | 国立天文台・JAXA・アストロアーツ・NHK科学（該当日のみ表示） |

## GitHub Secrets の設定

| Secret名 | 内容 |
|---|---|
| `GROQ_API_KEY` | Groq APIキー |
| `SLACK_WEBHOOK_URL` | 個人事業用SlackのWebhook URL |
| `GCAL_API_KEY` | Google Calendar APIキー |
| `GCAL_IDS` | カレンダーIDをカンマ区切り（例: `primary,xxx@group.calendar.google.com`） |

## Googleカレンダー連携の設定手順

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクト作成
2. 「Google Calendar API」を有効化
3. 「認証情報」→「APIキー」を作成
4. APIキーをGitHub Secretsの `GCAL_API_KEY` に登録
5. カレンダーIDをカンマ区切りで `GCAL_IDS` に登録
   - 個人カレンダー: `primary`
   - 家族カレンダー: Googleカレンダー設定→「カレンダーの統合」で確認

## 配信時刻の変更

`.github/workflows/morning-routine.yml` のcronを変更：
- JST 6:00 → `0 21 * * *`
- JST 7:00 → `0 22 * * *`（デフォルト）
- JST 8:00 → `0 23 * * *`
