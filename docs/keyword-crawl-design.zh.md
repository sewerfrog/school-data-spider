# 官网主页自动招生爬取设计说明

## 文档定位

本文档记录当前分支的阶段性目标、复盘结论和下一阶段执行计划。项目目标已经从
“提供一组调试参数辅助爬取”收敛为更明确的产品目标：

```text
输入一个大学官网主页 URL，程序自动发现官方本科招生来源，抽取模板中的申请要求、
申请时间、费用、英语要求、材料、联系方式和细分专业目录，并输出可追溯的
result.json、report.md 和 programme_catalog.csv。
```

因此，下一阶段不再把 `keyword_query` 或 LLM keyword optimization 当作用户需要理解
或配置的功能。真实运行必须依赖的策略，例如 domain inference、programme/admissions
relevance、合理的 timeout/browser 策略、source planning 和 diagnostics，应变成默认或
内部能力，而不是让用户手动拼参数。

已完成阶段：

**Phase 3: Source Acquisition Failure and LLM-Assisted Official Source Planning**

**阶段 3：来源获取失败诊断与 LLM 辅助官方来源规划**

**Phase 4: Programme Catalog Extraction**

**阶段 4：专业目录抽取与表格输出**

当前进入下一阶段：

**Phase 5: Homepage-First Automatic Admissions Crawl**

**阶段 5：官网主页优先的自动招生信息爬取**

阶段 3/4 的结论是：diagnostics、missing reasons、blocked/challenge detection、
programme catalog schema 和 CSV 输出都值得保留。但这些能力还没有让项目成为真正的
“官网主页输入 -> 自动找到招生和专业目录页 -> 输出完整模板”的工具。现阶段最大问题是：

- CLI 参数过多，真实运行必须知道 `--auto`、`--enable-browser`、`--keyword-query`、
  `--relevance-strategy bm25-like`、`--allowed-domain`、timeout / browser wait 等内部
  细节。
- `keyword_query` 本质是人工指引，不符合“只输入大学官网”的目标。
- LLM keyword optimization 只是把人工关键词结构化，不能解决官网导航和 source
  acquisition 问题，应该裁剪。
- 当前 source planning 只写 diagnostics，不进入 crawl frontier，因此不能实际帮助从
  主页找到专业目录页。
- 当前 discovery 是 bounded BFS/deque，只在单页内排序 links，没有全局优先 frontier；
  真实官网容易把 page budget 消耗在 about/news/corporate 页面。

Phase 5 的核心方向是：裁剪 keyword 指引功能，把默认爬取策略改成
programme/admissions-aware，并把 LLM 用在“分析官网导航和候选官方 source”上，而不是
用在“生成关键词”或“生成事实”上。

## 当前目标与边界

本项目的长期目标是：从任意大学官网出发，自动发现官方招生来源，并抽取可追溯的
本科招生关键字段。

当前已经明确的边界：

- 用户输入应尽量简化为官网主页 URL 和输出目录；大学官网对应的 domain、source
  discovery 策略、programme/admissions relevance 和常见网络参数应由程序默认处理。
- source 被抓到了，但内容是 WAF/challenge，不是招生页面。
- 字段缺失是 source acquisition 层失败，不是 extractor 本身没写好。
- LLM 可以辅助寻找官方替代来源、分析导航菜单和 source candidates，但不能绕过 WAF，
  也不能直接写 facts。
- 所有 facts 仍必须来自实际抓取到的官方 source、snippet 和 evidence path。
- diagnostics 只能解释“当前抓到的 source 和当前 extractor 链路发生了什么”，不能
  证明官网从未提供某字段。
- 不再把 `keyword_query` 作为产品主路径；需要爬取哪些招生信息由模板和内部
  source-discovery profile 决定。

## 已完成基线

以下能力已实现并应保留，不在当前阶段重写：

- evidence-first 数据流：只把有来源证据的内容写入招生 facts。
- programme catalog schema、extractor、diagnostics 和 `programme_catalog.csv` 已作为
  专业目录输出主线建立。
- source filtering 已过滤静态资源和明显低价值 privacy / GDPR / cookie / terms
  类 source，并保留 admissions prospectus / tuition / requirements 类 PDF 反例。
- `classification_assist_summary` 可以显示 classification assist 是否启用、是否触发、
  是否 0 触发。
