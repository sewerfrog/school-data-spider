# 关键词爬取、诊断与 Source Planning 设计说明

## 文档定位

本文档记录当前分支的阶段性目标、复盘结论和下一阶段执行计划。上一轮
`feature/model-assisted-keyword-crawl` 已合入 `main`；当前分支已经完成字段级
缺失原因、NTU fees 边界修复样板，以及本轮 source acquisition diagnostics /
mock source planning 工作。

已完成阶段：

**Phase 3: Source Acquisition Failure and LLM-Assisted Official Source Planning**

**阶段 3：来源获取失败诊断与 LLM 辅助官方来源规划**

当前准备进入下一阶段：

**Phase 4: Programme Catalog Extraction**

**阶段 4：专业目录抽取与表格输出**

项目最终目标是自动化爬取任意大学官网招生信息的关键字段。NTU 对比说明，
当前系统已经能在字段层解释 extractor / context gate / manual check 问题；NUS
对比进一步暴露了 source acquisition 层问题：有些官网入口会返回 WAF/challenge
页面，导致 extractor 根本没有拿到可用招生文本。

阶段 3 的结论是：这批改动值得保留，但它不是一次字段覆盖率大幅提升，而是一次
诊断层和规划层能力提升。下一阶段不应继续扩 LLM 功能，也不应继续把诊断逻辑
硬塞进主流程。新的优先方向是把“大学提供的每一个细分本科专业”提升为通用核心
能力：建立独立的 programme catalog schema、extractor、diagnostics 和 CSV/table
输出。

## 当前目标与边界

本项目的长期目标是：从任意大学官网出发，自动发现官方招生来源，并抽取可追溯的
本科招生关键字段。

当前已经明确的边界：

- source 被抓到了，但内容是 WAF/challenge，不是招生页面。
- 字段缺失是 source acquisition 层失败，不是 extractor 本身没写好。
- LLM 可以辅助寻找官方替代来源，但不能绕过 WAF，也不能直接写 facts。
- 所有 facts 仍必须来自实际抓取到的官方 source、snippet 和 evidence path。
- diagnostics 只能解释“当前抓到的 source 和当前 extractor 链路发生了什么”，不能
  证明官网从未提供某字段。

## 已完成基线

以下能力已实现并应保留，不在当前阶段重写：

- evidence-first 数据流：只把有来源证据的内容写入招生 facts。
- 默认 CLI 行为仍为规则路径；关键词计划、BM25-like relevance、mock LLM provider
  都是显式 opt-in。
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
- `temp_imports/previous-session-archive/nus-live-programmes/result.json`

这两个文件内容相同。旧输出是 programme collection 格式，不是当前 CLI 的标准
admissions schema。它包含：

- 14 个 official sources
- 85 条 structured programme records
- 6 条 special programme records
- 28 个 official admissions programme choices

旧输出同时明确记录了限制：NUS simple HTTP fetch 会遇到 Incapsula/WAF/noindex
challenge，旧数据是通过 browser/search extraction 和官方页面交叉核验得到的。

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

建议保留本轮 diff，理由是：

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

## Phase 4 当前任务目标

Phase 4 的目标是把“细分专业目录抽取”作为本项目的通用核心能力，而不是继续把它
塞进现有 admissions core field 的 `programmes` 里。

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

因此 Phase 4 应把系统核心能力拆成两条主线：

1. Admissions Facts Extraction：继续负责申请时间、费用、资格、材料、英语要求、
   联系方式等招生事实字段。
2. Programme Catalog Extraction：新增独立 schema、parser、diagnostics 和 CSV/table
   输出，负责大学本科专业目录、细分专业和所属学院/学制/degree/admissions choice。

## 目标输出形态

Phase 4 最终应生成：

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

## Phase 4 执行计划

### Step 1：定义 Programme Catalog Schema

修改文件：

- `university_admissions_crawler/extractor/schema.py`
- `tests/test_schema_evidence.py`

目标：

- 新增 `ProgrammeCatalogRecord`，不要直接大改现有 `ProgrammeRecord`。
- 在 `AdmissionsData` 上新增 `programme_catalog: list[ProgrammeCatalogRecord]`。
- 保留现有 `programmes` 字段，作为 admissions 摘要和兼容字段。
- 字段先覆盖旧 NUS CSV 已验证过的最小集合：
  - `name`
  - `faculty_or_school`
  - `degree_or_award`
  - `category`
  - `mode`
  - `duration_or_units`
  - `admissions_choice_name`
  - `specialisations_or_majors`
  - `source_url`
  - `evidence_snippet`
  - `evidence_confidence`
  - `parse_status`
  - `warnings`

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_schema_evidence.py
git diff --check
```

风险控制：

- 不删除或重命名 `ProgrammeRecord`。
- 不改变 `coverage.programmes` 的现有语义。
- 没有 source/snippet/evidence path 的专业不能进入 catalog。

### Step 2：固定 NUS Programme Catalog 目标样板

修改文件：

- `tests/fixtures/programme_catalog/nus/...`
- `tests/test_programme_catalog.py`

目标：

- 从旧 `outputs/nus-live-programmes/` 或
  `temp_imports/previous-session-archive/nus-live-programmes/` 中抽取最小官方 source
  fixture。
- 不要求一开始复现旧 CSV 全部 91 行。
- 先固定 3 类代表记录：
  - degree programme，例如 Business、Computing、Engineering。
  - major / specialisation，例如 BBA majors 或 CHS majors。
  - special programme，例如 NUS College。
- 测试必须断言 row value、source URL、evidence snippet 和 parse status。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_programme_catalog.py
git diff --check
```

