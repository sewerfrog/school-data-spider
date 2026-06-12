# 关键词爬取设计说明

## 目标

本文档记录将模型辅助关键词爬取逐步迁移到 `school-data-spider` 的设计边界。当前分支已按渐进式方案完成 Step 0 到 Step 5 的低风险部分：默认爬虫行为保持不变，关键词计划、BM25-like scorer 和 mock LLM keyword plan 均为显式 opt-in。

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

当前实现状态：

- 已新增 `BM25LikeRelevanceStrategy`，以现有 `score_url()` 为基线，再叠加 keyword plan 的正向关键词、负向关键词和 URL hint 命中分。
- 已新增 CLI 参数 `--relevance-strategy rule-based|bm25-like`，默认值为 `rule-based`。
- `bm25-like` 必须和 `--keyword-query` 一起使用；否则 CLI 报错退出，避免无关键词计划时改变 discovery 行为。
- 该 scorer 仍受 `max_pages`、`max_depth`、domain policy 和 `should_follow()` 阈值约束。
- 当前没有引入模型、网络依赖或第三方检索库。

### Step 5：增加模型关键词扩展

模型只根据用户目标生成 Keyword Plan。模型输出必须做 JSON schema 校验，失败则回退到规则关键词。

风险：中到高。涉及凭据、超时、费用、错误处理和可复现性。必须保持 opt-in，并且核心测试不能依赖网络或真实模型。

当前前置状态：

- 已定义 `KEYWORD_PLAN_OUTPUT_SCHEMA`，用于约束未来模型输出的字段、长度、数组大小和 source 枚举。
- 已新增 `keyword_plan_from_payload()`，用于把结构化 payload 转成 `KeywordPlan`，并拒绝额外字段、超长字段和错误类型。
- 已接入 `MockKeywordPlanProvider`，用于验证模型关键词计划链路，不访问真实模型 API。
- CLI 仅允许 `--enable-llm --llm-provider mock --keyword-query ...` 生成 reviewable `KeywordPlan`。
- 真实 provider 仍处于 guarded 状态；`openai`、`anthropic`、`gemini` 等不会被调用。
- 已在 `run.config["llm_keyword_plan"]` 记录 provider、schema、fallback、elapsed_ms、warnings 和错误诊断。

### Step 6：低置信度页面分类辅助

仅当规则分类低置信度时，模型可给出候选分类和理由。初期只记录到 diagnostics，不覆盖现有 `PageCategory`。

风险：中到高。不能让模型分类直接触发字段抽取，除非后续单独批准。

### Step 6 输出复盘和下一步计划

对 `outputs/hku-llm-keyword-test` 和 `outputs/hku-live-step6` 的 HKU 结果做对比后，当前判断是：Step 6 本身还没有优化最终招生事实数据。

对比结果：

- `hku-llm-keyword-test` 抓到 8 个 source，`hku-live-step6` 抓到 40 个 source。
- 两次输出的 evidence item 都是 6 条。
- 两次 coverage 都是 4/9，缺失字段相同：`undergraduate_application_entry`、`application_periods`、`english_requirements`、`accepted_qualifications`、`required_documents`。
- 两次最终 facts 相同：programmes、fees、scholarships、contacts 没有新增有效字段。
- `hku-live-step6` 多抓到的 source 主要是更多本科项目页、JUPAS 页面、PDF、CSS、favicon 和多语言页面；其中不少没有转化成 evidence。
- `hku-live-step6` 的 warnings 更多，新增了 live PDF 未启用 parser、application portal / challenge 诊断以及非事实资源相关噪音。
- 两次 `result.json` 都没有 `run.config["classification_assist"]`，说明该 HKU 输出里 Step 6 分类辅助没有实际参与，或者没有触发低置信度分类辅助条件。

原因判断：

- Step 6 当前设计是 safety-first diagnostics：模型候选分类只能记录，不能覆盖规则 `PageCategory`，也不能直接触发字段抽取。因此它本来就不会直接改变最终 admissions facts。
- `hku-live-step6` 的 source 增量主要来自运行参数扩大，例如 `max_pages=40`、`max_depth=3`，不是分类辅助带来的字段质量提升。
- 当前 HKU 结果的主要瓶颈不在低置信度分类，而在 source 过滤和 extractor 转化能力：抓到了更多页面，但核心缺失字段仍没有被抽成 evidence-backed facts。
- 现有规则分类仍会把部分 PDF、CSS、favicon、privacy/legal 页面打成 admissions 相关页面，说明 discovery / source filtering 和分类噪音控制还需要加强。

基于这个复盘，Step 6 后续不应马上升级为“模型覆盖分类”。更稳妥的路线是把它作为失败定位工具，用 diagnostics 反向改进规则分类、source 过滤和字段抽取。

