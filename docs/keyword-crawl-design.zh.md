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

**Phase 5: Homepage-First Automatic Admissions Crawl**

**阶段 5：官网主页优先的自动招生信息爬取**

当前待执行的工程化需求：

**Next Step: OpenAI Local Configuration Standardization**

**下一步：OpenAI 本地配置标准化**

后续功能规划：

**Phase 6: LLM Structured Extraction Fallback**

**阶段 6：LLM 结构化抽取候选 fallback**

阶段 3/4/5 的结论是：diagnostics、missing reasons、blocked/challenge detection、
programme catalog schema、CSV 输出、homepage-first discovery、priority frontier、
sitemap/path probing、guarded source planning frontier hint 和真实 OpenAI provider 都值得
保留。当前主链路已经从“用户用 keyword 引导 crawler”推进到“输入官网主页后，由内部
profile 自动优先发现招生和专业目录 source”。

当前仍需处理的问题已经不是 Phase 5 的 source acquisition 基线，而是：

- OpenAI 本地配置标准化已经完成：`.env.example`、`.gitignore`、README、
  版本说明和 `.env.example` 模板安全测试已对齐。
- 真实 OpenAI provider 已接入 guarded source planning、classification assist、
  programme catalog hint 和 Phase 6 structured extraction fallback；OpenAI 仍只产生
  source/candidate，不直接成为 facts authority。
- 字段覆盖率仍取决于真实站点结构、source acquisition、context gate 和 extractor；
  diagnostics 只能解释本次 run 的失败层级，不能证明官网从未提供某字段。
- `run_university_scan.py` 的插桩仍偏重，后续新增复杂诊断前应优先抽小 helper/tracer。

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
- `--enable-source-planning` 已接入 guarded LLM source planning。fixture/debug 模式仍需
  显式配合 `--enable-llm`；非 fixture live 默认启用 LLM-assisted source planning，
  `--llm-provider auto` 会在 `OPENAI_API_KEY` 存在时使用 OpenAI，否则记录 provider
  `none` 并继续 deterministic crawl。
- `llm_source_plan` 会写入 `run.config` diagnostics；accepted candidate URL 经过
  deterministic validation 后可以作为 bounded crawl frontier hint，但不会直接写 facts，
  不绕过 WAF。
- LLM candidate URL 会经过 deterministic validation，accepted/rejected 都可审计；
  accepted candidate 只影响 bounded source acquisition，不是 admissions facts。
- Markdown report 已在 facts 前展示 `Source Planning Diagnostics`，并明确说明它不是
  admissions facts。
- `run_university_scan.py` 当前不继续膨胀；已有 diagnostics recorder 能覆盖当前
  诊断写入需求。

这些能力提升的是排查能力，不等于字段覆盖率已经解决。coverage 仍取决于 source
selection、source acquisition、context gate、extractor 和真实站点结构。

Phase 5 已完成的裁剪和改造：

- `--keyword-query` 已降级为 deterministic debug input，不再是推荐主入口。
- LLM keyword plan / keyword optimization 已从主流程移除，不再作为文档化产品能力。
- `admissions_programme_profile` 已成为默认 relevance strategy；`bm25-like` 和
  `rule-based` 只保留为显式兼容/调试路径。
- Discovery 已使用全局 priority frontier，避免 page budget 被低价值 about/news/corporate
  页面优先消耗。
- Sitemap probing、常见官方路径 probing 和 extra candidates 已进入 priority frontier。
- `--enable-source-planning` 仍是显式 guarded opt-in，但 accepted candidate URL 经过
  deterministic validation 后可以作为 bounded crawl frontier hint；它们不会直接写
  admissions facts。

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

- `accepted_candidate_urls` 已从纯诊断候选升级为 bounded crawl frontier hint；它们仍不
  写 facts，实际抓取状态通过 `applied_candidate_urls`、`budget_skipped_candidate_urls`
  和每个 candidate 的 `crawl_status` 审计。
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
5. 增加 source-plan candidate URL validation；当时 accepted/rejected 只进入
   diagnostics，后续 Phase 5 已把 accepted URL 接成 bounded crawl frontier hint。
6. 在 `reports/render_report.py` 中于 facts 前展示 `Source Planning Diagnostics`。
7. 用 NUS mock source plan fixture 固定候选 URL 不写 facts 的边界；后续测试改为
   同时覆盖 crawled / budget-skipped crawl status。
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