风险控制：

- 旧 NUS CSV 只能作为 expected contract，不能当作当前通用 pipeline 已实现能力。
- fixture 必须来自官方 source，不用 LLM 生成专业事实。
- 不提交新的 live output。

### Step 3：实现结构化 Programme Catalog Parser

修改文件：

- 新增 `university_admissions_crawler/extractor/programme_catalog.py`
- 小范围接入 `university_admissions_crawler/pipeline/run_university_scan.py`
- `tests/test_programme_catalog.py`
- 必要时 `tests/test_pipeline.py`

目标：

- 新 parser 输出 `ProgrammeCatalogRecord`，不直接替代旧 `extract_programmes()`。
- 支持第一批明确结构：
  - programme index page
  - faculty/school undergraduate education page
  - card/grid programme list
  - table/list text
  - headings + following list
- 对无法稳定归类的记录使用 `raw_needs_manual_review` 或 row-level warning。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_programme_catalog.py tests/test_pipeline.py
git diff --check
```

风险控制：

- 不继续扩大 `extract_programmes()` 的 regex 职责。
- 不为了多抽而放宽到任意包含 Bachelor 的营销句子。
- 不把 major/minor/special programme 强行写成 degree programme。

### Step 4：Programme Source Discovery 优化

修改文件：

- `university_admissions_crawler/classifier/page_classifier.py`
- `university_admissions_crawler/crawler/discovery.py`
- `university_admissions_crawler/crawler/relevance.py`
- `tests/test_classifier.py`
- `tests/test_discovery.py`

目标：

- 让 crawler 更容易发现专业目录来源，而不是只停留在 general admissions 页面。
- 增强 programme source signals：
  - `/programmes/`
  - `/undergraduate-programmes`
  - `/undergraduate-education`
  - `/degree-programmes`
  - `/majors`
  - `/minors`
  - `/bulletin`
  - `/catalogue`
  - `/study/undergraduate`
- 继续受 `max_pages`、`max_depth`、allowed domain 和 source filtering 约束。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_classifier.py tests/test_discovery.py tests/test_pipeline.py
git diff --check
```

风险控制：

- 不做无边界全站 crawl。
- 不把 news、alumni、marketing、summer/pre-university programme 页面误判为本科专业目录。
- `accepted_candidate_urls` 仍只是 diagnostics 候选，是否进入 crawl frontier 需要未来阶段单独设计。

### Step 5：CSV / Table 输出

修改文件：

- 新增 `university_admissions_crawler/reports/programme_catalog_csv.py`
- `university_admissions_crawler/pipeline/output_writer.py`
- `tests/test_report_cli.py` 或新增 `tests/test_programme_catalog_output.py`

目标：

- 当 `programme_catalog` 非空时输出：
  - `programme_catalog.csv`
  - 可选 `programme_catalog.json`
- CSV 字段顺序固定。
- Markdown report 只展示 summary 和 diagnostics，不把完整表格塞进 facts。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_report_cli.py tests/test_programme_catalog_output.py
git diff --check
```

风险控制：

- 不破坏现有 `result.json`、`report.md` 输出。
- 空 catalog 时不生成误导性的“成功表格”。
- CSV 行必须来自 evidence-backed catalog records。

### Step 6：Programme Catalog Diagnostics

修改文件：

- `university_admissions_crawler/pipeline/diagnostics.py`
- `university_admissions_crawler/reports/render_report.py`
- `tests/test_programme_catalog.py`
- `tests/test_report_cli.py`

目标：

- 在 `run.config` 中新增 `programme_catalog_summary`，至少包含：
  - `candidate_count`
  - `accepted_count`
  - `rejected_count`
  - `duplicate_count`
  - `by_programme_type`
  - `by_faculty_or_school`
  - `parse_status_counts`
  - `sources_count`
  - `source_urls`
- report 在 facts 前或 programme catalog summary 区展示这些 diagnostics。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_programme_catalog.py tests/test_report_cli.py
git diff --check
```

风险控制：

- diagnostics 只解释抽取过程，不证明官网没有提供专业。
- 不把 rejected/ambiguous candidate 渲染成正式专业行。

### Step 7：NUS 端到端样板

修改文件：

