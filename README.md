# daily-updates

日々のニュースを自動で収集・要約し、マークダウンファイルとして蓄積するリポジトリです。

## 仕組み

毎日 8:00 (JST) に GitHub Actions が以下を自動実行します。

1. **Issue 作成** — 「YYYY/MM/DD デイリーアップデート」という Issue を作成
2. **ブランチ作成** — `YYYYMMDD_update` ブランチを作成
3. **ニュース収集 & 記事生成** — 53の RSS/Atom フィード（技術系・ビジネス系・SNS）から最新ニュースを取得し、GitHub Models (Claude Opus) で記事を生成
4. **PR 作成 & マージ** — main ブランチへの PR を作成し、自動マージ

## 生成される記事の構成

| セクション | 内容 |
|---|---|
| 1. Azure アップデート情報 | Azure サービスの新機能・更新情報（5〜6個） |
| 2. ニュースで話題のテーマ | IT・テクノロジー関連の注目トピック（5〜6個） |
| 3. SNSで話題のテーマ | はてブ・Reddit 等で盛り上がっているトピック（5〜6個） |
| 4. ビジネスホットトピック | IT以外の世界情勢・経済・社会の注目ニュース（5〜6個） |

各トピックには **見出し**・**要約**・**影響**・**参考リンク** が含まれます。
読了目安は約8分（4000〜5000文字）です。

## セットアップ

### 必要な Secrets

**GitHub Models（推奨）を使う場合、追加の Secret は不要です。** ニュース取得は無料の RSS フィード、LLM は `GITHUB_TOKEN` 経由の GitHub Models を使用します。

独自の OpenAI / Azure OpenAI を使いたい場合のみ、リポジトリの **Settings → Secrets and variables → Actions** に以下を設定してください。

| Secret 名 | 必須 | 説明 |
|---|---|---|
| `OPENAI_API_KEY` | - | OpenAI API キー |
| `AZURE_OPENAI_ENDPOINT` | - | Azure OpenAI を使用する場合のエンドポイント URL |
| `AZURE_OPENAI_DEPLOYMENT` | - | Azure OpenAI のデプロイメント名（既定: `claude-opus-4`） |
| `AZURE_OPENAI_API_KEY` | - | Azure OpenAI 専用キー（未設定時は `OPENAI_API_KEY` を使用） |

### ニュースソース

以下の無料 RSS/Atom フィードからニュースを自動取得します（合計 53 ソース）。一部フィードが取得に失敗しても、他のソースで処理を続行します。

#### Azure（3）
| ソース | URL |
|---|---|
| Azure Release Communications | `https://www.microsoft.com/releasecommunications/api/v2/azure/rss` |
| Azure Blog | `https://azure.microsoft.com/en-us/blog/feed/` |
| Google News Azure | Google News RSS（Azure アップデート） |

#### 技術系（日本語 × 10）
| ソース | URL |
|---|---|
| ITmedia NEWS | `https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml` |
| GIGAZINE | `https://gigazine.net/news/rss_2.0/` |
| Publickey | `https://www.publickey1.jp/atom.xml` |
| INTERNET Watch | `https://internet.watch.impress.co.jp/data/rss/1.0/iw/feed.rdf` |
| Zenn トレンド | `https://zenn.dev/feed` |
| ITmedia テクノロジー | `https://rss.itmedia.co.jp/rss/2.0/news_technology.xml` |
| PC Watch | `https://pc.watch.impress.co.jp/data/rss/1.0/pcw/feed.rdf` |
| DevelopersIO | `https://dev.classmethod.jp/feed/` |
| 日経クロステック IT | `https://xtech.nikkei.com/rss/xtech-it.rdf` |
| Impress Watch | `https://www.watch.impress.co.jp/data/rss/1.0/ipw/feed.rdf` |

#### 技術系（英語 × 10）
| ソース | URL |
|---|---|
| TechCrunch | `https://techcrunch.com/feed/` |
| The Verge | `https://www.theverge.com/rss/index.xml` |
| Ars Technica | `https://feeds.arstechnica.com/arstechnica/index` |
| Hacker News (Best) | `https://hnrss.org/best` |
| MIT Technology Review | `https://www.technologyreview.com/feed/` |
| Wired | `https://www.wired.com/feed/rss` |
| The Register | `https://www.theregister.com/headlines.atom` |
| ZDNet | `https://www.zdnet.com/news/rss.xml` |
| Dev.to | `https://dev.to/feed` |
| Slashdot | `https://slashdot.org/index.rss` |

