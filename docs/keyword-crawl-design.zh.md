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

近期已完成的工程化需求：

**Completed: OpenAI Local Configuration Standardization**

**已完成：OpenAI 本地配置标准化**

已完成并继续硬化的功能规划：

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

## 当前技术债修理方案与执行状态

本节基于 2026-07-02 对当前仓库的只读架构审计，目标是把最危险的三类债务拆成可执行、可验证、低回归风险的工程方案。

当前执行状态：

- 债务 1 已按“先拆 orchestration、冻结外部契约”的方向完成首轮代码清理：`run_university_scan.py` 保留扫描编排，category-routed extraction 与 guarded structured fallback 已迁出到独立 pipeline 模块。
- 债务 2 已完成能力边界显式化：`field_capability_matrix`、canonical `missing_reasons`、`action_target` 和 Markdown capability 说明已经接入 diagnostics/report/tests。为降低兼容风险，`missing_reasons[*].reason` 保持旧诊断标签，新的行动分类写入 `missing_reasons[*].canonical_reason`。
- 债务 3 尚未执行代码修改；本节只保留其契约治理方案，处理前需先做接口、schema 字段、compatibility alias 和文档状态盘点。

### 债务 1：`run_university_scan.py` 编排层过重

证据：

- `university_admissions_crawler/pipeline/run_university_scan.py` 同时承担 discovery 调用、source 持久化、HTML/JSON/PDF 分流、页面分类、`source_strategy` 二次候选抓取、coverage diagnostics、core supplement、LLM structured fallback 和最终补诊断。
- `run_scan()` 先走 `_run_scan_once()`，再根据 `source_strategy_summary` 可能追加候选 URL 后重新执行一次扫描。这个设计让“单次扫描状态”和“策略性补扫状态”混在同一入口里。
- `_run_scan_once()` 内部既写入 facts，又写入 source records，还维护 diagnostics。`attach_run_diagnostics()` 之后 LLM fallback 仍可能补写事实，随后再刷新 diagnostics，说明事实状态和诊断状态存在顺序耦合。
- `_append_programme_catalog()`、`_extract_core_supplements()`、`_apply_llm_structured_fallback()` 等能力已经是相对独立的功能块，但仍挂在同一个超大 orchestration 文件内。

风险：

- 任何字段抽取、LLM fallback、diagnostics 或 source strategy 的改动都容易触碰主扫描循环，回归半径过大。
- 测试虽然覆盖了多条关键路径，但很多断言是在最终结果上观察副作用，缺少中间阶段的稳定契约。
- 后续如果继续加 `selection_tests_or_interviews`、`international_requirements` 等字段，主循环会继续横向膨胀。

修理策略：

1. 先冻结外部契约，不改变 `run_scan()`、CLI 参数、`run.config`、`result.json`、report markdown、CSV 输出的结构。
2. 在 pipeline 内引入小型内部上下文对象，例如：
   - `CapturedSourceContext`：保存 URL、response、content type、extracted text、source record id、classifier result。
   - `ExtractionAttempt`：保存字段名、候选值、claim path、source id、accept/reject reason。
   - `ScanDiagnosticsState`：聚合 coverage、missing reasons、source strategy、LLM fallback diagnostics。
3. 把主循环拆成只读输入、显式输出的 helper：
   - `materialize_source(...)`：负责 response 到 source record/text 的转换。
   - `classify_source(...)`：负责 deterministic classifier 与 optional LLM assist 诊断，但不直接写 facts。
   - `extract_from_source(...)`：负责按 category 分派 deterministic extractor，返回 attempts。
   - `apply_validated_attempts(...)`：统一做 evidence validation 与 facts 写入。
   - `run_structured_fallback(...)`：从 orchestration 文件迁到独立模块，只接收缺失字段、候选 source、provider config，只返回 validated attempts 和 diagnostics。
4. 主文件保留为 orchestration shell：discovery -> materialize -> classify -> extract -> validate/apply -> diagnostics -> optional fallback -> output。

执行步骤：

1. 补充保护性测试，先用现有 fixture 固定这些输出切片：
   - evidence path resolution。
   - `coverage` / `missing_reasons`。
   - `source_strategy_summary`。
   - LLM structured fallback 的 accepted/rejected candidate。
   - programme catalog CSV 与 source index 的存在性。
2. 第一步只提取 `CapturedSourceContext` 和 source materialization，要求 fixture 输出结构等价。
3. 第二步提取 category dispatcher，保持现有 HTML/JSON/PDF 抽取顺序不变。
4. 第三步提取 LLM structured fallback 到 `pipeline/structured_fallback.py`，保留 provider mock-first 测试方式。
5. 最后再整理 diagnostics state，避免在同一个函数里多次“先诊断、后补事实、再补诊断”的隐式顺序。

验收标准：

- `run_university_scan.py` 只保留流程编排，单个 helper 有明确输入输出，不再承担字段解析细节。
- 现有 CLI、Python API、输出 JSON/report/CSV 的契约不变。
- deterministic 测试全量通过，并至少覆盖一次 source strategy 补扫、一次 LLM candidate accepted、一次 LLM candidate rejected。
- `python3 -m compileall university_admissions_crawler tests` 通过。

明确不做：

- 不在这次债务修理中改默认 live crawl 行为。
- 不借重构机会扩大 LLM 写 facts 的权限。
- 不删除 compatibility alias 或旧 public API。

### 债务 2：抽取器与分类器仍偏启发式，真实站点泛化边界不清

证据：