新的优化计划：

1. 让 Step 6 diagnostics 在 live 结果中可见

   - 重新跑 HKU，并显式开启 `--enable-llm --llm-provider mock --enable-classification-assist`。
   - 确认 `run.config["classification_assist"]` 是否出现，以及哪些 URL 被判为低置信度。
   - 在 Markdown report 的 diagnostics 区域增加 classification assist 摘要，但继续保持在 facts 之前，不进入 admissions facts。
   - 评估当前低置信度阈值是否过窄；如果 HKU 低质量 source 多数是 score=2，需要单独讨论是否把 score=2 纳入 diagnostics，而不是直接改变抽取行为。

2. 用 classification assist 诊断改进规则分类

   - 汇总规则分类和辅助候选分类不一致的页面，人工审查后再修改规则。
   - 优先处理 CSS、favicon、privacy PDF、GDPR PDF 等明显非招生事实资源，避免被分类为 `undergraduate_admissions`。
   - 对 `contact-us`、JUPAS、overview、international qualifications 等 HKU 页面补更细的分类信号。
   - 保留 “assistant candidate applied=false” 的边界，直到有单独评估证明覆盖规则分类不会扩大误抽取风险。

3. 提升 source filtering 和 discovery 噪音控制

   - 在 discovery 或 fetch 后过滤 `.css`、`.ico`、隐私政策、GDPR notice、cookie/legal 页面等低价值 source。
   - 对 PDF URL 做更细的 admissions / privacy / score-calculator / expected-score 分类，不把所有 admissions 域名下 PDF 都当作可抽取事实来源。
   - 对多语言重复页面和同一 programme listing 的重复入口做 canonical 或去重策略。
   - 继续保留 domain policy、`max_pages`、`max_depth` 和 opt-in scorer 边界。

4. 把“抓到更多页面”转化成“更高 coverage”

   - 增加 per-source extraction diagnostics：页面分类后尝试了哪些 extractor、为什么没有抽出字段。
   - 对 HKU 缺失字段建立专项抽取任务：application periods、English requirements、accepted qualifications、required documents、undergraduate application entry。
   - 针对 `international-qualifications`、`apply/overview`、JUPAS 页面和相关 PDF 分别分析原文结构，再补 fixture-backed extractor 测试。
   - 对 live PDF 结果单独评估 `--enable-pdf`，确认 JUPAS PDF 是否能补申请时间、资格或材料要求。

5. 建立固定评估集

   - 固定 HKU、NTU、PolyU 的 saved-source 或 live rerun 样例，记录每次变更前后的 source 数、无效 source 比例、evidence 数、coverage、warnings 和字段准确性。
   - 不再用 source 数量作为主要成功指标；主要看 core field coverage、evidence 质量和 warning 噪音是否改善。
   - 对 keyword plan、BM25-like、classification assist 分别做 ablation 对比，避免把参数扩大带来的抓取数量变化误判为模型辅助效果。

## 当前实现复盘

当前分支累计修改覆盖 Step 2 到 Step 5 的低风险部分，涉及如下文件：

- `university_admissions_crawler/crawler/relevance.py`
- `university_admissions_crawler/crawler/discovery.py`
- `university_admissions_crawler/pipeline/run_university_scan.py`
- `university_admissions_crawler/cli.py`
- `university_admissions_crawler/config_loader.py`
- `university_admissions_crawler/pipeline/batch.py`
- `university_admissions_crawler/reports/render_report.py`
- `university_admissions_crawler/extractor/llm_provider.py`
- `tests/test_discovery.py`
- `tests/test_pipeline.py`
- `tests/test_report_cli.py`
- `tests/test_relevance.py`
- `docs/keyword-crawl-design.zh.md`

### 已落地能力

1. 发现诊断

   `run.config["source_strategy"]` 中每个已处理 source 现在会记录：

   - `discovery_score`
   - `discovery_signals`
   - `relevance_strategy`

   这些字段只用于诊断，不参与字段抽取、页面分类或招生事实写入。

2. 用户关键词计划

   CLI 增加 `--keyword-query`。传入后会生成可审查的 `KeywordPlan`，并写入 `run.config["keyword_plan"]`：

   - `query`
   - `positive_keywords`
   - `negative_keywords`
   - `url_hints`
   - `source`
   - `warnings`

   默认不传 `--keyword-query` 时，不输出 `keyword_plan`，也不改变 scorer。

3. 非模型 BM25-like scorer

   CLI 增加 `--relevance-strategy`：

   - 默认 `rule-based`：继续使用既有规则评分。
   - 显式 `bm25-like`：使用 keyword plan 的 token/url hint 命中分辅助排序。

   `bm25-like` 需要 `--keyword-query`，否则直接报错。