- `tests/fixtures/programme_catalog/nus/...`
- `tests/test_programme_catalog.py`
- 必要时 `configs/` 增加示例配置，但不提交 live output。

目标：

- 用 NUS 做第一所完整样板，因为已有旧 CSV 可做目标参考。
- 第一阶段不要求完全复现旧 91 行，但要稳定覆盖：
  - Business / Computing / CDE / CHS 代表性专业。
  - degree programme、major/specialisation、special programme 的区分。
  - row-level source/evidence。
  - `programme_catalog.csv` 输出。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_programme_catalog.py tests/test_pipeline.py tests/test_report_cli.py
git diff --check
```

风险控制：

- NUS live 如果遇到 WAF/challenge，以 fixture test 为准。
- 不把旧 NUS one-off result 直接搬成当前 output。

### Step 8：HKU / NTU / PolyU 泛化样板

修改文件：

- `tests/fixtures/saved_sources/hku/...`
- `tests/fixtures/saved_sources/ntu/...`
- `tests/fixtures/saved_sources/polyu/...`
- `tests/test_programme_catalog.py`

目标：

- 每所学校先选择一个真实 programme catalog source。
- HKU：现有 source 中有 “UNDERGRADUATE COURSES” 卡片列表，可先抽 programme code、
  faculty、study period、type。
- NTU：优先找明确 undergraduate programmes 或 admissions choices 页面，不从申请说明
  长文里误抽。
- PolyU：解决当前 `programmes=0` 的空白，至少固定一个 programme list source。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_programme_catalog.py tests/test_classifier.py tests/test_discovery.py
git diff --check
```

风险控制：

- 每所学校只加最小 fixture，不引入大批 generated outputs。
- 不要求一次覆盖所有院系。
- 避免学校硬编码大分支；优先抽共通结构 helper。

### Step 9：去重、归一化与质量控制

修改文件：

- `university_admissions_crawler/extractor/programme_catalog.py`
- 可选新增 `university_admissions_crawler/extractor/programme_normalizer.py`
- `tests/test_programme_catalog.py`

目标：

- 建立 normalized key：
  - lowercased name
  - degree/award
  - faculty/school
  - source URL
- 输出 row-level warnings：
  - `duplicate_name`
  - `ambiguous_degree`
  - `missing_faculty`
  - `category_inferred`
  - `raw_needs_manual_review`
- 不静默删除重复项，先标记。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_programme_catalog.py
git diff --check
```

风险控制：

- 不把 admissions A-Z choice 和 academic programme 混为一类。
- 不把同名不同 award 的记录合并。

### Step 10：可选 LLM 辅助，只做分类提示

修改文件：

- `university_admissions_crawler/extractor/llm_provider.py`
- `tests/fixtures/llm/...`
- `tests/test_programme_catalog.py`

目标：

- 只有 deterministic parser 无法区分 category 时，LLM 可以给 category hint。
- LLM 只对已抓到 source text 中的 candidate 做分类辅助，例如：
  - degree programme vs major
  - special programme vs admissions pathway
  - full-time vs part-time
- LLM 不生成 programme facts，不补 source 里不存在的专业名。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_programme_catalog.py tests/test_compatibility_boundaries.py
git diff --check
```

风险控制：

- 默认关闭。
- mock-first。
- 不接 hosted provider。
- 仍必须 evidence/snippet 对齐。

## Phase 4 不做

- 不把 programme catalog 继续塞进现有 `coverage.programmes = found/missing` 语义里。
- 不删除现有 `ProgrammeRecord` 或旧 `programmes` 字段。
- 不把旧 NUS one-off CSV 当作当前通用 pipeline 的已实现能力。
- 不自动 follow `accepted_candidate_urls`。
- 不使用 LLM 生成专业事实。
- 不绕过 WAF、人机验证、登录或申请系统。
- 不刷新或提交大批 `outputs/` 历史产物。
- 不做无关格式化、依赖升级或全仓重排。

原 Phase 4 的单字段 extractor 修复计划暂时降级为后续候选任务。NTU application
period、NTU fees table、required documents 和 application entry 仍重要，但应在
Programme Catalog 这条主线建立后再继续小步处理。

## Phase 4 完成标准

本阶段可以认为完成，当且仅当：

- `result.json` 有 evidence-backed `programme_catalog`。
- scan 输出 `programme_catalog.csv`，字段顺序稳定。
- NUS fixture-backed 样板能覆盖 degree programme、major/specialisation 和 special
  programme。
- 至少一个 HKU/NTU/PolyU 样板证明 parser 不只是 NUS 特例。
- 每条 catalog row 有 source URL、evidence snippet、parse status 和必要 warnings。
- `programme_catalog_summary` 能解释候选数、接受数、重复数、分类分布和 source 分布。
- 现有 admissions facts、source planning、classification assist、LLM keyword plan 仍
  保持 evidence-first / diagnostics-only 边界。
- 完整 deterministic 测试通过。
