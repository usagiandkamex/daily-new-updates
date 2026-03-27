# daily-updates

日々のニュースを自動で収集・要約し、マークダウンファイルとして蓄積するリポジトリです。

## 仕組み

毎日 8:30 (JST) に GitHub Actions が以下を自動実行します。

1. **Issue 作成** — 「YYYY/MM/DD デイリーアップデート」という Issue を作成
2. **ブランチ作成** — `YYYYMMDD_update` ブランチを作成
3. **ニュース収集 & 記事生成** — 24の RSS/Atom フィード（技術系・ビジネス系・SNS）から最新ニュースを取得し、GitHub Models (GPT-4o) で記事を生成
4. **PR 作成 & マージ** — main ブランチへの PR を作成し、自動マージ

## 生成される記事の構成

| セクション | 内容 |
|---|---|
| 1. Azure アップデート情報 | Azure サービスの新機能・更新情報 |
| 2. ニュースで話題のテーマ | 技術系ニュースサイトで注目のトピック（最大3つ） |
| 3. SNSで話題のテーマ | はてブ・Reddit 等で盛り上がっているトピック（最大3つ） |
| 4. ビジネスホットトピック | ビジネス・経済に関する注目ニュース（最大3つ） |

各トピックには **見出し**・**要約**・**影響**・**参考リンク** が含まれます。

## セットアップ

### 必要な Secrets

**GitHub Models（推奨）を使う場合、追加の Secret は不要です。** ニュース取得は無料の RSS フィード、LLM は `GITHUB_TOKEN` 経由の GitHub Models を使用します。

独自の OpenAI / Azure OpenAI を使いたい場合のみ、リポジトリの **Settings → Secrets and variables → Actions** に以下を設定してください。

| Secret 名 | 必須 | 説明 |
|---|---|---|
| `OPENAI_API_KEY` | - | OpenAI API キー |
| `AZURE_OPENAI_ENDPOINT` | - | Azure OpenAI を使用する場合のエンドポイント URL |
| `AZURE_OPENAI_DEPLOYMENT` | - | Azure OpenAI のデプロイメント名（既定: `gpt-4o`） |
| `AZURE_OPENAI_API_KEY` | - | Azure OpenAI 専用キー（未設定時は `OPENAI_API_KEY` を使用） |

### ニュースソース

以下の無料 RSS/Atom フィードからニュースを自動取得します（合計 24 ソース）。一部フィードが取得に失敗しても、他のソースで処理を続行します。

#### Azure
| ソース | URL |
|---|---|
| Azure Updates | `https://azure.microsoft.com/ja-jp/updates/feed/` |

#### 技術系（日本語 × 5）
| ソース | URL |
|---|---|
| ITmedia NEWS | `https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml` |
| GIGAZINE | `https://gigazine.net/news/rss_2.0/` |
| Publickey | `https://www.publickey1.jp/atom.xml` |
| クラウド Watch | `https://cloud.watch.impress.co.jp/data/rss/1.0/cw/feed.rdf` |
| Zenn トレンド | `https://zenn.dev/feed` |

#### 技術系（英語 × 5）
| ソース | URL |
|---|---|
| TechCrunch | `https://techcrunch.com/feed/` |
| The Verge | `https://www.theverge.com/rss/index.xml` |
| Ars Technica | `https://feeds.arstechnica.com/arstechnica/index` |
| Hacker News (Best) | `https://hnrss.org/best` |
| MIT Technology Review | `https://www.technologyreview.com/feed/` |

#### ビジネス系（日本語 × 5）
| ソース | URL |
|---|---|
| NHK ビジネス | `https://www.nhk.or.jp/rss/news/cat4.xml` |
| 東洋経済オンライン | `https://toyokeizai.net/list/feed/rss` |
| ITmedia ビジネス | `https://rss.itmedia.co.jp/rss/2.0/business_articles.xml` |
| Google News 経済 | Google News RSS（経済・ビジネス） |
| Google News IT企業 | Google News RSS（IT企業・スタートアップ） |

#### ビジネス系（英語 × 5）
| ソース | URL |
|---|---|
| BBC Business | `https://feeds.bbci.co.uk/news/business/rss.xml` |
| CNBC Tech | `https://search.cnbc.com/rs/...` |
| Reuters Business | Google News RSS (site:reuters.com) |
| Bloomberg Tech | Google News RSS (site:bloomberg.com) |
| Financial Times | Google News RSS (site:ft.com) |

#### SNS / トレンド（3）
| ソース | URL |
|---|---|
| はてなブックマーク IT | `https://b.hatena.ne.jp/hotentry/it.rss` |
| Reddit Technology | `https://www.reddit.com/r/technology/.rss` |
| Reddit Programming | `https://www.reddit.com/r/programming/.rss` |

### Actions 権限

リポジトリの **Settings → Actions → General → Workflow permissions** で以下を有効にしてください。

- **Read and write permissions**
- **Allow GitHub Actions to create and approve pull requests**

## 手動実行

GitHub Actions の **Actions** タブから「デイリーアップデート」ワークフローを手動実行できます。
`target_date` に `YYYYMMDD` 形式で日付を指定できます（省略時は当日 JST）。