- `classifier/page_classifier.py` 主要依赖关键词与低置信度规则判断页面类别。
- `admissions_context.py` 通过 context gate 决定文本是否足以支持字段抽取，这能减少误报，但也会产生漏报。
- `extractor/html_extractor.py` 仍以字段级正则和局部上下文为主，例如 deadline、English、programme、prerequisite、fee、contact、required documents。
- `extractor/programme_catalog.py` 已包含若干来源提示，例如 HKU/NUS/NTU/PolyU 相关页面结构和 faculty hint。这提升了样本效果，但也说明 programme catalog 泛化依赖启发式。
- `reports/render_report.py` 与 diagnostics 文案已经强调：missing reason 解释的是“当前捕获源码与当前抽取器未产出”，不是官网不存在该字段的证明。

风险：

- 对新学校、新栏目、新页面模板，系统可能出现“抓到了页面但分类不准”“分类准但 context gate 拦截”“context gate 通过但 parser 不识别”的链式漏抽。
- 当前 diagnostics 能提示缺字段，但还不能稳定指出应该修 discovery、classifier、context gate 还是 extractor。
- 若继续用零散正则追加字段，会让 false positive/false negative 的边界越来越难维护。

修理策略：

1. 建立字段能力矩阵，以 `pipeline/diagnostics.py` 的 `CORE_FIELDS` 为主线。每个字段必须明确：
   - 依赖哪些 discovery page category。
   - 经过哪些 context gate。
   - deterministic extractor 的入口。
   - 是否允许 structured LLM fallback。
   - 允许写入的 claim path。
   - 失败时对应的 `missing_reasons` 类型。
2. 把缺失原因拆成可行动分类：
   - `source_not_found`：没捕获到支持该字段的页面。
   - `blocked_or_challenge`：捕获到的是挑战页、封锁页或无可用正文。
   - `context_gate_failed`：页面存在，但上下文不足以支持事实。
   - `attempted_no_match`：上下文通过，deterministic extractor 未匹配。
   - `raw_needs_manual_review`：抽到了原文候选，但无法可靠结构化。
   - `portal_or_login_required`：字段很可能在登录/申请系统内，不能从公开页面确认。
3. 以 fixture 和 saved source 驱动改进，不把 live network 作为核心测试依赖：
   - 从现有 HKU/NTU/PolyU/NUS saved source 中抽取最小 HTML 片段。
   - 每个字段至少保留一个 positive fixture 和一个 false-positive rejection fixture。
   - 复杂字段保留 raw value，只有确定可解析时才输出 structured value。
4. programme catalog 拆分为“通用表格/列表解析”和“来源 hint”两层：
   - 通用层只处理 table/list/card 的结构。
   - hint 层只提供轻量字段名映射、faculty hint、噪声过滤。
   - 不允许在 pipeline 主循环里新增学校专用分支。
5. LLM fallback 继续作为最后一层补洞：
   - 只能基于已捕获 source text。
   - candidate 必须通过 `validate_llm_candidate_fact` 和 claim path 白名单。
   - 不能覆盖 deterministic extractor 已经写入且有证据的字段。

执行步骤：

1. 先在文档或测试 fixture 注释中补齐字段能力矩阵，确认每个 core field 的 owner。
2. 按字段逐步整理 extractor 测试，优先顺序：
   - `application_deadline` 和 `tuition_fee`，因为它们最容易出现格式和币种差异。
   - `english_language_requirements`，因为页面模板差异大且误报成本高。
   - `required_documents`、`prerequisites`、`contact`，因为通常依赖段落上下文。
3. 为 programme catalog 增加“generic parser 不依赖学校名”的 fixture，再把学校 hint 测试单独隔离。
4. 扩展 `missing_reasons` 输出，让报告能区分“页面没来”和“页面来了但 parser 没懂”。
5. 每完成一个字段，同步补充 saved-source regression，避免为了新样本破坏旧样本。

验收标准：

- 每个 core field 都能从 capability matrix 追溯到 discovery category、context gate、extractor、diagnostics reason。
- 新增字段或修改 parser 时，不需要改 `run_university_scan.py` 主循环。
- report 的缺失说明能指导下一步修复位置，而不是只给出 generic missing。
- deterministic extractor 和 LLM fallback 的职责边界在测试里有正反例。

明确不做：

- 不承诺任意官网字段 100% 覆盖。
- 不引入大型 NLP/浏览器依赖作为 core extractor 前置条件。
- 不把 LLM 输出作为无证据事实写入。

### 债务 3：输出契约、兼容层与文档状态存在漂移

证据：

- `extractor/schema.py` 的 `AdmissionsRecord` 包含 `international_requirements`、`standardized_tests`、`selection_tests_or_interviews` 等字段，但当前主要抽取路径并没有稳定写入这些字段。
- `tests/test_compatibility_boundaries.py` 冻结了若干 compatibility/private alias，说明外部或历史调用面已经存在，不能随意删除。
- `crawler/config.py` 里的 `CrawlConfig` / `smoke_config()` 更像兼容边界，而 CLI live/fixture 默认值主要来自 `cli.py` 和 `config_loader.py`。
- README、VERSION_NOTES、PROJECT_MAP、设计文档里曾多次记录测试数量和阶段状态，这类数字很容易随测试增删而不一致。
- diagnostics/report 文案已经在局部强调“不是 absence proof”，但 schema 字段、报告字段和文档路线图之间仍可能让读者误以为所有 schema 字段都已稳定抽取。

风险：

