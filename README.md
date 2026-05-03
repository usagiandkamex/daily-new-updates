# daily-updates

日々のニュースを自動で収集・要約し、マークダウンファイルとして蓄積するリポジトリです。

## 仕組み

毎日 7:30 (JST) に GitHub Actions が以下を自動実行します。

1. **Issue 作成** — 「YYYY/MM/DD デイリーアップデート」という Issue を作成
2. **ブランチ作成** — `YYYYMMDD_update` ブランチを作成
3. **ニュース収集 & 記事生成** — 89 の RSS/Atom フィード（技術系・ビジネス系・SNS・コミュニティ）から最新ニュースを取得し、GitHub Models (claude-opus-4-6 / gpt-4o / gpt-4o-mini) で記事を生成
4. **PR 作成 & マージ** — main ブランチへの PR を作成し、自動マージ

## 生成される記事の構成

| セクション | 内容 |
|---|---|
| 1. Azure アップデート情報 | Azure サービスの新機能・更新情報（5〜6個） |
| 2. ニュースで話題のテーマ | IT・テクノロジー関連の注目トピック（5〜6個） |
| 3. SNSで話題のテーマ | はてブ・Reddit 等で盛り上がっているトピック（5〜6個） |
| 4. ビジネスホットトピック | IT以外の世界情勢・経済・社会の注目ニュース（5〜6個） |
| 5. コミュニティイベント情報 | 東京・神奈川の勉強会・connpass イベント情報 |

各トピックには **見出し**・**要約**・**影響**・**リンク** が含まれます。
読了目安は約8分（4000〜5000文字）です。

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
| `CONNPASS_API_KEY` | - | connpass API v2 キー（未設定時は RSS フォールバック）。設定後に `python scripts/verify_connpass_api.py` で実 API の動作確認が可能。 |

### ニュースソース

以下の無料 RSS/Atom フィードからニュースを自動取得します（合計 89 ソース）。一部フィードが取得に失敗しても、他のソースで処理を続行します。

#### Azure（3）
Azure Updates は Microsoft 公式ソース（公式 Azure Updates / モデル更新情報 / 公式ブログの Update 関連情報）のみを使用します。他ベンダーや非公式ニュース（Google News 等）は除外しています。

| ソース | URL |
|---|---|
| Azure Release Communications | `https://www.microsoft.com/releasecommunications/api/v2/azure/rss` |
| Azure Updates | `https://azure.microsoft.com/en-us/updates/feed/` |
| Azure Blog | `https://azure.microsoft.com/en-us/blog/feed/` |

#### 技術系（日本語 × 18）
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
| Microsoft Japan Blog | `https://news.microsoft.com/ja-jp/feed/` |
| Google Japan Blog | `https://japan.googleblog.com/feeds/posts/default?alt=rss` |
| Cybozu Inside Out | `https://blog.cybozu.io/feed` |
| Mercari Engineering Blog | `https://engineering.mercari.com/blog/feed.xml` |
| LINE Engineering Blog | `https://engineering.linecorp.com/ja/feed.xml` |
| ZOZO Tech Blog | `https://techblog.zozo.com/feed` |
| Recruit Tech Blog | `https://techblog.recruit.co.jp/feed` |
| DeNA Engineering Blog | `https://engineering.dena.com/blog/index.xml` |

#### 技術系（英語 × 25）
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
| Google Blog | `https://blog.google/rss/` |
| Microsoft Blog | `https://blogs.microsoft.com/feed/` |
| Google Developers Blog | `https://developers.googleblog.com/feeds/posts/default?alt=rss` |
| Google Cloud Blog | `https://cloud.google.com/feeds/gcp-blog-atom.xml` |
| AWS News Blog | `https://aws.amazon.com/blogs/aws/feed/` |
| Google News - Wiz | Google News RSS（wiz.io security cloud） |
| Netflix Tech Blog | `https://netflixtechblog.com/feed` |
| Uber Engineering Blog | `https://eng.uber.com/feed/` |
| Meta Engineering Blog | `https://engineering.fb.com/feed/` |
| GitHub Blog | `https://github.blog/feed/` |
| Stripe Engineering Blog | `https://stripe.com/blog/engineering.rss` |
| Airbnb Engineering Blog | `https://medium.com/airbnb-engineering/feed` |
| Discord Engineering Blog | `https://discord.com/category/engineering/rss` |
| InfoQ | `https://feed.infoq.com/` |
| Google News - Anthropic Engineering | Google News RSS（`site:anthropic.com/engineering`） |

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
| CNBC Tech | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910` |
| Reuters Business | Google News RSS (site:reuters.com) |
| Bloomberg Tech | Google News RSS (site:bloomberg.com) |
| Financial Times | Google News RSS (site:ft.com) |
| WSJ Tech | `https://feeds.a.dj.com/rss/RSSWSJD.xml` |
| Cloud Computing | Google News RSS (cloud computing) |
| AI Business | Google News RSS (AI business) |
| Startup Funding | Google News RSS (startup funding) |
| Semiconductor | Google News RSS (semiconductor) |