## Phase 5 已完成基线

Phase 5 的目标是把项目从“需要用户理解内部参数的 crawler”改成“输入官网主页即可
自动尝试完成招生模板”的 crawler。当前推荐命令形态已经收敛为：

```bash
.venv314/bin/python -m university_admissions_crawler.cli https://www.example.edu/ \
  --output-dir outputs/example-auto
```

本阶段已完成内容压缩如下：

1. 非 fixture URL 默认进入 live homepage-first scan，`--auto` 和 `--enable-live-network`
   只保留为兼容 flag。
2. 默认从输入 URL 推断官方 allowed domain，并保留 `--allowed-domain` /
   `--allowed-host` 作为高级控制。
3. live 默认参数已收敛为更适合真实官网的 `max_pages=80`、`max_depth=4`、
   `timeout_seconds=60`；`--smoke` 继续用于小预算验证。
4. `admissions_programme_profile` 已成为默认 relevance strategy，覆盖本科招生、申请
   要求、日期、费用、英语/国际要求、材料、联系方式和专业目录 source。
5. `--keyword-query` 已降级为 deterministic debug input；LLM keyword optimization 已从
   主流程移除。
6. Discovery 已从单页局部排序的 BFS/deque 改成全局 priority frontier，并记录候选 URL 的
   score、depth、source URL、anchor text 和 reason signals。
7. Sitemap probing、常见官方路径 probing 和 extra candidates 已能进入 priority
   frontier；404/403 path probe 不会被当作事实失败。
8. Guarded LLM source planning 已从纯 diagnostics 升级为 bounded crawl frontier hint：
   accepted candidate URL 必须先通过 HTTPS、allowed domain、low-value/source-value 等
   deterministic validation。
9. Markdown report 已显示 source planning enabled/triggered/applied、accepted/rejected、
   crawled/budget-skipped candidate URL；candidate URL 不直接生成 admissions facts。
10. Template completeness diagnostics 已能区分 source_not_found、source_blocked_or_challenge、
    source_budget_skipped、extractor_not_attempted、attempted_no_match、context_gate_failed、
    manual_check_required 和 portal_or_login_required 等失败层级。
11. NUS、HKU、NTU、PolyU saved-source pipeline 样板已覆盖 source discovery、page category、
    programme catalog rows 和 evidence path，未加入学校硬编码分支。
12. OpenAI provider 已接入 guarded source planning、low-confidence classification assist、
    captured programme row category/mode hint 和 structured extraction fallback；mock provider
    仍用于 deterministic offline tests。Anthropic/Gemini 仍 fail closed。
13. 非 fixture HTTP(S) 输入已切换为默认 LLM-assisted crawler：source planning、
    classification assist 和 structured extraction fallback 默认开启；`--llm-provider auto`
    在存在 `OPENAI_API_KEY` 时解析为 OpenAI，没有可用 provider 时记录
    `llm_runtime.provider = none` 并继续 deterministic crawl。`--no-llm` /
    `--deterministic-only` 是显式关闭入口。

当前仍然保留的边界：

- 不使用 LLM 直接生成招生事实、专业名、费用、申请时间或申请要求。
- 不绕过 WAF、人机验证、登录、portal 或申请系统。
- 不做无边界全站 crawl。
- 不把 live output 作为 pytest 依赖。
- 不一次性重写所有 extractor。
- 不把 hosted LLM 作为 deterministic test 依赖；live 默认可以启用 LLM-assisted crawler，
  但 provider 不可用时必须 fail closed / degrade to deterministic crawl。
- 所有 admissions facts 和 programme catalog rows 仍必须有 captured official source、
  snippet 和 evidence path。

最近验证状态：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
# 176 passed

env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m compileall -q university_admissions_crawler tests
# passed

