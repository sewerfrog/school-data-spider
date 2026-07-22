# Project Map

## 1. 这个项目是做什么的

本项目是一个 Python 3.11+ 的大学本科招生信息抓取与抽取 MVP。它从本地 fixture 或大学官网主页 URL 出发，有限发现招生相关页面，抽取能被 source/evidence 支持的结构化字段，并生成 legacy `result.json`、`report.md`、source 文件和清洗友好的 `structured/` 输出。

当前设计重点是 evidence-first：没有证据的招生事实应保持 `unknown` 或进入 `needs_manual_check` warning。项目不做录取判断、不做推荐、不做无边界爬取，也不绕过登录、验证码、WAF 或申请系统。

## 2. 当前已经能工作的功能

- Fixture 端到端扫描：`--fixture` 可跑 `tests/fixtures/mini_university_site/`。
- Live HTTP 扫描：非 fixture HTTP(S) URL 默认启用，`--auto` / `--enable-live-network` 仅作为兼容 flag 保留。
- Homepage-first 默认参数：live URL 默认 `max_pages=80`、`max_depth=4`、`timeout_seconds=60`，并从输入 URL 推断 allowed official domain。
- 可选 Playwright browser fallback：`--enable-browser`，HTTP-first，仅在需要渲染的 homepage/high-value 页面上 fallback；依赖未安装时返回 warning。
- 可选 PDF 文本解析：`--enable-pdf` 使用 `pypdf`，失败时返回 warning；未启用时 live PDF 只记录 warning，不再按 fixture PDF 文本解析。
- 批量配置扫描：`--config` 读取 JSON 配置并按大学 ID 输出子目录。
- bounded discovery：通过 `max_pages`、`max_depth` 控制范围。
- 两阶段 programme detail discovery：live 默认在同一 `max_pages` 总预算内预留 4 页；首轮解析目录，第二轮只补抓能唯一对应缺学院 row 且有 catalog-family 上下文的详情页。fixture 默认关闭，可用 `--programme-detail-reserve` 调整。
- URL/domain policy：支持 allowed host/domain、官方子域、URL 规范化和简单链接打分。
- 页面分类：规则分类招生、要求、截止日期、资格、专业、费用、奖学金、签证、住宿、联系信息和 irrelevant。
- 规则抽取：从 HTML/text 中抽取申请日期、英语要求、资格、专业、先修、费用、奖学金、签证、住宿、联系方式和材料。
- JSON/API 抽取：从公开 JSON 中保守抽取 programme、deadline、tuition fee、required documents。
- Programme catalog HTML fallback：支持重排表头、已知 metadata 列、grouped rows 上下文继承和
  HASS-like faculty/school section 继承；NUS/NTU 专用 name/faculty aliases 由 official registrable
  domain profile 隔离，继承字段使用独立 evidence，并保持 manual-review warning。
