# 官网主页自动招生爬取：当前状态与未完成计划

## 文档定位

这份文档只保留当前工程状态和下一步计划，不再记录 Phase 3/4/5/6 的历史流水账。

当前主目标：

- 输入学校官网主页后，自动发现招生、专业目录、费用、申请要求等官方 source。
- 只从 captured official source 写入 facts；没有证据的字段保持 `unknown`、missing reason 或
  manual-review diagnostics。
- `programme_catalog.csv` 只渲染 `AdmissionsData.programme_catalog`；CSV 本身不负责发现、
  补全或判断专业目录完整性。
- 高基数专业目录继续由 `programme_catalog` 承载，不回退到 legacy `programmes`。

当前最重要的剩余目标：

1. 针对 NTU 继续验证公开 catalog API 或可枚举数据源；当前 browser second-pass 已验证，
   但没有捕获到 JSON/API network response；最小 NTU rerun 已发现一个 suggestions API hint，
   但没有拿到 catalog JSON。
2. 继续收紧 HTML fallback，阻断长正文、second-major 说明和未知表格变体误写入专业目录。
3. 补 NTU/HASS 这类段落式学院页 fallback。
4. 继续补 rejected-row 级别 false-positive diagnostics。
5. 为高价值学校补 GraphQL、Algolia、Sitecore、Next.js data、ElasticSearch adapter。

## 当前结论

API catalog 主路径已经有首版实现，但 `outputs/ntu-api-live` 证明它还没有在 NTU 全校本科目录
页上触发。当前 NTU CSV 不是 API 结果，而是 HTML fallback 的不完整结果。当前代码已新增
static asset discovery，并用 NTU 动态目录页做过最小预算 rerun；该 rerun 没有产生完整 catalog
JSON，不能作为全校专业目录验收结果。

当前工作区新增的 `outputs/ntu-api-live-current` 进一步确认：

- `programme_catalog_browser_capture.triggered=true`。
- browser second-pass 成功打开
  `/admissions/undergraduate-programmes?listingKeyword=&disciplines=all&programmelevels=all&programmetypes=all&page=1`。
- `network_response_count=0`、`network_body_count=0`。
- `api_candidate_zero_reason=browser_capture_no_network_json`。
- `recommended_next_action=discover_public_catalog_api`。
- captured source 仍只有 `Programme Level`、`Programme Type`、`Full-time`、`Part-time` 等筛选器，
  没有专业 rows。

当前工作区新增的 `outputs/ntu-api-live-static-assets` 进一步确认：

- 输入页：
  `/admissions/undergraduate-programmes?listingKeyword=&disciplines=all&programmelevels=all&programmetypes=all&page=1`。
- `api_endpoint_candidate_count=1`。
- 唯一 candidate 是 `/api/suggestions/get?...programmesIndex=programmes...`。
- safe capture attempted 1，结果 `capture_failed`。
- `programme_catalog` 仍为 0 rows。
- `recommended_next_action=discover_public_catalog_api`。
- `programme_catalog_static_asset_discovery` 没有触发，因为页面源码本身已先发现 embedded API hint；
  static asset discovery 只在 API candidate 仍为 0 时启用。

关键证据：

- `outputs/ntu-api-live/report.md`：
  - `candidate sources 37`
  - `accepted rows 18`
  - `API pages 0`
  - `API accepted rows 0`
  - `HTML fallback used True`
  - `probable incomplete True`
  - `next action improve_table_segmentation`
- `outputs/ntu-api-live/result.json`：
  - `api_catalog_candidate_count=0`
  - `api_response_count=0`
  - `api_accepted_row_count=0`
  - `html_fallback_used=true`
  - `api_to_csv_ratio=0.0`
- `outputs/ntu-api-live/sources/3be6b8dadccb2123.txt`：
  - `/admissions/undergraduate-programmes` 只保存到 `Programme Level All`、
    `Programme Type All` 等筛选器文本，没有实际 programme rows。
- `outputs/ntu-api-live/programme_catalog.csv`：
  - 只有 18 条数据行。
  - 结果被 `/adm/programmes/undergraduate-programmes/...` ADM/BFA 子树主导。
  - 出现 `BEng SCE`、`BEng Design Stream` 这类来自 course table `Open to` 列的 false positive。