git diff --check
# passed
```

当前实现仍不是“任意大学官网完整字段覆盖”的生产级闭环。Phase 5 解决的是默认
source acquisition、priority discovery、programme catalog baseline、source planning
frontier 和 diagnostics 可审计性；字段覆盖率仍取决于真实站点结构、context gate 和
extractor 能力。

## Next Step：OpenAI Local Configuration Standardization

当前真实 OpenAI provider 已经可用。本阶段按团队项目标准化方式处理 API key 配置，
不引入新运行时依赖，不把真实 credentials 写入仓库，也不改变 evidence-first 运行边界。

当前状态：

- Step 1 已完成：`.gitignore` 已忽略 `.env` / `.env.*`，并保留 `.env.example` 可提交。
- Step 2 已完成：已新增 `.env.example`，只包含 `OPENAI_API_KEY=` 和
  `OPENAI_MODEL=gpt-4.1-mini`。
- Step 3 已完成：`README.md` 已加入团队本地配置流程，并说明 CLI 不自动读取 `.env`。
- Step 4 已完成：`VERSION_NOTES.zh.md` 和本文档已同步 OpenAI 本地配置边界。
- Step 5 已完成：已增加 `.env.example` 模板安全测试。

### Step 1：检查并补齐本地 secret 忽略规则（已完成）

修改文件：

- `.gitignore`

目标：

- 确认 `.env` 和 `.env.*` 被忽略。
- 明确保留 `.env.example` 可提交。
- 不忽略 README、docs、tests 或 outputs 中已有普通文件。

建议规则：

```gitignore
# Local secrets
.env
.env.*
!.env.example
```

验证方式：

```bash
git check-ignore -v .env
git check-ignore -v .env.example || true
git diff --check
```

风险控制：

- 不提交真实 `.env`。
- 不把 `.env.example` 误加入 ignore。

### Step 2：新增 `.env.example`（已完成）

修改文件：

- `.env.example`

目标：

- 提供团队共享的本地配置模板。
- 只包含变量名和安全默认模型，不包含真实 key 或 `sk-...` 示例。

建议内容：

```bash
# Copy this file to .env for local development.
# Never commit real API keys.

OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
```

验证方式：

```bash
git diff -- .env.example
rg -n "sk-" .env.example README.md VERSION_NOTES.zh.md docs/keyword-crawl-design.zh.md
```

风险控制：

- `.env.example` 是模板，不是运行证据，不进入 outputs 或 diagnostics。
- 不在 fixture、测试输出或 commit message 中放真实 key。

### Step 3：更新 README 的 OpenAI 本地配置流程（已完成）

修改文件：

- `README.md`

目标：

- 说明团队标准流程：
  - `cp .env.example .env`
  - 编辑 `.env`
  - 用 `set -a; source .env; set +a` 加载到当前 shell。
  - 用不打印 key 的命令验证环境变量是否存在。
- 明确代码仍读取 `OPENAI_API_KEY` / `OPENAI_MODEL` 环境变量。
- 明确 OpenAI 只用于 guarded source planning、classification assist 和 programme catalog
  hint，不直接写 admissions facts。

验证方式：

```bash
rg -n "env.example|OPENAI_API_KEY|OPENAI_MODEL|llm-provider openai" README.md
git diff --check
```

风险控制：

- 不承诺 CLI 自动读取 `.env`；当前阶段只是标准化模板和加载流程。
- 不把真实 key 写进 README。

### Step 4：同步版本说明和设计文档（已完成）

修改文件：

- `VERSION_NOTES.zh.md`
- `docs/keyword-crawl-design.zh.md`

目标：

- 记录 `.env.example` + 本地 `.env` 的团队配置方式。
- 说明 `.env` 是本地 secret，不是 crawler 输入、不是 evidence source、不会写 facts。
- 说明缺少 `OPENAI_API_KEY` 时 OpenAI provider fail closed 到 diagnostics，不中断整次 run。

验证方式：

```bash
rg -n "env.example|OPENAI_API_KEY|OPENAI_MODEL|fail closed" VERSION_NOTES.zh.md docs/keyword-crawl-design.zh.md
git diff --check
```

风险控制：

- 不把 OpenAI 配置标准化写成 Phase 6 structured extraction 已完成。
- 不改变真实模型使用边界。

### Step 5：增加配置模板安全测试

修改文件：

- `tests/test_openai_provider.py`

目标：

- 增加轻量测试，确认 `.env.example` 存在并包含 `OPENAI_API_KEY=` /
  `OPENAI_MODEL=gpt-4.1-mini`。
- 确认 `.env.example` 不包含明显真实 key 片段，例如 `sk-`。
- 不调用真实 OpenAI API，不读取本地 `.env`。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_openai_provider.py
git diff --check
```

风险控制：

- 测试只检查模板安全性，不依赖用户本机是否配置了真实 key。
- 不把 git 命令作为 pytest 依赖；`.gitignore` 行为用手动验证命令确认。