- `extraction_diagnostics_summary` 可以汇总 extractor 的 `extracted`、`no_match`、
  `skipped` 及跳过原因。
- `missing_reasons` 已作为诊断层输出，不改变 `coverage`、facts 或 evidence。
- `missing_reasons` 已优先区分 `attempted_no_match`、context gate、portal/manual
  check、`not_attempted` 等场景。
- Markdown report 已在 facts 前展示 diagnostics 和 missing reasons。
- NTU undergraduate tuition fee 已固定边界：只有官方 fee table/reference 时保留
  `raw_needs_manual_review`，只有 source 明确包含 `S$` 金额时才解析结构化 `SGD`
  amount。
- `looks_like_blocked_or_challenge_source()` 可以识别 Incapsula / WAF / noindex /
  captcha / access denied 等明显 challenge 内容。
- `source_strategy` / `source_strategy_summary` 可以把相关 source 标记为
  `blocked_or_challenge`，保留 source 供审计，但不会把它当普通招生 HTML 送进
  extractor。
- `missing_reasons` 已能用 `source_not_crawled` 表达 challenge source 导致的
  source acquisition failure。
- `extraction_diagnostics` 会记录 source-level `source_acquisition_status`，用于区分
  blocked source 上的 no-match 和 usable source 上的 no-match。
- `--enable-source-planning` 已接入 guarded mock LLM source planning。它必须配合
  `--enable-llm --llm-provider mock`，默认不启用。
- `llm_source_plan` 只写入 `run.config` diagnostics，不 crawl 候选 URL，不写 facts，
  不绕过 WAF。
- LLM candidate URL 会经过 deterministic validation，accepted/rejected 都可审计；
  accepted candidate 只是诊断候选，不是当前 crawl frontier。
- Markdown report 已在 facts 前展示 `Source Planning Diagnostics`，并明确说明它不是
  admissions facts。
- `run_university_scan.py` 当前不继续膨胀；已有 diagnostics recorder 能覆盖当前
  诊断写入需求。

这些能力提升的是排查能力，不等于字段覆盖率已经解决。coverage 仍取决于 source
selection、source acquisition、context gate、extractor 和真实站点结构。

以下能力在 Phase 5 需要裁剪或改造：

- `--keyword-query` 不应继续作为用户主入口。项目目标是按招生模板自动找 source，
  不是让用户用关键词引导 crawler。
- LLM keyword plan / keyword optimization 应删除或降级为内部测试遗留，不再作为文档化
  feature。
- `bm25-like` 不应继续要求用户显式选择；programme/admissions-aware relevance 应成为
  默认策略。
- `--enable-source-planning` 不应长期停留在 diagnostics-only；LLM source planning 应
  在通过 deterministic validation 后成为 guarded crawl frontier input。

## 当前复盘

### NTU 对比结论

用当前 feature 重新跑 NTU 后，coverage 仍为 `6/9`，没有单纯提升字段数量；
但结果更可信：

- postgraduate tuition fee 页面被降为 `irrelevant`，减少本科 fee 污染。
- fee 字段从多条混杂 fee candidate 收敛为官方 undergraduate tuition raw reference。
- fee candidate 被标记为 `raw_needs_manual_review`，没有伪造结构化金额。
- 缺失字段能区分：
  - `required_documents`: `attempted_no_match`
  - `accepted_qualifications`: `not_attempted`
  - `undergraduate_application_entry`: `manual_check_required`

这说明当前分支的主要价值是“可诊断、可定位”，不是短期 coverage 增长。

### NUS 对比结论与 Phase 3 复盘

项目已有旧 NUS 输出：

- `outputs/nus-live-programmes/result.json`
- `outputs/nus-live-programmes/programmes.csv`
- `outputs/nus-live-programmes/report.zh.md`
- `outputs/nus-live-programmes/sources/official-source-index.md`

旧临时归档中曾保留过一份复制内容；归并后不再作为独立路径引用。当前稳定参考
以 `outputs/nus-live-programmes/` 和 Phase 4 fixture 为准。

旧输出是 programme collection 格式，不是当前 CLI 的标准 admissions schema。它包含：

- 14 个 official sources
- 85 条 structured programme records
- 6 条 special programme records
- 28 个 official admissions programme choices
- `programmes.csv` 共 91 条数据行，含 degree programme、major、cross-disciplinary
  degree 和 special programme。