因此，下一步优先级不是继续堆更多 line-based parser，而是先补 API acquisition：

```text
dynamic shell -> browser/network capture
dynamic shell + API 0 -> same-domain static JS asset endpoint discovery
network JSON body -> catalog detector
official JSON object -> programme_catalog
HTML/static parser -> fallback only
diagnostics -> 判断是否完整、为什么不完整
```

## 已完成能力压缩索引

### 1. 扫描主链路

已完成：

- fixture scan、live HTTP scan、可选 browser mode、可选 PDF parsing。
- homepage-first discovery、sitemap、bounded frontier、common path probing。
- source strategy diagnostics、template completeness、missing reasons。
- `run_university_scan.py` 已完成首轮拆分：输出写入、diagnostics、API catalog helper、
  LLM runtime 等能力已有独立模块承接；入口仍保留编排职责。

仍保留风险：

- `run_university_scan.py` 仍是中心编排入口，后续新增复杂 diagnostics 前应继续抽小 helper。
- source acquisition 的完整性取决于预算、动态页面和站点结构，diagnostics 只能解释本次 run，
  不能证明官网从未提供某字段。

### 2. 能力边界与 missing reasons

已完成：

- `field_capability_matrix`。
- canonical `missing_reasons`。
- `action_target` / `next_action`。
- Markdown report capability 说明。
- 兼容旧字段：`missing_reasons[*].reason` 保持 legacy 标签，新分类写入
  `missing_reasons[*].canonical_reason`。

仍保留风险：

- diagnostics 是解释层，不是事实来源。
- 不能把 `no_match`、`context_gate_failed`、`existing_value`、`portal_unreachable` 简化成同一种
  “缺失”。

### 3. Programme Catalog schema 与 CSV

已完成：

- `ProgrammeCatalogRecord` 和 `AdmissionsData.programme_catalog`。
- `programme_catalog.csv` renderer。
- row-level evidence path 校验。
- `programme_catalog_summary` 基础统计：
  - candidate/crawled catalog source count
  - accepted rows
  - raw-needs-review rows
  - row warnings
  - low row yield
  - probable incomplete
  - recommended next action
- HTML/static parser 已能处理部分表格、列表和 flattened table-like text。
- HTML/static parser 已加入课程表止血规则，阻断 `Course Code`、`Course Title`、`AU`、
  `Pre-req`、`Open to`、`Major PE Courses` 等课程表上下文被误写成专业 row。

仍保留风险：

- HTML parser 仍可能误抽长正文、second-major 说明或未知表格变体。
- 单一子树污染尚未作为明确 diagnostics，例如 NTU ADM/BFA 子树主导结果。
- NTU school/faculty context 不足，导致大量 `faculty_or_school=unknown`。

### 4. API Catalog 首版

已完成：

- API candidate discovery diagnostics。
- 安全 JSON capture：
  - 同域。
  - GET。
  - JSON content type 或 JSON body。
  - response size 上限。
  - 不 replay auth、token、POST、off-domain redirect。
- `extract_programme_catalog_api()`：
  - 支持 list、items/results/data、edges/nodes 等常见 JSON 结构。
  - 只从真实 JSON object 生成 `programme_catalog` rows。
  - 缺 name、导航/筛选器、长文本 object 会被 rejected。
- pagination proof：
  - page/pageSize。
  - offset/limit。
  - cursor/hasNextPage。
  - total mismatch / budget hit 写入 diagnostics。
- filter enumeration proof：
  - 只枚举官方 metadata 暴露的低风险参数。
  - 例如 level、programmeType、studyMode、faculty。
- API 成功时优先写 `programme_catalog`；API 不存在或不完整时 HTML fallback 继续可用。
- Browser fetcher 已把 network JSON/API response URL 单独记录为 `network_response_urls`，
  API discovery 可将其纳入 safe capture。
- `catalog_api_body_profile()` 已完成首版：用 JSON body 的 programme-like object、
  pagination total/count、filter metadata 和 sample keys 判断是否像 catalog API。
