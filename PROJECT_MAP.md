# Project Map

## 1. 这个项目是做什么的

本项目是一个 Python 3.11+ 的大学本科招生信息抓取与抽取 MVP。它从本地 fixture 或显式开启的 live URL 出发，有限发现招生相关页面，抽取能被 source/evidence 支持的结构化字段，并生成 `result.json`、`report.md` 和 source 文件。

当前设计重点是 evidence-first：没有证据的招生事实应保持 `unknown` 或进入 `needs_manual_check` warning。项目不做录取判断、不做推荐、不做无边界爬取，也不绕过登录、验证码、WAF 或申请系统。

## 2. 当前已经能工作的功能

- Fixture 端到端扫描：`--fixture` 可跑 `tests/fixtures/mini_university_site/`。
- Live HTTP 扫描：`--enable-live-network` 或 `--auto` 显式开启。
- 可选 Playwright browser 扫描：`--enable-browser`，依赖未安装时返回 warning。
- 可选 PDF 文本解析：`--enable-pdf` 使用 `pypdf`，失败时返回 warning；未启用时 live PDF 只记录 warning，不再按 fixture PDF 文本解析。
- 批量配置扫描：`--config` 读取 JSON 配置并按大学 ID 输出子目录。
- bounded discovery：通过 `max_pages`、`max_depth` 控制范围。
- URL/domain policy：支持 allowed host/domain、官方子域、URL 规范化和简单链接打分。
- 页面分类：规则分类招生、要求、截止日期、资格、专业、费用、奖学金、签证、住宿、联系信息和 irrelevant。
- 规则抽取：从 HTML/text 中抽取申请日期、英语要求、资格、专业、先修、费用、奖学金、签证、住宿、联系方式和材料。
- JSON/API 抽取：从公开 JSON 中保守抽取 programme、deadline、tuition fee、required documents。
- 证据与校验：记录 source、snippet、claim path、hash、warnings，并校验 non-unknown claim 是否有 evidence。
- 报告输出：生成 Markdown evidence report。
- 增量 diff：传入 previous result 时记录 source hash 和字段变化。
- 测试：`.venv314` 环境下当前 pytest 结果为 `79 passed`；saved-source 迁移相关局部测试为 `20 passed`。

## 3. 未完成或实验性功能

- LLM：CLI 有 `--enable-llm` / `--llm-provider`，但当前直接报错；代码里只有 provider protocol、mock 和 evidence-gated candidate 校验。
- ScrapeGraphAI：CLI 有 `--enable-scrapegraph`，但当前直接报错；`ScrapeGraphFetcherStub` 只是 warning stub。
- crawl4ai：`Crawl4AIFetcherStub` 只是 warning stub，没有真实 adapter。
- Sitemap：`parse_sitemap_urls()` 存在，但当前 discovery 主流程未使用。用途 unclear。
- 复杂专业体系抽取：当前主要是 regex，无法稳定区分 degree、major、minor、second major、special programme 等。
- 复杂表格/PDF 表格：HTML table 只转文本，`pypdf` 只抽文本；不是结构化表格解析。
- 部分 schema 字段未填充：`international_requirements`、`standardized_tests`、`selection_tests_or_interviews` 当前基本未由 pipeline 写入。用途 partially unclear。
- `CrawlConfig` / `smoke_config()` 当前不是主要运行路径。保留原因 unclear。

## 4. 如何运行项目

Fixture smoke：

```bash
.venv314/bin/python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --output-dir /tmp/uac-smoke \
  --max-pages 20 \
  --max-depth 3
```

Live HTTP：