- 证据与校验：记录 source、snippet、claim path、hash、warnings，并校验 non-unknown claim 是否有 evidence。
- 报告输出：生成 Markdown evidence report。
- Structured output records：`structured/` 生成 `manifest.json`、`institution.json`、`facts.jsonl`、`sources.jsonl`、`evidence.jsonl`、`missing_fields.jsonl`、`warnings.jsonl`、`diagnostics.json`，以及 `records/programme_catalog.jsonl`、清洗版 `records/programme_catalog.csv`、全部 12 类 requirement collection JSONL 和 `records/programmes_legacy.jsonl`；`diagnostics.diff` 在 `run.config.diff` 存在时（包括 `baseline=none`）无损保留该 payload。batch config 路径在根 `structured/manifest.json` 中记录学校目录数、文件、行数、每表 input coverage、row validation、source/evidence reference-index coverage、evidence-source validation 和统一 `batch_validation` verdict，并生成旧有 programme catalog/missing/source 三表及全部 12 类 requirement 聚合 JSONL。
- 增量 diff：传入 previous result 时记录 source hash 和字段变化。
- source filtering：抓取前过滤明显静态资源和 privacy/GDPR/cookie/terms 类低价值文档，并用 admissions prospectus、entry requirements、tuition fees、programme requirements PDF 反例保护误删边界。
- diagnostics：`classification_assist_summary`、`extraction_diagnostics_summary`、`missing_reasons`、`template_completeness`、programme candidate ledger 和 field-evidence mapping 已写入 `run.config`，报告会在 facts 前展示聚合诊断；这些内容不改变事实字段。字段级缺失原因和抽取器修复细节见 `docs/keyword-crawl-design.zh.md`。
- programme catalog merge：HTML/API 候选共用 institution/category/name/award 身份规则和
  source-role 优先级；canonical row 优先，faculty/detail 只补充缺失字段并保留独立 evidence。
  Step 6 的 completeness evaluator 也已按 canonical/candidate/section/API proof fail closed；Markdown
  report 和 `structured/diagnostics.json` compact contract 会直接解释 status、basis、failure reason 和
  discovery/segmentation/entity-gate/completeness-proof failure stage。row-yield 会同时保留 raw accepted
  count/ratio，并基于 accepted ledger claim path、structural anchor 和 entity-quality signals 输出 adjusted
  count/ratio/exclusion reasons；这些诊断不改写 programme facts。
- saved-source 回归：HKU/NTU/PolyU 相关回归 fixture 已迁到 `tests/fixtures/saved_sources/`；NUS/HKU/NTU/PolyU 已有 homepage/admissions -> programme catalog source 的 fixture-backed pipeline 样板。NTU fee 当前能力边界见 `docs/keyword-crawl-design.zh.md`。
- 测试：`.venv314` 环境下最近完整 pytest 结果为 `390 passed`；README 所列
  structured-output 目标组为 `53 passed`，`compileall` 和 `git diff --check` 通过。

## 3. 未完成或实验性功能

- LLM：`--enable-llm --llm-provider mock` 当前支持 deterministic mock；`openai` 支持 Responses API，`openai-chat` 支持 OpenAI-compatible `/v1/chat/completions` 中转站，并可用 `OPENAI_USER_AGENT` 兼容拒绝 Python 默认 `urllib` client signature 的 relay WAF、用 `OPENAI_CHAT_RESPONSE_FORMAT=json_object|none` 兼容拒绝大 schema `response_format` body 的 relay。Hosted provider 缺 key、网络失败或返回不合规时仍 fail closed 到 diagnostics。LLM keyword-plan generation 已移除，LLM candidate facts 仍只能走 evidence-gated 校验 helper，不是 pipeline 默认事实来源。
- ScrapeGraphAI：CLI 有 `--enable-scrapegraph`，但当前直接报错；`ScrapeGraphFetcherStub` 只是 warning stub。
- crawl4ai：`Crawl4AIFetcherStub` 只是 warning stub，没有真实 adapter。
- Sitemap：discovery 会探测 sitemap 并把相关招生/专业目录 URL 加入 priority frontier；`parse_sitemap_urls()` 仍由兼容/边界测试覆盖。
- 复杂专业体系抽取：已有保守的表头映射、group/section context 和误报拒绝路径，但仍无法稳定区分所有 degree、major、minor、second major、special programme 体系。
- 复杂表格/PDF 表格：HTML table 仍先转文本再按受支持形态解析，`pypdf` 只抽文本；当前不是通用 DOM/PDF table schema parser。
- Structured output 剩余 schema 讨论：`institution` scalar facts 尚未进入统一 fact envelope；如要加入，应作为 additive schema slice 并补 focused tests。
- 部分 schema 字段未填充：`international_requirements`、`standardized_tests`、`selection_tests_or_interviews` 当前基本未由 pipeline 写入。用途 partially unclear。
- `CrawlConfig` / `smoke_config()` 当前不是主要运行路径；作为兼容/未来配置入口保留，并由边界测试固定当前契约。

## 4. 如何运行项目

Fixture smoke：

```bash
.venv314/bin/python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --output-dir /tmp/uac-smoke \
  --max-pages 20 \
  --max-depth 3
```