- Safe capture 已先用 body profile 过滤非 catalog JSON；body detector 只决定 candidate，
  事实写入仍由 `extract_programme_catalog_api()` 完成。
- Dynamic shell source 已能写入 `catalog_source_status=dynamic_shell_no_rows`，并把 next action
  指向 `capture_browser_network_api`。
- 当 dynamic shell 且 API candidate 为 0 时，pipeline 会对该页面执行一次受限 browser
  second-pass capture；该 pass 只用于捕获公开 network JSON diagnostics，不绕过权限。
- Browser fetcher 已记录 HAR-like network response metadata：
  - URL。
  - method。
  - status。
  - content type。
  - response size。
  - query 参数摘要。
  - 安全 response headers。
  - body hash / truncated 状态。
- Safe capture 可直接使用 browser network 已捕获的公开 GET JSON body，不再必须二次 replay。
- POST、auth/token query、off-domain browser network response 只进入 rejected diagnostics，不写 facts。
- `programme_catalog_summary` 已加入：
  - `api_endpoint_candidate_count`
  - `browser_network_candidate_count`
  - `network_body_available_count`
  - `api_candidate_zero_reason`
  - `catalog_source_family_counts`
  - `accepted_source_family_counts`
  - `source_family_bias`
  - `false_positive_rejected_count`

仍保留风险：

- NTU live 已验证 browser second-pass 能打开目录页，但没有捕获到 JSON/API network response；
  后续需要从 JS/static assets、站点搜索接口、Sitecore/Next data 或页面参数继续发现公开数据源。
- `run.config` 只保留 network body summary/hash；如果启用 `source_output_dir`，已接受的官方 JSON
  body 会作为 captured source artifact 保存以支持证据追溯。
- 如果 Playwright 运行环境缺浏览器、页面被 WAF/challenge 拦截，仍不会绕过限制。
- `false_positive_rejected_count` 目前是稳定 summary 字段，但 rejected-row 级别细账仍不足。
- GraphQL、Algolia、Sitecore、Next.js data、ElasticSearch 等 adapter 尚未实现。

### 5. LLM / OpenAI guarded 能力

已完成：

- OpenAI 本地配置、`.env.example`、secret 忽略与安全测试。
- live scan 默认可启用 LLM-assisted crawling；`--no-llm` / `--deterministic-only` 可关闭。
- guarded source planning。
- classification assist diagnostics。
- programme catalog hint。
- structured extraction fallback。
- LLM candidate 必须通过 captured source text、snippet、claim path 验证后才能写入 facts。

边界：

- 模型可以提出 source/candidate/mapping/pagination/filter 建议。
- 模型不能编造专业、费用、要求等事实。
- 运行时不能用模型为每条 row 生成招生事实。

### 6. 当前验证状态

当前工作区最新验证：

```bash
.venv314/bin/python -m pytest -q
# 227 passed

git diff --check
# passed
```

本文件只记录当前状态。旧的 `126 passed`、`153 passed`、`176 passed` 等历史测试数不再作为当前
进度依据。

## 未完成计划

### P0：Dynamic Shell Browser/Network Capture

状态：browser/network 首版完成；static JS asset endpoint discovery 首版完成；live NTU 已做最小页
rerun，结果是页面源码暴露 suggestions API hint，但没有拿到完整 catalog JSON。

已完成：

- Programme-list 动态筛选壳可被标记为 `catalog_source_status=dynamic_shell_no_rows`。
- Dynamic shell + API 0 的 report next action 已改为 `capture_browser_network_api`。
- Playwright browser fetcher 已把 network JSON/API response URL 写入 `network_response_urls`。
- Playwright browser fetcher 已把 network JSON/API response metadata 写入 `network_responses`：
  method、status、content type、response size、query 参数摘要、安全 response headers、body hash
  和 truncated 状态。
- API discovery 已能从 `network_response_urls` 生成 candidate，并交给 safe capture。
- API discovery 已能从 `network_responses` 生成 candidate，并把 network metadata 写入 diagnostics。
- Safe capture 已能直接消费 browser network 捕获到的公开 GET JSON body；`run.config` 只写 summary/hash，
  不写原始 body。