```bash
.venv314/bin/python -m university_admissions_crawler.cli https://www.example.edu/admissions \
  --enable-live-network \
  --allowed-domain example.edu \
  --output-dir outputs/example-live \
  --max-pages 30 \
  --max-depth 2
```

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
- `university_admissions_crawler/crawler/`：fetcher、HTML/JSON 文本化与链接 helper、discovery、URL filter、招生上下文 gate、sitemap parser。
- `university_admissions_crawler/crawler/html_text.py`：HTML 主内容提取、噪音移除、table 转文本、tag stripping helper。
- `university_admissions_crawler/crawler/json_content.py`：JSON 文本格式化、JSON link 提取、保序去重 helper；提供 public helper 名称，并保留 underscored 兼容别名。
- `university_admissions_crawler/crawler/optional_stubs.py`：crawl4ai 和 ScrapeGraphAI warning-only fetcher stub；`fetcher.py` 继续 re-export 原类名。
- `university_admissions_crawler/classifier/`：规则页面分类器。
- `university_admissions_crawler/extractor/`：schema、HTML/API/PDF/LLM 抽取和标准化解析。
- `university_admissions_crawler/evidence/`：source/evidence helper、hash、source 文件写入、previous result 加载。
- `university_admissions_crawler/pipeline/`：扫描主流程、batch orchestration、batch 结果合并、结果写出 helper、diff、coverage/source strategy diagnostics。
- `university_admissions_crawler/pipeline/batch.py`：`--config` 批量扫描 orchestration；负责读取配置、按 university id 调用写出 helper、调用 `run_scan()`。
- `university_admissions_crawler/pipeline/merge.py`：批量多 seed 扫描结果合并；负责合并 requirement/programme/evidence claim path。
- `university_admissions_crawler/pipeline/output_writer.py`：写出 `result.json` 和 `report.md` 的小 helper；当前 CLI 单次扫描和 batch config 路径都已复用。
- `university_admissions_crawler/reports/`：Markdown 报告渲染。
- `tests/`：pytest 测试与 fixture 站点。
- `configs/`：示例大学批量配置。
- `outputs/`：generated-only 输出目录；当前测试 fixture 已迁到 `tests/fixtures/saved_sources/`，测试不应再依赖这里。
- `outputs/nus-live-programmes/`：旧 NUS 一次性产物，包含 `result.json`、reports、`programmes.csv` 和 source index；作为参考样例保留，是否迁到 docs unclear。
- `outputs/batch*/`：旧 live/batch 扫描产物，包含 HKU、NTU、PolyU 等历史结果；作为参考样例保留，重新运行后才会反映当前代码。
- `temp_imports/`：previous-session archive。是否仍需保留 unclear。

## 6. 重要函数、类、组件说明

- `cli.main()`：命令行入口。
- `pipeline.batch._run_batch()` / `_run_university_config()`：batch config 扫描入口和单个大学配置扫描。
- `pipeline.merge.merge_data()`：合并多个 `AdmissionsData`，并重新指向合并后的 evidence claim path；`_merge_data` 仍作为兼容别名保留。
- `pipeline.output_writer.write_result_files()`：创建输出目录并写出 `result.json` 与 `report.md`，返回两个输出路径。
- `run_fixture_scan()` / `run_scan()`：fixture 和通用扫描主入口。
- `pipeline.run_university_scan._default_pdf_extractor()`：默认 PDF extractor 策略；fixture fetcher 使用 `FixturePDFExtractor`，其他 fetcher 使用 `MissingPDFExtractor`，除非调用方显式传入 parser。
- `DiscoveryConfig` / `discover()`：扫描范围配置和 bounded discovery。
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
- `attach_run_diagnostics()`：写入 coverage 和 source strategy。
- `attach_validation_warnings()` / `normalize_admissions_data()`：证据、冲突、过期、非官方来源等 warning policy。
- `render_markdown_report()`：生成 Markdown 报告。

## 7. 已知问题

