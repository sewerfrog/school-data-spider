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

## 渐进式迁移步骤与当前状态

### Step 0 到 Step 3：已完成

已完成设计文档、默认 relevance strategy 接口、发现诊断和用户关键词计划。当前行为边界：

- 默认 crawler 仍使用规则评分和 bounded discovery。
- `--keyword-query` 单独使用时只记录 `run.config["keyword_plan"]`，不改变抓取顺序。
- source-level discovery 诊断只写入 `run.config["source_strategy"]`，不参与招生事实写入。

### Step 4：BM25-like scorer 已完成，保持 opt-in

已新增 `BM25LikeRelevanceStrategy` 和 `--relevance-strategy bm25-like`。该策略以现有 `score_url()` 为基线，再叠加 keyword plan 的关键词和 URL hint 命中分。

行为边界：

- `bm25-like` 必须和 `--keyword-query` 一起使用。
- 它仍受 `max_pages`、`max_depth`、domain policy 和 follow 阈值约束。
- 它会改变候选 URL 排序，因此不能成为默认策略。

### Step 5：mock LLM keyword plan 已完成，真实 provider 仍 guarded

已完成模型关键词计划的低风险链路：

- `KEYWORD_PLAN_OUTPUT_SCHEMA`
- `keyword_plan_from_payload()`
- `MockKeywordPlanProvider`
- `generate_keyword_plan_with_fallback()`
- `run.config["llm_keyword_plan"]`

当前只允许 `--enable-llm --llm-provider mock --keyword-query ...`。真实 provider 仍不能调用；接入前必须单独设计凭据、超时、费用、prompt/schema 版本、日志脱敏和 fallback。

### Step 6：低置信度分类辅助已进入 diagnostics-only 阶段

Step 6 的设计边界保持不变：模型候选分类只能记录为 diagnostics，不覆盖规则 `PageCategory`，不直接触发字段抽取，也不写入招生 facts。

当前已落地或正在保留的方向：

- `classification_assist_summary`：即使 assist 启用了但 0 触发，也能在 `run.config` 中看到状态。
- source filtering：过滤静态资源和明显低价值 privacy/GDPR/cookie 类 PDF，减少 HKU 等 live 结果中的噪音。
- `extraction_diagnostics_summary`：记录每个 source 里 extractor 的尝试、跳过和失败原因。
- Markdown report 在 facts 前展示 diagnostics，不把诊断内容混进 facts。

这批改动提升的是可诊断性，不是字段覆盖率本身。coverage 仍取决于 source selection、context gate 和具体 extractor 能力。

## Step 6 复盘：收益与限制

### 已确认收益

- `classification_assist_summary` 解决了旧输出中 `classification_assist` 不出现时无法区分“未启用、未触发、出错”的问题。
- HKU source filtering 有明确收益：低价值 `other` source 减少，GDPR privacy PDF 被移除，coverage 未下降。
- `extraction_diagnostics_summary` 能区分 `no_match`、`context_gate_failed`、`existing_value`、`undergraduate_context_gate_failed` 等路径。
- 报告新增 diagnostics 且位于 facts 前，符合 evidence-first 方向。

### 仍有限制

- `run_university_scan.py` 的插桩已经明显变重。短期可接受，但下一步不能继续把更多诊断逻辑硬塞进主循环。
- 当前 diagnostics 不能证明“官网没有提供”。它只能说明“当前抓到的 source 中，现有 extractor 没抽出来或被 gate 跳过”。
- source filtering 仍有误删风险。静态资源过滤风险低；privacy/GDPR PDF 过滤合理；但未来若学校把招生条款 PDF 命名为 `terms-and-conditions.pdf`，可能被误过滤。
- NTU fees 隔离检查修正了原判断：saved undergraduate fee 页面抓到了，分类为 `fees`，但当前先被 `has_undergraduate_fee_context(...)` 拦住，pipeline 记录为 `context_gate_failed`，还没有真正走到 `extract_fee`。

### 对整体目标的判断

