# Project Map

## 1. 这个项目是做什么的

本项目是一个 Python 3.11+ 的大学本科招生信息抓取与抽取 MVP。它从本地 fixture 或显式开启的 live URL 出发，有限发现招生相关页面，抽取能被 source/evidence 支持的结构化字段，并生成 `result.json`、`report.md` 和 source 文件。

当前设计重点是 evidence-first：没有证据的招生事实应保持 `unknown` 或进入 `needs_manual_check` warning。项目不做录取判断、不做推荐、不做无边界爬取，也不绕过登录、验证码、WAF 或申请系统。

## 2. 当前已经能工作的功能

- Fixture 端到端扫描：`--fixture` 可跑 `tests/fixtures/mini_university_site/`。
- Live HTTP 扫描：`--enable-live-network` 或 `--auto` 显式开启。
- 可选 Playwright browser 扫描：`--enable-browser`，依赖未安装时返回 warning。
- 可选 PDF 文本解析：`--enable-pdf` 使用 `pypdf`，失败时返回 warning。
- 批量配置扫描：`--config` 读取 JSON 配置并按大学 ID 输出子目录。
- bounded discovery：通过 `max_pages`、`max_depth` 控制范围。
- URL/domain policy：支持 allowed host/domain、官方子域、URL 规范化和简单链接打分。
- 页面分类：规则分类招生、要求、截止日期、资格、专业、费用、奖学金、签证、住宿、联系信息和 irrelevant。
- 规则抽取：从 HTML/text 中抽取申请日期、英语要求、资格、专业、先修、费用、奖学金、签证、住宿、联系方式和材料。
- JSON/API 抽取：从公开 JSON 中保守抽取 programme、deadline、tuition fee、required documents。
- 证据与校验：记录 source、snippet、claim path、hash、warnings，并校验 non-unknown claim 是否有 evidence。
- 报告输出：生成 Markdown evidence report。
- 增量 diff：传入 previous result 时记录 source hash 和字段变化。
- 测试：`.venv314` 环境下当前 pytest 结果为 `76 passed`。

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
- `university_admissions_crawler/cli.py`：CLI、单次扫描、批量扫描、结果写入。
- `university_admissions_crawler/config.py`：关键词和 `CrawlConfig`；当前使用较少。
- `university_admissions_crawler/config_loader.py`：batch JSON 配置读取。
- `university_admissions_crawler/crawler/`：fetcher、discovery、URL filter、招生上下文 gate、sitemap parser。
- `university_admissions_crawler/classifier/`：规则页面分类器。
- `university_admissions_crawler/extractor/`：schema、HTML/API/PDF/LLM 抽取和标准化解析。
- `university_admissions_crawler/evidence/`：source/evidence helper、hash、source 文件写入、previous result 加载。
- `university_admissions_crawler/pipeline/`：扫描主流程、diff、coverage/source strategy diagnostics。
- `university_admissions_crawler/reports/`：Markdown 报告渲染。
- `tests/`：pytest 测试与 fixture 站点。
- `configs/`：示例大学批量配置。
- `outputs/`：generated-only 输出目录；当前测试 fixture 已迁到 `tests/fixtures/saved_sources/`，测试不应再依赖这里。
- `outputs/nus-live-programmes/`：旧 NUS 一次性产物，包含 `result.json`、reports、`programmes.csv` 和 source index；作为参考样例保留，是否迁到 docs unclear。
- `outputs/batch*/`：旧 live/batch 扫描产物，包含 HKU、NTU、PolyU 等历史结果；作为参考样例保留，重新运行后才会反映当前代码。
- `temp_imports/`：previous-session archive。是否仍需保留 unclear。

## 6. 重要函数、类、组件说明