- `cli.py` 职责已减轻：merge、batch runner 和结果写出 helper 已拆到 pipeline 层；但 CLI 仍同时负责参数解析、单次扫描和部分 URL/domain helper。
- `pipeline/batch.py` 当前仍依赖 `argparse.Namespace` 和 `parser.error()`，并保留 `print()` 输出进度。文件写入细节已拆到 `pipeline/output_writer.py`，但 pipeline 层和 CLI 层边界仍不够干净。
- `pipeline/output_writer.py` 当前已被 CLI 单次扫描和 batch config 路径复用。风险是未来修改该 helper 会同时影响两条输出路径，因此需要继续保留 CLI/report 测试覆盖。
- `pipeline/merge.py` 已提供公开 `merge_data()`，并通过测试明确 `_merge_data` 兼容别名仍等同于 `merge_data`。后续需要决定是否长期保留该别名，或在确认没有外部依赖后删除。
- `cli.py` 和 `pipeline/batch.py` 之间仍有相似 URL/domain helper 逻辑；为避免扩大行为变更，本轮未抽公共 helper。
- `pipeline/run_university_scan.py` 职责偏重：调度、分类分流、抽取、PDF、补抽取、diff 混在一起。
- `crawler/fetcher.py` 文件仍偏大：fixture/live/browser fetcher 和 PDF HTTP fallback 仍在同一文件；HTML 文本化 helper 已拆到 `crawler/html_text.py`，JSON link/text helper 已拆到 `crawler/json_content.py`，optional stubs 已拆到 `crawler/optional_stubs.py`。
- `crawler/json_content.py` 当前同时提供 public helper 和 underscored 兼容别名，API 面比之前更宽。后续如果决定只保留 public 名称，需要单独确认没有外部 private import。
- `crawler/optional_stubs.py` 为避免与 `fetcher.py` 循环导入，使用函数内延迟导入 `FetchResult` 和 `_fixed_retrieved_at()`。可工作但不是最终理想边界；如果后续把 fetch result 类型移到独立模块，可再收紧。
- 抽取质量主要取决于 regex 和文本上下文 gate，对真实复杂官网不稳定。
- live PDF 默认策略已明确：未启用 `--enable-pdf` 时，非 fixture PDF 只产生 `OPTIONAL_DEPENDENCY_MISSING` warning，不产生基于 fixture parser 的 evidence。风险是如果外部调用曾依赖旧的隐含 fixture parser 行为，会看到输出减少；当前测试已覆盖新策略。
- `outputs/` 已不应承担当期测试 fixture；如果后续需要保留样例，应迁到 `docs/examples/` 或记录清单。
- `.venv314/`、`.omx/`、`.idea/`、`temp_imports/` 不属于核心产品源码；是否保留需进一步确认。
- README / VERSION_NOTES 已收敛职责；真实站点旧结果仍需要重跑才反映当前代码。

## 8. 下一步推荐清理方向

已完成：