- 下游使用者无法区分“稳定事实字段”“实验字段”“仅 schema 预留字段”“diagnostic 字段”。
- 为了保持旧测试通过，内部 private alias 可能继续被当作事实公共 API 扩散。
- 文档中的测试数量、phase 状态、默认行为如果漂移，会削弱后续维护者对文档的信任。

修理策略：

1. 建立运行契约清单，把接口分成四类：
   - `primary`：CLI、`run_scan()`、`run_fixture_scan()`、`AdmissionsData`、`write_result_files()`、稳定输出字段。
   - `compatibility`：历史 alias、private alias、旧 config wrapper，短期保留但不鼓励新增调用。
   - `experimental`：schema 预留字段、LLM assist diagnostics、source planning diagnostics。
   - `generated-output`：reports、CSV、source index、coverage/missing reasons。
2. 给 schema 字段加状态说明：
   - 已稳定抽取：可以在报告中作为事实展示。
   - 条件抽取：只在 source text 足够且 extractor 支持时展示。
   - 预留/实验：可以出现在 schema，但不能让文档暗示已稳定覆盖。
3. 给 compatibility surface 制定退场策略：
   - 当前阶段不删除，先在文档中标明 owner 和用途。
   - 新代码不再引用 private alias。
   - 若未来要移除，必须先有一次显式迁移说明和测试调整。
4. 文档状态改成少写易漂移数字：
   - README 只描述能力面和推荐命令。
   - VERSION_NOTES 记录 release-level 验证快照。
   - PROJECT_MAP 描述模块边界。
   - 本设计文档记录方案、边界和设计决策，不反复维护“最新通过测试数量”。
5. 对输出字段建立事实/诊断分界：
   - facts 必须有 source/evidence claim path。
   - diagnostics 只能解释系统行为，不能当作招生事实。
   - experimental 字段默认需要 manual check 或明确 provenance。

执行步骤：

1. 用 `rg` 生成一次接口与字段盘点：
   - public imports / CLI flags。
   - schema 字段写入点。
   - compatibility alias 使用点。
   - docs 中的测试数量和 phase 状态。
2. 在文档中补一张契约表，先完成标注，不立刻改代码。
3. 对未稳定写入的 schema 字段，逐项选择：
   - 补 deterministic extractor。
   - 仅作为 manual/experimental 字段保留。
   - 计划未来破坏性迁移，但当前不删除。
4. 将测试只绑定到真正承诺的 contract，不要为内部 helper 自动形成长期兼容义务。
5. 每次 release 只在一个地方更新验证快照，其他文档引用该快照或避免写死数字。

验收标准：

- 文档能清楚区分事实字段、诊断字段、实验字段、兼容 API。
- 未稳定抽取的 schema 字段不会被描述成已完成能力。
- compatibility alias 有保留理由和未来处理方式。
- README/VERSION_NOTES/PROJECT_MAP/本设计文档之间不再出现互相矛盾的阶段状态或测试数量。

明确不做：

- 不在本 docs 更新中删除字段、alias 或旧配置入口。
- 不把测试数量作为长期架构质量指标。
- 不让 diagnostics 输出替代 evidence-backed facts。

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

## Programme Catalog 完整性修复方案

当前 `programme_catalog.csv` 只写出 `AdmissionsData.programme_catalog` 中已经接受的行；
CSV renderer 本身不负责发现或补全专业。因此“CSV 只能爬到一部分”的主因应在上游：
目录源是否抓到、抓到的页面文本是否保留了可解析结构、parser 是否能把表格/列表拆成
row-level candidate，以及 diagnostics 是否能识别“有目录信号但 accepted rows 很少”的
不完整状态。

当前样例证据：

- `outputs/ntu-openai-live/report.md` 显示 `candidate sources 14`、`crawled catalog
  sources 14`，但 `accepted rows 3`，同时 `probable incomplete False`、
  `next action none`。这说明 diagnostics 没有把“候选目录源很多但输出很少”识别为
  目录不完整。
- `outputs/ntu-openai-live/sources/456811f72e86eb31.txt` 只保存到 NTU programme
  filter shell 文案，例如 programme level / programme type，没有实际专业列表。说明
  JS/filter 型页面需要专门的动态内容或公开 API 发现策略。
- `outputs/ntu-live-browser/sources/ae25c9ba9b34de33.txt` 已包含完整
  `Programme | Degree Title` 表，例如 Accountancy、Computer Science、Medicine 等，
  但文本被压成一整行，当前 line-based parser 无法稳定拆成多条专业记录。
- `outputs/ntu-live-browser/report.md` 只有 3 条 candidate/accepted rows，且
  manual-review rows 也是 3；`outputs/nus-bulletin-programmes-browser/report.md`
  有 25 条 accepted rows，但 18 条 manual-review rows、39 个 row warnings。说明
  当前 parser 同时存在漏抽和误抽长段正文的问题。

目标：

- 把 programme catalog 从“少量样本可抽取”提升为“能解释目录覆盖率的通用管线”。
- 保持 evidence-first：只有 captured official source 中可定位的 row 才进入
  `programme_catalog` 和 CSV。
- 不扩大 legacy `programmes` 的语义；高基数专业目录继续只由 `programme_catalog`
  承载。
- 下一阶段把公开接口作为 programme catalog 的优先路径：当官网前端背后存在可访问的
  JSON/API catalog 时，优先从 API object 生成 row-level evidence；HTML/static parser
  作为兜底，browser/network capture 只在动态壳或低产出时启用。