4. batch config opt-in keyword plan

   batch config 现在可以可选配置：

   - `keyword_query`
   - `relevance_strategy`

   默认不配置时仍使用 `rule_based`。配置 `bm25-like` 时仍要求存在 `keyword_query`。

5. strategy factory

   已新增统一的 strategy 构造入口：

   - `build_relevance_strategy()`
   - `keyword_plan_from_payload()`
   - `KEYWORD_PLAN_OUTPUT_SCHEMA`

   CLI 和 batch 共用同一套 keyword query / strategy 校验逻辑，避免两边分叉。

6. Markdown report diagnostics

   报告现在会在 facts 之前展示诊断型 keyword 信息：

   - `Keyword Plan`
   - `LLM Keyword Plan Diagnostics`

   这些内容只属于运行诊断，不进入 admissions facts。

7. mock LLM keyword plan

   已在 `llm_provider.py` 中新增 `MockKeywordPlanProvider` 和 `generate_keyword_plan_with_fallback()`。该链路只输出 `KeywordPlan`，并记录 `run.config["llm_keyword_plan"]` 诊断。当前不会调用真实模型 API。

### 行为边界

- 默认 CLI 参数、fixture scan、live HTTP scan 仍使用 `rule_based`。
- `--keyword-query` 单独使用只记录计划，不改变 discovery 排序。
- 只有同时传入 `--keyword-query` 和 `--relevance-strategy bm25-like` 时，候选链接排序和 follow 判断才会使用新 scorer。
- 只有同时传入 `--enable-llm --llm-provider mock --keyword-query ...` 时，才会走 mock LLM keyword plan 生成链路。
- `openai`、`anthropic`、`gemini` 等真实 provider 仍被 CLI 拒绝，不会调用网络模型。
- 新增诊断字段会改变输出 JSON 的形状，但不改变招生事实字段的含义。
- 当前没有删除、移动文件；batch config 只增加可选字段。

### 验证结果

Step 5 低风险部分完成后已运行：

```bash
.venv314/bin/python -m pytest -q tests/test_relevance.py tests/test_report_cli.py tests/test_pdf_llm_incremental.py
.venv314/bin/python -m compileall -q university_admissions_crawler tests
.venv314/bin/python -m pytest -q
git diff --check
```

结果：`101 passed`。

## 风险和后续待改点

### 已发现风险

1. `run.config` 输出结构继续变宽

   Step 2 增加了 source-level discovery 诊断字段，Step 3 增加了可选 `keyword_plan`，Step 4 增加了 strategy 名称，Step 5 增加了可选 `llm_keyword_plan`。下游如果对 JSON schema 做严格字段校验，需要同步接受这些诊断字段。

2. `bm25-like` 会改变抓取顺序

   该行为是预期能力，但会影响 `max_pages` 较小时最终抓到的页面集合。因此必须继续保持 opt-in，不应让 `--keyword-query` 自动切换 scorer。

3. 当前 keyword plan 解析较简单

   `keyword_plan_from_query()` 目前只是按空白、逗号、分号、竖线和斜线拆词，并做简单 URL hint 映射。它适合作为可审查结构，不适合作为最终语义理解方案。

4. BM25-like 不是完整 BM25

   当前实现更接近 deterministic token overlap 加权，而不是带文档频率、长度归一化和语料统计的完整 BM25。命名中的 `Like` 必须保留，避免误解为成熟检索算法。

5. `should_follow()` 的文本上下文有限

   discovery 在判断是否 follow 某个 link 时，通常只有 URL 或链接文本，没有完整目标页正文。因此 keyword plan 对 follow 阶段的帮助主要来自 URL 和 link text，而不是目标页内容。

6. batch config 已支持 keyword plan，但仍需谨慎使用

   batch config 现在可以配置 `keyword_query` 和 `relevance_strategy`。默认仍不启用；`bm25-like` 仍要求存在 `keyword_query`。风险点在于批量任务如果开启 `bm25-like`，不同学校的 `max_pages` 较小时页面集合可能发生变化。

7. 诊断信号和评分规则存在重复描述

   `RuleBasedRelevanceStrategy` 的 `diagnose()` 需要和 `score_url()` 的规则保持同步。后续如果修改 `score_url()`，需要同步检查 `_rule_based_signals()`，否则诊断可能和实际分数不一致。

8. mock LLM 不代表真实模型能力

   `MockKeywordPlanProvider` 只验证结构化链路和 fallback，不验证真实 prompt、模型稳定性、token 成本、速率限制或网络错误。不能把当前 mock 测试结果解读为真实 provider 可用。