这批改动值得保留，但应准确描述为“排查能力提升”，不是“数据覆盖率提升”。

系统从“只告诉你缺字段”进化到“告诉你缺字段可能卡在哪一步”。这会降低后续 HKU、NTU、PolyU 真实站点优化成本，但还没有解决字段抽取能力本身。

## 已执行进度复盘

### Step A：冻结并验证当前 diagnostics/source filtering 改动，已完成

修改文件：无。

结果：旧 Codex 已完成的 diagnostics/source filtering 改动可以保留，基线测试通过。

已验证：

```bash
git diff --check
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m university_admissions_crawler.cli tests/fixtures/mini_university_site --fixture --output-dir /tmp/uac-current-diagnostics --max-pages 20 --max-depth 3
```

验证结果：

- 目标测试组：52 passed。
- 完整测试：107 passed。
- fixture smoke 写出 `/tmp/uac-current-diagnostics/result.json` 和 `/tmp/uac-current-diagnostics/report.md`。

### Step B：补 source filtering 的边界测试，已完成

修改文件：

- `tests/test_filters.py`
- `tests/test_discovery.py`

结果：保留静态资源和 privacy/GDPR/cookie/terms 类低价值 PDF 过滤，同时用招生 PDF 反例保护误删边界。

新增边界：

- `privacy-notice-applicants.pdf`、`GDPR Privacy Notice Applicants.pdf`、`cookie-policy.pdf`、`terms-of-use.pdf`、`Personal Information Collection Statement.pdf` 不 follow。
- `2026-undergraduate-admissions-prospectus.pdf`、`international-entry-requirements.pdf`、`undergraduate-tuition-fees.pdf`、`programme-requirements.pdf` 继续允许。
- discovery 层确认招生 PDF 可以进入抓取结果。

已验证：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
git diff --check
```

验证结果：

- source filtering 相关测试：17 passed。
- 目标测试组：55 passed。

### Step C：收敛 extraction diagnostics 的重复记录，已完成

修改文件：

- `university_admissions_crawler/pipeline/run_university_scan.py`
- `tests/test_pipeline.py`

结果：新增薄的 `_ExtractionDiagnosticsRecorder`，把主流程和 `_extract_core_supplements()` 中分散的 attempt 记录收敛到一个入口。`_record_extraction_attempt(...)` 仍是底层 dict 写入函数。

边界：

- 未拆整个 `run_scan()`。
- 未改变 extractor 调用顺序。
- 未改变 facts/evidence 写入逻辑。
- 未改变 diagnostics JSON 字段结构。

已验证：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_report_cli.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
git diff --check
```

验证结果：

- pipeline/report 相关测试：38 passed。
- 目标测试组：55 passed。
- 完整测试：110 passed。

### Step D：新增字段级 missing reasons，已完成

修改文件：

- `university_admissions_crawler/pipeline/diagnostics.py`
- `university_admissions_crawler/reports/render_report.py`
- `tests/test_pipeline.py`
- `tests/test_report_cli.py`

结果：在 `run.config` 顶层新增 `missing_reasons`，不改变 `coverage` 原结构。reason 从现有 `coverage.missing`、`extraction_diagnostics`、`source_strategy` 推导，不新增抓取、不新增 extractor、不改 facts/evidence。

第一版 reason：

- `not_attempted`
- `attempted_no_match`
- `context_gate_failed`
- `undergraduate_context_gate_failed`
- `application_portal_unreachable`
- `manual_check_required`

输出形状：

```json
{
  "fees": {
    "reason": "context_gate_failed",
    "attempts": 2,
    "attempted_extractors": ["extract_fee"],
    "source_urls": ["https://example.edu/fees"],
    "note": "Captured sources did not pass the field-specific context gate."
  }
}
```

报告行为：

- `## Missing Reasons` 位于 facts 前。
- 只在存在缺失字段时展示，不输出空章节。
- 明确说明 missing reasons 描述的是当前 crawl/extractor 状态，不证明官网没有提供字段。