Homepage-first live HTTP：

```bash
.venv314/bin/python -m university_admissions_crawler.cli https://www.example.edu/ \
  --output-dir outputs/example-live
```

需要收窄范围时再显式传 `--max-pages`、`--max-depth`、`--allowed-domain` 或
`--timeout-seconds`。

Batch config：

```bash
.venv314/bin/python -m university_admissions_crawler.cli \
  --config configs/universities.example.json \
  --output-dir outputs/batch
```

Tests：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
```

Syntax check：

```bash
python3 -m compileall university_admissions_crawler tests
```

注意：当前默认 `python3 -m pytest -q` 可能失败，因为默认 Python 环境未必安装 pytest。

## 5. 主要文件夹和文件说明

- `university_admissions_crawler/`：源码包。
- `university_admissions_crawler/cli.py`：CLI 参数解析、单次 fixture/live 扫描、调用 pipeline output writer 写结果；batch 扫描已委托给 pipeline 层。
- `university_admissions_crawler/config.py`：关键词和 `CrawlConfig`；当前使用较少。
- `university_admissions_crawler/config_loader.py`：batch JSON 配置读取。
- `university_admissions_crawler/crawler/`：fetcher、fetch result 类型、source type/content type helper、HTML/JSON 文本化与链接 helper、discovery、URL filter、招生上下文 gate、sitemap parser。
- `university_admissions_crawler/crawler/types.py`：`FetchResult` 和 `Fetcher` protocol；`crawler.fetcher` 仍 re-export 旧导入路径。
- `university_admissions_crawler/crawler/source_types.py`：URL/content-type/fixture path 到 `SourceType` 的判断 helper，以及 `SourceType` 到 content type 的映射 helper；`crawler.fetcher` 仍保留原 private helper 兼容名。
- `university_admissions_crawler/crawler/html_text.py`：HTML 主内容提取、噪音移除、typed blocks、table 转文本，
  以及在可见 blocks 为空时有界提取 JSON-LD `Course` cards。
- `university_admissions_crawler/crawler/json_content.py`：JSON 文本格式化、JSON link 提取、保序去重 helper；提供 public helper 名称，并保留 underscored 兼容别名。
- `university_admissions_crawler/crawler/optional_stubs.py`：crawl4ai 和 ScrapeGraphAI warning-only fetcher stub；`fetcher.py` 继续 re-export 原类名。
- `university_admissions_crawler/classifier/`：规则页面分类器。
- `university_admissions_crawler/extractor/`：schema、HTML/API/PDF/LLM 抽取和标准化解析。
- `university_admissions_crawler/extractor/institution_profiles.py`：按 official registrable domain
  选择 NUS/NTU profile，集中保存 domain-scoped programme name patterns 和 faculty aliases。
- `university_admissions_crawler/extractor/programme_catalog.py`：保守的 HTML programme catalog parser；负责候选账本、表头映射、group/section context、误报 gate 和字段级 evidence。
- `university_admissions_crawler/evidence/`：source/evidence helper、hash、source 文件写入、previous result 加载。
- `university_admissions_crawler/pipeline/`：扫描编排、source capture/context、category extraction、API catalog capture/augmentation、batch/merge、结果写出、diff 和 diagnostics。
- `university_admissions_crawler/pipeline/batch.py`：`--config` 批量扫描 orchestration；负责读取配置、计算 batch scan limits、按 university id 调用写出 helper、调用 `run_scan()`。
- `university_admissions_crawler/pipeline/merge.py`：批量多 seed 扫描结果合并；负责合并 requirement/programme/evidence claim path。
- `university_admissions_crawler/pipeline/programme_catalog_merge.py`：programme row 的跨来源身份匹配、
  canonical-first replacement、补充字段 evidence 和 merge/quarantine ledger。
- `university_admissions_crawler/pipeline/programme_detail_selection.py`：从首轮 pending/budget-skipped frontier
  中选择与未完整目录 row 唯一匹配的详情页，并记录 catalog-family、family budget 和拒绝原因。
- `university_admissions_crawler/pipeline/programme_catalog_completeness.py`：基于 canonical source、candidate/section
  conservation、source acquisition 和 API pagination/filter proof 生成 fail-closed completeness 结论。
- `university_admissions_crawler/pipeline/output_writer.py`：写出 `result.json`、`report.md`、legacy `programme_catalog.csv` 和 `structured/` 的小 helper；当前 CLI 单次扫描和 batch config 路径都已复用。
- `university_admissions_crawler/reports/`：Markdown 报告、legacy programme catalog CSV 和 structured output 渲染。
- `university_admissions_crawler/reports/structured_export.py`：清洗输出 export layer；只渲染 `AdmissionsData`，不改变 extractor 行为或 legacy 输出契约。
- `tests/`：pytest 测试与 fixture 站点。
- `tests/test_structured_output.py`：structured output 契约测试，覆盖可 join ID、清洗版 CSV、第二批 records、legacy 输出兼容和空 record 输出。
- `tests/test_compatibility_boundaries.py`：兼容别名和半使用接口的边界测试；用于防止低风险清理时误删仍需保留的入口。
- `configs/`：示例大学批量配置。
- `outputs/`：generated-only 输出目录；当前测试 fixture 已迁到 `tests/fixtures/saved_sources/`，测试不应再依赖这里。
- `outputs/nus-live-programmes/`：旧 NUS 一次性产物，包含 `result.json`、reports、`programmes.csv` 和 source index；作为 Phase 4 programme catalog 的参考样例保留。它包含 14 个 official sources、85 条 structured programme records、6 条 special programme records 和 28 个官方招生 A-Z 入口；但这是 browser/search extraction 与官方页面交叉核验的一次性产物，不代表当前通用 pipeline 已能稳定复现完整 NUS 专业体系。
- `outputs/batch*/`：旧 live/batch 扫描产物，包含 HKU、NTU、PolyU 等历史结果；作为参考样例保留，重新运行后才会反映当前代码。

## 6. 重要函数、类、组件说明

- `cli.main()`：命令行入口。
- `pipeline.batch._run_batch()` / `_run_university_config()`：batch config 扫描入口和单个大学配置扫描。
- `pipeline.batch._scan_limits_for_config()`：集中计算 batch config 的 `max_pages` / `max_depth`，保留 university config 覆盖 CLI/smoke 默认值的现有行为。
- `pipeline.merge.merge_data()`：合并多个 `AdmissionsData`，并重新指向合并后的 evidence claim path；`_merge_data` 仍作为兼容别名保留。
- `pipeline.output_writer.write_result_files()`：创建输出目录并写出 `result.json`、`report.md`、legacy `programme_catalog.csv` 和 `structured/`；返回 legacy result/report 两个输出路径以保留兼容。
- `extractor.programme_catalog.extract_programme_catalog()`：输出 evidence-backed catalog rows，并可记录每个 HTML candidate 的 accepted/rejected/context 诊断。
- `reports.structured_export.write_structured_outputs()`：写出清洗主表和证据表；当前 `facts.jsonl` 聚合 programme catalog、第二批 requirement records 和 legacy programme rows。
- `reports.structured_export.write_structured_batch_outputs()`：合并 batch 路径下每所学校已生成的 structured JSONL，写出 batch manifest、旧有三表和 12 类 requirement 聚合表；manifest 逐表区分 missing、present-empty 和 present-nonempty 输入，审计 row envelope、表级最小字段、同校 source/evidence 引用链、source/evidence ID 歧义和跨 record 表 ID 重复，再聚合为 `valid` / `incomplete` / `invalid` 三态 `batch_validation`。verdict 仅表示 structured artifact integrity，不表示官网信息完整；审计不丢弃、改写或去重异常行，也不改变 CLI 退出码。
- `run_fixture_scan()` / `run_scan()`：fixture 和通用扫描主入口。
- `pipeline.run_university_scan._default_pdf_extractor()`：默认 PDF extractor 策略；fixture fetcher 使用 `FixturePDFExtractor`，其他 fetcher 使用 `MissingPDFExtractor`，除非调用方显式传入 parser。
- `DiscoveryConfig` / `discover()`：扫描范围配置、全局 priority frontier、sitemap/path probing、extra candidates、
  programme source-family budget 和可选 pending frontier capture。
- `DomainPolicy` / `canonicalize_url()` / `score_url()`：域名允许规则、URL 规范化、链接排序。
- `FetchResult` / `Fetcher`：抓取结果和 fetcher protocol。
- `FixtureFetcher` / `LiveHTTPFetcher` / `PlaywrightBrowserFetcher`：三种实际抓取实现。
- `Crawl4AIFetcherStub` / `ScrapeGraphFetcherStub`：可选未来 fetch engine 的 warning-only stub；实现位于 `crawler/optional_stubs.py`，仍可从 `crawler.fetcher` 导入。
- `classify_page()`：页面规则分类。
- `AdmissionsData` / `FieldValue` / `EvidenceItem` / `SourceRecord`：核心输出与证据模型。
- `extract_api_claims()` 和 `extract_*()` HTML 抽取函数：把 source text 转为候选字段和 evidence。
- `parse_english_tests()` / `parse_money_candidates()` / `parse_application_dates()`：轻量结构化解析。
- `FixturePDFExtractor` / `MissingPDFExtractor` / `PypdfPDFExtractor`：fixture PDF、未启用 PDF parser 的 warning guard、可选真实 PDF 文本解析。
- `validate_llm_candidates()`：只接受能匹配已有 evidence 的 LLM 候选。
- `pipeline.source_planning`：校验 mock LLM source navigation 输出，accepted URL candidates 可作为 bounded crawl frontier hints；facts 仍必须来自抓到的官方 source 和 evidence。
- `attach_run_diagnostics()`：写入 coverage、source strategy、classification assist summary、extraction diagnostics summary、missing reasons 和 programme catalog 候选/evidence 聚合。
- `attach_validation_warnings()` / `normalize_admissions_data()`：证据、冲突、过期、非官方来源等 warning policy。
- `render_markdown_report()`：生成 Markdown 报告。

## 7. 已知问题

- `cli.py` 职责已减轻：merge、batch runner 和结果写出 helper 已拆到 pipeline 层；但 CLI 仍同时负责参数解析、单次扫描和部分 URL/domain helper。
- `pipeline/batch.py` 当前仍依赖 `argparse.Namespace` 和 `parser.error()`，并保留 `print()` 输出进度。文件写入细节已拆到 `pipeline/output_writer.py`，scan limit 计算已抽到 `_scan_limits_for_config()`，但 pipeline 层和 CLI 层边界仍不够干净。
- `pipeline/output_writer.py` 当前已被 CLI 单次扫描和 batch config 路径复用，并默认追加 `structured/` 输出。风险是未来修改该 helper 会同时影响两条输出路径，因此需要继续保留 CLI/report/structured-output 测试覆盖。
- `pipeline/merge.py` 已提供公开 `merge_data()`，并通过测试明确 `_merge_data` 兼容别名仍等同于 `merge_data`。后续需要决定是否长期保留该别名，或在确认没有外部依赖后删除。
- `cli.py` 和 `pipeline/batch.py` 之间仍有相似 URL/domain helper 逻辑；为避免扩大行为变更，本轮未抽公共 helper。
- `pipeline/run_university_scan.py` 已收敛为中心编排入口；source capture、captured context、category extraction、API catalog capture/augmentation 和 incremental diff 已拆成模块。后续仍应避免把新业务细节重新塞回编排文件。
- `pipeline/category_extraction.py` 目前集中分类路由、核心补抽取和 extraction diagnostics recorder；继续扩字段时应优先拆独立 extractor/helper，并保留 route-level 回归。
- `missing_reasons` 是当前抓取和 extractor 尝试的诊断，不是官网字段缺失证明；字段级 reason 的详细边界和后续修复循环见 `docs/keyword-crawl-design.zh.md`。
- source filtering 对 HKU 类站点有降噪收益，但低价值文档过滤仍有少量误删风险；招生 prospectus / entry requirements / tuition fees / programme requirements PDF 反例测试需要继续保留。
- NTU undergraduate fees 当前只能抽到官网 fee table/reference raw candidate，不是结构化金额。若要拿到具体金额，需要后续解析或抓取实际 fee table 内容。
- `crawler/fetcher.py` 文件仍偏大：fixture/live/browser fetcher 和 PDF HTTP fallback 仍在同一文件；HTML 文本化 helper 已拆到 `crawler/html_text.py`，JSON link/text helper 已拆到 `crawler/json_content.py`，optional stubs 已拆到 `crawler/optional_stubs.py`，fetch result 类型已拆到 `crawler/types.py`，source/content-type 判断已拆到 `crawler/source_types.py`。
- `crawler/json_content.py` 当前同时提供 public helper 和 underscored 兼容别名，API 面比之前更宽。后续如果决定只保留 public 名称，需要单独确认没有外部 private import。
- `crawler/optional_stubs.py` 已直接依赖 `crawler.types.FetchResult`，减少了对 `fetcher.py` 的循环导入风险；但仍延迟导入 `_fixed_retrieved_at()`，因为固定 fixture 时间 helper 还在 `fetcher.py`。
- `crawler/types.py` 和 `crawler/source_types.py` 拆出后，`crawler.fetcher` 仍保留 `FetchResult` / `Fetcher` 和 `_source_type_*` / `_content_type_*` private helper 兼容出口。后续如果要删除这些兼容名，需要单独确认外部调用风险。
- `tests/test_compatibility_boundaries.py` 新增后，兼容别名和半使用接口被测试固定；这会提高后续删除相关入口的显式成本，但能避免误删。
- 抽取质量主要取决于 regex 和文本上下文 gate，对真实复杂官网不稳定。
- live PDF 默认策略已明确：未启用 `--enable-pdf` 时，非 fixture PDF 只产生 `OPTIONAL_DEPENDENCY_MISSING` warning，不产生基于 fixture parser 的 evidence。风险是如果外部调用曾依赖旧的隐含 fixture parser 行为，会看到输出减少；当前测试已覆盖新策略。
- `outputs/` 已不应承担当期测试 fixture；如果后续需要保留样例，应迁到 `docs/examples/` 或记录清单。
- Structured output 当前 schema version 为 `structured-output-v1`，本阶段只做 additive 输出并保留 legacy 文件；`institution` scalar facts 尚未进入统一 fact envelope。
- `.venv314/`、`.omx/`、`.idea/` 不属于核心产品源码；是否保留需进一步确认。
- 旧临时归档目录已不再作为项目结构保留；其中的 handoff、fixture smoke 和 NUS one-off 摘要已经归并到 `docs/keyword-crawl-design.zh.md` 与本文件。
- README / VERSION_NOTES 已收敛职责；真实站点旧结果仍需要重跑才反映当前代码。

## 8. 下一步推荐清理方向

已完成：

1. 已稳定 housekeeping 变更并提交：`.gitignore`、`PROJECT_MAP.md`、缓存/`.DS_Store` 清理。
2. 已把测试依赖的 saved source 迁到 `tests/fixtures/saved_sources/`，并更新 HKU/NTU/PolyU 相关测试路径。
3. 已将 `outputs/` 明确为 generated-only；新测试不应再读取 `outputs/`。
4. 已保留 `outputs/` 历史输出，没有整体删除。删除或迁移样例前仍需要人工确认。
5. 已收敛 README / VERSION_NOTES 文档职责，避免把运行教程、版本快照和项目地图混在一起。
6. 已拆出 `cli.py` 的 merge helper 到 `pipeline/merge.py`，并保留 `_merge_data` 兼容别名。
7. 已拆出 `cli.py` 的 batch runner 到 `pipeline/batch.py`；CLI 只保留 `--config` 分支调用。
8. 已从 `crawler/fetcher.py` 拆出 HTML 文本化、JSON helper、optional warning-only stubs、`FetchResult` / `Fetcher`、source/content-type helper，并保留必要兼容出口。
9. 已明确 live PDF 默认策略：fixture 继续使用 `FixturePDFExtractor`，非 fixture 未显式启用 parser 时使用 `MissingPDFExtractor` 返回 warning。
10. 已让 CLI 单次扫描和 batch config 路径复用 `pipeline.output_writer.write_result_files()`。
11. 已新增 `tests/test_compatibility_boundaries.py`，集中覆盖兼容别名和半使用接口，避免低风险清理时误删仍需保留的入口。
12. 已在 `pipeline/batch.py` 抽出 `_scan_limits_for_config()`，只集中 batch `max_pages` / `max_depth` 计算，未改变 `parser.error()` 或 `print()` 行为。
13. 已补 diagnostics/source filtering 与 Phase 2 字段级诊断能力：classification assist summary、source-level extraction diagnostics、field-level missing reasons、低价值 source 过滤边界测试，以及 NTU fee raw/reference 与 amount-row 解析边界测试。专题设计和执行记录见 `docs/keyword-crawl-design.zh.md`。
14. 已将旧临时归档的 handoff、fixture smoke run 和 NUS one-off programme sample 摘要归并到 `docs/keyword-crawl-design.zh.md` 与本文件，临时归档目录不再作为项目结构保留。
15. 已新增 `structured/` output layer：保留 legacy `result.json` / `report.md` / root `programme_catalog.csv`，同时输出 joinable sources/evidence/facts/missing/warnings/diagnostics、`records/programme_catalog.*` 和第二批 requirement/legacy programme records。
16. 已新增 batch 级 structured 合并输出：根 manifest、programme catalog/missing/source 旧表和全部 12 类 requirement 聚合表，并补充 schema migration / compatibility policy。
17. 已完成 programme catalog HTML hardening：覆盖重排/partial header、metadata columns、grouped rows、HASS-like section context、字段级 evidence、候选拒绝 ledger，以及 Markdown/structured diagnostics 输出。
18. 已为 batch structured manifest 新增非阻断 `batch_validation`：`valid` 表示当前结构完整性校验通过，`incomplete` 表示仅有文件缺口或空输入，`invalid` 表示存在坏行、不可读索引、非法/歧义 ID 或证据断链；`invalid` 优先级最高。

当前验证基线见第 2 节；本清单不再保留旧阶段测试数，避免把历史验证误读为当前结果。

建议的后续顺序：

1. 继续找 NTU 公开 catalog API，并补 Sitecore/Next.js/GraphQL/Algolia/ElasticSearch 等高价值 adapter。风险：MEDIUM 到 HIGH。
2. 评估是否把 `institution` scalar facts 纳入统一 fact envelope；如做，只做 additive schema slice。风险：MEDIUM。
3. 继续拆 `crawler/fetcher.py`，但只做一类边界：优先考虑 PDF HTTP fallback 或 fixed/retrieved-at time helper，暂不同时拆 fixture/live/browser 类。风险：MEDIUM。
4. 继续收敛 pipeline 边界：`pipeline/batch.py` 仍依赖 `argparse.Namespace`、`parser.error()` 和 `print()`；如需拆，应先抽 options/diagnostic 小 helper，并用 `tests/test_report_cli.py` 覆盖。风险：MEDIUM。
5. 处理兼容出口：`crawler.fetcher.FetchResult` / `Fetcher` re-export、`crawler.fetcher._source_type_*`、`crawler.json_content._*`、`pipeline.merge._merge_data`。短期继续保留；如要删除，先 `rg` 全仓库并单独提交。风险：SAFE 到 MEDIUM。
6. 不要一次性重写 extractor，也不要随便引入新依赖；先用 fixture-backed tests 支撑小步重构，再针对未覆盖的跨区块 table、PDF、programme 体系补专项能力。风险：HIGH。