旧输出同时明确记录了限制：NUS simple HTTP fetch 会遇到 Incapsula/WAF/noindex
challenge，旧数据是通过 browser/search extraction 和官方页面交叉核验得到的。

旧临时归档中的其他信息已经压缩为以下项目级结论：

- 上一阶段 handoff 明确了 evidence-first MVP 边界：核心运行时保持轻依赖，fixture-first，
  live/browser/LLM/ScrapeGraph 都是 guarded flags；无法证实的招生事实只能保持 unknown、
  warning 或 needs-manual-check。
- fixture smoke run 原始临时目录已经不可读，只保留当时已确认统计：14 个 source、
  16 条 evidence、14 个 discovered categories；warning 包括 diff manual check、
  application deadline conflict 和 stale page；没有 missing evidence warning。
- NUS one-off 专业产物是官方来源交叉核验结果，不是当前通用 pipeline 可稳定复现的
  自动爬取结果。它的价值是为 Phase 4 定义 programme catalog 表格形态、source index
  和 fixture-backed 目标样板。

本轮 source acquisition diagnostics 固定了 NUS Incapsula/challenge 场景：如果抓到的
source 内容是 challenge 页面，系统会把它诊断为 `blocked_or_challenge`，并把字段缺失
解释为 source acquisition failure，而不是普通 extractor failure。

历史 NUS HTTP/browser 抓取曾只抓到 1 个 source，内容是：

- `NOINDEX, NOFOLLOW`
- `_Incapsula_Resource`
- `Request unsuccessful`
- `Incapsula incident ID`

这不是 extractor 回归，而是 source acquisition 失败。Phase 3 已经把这种失败边界
显式化，并用 fixture 固定。

本轮 live smoke 进一步说明：当本机 browser 跑法实际抓到 30 个 NUS 官方 HTML
source 时，source planning 没有触发，coverage 为 `2/9`，只找到
`required_documents` 和 `fees`。这说明剩余 NUS 问题已经从 WAF/challenge 转向
extractor、context gate 和 source prioritization：

- `programmes`: `attempted_no_match`
- `application_periods`: `attempted_no_match`
- `english_requirements`: `context_gate_failed`
- `contacts`: `context_gate_failed`
- `accepted_qualifications`: `not_attempted`
- `undergraduate_application_entry`: `manual_check_required`

## Phase 3 保留结论

以下是 Phase 3 当时的保留理由；Phase 5 会在保留 evidence-first 和 diagnostics 边界的
前提下主动改变默认 crawl 策略：

- 默认运行路径基本不变，source planning 是显式 opt-in。
- LLM 输出没有污染 facts。
- blocked/challenge source 被保留为 source/diagnostics，没有被静默删除。
- 新增能力主要提升诊断和审计，不会让 crawler 更激进。
- tests 和 live smoke 都支持当前方向。

仍需保留的风险提醒：

- `accepted_candidate_urls` 是已验证的诊断候选，不是当前实现中的自动 crawl frontier。
- `run_university_scan.py` 插桩已经偏重，后续不要继续把更多诊断逻辑硬塞进主流程；
  如需继续扩展，应先抽小 helper/tracer。
- `missing_reasons` 不能证明官网没有提供某字段，只能解释当前抓取链路和 extractor
  尝试结果。
- source filtering 有降噪收益，但仍需 admissions PDF 反例测试保护，避免误删
  `terms-and-conditions` 这类少数可能承载招生条款的文件。

## Phase 3 已完成执行记录

上一阶段的执行记录压缩如下，详细过程不再作为当前执行计划保留：

1. 固定 NUS Incapsula challenge fixture：
   `tests/fixtures/saved_sources/nus/incapsula_challenge.html`。
2. 在 `crawler/filters.py` 中增加 deterministic blocked/challenge detector。
3. 在 `pipeline/diagnostics.py` 中把 challenge source 导致的缺失归为
   `source_not_crawled`。
4. 增加 `--enable-source-planning` guarded mock 入口和
   `pipeline/source_planning.py`。
5. 增加 source-plan candidate URL validation；accepted/rejected 只进入 diagnostics。
6. 在 `reports/render_report.py` 中于 facts 前展示 `Source Planning Diagnostics`。
7. 用 NUS mock source plan fixture 固定 “候选 URL 不被自动抓取、不写 facts” 的边界。
8. live smoke 验证：浏览器能抓到 NUS 30 个官方 HTML source 时，source planning
   不触发；coverage 为 `2/9`，剩余问题转向 extractor / context gate /
   source prioritization。