- 先增强 diagnostics 和 fixture，再逐步扩大 source acquisition 与 parser 行为，避免
  用 live 输出作为不可复现测试基线。

### Step A：增强目录源发现与抓取状态

要新增或收敛一套 `programme_catalog` 专用 source-candidate 诊断，而不是只看最终
`accepted_row_count`：

- 统一记录 catalog source candidates：
  - 来源：homepage/frontier link、sitemap、common path probing、source planning、
    captured page 内部链接、公开 JSON/API 或 script hint。
  - 类型：static table/list、JS/filter shell、faculty/school catalogue、bulletin、
    programme detail、major/minor page、PDF、public API/JSON。
  - 证据：URL/title/text signals，例如 `degree-programmes`、`undergraduate-programmes`、
    `Programme | Degree Title`、`Bachelor`、`Major`、`Minor`、`Programme Type`、
    `School offering`。
- 对每个 candidate source 记录 crawl status：
  - `not_crawled_budget_skipped`
  - `crawled_html`
  - `crawled_pdf`
  - `blocked_or_challenge`
  - `dynamic_shell_no_rows`
  - `public_api_candidate`
  - `rejected_off_domain_or_low_value`
- 对 JS/filter shell 页面，若浏览器保存文本只有筛选器、没有 row-level programme 文本，
  不应当算作成功 source；应标记 `dynamic_shell_no_rows`，并尝试从 captured HTML /
  script / network metadata 中提取公开 API 或分页 URL，再经过 allowed-domain、
  HTTPS、low-value 过滤后进入 bounded crawl frontier。
- 不做的事：
  - 不绕过登录、验证码、portal 或权限限制。
  - 不把未抓取的 candidate URL 当作招生事实。
  - 不让 LLM 生成新 URL 后直接写事实；LLM 最多只能提供 bounded source planning hint，
    并继续受 deterministic validation 约束。

验收：

- fixture 能证明 `/education/degree-programmes`、`/admissions/undergraduate-programmes`、
  `/bulletin/.../programmes`、`/majors`、`/minors` 等入口会进入 catalog candidate
  diagnostics。
- JS shell fixture 在没有 rows 时输出 `dynamic_shell_no_rows`，而不是
  `probable_incomplete_catalog=False`。
- candidate URL 进入 crawl frontier 前必须经过 domain、scheme、low-value 和 budget
  validation；被跳过的 URL 要能在 diagnostics 中解释。

### Step B：新增表格/列表分段解析层

当前 `_candidate_lines()` 偏 line-based，适合已经保留换行的页面，不适合被清洗成单行的
官方表格。需要在 `extract_programme_catalog()` 前段新增通用 segmentation 层：

- HTML 保留结构时优先走结构化提取：
  - `<table>` / `<tr>` / `<td>` 转为 row cells。
  - `<li>`、card list、definition list 转为 candidate rows。
  - row-level link 如果存在，写入 future `programme_url` 或 diagnostics metadata。
- HTML 已被保存为扁平 text 时，增加 table-like text segmenter：
  - 识别 `Programme | Degree Title . Accountancy | Bachelor of Accountancy . ...`
    这类重复 `cell | cell .` 模式。
  - 识别 `Second Major | School offering | Offered to students ...`、
    `Minor Programme | School offering ...` 等三列表。
  - 根据最近的 section heading 继承 category context，例如 single degree、double major、
    double degree、integrated programme、minor、second major。
- 每条 candidate row 必须保留：
  - `raw_text`
  - `cells`
  - `source_url`
  - `source_title`
  - `section_heading`
  - `parse_status`
  - `evidence_snippet`
- 加强误抽防线：
  - 长段正文不能因为出现 `Bachelor` / `programme` 就被当作专业名。
  - 对 `name` 设定长度、标点密度、句子数量和 table-cell density gate。
  - overview/admissions/curriculum 长段可以进入 diagnostics 的 rejected/raw review，
    但不能静默进入 CSV。
- 泛化原则：
  - 通用 parser 不依赖学校名。
  - 学校 hint 只用于补 faculty/category 等上下文，不生成不存在的专业。
  - LLM programme hint 只能对 captured candidate row 做分类提示，不能凭空新增 row。

验收：

- NTU `Programme | Degree Title` 单行 saved-source fixture 应抽出多条 row，例如
  Accountancy、Aerospace Engineering、Computer Science、Medicine 等，而不是一条长文本。
- NUS bulletin / CHS 长篇 overview fixture 不应把整段 overview 当成专业名；必要时标
  `raw_needs_manual_review` 或 rejected diagnostic。
- `programme_catalog.csv` 字段顺序不变；新增 metadata 如果还没进入稳定 schema，
  先放 diagnostics，不破坏 CSV 消费方。
- 每条 accepted row 都必须有 row-level evidence path 和 snippet；没有 captured
  snippet 的候选只能留在 diagnostics。

### Step C：重做完整性诊断与下一步建议

`programme_catalog_summary` 不能只统计已经接受的 rows。它需要同时解释“抓到了哪些疑似
目录源、哪些源没有解析出 row、为什么当前 CSV 可能不完整”。

建议新增或补齐指标：

- source 级：
  - `candidate_source_count`
  - `crawled_catalog_source_count`
  - `eligible_catalog_source_count`
  - `dynamic_shell_source_count`
  - `table_like_source_count`
  - `parsed_zero_row_source_count`
  - `blocked_catalog_source_count`
- row 级：
  - `accepted_row_count`
  - `raw_needs_review_count`
  - `rejected_candidate_row_count`
  - `long_text_rejected_count`
  - `duplicate_count`
  - `row_warning_count`