- POST、auth/token query、off-domain network response 会被标记为 rejected candidate，不 replay，
  不写 facts。
- Pipeline 已新增 dynamic shell + API 0 的自动 browser second-pass capture。
- Pipeline 已新增 dynamic shell + API 0 的同源静态 JS asset discovery：
  - 最多取样 3 个动态壳 source pages。
  - 最多抓取 8 个同源 `.js` / `.mjs` asset。
  - 单个 asset 上限 1MB。
  - asset 只参与 API endpoint hint discovery，不进入 admissions source processing，
    不直接写 facts。
- API endpoint hint 识别已覆盖 `.json`、`/api/`、`/_next/data/`、GraphQL、OData、
  Sitecore、search、listing 等公开目录接口形态；仍需 URL 同时具备 programme/course/degree
  等 catalog signal。
- 报告新增 `programme_catalog_static_asset_discovery`：
  - candidate source pages。
  - candidate/fetched static assets。
  - asset 中发现的 API endpoint hints。
  - rejected static assets。
- 如果抓到静态 asset 但没有 endpoint hint，summary 使用
  `api_candidate_zero_reason=static_asset_no_endpoint_hints`，next action 指向
  `discover_public_catalog_api`。
- `outputs/ntu-api-live-current` 已证明：
  - browser second-pass attempted 1。
  - captured pages 1。
  - network responses 0。
  - network bodies 0。
  - next action `discover_public_catalog_api`。
- `outputs/ntu-api-live-static-assets` 已证明：
  - 普通 `/search-results?q={{...}}` 模板已不再污染 API candidates。
  - 当前只剩 1 个 suggestions API candidate。
  - safe capture 未拿到 JSON catalog。
  - next action `discover_public_catalog_api`。

仍未完成：

- 尚未找到 NTU 页面背后的公开 catalog JSON/API。
- 尚未在 NTU 上发现真正返回专业目录 rows 的 Sitecore/search/listing/Next data endpoint。
- 尚未验证 NTU 是否需要更专门的 Sitecore、Next.js data、search endpoint adapter 才能拿到完整目录。
- 尚未在 NTU 上跑通 dynamic shell -> browser/network body -> API extractor -> CSV 的完整闭环。

问题：

- NTU `/admissions/undergraduate-programmes` 被抓到的是筛选器壳。
- `api_catalog_candidate_count=0` 时，safe JSON capture 没有入口。
- 当前报告应优先指向 browser/network 或 static asset/public API acquisition，而不是先继续堆
  line-based HTML parser。

修改范围：

- 在 source diagnostics 中稳定识别 dynamic shell：
  - 有 programme/filter 信号。
  - 有 `Programme Level`、`Programme Type`、`Full-time`、`Part-time` 等筛选器。
  - 没有实际 rows。
- 当 dynamic shell 且 API candidate 为 0 时，触发受限 browser/network capture。
- 只记录公开 GET JSON：
  - URL。
  - method。
  - content type。
  - response size。
  - query 参数摘要。
  - body 摘要或 capture key。
- 不保存 cookie/auth header。
- 不 replay POST。
- 不绕过登录、验证码、WAF、签名或权限接口。
- 静态 asset discovery 只抓同源 JS asset，不保存 cookie/auth header，不把 JS asset 当作招生事实来源。

验收：

- NTU-like dynamic shell fixture 触发 `capture_browser_network_api`。
- browser/network 中发现的公开 JSON response 能进入 API candidate diagnostics。
- browser/network 已捕获的公开 GET JSON body 可直接进入 `programme_catalog`，不需要二次 refetch。
- 没有 JSON response 时只更新 diagnostics，不写 facts。
- POST/auth/off-domain network response 只产生 rejected candidate。
- report 中 dynamic shell + API 0 的 next action 是 `capture_browser_network_api`，
  不是单纯 `improve_table_segmentation`。

测试：

- `tests/test_api_catalog_discovery.py`
- `tests/test_report_cli.py`
- fixture 覆盖：
  - filter shell。
  - network JSON。
  - no network JSON。
  - POST/auth/off-domain rejected。

风险控制：