#### SNS / トレンド（11）
| ソース | URL |
|---|---|
| はてなブックマーク IT | `https://b.hatena.ne.jp/hotentry/it.rss` |
| Reddit Technology | `https://www.reddit.com/r/technology/.rss` |
| Reddit Programming | `https://www.reddit.com/r/programming/.rss` |
| X(Twitter) テック話題 JP | Google News RSS |
| X(Twitter) 新機能・ニュース JP | Google News RSS |
| X(Twitter) Tech EN | Google News RSS |
| Reddit DevOps | `https://www.reddit.com/r/devops/.rss` |
| Reddit SysAdmin | `https://www.reddit.com/r/sysadmin/.rss` |
| Qiita トレンド | `https://qiita.com/popular-items/feed` |
| Reddit Artificial Intelligence | `https://www.reddit.com/r/artificial/.rss` |
| Reddit Cloud Computing | `https://www.reddit.com/r/cloudcomputing/.rss` |

#### コミュニティイベント（12）
| ソース | URL |
|---|---|
| Google News connpass IT 参加レポ | Google News RSS（connpass IT 勉強会 参加レポ） |
| Google News Azure User Group | Google News RSS（Azure User Group 勉強会） |
| Google News AWS JAWS 勉強会 | Google News RSS（JAWS AWS 勉強会 connpass） |
| Google News クラウド DevOps IT 勉強会 | Google News RSS（クラウド・DevOps 勉強会） |
| Google News AIOps FinOps コミュニティ | Google News RSS（AIOps / FinOps / MLOps コミュニティ） |
| Zenn connpass イベント | `https://zenn.dev/api/rss_feed/topic/connpass` |
| Zenn 勉強会 | `https://zenn.dev/api/rss_feed/topic/勉強会` |
| Zenn LT イベント | `https://zenn.dev/api/rss_feed/topic/lt` |
| Qiita connpass | `https://qiita.com/tags/connpass/feed` |
| Qiita 勉強会 | `https://qiita.com/tags/勉強会/feed` |
| はてなブックマーク IT 勉強会 | はてなブックマーク RSS（IT 勉強会 参加レポ） |
| Google News Zenn IT 勉強会イベント | Google News RSS（site:zenn.dev 勉強会 connpass） |

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
3. **ニュース収集 & 記事生成** — 96 の RSS フィード（SNS・テックブログ中心）から直近12時間のニュースを取得し、GitHub Models (claude-opus-4-6 / gpt-4o / gpt-4o-mini) で記事を生成
4. **PR 作成 & マージ** — main ブランチへの PR を作成し、自動マージ

### 生成される記事の構成

| セクション | 内容 |
|---|---|
| 1. Microsoft | Microsoft 関連の最新話題（5〜6個） |
| 2. AI | AI・機械学習関連のトピック（5〜6個） |
| 3. Azure | Azure クラウド関連のトピック（5〜6個） |
| 4. クラウド（AWS / GCP / OCI） | Azure 以外のクラウドサービスのトピック（5〜6個） |
| 5. セキュリティ | サイバーセキュリティ関連のトピック（5〜6個） |
| 6. IT運用・管理 | AIOps・ITSM・DevOps・SRE Agent などのトピック（5〜6個） |
| 7. 日本企業テックブログ | サイボウズ・メルカリ・LINE・ZOZO 等のテックブログ（5〜6個） |
| 8. 海外企業テックブログ | Netflix・Uber・Meta・GitHub 等の海外エンジニアリングブログ（5〜6個） |

### ニュースソース（103 ソース）

#### Microsoft（13）
| ソース | URL |
|---|---|
| Reddit Microsoft | `https://www.reddit.com/r/microsoft/.rss` |
| Reddit Windows | `https://www.reddit.com/r/Windows11/.rss` |
| はてなブックマーク Microsoft | `https://b.hatena.ne.jp/search/tag?q=Microsoft&mode=rss` |
| Google News Microsoft | Google News RSS |
| Publickey | `https://www.publickey1.jp/atom.xml` |
| Microsoft Blog | `https://blogs.microsoft.com/feed/` |
| Microsoft Japan Blog | `https://news.microsoft.com/ja-jp/feed/` |
| Microsoft Developer Blog | `https://devblogs.microsoft.com/feed/` |
| The Verge Microsoft | Google News RSS |
| Ars Technica Microsoft | Google News RSS |
| ZDNet Microsoft | Google News RSS |
| Google News Microsoft Copilot EN | Google News RSS |
| Google News Microsoft 新機能 JP | Google News RSS |

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

#### Azure（9）
Azure 関連情報は、Microsoft 公式ソース（Azure Blog・Azure Release Communications）に加え、Reddit・はてなブックマーク・Qiita・Zenn・Google News・Hacker News 等の SNS やコミュニティブログからも収集します。

