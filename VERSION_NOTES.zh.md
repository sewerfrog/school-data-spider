# 版本说明：University Admissions Crawler MVP

快照日期：2026-07-21
项目目录：`/Users/sewerfrog/work/智能选校/school-data-spider`

本文是版本快照和变更说明。安装、运行和测试命令以 `README.md` 为准；项目结构、已知问题和清理计划以 `PROJECT_MAP.md` 为准。

## 1. 当前版本定位

本项目是一个 evidence-first 的大学本科招生信息抓取与抽取 MVP。它可以从本地 fixture 或大学官网主页 URL 出发，有限发现官方 source，从公开 HTML/JSON/API/PDF source 中提取可追溯信息，输出 legacy `result.json`、`report.md`、source 文件、evidence 记录和清洗友好的 `structured/` 输出。

核心边界没有变化：

- 不生成录取判断。
- 不绕过登录、验证码、WAF 或申请系统。
- 没有证据支撑的招生事实应保持 `unknown` 或进入 `needs_manual_check` warning。
- 浏览器、真实 PDF、LLM、crawl4ai、ScrapeGraphAI 等能力必须显式开启或仍处于 guarded/stub 状态；非 fixture 的普通 HTTP(S) URL 会默认走 live HTTP。

## 2. 本轮主要变化

