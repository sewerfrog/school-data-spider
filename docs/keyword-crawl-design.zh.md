# 关键词爬取与抽取修复设计说明

## 文档定位

本文档从当前分支开始记录下一阶段目标：字段级缺失原因闭环与抽取器修复样板。

上一阶段 `feature/model-assisted-keyword-crawl` 已合入 `main`，其目标是让关键词爬取、模型辅助分类和抽取诊断变得可见、可审计、可报告。当前新分支不再继续扩展上一阶段的历史日志，也不再把更多诊断逻辑堆进主流程；本阶段聚焦于回答一个更接近最终目标的问题：

当系统没有产出某个招生字段时，应该能说明失败发生在哪一步，并能用可复现 fixture 修复高确定性 extractor 问题。

项目最终目标是自动化爬取任意大学官网招生信息的关键字段。要达到这个目标，系统不能只输出 `missing`，还需要区分：

- 页面没有被抓到。
- 页面被抓到，但分类或上下文门控没有通过。
- extractor 被尝试，但没有匹配。
- 字段可能在申请门户或需要人工核验。
- 当前只找到了官网引用或表格入口，还没有结构化金额、日期或条件。

## 已完成基线

当前 `main` 已具备以下能力，本阶段应保留这些改动，不重写已经工作的模块：

- evidence-first 数据流：只把有来源证据的内容写入招生 facts。
- 默认 CLI 行为仍为规则路径；关键词计划、BM25-like relevance、mock LLM provider 都是显式 opt-in。
- `classification_assist_summary` 可以显示 classification assist 是否启用、是否触发、是否 0 触发。
- source filtering 已过滤静态资源和明显低价值 privacy / GDPR / cookie / terms 类 source，并保留招生 prospectus / tuition / requirements 类 PDF 反例保护。
- `extraction_diagnostics_summary` 可以汇总 extractor 的 `extracted`、`no_match`、`skipped` 及跳过原因。
- `missing_reasons` 已作为诊断层输出，不改变 `coverage`、facts 或 evidence。
- Markdown report 已在 facts 前展示 diagnostics 和 missing reasons。
- NTU undergraduate tuition fee saved source 已能产出官网 fee table/reference raw candidate，但还不是结构化金额解析。

这些能力提升的是排查能力，不等于字段覆盖率已经解决。coverage 仍取决于 source selection、context gate、extractor 和真实站点结构。

## 当前差距

### 1. 缺失原因仍不够稳定

`missing_reasons` 目前是第一版字段级诊断。它可以说明当前抓到的 source 中发生了什么，但在同一字段对应多个 source、多个 extractor attempt 时，reason 的优先级仍可能不够准确。

下一步要让字段级归因更接近真实瓶颈。建议优先级为：

1. `attempted_no_match`：已经抓到相关 source 且 extractor 被尝试，但没有抽出结果。
2. `context_gate_failed` / `undergraduate_context_gate_failed`：source 被抓到，但字段门控未通过。
3. `application_portal_unreachable`：候选入口指向申请门户或外部系统，当前流程不能进入。
4. `not_attempted`：当前抓取结果中没有足够 source 触发该字段 extractor。
5. `manual_check_required`：存在诊断信息，但无法归入更具体原因。

如果同一字段同时存在 `attempted_no_match` 和 `context_gate_failed`，应优先展示 `attempted_no_match`，因为它说明系统已经到达了 extractor 层，下一步更可能是修 extractor 或 fixture。

### 2. diagnostics 不能证明官网没有提供字段

当前 diagnostics 只能说明“本次抓到的 source 中，现有规则没有产出字段”。它不能证明官网从未公开该字段。

在后续文档和报告中，仍应避免写成“官网没有提供”。更准确的描述是：

- captured sources did not include a usable value；
- extractor attempted but no match；
- source failed context gate；
- application portal/manual check required。

只有未来建立字段级 absence evidence 后，才可以更强地表达“官网公开页面未发现”。

### 3. NTU fees 仍停留在 raw reference

NTU undergraduate tuition fee saved source 已经能通过 context gate，并生成官网 fee table/reference raw candidate。

但当前结果仍是：

- `parse_status = "raw_needs_manual_review"`
- `parsed = []`
- 没有结构化 `S$` / `SGD` 金额

这不是回归，而是一个明确的下一步样板：先基于 saved source 和最小 fixture 证明 extractor 能稳定识别官方 fee table，再决定是否扩展到金额表格解析。

## 下一阶段目标

本阶段目标命名为：

**Phase 2: Field-Level Missing Reason and Extractor Repair Loop**

中文描述：

**阶段 2：字段级缺失原因闭环与抽取器修复样板**

本阶段完成后，系统应具备以下能力：

- 对每个缺失字段给出更可信的字段级 reason。
- 当 source 已经被抓到但 extractor 失败时，能把问题定位到 extractor 层。
- 用 NTU fees 建立第一个真实站点的 fixture-backed 修复样板。
- 继续保持 diagnostics 与 facts 分离。
- 后续处理 HKU / PolyU / 其他大学字段缺失时，可以先看 missing reason 决定修 source selection、context gate、extractor，还是标记 portal/manual check。

## 执行计划

### Step 1：修正 missing reasons 的字段级归因优先级

修改文件：