- coverage signal：
  - `table_marker_count`
  - `degree_keyword_count`
  - `programme_link_count`
  - `estimated_row_signal_count`
  - `accepted_to_signal_ratio`

`probable_incomplete_catalog=True` 的触发条件应至少覆盖：

- `candidate_source_count` 很高但 `accepted_row_count` 很低，例如 NTU 样例中
  `14 -> 3`。
- 存在 `dynamic_shell_no_rows` source。
- source text 中有强 table marker，例如 `Programme | Degree Title` 或
  `Minor Programme | School offering`，但 parser 接受行数为 0 或很少。
- accepted rows 大量 `manual_review` / warnings，或 accepted row name 明显过长。
- crawl budget 跳过了高分 catalog candidates。

`recommended_next_action` 应从单个 `none` 扩成可执行分类：

- `improve_source_acquisition`
- `enable_browser_or_api_capture`
- `increase_catalog_crawl_budget`
- `improve_table_segmentation`
- `tighten_false_positive_filters`
- `manual_review_raw_rows`
- `none`

report 中要明确区分：

- `programme_catalog.csv` 当前有多少 accepted rows。
- 这些 rows 是否足以代表完整目录。
- 哪些 candidate sources 没有转成 rows。
- 下一步是抓取问题、动态页面问题、parser 问题，还是人工复核问题。

验收：

- 当样例呈现 `candidate sources 14`、`accepted rows 3` 时，不能再输出
  `probable incomplete False` 和 `next action none`。
- 当保存文本只有 filter shell 时，报告应指向 `enable_browser_or_api_capture` 或
  `improve_source_acquisition`。
- 当保存文本包含 `Programme | Degree Title` 但没有 rows 时，报告应指向
  `improve_table_segmentation`。
- 当 fixture 中预期 rows 被稳定抽出、warning 低且没有 skipped 高分 catalog source 时，
  才允许 `recommended_next_action=none`。

### 推荐执行顺序

1. 先做 diagnostics-only slice：新增 source/row completeness metrics 和 report 展示，
   不改变 accepted rows，先让“不完整”可见。
2. 再做 generic table segmenter：优先修 NTU `Programme | Degree Title` 单行表，
   用 saved-source fixture 固定行为。
3. 再处理 JS/filter shell：浏览器等待、公开 API/link hint 和 bounded crawl frontier
   作为独立 slice，避免和 parser 改动混在一起。
4. 最后收紧 false-positive 过滤：降低长篇 overview/申请说明被误写入 CSV 的概率。

验证命令：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_programme_catalog.py tests/test_pipeline.py tests/test_report_cli.py
python3 -m pytest -q
git diff --check
```

主要风险与控制：

- 过度抓取：catalog candidates 必须走 budget 和 allowed-domain validation，并记录被跳过
  的原因。
- 误抽正文：增加 row length、cell density、section context 和 long-text rejection，
  默认宁可 diagnostics/raw review，也不要把长段正文写进 CSV。
- 学校特例膨胀：先用 generic fixtures 证明表格/列表模式，再把 HKU/NUS/NTU/PolyU hint
  限制在上下文补充。
- 输出契约漂移：CSV 字段保持稳定；新增未稳定字段先进入 `run.config` diagnostics。
- LLM 幻觉：LLM 只做 classification/source-planning hint，所有写入仍必须通过 captured
  source snippet 和 claim path validation。

最近验证状态：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
# 153 passed

git diff --check
# passed
```

### 下一阶段：API Catalog 主路径升级计划

当前 `programme_catalog.csv` 仍无法稳定爬取完整专业目录，说明前一阶段的
diagnostics、table segmenter 和 false-positive 过滤只能缓解 HTML 文本路径的问题，不能
根治 JS/filter shell 和高基数目录的完整性问题。下一阶段应把专业目录管线升级为：

```text
API catalog path 优先
HTML/static parser 兜底
browser/network capture 只在动态壳或低产出时启用
diagnostics 判断是否完整
```

目标不是绕过权限或登录系统，而是在官网公开接口存在时，用接口更完整、清晰、可验证地
拉取专业目录。

#### 总体判断

如果学校官网前端背后有公开 JSON/API，并且接口返回完整 catalog、分页/筛选参数可枚举，
接口爬取通常比 HTML/browser 文本解析更稳定：

- JSON 字段天然结构化，能减少 table/card/list 文本清洗。
- 每个 JSON object 可作为 row-level evidence snippet。
- 分页接口常暴露 `total`、`count`、`pageInfo`、`hasNextPage`，更容易判断完整性。
- 可以枚举 `level=undergraduate`、`programmeType=degree`、`studyMode=full-time`、
  `faculty` / `school` 等筛选参数。
- 可以避开 HTML 表格压平、卡片布局变化、导航正文混入和长篇介绍文误抽。

限制也必须明确：

- 不能保证所有学校都有公开接口。
- 不绕过登录、验证码、WAF、签名、动态 token 或权限接口。
- 接口可能只返回当前筛选页，必须处理分页、筛选枚举和完整性校验。
- GraphQL、Algolia、Sitecore、Next.js data、ElasticSearch 等结构需要 adapter 或字段
  mapping，不能用一套固定 key 假设覆盖所有学校。

#### 当前实现状态

当前分支已经从“API 只进入 legacy `programmes`”前进到“公开 JSON/API 可直接贡献
`programme_catalog`”：