#### ビジネス系（日本語 × 10）
| ソース | URL |
|---|---|
| NHK ビジネス | `https://www.nhk.or.jp/rss/news/cat4.xml` |
| 東洋経済オンライン | `https://toyokeizai.net/list/feed/rss` |
| ITmedia エンタープライズ | `https://rss.itmedia.co.jp/rss/2.0/enterprise.xml` |
| Google News 経済 | Google News RSS（経済・ビジネス） |
| Google News IT企業 | Google News RSS（IT企業・スタートアップ） |
| Google News AI | Google News RSS（AI・人工知能） |
| Google News DX | Google News RSS（DX・デジタルトランスフォーメーション） |
| Google News スタートアップ | Google News RSS（スタートアップ・資金調達） |
| Google News 半導体 | Google News RSS（半導体・テクノロジー） |
| Google News サイバーセキュリティ | Google News RSS（サイバーセキュリティ・脆弱性） |

#### ビジネス系（英語 × 10）
| ソース | URL |
|---|---|
| BBC Business | `https://feeds.bbci.co.uk/news/business/rss.xml` |
| CNBC Tech | `https://search.cnbc.com/rs/...` |
| Reuters Business | Google News RSS (site:reuters.com) |
| Bloomberg Tech | Google News RSS (site:bloomberg.com) |
| Financial Times | Google News RSS (site:ft.com) |
| WSJ Tech | `https://feeds.a.dj.com/rss/RSSWSJD.xml` |
| Cloud Computing | Google News RSS (cloud computing) |
| AI Business | Google News RSS (AI business) |
| Startup Funding | Google News RSS (startup funding) |
| Semiconductor | Google News RSS (semiconductor) |

#### SNS / トレンド（10）
| ソース | URL |
|---|---|
| はてなブックマーク IT | `https://b.hatena.ne.jp/hotentry/it.rss` |
| Reddit Technology | `https://www.reddit.com/r/technology/.rss` |
| Reddit Programming | `https://www.reddit.com/r/programming/.rss` |
| X(Twitter) IT話題 (国内) | Google News RSS |
| X(Twitter) Tech Trends | Google News RSS |
| Reddit DevOps | `https://www.reddit.com/r/devops/.rss` |
| Reddit SysAdmin | `https://www.reddit.com/r/sysadmin/.rss` |
| Qiita トレンド | `https://qiita.com/popular-items/feed` |
| Reddit Artificial Intelligence | `https://www.reddit.com/r/artificial/.rss` |
| Reddit Cloud Computing | `https://www.reddit.com/r/cloudcomputing/.rss` |

### Actions 権限

リポジトリの **Settings → Actions → General → Workflow permissions** で以下を有効にしてください。

- **Read and write permissions**
- **Allow GitHub Actions to create and approve pull requests**

## 手動実行

GitHub Actions の **Actions** タブからワークフローを手動実行できます。

### デイリーアップデート
- `target_date` に `YYYYMMDD` 形式で日付を指定できます（省略時は当日 JST）。

### テクニカル雑談
- `target_date` に `YYYYMMDD` 形式で日付を指定できます（省略時は当日 JST）。
- `slot` で時間帯を選択できます（`am` / `pm`、省略時は現在時刻で自動判定）。

---

## テクニカル雑談

デイリーアップデートとは別に、**1日2回（3:00 / 15:00 JST）** SNS を中心とした IT 関連の話題を収集し、カジュアルなテクニカル雑談記事を自動生成します。

### 仕組み

1. **Issue 作成** — 「YYYY/MM/DD テクニカル雑談（午前/午後）」という Issue を作成
2. **ブランチ作成** — `YYYYMMDD_smallchat_am` または `YYYYMMDD_smallchat_pm` ブランチを作成
3. **ニュース収集 & 記事生成** — 40 の RSS フィード（SNS・テックブログ中心）から直近12時間のニュースを取得し、GitHub Models (Claude Opus) で記事を生成
4. **PR 作成 & マージ** — main ブランチへの PR を作成し、自動マージ

### 生成される記事の構成