最近验证状态：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
# 126 passed

env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
# 71 passed
```

## Phase 4 已完成基线

Phase 4 已把“细分专业目录抽取”作为本项目的通用核心能力，而不是继续把它塞进
现有 admissions core field 的 `programmes` 里。

原因：

- 专业目录是高基数表格。一个大学可能有几十到几百条 degree、major、minor、
  second major、special programme、dual degree 或 admissions choice。只用
  `coverage.programmes = found` 会严重低估完整性问题。
- 现有 `ProgrammeRecord` 只包含 `name`、`degree`、`faculty_or_school`、
  `source_url`、`prerequisites`、`evidence`，不足以承载专业表需要的 category、
  mode、duration、admissions choice、major/minor/specialisation、programme URL、
  parse status 和 row-level warnings。
- 当前 `extract_programmes()` 主要是 Bachelor/BSc/BA/BEng 等 regex，适合轻量候选，
  不适合构建完整专业目录。
- 旧 NUS `outputs/nus-live-programmes/programmes.csv` 已经证明目标表格形态有价值，
  但它是一份一次性产物，不代表当前通用 pipeline 已能稳定复现。

因此系统核心能力现在拆成两条主线：

1. Admissions Facts Extraction：继续负责申请时间、费用、资格、材料、英语要求、
   联系方式等招生事实字段。
2. Programme Catalog Extraction：新增独立 schema、parser、diagnostics 和 CSV/table
   输出，负责大学本科专业目录、细分专业和所属学院/学制/degree/admissions choice。

## 当前输出形态

Phase 4 当前已经生成：

- `result.json` 中的 `programme_catalog`。
- `programme_catalog.csv`，用于表格审阅、数据库导入或后续选校业务。
- report 中的 programme catalog summary 和 diagnostics，不把 100+ 行完整表硬塞进
  admissions facts 区。

建议 CSV 字段：

```text
university_id
university_name
programme_id
name
normalized_name
faculty_or_school
department
degree_or_award
programme_level
programme_type
category
mode
duration_or_units
admissions_choice_name
majors
minors
second_majors
specialisations
programme_url
source_url
source_title
evidence_snippet
evidence_confidence
parse_status
warnings
retrieved_at
```

`programme_type` 至少应能区分：

- `degree_programme`
- `major`
- `minor`
- `second_major`
- `specialisation`
- `special_programme`
- `dual_degree`
- `joint_degree`
- `pathway`
- `admissions_choice`

## Phase 4 已完成执行记录

Phase 4 的详细 step 过程已执行完成；这里保留压缩记录，避免继续堆叠历史计划。

已完成：

1. 新增 `ProgrammeCatalogRecord`，并在 `AdmissionsData` 上新增
   `programme_catalog: list[ProgrammeCatalogRecord]`，同时保留旧 `programmes` 字段。
2. 固定 NUS programme catalog fixture，覆盖 degree programme、major 和 special
   programme 的 row-level source/evidence。
3. 新增 `extractor/programme_catalog.py`，不替代旧 `extract_programmes()`，专门负责
   高基数专业目录表格。
4. 增强 programme source discovery signals，覆盖 `/programmes`、
   `/undergraduate-programmes`、`/undergraduate-education`、`/degree-programmes`、
   `/majors`、`/minors`、`/bulletin`、`/catalogue`、`/study/undergraduate`。
5. 新增 `reports/programme_catalog_csv.py`，当 `programme_catalog` 非空时输出
   `programme_catalog.csv`。
6. 新增 `programme_catalog_summary` diagnostics，在 report 的 facts 前展示专业目录
   候选数、接受数、重复数、类型分布、院系分布、parse status 和 source URL。
7. 增加 NUS fixture-backed 端到端样板，但不把旧 NUS one-off result 直接搬成当前
   output。
8. 增加 HKU / NTU / PolyU 最小 saved-source 样板，证明 parser 不只是 NUS 特例。
9. 增加 normalized key 和 row-level warnings：`duplicate_name`、`ambiguous_degree`、
   `missing_faculty`、`category_inferred`、`raw_needs_manual_review`。
10. 增加可选 mock LLM programme candidate classification hint；它只对已抓到 source
    text 中的 candidate 做分类提示，不生成专业事实。

最近验证状态：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
# 153 passed

git diff --check
# passed
```