- 已新增 `extractor/programme_catalog_api.py`，能把 captured public JSON object 转成
  `ProgrammeCatalogRecord`，并把单条 JSON object 作为 row-level evidence。
- `run_university_scan.py` 的 `SourceType.JSON` 分支已经接入 API catalog extractor；
  高基数 catalog API 不再把每条专业同步膨胀到 legacy `programmes`。
- 已新增 API pagination proof，支持 `page/pageSize`、`offset/limit`、
  `cursor/hasNextPage/endCursor` 三类最小翻页，并把分页结果写入 diagnostics。
- 已新增 diagnostics-only API discovery，能从 captured HTML/script/link/browser URL 中记录
  API endpoint candidate、source page、reason、status、response content type / size 和
  rejection reason。
- 已新增 safe JSON response capture 首版：对 discovery 发现但未进入 frontier 的
  `not_fetched` / `captured_url_only` 候选，在同域/allowed-domain、公开 GET、无敏感
  query、小响应体预算内主动抓取；抓到的 JSON 复用 API extractor 与 pagination path，
  只有 row-level JSON evidence 通过校验后才写入 `programme_catalog`。
- 已新增 filter enumeration proof：只从 captured official JSON 里的 `filters` / `facets` /
  `filterOptions` metadata 读取低风险筛选值，生成 bounded GET JSON 请求，并复用 API
  extractor 与 pagination path；programme row 里的普通 `faculty` / `level` 字段不会被误当成
  filter options。
- `programme_catalog_summary` 与 Markdown report 已展示 API response/page/accepted/rejected/
  total/pagination/filter/html fallback 等核心指标。

仍未完成的能力：

- Browser network capture 仍主要保留 URL；尚未保存 HAR-like request params、response header
  或完整 network body metadata。
- 筛选枚举仍是保守首版：不 fuzz 未知参数，不自动推断没有官方 filter metadata 的参数，
  尚未做复杂多维组合覆盖率证明。
- `detail_url`、逐条 rejected API object reason、filter coverage proof、`api_adapter_used`
  仍未进入稳定 diagnostics。
- GraphQL、Algolia、Sitecore、Next.js data、ElasticSearch 等 adapter 尚未实现。

#### 目标架构

新增 programme catalog 专用 API path，保持现有 CSV 输出契约：

```text
catalog candidate discovery
  -> API/network candidate classification
  -> safe API capture
  -> pagination/filter expansion
  -> programme_catalog_api_extractor
  -> ProgrammeCatalogRecord + row-level JSON evidence
  -> completeness diagnostics
  -> programme_catalog.csv
```

输出原则：

- `programme_catalog.csv` 仍只渲染 `AdmissionsData.programme_catalog`。
- API row 必须来自 captured official JSON object，不能由模型或页面标题生成。
- `source_url` 可以是公开 API endpoint 或 programme detail URL；如果两者都存在，API
  endpoint 作为 evidence source，detail URL 先进入 diagnostics/future metadata，等 schema
  稳定后再进入正式字段。
- `evidence_snippet` 使用单条 JSON object 的压缩片段，而不是整份响应。
- 旧 `programmes` 字段继续保持低基数兼容语义，不承载完整目录。

#### 模型的角色边界

模型可以加速接口发现和字段 mapping，但不能直接写招生事实。

模型适合做：

- 从 HTML、JS、network log、HAR、JSON sample 中找接口候选。
- 判断哪个 response 像 programme catalog API。
- 推断分页模式，例如 `page/pageSize`、`offset/limit`、`skip/take`、
  `cursor/endCursor/hasNextPage`。
- 推断筛选参数，例如 `level=undergraduate`、`programmeType=degree`、
  `studyMode=full-time`、`faculty` / `school`。
- 生成字段映射建议，例如 `name`、`degree_or_award`、`faculty_or_school`、
  `category`、`detail_url`、`duration`、`mode`。

模型不能做：

- 编造接口 URL。
- 绕过登录、验证码、token、签名或权限限制。
- 在没有 captured official source 的情况下写入 `programme_catalog`。
- 根据页面标题或模型常识生成专业列表。
- 不做 `total` / `count` / `page` 校验就判断“已经完整”。
- 在运行时对每条 row 调模型生成事实。

正确边界是：

```text
模型提出候选接口和分页策略
代码按规则验证和抓取
只有真实抓到的 JSON object 才能写入 programme_catalog
```

#### Step D：API Discovery 与 Safe JSON Capture

先把“是否存在公开 catalog API”和“是否能抓到官方 JSON body”变成可见状态；safe capture
可以写入 facts，但前提是抓到公开 JSON response，且 row-level evidence 通过现有校验。

候选来源：

- captured HTML 里的 `.json`、`/api/`、`/_next/data/`、`graphql`、`search`、
  `programme`、`course`、`catalog` endpoint hint。
- `<script>` / embedded JSON / data attributes 中的 endpoint、build id、API base URL。
- browser network response 中的 JSON URL，尤其是由 programme list / filter 页面触发的
  GET JSON。
- sitemap、frontier links 和 source planning hints 中的 JSON/API URL。

记录 discovery/capture diagnostics；只有 safe capture 抓到的官方 JSON row 才能写 facts：

- `api_catalog_candidate_count`
- `api_candidate_urls`
- `api_candidate_source_page`
- `api_candidate_reason`
- `api_candidate_status`: `not_fetched`、`captured_url_only`、`captured_json`、
  `rejected_off_domain`、`rejected_non_get`、`rejected_auth_or_token`、
  `rejected_too_large`、`capture_failed`、`non_json_response`、`blocked_or_challenge`