- 默认 bounded。
- 只对 catalog-like shell 触发。
- 所有 rejected candidate 必须有 reason。

### P0：Response-Body Catalog Detector

状态：首版完成。

已完成：

- `catalog_api_body_profile()` 已能输出：
  - `api_body_likely_catalog`
  - `api_body_signals`
  - `api_body_candidate_object_count`
  - `api_body_parseable_row_count`
  - `api_body_filter_keys`
  - `api_body_sample_keys`
  - `api_body_rejection_reason`
- URL 不含 `programme` / `catalog` 但 body 像专业目录的 browser-network JSON，可进入
  candidate diagnostics 并写入 `programme_catalog`。
- body 只是导航/页面配置时会被 `rejected_body_not_catalog` 拒绝。

仍未完成：

- body detector 尚未形成可插拔 adapter；复杂 GraphQL/Algolia/Sitecore/Next.js/ElasticSearch
  仍在 P2。
- report 只展示 API discovery 基础字段，尚未完整展示 body sample keys/signals。

问题：

- 当前 API discovery 更容易发现 URL 中带 `.json`、`/api/`、`programme`、`catalog`、
  `search` 的 endpoint。
- 真实前端接口可能 URL 名称不明显，但 JSON body 明显是 programme catalog。

修改范围：

- 对 browser/network JSON response 增加 body-level 判断：
  - programme-like object list。
  - name/title/degree/award/faculty/school/duration/mode/detail URL。
  - pagination metadata：total/count/pageInfo/hasNextPage/next。
  - filter metadata：level/programmeType/studyMode/faculty/school。
- 输出 body detector diagnostics：
  - accepted body signal。
  - rejected reason。
  - candidate object count。
  - sample keys。
- 将 body detector 接入 safe capture 和 API extractor。

验收：

- URL 不含 `programme` / `catalog`，但 body 像专业目录的 JSON 能进入 candidate diagnostics。
- URL 像 API 但 body 只是导航、筛选器、页面配置时被 rejected。
- body detector 不能直接写 facts；facts 仍由 `extract_programme_catalog_api()` 从 JSON object 写入。

测试：

- `tests/test_api_catalog_discovery.py`
- `tests/test_programme_catalog_api.py`

风险控制：

- body detector 只决定 candidate，不生成 row。
- 大 response 仍受 size limit 保护。

### P1：HTML False-Positive Cleanup

状态：首版完成。

已完成：

- HTML/static parser 已加入课程表上下文拒绝：
  `Course Code`、`Course Title`、`AU`、`Pre-req`、`Open to`、`Major PE Courses`。
- 新增回归测试证明 `BEng SCE`、`BEng Design Stream` 不再从 course table `Open to`
  列进入 `programme_catalog.csv`。

仍未完成：

- rejected row 还没有完整进入稳定 diagnostics 计数，例如 `false_positive_rejected_count`。
- second-major 说明、长正文和更多未知表格变体仍需继续收紧。

问题：

- `outputs/ntu-api-live/programme_catalog.csv` 出现 `BEng SCE`、`BEng Design Stream`。
- 这些值来自 ADM course table 的 `Open to` 列，不是专业目录 row。

修改范围：

- 在 HTML/static parser 中加入 course-table rejection：
  - `Course Code`
  - `Course Title`
  - `AU`
  - `Pre-req`
  - `Open to`
  - `Major PE Courses`
  - course list / curriculum table。
- 对 row name 加强 gate：
  - 长度。
  - 标点密度。
  - 句子数量。
  - course-code density。
  - table-cell role。
- rejected row 进入 diagnostics，不静默消失。

验收：

- `BEng SCE`、`BEng Design Stream` 不再进入 `programme_catalog.csv`。
- 课程表、课程列表、second-major 课程说明不写为 `degree_programme`。
- 专业目录表格仍能抽出正常 Bachelor rows。

测试：

- `tests/test_programme_catalog.py`
- `tests/test_report_cli.py`

风险控制：

- 不用学校名硬编码。
- 以 row context 和 table header 判断。
- 对不确定 row 标为 rejected/manual-review，而不是硬写入 CSV。

### P1：NTU/HASS Segment Fallback

问题：

