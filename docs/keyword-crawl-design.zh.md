# 关键词爬取设计说明

## 目标

本文档记录将模型辅助关键词爬取逐步迁移到 `school-data-spider` 的设计边界。当前阶段只定义方案，不改变现有爬虫行为。

项目现状是 evidence-first 的确定性招生信息爬虫：从 seed URL 出发，有限发现页面，抓取 source，规则分类页面，规则抽取字段，最后做 evidence 校验和报告输出。后续引入模型时，模型应先用于“帮助发现更相关的候选 URL / 页面”，而不是直接生成招生事实。

## 参考项目启发

### ScrapeGraphAI

可借鉴的部分：

- 把复杂任务拆成小步骤：fetch、parse、generate、merge、retry。
- 用显式 pipeline 描述数据流，便于定位失败步骤。
- 记录模型执行信息，例如 token、成本、错误节点和最终 state。
- 多页面结果先独立处理，再集中合并。

不适合直接迁移的部分：

- 不应让 LLM 直接替代当前 evidence-first 抽取链路。
- 不应复制其字符串表达式式 state key 机制；当前项目更需要稳定、可测试的数据结构。
- 不应把 ScrapeGraphAI 整体作为核心依赖，否则会扩大可选依赖面并提高行为漂移风险。

### Crawl4AI

可借鉴的部分：

- 把运行参数集中到配置对象，而不是持续增加零散参数。
- 先用关键词、BM25、URL scorer 等廉价策略缩小候选范围，再进行昂贵处理。
- 深度爬取策略可以分为 BFS、best-first、stream/batch 等，但都受 `max_pages` 和 `max_depth` 限制。
- 抓取结果保留诊断信息，例如分数、来源、链接、缓存和失败原因。
- LLM 是可选 strategy，核心抓取流程可不依赖模型。

不适合直接迁移的部分：

- 当前项目不需要整体改成 async crawler。
- 当前项目不应直接引入 Crawl4AI 的重依赖、缓存数据库、代理池或反 bot 能力。
- 当前项目不应绕过 WAF、登录、验证码或申请系统。

## 设计原则

1. 默认行为不变。
2. 模型能力必须显式开启。
3. 模型只影响候选优先级或人工诊断，不能直接写入招生事实。
4. 所有新增能力必须受 `max_pages`、`max_depth`、domain policy 和官方来源边界限制。
5. 模型失败、超时、返回格式错误时，必须回退到当前规则策略。
6. 输出必须保留模型参与痕迹，便于人工复查。
7. 每一步实现都应足够小，方便用 `git diff` 单独审查。

## 推荐目标架构

推荐将关键词爬取分成三层：

### 1. Relevance Strategy

职责：对 URL、标题、链接文本、页面摘要进行相关性评分。

初始策略应只是现有 `score_url()` 的薄包装，确保结果不变。后续可以增加：

- `RuleBasedRelevanceStrategy`
- `KeywordPlanRelevanceStrategy`
- `BM25LikeRelevanceStrategy`
- `LLMExpandedKeywordStrategy`

该层只返回分数、命中的关键词、负向信号和简短理由，不抓取页面，不抽取招生字段。

### 2. Keyword Plan

职责：把用户目标转成可审查的关键词计划。

建议字段：

```json
{
  "query": "本科 国际申请 英语要求 学费 奖学金",
  "positive_keywords": ["undergraduate", "admissions", "international", "IELTS"],
  "negative_keywords": ["postgraduate", "alumni", "news"],
  "url_hints": ["/admissions", "/undergraduate", "/fees"],
  "source": "default|user|llm",
  "warnings": []
}
```

模型可以在未来帮助生成这个计划，但计划本身必须先落地为普通结构化数据，再交给规则 scorer 使用。

### 3. Discovery Policy

职责：决定候选 URL 的遍历顺序。

第一阶段继续使用当前 BFS。后续可以新增可选 best-first：

- BFS：行为稳定，适合作为默认。
- Best-first：高相关 URL 优先抓，适合 `max_pages` 较小但站点很大的场景。

无论使用哪种策略，都不能突破 domain policy 和页面数量限制。

## 渐进式迁移步骤

### Step 0：设计文档

只新增本文档，不改运行时代码。

验收标准：

- 没有源码行为变更。
- `git diff` 只包含文档新增。

### Step 1：抽出默认相关性接口

新增 `crawler/relevance.py`，把当前 `score_url()` 包成默认 strategy。

预期改动：

- 新增相关性 dataclass / protocol。
- `discover()` 仍默认使用现有评分逻辑。
- 添加测试证明默认 discovery 输出不变。

风险：低。目标是结构调整，不改变行为。

### Step 2：增加发现诊断

在 `run.config` 中记录每个 source 的 discovery score、匹配信号和 strategy 名称。

风险：低到中。输出 JSON 会新增诊断字段，但招生事实不变。

### Step 3：支持用户关键词计划

增加可选 CLI / config 输入，例如 `--keyword-query` 或 batch config 字段。默认不启用。

风险：中。需要明确 batch 配置、报告输出和测试。

### Step 4：增加非模型 BM25-like scorer

先实现本地、确定性的 BM25-like 或 token overlap scorer，用标题、URL、链接文本、页面片段排序候选。

风险：中。启用后会改变抓取顺序，应保持 opt-in。

### Step 5：增加模型关键词扩展

模型只根据用户目标生成 Keyword Plan。模型输出必须做 JSON schema 校验，失败则回退到规则关键词。

风险：中到高。涉及凭据、超时、费用、错误处理和可复现性。必须保持 opt-in，并且核心测试不能依赖网络或真实模型。

### Step 6：低置信度页面分类辅助

仅当规则分类低置信度时，模型可给出候选分类和理由。初期只记录到 diagnostics，不覆盖现有 `PageCategory`。

风险：中到高。不能让模型分类直接触发字段抽取，除非后续单独批准。

## 不建议做的事

- 不要一次性替换 `discover()`。
- 不要把 ScrapeGraphAI 或 Crawl4AI 的代码复制进项目。
- 不要把 LLM 输出直接写入 `AdmissionsData`。
- 不要为了关键词爬取绕过当前官方域名限制。
- 不要把 optional dependency 变成核心依赖。
- 不要删除当前半使用接口，例如 `CrawlConfig`、`parse_sitemap_urls()` 或 optional stubs，除非单独确认。

## 后续首次实现建议

如果开始 Step 1，建议只修改：

- `university_admissions_crawler/crawler/relevance.py`
- `university_admissions_crawler/crawler/discovery.py`
- `tests/test_relevance.py` 或 `tests/test_discovery.py`

不建议第一步修改：

- `cli.py`
- `pipeline/run_university_scan.py`
- `extractor/llm_provider.py`
- `pyproject.toml`

这样可以先建立扩展点，同时最大限度降低行为变化风险。