| セクション | 内容 |
|---|---|
| 1. Microsoft | Microsoft 関連の最新話題（最大3つ） |
| 2. AI | AI・機械学習関連のトピック（最大3つ） |
| 3. Azure | Azure クラウド関連のトピック（最大3つ） |
| 4. クラウド | AWS / GCP / OCI 等 Azure以外のクラウドトピック（最大3つ） |
| 5. セキュリティ | サイバーセキュリティ関連のトピック（最大3つ） |

### ニュースソース（50 ソース）

#### Microsoft（10）
| ソース | URL |
|---|---|
| Reddit Microsoft | `https://www.reddit.com/r/microsoft/.rss` |
| Reddit Windows | `https://www.reddit.com/r/Windows11/.rss` |
| はてなブックマーク Microsoft | `https://b.hatena.ne.jp/search/tag?q=Microsoft&mode=rss` |
| X(Twitter) Microsoft話題 | Google News RSS |
| Google News Microsoft | Google News RSS |
| Reddit Surface | `https://www.reddit.com/r/Surface/.rss` |
| Publickey | `https://www.publickey1.jp/atom.xml` |
| Qiita Microsoft | `https://qiita.com/tags/microsoft/feed` |
| Google News Microsoft Japan | Google News RSS |
| Google News Windows | Google News RSS |

#### AI（10）
| ソース | URL |
|---|---|
| Reddit MachineLearning | `https://www.reddit.com/r/MachineLearning/.rss` |
| Reddit LocalLLaMA | `https://www.reddit.com/r/LocalLLaMA/.rss` |
| はてなブックマーク AI | `https://b.hatena.ne.jp/search/tag?q=AI&mode=rss` |
| X(Twitter) AI話題 | Google News RSS |
| Hacker News AI | `https://hnrss.org/best?q=AI+LLM` |
| Reddit Artificial | `https://www.reddit.com/r/artificial/.rss` |
| Reddit OpenAI | `https://www.reddit.com/r/OpenAI/.rss` |
| Qiita AI | `https://qiita.com/tags/ai/feed` |
| Zenn AI | `https://zenn.dev/topics/ai/feed` |
| Google News AI Business | Google News RSS |

#### Azure（10）
| ソース | URL |
|---|---|
| Azure Blog | `https://azure.microsoft.com/en-us/blog/feed/` |
| Azure Release Communications | `https://www.microsoft.com/releasecommunications/api/v2/azure/rss` |
| Reddit Azure | `https://www.reddit.com/r/azure/.rss` |
| X(Twitter) Azure話題 | Google News RSS |
| Google News Azure | Google News RSS |
| Azure SDK Blog | `https://devblogs.microsoft.com/azure-sdk/feed/` |
| Qiita Azure | `https://qiita.com/tags/azure/feed` |
| DevelopersIO | `https://dev.classmethod.jp/feed/` |
| Reddit CloudComputing | `https://www.reddit.com/r/cloudcomputing/.rss` |
| Google News Azure Japan | Google News RSS |

#### セキュリティ（10）
| ソース | URL |
|---|---|
| Reddit netsec | `https://www.reddit.com/r/netsec/.rss` |
| Reddit cybersecurity | `https://www.reddit.com/r/cybersecurity/.rss` |
| はてなブックマーク IT | `https://b.hatena.ne.jp/hotentry/it.rss` |
| X(Twitter) セキュリティ話題 | Google News RSS |
| Google News Cybersecurity | Google News RSS |
| Qiita セキュリティ | `https://qiita.com/tags/security/feed` |
| Reddit InfoSec | `https://www.reddit.com/r/InfoSecNews/.rss` |
| Google News サイバーセキュリティ JP | Google News RSS |
| INTERNET Watch | `https://internet.watch.impress.co.jp/data/rss/1.0/iw/feed.rdf` |
| Slashdot | `https://slashdot.org/index.rss` |

#### クラウド（AWS / GCP / OCI）（10）
| ソース | URL |
|---|---|
| Reddit AWS | `https://www.reddit.com/r/aws/.rss` |
| Reddit GCP | `https://www.reddit.com/r/googlecloud/.rss` |
| Reddit CloudComputing | `https://www.reddit.com/r/cloudcomputing/.rss` |
| Qiita AWS | `https://qiita.com/tags/aws/feed` |
| Qiita GCP | `https://qiita.com/tags/gcp/feed` |
| Google News AWS | Google News RSS |
| Google News GCP | Google News RSS |
| Google News OCI | Google News RSS |
| Google News クラウド JP | Google News RSS |
| DevelopersIO AWS | `https://dev.classmethod.jp/feed/` |