- `university_admissions_crawler/pipeline/diagnostics.py`
- `tests/test_pipeline.py`

目标：

- 当同一字段存在多个 source-level attempt 时，优先展示最接近真实瓶颈的 reason。
- `attempted_no_match` 应优先于 context gate 类 skipped reason。
- 保持 `missing_reasons` 仍为诊断层，不改变 facts、evidence 或 `coverage` 字段结构。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m compileall -q university_admissions_crawler tests
git diff --check
```

### Step 2：用 NTU fees 建立 extractor 修复样板

修改文件：

- `university_admissions_crawler/extractor/html_extractor.py`
- `tests/test_pipeline.py`
- 必要时新增或调整 `tests/fixtures/saved_sources/ntu/` 下的最小 fixture，但不依赖 live network。

目标：

- 保留当前 NTU undergraduate fee table/reference fallback。
- 如果 saved source 或新增 fixture 中存在可解析金额，再做窄范围结构化解析。
- 如果当前 source 仍只有引用文本，则明确保持 `raw_needs_manual_review`，不要伪造金额。
- 继续保护负例：graduate / postgraduate / hall / PhD / current-students fee source 不应误抽为 undergraduate fees。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
git diff --check
```

### Step 3：小范围收敛 diagnostics 写入边界

修改文件：

- 优先不修改。
- 只有 Step 1 或 Step 2 发现必须整理时，才小范围触碰 `university_admissions_crawler/pipeline/run_university_scan.py`。

目标：

- 不重写 `run_scan()`。
- 不继续把大段诊断判断硬塞进主循环。
- 只在确实减少重复、保持行为不变时，抽出薄 helper。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_report_cli.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
git diff --check
```

### Step 4：同步项目入口文档

修改文件：

- `README.md`
- `VERSION_NOTES.zh.md`
- 必要时 `PROJECT_MAP.md`
- `docs/keyword-crawl-design.zh.md`

目标：

- 在代码行为稳定后，再同步项目入口文档。
- 不提前把计划写成已完成能力。
- 明确区分 raw reference、structured parsed value、manual check。

验证方式：

```bash
git diff --check -- README.md VERSION_NOTES.zh.md PROJECT_MAP.md docs/keyword-crawl-design.zh.md
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
```

### Step 5：收窄 portal/manual-check missing reason 边界

修改文件：

- `university_admissions_crawler/pipeline/diagnostics.py`
- `tests/test_pipeline.py`
- `docs/keyword-crawl-design.zh.md`

目标：

- 当字段没有 `no_match` 或 context gate 这类更具体失败，但本次 crawl 已发现 application portal / blocked challenge source 时，优先输出 `application_portal_unreachable`。
- 保持 `attempted_no_match` 和 context gate 仍高于 portal reason。
- 不把 portal reason 写成“官网没有提供字段”，只表示当前流程不能进入或不能使用该入口。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
git diff --check
```

## 当前执行结果

截至 2026-06-18，本阶段 Step 1 到 Step 5 已按最小风险路径执行：

- Step 1 已修正 `missing_reasons` 优先级：同一字段同时存在 extractor `no_match` 与 context gate skipped 时，优先输出 `attempted_no_match`。
- Step 2 已固定 NTU fees 边界：当前 saved source 只有官方 fee table/reference，继续保持 `raw_needs_manual_review`；新增 NTU-style amount-row fixture 证明 source 明确包含 `S$` 金额时可解析为结构化 `SGD` amount。
- Step 3 已隔离检查 `run_university_scan.py`，确认现有 `_ExtractionDiagnosticsRecorder` 已覆盖当前收敛需求，因此没有修改主流程。
- Step 4 已同步 `README.md`、`VERSION_NOTES.zh.md` 和 `PROJECT_MAP.md`，避免把 raw reference 写成结构化金额或 coverage 提升。
- Step 5 已收窄 portal/manual-check 边界：当没有更具体 extractor/context 失败且存在 application portal / challenge source 时，优先输出 `application_portal_unreachable`，避免落入泛化 `manual_check_required`。

当前完整验证结果：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
# 114 passed
```

## 本阶段不做

- 不继续扩展上一阶段的 Step 0 到 Step 6 过程日志。
- 不重新引入 ScrapeGraphAI / Crawl4AI 的长篇对比。
- 不全面重写 `run_university_scan.py`。
- 不直接补齐 HKU / PolyU 所有缺失字段。
- 不把 LLM 输出写入招生 facts。
- 不把 `missing_reasons` 描述成“官网没有提供”。
- 不依赖 live network 作为测试依据。
- 不刷新或提交大批 `outputs/` 历史产物。
- 不做无关格式化、无关依赖升级或全仓重排。

## 完成标准

本阶段可以认为完成，当且仅当：

- 字段级 `missing_reasons` 在混合失败场景下有稳定、测试覆盖的优先级。
- NTU fees 的当前能力边界被测试固定：能抽 raw reference 就明确标记 raw/manual-review，能解析金额才进入 structured parsed value。
- 所有新增行为都有 fixture-backed 测试。
- 完整测试通过。
- README / VERSION_NOTES / 设计文档与实际能力一致。

最终，本阶段的价值不是短期把 coverage 数字抬高，而是让任意大学官网的招生字段抽取进入可诊断、可复现、可逐字段修复的循环。