## Phase 5 当前任务目标

Phase 5 的目标是把项目从“需要用户理解内部参数的 crawler”改成“输入官网主页即可
自动尝试完成招生模板”的 crawler。

目标命令形态：

```bash
.venv314/bin/python -m university_admissions_crawler.cli https://www.example.edu/ \
  --output-dir outputs/example-auto
```

用户不应必须知道：

- `--auto`
- `--allowed-domain`
- `--keyword-query`
- `--relevance-strategy bm25-like`
- `--enable-source-planning`
- `--browser-wait-until domcontentloaded`
- `--timeout-seconds 90`

这些属于项目内部策略，应该由默认 profile 或自动 fallback 处理。

Phase 5 的“自动”不是无边界全站爬取，而是：

1. 从 homepage 推断官方 domain / subdomain scope。
2. 使用内置 admissions/programme source-discovery profile。
3. 优先抓取本科招生、申请要求、费用、英语要求、材料、联系方式和专业目录相关 source。
4. 在 deterministic discovery 不足时，用 LLM 生成官方 source candidates。
5. LLM candidates 经过 URL/domain/source-value validation 后才能进入 crawl frontier。
6. 所有 admissions facts 和 programme rows 仍必须来自实际抓取的 source/evidence。
7. 如果没有抓全，report 必须说明失败卡在 source discovery、blocked/challenge、
   budget exhausted、context gate 还是 extractor no_match。

## Phase 5 裁剪范围

需要裁剪或降级的功能：

- 删除面向用户的 LLM keyword optimization。它不符合“输入官网主页自动爬取模板”的
  产品目标，也没有解决真实官网的 source discovery 问题。
- `keyword_query` 不再作为主功能入口。保留与否取决于兼容成本；即使短期保留，也只能
  作为低层调试参数，不应出现在推荐命令和主 README 工作流里。
- `bm25-like` 不再要求用户显式选择。内置 programme/admissions relevance profile 应成为
  默认 discovery 策略。
- `source planning` 不再只是 report diagnostics；下一阶段应让 validated candidates
  成为 guarded frontier input。
- LLM 不生成申请要求、申请时间、专业名、费用、英语成绩等事实；LLM 只参与 source
  navigation、页面用途判断和已抓取 candidate 的分类提示。

保留能力：

- evidence-first schema 和 validation。
- field-level `missing_reasons` 和 extraction diagnostics。
- blocked/challenge detection。
- programme catalog schema、CSV 输出和 row-level warnings。
- mock-first LLM 测试方式。
- optional browser/PDF 能力，但默认策略需要更适合真实官网。

## Phase 5 执行计划

### Step 1：CLI 默认运行模式收敛

修改文件：

- `university_admissions_crawler/cli.py`
- `university_admissions_crawler/config_loader.py`
- `university_admissions_crawler/pipeline/batch.py`
- `tests/test_report_cli.py`
- `tests/test_pipeline.py`

目标：

- 非 fixture 输入默认为 live auto crawl，不再要求用户显式传 `--auto` 或
  `--enable-live-network`。
- 默认从输入 URL 推断 `allowed_domains`，保留 `--allowed-domain` / `--allowed-host` 作为
  额外收窄或扩展。
- 默认 `max_pages` 调整到真实官网可用范围，例如 `80` 或 `100`；`--smoke` 继续保持小
  上限。
