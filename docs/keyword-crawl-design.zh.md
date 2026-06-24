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

**Phase 4: Fixture-Backed Field Repair Loop**

**阶段 4：基于 fixture 的真实字段修复闭环**

项目最终目标是自动化爬取任意大学官网招生信息的关键字段。NTU 对比说明，
当前系统已经能在字段层解释 extractor / context gate / manual check 问题；NUS
对比进一步暴露了 source acquisition 层问题：有些官网入口会返回 WAF/challenge
页面，导致 extractor 根本没有拿到可用招生文本。

阶段 3 的结论是：这批改动值得保留，但它不是一次字段覆盖率大幅提升，而是一次
诊断层和规划层能力提升。下一阶段不应继续扩 LLM 功能，也不应继续把诊断逻辑
硬塞进主流程；更稳的方向是选择一个真实字段缺口，基于 saved/current source 建立
fixture-backed extractor / context-gate 修复样板。

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

下一阶段不要继续扩大 LLM 功能。当前更小风险的目标是建立一个“真实字段修复闭环”：

- 先隔离确认某个缺字段确实有可用官方 source。
- 再用 fixture-backed failing test 固定该缺口。
- 只修改对应 extractor、context gate 或 source classification 的最小位置。
- 保持 evidence-first：没有 source/snippet/evidence path 的内容仍不能写 facts。
- 每次只修一个字段，不把 NUS/NTU/HKU/PolyU 多校问题混在一次改动里。

优先候选：

1. NUS `programmes`：当前 live smoke 中是 `attempted_no_match`，如果 captured source
   已包含官方 programme list，这是最适合做第一个 extractor 修复样板的高价值字段。
2. NTU `application_periods`：如果 saved/current source 中已有明确日期表，比
   `undergraduate_application_entry` 更适合先修。
3. NTU `fees`：只有在 source 明确包含 `S$` 金额或可解析表格内容时才继续结构化；
   否则保持 `raw_needs_manual_review`，不伪造 amount。

暂不优先：

- `required_documents`：很多内容在 application portal / checklist 内，需要先区分
  portal-only 信息和公开页面信息。
- `undergraduate_application_entry`：当前逻辑依赖 application period 设置入口，后续要
  单独设计 admissions/apply URL 候选识别，不应和字段 extractor 修复混在一起。
- hosted LLM source planning：当前 mock-only 诊断入口已经足够，下一步不扩大供应商。

## Phase 4 执行计划

### Step 1：文档状态对齐

修改文件：

- `docs/keyword-crawl-design.zh.md`
- `README.md`
- `VERSION_NOTES.zh.md`

目标：

- 把 Phase 3 标记为已完成并写入复盘结论。
- 明确 `accepted_candidate_urls` 只是 diagnostics 候选，不是当前 crawl frontier。
- 把下一阶段目标切换到 fixture-backed field repair loop。

验证方式：

```bash
git diff --check
```

风险控制：

- 只改描述型文档。
- 不改运行代码、测试 fixture 或 generated outputs。

### Step 2：隔离选择第一个字段修复目标

修改文件：

- 无。输出只写 `/tmp`，不提交 generated artifacts。

目标：

- 用现有 CLI 或已保存 output 对比 NUS / NTU 的 `coverage`、`missing_reasons`、
  `extraction_diagnostics_summary`、`source_strategy_summary`。
- 只选择一个满足以下条件的字段：
  - source 是官方 source。
  - source text 中确实有目标字段的可抽取证据。
  - 当前缺失原因不是纯 portal/manual-check。
  - 修复点能落在 extractor / context gate / classifier 的小范围代码里。

验证方式：

```bash
.venv314/bin/python -B -m university_admissions_crawler.cli <seed-url> \
  --enable-browser \
  --browser-wait-until domcontentloaded \
  --timeout-seconds 45 \
  --output-dir /tmp/uac-field-repair-check \
  --allowed-domain <official-domain> \
  --max-pages 30 \
  --max-depth 2
```

风险控制：

- 如果 source 中没有明确证据，停止并换目标，不写 extractor 猜测规则。
- 如果需要新增 fixture，先在下一步单独完成，不和生产代码混改。

### Step 3：为选中字段增加 fixture-backed failing test

修改文件：

- `tests/fixtures/saved_sources/<school>/...`，仅在需要固化官方 source 时新增。
- `tests/test_pipeline.py` 或现有更贴近的 focused test 文件。
- 如确实需要新建测试文件，应先说明理由，避免测试分散。

目标：