- API 不可用时，NTU/HASS 学院页可能以段落或分组方式展示：
  `School -> Bachelor -> Majors`。
- 当前 parser 容易把长段拼成一条 row，或只抽到 ADM/BFA 页面。

修改范围：

- 增加段落式目录 fallback：
  - 识别 school/faculty heading。
  - 识别 Bachelor/BA/BSc/BSocSci/BEng 等 degree heading。
  - 将 majors / specialisations 写入 `specialisations_or_majors`，不拼进 `name`。
- 补 source context hint：
  - URL path。
  - page title。
  - heading hierarchy。

验收：

- HASS-like fixture 能拆出多条 degree rows。
- majors 进入 `specialisations_or_majors`。
- `faculty_or_school` 不再大量 unknown。
- 长篇 overview 不进入 CSV。

测试：

- `tests/test_programme_catalog.py`
- `tests/test_programme_catalog_output.py`

风险控制：

- 只在 API 不存在、不完整或受限时作为 fallback。
- 不把普通介绍页当全校完整目录。

### P1：Completeness Diagnostics 分层

状态：首版完成，rejected-row 细账仍需后续补强。

已完成：

- Dynamic shell + API 0 已指向 `capture_browser_network_api`。
- `api_candidate_zero_reason` 已进入 `programme_catalog_summary`。
- Static asset discovery 无 endpoint hint 时，`api_candidate_zero_reason` 已能写成
  `static_asset_no_endpoint_hints`，`recommended_next_action=discover_public_catalog_api`。
- `catalog_source_family_counts` / `accepted_source_family_counts` 已进入 summary 和 report。
- ADM/BFA 这类单一 accepted source-family 主导可标记 `source_family_bias`。
- `false_positive_rejected_count` 已成为稳定 summary/report 字段。
- next action 已能区分：
  - `capture_browser_network_api`
  - `discover_public_catalog_api`
  - `inspect_api_response_body`
  - `tighten_catalog_false_positive_filters`
  - `review_source_family_bias`

仍未完成：

- `false_positive_rejected_count` 还不是完整 rejected row ledger；需要 extractor 把 course table、
  second-major、长正文等 reject reason 稳定记录下来。
- `dynamic_shell_source_count` 目前可从 `source_status_counts.dynamic_shell_no_rows` 推导，
  尚未单独作为顶层字段。
- `fallback_html_parser` 分支尚未和 NTU/HASS fallback 打通。

剩余问题：

- `recommended_next_action` 已比之前更细，但 rejected-row ledger 和 NTU/HASS fallback 尚未打通。
- NTU 这类情况需要明确区分：
  - source acquisition 未闭环。
  - browser/network API 未触发。
  - parser segmentation 不够。
  - HTML false positive 污染。
  - 单一 source family 主导。

修改范围：

- 新增或补齐 metrics：
  - `dynamic_shell_source_count`
  - `browser_network_candidate_count`
  - `api_candidate_zero_reason`
  - `catalog_source_family_counts`
  - `accepted_source_family_counts`
  - `false_positive_rejected_count`
- 扩展 next action：
  - `capture_browser_network_api`
  - `inspect_api_response_body`
  - `tighten_catalog_false_positive_filters`
  - `discover_public_catalog_api`
  - `static_asset_no_endpoint_hints`
  - `fallback_html_parser`
  - `manual_review_raw_rows`

验收：

- dynamic shell + API 0 -> `capture_browser_network_api`。
- dynamic shell + 同源 JS asset endpoint hint -> safe capture official JSON -> `programme_catalog`。
- dynamic shell + 同源 JS asset 但无 endpoint hint -> `discover_public_catalog_api`。
- JSON response 存在但 body 未分类 -> `inspect_api_response_body`。
- course table false positive 被拦截 -> `tighten_catalog_false_positive_filters`。
- ADM/BFA 单一子树主导 -> report 明确提示 source-family bias。

测试：

- `tests/test_programme_catalog.py`
- `tests/test_report_cli.py`
- `tests/test_pipeline.py`

风险控制：

- diagnostics 只解释，不改 facts。
- next action 可以多值或优先级化，但必须保持 report 可读。

### P2：API Adapter Layer