| ソース | URL |
|---|---|
| Azure Blog | `https://azure.microsoft.com/en-us/blog/feed/` |
| Azure Release Communications | `https://www.microsoft.com/releasecommunications/api/v2/azure/rss` |
| Reddit Azure | `https://www.reddit.com/r/AZURE/.rss` |
| はてなブックマーク Azure | `https://b.hatena.ne.jp/search/tag?q=Azure&mode=rss` |
| Qiita Azure | `https://qiita.com/tags/azure/feed` |
| Zenn Azure | `https://zenn.dev/topics/azure/feed` |
| Google News Azure EN | Google News RSS |
| Google News Azure JP | Google News RSS |
| Hacker News Azure | `https://hnrss.org/best?q=Azure` |

#### セキュリティ（12）
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
| Google News Wiz Research | Google News RSS |
| Google News Project Zero | Google News RSS |

#### クラウド（AWS / GCP / OCI）（13）
| ソース | URL |
|---|---|
| Reddit AWS | `https://www.reddit.com/r/aws/.rss` |
| Reddit GCP | `https://www.reddit.com/r/googlecloud/.rss` |
| Reddit CloudComputing | `https://www.reddit.com/r/cloudcomputing/.rss` |
| Qiita AWS | `https://qiita.com/tags/aws/feed` |
| Google News AWS | Google News RSS |
| Google News GCP | Google News RSS |
| Google News OCI | Google News RSS |
| Google News クラウド JP | Google News RSS |
| DevelopersIO AWS | `https://dev.classmethod.jp/feed/` |
| Google Cloud Blog | `https://cloud.google.com/feeds/gcp-blog-atom.xml` |
| AWS News Blog | `https://aws.amazon.com/blogs/aws/feed/` |
| Google Blog | `https://blog.google/rss/` |
| Google News Google Cloud JP | Google News RSS |

#### IT運用・管理（25）
| ソース | URL |
|---|---|
| Microsoft Tech Community IT Ops | `https://techcommunity.microsoft.com/plugins/custom/microsoft/o365/custom-blog-rss?tid=8&board=ITOpsTalkBlog` |
| Reddit SysAdmin | `https://www.reddit.com/r/sysadmin/.rss` |
| Reddit DevOps | `https://www.reddit.com/r/devops/.rss` |
| Google News AIOps EN | Google News RSS |
| Google News AIOps JP | Google News RSS |
| Google News IT運用 | Google News RSS |
| Google News IT Operations | Google News RSS |
| Google News Azure Monitor AIOps | Google News RSS |
| Google News Microsoft Intune | Google News RSS |
| InfoQ DevOps | `https://feed.infoq.com/DevOps` |
| Reddit MSP | `https://www.reddit.com/r/msp/.rss` |
| Google News ITSM | Google News RSS |
| Google News Observability | Google News RSS |
| Google News SRE Agent EN | Google News RSS |
| Google News SRE Agent JP | Google News RSS |
| Datadog Engineering Blog | `https://www.datadoghq.com/blog/engineering/feed.xml` |
| The New Stack | `https://thenewstack.io/feed/` |
| Google News Datadog Dynatrace AIOps | Google News RSS |
| Google News ServiceNow AIOps | Google News RSS |
| Google News SRE overseas case study | Google News RSS |
| DevOps.com | `https://devops.com/feed/` |
| DZone DevOps | `https://dzone.com/devops-tutorials-tools-news/feed` |
| GitLab Blog | `https://about.gitlab.com/blog/feed.xml` |
| Google News DevOps JP | Google News RSS |
| Google News DevOps CI/CD EN | Google News RSS |

#### 日本企業テックブログ（9）
| ソース | URL |
|---|---|
| Cybozu Inside Out | `https://blog.cybozu.io/feed` |
| Mercari Engineering Blog | `https://engineering.mercari.com/blog/feed.xml` |
| LINE Engineering Blog | `https://engineering.linecorp.com/ja/feed.xml` |
| ZOZO Tech Blog | `https://techblog.zozo.com/feed` |
| Recruit Tech Blog | `https://techblog.recruit.co.jp/feed` |
| DeNA Engineering Blog | `https://engineering.dena.com/blog/index.xml` |
| Google Japan Blog | `https://japan.googleblog.com/feeds/posts/default?alt=rss` |
| Zenn サイボウズ | `https://zenn.dev/cybozu/feed` |
| Google News 企業テックブログ | Google News RSS |

#### 海外企業テックブログ（12）
| ソース | URL |
|---|---|
| Netflix Tech Blog | `https://netflixtechblog.com/feed` |
| Uber Engineering Blog | `https://eng.uber.com/feed/` |
| Meta Engineering Blog | `https://engineering.fb.com/feed/` |
| GitHub Blog | `https://github.blog/feed/` |
| Stripe Engineering Blog | `https://stripe.com/blog/engineering.rss` |
| Airbnb Engineering Blog | `https://medium.com/airbnb-engineering/feed` |
| Discord Engineering Blog | `https://discord.com/category/engineering/rss` |
| Dev.to | `https://dev.to/feed` |
| InfoQ | `https://feed.infoq.com/` |
| Hacker News (Best) | `https://hnrss.org/best` |
| Google News Engineering Blog EN | Google News RSS |
| Google News - Anthropic Engineering | Google News RSS（`site:anthropic.com/engineering`） |