## Phase 6：LLM Structured Extraction Fallback

Phase 6 的目标是在 Phase 5 homepage-first source acquisition 基础上，增加一个
evidence-first 的 LLM structured extraction fallback。它解决的问题不是“让 LLM 编写招生
事实”，而是在 crawler 已经抓到并保存官方 source text / markdown 后，让 LLM 帮助从这些
source 中提出结构化候选值，再由 deterministic validation 决定候选值是否能进入结果。

这一步的核心边界：

- deterministic extractor 仍是主路径。
- LLM structured extraction 只在字段 missing、extractor no_match、context gate 不确定、
  或 programme catalog candidate rows 需要补全时作为 fallback。
- LLM 不能访问未抓取页面，不能根据常识补全，不能引用没有保存进 run 的 source。
- LLM 输出不是 admissions fact，只是 candidate fact。
- 每个 candidate fact 必须带有 `claim_path`、`value`、`evidence_snippet`、`source_url`、
  `confidence`。
- candidate 只有通过 deterministic validation 后，才能进入 result；否则只进入
  diagnostics / warnings。
- report 必须明确区分 deterministic facts、validated LLM fallback facts、rejected LLM
  candidates。

### Phase 6 数据流

Phase 6 的目标数据流是：

1. homepage-first crawler 获取并保存官方 source。
2. deterministic extractors 先尝试抽取 core fields 和 programme catalog。
3. pipeline 根据 `missing_reasons`、`extraction_diagnostics_summary` 和 programme catalog
   completeness 选择少量高价值 source text 作为 LLM fallback 输入。
4. LLM provider 返回 candidate facts。
5. deterministic validator 校验每个 candidate：
   - `source_url` 必须属于本次 run 已抓到的 official source。
   - `source_url` 必须通过 domain policy，不是 social/forum/video/portal/login/redirect。
   - `claim_path` 必须属于允许写入的 schema path。
   - `evidence_snippet` 必须原文存在于 captured source text / markdown。
   - `value` 必须原文存在于 `evidence_snippet`，或满足字段级可验证 normalization 规则。
   - `confidence` 必须在允许范围内，例如 `0.0 <= confidence <= 1.0`。
   - 字段上下文必须通过 deterministic gate，例如 undergraduate / international /
     admissions / programme context。
6. 通过 validation 的 candidate 才能进入 result，并标记 extraction method 为
   `llm_fallback_validated`。
7. 未通过 validation 的 candidate 写入 diagnostics / warnings，保留 reject reason。

### Candidate Fact Schema

LLM structured extraction 的最小 candidate fact schema：

```json
{
  "claim_path": "admissions.application_period",
  "value": "Applications open from 1 February to 19 March 2026",
  "evidence_snippet": "Applications open from 1 February to 19 March 2026 for undergraduate admissions.",
  "source_url": "https://www.example.edu/admissions/undergraduate",
  "confidence": 0.78
}
```

可选诊断字段：

- `reason`
- `source_title`
- `candidate_type`
- `normalization_hint`

这些可选字段不能作为事实依据；事实依据仍只能是 `source_url` 和 `evidence_snippet`。

允许写入的 `claim_path` 必须显式白名单化。第一版建议只覆盖：

- `admissions.application_period`
- `admissions.application_deadline`
- `admissions.application_entry`
- `admissions.requirements.academic`
- `admissions.requirements.english`
- `admissions.required_documents`
- `admissions.fees`
- `admissions.scholarships`
- `admissions.contact`
- `programme_catalog[].name`
- `programme_catalog[].degree`
- `programme_catalog[].faculty_or_school`
- `programme_catalog[].duration`
- `programme_catalog[].entry_requirements`
- `programme_catalog[].source_url`

不允许第一版写入：

- ranking、就业率、薪资、课程评价等非招生模板字段。
- LLM 推断出来但 source 没有明确写出的字段。
- 需要登录 portal 才能确认的字段。
- 需要跨页面综合推理但没有单条 snippet 支撑的字段。

### Step 1：定义 LLM candidate fact schema 和 provider boundary

修改文件：

- `university_admissions_crawler/extractor/llm_provider.py`
- `tests/test_llm_provider.py`
- 必要时新增 `university_admissions_crawler/extractor/llm_structured_extraction.py`

目标：

