# 版本说明：University Admissions Crawler MVP

快照日期：2026-06-24
项目目录：`/Users/sewerfrog/work/智能选校/school-data-spider`

本文是版本快照和变更说明。安装、运行和测试命令以 `README.md` 为准；项目结构、已知问题和清理计划以 `PROJECT_MAP.md` 为准。

## 1. 当前版本定位

本项目是一个 evidence-first 的大学本科招生信息抓取与抽取 MVP。它从本地 fixture、显式开启的 live URL、公开 JSON/API 或 PDF source 中提取可追溯信息，输出 `result.json`、`report.md`、source 文件和 evidence 记录。

核心边界没有变化：

- 不生成录取判断。
- 不绕过登录、验证码、WAF 或申请系统。
- 没有证据支撑的招生事实应保持 `unknown` 或进入 `needs_manual_check` warning。
- 浏览器、真实 PDF、LLM、crawl4ai、ScrapeGraphAI 等能力必须显式开启或仍处于 guarded/stub 状态。

## 2. 本轮主要变化

- Browser PDF fallback：Playwright 遇到明显 PDF URL、PDF content type，或 `Download is starting` 导航时，会回退到 `LiveHTTPFetcher` 下载 PDF bytes，使 source 能记录为 `SourceType.PDF`。
- Cleaned candidate：`FieldValue` 增加 `raw_text`、`parsed`、`parse_status`，用于区分原始候选和轻量结构化结果。
- 轻量结构化解析：当前覆盖部分 English requirements、fee amounts 和 application dates；无法可靠解析时保留 raw candidate。
- 本科上下文过滤：对 postgraduate/graduate、hall/accommodation、search/current-students、privacy/contact form 等常见污染页面做更保守的核心字段 gate。
- 主内容和表格文本化：HTML 处理会优先取主内容区域，并将表格转成可抽取文本；这不是完整 DOM/table schema parser。
- 诊断输出：`run.config` 记录 coverage、source strategy 和 source strategy summary，报告中也会显示解析状态。
- Classification assist diagnostics：guarded mock classification assist 只记录候选分类诊断；`classification_assist_summary` 会记录 entries、fallback、applied、disagreement 等计数，即使启用后 0 触发也保持可见。
- Source filtering 边界：抓取前过滤明显静态资源和 privacy/GDPR/cookie/terms 类低价值文档，同时通过 admissions prospectus、entry requirements、tuition fees、programme requirements PDF 反例保护招生材料。
- Extraction diagnostics：source-level 记录 extractor 的 `extracted`、`no_match`、`skipped` 等结果和 reason，汇总到 `extraction_diagnostics_summary`；报告在 facts 前展示。
- Missing reasons：对 `coverage.missing` 增加字段级 `missing_reasons`，用于说明当前 crawl/extractor 链路卡在 `source_not_crawled`、`not_attempted`、`attempted_no_match`、`context_gate_failed`、`application_portal_unreachable` 等位置。同一字段同时存在 extractor `no_match` 和 context gate skipped 时，当前优先展示 `attempted_no_match`；challenge source 导致 extractor 没拿到可用文本时优先展示 `source_not_crawled`；它仍不是官网缺失证明。
- Source acquisition diagnostics：新增明显 WAF/challenge/noindex/captcha/access denied 页面检测；相关 source 会保留供审计，但在 `source_strategy` 中标为 `blocked_or_challenge`，不会被当作普通招生 HTML 送入事实抽取。
- LLM source planning diagnostics：新增 `--enable-source-planning` guarded mock 入口，必须配合 `--enable-llm --llm-provider mock`。它只生成候选官方 URL、query 和 category hint，写入 `run.config.llm_source_plan`；candidate URL 会经过 deterministic validation 并分成 accepted/rejected，但不会被自动 crawl，也不会写入 admissions facts。
- Source planning report：Markdown report 在 facts 前展示 `Source Planning Diagnostics`，显示 enabled/triggered/applied、blocked source 数量、accepted/rejected candidate URLs 和 diagnostics-only note。
- NTU fees saved-source 回归：NTU undergraduate tuition fee 页面已通过 fee context gate；在当前 saved text 没有金额时，extractor 只输出官方 fee table/reference raw candidate，`parse_status` 为 `raw_needs_manual_review`，不伪造结构化金额。新增 NTU-style amount-row fixture 验证 source 明确包含 `S$` 金额时会解析为结构化 `SGD` amount。
- Saved-source 回归材料：测试依赖的 HKU/NTU/PolyU saved source 已复制到 `tests/fixtures/saved_sources/`，测试不应再读取 `outputs/`。
- `outputs/` 语义收敛：`outputs/` 保留为生成输出和历史参考样例目录，不作为当前 deterministic test fixture 来源。
- CLI / packaging 边界：`pyproject.toml` 提供 `university-admissions-crawler` console script；文档示例继续使用 `python -m university_admissions_crawler.cli`，避免依赖 PATH 状态。
- Guarded LLM 边界：`--enable-llm --llm-provider mock` 现在有两条 mock-only 诊断用途：带 `--keyword-query` 时生成 keyword plan；带 `--enable-classification-assist` 时记录低置信度分类辅助诊断。真实 hosted providers 仍被 CLI 拒绝。
- 结构清理：单次扫描和 batch 扫描已共用 `pipeline/output_writer.py` 写出 `result.json` / `report.md`。
- crawler 边界拆分：`FetchResult` / `Fetcher` 已拆到 `crawler/types.py`，source/content-type 判断已拆到 `crawler/source_types.py`，JSON helper 已拆到 `crawler/json_content.py`，optional warning-only stubs 已拆到 `crawler/optional_stubs.py`。
- 兼容保护：旧的 `crawler.fetcher` 导入路径、JSON underscored helper、`pipeline.merge._merge_data` 等兼容入口仍保留，并由 `tests/test_compatibility_boundaries.py` 覆盖。
- Batch 边界收敛：`pipeline/batch.py` 已抽出 `_scan_limits_for_config()`，但仍保留 `argparse.Namespace`、`parser.error()` 和 `print()` 行为。