- Browser PDF fallback：Playwright 遇到明显 PDF URL、PDF content type，或 `Download is starting` 导航时，会回退到 `LiveHTTPFetcher` 下载 PDF bytes，使 source 能记录为 `SourceType.PDF`。
- Cleaned candidate：`FieldValue` 增加 `raw_text`、`parsed`、`parse_status`，用于区分原始候选和轻量结构化结果。
- 轻量结构化解析：当前覆盖部分 English requirements、fee amounts 和 application dates；无法可靠解析时保留 raw candidate。
- 本科上下文过滤：对 postgraduate/graduate、hall/accommodation、search/current-students、privacy/contact form 等常见污染页面做更保守的核心字段 gate。
- 主内容和表格文本化：HTML 处理会优先取主内容区域，并将表格转成可抽取文本；这不是完整 DOM/table schema parser。
- 诊断输出：`run.config` 记录 coverage、source strategy 和 source strategy summary，报告中也会显示解析状态。
- Classification assist diagnostics：guarded classification assist 支持 deterministic `mock` 和真实 `openai` provider；只记录候选分类诊断，`classification_assist_summary` 会记录 entries、fallback、applied、disagreement 等计数，即使启用后 0 触发也保持可见。
- Source filtering 边界：抓取前过滤明显静态资源和 privacy/GDPR/cookie/terms 类低价值文档，同时通过 admissions prospectus、entry requirements、tuition fees、programme requirements PDF 反例保护招生材料。
- Extraction diagnostics：source-level 记录 extractor 的 `extracted`、`no_match`、`skipped` 等结果和 reason，汇总到 `extraction_diagnostics_summary`；报告在 facts 前展示。
- Missing reasons：对 `coverage.missing` 增加字段级 `missing_reasons`，用于说明当前 crawl/extractor 链路卡在 `source_not_crawled`、`not_attempted`、`attempted_no_match`、`context_gate_failed`、`application_portal_unreachable` 等位置。同一字段同时存在 extractor `no_match` 和 context gate skipped 时，当前优先展示 `attempted_no_match`；challenge source 导致 extractor 没拿到可用文本时优先展示 `source_not_crawled`；它仍不是官网缺失证明。
- Source acquisition diagnostics：新增明显 WAF/challenge/noindex/captcha/access denied 页面检测；相关 source 会保留供审计，但在 `source_strategy` 中标为 `blocked_or_challenge`，不会被当作普通招生 HTML 送入事实抽取。
- Homepage-first live 默认：非 fixture HTTP(S) 输入现在默认启用 live HTTP、推断 allowed official domain，并使用 live 默认 `max_pages=80`、`max_depth=4`、`timeout_seconds=60`。`--auto` 和 `--enable-live-network` 仍保留为兼容 flag，但普通单 URL scan 不再需要用户理解这些内部参数。
- 默认 LLM-assisted live crawler：非 fixture HTTP(S) 输入默认启用 LLM-assisted source planning、classification assist 和 structured extraction fallback。`--llm-provider auto` 会在存在 `OPENAI_API_KEY` 时解析为 OpenAI Responses API provider；没有可用 provider 时记录 `run.config.llm_runtime.provider = none` 并继续 deterministic crawl。`--no-llm` / `--deterministic-only` 可显式关闭。
- LLM source navigation：支持 `--llm-provider mock`、`--llm-provider openai` 和 `--llm-provider openai-chat`。`openai` 使用 `/v1/responses`；`openai-chat` 使用 OpenAI-compatible `/v1/chat/completions` 中转站，并通过 `OPENAI_BASE_URL`、`OPENAI_CHAT_COMPLETIONS_PATH`、`OPENAI_CHAT_RESPONSE_FORMAT`、可选 `OPENAI_REASONING_EFFORT` 和可选 `OPENAI_USER_AGENT` 配置。它们只生成候选官方 URL、query 和 category hint，写入 `run.config.llm_source_plan`；candidate URL 会经过 deterministic validation 并分成 accepted/rejected，accepted URL 可作为 bounded crawl frontier hint，但不会直接写入 admissions facts。
- Source planning report：Markdown report 在 facts 前展示 `Source Planning Diagnostics`，显示 enabled/triggered/applied、blocked source 数量、accepted/rejected/applied/budget-skipped candidate URLs 和 diagnostics-only note。
- NTU fees saved-source 回归：NTU undergraduate tuition fee 页面已通过 fee context gate；在当前 saved text 没有金额时，extractor 只输出官方 fee table/reference raw candidate，`parse_status` 为 `raw_needs_manual_review`，不伪造结构化金额。新增 NTU-style amount-row fixture 验证 source 明确包含 `S$` 金额时会解析为结构化 `SGD` amount。
- Saved-source 回归材料：测试依赖的 HKU/NTU/PolyU saved source 已复制到 `tests/fixtures/saved_sources/`，测试不应再读取 `outputs/`。
- `outputs/` 语义收敛：`outputs/` 保留为生成输出和历史参考样例目录，不作为当前 deterministic test fixture 来源。
- CLI / packaging 边界：`pyproject.toml` 提供 `university-admissions-crawler` console script；文档示例继续使用 `python -m university_admissions_crawler.cli`，避免依赖 PATH 状态。
- Guarded LLM 边界：LLM keyword-plan generation 已从主流程移除；`--keyword-query` 只保留为 deterministic debug input。OpenAI provider 已接入 source planning、classification assist、captured programme-catalog hint 和 structured extraction fallback。LLM 只生成 source/candidate 计划或候选事实；structured candidate 必须通过 captured-source、snippet、value、claim_path 和 context gate 的 deterministic validation 后才可写入 result。Anthropic/Gemini 仍被 CLI 拒绝。
- OpenAI 本地配置标准化：仓库提供 `.env.example` 模板，真实 `.env` 由本地开发者自行维护并被 `.gitignore` 忽略。代码仍通过 process environment 读取 `OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_BASE_URL`、`OPENAI_CHAT_COMPLETIONS_PATH`、`OPENAI_CHAT_RESPONSE_FORMAT`、`OPENAI_REASONING_EFFORT`、`OPENAI_USER_AGENT` 和 `UAC_LLM_PROVIDER`；CLI 不会自动加载 `.env`，运行前仍需 `set -a; source .env; set +a`。`.env` 不是 crawler 输入、不是 evidence source，不会写入 facts、fixtures 或 outputs。缺少 key 或 provider error 时 hosted provider fail closed 到 diagnostics，不应中断整次 run。
- Chat completions provider 边界：`openai-chat` 会把 guarded instructions 和 JSON user payload 转成 chat `messages`，默认请求 `response_format` JSON schema；如果中转站或 relay WAF 不支持 schema-constrained body，可把 `OPENAI_CHAT_RESPONSE_FORMAT` 设为 `json_object` 或 `none` 做兼容降级。返回内容必须是 `choices[0].message.content` 中的严格 JSON object，并继续走现有 payload validators 和 captured-source deterministic validation。
- 默认 relevance profile：`admissions_programme_profile` 已成为默认 discovery strategy，用内部 admissions/programme 信号优先本科招生、申请要求、日期、费用、英语/国际要求、材料、联系方式和专业目录 source；`rule-based` 和 `bm25-like` 仍保留为显式兼容/调试路径，不再是推荐主路径。
- 真实学校 fixture-backed 样板：NUS、HKU、NTU、PolyU 的最小官方 saved-source 样板现在覆盖 homepage/admissions -> programme catalog source 的 discovery、page category、programme catalog rows 和 evidence path。旧 NUS one-off CSV 仍只是参考，不代表当前 pipeline 已完整复现 NUS 全量专业体系。
- Programme catalog HTML hardening：parser 现在支持重排表头、partial header、已知 metadata 列、grouped rows 上下文继承和 HASS-like faculty/school section 继承；未知表格形态保持拒绝或 manual review，不回退成无边界名称推断。
- Programme field evidence：从 group/section context 继承的 `degree_or_award`、`faculty_or_school` 或 `category` 使用独立 claim path 和 evidence snippet；structured programme JSONL 追加可选 field evidence refs，CSV 字段保持不变。
- Programme candidate diagnostics：eligible HTML catalog source 的候选 accepted/rejected/context 决策、拒绝原因、候选形态、context 继承和 metadata header 统计进入 `programme_catalog_summary`、Markdown report 和 `structured/diagnostics.json`；这些内容是诊断，不是招生事实或目录完整性证明。对可见 typed blocks 为空的 HTML，现可有界使用官方 JSON-LD `Course` name/link 生成 card candidates，且 name 必须同时存在于可见归一化 source text；legacy 分支会拒绝被压平为“分类标签 + degree + 摘要”的无边界卡片文本。
- Programme completeness diagnostics：fail-closed evaluator 将未通过的 proof check 归类为 `discovery`、`segmentation`、`entity_gate` 或 `completeness_proof`；Markdown report 直接展示 status/basis/failure，`structured/diagnostics.json` 顶层追加精简 `programme_catalog_completeness` 对象。row-yield 同时保留 raw accepted count/ratio，并追加由 accepted ledger claim path、structural anchor 和 entity-quality signals 校验后的 adjusted count/ratio/exclusion reasons；没有 ledger 时显式回退 raw count。即使没有 candidate/source，discovery failure 仍会显示；legacy facts、CSV 字段和输出路径不变。
- Programme detail 定向第二轮：live CLI 默认在同一个 `max_pages` 内预留 4 页，先解析目录和未完整 row，再从首轮 pending/budget-skipped frontier 中选择唯一匹配且有 catalog-family 上下文的详情页；fixture 默认不启用，可用 `--programme-detail-reserve` 调整或设为 0。小预算下有效预留不超过 `max_pages` 的四分之一。外域 redirect、无唯一 row、无目录 family 上下文和已耗尽 family budget 的候选继续 fail closed；选择/拒绝诊断写入 legacy result、Markdown report 和 `structured/diagnostics.json`。
- 结构清理：单次扫描和 batch 扫描已共用 `pipeline/output_writer.py` 写出 `result.json` / `report.md`。
- Structured output records：`pipeline/output_writer.py` 保留 legacy `result.json`、`report.md` 和 root `programme_catalog.csv`，同时追加 `structured/` 清洗输出。`facts.jsonl` 和 `records/` 现覆盖 programme catalog、legacy programmes 以及全部 12 类 requirement collection；新增 `international_requirements.jsonl`、`standardized_tests.jsonl`、`selection_tests_or_interviews.jsonl`、`visa.jsonl` 和 `housing.jsonl`。这些文件提供可 join 的 `source_id`、`evidence_id` 和 `record_id`；source row 还提供 normalized host/path，programme row 提供 normalized programme name key。`run.config.diff` 存在时（包括 `baseline=none`），`structured/diagnostics.json` 的 `diagnostics.diff` 无损保留 v3 impact ledger；无 diff 的旧式对象不生成该可选键。
- Batch structured output：batch config 路径会在 batch 根 `structured/` 追加 manifest、旧有 `all_programme_catalog.jsonl`、`all_missing_fields.jsonl`、`all_sources.jsonl` 和全部 12 类 requirement `all_*.jsonl`。manifest 记录 `structured-output-v1`、输入学校目录数、各表行数、文件映射、`input_coverage`、`input_validation`、聚合校验摘要、`reference_index_coverage`、`evidence_validation` 和统一 `batch_validation`；validation 审计 row envelope、表级最小字段、同校 source/evidence 引用链、重复/歧义 source/evidence ID 和跨 programme/requirement 表 record ID 重复。`batch_validation` 以 `valid` / `incomplete` / `invalid` 三态、reason codes 和 metrics 聚合结构完整性，`invalid` 优先于 `incomplete`；它不代表抓取或招生数据完整，也不改变 CLI 退出码。这些文件只是合并每所学校已生成的 structured JSONL，不重新抓取、去重、推断、改写或丢弃异常行；旧目录和既有重复仍保留，但会显式进入 manifest 审计。
- Structured schema policy：当前 schema version 为 `structured-output-v1`。本阶段只做 additive 输出，保留 legacy 文件；下游应按 `schema_version` 分支读取，并优先消费 `structured/facts.jsonl` 或 record-specific JSONL，而不是把 `result.json` 当清洗 schema。
- crawler 边界拆分：`FetchResult` / `Fetcher` 已拆到 `crawler/types.py`，source/content-type 判断已拆到 `crawler/source_types.py`，JSON helper 已拆到 `crawler/json_content.py`，optional warning-only stubs 已拆到 `crawler/optional_stubs.py`。
- 兼容保护：旧的 `crawler.fetcher` 导入路径、JSON underscored helper、`pipeline.merge._merge_data` 等兼容入口仍保留，并由 `tests/test_compatibility_boundaries.py` 覆盖。
- Batch 边界收敛：`pipeline/batch.py` 已抽出 `_scan_limits_for_config()`，但仍保留 `argparse.Namespace`、`parser.error()` 和 `print()` 行为。

