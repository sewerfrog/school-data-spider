# 版本说明：University Admissions Crawler MVP

快照日期：2026-06-16
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
- Missing reasons：对 `coverage.missing` 增加字段级 `missing_reasons`，用于说明当前 crawl/extractor 链路卡在 `not_attempted`、`attempted_no_match`、`context_gate_failed`、`application_portal_unreachable` 等位置。它不是官网缺失证明。
- NTU fees saved-source 回归：NTU undergraduate tuition fee 页面已通过 fee context gate；在当前 saved text 没有金额时，extractor 只输出官方 fee table/reference raw candidate，`parse_status` 为 `raw_needs_manual_review`，不伪造结构化金额。
- Saved-source 回归材料：测试依赖的 HKU/NTU/PolyU saved source 已复制到 `tests/fixtures/saved_sources/`，测试不应再读取 `outputs/`。
- `outputs/` 语义收敛：`outputs/` 保留为生成输出和历史参考样例目录，不作为当前 deterministic test fixture 来源。
- 结构清理：单次扫描和 batch 扫描已共用 `pipeline/output_writer.py` 写出 `result.json` / `report.md`。
- crawler 边界拆分：`FetchResult` / `Fetcher` 已拆到 `crawler/types.py`，source/content-type 判断已拆到 `crawler/source_types.py`，JSON helper 已拆到 `crawler/json_content.py`，optional warning-only stubs 已拆到 `crawler/optional_stubs.py`。
- 兼容保护：旧的 `crawler.fetcher` 导入路径、JSON underscored helper、`pipeline.merge._merge_data` 等兼容入口仍保留，并由 `tests/test_compatibility_boundaries.py` 覆盖。
- Batch 边界收敛：`pipeline/batch.py` 已抽出 `_scan_limits_for_config()`，但仍保留 `argparse.Namespace`、`parser.error()` 和 `print()` 行为。

## 3. 已知仍有限制

- 真实官网抽取仍不是生产级；复杂专业体系、复杂费用表、多轮申请日期和 PDF 表格需要更强的 section/table 级解析。
- NTU fees 当前只是找到官方 fee table/reference，不是完成金额结构化解析；后续需要抓到或解析实际 table 内容。
- `missing_reasons` 描述的是当前抓取和 extractor 尝试结果，不能证明官网没有提供该字段；多 source 混合失败时字段级归因优先级仍可优化。
- source filtering 有明确降噪收益，但低价值文档关键词仍可能误伤极少数招生材料，因此 admissions PDF 反例测试需要继续保留。
- `outputs/nus-live-programmes/` 是旧的一次性 NUS 产物，不能代表当前通用 pipeline 已能稳定复现完整 NUS 专业体系。
- 旧的 HKU/NTU/PolyU/NUS `outputs/` 结果不会因代码修复自动更新；要看到新行为需要重新跑真实学校 crawl。
- Browser 抓取依赖本地 Playwright 和 Chromium；缺失时应返回 `optional_dependency_missing` warning。
- WAF、portal、challenge 页面和连接关闭仍可能导致抓取失败或抓到无效内容。
- `overall confidence` 不是覆盖率指标；字段是否完整应同时查看 coverage 和 warnings。
- 通用 pipeline 当前只输出英文 `report.md`；中文报告尚未通用化。
- 当前没有 scheduler、来源失效监控或业务级定时 diff。

## 4. 本轮验证参考

当前完整验证已通过：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
```

结果：`112 passed`。

与本轮 diagnostics/source-filtering/report 相关的目标测试组：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
```

结果：`57 passed`。

完整验证命令和环境说明请看 `README.md`。

## 5. 下一版本方向

- 增强 DOM / section / table 级解析，减少长页面和复杂 CMS 的文本污染。
- 增强专业抽取器，区分 degree programme、major、minor、second major、special programme。
- 增强日期、费用和奖学金抽取，支持多申请人群、多轮次、多 cohort 和资助类型。
- 优先优化 `missing_reasons` 的字段级归因优先级，避免同一字段多个 source 混合失败时展示次要原因。
- 继续处理 NTU fees 的真实表格内容解析；当前只应把 saved-source 行为视为 raw reference fallback。
- 增强 PDF 表格解析；是否引入 `pdfplumber` 或同类依赖需要单独评估。
- 将有价值的真实学校样例迁移到更明确的 `docs/examples/` 或记录保留清单，避免继续混用 `outputs/`。
- 继续小步拆分 `crawler/fetcher.py` 剩余的 PDF fallback 或时间 helper，避免同时移动 fixture/live/browser fetcher 类。
- 继续收敛 `pipeline/batch.py` 和 `pipeline/run_university_scan.py` 的过重职责；任何删除兼容入口前先用 `rg` 确认调用风险并单独提交。

## 6. 文档分工

- `README.md`：项目简介、安装、运行、测试和使用注意事项。
- `PROJECT_MAP.md`：当前模块地图、已知问题、清理方向和维护计划。
- `VERSION_NOTES.zh.md`：当前版本快照和变更说明，不再承担完整运行教程或项目地图职责。