- 默认 `max_depth` 调整为 `4` 或 `5`，避免 `20` 这类深爬造成噪音。
- 默认 `timeout_seconds` 调整到真实官网更可用的范围，例如 `60` 或 `90`。
- 默认 browser wait 使用 `domcontentloaded`，避免 `networkidle` 在复杂官网长时间卡住。
- 保留 `--fixture` 的旧行为，不让 fixture tests 受 live defaults 影响。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_report_cli.py tests/test_pipeline.py
git diff --check
```

风险控制：

- 不删除显式参数，只改变推荐路径和默认行为。
- `--fixture` 必须继续离线、确定性运行。
- batch config 中已有 university-level `max_pages` / `max_depth` 覆盖逻辑继续保留。

### Step 2：裁剪 LLM keyword optimization

修改文件：

- `university_admissions_crawler/cli.py`
- `university_admissions_crawler/extractor/llm_provider.py`
- `university_admissions_crawler/reports/render_report.py`
- `university_admissions_crawler/crawler/relevance.py`
- `tests/test_relevance.py`
- `tests/test_report_cli.py`
- `README.md`
- `VERSION_NOTES.zh.md`

目标：

- 删除或废弃 `MockKeywordPlanProvider`、`KeywordPlanProvider`、
  `generate_keyword_plan_with_fallback` 和 `llm_keyword_plan` report section。
- CLI 不再支持 `--enable-llm --keyword-query` 作为生成 keyword plan 的功能。
- `keyword_query` 如果短期保留，只作为 deterministic debug input，不再由 LLM 优化。
- README / VERSION_NOTES 不再把 LLM keyword plan 写成项目能力。
- 保留 LLM source planning 和 programme candidate classification hint 的 mock-first
  测试能力，因为它们服务于 source navigation 和分类提示，不是 keyword 指引。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_relevance.py tests/test_report_cli.py tests/test_compatibility_boundaries.py
git diff --check
```

风险控制：

- 不一刀切删除所有 LLM 代码。
- 不删除 `validate_llm_candidates()` 这类 evidence-gated helper，除非单独确认无调用价值。
- 删除前先用 `rg` 确认所有 `llm_keyword_plan`、`MockKeywordPlanProvider` 和
  `generate_keyword_plan_with_fallback` 引用。

### Step 3：默认 programme/admissions relevance profile

修改文件：

- `university_admissions_crawler/crawler/relevance.py`
- `university_admissions_crawler/crawler/filters.py`
- `university_admissions_crawler/crawler/discovery.py`
- `university_admissions_crawler/config_loader.py`
- `tests/test_relevance.py`
- `tests/test_discovery.py`
- `tests/test_report_cli.py`

目标：

- 将 programme/admissions-aware relevance 设为默认，而不是让用户显式传
  `--relevance-strategy bm25-like`。
- 内置默认 source-discovery profile，覆盖：
  - undergraduate admissions
  - application requirements
  - application dates / deadlines
  - tuition / fees
  - English / international requirements
  - required documents
  - contact
  - undergraduate programmes / degrees / majors / bulletin / catalogue
- `keyword_query` 不再是启用相关排序的前置条件。
- 保留负面 signals：news、alumni、giving、jobs、staff、privacy、cookie、marketing、
  postgraduate-only、executive education。
- report 中的 relevance diagnostics 应显示使用的是内部 profile，而不是用户 keyword。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_relevance.py tests/test_discovery.py tests/test_report_cli.py
git diff --check
```

风险控制：

- 不让 programme hints 覆盖非本科上下文 gate。
- 不把 summer school、pre-university、news article 误判为本科专业目录。
- 保留 `max_pages` / `max_depth` / domain policy，不做无限 crawl。

### Step 4：Discovery 改为全局 priority frontier

修改文件：

- `university_admissions_crawler/crawler/discovery.py`
- `university_admissions_crawler/crawler/relevance.py`
- `tests/test_discovery.py`
- 必要时 `tests/test_pipeline.py`

目标：

- 用全局优先队列替代当前 deque BFS。
- 每个 candidate URL 记录 score、depth、source URL、anchor text、reason signals。
- 每轮 fetch 当前最高分 candidate，而不是只按当前页面局部排序。
- programme/admissions source 得分高于 about/news/corporate 页面。
- page budget 快耗尽时，仍优先保留高价值 admissions/programme source。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_discovery.py tests/test_pipeline.py
git diff --check
```

风险控制：

- 去重必须继续基于 canonical URL。
- 同一个 URL 不因多个入口重复抓取。
- 深度限制继续生效。
- 失败 fetch 不应阻断其他 high-score candidates。

### Step 5：Sitemap 与官方常见路径 probing

修改文件：

- `university_admissions_crawler/crawler/sitemap.py`
- `university_admissions_crawler/crawler/discovery.py`
- `university_admissions_crawler/crawler/filters.py`
- `tests/test_discovery.py`
- `tests/test_fetcher.py`

目标：

- 自动尝试公开 sitemap：
  - `/sitemap.xml`
  - `/sitemap_index.xml`