已验证：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_report_cli.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m university_admissions_crawler.cli tests/fixtures/mini_university_site --fixture --output-dir /tmp/uac-missing-reasons --max-pages 20 --max-depth 3
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
git diff --check
```

验证结果：

- pipeline/report 相关测试：39 passed。
- 目标测试组：56 passed。
- 完整测试：111 passed。
- fixture smoke 写出 `/tmp/uac-missing-reasons/result.json` 和 `/tmp/uac-missing-reasons/report.md`。

### Step E：隔离检查 NTU fees，已完成

修改文件：无。

检查对象：

- undergrad fee source：`tests/fixtures/saved_sources/ntu/980551993bc03f86.txt`
- graduate fee source：`tests/fixtures/saved_sources/ntu/359466af0e460cb9.txt`

实际发现：

- NTU undergraduate fee 页 URL 是 `https://www.ntu.edu.sg/admissions/undergraduate/financial-matters/tuition-fees`。
- `classify_page(...)` 结果为 `fees`，score 为 6。
- `has_undergraduate_admissions_context(...)` 为 true。
- `has_undergraduate_fee_context(...)` 为 false。
- `extract_fee(...)` 直接调用当前也返回 no record，但 pipeline 中真正记录的是 `skipped/context_gate_failed`，因为 fee context gate 先拦截了 extractor。
- graduate tuition source 仍被正确排除：classification 为 `irrelevant`，undergraduate context 为 false，fee context 为 false。

最小 saved-source pipeline 结果：

```text
fees_count: 0
coverage_missing_contains_fees: True
missing_reasons_fees.reason: context_gate_failed
```

结论：原计划中“NTU fees 优先修 `extract_fee no_match`”需要调整。下一步应先修 NTU fee context gate，再判断是否还需要改 `extract_fee`。

## 调整后计划的执行结果

### Step F1：固化 NTU fee context gate 回归样例，已完成

修改文件：

- `tests/test_pipeline.py`

结果：把 Step E 的隔离结论固化为 fixture-backed 测试，避免后续修源码时丢失边界。

测试覆盖：

- NTU undergraduate fee source 分类为 `fees`。
- `has_undergraduate_admissions_context(...)` 为 true。
- F1 时 `has_undergraduate_fee_context(...)` 仍为 false。
- 最小 saved-source pipeline 在修复前的失败路径是 `missing_reasons["fees"]["reason"] == "context_gate_failed"`。
- pipeline diagnostics 中 `extract_fee` 为 `skipped/context_gate_failed`。

已验证：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
git diff --check
```

验证结果：

- pipeline 测试：22 passed。
- 目标测试组：57 passed。
- 完整测试：112 passed。

### Step F2：修 NTU undergraduate fee context gate，已完成

修改文件：

- `university_admissions_crawler/crawler/admissions_context.py`
- `tests/test_pipeline.py`

结果：明确的 NTU undergraduate tuition fees 页面已经通过 `has_undergraduate_fee_context(...)`。负向保护仍保留在 URL/title/path 层，避免正文导航里的 `Postgraduate` 等词误杀 undergraduate fee 页面。

保留的负向边界：

- graduate / postgraduate。
- hall fee / hall admission。
- residential life。
- current-students。
- `/sao/`。
- PhD fellowship。

执行边界：

- 未改 `extract_fee(...)`。
- 不改 discovery、source filtering、report rendering。
- F2 后，NTU source 已进入 `extract_fee`，但 extractor 返回 `no_match`，因此需要 F3。

已验证：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
git diff --check
```

验证结果：

- pipeline 测试：22 passed。
- 目标测试组：57 passed。
- 完整测试：112 passed。

### Step F3：修 NTU fee extractor 的最小能力，已完成

修改文件：

- `university_admissions_crawler/extractor/html_extractor.py`
- `tests/test_pipeline.py`

结果：针对 NTU undergraduate tuition fee saved source 增加窄范围的 fee-table reference fallback。

重要边界：