- `cli.main()`：命令行入口。
- `run_fixture_scan()` / `run_scan()`：fixture 和通用扫描主入口。
- `DiscoveryConfig` / `discover()`：扫描范围配置和 bounded discovery。
- `DomainPolicy` / `canonicalize_url()` / `score_url()`：域名允许规则、URL 规范化、链接排序。
- `FetchResult` / `Fetcher`：抓取结果和 fetcher protocol。
- `FixtureFetcher` / `LiveHTTPFetcher` / `PlaywrightBrowserFetcher`：三种实际抓取实现。
- `classify_page()`：页面规则分类。
- `AdmissionsData` / `FieldValue` / `EvidenceItem` / `SourceRecord`：核心输出与证据模型。
- `extract_api_claims()` 和 `extract_*()` HTML 抽取函数：把 source text 转为候选字段和 evidence。
- `parse_english_tests()` / `parse_money_candidates()` / `parse_application_dates()`：轻量结构化解析。
- `FixturePDFExtractor` / `PypdfPDFExtractor`：fixture PDF 和可选真实 PDF 文本解析。
- `validate_llm_candidates()`：只接受能匹配已有 evidence 的 LLM 候选。
- `attach_run_diagnostics()`：写入 coverage 和 source strategy。
- `attach_validation_warnings()` / `normalize_admissions_data()`：证据、冲突、过期、非官方来源等 warning policy。
- `render_markdown_report()`：生成 Markdown 报告。

## 7. 已知问题

- `cli.py` 职责偏重：参数解析、批量扫描、merge、文件写入混在一起。
- `pipeline/run_university_scan.py` 职责偏重：调度、分类分流、抽取、PDF、补抽取、diff 混在一起。
- `crawler/fetcher.py` 文件偏大：fixture/live/browser fetcher、future stub、HTML 文本化 helper 都在同一文件。
- 抽取质量主要取决于 regex 和文本上下文 gate，对真实复杂官网不稳定。
- 未启用 `--enable-pdf` 时，pipeline 默认使用 `FixturePDFExtractor()`；对真实 PDF bytes 的语义不清晰。
- `outputs/` 已不应承担当期测试 fixture；如果后续需要保留样例，应迁到 `docs/examples/` 或记录清单。
- `.venv314/`、`.omx/`、`.idea/`、`temp_imports/` 不属于核心产品源码；是否保留需进一步确认。
- README / VERSION_NOTES 可能描述旧输出状态；真实站点旧结果需要重跑才反映当前代码。

## 8. 下一步推荐清理方向

1. 稳定当前 housekeeping 变更。先单独提交 `.gitignore`、`PROJECT_MAP.md` 和已删除的缓存/`.DS_Store`，避免后续结构调整与生成物清理混在一起。
2. 把测试依赖的 saved source 从 `outputs/` 迁到 `tests/fixtures/saved_sources/`，只迁移测试实际读取的 HKU/NTU/PolyU source 文件，再更新测试路径。
3. 已将 `outputs/` 明确为 generated-only；不要让新测试再读取 `outputs/`。仍有价值的样例输出可移动到 `docs/examples/` 或记录保留清单。
4. 不要直接整体删除 `outputs/`。当前目录仍保留 NUS、HKU、NTU、PolyU 历史输出，删除前需要确认是否迁移样例或归档。
5. 把 `cli.py` 的 batch 扫描、数据 merge 和结果写入逻辑拆到 pipeline 层，例如 `pipeline/batch.py` 和 `pipeline/merge.py`，保持 CLI 行为不变。
6. 拆分 `crawler/fetcher.py`，先把 HTML 文本化 helper 与 fetcher 实现分开，再按 fixture/live HTTP/Playwright/stub 拆文件。
7. 处理未使用或半使用接口：`CrawlConfig` / `smoke_config()`、`parse_sitemap_urls()`、`source_hashes()`、`_looks_like_false_english_requirement()`。先加说明或测试，再决定删除。
8. 明确 live PDF 默认策略。未启用 `--enable-pdf` 时，live PDF 应记录 source 和 warning，而不是按 fixture PDF 解析；fixture PDF 仍可使用 `FixturePDFExtractor`。
9. 对未填充 schema 字段做兼容性决策：`international_requirements`、`standardized_tests`、`selection_tests_or_interviews` 应标为 experimental、补 pipeline 行为，或在兼容计划后移除。
10. 不要一次性重写 extractor，也不要随便引入新依赖；先用 fixture-backed tests 支撑小步重构，再针对复杂 table、PDF、programme 抽取补专项能力。