- 增加 `StructuredExtractionProvider` / `MockStructuredExtractionProvider`。
- 定义 `LLMStructuredCandidateFact` dataclass 或等价结构。
- provider 输入只接受 captured official source 的 text / markdown 摘要和允许 claim paths。
- provider 输出只允许 candidate facts，不允许直接修改 `result.json`。
- mock provider 支持 deterministic fixture payload，便于测试 validation plumbing。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_llm_provider.py
git diff --check
```

风险控制：

- 不在本步骤接 hosted provider。
- 不让 provider 接收 arbitrary URL 或未抓取 source。
- schema 中 required keys 缺失时必须 fail closed。

### Step 2：实现 deterministic candidate validator

修改文件：

- `university_admissions_crawler/evidence/validator.py`
- `university_admissions_crawler/pipeline/diagnostics.py`
- `tests/test_evidence.py`
- `tests/test_pipeline.py`

目标：

- 实现 `validate_llm_candidate_fact()`。
- 校验 captured source membership、domain policy、allowed claim path、snippet containment、
  value containment、confidence range 和字段级 context gate。
- 返回 accepted candidate 或 rejected diagnostic，不抛出影响整次 run 的异常。
- reject reason 至少覆盖：
  - `source_not_captured`
  - `source_not_official`
  - `claim_path_not_allowed`
  - `snippet_not_found`
  - `value_not_in_snippet`
  - `context_gate_failed`
  - `low_confidence`
  - `malformed_candidate`

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_evidence.py tests/test_pipeline.py
git diff --check
```

风险控制：

- snippet containment 必须基于本次 run 保存的 source text / markdown，不依赖 live refetch。
- 不因为 LLM confidence 高就跳过 deterministic validation。
- 对 normalization 只开放字段级白名单，例如货币空格、日期标点、大小写差异。

### Step 3：pipeline 中接入 fallback 触发条件

修改文件：

- `university_admissions_crawler/pipeline/run_university_scan.py`
- `university_admissions_crawler/pipeline/diagnostics.py`
- `university_admissions_crawler/config_loader.py`
- `university_admissions_crawler/cli.py`
- `tests/test_pipeline.py`
- `tests/test_report_cli.py`

目标：

- 增加显式 guarded flag，例如 `--enable-llm-structured-extraction`。
- 只有在 `--enable-llm` 且 provider 可用时才允许触发。
- 触发条件基于本次 run 结果：
  - core field missing 且有相关 official source。
  - extractor attempted_no_match。
  - programme catalog probable_incomplete。
  - source 已抓到但 deterministic extractor 覆盖不足。
- LLM fallback 输入应按 source 价值和 token budget 裁剪，优先 admissions/programme high-value
  source。
- fallback 不应改变 discovery、fetch、domain policy 或 source filtering。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_report_cli.py
git diff --check
```

风险控制：

- live 默认启用 LLM-assisted crawler，但 hosted provider 不可用时必须 fail closed 并继续
  deterministic crawl。
- mock-first，fixture tests 不依赖网络或付费 API。
- fallback 只处理已经保存的 source，不新增 crawl。

### Step 4：validated candidate 写入 result 与 evidence

修改文件：

- `university_admissions_crawler/pipeline/run_university_scan.py`
- `university_admissions_crawler/evidence/validator.py`
- `university_admissions_crawler/extractor/programme_catalog.py`
- `tests/test_pipeline.py`
- `tests/test_programme_catalog.py`

目标：

- accepted candidate 写入对应 claim path。
- 写入时保留 provenance：
  - `source_url`
  - `evidence_snippet`
  - `extractor = llm_fallback_validated`
  - `confidence`
  - `validation_status = accepted`
- 如果 deterministic extractor 已经给出字段值，LLM fallback 不覆盖现有值，只进入
  diagnostics 或 alternative candidate。
- programme catalog row 需要 row-level evidence，不允许只凭页面标题生成 row。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_programme_catalog.py
git diff --check
```

风险控制：

- 不让 LLM fallback 覆盖 deterministic accepted facts。
- 对 list 字段要去重，避免同一 snippet 生成重复 row。
- 如果 candidate 部分通过、部分失败，只写通过部分，失败部分保留 reject diagnostics。

### Step 5：report 中增加 LLM fallback diagnostics

修改文件：

- `university_admissions_crawler/reports/render_report.py`
- `tests/test_report_cli.py`

目标：