- 当前 saved text 没有直接暴露 `S$`、`SGD` 或具体金额，所以 extractor 不生成金额。
- 输出的是官网 fee table/reference raw candidate。
- `parsed` 保持 `[]`。
- `parse_status` 为 `raw_needs_manual_review`。
- pipeline 中 NTU undergrad fee source 现在能生成 `fees` 记录，不再是 `no_match`。
- PolyU hall fees、PolyU PhD fellowship、NTU graduate tuition 仍不会被误抽为 undergraduate fees。

直接检查结果：

```text
record: True
value: Tuition Fees For Semester 1 and 2 Accepted programme offer in 2026. Tuition fees payable for AY2026-27. Tuition Fees payable per academic unit For Semester 1,2&nbsp;and Special Term Tuition fees and MOE Subsidy for part-time undergraduates programme
parse_status: raw_needs_manual_review
parsed: []
evidence_count: 1
```

执行边界：

- 不重写 `extract_fee(...)`。
- 不放宽到会误抽 postgraduate、hall、current-students fee 的规则。
- 保留现有 context gate。
- 不把 raw candidate 当作已结构化金额。

已验证：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
git diff --check
```

验证结果：

- pipeline 测试：22 passed。
- 目标测试组：57 passed。
- 完整测试：112 passed。

## 剩余问题与下一步

### 当前剩余问题

- NTU fees 现在只是“官网 fee table/reference 被找到”，不是金额结构化解析完成。要拿到具体金额，需要后续抓到或解析 NTU 实际 table 内容。
- `missing_reasons` 的字段级归因优先级仍可优化：当多个 source 对同一字段有不同失败原因时，应优先展示最接近真实瓶颈的 source-level 结果，例如 extracted > attempted_no_match > context_gate_failed > not_attempted。
- 项目级文档已同步本轮完整改动。

### Step G：最后同步项目文档，已完成

修改文件：

- `README.md`
- `PROJECT_MAP.md`
- `VERSION_NOTES.zh.md`
- `docs/keyword-crawl-design.zh.md`

结果：项目入口文档已同步当前真实状态，不再沿用旧测试数量或旧诊断描述。

已同步内容：

- classification assist summary 可区分 0 触发。
- extraction diagnostics / missing reasons 是诊断，不是招生事实。
- source filtering 的收益和误删边界。
- NTU fees 已修复为 fixture-backed raw fee table/reference fallback，但不是金额结构化解析。
- pytest 数量更新为当前完整验证 `112 passed`，目标测试组 `57 passed`。

验证方式：

```bash
git diff --check -- README.md PROJECT_MAP.md VERSION_NOTES.zh.md docs/keyword-crawl-design.zh.md
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
```

## 当前行为边界

- 默认 CLI 参数、fixture scan、live HTTP scan 仍使用 `rule_based`。
- `--keyword-query` 单独使用只记录计划，不改变 discovery 排序。
- 只有同时传入 `--keyword-query` 和 `--relevance-strategy bm25-like` 时，候选链接排序和 follow 判断才会使用新 scorer。
- 只有 `--enable-llm --llm-provider mock` 的 guarded 路径可用；真实 provider 仍不可调用。
- classification assist 只记录候选分类，`applied` 必须保持 `false`，不能直接触发字段抽取。
- diagnostics 可以变宽，但不能混入 `AdmissionsData` facts。

## 不建议做的事

- 不要一次性替换 `discover()` 或重写 `run_scan()`。
- 不要把 ScrapeGraphAI 或 Crawl4AI 的代码复制进项目。
- 不要把 LLM 输出直接写入 `AdmissionsData`。
- 不要为了关键词爬取绕过当前官方域名限制。
- 不要把 optional dependency 变成核心依赖。
- 不要继续把大量诊断逻辑塞进 `run_university_scan.py` 主循环。
- 不要在 missing reasons 里声称“官网没有提供”，除非后续建立了字段级 absence evidence。
- 不要删除当前半使用接口，例如 `CrawlConfig`、`parse_sitemap_urls()` 或 optional stubs，除非单独确认。
