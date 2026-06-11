# 关键词爬取设计说明

## 目标

本文档记录将模型辅助关键词爬取逐步迁移到 `school-data-spider` 的设计边界。当前分支已按渐进式方案完成 Step 0 到 Step 4：默认爬虫行为保持不变，关键词计划和 BM25-like scorer 均为显式 opt-in。

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

### Step 6：低置信度页面分类辅助

仅当规则分类低置信度时，模型可给出候选分类和理由。初期只记录到 diagnostics，不覆盖现有 `PageCategory`。

风险：中到高。不能让模型分类直接触发字段抽取，除非后续单独批准。

## 当前实现复盘

本轮修改覆盖 Step 2 到 Step 4，累计修改范围如下：

- `university_admissions_crawler/crawler/relevance.py`
- `university_admissions_crawler/crawler/discovery.py`
- `university_admissions_crawler/pipeline/run_university_scan.py`
- `university_admissions_crawler/cli.py`
- `tests/test_discovery.py`
- `tests/test_pipeline.py`
- `tests/test_report_cli.py`

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

### 行为边界

- 默认 CLI 参数、fixture scan、live HTTP scan 仍使用 `rule_based`。
- `--keyword-query` 单独使用只记录计划，不改变 discovery 排序。
- 只有同时传入 `--keyword-query` 和 `--relevance-strategy bm25-like` 时，候选链接排序和 follow 判断才会使用新 scorer。
- 新增诊断字段会改变输出 JSON 的形状，但不改变招生事实字段的含义。
- 当前没有删除、移动文件，也没有改变 batch config 输入格式。

### 验证结果

Step 4 完成后已运行：

```bash
.venv314/bin/python -m pytest -q tests/test_discovery.py tests/test_report_cli.py tests/test_pipeline.py
.venv314/bin/python -m compileall -q university_admissions_crawler tests
git diff --check
.venv314/bin/python -m pytest -q
```

结果：`90 passed`。

## 风险和后续待改点

### 已发现风险

1. `run.config` 输出结构变宽

   Step 2 增加了 source-level discovery 诊断字段，Step 3 增加了可选 `keyword_plan`，Step 4 增加了 strategy 名称。下游如果对 JSON schema 做严格字段校验，需要同步接受这些诊断字段。

2. `bm25-like` 会改变抓取顺序

   该行为是预期能力，但会影响 `max_pages` 较小时最终抓到的页面集合。因此必须继续保持 opt-in，不应让 `--keyword-query` 自动切换 scorer。

3. 当前 keyword plan 解析较简单

   `keyword_plan_from_query()` 目前只是按空白、逗号、分号、竖线和斜线拆词，并做简单 URL hint 映射。它适合作为可审查结构，不适合作为最终语义理解方案。

4. BM25-like 不是完整 BM25

   当前实现更接近 deterministic token overlap 加权，而不是带文档频率、长度归一化和语料统计的完整 BM25。命名中的 `Like` 必须保留，避免误解为成熟检索算法。

5. `should_follow()` 的文本上下文有限

   discovery 在判断是否 follow 某个 link 时，通常只有 URL 或链接文本，没有完整目标页正文。因此 keyword plan 对 follow 阶段的帮助主要来自 URL 和 link text，而不是目标页内容。

6. batch config 尚未支持 keyword plan

   Step 3 按低风险原则只接入 CLI，没有扩展 `config_loader.py` 和 batch JSON schema。批量任务如需关键词计划，应单独做一个小步骤，并补 batch 测试。

7. 诊断信号和评分规则存在重复描述

   `RuleBasedRelevanceStrategy` 的 `diagnose()` 需要和 `score_url()` 的规则保持同步。后续如果修改 `score_url()`，需要同步检查 `_rule_based_signals()`，否则诊断可能和实际分数不一致。

### 建议后续修改

1. 为 keyword plan 增加独立单元测试

   当前测试主要通过 CLI 和 discovery 覆盖。后续可以新增 `tests/test_relevance.py`，单独测试 `keyword_plan_from_query()`、URL hint 映射和 negative keyword。

2. 为 batch config 增加 opt-in keyword plan

   建议字段为 `keyword_query` 和 `relevance_strategy`。默认不启用，且 `bm25-like` 仍要求存在 `keyword_query`。

3. 在报告中展示 keyword plan 摘要

   目前 keyword plan 只在 `result.json` 中。后续可在 Markdown report 的 diagnostics 区域展示，但不应进入 admissions facts。

4. 抽出更清晰的 strategy factory

   CLI 当前直接组装 strategy。若 batch 也支持 strategy，可以新增一个小函数统一校验 `keyword_query` 和 `relevance_strategy`，避免 CLI/batch 重复实现。

5. Step 5 前先定义模型输出 schema

   模型只生成 `KeywordPlan`，需要明确 JSON schema、长度限制、超时、fallback、warnings 和 provider 诊断字段。不要让模型直接影响 `AdmissionsData`。

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