问题：

- 通用 JSON mapping 不一定覆盖 GraphQL、Algolia、Sitecore、Next.js data、ElasticSearch。

修改范围：

- 增加 adapter registry。
- adapter 只解析官方响应结构，不生成事实。
- adapter 输出统一 `ProgrammeCatalogRecord` candidate。
- 记录 `api_adapter_used`。

验收：

- 没有 adapter 时通用 extractor 继续工作。
- adapter 命中时 diagnostics 可追踪。
- adapter 不绕过 safe capture 边界。

测试：

- `tests/test_programme_catalog_api.py`
- 新增 adapter fixture tests。

风险控制：

- 只为高价值、可复现结构加 adapter。
- 不做未知参数 fuzz。

### P2：输出契约与兼容层治理

问题：

- 历史上 result JSON、Markdown report、CSV、docs 和 tests 容易漂移。
- 债务 3 还没有单独执行代码治理。

修改范围：

- 盘点稳定字段：
  - `result.json`
  - `report.md`
  - `programme_catalog.csv`
  - diagnostics keys。
- 为 compatibility alias 明确生命周期。
- 为新增 diagnostics 字段补 report/tests。
- 文档只描述当前实现，不继续堆旧 phase 历史。

验收：

- schema 变动有 focused tests。
- report、CSV、result JSON 同步。
- 不再用旧 outputs 当当前行为证明；旧 outputs 只能当 regression signal。

测试：

- `tests/test_programme_catalog_output.py`
- `tests/test_report_cli.py`
- `tests/test_schema_evidence.py`
- `tests/test_compatibility_boundaries.py`

风险控制：

- 不删除兼容字段，除非先有迁移说明和测试。
- docs 更新与代码变更同一 slice 完成。

## 下一步推荐执行顺序

1. 针对 NTU 执行 `discover_public_catalog_api`：从 JS/static assets、Sitecore/search endpoint、
   sitemap/source links 中找公开 catalog 数据源。
2. 继续 P1 HTML False-Positive Cleanup：覆盖 second-major 说明、长正文和更多课程表变体，并把
   rejected-row reason 写入 diagnostics。
3. 实现 P1 NTU/HASS Segment Fallback。
4. 如 NTU 公开数据源属于 Sitecore/Next.js/搜索接口，实现对应 P2 adapter。
5. 执行 P2 输出契约与兼容层治理。

每个 slice 的交付要求：

- 修改前先加或更新 fixture。
- 自己跑 focused tests。
- focused tests 通过后跑完整 `pytest -q`。
- 跑 `git diff --check`。
- 汇报：
  - 改动。
  - 结果。
  - 风险。
  - 未覆盖项。

## 测试入口

常用完整验证：

```bash
.venv314/bin/python -m pytest -q
git diff --check
```

P0/P1 focused tests：

```bash
.venv314/bin/python -m pytest -q \
  tests/test_api_catalog_discovery.py \
  tests/test_programme_catalog_api.py \
  tests/test_api_catalog_pagination.py \
  tests/test_api_catalog_filters.py \
  tests/test_programme_catalog.py \
  tests/test_report_cli.py
```

fixture smoke：

```bash
.venv314/bin/python -m university_admissions_crawler.cli \
  tests/fixtures/mini_university_site \
  --fixture \
  --output-dir /tmp/uac-smoke \
  --max-pages 20 \
  --max-depth 3
```

## 模型边界

模型可以做：

- 从 HTML、JS、network log、HAR、JSON sample 中提出 API candidate。
- 判断 response 是否像 programme catalog。
- 推断分页模式。
- 推断筛选参数。
- 提供字段映射建议。

模型不能做：

- 编造接口 URL。
- 绕过登录、验证码、token、签名、WAF 或权限接口。
- 在没有 captured official source 的情况下写入 `programme_catalog`。
- 根据页面标题或常识生成专业列表。
- 在运行时为每条 row 生成招生事实。
- 不做 total/count/page/filter 校验就声称“已完整”。

正确边界：

```text
模型提出候选接口和解析策略
代码按规则抓取和验证
只有真实抓到的官方 JSON/HTML/PDF evidence 才能写 facts
```