- 先写失败测试，证明当前缺口可复现。
- 测试同时断言 value 和 evidence claim path。
- 保留当前 `missing_reasons` 断言，避免修字段时破坏诊断。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py
git diff --check
```

风险控制：

- fixture 必须来自官方 source，不能用 LLM 生成事实内容。
- 不从 `outputs/` 直接读取测试数据；需要的 saved source 应复制到
  `tests/fixtures/saved_sources/`。

### Step 4：最小 extractor / gate 修复

修改文件：

- 优先 `university_admissions_crawler/extractor/structured.py`。
- 如果诊断证明是 gate 问题，才改
  `university_admissions_crawler/crawler/admissions_context.py`。
- 如果诊断证明是分类问题，才改
  `university_admissions_crawler/classifier/page_classifier.py`。
- 避免继续扩大 `university_admissions_crawler/pipeline/run_university_scan.py`。

目标：

- 让 Step 3 的失败测试通过。
- 只覆盖目标字段的已验证页面结构。
- 保留 raw fallback；无法稳定解析时使用 `raw_needs_manual_review` 或
  `needs_manual_check`，不生成假结构化值。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_classifier.py tests/test_classifier_ntu_regression.py
git diff --check
```

风险控制：

- 不重写已有 extractor。
- 不为了提高 coverage 降低 context gate。
- 不改变 LLM/source planning 行为。

### Step 5：报告和 diagnostics 回归检查

修改文件：

- 默认无。
- 只有当字段输出形态或 diagnostics 展示确实变化时，才改
  `university_admissions_crawler/reports/render_report.py` 和
  `tests/test_report_cli.py`。

目标：

- 确认修复后的字段显示在 facts 中。
- 确认 `missing_reasons` 不再把已找到字段列为 missing。
- 确认 diagnostics 仍位于 facts 前，source planning 仍不写 facts。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_report_cli.py tests/test_pipeline.py
git diff --check
```

风险控制：

- 不为了展示效果改变 schema。
- 不把候选 URL、classification assist 或 source plan 内容渲染成 admissions facts。

### Step 6：live smoke 与旧输出对比

修改文件：

- 无。输出只写 `/tmp`，不提交 generated artifacts。

目标：

- 对选中学校重新跑小范围 live/browser smoke。
- 对比修复前后的 `coverage`、`facts`、`missing_reasons`、
  `extraction_diagnostics_summary`。
- 只宣布经过 source/evidence 验证的提升，不把 live 网络偶然性当稳定能力。

验证方式：

```bash
.venv314/bin/python -B -m university_admissions_crawler.cli <seed-url> \
  --enable-browser \
  --browser-wait-until domcontentloaded \
  --timeout-seconds 45 \
  --output-dir /tmp/uac-field-repair-after \
  --allowed-domain <official-domain> \
  --max-pages 30 \
  --max-depth 2
```

风险控制：

- 如果 live source 结构变化导致结果不可比，以 fixture test 为准，并在复盘中说明。
- 不提交 `/tmp` 或 `outputs/` 中的大批生成结果。

### Step 7：阶段复盘、文档同步与提交

修改文件：

- `docs/keyword-crawl-design.zh.md`
- 必要时 `README.md`
- 必要时 `VERSION_NOTES.zh.md`

目标：

- 记录这次字段修复到底提升了什么。
- 明确它是否提升 coverage，还是只提升 raw/reference 可信度。
- 记录仍未解决的字段和下一步候选。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
python -m compileall -q university_admissions_crawler tests
git diff --check
```

风险控制：

- 不把单个学校的字段修复宣传成“任意大学已完成”。
- commit 前确认 `git status`，只提交本阶段相关文件。

## Phase 4 不做

- 不继续扩展 LLM provider 或 hosted LLM。
- 不自动 follow `accepted_candidate_urls`；如要把候选 URL 接入 crawl frontier，需要
  新阶段单独设计。
- 不用 LLM 生成 programme、fee、deadline、requirement 等招生 facts。
- 不绕过 WAF、人机验证、登录或申请系统。
- 不把旧 NUS programme collection 当作当前通用 pipeline 的能力证明。
- 不重写 `run_university_scan.py` 主循环。
- 不刷新或提交大批 `outputs/` 历史产物。
- 不做无关格式化、依赖升级或全仓重排。

## Phase 4 完成标准

本阶段可以认为完成，当且仅当：

- 选中一个真实字段缺口，并有 fixture-backed test 固定。
- 修复后该字段有 source、snippet 和 evidence claim path。
- 对应 `missing_reasons` 从 missing 中退出或原因更准确。
- source planning、classification assist、LLM keyword plan 仍保持 diagnostics-only。
- 完整 deterministic 测试通过。
- 文档明确说明这次提升对“任意大学官网自动化爬取”目标的实际帮助和边界。