- 从 sitemap 中筛选 admissions/programme relevant URL 进入 frontier。
- 对常见官方路径做低成本 probing，例如：
  - `/admissions`
  - `/undergraduate`
  - `/undergraduate-admissions`
  - `/undergraduate-programmes`
  - `/programmes`
  - `/degree-programmes`
  - `/study/undergraduate`
  - `/catalogue`
  - `/catalog`
  - `/bulletin`
- 所有 probed URL 必须经过 domain policy、low-value filter 和 fetch/evidence 流程。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_discovery.py tests/test_fetcher.py
git diff --check
```

风险控制：

- 不把 404/403 path probe 当作事实失败，只作为 source acquisition diagnostics。
- 不写死 NUS/HKU/NTU/PolyU 特例路径。
- 不绕过 robots、登录、WAF 或验证码。

### Step 6：LLM source navigation 接入 crawl frontier

修改文件：

- `university_admissions_crawler/pipeline/source_planning.py`
- `university_admissions_crawler/extractor/llm_provider.py`
- `university_admissions_crawler/crawler/discovery.py`
- `university_admissions_crawler/crawler/filters.py`
- `university_admissions_crawler/reports/render_report.py`
- `tests/test_pipeline.py`
- `tests/test_report_cli.py`
- `tests/test_discovery.py`

目标：

- 将 source planning 从 diagnostics-only 改成 guarded frontier input。
- LLM 输入只包含：
  - homepage URL
  - 已发现的官方 links / titles / anchor text
  - sitemap/path-probe candidates
  - blocked/challenge diagnostics
  - 当前 coverage / programme catalog summary
- LLM 输出只允许：
  - candidate official URLs
  - candidate path patterns
  - expected source category
  - reason
- deterministic validator 决定能否进入 frontier：
  - 必须 HTTPS
  - 必须 allowed domain
  - 禁止 social/forum/video/redirect/tracking URL
  - 禁止 low-value source
  - 禁止 portal/login/application system
- report 显示 candidate 是否 accepted、rejected、crawled、blocked 或 budget-skipped。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_report_cli.py tests/test_discovery.py
git diff --check
```

风险控制：

- LLM accepted candidate 只是 source URL，不是 admissions fact。
- candidate 被 crawl 后，facts 仍必须来自 fetched source/evidence。
- mock-first，不在本步骤接 hosted provider。
- 如果 source planning 结果为空，crawler 应回退 deterministic frontier。

### Step 7：网络与 browser fallback 默认策略

修改文件：

- `university_admissions_crawler/cli.py`
- `university_admissions_crawler/crawler/fetcher.py`
- `university_admissions_crawler/pipeline/run_university_scan.py`
- `tests/test_fetcher.py`
- `tests/test_failure_recovery.py`
- `tests/test_report_cli.py`

目标：

- 默认 live crawl 先用 HTTP fetch。
- 如果 homepage 或 high-value source 出现 challenge/no useful links/JS-heavy signal，再 fallback
  browser fetch。
- browser 默认 `wait_until=domcontentloaded`，timeout 使用真实官网可用值。
- blocked/challenge source 继续保留并进入 diagnostics。
- 不把 browser 作为绕过 WAF 的手段；只用于正常 JS-rendered 页面。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_fetcher.py tests/test_failure_recovery.py tests/test_report_cli.py
git diff --check
```

风险控制：

- Playwright 未安装时必须 fail closed，给 warning，而不是让整个 fixture suite 依赖浏览器。
- 不把 browser fallback 引入 fixture 默认路径。
- 不隐藏 HTTP challenge 诊断。

### Step 8：模板字段 completeness diagnostics

修改文件：

- `university_admissions_crawler/pipeline/diagnostics.py`
- `university_admissions_crawler/pipeline/run_university_scan.py`
- `university_admissions_crawler/reports/render_report.py`
- `tests/test_pipeline.py`
- `tests/test_report_cli.py`

目标：

- 把 diagnostics 从“字段缺失原因”扩展为“模板完成度解释”。
- 对每个目标字段记录：
  - source_found
  - source_not_found
  - source_blocked_or_challenge
  - source_budget_skipped
  - extractor_not_attempted
  - attempted_no_match
  - context_gate_failed
  - manual_check_required
  - portal_or_login_required
- 对 programme catalog 额外记录：
  - candidate_source_count
  - crawled_catalog_source_count
  - accepted_row_count
  - raw_needs_review_count
  - probable_incomplete_catalog
- report 应告诉用户下一步该补 source discovery、LLM source navigation、extractor 还是
  manual check，而不是只显示 missing。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_report_cli.py tests/test_programme_catalog.py
git diff --check
```