- 在 `Facts` 前增加或扩展 diagnostics section，显示：
  - fallback enabled / triggered / provider。
  - candidate count。
  - accepted count。
  - rejected count。
  - reject reasons summary。
  - accepted claim paths。
  - source URLs used。
- Facts 区域中如果字段来自 LLM fallback，必须标记为
  `llm_fallback_validated`，并显示 evidence snippet。
- rejected candidates 不进入 Facts。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_report_cli.py
git diff --check
```

风险控制：

- report 不能把 LLM fallback 描述成“模型确认事实”。
- diagnostics 应帮助判断是 extractor 需要补强，还是 LLM candidate 被 validator 拒绝。

### Step 6：fixture-backed 学校样板

修改文件：

- `tests/fixtures/llm_structured_extraction/...`
- `tests/test_pipeline.py`
- `tests/test_programme_catalog.py`
- `tests/test_report_cli.py`

目标：

- 增加最小 fixture，覆盖：
  - deterministic extractor no_match，但 source text 中有明确字段。
  - LLM candidate snippet 不存在，被拒绝。
  - LLM candidate value 不在 snippet，被拒绝。
  - LLM candidate source_url 未被本次 run 抓到，被拒绝。
  - programme catalog row 通过 validated snippet 进入 CSV/result。
- 优先选 NUS/NTU/HKU 中已保存过的官方 source 片段做最小 fixture，不提交大批 live output。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_programme_catalog.py tests/test_report_cli.py
git diff --check
```

风险控制：

- 不用 live network 作为测试依赖。
- 不为了测试方便放宽 evidence validator。
- 不加入学校特例逻辑。

### Step 7：文档与用户命令边界

修改文件：

- `README.md`
- `VERSION_NOTES.zh.md`
- `PROJECT_MAP.md`
- `docs/keyword-crawl-design.zh.md`

目标：

- README 继续保持 homepage-first 自动 crawl 为主命令，并说明 live 默认是
  LLM-assisted evidence-first crawler。
- LLM structured extraction 是默认 live assisted crawler 的 fallback 层，但不是 facts
  authority；deterministic validation 仍决定是否写入 result。
- 文档明确：
  - LLM 不生成事实。
  - LLM 只从 captured official source 里提出 candidates。
  - deterministic validation 决定是否进入 result。
  - rejected candidates 会进入 diagnostics。
- VERSION_NOTES 记录 Phase 6 的 capability boundary 和风险控制。

验证方式：

```bash
rg -n "LLM structured|llm_fallback_validated|candidate fact|evidence-first" README.md VERSION_NOTES.zh.md PROJECT_MAP.md docs/keyword-crawl-design.zh.md
git diff --check
```

风险控制：

- 不把 Phase 6 写成任意大学 100% 自动完整抽取。
- 不承诺 hosted LLM 在所有学校上稳定提升覆盖率。
- 不弱化“无法验证则 unknown / needs_manual_check”的原则。

## Phase 6 不做

- 不让 LLM crawl 新页面。
- 不让 LLM 绕过 source navigation validator、domain policy、WAF、portal、login 或验证码。
- 不让 LLM 根据常识、搜索结果或未抓取页面生成事实。
- 不让 LLM 覆盖 deterministic accepted facts。
- 不把 confidence 当作 evidence。
- 不把 rejected candidates 写入 facts 或 programme CSV。
- 不把 hosted LLM 作为 deterministic test 依赖。

## Phase 6 完成标准

本阶段可以认为完成，当且仅当：

- LLM structured extraction provider 和 mock provider 有清晰 schema。
- 每个 candidate fact 都包含 `claim_path`、`value`、`evidence_snippet`、`source_url`、
  `confidence`。
- deterministic validator 能拒绝 source 未抓取、snippet 不存在、value 不在 snippet、
  claim path 不允许、context gate 失败、confidence 不合法的 candidate。
- accepted candidate 能进入 result，并保留 `llm_fallback_validated` provenance。
- rejected candidate 只进入 diagnostics / warnings。
- deterministic extractor 已有值时，LLM fallback 不覆盖。
- programme catalog row 可以通过 validated snippet 补入，但必须有 row-level evidence。
- report 在 Facts 前显示 LLM fallback diagnostics。
- README / VERSION_NOTES / PROJECT_MAP 对能力边界描述一致。
- 完整 deterministic pytest 通过。