## 3. 已知仍有限制

- 真实官网抽取仍不是生产级；programme catalog 已覆盖若干 table/section 形态，但复杂跨区块专业体系、复杂费用表、多轮申请日期和 PDF 表格仍需要更强解析。
- Structured output 的 `institution` scalar facts 还没有进入统一 fact envelope；如后续加入，应作为 additive schema slice 并补 focused tests。
- NTU fees 当前 saved source 只是找到官方 fee table/reference，不是完成真实金额结构化解析；后续需要抓到或解析实际 table 内容。
- `missing_reasons` 描述的是当前抓取和 extractor 尝试结果，不能证明官网没有提供该字段；portal/manual-check/absence evidence 仍需要后续单独设计。
- `llm_source_plan.accepted_candidate_urls` 是已验证的 source navigation 候选；它们可以进入 bounded crawl frontier，但仍可能因 page budget 被跳过。它们不是招生事实，只有实际抓到的官方 source 和 deterministic evidence 才能支撑 result。
- LLM keyword optimization 已移除；下一阶段的自动化应来自 homepage-first source discovery、默认 relevance profile 和 source navigation，而不是用户输入 keyword query。
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
.venv314/bin/python -m pytest -q
.venv314/bin/python -m compileall university_admissions_crawler tests
```

结果：最近完整 pytest 为 `390 passed`；compileall 已重跑通过。

与本轮 structured output records 相关的目标测试组：

```bash
.venv314/bin/python -m pytest -q tests/test_structured_output.py tests/test_programme_catalog_output.py tests/test_report_cli.py
```

结果：最近 structured-output 目标组为 `53 passed`。

完整验证命令和环境说明请看 `README.md`。

## 5. 下一版本方向

- 在现有表头映射、group/section context 和候选拒绝 ledger 上继续扩展未覆盖的跨区块 DOM/table 形态，避免重新引入宽松 fallback。
- 继续评估 structured output 是否需要把 `institution` scalar facts 纳入统一 fact envelope；如做，保持 additive schema 变更并补迁移说明。
- 增强专业抽取器，区分 degree programme、major、minor、second major、special programme。
- 增强日期、费用和奖学金抽取，支持多申请人群、多轮次、多 cohort 和资助类型。
- 继续完善 `missing_reasons` 的 portal/manual-check/absence-evidence 边界；当前已优先处理 `attempted_no_match` 与 context gate 的混合场景。
- 下一阶段优先建立 fixture-backed field repair loop：先选一个真实缺字段，确认官方 source 中有明确证据，再增加失败测试，最后做最小 extractor/context-gate 修复。
- 第一批候选优先级：NUS `programmes`、NTU `application_periods`、NTU `fees` 的真实表格内容解析。`required_documents` 和 `undergraduate_application_entry` 暂不优先，因为它们更可能涉及 portal/checklist 或 application-entry 识别逻辑。
- LLM 已进入默认 live assisted 阶段：OpenAI provider 可用于 source planning、classification assist、captured programme-catalog hint 和 structured extraction fallback，但仍不能直接写 admissions facts；candidate 必须通过 captured-source deterministic validation 才能进入 result。
- 继续处理 NTU fees 的真实表格内容解析；当前应把 saved-source 行为视为 raw reference fallback，把 NTU-style amount-row fixture 视为解析能力边界测试。
- 增强 PDF 表格解析；是否引入 `pdfplumber` 或同类依赖需要单独评估。
- 将有价值的真实学校样例迁移到更明确的 `docs/examples/` 或记录保留清单，避免继续混用 `outputs/`。
- 继续小步拆分 `crawler/fetcher.py` 剩余的 PDF fallback 或时间 helper，避免同时移动 fixture/live/browser fetcher 类。
- 继续收敛 `pipeline/batch.py` 的 CLI 依赖和 `pipeline/category_extraction.py` 的路由/诊断职责；`run_university_scan.py` 已回到编排层，任何删除兼容入口前仍需用 `rg` 确认调用风险并单独提交。

## 6. 文档分工

- `README.md`：项目简介、安装、运行、测试和使用注意事项。
- `PROJECT_MAP.md`：当前模块地图、已知问题、清理方向和维护计划。
- `VERSION_NOTES.zh.md`：当前版本快照和变更说明，不再承担完整运行教程或项目地图职责。