## 3. 已知仍有限制

- 真实官网抽取仍不是生产级；复杂专业体系、复杂费用表、多轮申请日期和 PDF 表格需要更强的 section/table 级解析。
- NTU fees 当前 saved source 只是找到官方 fee table/reference，不是完成真实金额结构化解析；后续需要抓到或解析实际 table 内容。
- `missing_reasons` 描述的是当前抓取和 extractor 尝试结果，不能证明官网没有提供该字段；portal/manual-check/absence evidence 仍需要后续单独设计。
- `llm_source_plan.accepted_candidate_urls` 是已验证的诊断候选，不是当前实现中的自动 crawl frontier；要让 crawler follow 这些 URL，需要单独设计新阶段。
- NUS browser smoke 在可用浏览器环境下能抓到一批官方 HTML source 时，source planning 不会触发；当时 coverage 为 `2/9`，说明剩余问题主要是 extractor、context gate 和 source prioritization，而不是继续扩 LLM。
- source filtering 有明确降噪收益，但低价值文档关键词仍可能误伤极少数招生材料，因此 admissions PDF 反例测试需要继续保留。
- `outputs/nus-live-programmes/` 是旧的一次性 NUS 产物，不能代表当前通用 pipeline 已能稳定复现完整 NUS 专业体系。
- 旧的 HKU/NTU/PolyU/NUS `outputs/` 结果不会因代码修复自动更新；`outputs/hku-live-step6*` 和 `outputs/ntu-current-diagnostics/` 这类当前分支诊断输出也只是 generated artifacts。要看到新行为需要重新跑对应学校 crawl。
- Browser 抓取依赖本地 Playwright 和 Chromium；缺失时应返回 `optional_dependency_missing` warning。
- WAF、portal、challenge 页面和连接关闭仍可能导致抓取失败或抓到无效内容。
- `overall confidence` 不是覆盖率指标；字段是否完整应同时查看 coverage 和 warnings。
- 通用 pipeline 当前只输出英文 `report.md`；中文报告尚未通用化。
- 当前没有 scheduler、来源失效监控或业务级定时 diff。

## 4. 本轮验证参考

当前完整验证已通过：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
.venv314/bin/python -m compileall -q university_admissions_crawler tests
```

结果：pytest 为 `126 passed`；compileall 通过。

与本轮 diagnostics/source-filtering/source-planning/report 相关的目标测试组：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
```

结果：`71 passed`。

完整验证命令和环境说明请看 `README.md`。

## 5. 下一版本方向

- 增强 DOM / section / table 级解析，减少长页面和复杂 CMS 的文本污染。
- 增强专业抽取器，区分 degree programme、major、minor、second major、special programme。
- 增强日期、费用和奖学金抽取，支持多申请人群、多轮次、多 cohort 和资助类型。
- 继续完善 `missing_reasons` 的 portal/manual-check/absence-evidence 边界；当前已优先处理 `attempted_no_match` 与 context gate 的混合场景。
- 下一阶段优先建立 fixture-backed field repair loop：先选一个真实缺字段，确认官方 source 中有明确证据，再增加失败测试，最后做最小 extractor/context-gate 修复。
- 第一批候选优先级：NUS `programmes`、NTU `application_periods`、NTU `fees` 的真实表格内容解析。`required_documents` 和 `undergraduate_application_entry` 暂不优先，因为它们更可能涉及 portal/checklist 或 application-entry 识别逻辑。
- 暂不继续扩展 LLM 功能；当前 mock source planning 已足够用于诊断，下一阶段应回到 source/evidence-backed extractor 修复。
- 继续处理 NTU fees 的真实表格内容解析；当前应把 saved-source 行为视为 raw reference fallback，把 NTU-style amount-row fixture 视为解析能力边界测试。
- 增强 PDF 表格解析；是否引入 `pdfplumber` 或同类依赖需要单独评估。
- 将有价值的真实学校样例迁移到更明确的 `docs/examples/` 或记录保留清单，避免继续混用 `outputs/`。
- 继续小步拆分 `crawler/fetcher.py` 剩余的 PDF fallback 或时间 helper，避免同时移动 fixture/live/browser fetcher 类。
- 继续收敛 `pipeline/batch.py` 和 `pipeline/run_university_scan.py` 的过重职责；任何删除兼容入口前先用 `rg` 确认调用风险并单独提交。

## 6. 文档分工

- `README.md`：项目简介、安装、运行、测试和使用注意事项。
- `PROJECT_MAP.md`：当前模块地图、已知问题、清理方向和维护计划。
- `VERSION_NOTES.zh.md`：当前版本快照和变更说明，不再承担完整运行教程或项目地图职责。