风险控制：

- diagnostics 仍不能表述为“官网没有提供”，只能表述为“本次 run 没有抓到或没抽出”。
- 不把 diagnostics 写入 facts。

### Step 9：真实学校样板与 fixture-backed 回归

修改文件：

- `tests/fixtures/programme_catalog/nus/...`
- `tests/fixtures/saved_sources/hku/...`
- `tests/fixtures/saved_sources/ntu/...`
- `tests/fixtures/saved_sources/polyu/...`
- `tests/test_discovery.py`
- `tests/test_programme_catalog.py`
- `tests/test_pipeline.py`

目标：

- 用 NUS、HKU、NTU/PolyU 作为三类结构样板：
  - NUS：homepage -> OAM / Bulletin / CHS / faculty programme pages。
  - HKU：homepage/admissions -> undergraduate courses/cards。
  - NTU 或 PolyU：homepage/admissions -> programme/admissions choice table。
- 每个样板只提交最小官方 source fixture，不提交大批 live output。
- 每个 fixture 都要断言 source discovery、page category、programme catalog rows 和
  evidence path。
- live smoke 可以作为人工验证，但不作为 deterministic test 依赖。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_discovery.py tests/test_programme_catalog.py tests/test_pipeline.py
git diff --check
```

风险控制：

- 不把旧 NUS one-off CSV 当作当前 pipeline 已完全复现。
- 不因为某校 fixture 结构写学校硬编码分支。
- 不为了提高 row count 放宽到 marketing/about 页面误抽。

### Step 10：文档、README 与推荐命令重写

修改文件：

- `README.md`
- `VERSION_NOTES.zh.md`
- `PROJECT_MAP.md`
- `docs/keyword-crawl-design.zh.md`

目标：

- README 主命令改为 homepage-first 自动 crawl。
- 删除或降级所有“用户需要 keyword query / bm25-like / LLM keyword plan”的主路径描述。
- 明确 LLM 的新位置：source navigation，不生成 facts。
- 明确默认参数和高级调试参数的区别。
- VERSION_NOTES 记录 breaking/behavior change：live URL 默认 auto crawl、relevance 默认变更、
  LLM keyword optimization 裁剪。

验证方式：

```bash
rg -n "llm_keyword_plan|MockKeywordPlanProvider|keyword optimization|--keyword-query" README.md VERSION_NOTES.zh.md PROJECT_MAP.md
git diff --check
```

风险控制：

- 文档不能夸大“任意大学官网完整自动化已完成”。
- 需要把 live smoke 和 deterministic fixture-backed tests 分开描述。
- 明确不绕过 WAF、登录、验证码或申请系统。

## Phase 5 不做

- 不使用 LLM 生成招生事实、专业名、费用、申请时间或申请要求。
- 不绕过 WAF、人机验证、登录、portal 或申请系统。
- 不做无边界全站 crawl。
- 不把 live output 作为 pytest 依赖。
- 不一次性重写所有 extractor。
- 不为了减少参数而删除 fixture/debug 所需的低层控制项；低层参数可以保留，但不应作为
  推荐主路径。
- 不引入付费 hosted LLM provider 作为默认测试或默认运行依赖。

## Phase 5 完成标准

本阶段可以认为完成，当且仅当：

- 用户输入官网主页 URL 和 output dir 即可启动真实官网 scan。
- 默认 domain inference、programme/admissions relevance、合理 timeout/browser wait 生效。
- `keyword_query` 不再是主路径，LLM keyword optimization 已删除或彻底降级。
- discovery 使用全局 priority frontier，能在 page budget 内优先抓高价值招生/专业目录
  source。
- sitemap/path probing 能把公开招生/专业目录候选加入 frontier。
- LLM source navigation 的 accepted candidates 能经过 validation 后进入 frontier，并在
  report 中可审计。
- facts 和 programme catalog rows 仍全部 evidence-backed。
- report 能解释模板字段和 programme catalog 的完成度及失败层级。
- NUS/HKU/NTU 或 PolyU fixture-backed 样板通过。
- 完整 deterministic pytest 通过。