1. 已稳定 housekeeping 变更并提交：`.gitignore`、`PROJECT_MAP.md`、缓存/`.DS_Store` 清理。
2. 已把测试依赖的 saved source 迁到 `tests/fixtures/saved_sources/`，并更新 HKU/NTU/PolyU 相关测试路径。
3. 已将 `outputs/` 明确为 generated-only；新测试不应再读取 `outputs/`。
4. 已保留 `outputs/` 历史输出，没有整体删除。删除或迁移样例前仍需要人工确认。
5. 已收敛 README / VERSION_NOTES 文档职责，避免把运行教程、版本快照和项目地图混在一起。
6. 已拆出 `cli.py` 的 merge helper 到 `pipeline/merge.py`。行为保持原样，当前验证：`tests/test_report_cli.py tests/test_pipeline.py` 为 `26 passed`，完整 pytest 为 `76 passed`。
7. 已拆出 `cli.py` 的 batch runner 到 `pipeline/batch.py`。CLI 只保留 `--config` 分支调用，当前验证同上。
8. 已从 `crawler/fetcher.py` 拆出 HTML 文本化 helper 到 `crawler/html_text.py`。行为保持原样，当前验证：`tests/test_fetcher.py tests/test_pipeline.py` 为 `32 passed`，完整 pytest 为 `76 passed`。
9. 已把 `pipeline.merge._merge_data()` 改为公开 `merge_data()`，并保留 `_merge_data` 兼容别名。当前验证：`tests/test_report_cli.py tests/test_pipeline.py` 为 `26 passed`，完整 pytest 为 `76 passed`。
10. 已明确 live PDF 默认策略：fixture 继续使用 `FixturePDFExtractor`，非 fixture 未显式启用 parser 时使用 `MissingPDFExtractor` 返回 warning。当前验证：PDF/pipeline/failure 相关测试为 `32 passed`，完整 pytest 为 `77 passed`。
11. 已从 `crawler/fetcher.py` 拆出 JSON link/text helper 到 `crawler/json_content.py`。`fetcher.py` 仍重新导入原 private helper 名称以降低兼容风险。当前验证：完整 pytest 为 `79 passed`。
12. 已新增 `pipeline/output_writer.py`，并让 batch config 路径通过 `write_result_files()` 写出 `result.json` 和 `report.md`。当前验证：`tests/test_report_cli.py tests/test_pipeline.py` 为 `29 passed`，完整 pytest 为 `79 passed`。
13. 已明确 `_merge_data` 短期继续作为 `merge_data` 的兼容别名，并新增测试确认 `_merge_data is merge_data`。当前验证：完整 pytest 为 `79 passed`。
14. 已让 `cli.py` 单次扫描复用 `pipeline.output_writer.write_result_files()`，输出文件名和 `print()` 文案保持不变。当前验证：`tests/test_report_cli.py` 为 `8 passed`，完整 pytest 为 `79 passed`。
15. 已从 `crawler/fetcher.py` 拆出 optional warning-only stubs 到 `crawler/optional_stubs.py`，并从 `fetcher.py` 继续 re-export `Crawl4AIFetcherStub` / `ScrapeGraphFetcherStub`。当前验证：`tests/test_fetcher.py tests/test_report_cli.py` 为 `21 passed`，完整 pytest 为 `79 passed`。
16. 已把 `crawler/json_content.py` 的 helper 改为 public 名称，并保留 underscored 兼容别名；`fetcher.py` 改用 public helper，同时保留模块层 private 名称兼容。当前验证：`tests/test_fetcher.py tests/test_pipeline.py` 为 `34 passed`，完整 pytest 为 `79 passed`。

建议的后续顺序：

1. 继续拆 `crawler/fetcher.py`，但只做一类边界：优先考虑 PDF HTTP fallback 或 source type/content type helper，暂不同时拆 fixture/live/browser 类。风险：MEDIUM。
2. 考虑把 `FetchResult` / `Fetcher` 类型移到独立模块，减少 `optional_stubs.py` 的延迟导入和后续 adapter 循环导入风险；这会影响多个 import，需单独测试。风险：MEDIUM。
3. 继续收敛 pipeline 边界：`pipeline/batch.py` 仍依赖 `argparse.Namespace`、`parser.error()` 和 `print()`；如需拆，应先抽 options/diagnostic 小 helper，并用 `tests/test_report_cli.py` 覆盖。风险：MEDIUM。
4. 处理 `pipeline/merge.py` 的兼容别名：短期继续保留 `_merge_data`；如果决定删除，先 `rg` 确认仓库和外部调用风险，并单独提交。风险：SAFE 到 MEDIUM。
5. 决定 `crawler/json_content.py` underscored 兼容别名是否长期保留；如要删除，先 `rg` 全仓库并单独提交。风险：SAFE 到 MEDIUM。
6. 处理未使用或半使用接口：`CrawlConfig` / `smoke_config()`、`parse_sitemap_urls()`、`source_hashes()`、`_looks_like_false_english_requirement()`。先加说明或测试，再决定删除。风险：SAFE 到 MEDIUM。
7. 对未填充 schema 字段做兼容性决策：`international_requirements`、`standardized_tests`、`selection_tests_or_interviews` 应标为 experimental、补 pipeline 行为，或在兼容计划后移除。风险：MEDIUM 到 HIGH。
8. 评估 `outputs/nus-live-programmes/` 和 `outputs/batch*/` 中仍有价值的样例是否迁到 `docs/examples/` 或保留清单。任何移动或删除都需要人工确认。风险：MEDIUM。
9. 不要一次性重写 extractor，也不要随便引入新依赖；先用 fixture-backed tests 支撑小步重构，再针对复杂 table、PDF、programme 抽取补专项能力。风险：HIGH。