9. LLM fallback 当前只回退到规则 query 解析

   `generate_keyword_plan_with_fallback()` 在 provider 出错或 payload 校验失败时，会回退到 `keyword_plan_from_query()`。这能保证流程不中断，但不会产生更强的语义理解能力。

10. report 中的 keyword plan 是诊断，不是事实

   Markdown report 已展示 keyword plan 和 LLM keyword diagnostics。使用者需要明确这些字段只是爬取策略解释，不能作为招生要求、费用或申请事实。

11. batch 多 seed 合并时 run.config 仍以合并目标为主

   batch 多 seed 会合并 `AdmissionsData`。当前 keyword plan 是 university-level 配置，适合共享到每个 seed；如果未来每个 seed 需要不同 keyword plan，需要另行设计 per-seed diagnostics。

### 已处理的后续修改

1. 为 keyword plan 增加独立单元测试

   已新增 `tests/test_relevance.py`，单独测试 `keyword_plan_from_query()`、URL hint 映射、negative keyword、schema payload 校验和 strategy factory。

2. 为 batch config 增加 opt-in keyword plan

   已在 batch config 中增加可选 `keyword_query` 和 `relevance_strategy`。默认不启用，且 `bm25-like` 仍要求存在 `keyword_query`。

3. 在报告中展示 keyword plan 摘要

   已在 Markdown report 的 diagnostics 区域增加 `Keyword Plan` 摘要，并保持在 `Facts` 之前，不进入 admissions facts。

4. 抽出更清晰的 strategy factory

   已新增 `build_relevance_strategy()`，CLI 和 batch 共用同一套 `keyword_query` / `relevance_strategy` 校验与 strategy 构造逻辑。

5. Step 5 前先定义模型输出 schema

   已定义 `KEYWORD_PLAN_OUTPUT_SCHEMA` 和 `keyword_plan_from_payload()`，并接入 mock provider 验证 schema/fallback 链路。尚未处理真实模型 provider 的凭据、超时、费用和 token 诊断。

6. Step 5 mock LLM keyword plan

   已新增 `MockKeywordPlanProvider` 和 `generate_keyword_plan_with_fallback()`。CLI 仅允许 `--enable-llm --llm-provider mock --keyword-query ...`，真实 provider 仍保持 guarded。

### 仍待处理

1. 真实模型 provider 仍未接入

   当前只接入 mock provider。下一步如要接真实 provider，需要单独确认凭据、超时、费用、网络访问和 fallback 策略。

2. provider 诊断字段仍需扩展

   当前已记录 provider、schema、elapsed_ms、fallback、warnings 和错误信息。真实 provider 接入时仍需补模型名、token、成本和超时原因。

3. batch 文档示例还未补充

   当前设计文档描述了字段，但 README 或示例 config 尚未补充 batch keyword 配置样例。

4. 真实 provider 接入策略未确定

   需要先确定 provider 抽象、API key 读取方式、超时、重试、费用预算、日志脱敏和测试替身。不能直接把真实 provider 接到默认 CLI。

5. prompt 和 schema 版本管理未设计

   真实模型生成 `KeywordPlan` 时，需要记录 prompt/schema 版本，否则后续难以复现计划来源。

6. LLM keyword plan 与 `bm25-like` 的组合策略需要人工评估

   当前允许 mock LLM plan 作为 `bm25-like` 的输入。真实模型接入后，需要用固定 fixture 和少量真实站点评估排序变化，避免模型扩展词让 crawler 偏离本科招生页面。

## 不建议做的事

- 不要一次性替换 `discover()`。
- 不要把 ScrapeGraphAI 或 Crawl4AI 的代码复制进项目。
- 不要把 LLM 输出直接写入 `AdmissionsData`。
- 不要为了关键词爬取绕过当前官方域名限制。
- 不要把 optional dependency 变成核心依赖。
- 不要删除当前半使用接口，例如 `CrawlConfig`、`parse_sitemap_urls()` 或 optional stubs，除非单独确认。

## 下一步建议

如果继续 Step 5，不建议直接接入真实模型调用。更低风险的顺序是：

1. 先补 `KeywordPlan` 的 schema 校验和独立测试。
2. 再补 strategy factory，统一 CLI 和未来 batch 的参数校验。
3. 然后接入 mock LLM provider，只输出 `KeywordPlan`，并记录 provider、耗时、fallback 和 warnings。
4. 最后再考虑真实 provider，且必须保持显式 opt-in。

上述第 1、2、3 项已经完成；下一步如果继续推进，应单独设计真实 provider 的凭据、超时、成本、prompt/schema 版本和错误处理，不应直接把真实模型接入默认流程。