- `api_response_content_type`
- `api_response_size_bytes`
- `programme_catalog_api_capture`: attempted/captured/rejected URL、accepted row count、
  budget hit、是否实际写入 facts。

安全边界：

- 只抓同域或 allowed-domain 内的 HTTPS/HTTP GET JSON。
- 不保存 cookie、Authorization、CSRF header、个人信息 header。
- 不 replay POST、GraphQL mutation、登录后接口或带明显签名/一次性 token 的请求。
- 候选 URL 和重定向后的 `final_url` 都必须留在 allowed-domain 内。
- 设置每站最大 API candidates、最大响应体、最大总请求数。

验收：

- JS/filter shell fixture 应能输出 `dynamic_shell_no_rows`，同时列出公开 API candidate。
- 没有公开 API 时，diagnostics 明确 `api_catalog_candidate_count=0`，不影响 HTML 兜底。
- 被拒绝的 API candidate 必须有 rejection reason。
- 嵌入 HTML/script 且不在 discovery frontier 内的安全 JSON candidate 可被 bounded capture
  抓取，并经 API extractor 写入 `programme_catalog`。
- 抓取失败、非 JSON response 或响应过大时，只更新 diagnostics，不写 facts。

#### Step E：Programme Catalog API Extractor

新增 `extractor/programme_catalog_api.py`，专门把公开 JSON object 转成
`ProgrammeCatalogRecord`，不再复用 legacy `extract_api_claims()` 的 `programmes` 写入路径。

通用对象识别：

- 支持 payload 包裹层：`items`、`results`、`data`、`records`、`nodes`、`edges[].node`、
  `programmes`、`courses`。
- 候选 object 必须同时满足：
  - 有 programme-like name key：`name`、`title`、`programmeName`、`programName`、
    `courseTitle`、`degreeTitle`。
  - 有 undergraduate/catalog signal：`undergraduate`、`bachelor`、`degree`、`major`、
    `minor`、`full-time`、`programme`、`course`，或来源 API 已被 catalog classifier
    标为高置信。
  - object 不是导航、筛选器、统计项或纯院系列表。

字段 mapping：

- `name`：来自稳定 title/name 字段，要求长度、标点密度和 HTML 噪声通过 gate。
- `degree_or_award`：`degree`、`award`、`qualification`、`degreeTitle`、`awardName`。
- `faculty_or_school`：`faculty`、`school`、`college`、`department`、`schoolName`。
- `category`：从 `type`、`programmeType`、`level`、`award`、`degree`、`major/minor`
  signal 映射为 `degree_programme`、`major`、`minor`、`dual_degree`、
  `special_programme` 或 `unknown`。
- `mode`：`mode`、`studyMode`、`attendance`、`fullTimePartTime`。
- `duration_or_units`：`duration`、`studyPeriod`、`units`、`credits`。
- `admissions_choice_name`：`choice`、`admissionChoice`、`jupasCode`、`applicationCode`。
- `detail_url`：先作为 diagnostics metadata；等 schema 稳定后再进入正式字段。

row-level evidence：

- 每条 accepted row 的 `evidence_snippet` 是对应 JSON object 的 compact JSON。
- `evidence_path` 仍使用 `/programme_catalog/{index}/name`。
- 如果 API object 没有 stable name 或无法和 official source 绑定，只进入 rejected
  diagnostics，不进入 CSV。

验收：

- fixture API 返回多条 undergraduate programmes 时，`data.programme_catalog` 和
  `programme_catalog.csv` 行数一致。
- 每条 API row 的 evidence snippet 能定位到原始 JSON object。
- legacy `programmes` 不因高基数 API catalog 膨胀。

#### Step F：分页与筛选枚举

接口完整性的关键不是抓到一个 API，而是确认抓完了所有页和必要筛选。

分页识别：

- page 模式：`page` + `pageSize` / `limit`。
- offset 模式：`offset` / `skip` + `limit` / `take`。
- cursor 模式：`cursor` / `after` + `endCursor` / `hasNextPage`。
- total 模式：`total`、`count`、`totalCount`、`recordsTotal`。

筛选枚举：

- 只枚举低风险、可解释、官方 JSON filter metadata 已暴露的维度：
  - `level=undergraduate`
  - `programmeType=degree`
  - `studyMode=full-time`
  - `faculty` / `school`
- 不暴力枚举未知参数，不 fuzz，不尝试绕过 token。
- 不把 programme row 里的普通字段当成 filter option；必须来自 `filters`、`facets`、
  `filterOptions`、`searchFilters` 等 filter metadata 容器。

预算：

- 每站最大 API endpoint 数。
- 每 endpoint 最大页数。
- 每 endpoint 最大 accepted row 数。
- 每 endpoint 最大空页 / 重复页次数。
- 每 endpoint 最大 filter URL 数；filter URL、重定向后的 final URL、响应类型和响应体大小
  都要继续通过安全校验。
- 所有扩展请求必须记录在 diagnostics。

完整性判定：

- 如果 API 暴露 `total=120`，accepted rows 只有 40，必须标记
  `api_pagination_incomplete=True`。
- 如果没有 total，但分页连续返回直到空页 / `hasNextPage=False`，可标记
  `api_pagination_complete=True`。
- 如果只抓了第一页且无法证明无下一页，不能输出 `recommended_next_action=none`。

验收：

- fixture 覆盖 page、offset、cursor 三种分页。
- API 返回 total 与 accepted row mismatch 时，report 标记 incomplete。
- fixture 覆盖官方 filter metadata -> bounded filter URL -> `programme_catalog` 写入。
- API 完整抓取后，report 显示 `api_pagination_complete=True`，且
  `recommended_next_action=none` 仅在 warnings/duplicates/HTML skipped signals 可接受时出现。

#### Step G：API 优先的 Source Strategy 与 Report

`programme_catalog_summary` 需要新增 API 维度，避免只从 HTML candidate 角度解释完整性：

- `api_catalog_candidate_count`
- `api_response_count`
- `api_accepted_row_count`
- `api_rejected_row_count`
- `api_total_count`
- `api_page_count`
- `api_pagination_complete`
- `api_pagination_incomplete`
- `api_filter_dimensions`
- `api_adapter_used`
- `html_fallback_used`
- `api_to_csv_ratio`

`recommended_next_action` 需要扩展：

- `discover_public_catalog_api`
- `capture_browser_network_api`
- `implement_api_field_mapping`
- `expand_api_pagination`
- `enumerate_api_filters`
- `fallback_html_parser`
- `manual_review_api_rows`
- `none`

触发规则：

- 有 JS/filter shell 且没有 API candidate：`capture_browser_network_api`。
- 有 API candidate 但未抓 body：`capture_browser_network_api` 或
  `discover_public_catalog_api`。
- 有 JSON body 但 row 为 0：`implement_api_field_mapping`。
- row 数少于 API total：`expand_api_pagination`。
- 只抓默认筛选页：`enumerate_api_filters`。
- API 不存在或受限，但 HTML table marker 强：`fallback_html_parser`。
- API row warnings 多：`manual_review_api_rows`。

#### 推荐执行顺序（API 升级）

1. **Diagnostics-only API discovery（已完成首版）**：记录 API candidates、rejection
   reasons、network URL；candidate discovery 本身不改变 CSV。
2. **Capture safe JSON responses（已完成首版）**：只保存公开 GET JSON body 和 response
   metadata，不 replay 需要权限的请求。
3. **API -> programme_catalog extractor（已完成首版）**：新增 catalog 专用 JSON extractor，
   先覆盖 fixture 和 saved API sample。
4. **Pagination proof（已完成首版）**：支持 page/offset/cursor 三类最小分页，并把 total
   mismatch 写入 diagnostics。
5. **Filter enumeration proof（已完成首版）**：只枚举 undergraduate/degree/full-time/faculty
   等低风险参数。
6. **HTML fallback integration（部分完成）**：API 成功时优先使用 API；API 不存在、不完整
   或受限时，继续使用 HTML/static parser，并在 report 中解释 fallback 原因。
7. **Adapter layer（未完成）**：仅当通用 mapping 不足且站点价值高时，增加 GraphQL/
   Algolia/Sitecore/Next.js/ElasticSearch adapter；adapter 只负责解析官方响应结构，不生成事实。

#### 测试计划

- `tests/test_api_catalog_discovery.py`
  - HTML script 中发现 API candidate。
  - 未进入 frontier 的安全 JSON candidate 会被 bounded capture 抓取并写入
    `programme_catalog`。
  - safe capture 抓取失败、非 JSON response 或过大 response 只更新 diagnostics。
  - browser network 中发现 JSON API URL。
  - off-domain、POST、auth/token-like candidate 被拒绝并记录原因。
- `tests/test_programme_catalog_api.py`
  - JSON list 写入 `programme_catalog` 和 CSV。
  - nested payload、edges/nodes、items/results/data 结构都能抽取。
  - 缺 name、疑似导航/筛选器、长文本 object 被 rejected。
- `tests/test_api_catalog_pagination.py`
  - page/pageSize、offset/limit、cursor/hasNextPage 三种分页。
  - `total` mismatch 标记 incomplete。
  - budget hit 时 report 指向 `expand_api_pagination` 或 `increase_catalog_crawl_budget`。
- `tests/test_api_catalog_filters.py`
  - 官方 JSON filter metadata 暴露 `level` / `programmeType` / `studyMode` 时，生成 bounded
    filter URL 并写入 `programme_catalog`。
  - report 展示 `api_filter_candidate_dimensions`、`api_filter_dimensions`、attempted/fetched/
    rejected URL 计数和 budget hit。
- `tests/test_pipeline.py`
  - API path 优先于 HTML fallback。
  - API 受限时 fallback 到 HTML parser。
  - legacy `programmes` 不承载高基数完整目录。
- `tests/test_report_cli.py`
  - report 展示 API candidate、pagination、accepted/rejected row、next action。

验证命令：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_api_catalog_discovery.py \
  tests/test_programme_catalog_api.py \
  tests/test_api_catalog_pagination.py \
  tests/test_programme_catalog.py \
  tests/test_pipeline.py \
  tests/test_report_cli.py

.venv314/bin/python -m pytest -q
git diff --check
```

#### 风险与控制

- **完整性误判**：没有 `total` / `hasNextPage` / 末页证据时，不允许标记 complete。
- **权限边界**：不 replay 登录态请求，不保存敏感 header，不尝试签名/token 绕过。
- **过度抓取**：所有 API expansion 必须有 endpoint/page/row/byte budget。
- **schema 漂移**：CSV 字段先不变；`detail_url`、API metadata 等先进入 diagnostics。
- **adapter 膨胀**：默认用通用 extractor；adapter 需要 fixture 和明确站点结构证据。
- **模型幻觉**：模型只产出候选和 mapping suggestion；写事实必须经过 captured JSON object
  与 claim path validation。

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
