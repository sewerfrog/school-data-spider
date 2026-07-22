# 官网主页自动招生爬取：当前基线与专业目录修复计划

## 文档用途

本文保留三类内容：

- 当前仍有效的工程基线。
- 已执行修改计划的当前验收结论。
- 仍有效的风险边界和后续候选工作。

已经完成的 Phase、Step、Structured Output 分批交付和历史复盘不再逐项展开。旧输出只能用于定位
回归，不能用于证明当前行为正确。

计划快照日期：2026-07-22。

## 已完成基线

以下能力视为后续修改必须保留的基线，不再拆成历史步骤：

- homepage-first discovery、sitemap、bounded frontier、common path probing。
- live HTTP、可选 Playwright fallback、fixture scan 和可选 PDF parsing。
- official-domain policy、redirect/domain guard、Public Suffix List 域名判断。
- source artifact、evidence、claim path validation、missing reasons 和 template completeness。
- `ProgrammeCatalogRecord`、`AdmissionsData.programme_catalog`、root CSV 和 row-level evidence。
- programme catalog 的 API discovery、safe capture、pagination、filter enumeration 和 diagnostics。
- HTML candidate ledger，以及课程表、长正文、admissions/second-major explainer 的部分拒绝规则。
- reordered/partial table headers、grouped rows、section context 和字段级 evidence。
- guarded LLM source planning、classification assist、catalog hint 和 structured extraction fallback。
- additive `structured-output-v1`、record JSONL、证据表、missing 表、diagnostics 和 batch 合并输出。

这些能力不是本计划的重做对象。后续改动必须保持旧输出文件存在，并保持“没有 captured official
evidence 就不能写 facts”的边界。

## 当前问题

### 1. NTU 输出现状

本计划以 `outputs/ntu-live-20260717` 的实际结果作为故障样本：

- 捕获 105 个 source。
- 71 个 source 被视为 programme catalog candidate。
- 写入 28 条 `programme_catalog`。
- 其中 14 条 `name` 超过 160 个字符。
- 22 条记录带 manual-review 类质量警告。
- API response 和 API accepted row 都是 0，全部事实来自 HTML fallback。
- 5 个 LLM structured candidates 全部被拒绝，没有写入 facts。
- NTU 官方 `https://www.ntu.edu.sg/education/degree-programmes` 权威总目录没有被捕获。

当前错误不是 source 伪造，而是字段边界错误。典型污染包括：

- 整页 HASS 介绍被写成一个 programme name。
- CCDS 页面中的 CSS 和页面配置文本被写成 programme name。
- `Care, Serve, Learn` 课程行被写成学位专业。
- `Related Programmes` 中的链接文字被归到当前详情页。
- Chinese、Philosophy 等详情页中的相关专业被错误归属。
- NTU 记录出现 `NUS Business School` 等跨学校 faculty hint。

### 2. 已确认的原因链

1. `crawler/html_text.py::_html_to_text()` 把所有空白压成单个空格，HTML block boundary 丢失。
2. `extractor/programme_catalog.py` 后续仍按换行、HTML block 和 `|` 判断段落与表格，上下游契约冲突。
3. 页面标题自带的 `|` 会让整页单行文本进入 table parser。
4. table parser 缺少可靠的 block provenance、名称长度和 sentence/CSS 校验。
5. `parsed` 只表示字段存在，不表示候选在语义上是 programme entity。
6. crawler 对 detail、minor、old cohort 和 curriculum 页打分过高，却没有优先拿到 canonical catalog。
7. generic parser 中仍有 NUS 专用 faculty/name 规则，且没有按学校域名隔离。
8. NTU fixture 是人工整理后的理想文本，没有覆盖 Sitefinity 实际的一行文本、标题 pipe、CSS、
   curriculum table 和 related links。

## 修改目标

### 必须达到

- `programme_catalog` 只包含可由官方页面结构证明的专业实体。
- programme name 不能是正文句子、CSS、课程行、统计数字或整段 related-programme 容器。
- 非 table block 中的字面 `|` 不能触发 table parser。
- detail page 只能确认当前页面主 programme；相关链接只能作为 discovery hint，不能直接归属当前页。
- faculty/school 不能跨学校泄漏，NUS 规则只能在 NUS source 上生效。
- canonical catalog、faculty catalog、detail、minor、curriculum、old cohort 等 source role 可诊断。
- API 不存在或不可访问时，canonical HTML 仍能生成可靠目录。
- ambiguous candidate 留在 diagnostics/quarantine，不进入 accepted facts 和 CSV。
- 完整性必须有 canonical section、row count 或分页证明；不能只因抓到若干详情页就声称完整。
- 保留 legacy `result.json`、`report.md`、root `programme_catalog.csv` 和 `structured/` 输出路径。

### 本计划不做

- 不要求必须找到 NTU 私有或未公开 API。
- 不绕过 token、WAF、验证码、登录、签名或访问控制。
- 不让 LLM 直接生成 programme rows。
- 不重写 admissions、fees、requirements 等其他 extractor。
- 不删除 legacy 输出文件或升级 `structured-output-v1`。
- 不把 live network scan 加入必须离线通过的核心 pytest。
- 不用硬编码的一次性 NTU 专业名单替代结构化提取。

## 目标数据流

后续 programme catalog 链路应调整为：

```text
raw HTML
  -> main/noise filtering
  -> typed content blocks
       heading
       paragraph
       list_item
       table_row(cells)
  -> source role classification
       canonical_catalog
       faculty_catalog
       programme_detail
       minor_or_second_major_catalog
       curriculum_or_old_cohort
       unrelated
  -> block-aware candidates
  -> structural and semantic gates
  -> institution-scoped context
  -> dedupe and completeness proof
  -> accepted programme facts + rejected/quarantined diagnostics
```

现有 plain text/markdown 继续提供给 classifier 和其他 extractor。typed blocks 是 programme catalog 的
内部增量输入，不直接改变外部 schema。

## 分步修改计划

### Step 0：冻结故障样本和验收基准

目的：先把本次真实错误变成离线可复现测试，避免修一个页面、破坏另一个页面。

计划改动：

- 从当前 captured source 中提取最小、可审计 fixture，不提交完整 live output：
  - HASS 整页单行文本和标题 pipe。
  - CCDS CSS/page-header 污染。
  - `Care, Serve, Learn | 3 AU` curriculum row。
  - Chinese/Philosophy detail 页的 `Related Programmes`。
  - old-cohort minor curriculum。
  - canonical `Programme | Degree Title` table。
- 为每个 fixture 建立明确的 positive/negative oracle：
  - 应接受的 programme names。
  - 必须拒绝的 candidate text。
  - 预期 source role、candidate block kind 和 rejection reason。
- 新增“当前错误必须先红”的 regression tests。
- 保留现有 NUS、HKU、PolyU、NTU HASS 和 non-standard table fixtures，作为跨校回归基线。

主要文件：

- `tests/fixtures/saved_sources/ntu/`
- `tests/fixtures/programme_catalog/ntu_live_regressions/`
- `tests/test_programme_catalog.py`
- `tests/test_pipeline.py`

验收：

- 新 fixture 不依赖网络、浏览器或凭据。
- 测试能分别复现整页正文、CSS、课程行、related links 和跨学校 faculty 泄漏。
- 正例覆盖 canonical table、HASS section 和 CCDS programme card/list。

不改：

- 本步骤不修改 parser 行为。
- 不把 2026-07-17 的完整输出目录提交为 fixture。

风险：

- 过度裁剪 fixture 可能丢失真实触发条件。每个 fixture 必须保留触发错误的标题、相邻 heading、
  table/paragraph 边界和必要 URL metadata。

### Step 1：建立 block-preserving HTML 文本契约

目的：解决 HTML normalizer 与 programme parser 的根本契约冲突。

计划改动：

- 在 HTML normalization 层增加内部 typed block 表达，至少包含：
  - `kind`
  - `text`
  - `cells`
  - `heading_level`
  - `section_path`
  - 可选 link metadata
- 只把真实 `<table>/<tr>/<td>/<th>` 转成 `table_row`；普通 heading/paragraph 中的 `|` 保持普通文本。
- 在 strip tags 前保留 `h1-h6`、`p`、`li`、`br`、table row 的 block boundary。
- 继续移除 `script/style/noscript/svg/nav/header/footer/aside`。
- 对 Sitefinity 把 CSS 作为可见正文发布的情况增加 CSS-like block 检测，但只标记/拒绝，不静默修改
  其他正文。
- `FetchResult`、`SourceTextContext` 和 `SourceExtractionContext` 增量携带 content blocks。
- 现有 `markdown/plain text` 保持可用，其他 extractor 暂不切换到 typed blocks。

主要文件：

- `university_admissions_crawler/crawler/html_text.py`
- `university_admissions_crawler/crawler/fetcher.py`
- `university_admissions_crawler/pipeline/scan_context.py`
- 相关 fetcher/html-text tests

验收：

- HASS title 中的 `|` 不产生 table row。
- canonical programme table 保留稳定 row/cell 边界。
- paragraph、list item 和 heading 顺序稳定。
- script/style 内容不进入 blocks。
- 当前 classifier 和非 programme extractors 的 plain-text 输入保持兼容。

不改：

- 不在本步骤判断哪些 block 是专业。
- 不改变 JSON/PDF/API source 的现有解析行为。

风险：

- 直接改变 `_html_to_text()` 输出可能影响所有 extractor。本步骤应采用增量 blocks，并用兼容 plain text
  限制 blast radius。
- HTML regex 对嵌套结构不可靠；若现有实现无法稳定保留边界，应使用标准库 `HTMLParser` 建 block，
  仍不引入强制第三方依赖。

### Step 2：programme parser 改为 block-aware

目的：只有具有真实结构 provenance 的候选才能进入对应 parser 分支。

计划改动：

- `extract_programme_catalog()` 增量接收 typed blocks。
- 只有 `table_row` 可以进入 table parser；删除“任意文本含 `|` 即表格”的主路径。
- heading/list/card-like block 进入 title/list candidate path。
- paragraph 只能进入严格的 sentence candidate path，不能借上下文中的 `Bachelor` 把整段正文作为 name。
- section context 只在明确 heading/block boundary 内继承；遇到新 heading、table、admissions、curriculum、
  contact、related-programmes boundary 时清空。
- legacy fixture 或非 HTML source 没有 blocks 时保留兼容 fallback，但进入更严格门禁并输出
  `legacy_text_fallback` diagnostics。
- candidate diagnostics 增加 `block_kind`、`section_path` 和 `parser_branch`。

主要文件：

- `university_admissions_crawler/extractor/programme_catalog.py`
- `university_admissions_crawler/pipeline/category_extraction.py`
- `tests/test_programme_catalog.py`

验收：

- 整页单行文本不再生成一条超长 programme。
- table header、table row、section heading 和 paragraph 的处理路径可从 diagnostics 追踪。
- HASS section fixture 仍能提取 degree + faculty + majors。
- reordered/grouped/partial-header fixtures 不回归。

不改：

- 不在本步骤调整 crawler frontier 排序。
- 不要求 API catalog 可用。

风险：

- 严格 block provenance 会降低旧站点的召回率。无法确认的候选必须进入 quarantine，而不是重新放宽
  到整页正则扫描。

### Step 3：增加严格的 programme entity 门禁

目的：把“文本中出现 Bachelor”和“这是一个专业实体”分开。

计划改动：

- accepted programme name 必须满足至少一种结构锚点：
  - canonical table 的 programme/degree cell。
  - programme card/list item 的主链接或标题。
  - detail page 的主 `h1`。
  - faculty catalog 中明确 degree heading。
- 增加统一拒绝规则：
  - CSS/JS/template markers。
  - 超过安全上限的 programme name。
  - 明显 sentence-like 的介绍、申请条件和 career prose。
  - course code、AU、curriculum、pre-requisite、BDE/ICC、table total。
  - `Related Programmes`、FAQ、contact、academic integrity、brochure 等容器正文。
  - 只有 degree keyword、没有结构锚点的 paragraph。
- detail page 的 accepted name 必须与 `h1`、page title 或规范化 URL slug 一致。
- related-programme link 只进入 discovery queue；目标页未捕获前不写 programme fact。
- `_is_confident_row()` 增加 structural anchor、source role、name quality 和 institution consistency 条件。
- `parsed` 只用于结构和语义门禁都通过的行。
- ambiguous row 不再以 `raw_needs_manual_review` 混入 accepted catalog；保留到 candidate diagnostics 或
  additive quarantine 输出。

主要文件：

- `university_admissions_crawler/extractor/programme_catalog.py`
- `university_admissions_crawler/pipeline/diagnostics.py`
- `university_admissions_crawler/reports/render_report.py`
- `tests/test_programme_catalog.py`

验收：

- CSS、完整段落、`Care, Serve, Learn`、curriculum totals 和 related container 全部被拒绝。
- rejection reason 具体到 `css_or_template_text`、`course_or_curriculum_row`、
  `related_programme_container`、`sentence_like_name`、`unanchored_degree_mention` 等类别。
- 每条 accepted row 都能说明 source role、block kind 和 anchor。
- 不再出现“26 行 parsed、22 行仍需人工审查”这种状态冲突。

不改：

- 不用 LLM 代替 entity gate。
- 不因名称与已有知识库不一致就自动改写官网名称。

风险：

- 部分合法双学位名称很长，不能只依赖固定长度。长度上限必须与结构锚点、句子特征共同判断，
  超限候选进入 quarantine 供检查。

### Step 4：source role 和 canonical-catalog-first 发现策略（已完成）

已实现：

- `crawler/programme_sources.py` 统一提供 `canonical_catalog`、`faculty_catalog`、
  `programme_detail`、`minor_or_second_major_catalog`、`curriculum_or_old_cohort`、`unrelated`
  六类内部 role；extractor、discovery 和 pipeline 不再各自维护一套判断。
- discovery frontier 按 canonical > faculty > detail > minor > curriculum 排序；普通 admissions source
  保持原 relevance 竞争力，不会因 `unrelated` 标签被全局饿死。
- NTU profile 只在 registrable domain 为 `ntu.edu.sg` 时加入
  `/education/degree-programmes`，候选仍必须通过原有 `DomainPolicy`。
- detail/minor/old-cohort/curriculum 不再仅因 URL 含 `undergraduate-programmes` 被当作目录枚举源；
  当前学年的 NUS bulletin 不会仅因 `AY20xx` 被误判为旧 cohort。
- detail source 不创建独立 catalog row。它只能稳定、唯一匹配已经捕获的 canonical/faculty row，且只补
  `faculty_or_school`、`mode`、`duration_or_units` 的空值；补充值写入
  `programme_catalog_enrichment_evidence` 并单独校验证据来源。
- `programme_source_family_budget` 默认每个 detail/minor/curriculum source family 最多抓取 4 页；
  fetched/skipped 决策写入 `programme_frontier_diagnostics` 和 `programme_frontier_summary`。
- live 默认启用 4 页定向详情 reserve 时，首轮 detail family 使用分层预算：canonical catalog
  直接链接的详情保留 2 页，已发现 faculty catalog 支撑的详情和没有 catalog backing 的详情各 1 页；
  第二轮最多为同 family 使用余下 3 页，两轮合计仍不超过原 family cap 4。
- captured source strategy 记录 role、role signals 和 source family；Markdown report 输出 role-specific counts。
- API candidate discovery 保持可选。JSON 必须真实 captured，且通过 total 或 pagination completeness proof
  才升为 `canonical_catalog`；证明不足时只标为 `faculty_catalog`，不会因 `.json` URL 抢在 HTML canonical 前。

已验证：

- deterministic NTU discovery fixture 在 `max_pages=2` 时先抓 seed，再抓 canonical degree catalog。
- 同一 detail source family 超预算后产生可解释的 skipped 诊断。
- old cohort 不计入 catalog enumeration source；detail 只补稳定匹配行且字段证据通过 schema 校验。
- 完整/不完整 API 分别落入 canonical/faculty role；全量测试和 fixture smoke 通过。

本步未改：

- 未放宽 official-domain policy，也未允许 source planner 越过 safe capture。
- 未做跨来源全局去重、canonical row 冲突决议或 catalog completeness 总证明，这些仍属于 Step 6。
- 未把 NTU profile 规则扩散到通用规则；其他学校的独立 profile 仍属于 Step 5。
- 未用本轮 deterministic fixture 代替 Step 9 的 NTU live 验收。

### Step 5：隔离 institution-specific 规则（已完成）

目的：消除 NUS faculty/name 规则对 NTU、HKU、PolyU 等 source 的污染。

已实现：

- 新增 `extractor/institution_profiles.py`，把 NUS 专用 CHS/FASS/NUS College/SPS/E-Scholars
  name patterns 和 faculty aliases 从 generic parser 移出。
- profile 只由 `is_official=True` 的 source URL registrable domain 选择；当前只有
  `nus.edu.sg -> nus` 和 `ntu.edu.sg -> ntu`。未知域及 non-official source 均记录为
  `institution_profile=generic`。
- NUS profile 处理 NUS Business School、CHS、FASS、NUS College、School of Computing、
  CDE 和 Faculty of Science；NTU profile 处理 Nanyang Business School、CCDS、CoHASS、
  ADM、SoH、SSS 和 WKWSCI。
- generic faculty 只从明确的 section heading/provider phrase、faculty table cell、programme
  card context 或 source title segment 提取；不再扫描正文前 500 字生成全页 faculty hint。
- programme name 或 faculty label 命中其他 institution profile 时，entity gate 拒绝该候选并记录
  `institution_context_mismatch`；外校 faculty section 也不能被后续 programme 继承。
- `nav`、`footer` 等 HTML noise 在 block extraction 前移除；`related` section 继续由 container gate
  拒绝，因此 detail enrichment 不能从这些区域推断 faculty。
- `Scholars Programme` 保留 generic name candidate，因为该名称不属于 NUS 独占；其 category 仍需
  明确结构或受约束的 classification hint，NUS 专属名称不采用此例外。

已验证：

- NUS deterministic source fixture 继续识别原有 NUS 专用 programme 和 faculty。
- NTU source 正文出现 NUS Business School、NUS College、CHS/FASS 时不会写入输出。
- NTU 结构化行或 faculty section 出现 NUS 专属 label 时，以
  `institution_context_mismatch` 拒绝。
- NTU 七组 documented aliases 均在 official `ntu.edu.sg` source 上解析为 canonical faculty label。
- unknown domain 与 non-official NUS source 不启用 profile，仍可保留 generic table 中明确提供的
  faculty 值。
- detail 页的 nav/footer/related NUS 文本不会补写 faculty；generic source title 中明确独立的
  `School of Computing` segment 仍可作为 detail enrichment 证据。

本步未改：

- 未建立包含全世界大学名称的静态知识库；当前 profile 只覆盖已验证的 NUS/NTU 规则。
- 未用模型猜 faculty，也未改变 official-domain policy、source role 或 canonical-first frontier。
- 未处理跨来源去重、来源优先级和 catalog completeness proof；这些仍属于 Step 6。

剩余风险：

- 新学校的缩写不会自动识别，必须先以 deterministic fixture 证明后再加入对应 domain profile。
- 学校改名或合并 faculty 后，旧 alias 只会继续在原 profile 内生效，但 canonical label 需要人工更新。
- 纯文本 fallback 无法恢复 nav/footer DOM provenance，因此它不会把 profile alias 正文当 faculty；代价是
  缺少 heading/table/source-title 证据的 faculty 保持 unknown。

### Step 6：重做去重、来源优先级和完整性证明

目的：输出不仅“没有明显垃圾”，还要能解释覆盖范围和缺失原因。

当前进度：记录身份与来源优先级、完整性 proof evaluator、report/structured diagnostics 可消费输出和
quality-adjusted row-yield 均已完成；deterministic 实现已收口，live-network 边界已由 Step 9
以 fail-closed 方式验收。

- `pipeline/programme_catalog_merge.py` 统一处理 HTML canonical/faculty 和 JSON API
  候选，身份键包含 institution registrable domain、category、normalized name 和
  degree/award。
- canonical 记录优先；faculty 或未证明完整的 API 只补充主记录缺失字段，冲突字段
  保留 canonical 值。如果更高优先级来源后到，则替换主记录的 source provenance，同时保留低优先级
  来源提供的非冲突字段和独立 evidence。
- programme detail 继续只允许补充已有 canonical/faculty row，但匹配已复用同一身份规则。
- 同名但 award 或 category 不同的记录保留；缺少 award 且命中多个兼容记录的候选
  fail closed 到 quarantine，不猜测归属。
- `programme_catalog_row_provenance`、`programme_catalog_merge_diagnostics` 和
  `programme_catalog_enrichment_evidence` 记录主来源、merge/replacement/quarantine 决策以及补充字段证据；
  去重后的 row、warning、candidate diagnostics 和 field evidence claim path 会重排，不留空洞索引。

本部分已验证：

- canonical-first、faculty-first 后 canonical replacement、同名不同 award/category、模糊匹配 quarantine
  和 claim-path rebase 均有 focused tests。
- 管线集成测试证明：未证明完整的 API 不会覆盖 HTML canonical row，只会用自身
  captured evidence 补充缺失字段。

第二部分已完成：

- `pipeline/programme_catalog_completeness.py` 以 fail-closed 规则统一计算
  `complete` / `probable_incomplete`：必须同时存在 accepted canonical row、candidate 守恒、
  candidate-bearing section 守恒、无 quarantine/manual-review/acquisition gap；存在 API 时还要求
  pagination 与 filter enumeration proof 闭合。
- `programme_catalog_summary` 新增 `source_role_counts`、`accepted_by_source_role`、
  `canonical_catalog_captured`、`canonical_catalog_accepted`、candidate/section conservation counts、
  `quarantined_candidate_count`、`catalog_complete`、`catalog_completeness_status`、
  `catalog_completeness_basis`、`catalog_completeness_failure_reasons` 和逐项 checks。
- API aggregate 不再把只提供 filters 且没有 programme candidate/total/pagination 信号的 selector
  response 当成一个未完成 catalog group；selector 仍保留在 response/filter diagnostics。
- `probable_incomplete_catalog` 已收紧：未得到完整 proof 时不再因“暂未发现异常”而返回 false。
- completed/incomplete pagination API、filter API/CDN redirect、canonical HTML、缺 canonical、quarantine 和
  unknown candidate decision 都有 deterministic tests。

第三部分已完成：

- completeness evaluator 将失败 check 统一归类为 `discovery`、`segmentation`、`entity_gate` 或
  `completeness_proof`，并输出稳定排序的 stage list/counts；报告和 structured export 不各自重复推断。
- Markdown report 直接展示 completeness status、canonical captured/accepted、candidate/section
  conservation、source role、basis、failure reasons 和 failure stages。即使尚未发现任何 candidate/source，
  discovery failure 也不会被报告的零计数提前返回隐藏。
- `structured/diagnostics.json` 保留完整 `programme_catalog_summary`，并在顶层追加精简的
  `programme_catalog_completeness` 契约，供下游读取 status、proof、failure 和 next action；candidate ledger
  不复制进该精简对象。
- complete、warning-only entity-gate failure、unknown decision proof failure、缺 canonical、零候选 report 和
  structured complete/incomplete compact contract 均有 deterministic tests。

第四部分已完成：

- 原始 `accepted_row_count` 和 `accepted_to_candidate_source_ratio` 保留，不改变 facts 或旧观测值；新增
  `quality_adjusted_accepted_row_count`、`quality_excluded_accepted_row_count`、
  `quality_exclusion_reason_counts` 和 adjusted ratio。
- accepted candidate 只有通过 claim-path 对账、具有 structural anchor，且没有明确的 name-quality、
  institution-context 或 `accepted_manual_review` 失败时，才进入 quality-adjusted count。
- candidate ledger 通过后还要检查最终 programme row；`parse_status != parsed` 以
  `raw_needs_manual_review` 排除，`NEEDS_MANUAL_CHECK` warning 以
  `needs_manual_check_warning` 排除。raw accepted count 和 programme facts 均不删除。
- `category_inferred` 只用于 category 缺少直接文本证据的情况。名称、award 或显式 type 中与 category
  一致的 Bachelor/学位缩写、major/minor、special programme、double/dual degree 词法证据可以解除该
  warning；多个 Bachelor/学位信号但没有显式 type 时仍需复核，不能直接猜成普通或 dual degree。
  institution profile fallback 和 LLM hint 同样保留 warning。
- `raw_low_row_yield` 保留旧 accepted 数量的判断；`low_row_yield` 改用 adjusted count，因而弱 accepted
  rows 不能再把低产出伪装成正常。该结果继续进入 completeness 的 `row_yield_not_suspicious` check。
- 如果运行中没有 accepted candidate ledger，则 `quality_adjustment_applied=false`，adjusted count 回退为
  原 accepted count，避免旧结果或手工构造数据被无证据地扣成 0。
- Markdown report 和 `structured/diagnostics.json` compact contract 同时展示原始/adjusted count、ratio、
  exclusion reasons 和 yield；root/structured programme records 的行数和字段没有变化。

Live 验收状态：

- 已完成 NTU deterministic live-network 验收；当前不伪造目录完整结论，并对无法由
  captured official evidence 支持的字段保持 `probable_incomplete` / manual review。详细过程与
  最终边界见 Step 9。

本阶段继续不把 programme count 当作完整性常量，也未引入外部依赖。

计划改动：

- [x] 规范化去重 key 至少包含 institution、category、programme name、degree/award。
- [x] canonical catalog row 优先；faculty/detail row 只补充字段，不重复创建 programme。
- [x] 同名但不同 award/category 的记录保留并明确区分。
- [x] completeness 按 source role 和 catalog section 计算：
  - [x] canonical source 是否捕获并产生 accepted row。
  - [x] 已识别的 candidate-bearing section 是否全部处理。
  - [x] candidate ledger 与 accepted/rejected/context/quarantined 是否守恒。
  - [x] API total/page/filter proof 是否存在。
- [x] 只有存在可解释 proof 时才设置 catalog complete；否则保持 probable incomplete。
- [x] `programme_catalog_summary` 增加：
  - [x] `source_role_counts`
  - [x] `accepted_by_source_role`
  - [x] `candidate_block_kind_counts`
  - [x] `quarantined_candidate_count`
  - [x] `canonical_catalog_captured`
  - [x] `catalog_completeness_basis`
  - [x] `institution_context_mismatch_count`
- [x] 修正“accepted garbage 导致 low row yield 看似正常”的诊断失真。

主要文件：

- `university_admissions_crawler/pipeline/programme_catalog_merge.py`
- `university_admissions_crawler/pipeline/programme_catalog_completeness.py`
- `university_admissions_crawler/pipeline/category_extraction.py`
- `university_admissions_crawler/pipeline/api_catalog_capture.py`
- `university_admissions_crawler/pipeline/diagnostics.py`
- `university_admissions_crawler/reports/render_report.py`
- `university_admissions_crawler/reports/structured_export.py`
- `tests/test_programme_catalog_merge.py`
- `tests/test_programme_catalog_completeness.py`
- diagnostics/report/structured-output tests

验收：

- [x] candidate 总数可以解释为 accepted + rejected + context + quarantined。
- [x] canonical catalog 未抓到或没有 accepted row 时不会报告 complete。
- [x] report 能直接说明是 discovery、segmentation、entity gate 还是 completeness proof 失败。
- [x] diagnostics 新字段是 additive，不破坏旧消费者。
- [x] raw/quality-adjusted accepted count 可以解释 low-row-yield 差异，且不改写 programme facts。

不改：

- diagnostics 不写入 admissions facts。
- 不把 programme count 当作跨学年永久常量。

风险：

- 诊断字段继续堆入 `run.config` 会扩大快照。只加入本计划验收需要的聚合字段，逐候选明细继续放
  candidate ledger/structured diagnostics，不复制到多个位置。
- quality adjustment 依赖 accepted ledger 的 claim path 和 structural anchor；没有 ledger 时显式回退原始
  count，不把“无法评估”误报成“全部低质量”。

### Step 7：输出语义和兼容性收口

目的：保证修复后的 CSV/JSONL 是清洗可用事实，而不是候选暂存区。

计划改动：

- root `programme_catalog.csv` 和 structured programme records 只渲染 accepted programme facts。
- rejected/quarantined candidates 只进入 diagnostics；若需要落盘，使用 additive、明确命名的
  quarantine JSONL，不混入 facts。
- 保留 stable source/evidence refs 和 claim paths。
- 记录本次语义收紧：同一 source 下 programme row 数可能下降，这是 false-positive removal，
  不是兼容输出文件缺失。
- README、PROJECT_MAP、VERSION_NOTES 只在实现完成并通过验收后同步，不在计划阶段提前宣称完成。

主要文件：

- `university_admissions_crawler/reports/programme_catalog_csv.py`
- `university_admissions_crawler/reports/structured_export.py`
- `university_admissions_crawler/pipeline/output_writer.py`
- output compatibility tests

验收：

- legacy 文件名和 structured 路径保持不变。
- CSV/JSONL 中不存在 raw rejected/quarantined candidates。
- accepted row 的 source/evidence join 全部有效。
- 空 catalog 时仍按既有契约处理，不生成伪造 placeholder row。

不改：

- 不升级 schema version。
- 不删除或重命名现有输出字段。

风险：

- 下游可能曾错误依赖 `raw_needs_manual_review` 行。实现前应在 VERSION_NOTES 中把该语义变化标为
  quality tightening，并用 fixture 展示迁移结果。

### Step 8：离线回归、跨校验证和性能检查

目的：证明修复不是 NTU 单点特判，也没有破坏已有学校。

验证顺序：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_programme_catalog.py

PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_pipeline.py \
  tests/test_programme_catalog.py \
  tests/test_report_cli.py \
  tests/test_structured_output.py

PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider

PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m compileall \
  university_admissions_crawler tests

git diff --check
```

覆盖矩阵：

| 场景 | 预期 |
|---|---|
| NTU canonical table | 按 row/cell 提取 programme + degree |
| NTU HASS section | 提取 degree、faculty、majors |
| NTU CCDS page with CSS | CSS 全拒绝，programme cards 可提取 |
| NTU curriculum | course/AU/ICC/CSL 不进入 catalog |
| NTU detail related links | 只作为 discovery hint |
| NTU old cohort minor page | 不生成 degree row |
| NUS catalog | NUS profile 正常，规则不泄漏 |
| HKU/PolyU table/card | 现有结果不回归 |
| grouped/reordered/partial table | 现有 table-shape 能力不回归 |
| fixture smoke | legacy 和 structured outputs 都生成 |

性能边界：

- HTML block extraction 必须是页面大小的线性处理。
- 每页 block/candidate 数设置诊断上限，超过上限 fail closed 到 warning。
- 不为每个 block 调模型。
- 不因 source role 增加无界 frontier。

### Step 9：NTU live deterministic 验收（已按 fail-closed 边界完成）

目的：用当前官网验证离线 fixture 之外的真实效果，且把 LLM 变量排除。

建议命令：

```bash
.venv314/bin/python -m university_admissions_crawler.cli \
  https://www.ntu.edu.sg/admissions/undergraduate \
  --output-dir outputs/ntu-deterministic-20260721-step9-table-scope \
  --deterministic-only \
  --max-pages 120 \
  --max-depth 4
```

若 HTTP source 是 dynamic shell，再单独运行 browser-enabled deterministic 对照；browser 只改变 source
capture，不改变 programme entity gate。

live 验收标准：

- captured source 包含 NTU canonical degree catalog，或 diagnostics 明确说明未捕获原因。
- programme name 中 CSS、模板代码、长正文、课程行和整段 related container 为 0。
- `NUS Business School` 等跨学校 faculty 泄漏为 0。
- `Care, Serve, Learn` 不作为 degree programme。
- detail 页 programme name 与主 heading/title/slug 一致。
- 每条 accepted row 有 official source、evidence 和 structural anchor。
- duplicate 只能由不同 category/award 解释。
- canonical section 的 discovered/accepted/rejected/quarantined 数量可对账。
- API row 可以是 0；只要 canonical HTML 有完整性证明，API 不是失败条件。
- 无完整性证明时必须保持 `probable_incomplete=true`。

2026-07-21 验证状态：

- 首次输出 `outputs/ntu-deterministic-20260721-step6` 捕获了 canonical
  `/education/degree-programmes`，但页面分类被通用 `/education` context gate 错误降为 `irrelevant`。
- 页面分类现复用 `canonical_catalog` source role；输出
  `outputs/ntu-deterministic-20260721-step6-canonical` 中 canonical 页面已正确分类为 `programme_list`。
- canonical parser 现把 `Second Major/Minor | School offering... | Offered to students...` 识别为
  非目录 eligibility table scope。`outputs/ntu-deterministic-20260721-step9-table-scope` 中该 scope 的
  86 个 candidates 全部以 `minor_or_second_major_eligibility_table` 拒绝；canonical accepted rows 从
  68 降为 67，唯一移除项是误报 `All except: NIE ...`，没有新增或误删其他 canonical 名称。
- candidate conservation 和 canonical section conservation 均可对账；focused programme/NTU regressions
  为 `62 passed`。
- 本轮未启动 browser 对照：canonical source 是含 typed table rows 的静态 HTML，不是 dynamic shell；
  browser 不能解决本轮暴露的 entity/segmentation 问题。
- CCDS 静态页为 HTTP 200，但可见 Sitefinity 结构在现有 HTML parser 中产生 0 个 typed
  block；同页官方 JSON-LD 以 `ItemList` / `Course` 提供了名称和主链接边界。当可见
  typed blocks 为空时，HTML normalization 现以最多 500 个 `Course` 生成 `card`
  blocks；`Course.name` 还必须出现在可见归一化文本中，保证保存的 source text 可复核。
  已有 heading/table/list blocks 时不混入 JSON-LD，避免重复候选。
- legacy text parser 现显式拒绝“分类标签 + Bachelor 名称 + 摘要”的无边界行，因此
  JSON-LD 损坏或缺失时也不会回退为 `Computing` / `Business` programme name。对与
  主链接或卡片标题完全一致的名称，14--28 词的长标题可通过；句号和 `provides
  students` 等叙述标记仍拒绝。
- `outputs/ntu-deterministic-20260721-step9-card-boundary` 中 programme catalog 从 112 行变为
  117 行；canonical 保持 67 行，CCDS 来源从 9 个错误边界行变为 15 个精确
  Bachelor 名称，CCDS 来源中精确 `Computing` / `Business` 名称为 0；这 15 行全部
  以 `programme_primary_link` 作为 structural anchor。5 个不以 Bachelor 开头的
  `Double Degree ...` cards 仍由既有保守语法拒绝，本轮未扩大 category grammar。
- quality-adjusted ledger 已修复并以
  `outputs/ntu-deterministic-20260721-step9-quality-ledger-live` 重跑同一 live 矩阵。facts 仍为
  117 rows；adjusted count 从错误的 117 变为 0，117 rows 全部以
  `needs_manual_check_warning` 排除。raw yield 保持正常，adjusted yield 为低产出，建议行动从被
  segmentation 掩盖的建议修正为 `review_catalog_warnings`。
- `category_inferred` 已按直接文本证据校准，并以
  `outputs/ntu-deterministic-20260721-step9-category-evidence-conservative-live` 重跑。facts 和 programme
  `(name, award, category, source_url)` 四元组仍与上一轮 117 rows 完全一致；category warning 从 117
  降为 10，quality-adjusted accepted 从 0 恢复为 34，raw/adjusted yield 均不再异常。保留的 10 rows
  含多个 Bachelor/award 信号但没有显式 type，涵盖 dual、alternative award 和联合学位等混合语义；
  profile fallback 和 LLM hint 的 warning 也有 deterministic tests。
- 当前共有 83 个 `missing_faculty` 和 10 个 `category_inferred` warning records；后者全部与前者重叠，
  因此 manual-review rows 和 adjusted excluded 都是 83，而不是 93。建议行动仍为
  `review_catalog_warnings`；canonical captured、canonical accepted、candidate conservation 和 section
  conservation 仍全部成立。
- `missing_faculty` 第一轮以
  `outputs/ntu-deterministic-20260721-step9-faculty-evidence-provenance-live` 验证。学院 profile alias 现只接受官方
  source title，不再从 URL path 推断，并为 title 派生的 `faculty_or_school` 单独生成字段证据。跨来源 merge
  只把 `(Hons)/(Honours)` 和 `&/and` 作为 award identity 的展示等价，不改写输出值；11 个重复展示行被
  合并，其中 9 个 canonical rows 从 faculty catalog 获得学院和 enrichment evidence。facts 从 117 降为
  106，`missing_faculty` 从 83 降为 73；sources 保持 106，canonical accepted 保持 67，raw/adjusted yield
  均未触发低产出。
- `Communication Studies` 和 `Economics and Data Science` 各有两个官方来源给出不同学院归属。merge 仍
  保留高优先级 canonical row 的已有值，但现在发出 `conflicting_faculty_or_school` 人工复核 warning，
  不再静默忽略；因此 manual-review rows 为 75，quality-adjusted accepted 为 31。10 个
  `category_inferred` 仍全部与其他 warning 重叠，总 warning records 为 85。
- 详情页补充第二轮以
  `outputs/ntu-deterministic-20260721-step10-detail-enrichment-live` 验证。catalog parser 现保存与专业名称
  完全一致的主链接到 row provenance；抓取发生 redirect 时同时保留 requested URL。显式详情页即使被页面
  classifier 归为 `undergraduate_admissions`，也会进入独立的 detail enrichment 路径；普通
  `student-activities`、`student-achievements` 等 programme 子页面不会进入。详情正文没有 H1 时，只允许
  页面主标题生成 `detail_source_identity` candidate，且 detail 仍不能创建新 catalog row。
- 本轮用唯一主链接或保守的 detail-title identity 补全了 `Robotics` 和 4 个 HASS double-major rows 的
  `faculty_or_school`；字段证据均指向对应官方详情页标题，已解决的 `missing_faculty` row warning 被删除。
  sources 和 facts 均保持 106，programme name 集合零新增、零删除，evidence 从 234 增至 239，
  `missing_faculty` 从 73 降为 68，catalog warning records 从 85 降为 80。full pytest 为
  `344 passed`，compileall、fixture smoke 和 `git diff --check` 均通过。
- 跨来源展示变体归并以
  `outputs/ntu-deterministic-20260721-step11-display-variant-merge-live` 验证。该 fallback 只在严格身份
  匹配失败后启用，且必须同时满足 canonical/faculty 相反角色、两个官方 HTML source、
  institution/category/学位族相同和专业主题唯一。JSON API、同角色 source 和不同学位族不走该
  fallback；`Bachelor of Business` / `Bachelor of Accountancy with Second Major in Sustainability`
  均保持独立。
- live facts 从 106 收敛到 101，仅移除 5 个已确认的长标题重复行，新增名称为 0；canonical accepted
  保持 67。`Artificial Intelligence and Society`、`Computer Engineering`、`Economics and
  Media Analytics` 和 `Psychology and Media Analytics` 的 canonical rows 获得 faculty 字段及官方
  enrichment evidence；合并行的主链接 provenance 取并集保留。`missing_faculty` 从 68 降为
  63，catalog warning records 从 80 降为 75，quality-adjusted accepted 保持 36。full pytest 为
  `352 passed`；合并 diagnostics 显式记录 `match_method=cross_source_display_variant`。
- source-role frontier 收缩以
  `outputs/ntu-deterministic-20260721-step12-source-role-frontier-live` 验证。`/programmes/...` 不再仅因祖先
  path 含 `programmes` 就自动成为 `faculty_catalog`；目录叶、明确本科目录叶、catalog 结构或 programme
  listing 文本仍可进入该角色。fetched `faculty_catalog` 从上一轮 94 降至 18，其中 continuing/professional
  噪声从 25 降至 0。释放的 frontier 容量抓到 NIE 官方本科目录，新增 15 个有来源证据的 NIE programme
  rows，上一轮名称零删除；因此 accepted rows 从 101 增至 116，不应把 row 增长解释为 parser 放宽。
- canonical 详情页优先级以
  `outputs/ntu-deterministic-20260721-step13-canonical-detail-priority-live` 验证。单数
  `/undergraduate-programme/<programme>` 现归入有界 `programme_detail`；canonical catalog 直接链接的详情页
  获得独立 frontier signal 和有限 score boost，但仍受每 source family 4 页预算约束。NTU 主域该 family
  实际抓取 4 页、显式跳过 58 页；另有 1 页来自独立的官方 WCMS host。四个主域页面均通过
  `primary_source_url` 匹配已有 row，但其标题没有学院名，因此没有伪造字段。
- 本轮唯一语义字段变化是 `Process Engineering and Synthetic Chemistry` 从 CCEB 官方详情页标题获得
  `School of Chemistry, Chemical Engineering and Biotechnology (CCEB)` 及字段证据；其余 row 内容与
  step12 相同。最终 sources 为 99、accepted rows 为 116、evidence 为 286；`missing_faculty` 从 65 降至
  64，warning objects 从 77 降至 76，warning rows 从 67 降至 66，quality-adjusted accepted 为 50。
  full pytest 为 `355 passed`。
- 截至 Step 13，Step 9 尚未通过。完整性仍为 `probable_incomplete`，剩余 64 个 `missing_faculty` 不得按 URL、专业名或
  sustainability 主题标签猜值。当前 family budget 内的详情选择仍受通用 relevance score 影响，偏向含
  `English` 等高分词的页面；下一轮应在不放大抓取预算的前提下，研究按未解决 row 和可验证学院证据选择
  detail source，而不是提高预算、忽略 warning 或恢复 raw count 绕过质量门。
- related compound detail 的第一版 live 输出
  `outputs/ntu-deterministic-20260721-step14-related-compound-detail-live` 是拒绝样本，不是验收基线。该版从
  孤立的 SPMS detail family 抓到 4 个 HASS double-major 同名页面，并因 `detail_title_identity` 唯一而错误
  写入 `School of Physical and Mathematical Sciences`。页面标题虽然包含学院字符串，但该 family 没有任何
  已捕获 canonical/faculty catalog 上下文，证明“名称唯一 + 官方域 + 标题学院”仍不足以建立归属。
- 修正后的非 primary detail 写入门要求详情 source family 已有被捕获的 canonical/faculty catalog，或详情
  URL 是同 host 目录 URL 的后代；显式命中 row `primary_source_url` 的 redirect 仍可直接进入稳定匹配。
  discovery 的 related-compound 加分也只对 catalog-backed family 生效，仍不改变 `max_pages=120` 和每
  family 4 页预算。离线反例验证孤立 SPMS title identity 被拒绝并保持 `missing_faculty`。
- 修正结果以 `outputs/ntu-deterministic-20260721-step15-catalog-backed-detail-live` 验证：step14 的 4 个错误
  学院全部回退为空，116 个 programme 名称及全部 catalog 语义字段与 step13 完全一致。sources 为 103、
  evidence 为 289、`missing_faculty` 为 64、warning objects 为 76、warning rows 为 66、quality-adjusted
  accepted 为 50，完整性仍为 `probable_incomplete`。8 个 catalog-backed related-compound 候选获得优先
  signal，但没有新增可验证学院字段；这说明下一轮仍需改进候选选择，不能放宽写入门。
- 两阶段定向详情抓取以
  `outputs/ntu-deterministic-20260721-step16-targeted-detail-second-pass-live` 验证。live 默认在原
  `max_pages` 内请求预留 4 页；小预算时有效预留不超过总预算四分之一。首轮本次使用 116 页和每 family
  2 页详情预算，解析目录后只从 pending/budget-skipped frontier 中选择仍缺学院、URL identity 唯一且
  catalog-backed 的 row；第二轮 4 页抓取后总 discovered pages 恰为 120，没有扩大总页数。fixture 默认
  reserve 为 0，外域 redirect 明确拒绝且不能写 source/fact。
- Step 16 选中 56 个可用候选中的 4 个：2 个 HASS detail-title identity 和 2 个 canonical
  primary URL。`Chinese and English`、`English and History` 从 HASS 官方标题获得学院字段及独立 evidence；
  另两个 primary detail 标题没有学院，保持 `missing_faculty`。116 个 programme 名称零新增、零删除，除
  这两个学院字段外 catalog 语义四元组与 step15 相同；错误 SPMS 学院归属仍为 0。`missing_faculty`
  从 64 降至 62，warning rows 从 66 降至 64，quality-adjusted accepted 从 50 升至 52；完整性仍为
  `probable_incomplete`。
- Step 17 将定向详情排序改为“显式 detail 结构、权威目录 row 顺序、稳定 tie-break”，并在
  source family 间 round-robin；通用 relevance score 只保留为 diagnostics，不再决定未解决 row 的
  优先级。4 个目标改为 HASS `Chinese and English`、canonical `Accountancy`、HASS
  `Chinese and Linguistics and Multilingual Studies` 和 canonical `Accountancy (Sustainability
  Management and Analytics)`，仅 1 个名称含 `English`。
- `outputs/ntu-deterministic-20260722-step17-row-fair-targeting-live` 是拒绝样本：排序公平性已生效，
  但第二个 HASS 官方详情标题因超过通用 14 词句子阈值，被误拒绝为 `sentence_like_name`。
  该页未能补全学院，使 `missing_faculty` 从 Step 16 的 62 回退为 63、quality-adjusted accepted
  从 52 回退为 51，因此不能作为验收基线。
- Step 18 只对与官方详情页 source title identity 完全一致的名称放宽通用词数阈值；
  `applicants`、`students`、`provides` 等叙述性标记、句末标点和 240 字符硬上限仍会拒绝。
  programme detail 仍不能新增目录 row，只能在 catalog-backed family 内通过主链接、唯一目录身份
  或唯一 detail-title identity 补全已有 row。
- 最终以 `outputs/ntu-deterministic-20260722-step18-long-detail-title-live` 验证：116 个 programme 零新增、
  零删除，全部目录语义字段只有 `Chinese and Linguistics and Multilingual Studies` 的
  `faculty_or_school` 从空值变为 HASS；证据直接来自该官方详情标题。sources 为 96、
  evidence 为 282、`missing_faculty` 为 62、warning rows 为 64、quality-adjusted accepted 为
  52；错误 SPMS 学院归属仍为 0，完整离线测试为 `364 passed`。
- 当前排序解决了通用关键词偏置，但仍是公平且可审计的确定性近似，不是预知页面内容的
  真实信息增益模型。本次 2 个 canonical Accountancy detail 标题没有学院，所以仍只有 2/4 页
  产生字段补全；目录完整性也仍为 `probable_incomplete`。下一轮应在不放大抓取预算、不放宽
  写入门的前提下，提高定向详情的可验证字段收益。
- Step 19 将可审计的“证据收益先验”接入第二阶段选择。候选页若与已抓取
  `faculty_catalog` 共享 source family 或位于其 URL 祖先路径下，则归入
  `faculty_catalog_backed`；其他已通过 canonical/primary-link 门的候选归入
  `catalog_backed_exploration`。排序先使用结构层级，再按权威目录 row 顺序和稳定
  tie-break；relevance score 仍只用于 diagnostics。
- 为防止单一 faculty family 永久垄断 reserve，当高先验与其他候选同时存在且
  reserve > 1 时，固定保留 1 个 exploration 名额。reserve 为 4、family cap 为 4 时，首轮同
  family 详情容量为 1，第二轮最多使用 3，两轮总数仍不得超过 4；小预算
  reserve <= 2 时仍将同 family 容量全部留给目录解析后的定向抓取。
- `outputs/ntu-deterministic-20260722-step19-evidence-likelihood-targeting-live` 实际选中 3 个
  `faculty_catalog_backed` HASS 详情和 1 个 canonical Accountancy exploration。HASS 首轮 1 页、
  定向 3 页，总计恰为 family cap 4；两阶段总 discovered pages 仍为 120。三个高先验
  目标全部从各自官方标题产生学院 evidence，exploration 页只完成身份匹配、没有写空缺字段。
- Step 18/19 的 116 个 programme 零新增、零删除，所有目录语义字段只新增
  `Economics and Psychology` 的 HASS 学院；错误 SPMS 归属仍为 0。sources 为 95、evidence 为
  282、`missing_faculty` 从 62 降至 61、warning rows 从 64 降至 63、quality-adjusted accepted
  从 52 升至 53；4 个目标仍只有 1 个名称含 `English`。完整离线测试为 `366 passed`。
- 首轮 family 容量重分配会改变 116 页内的 source mix；本live 中 institution、admissions、fees、
  contacts 与 Step 18 一致，scholarships 新增 1 条官方 ASEAN Scholarship 记录，但兼容用 legacy
  `programmes` 从 102 变为 100，discovered categories 也随 source 替换变动。这些变化没有进入权威
  `programme_catalog`，但说明当前配额仍是全局 source-mix 取舍，不能宣称对兼容输出零影响。
- 目录完整性仍为 `probable_incomplete`，还有 61 个 `missing_faculty`。下一轮应优先研究如何
  在不扩大总抓取和不削弱其他 source family 基线的前提下，缩小这个 source-mix 影响。
- Step 20 首先尝试只把 faculty-catalog-backed detail family 的首轮上限保持为 1，其他 detail
  family 恢复为 2。`outputs/ntu-deterministic-20260722-step20-scoped-family-reserve-live` 证明该范围仍过宽：
  canonical `English and History` 虽恢复，但一个没有 catalog backing 的 SPMS detail 也额外进入；
  Step 18 到该输出的 source URL 对称差仍为 16，没有比 Step 19 收敛，因此该输出是拒绝样本。
- 修订规则把首轮 detail 分成三类：带 `canonical_catalog_detail_link` 的 family 使用 2；与已抓取
  `faculty_catalog` 同 family 的详情使用 1；两类证据都没有的 `catalog_unbacked` 详情也使用 1。
  skipped diagnostics 记录实际 `family_budget` 和 `family_budget_policy`；report 同时输出三类预算。
  这只改变首轮容量分配，不扩大 120 页总预算或 family cap 4，也没有改变第二阶段身份匹配、
  official-domain 校验和 evidence 写入门。
- canonical backing 以独立 URL 集合记录；即使详情先从 seed 入队、随后才被 canonical catalog 链接，
  frontier 去重也不会丢失其 catalog-backed 预算身份。该顺序边界已有 deterministic 反例覆盖。
- 验收输出为 `outputs/ntu-deterministic-20260722-step20-catalog-scoped-dedup-safe-live`。首轮诊断为
  default 2、faculty-catalog-backed 1、catalog-unbacked 1，第二轮 family reserve 为 3；仍选中
  Step 19 的 3 个 HASS 高先验目标和 1 个 canonical Accountancy exploration，两阶段 discovered
  pages 合计 120。Step 19 到 Step 20 只新增 canonical-linked `English and History` source，零移除；
  Step 18 到 Step 20 的 source URL 对称差从 16 降到 15。
- Step 19/20 的 116 行 `programme_catalog` 语义完全一致：sources 为 96、evidence 为 282、
  `missing_faculty` 为 61、warning rows 为 63、quality-adjusted accepted 为 53，错误 SPMS 学院归属
  仍为 0，完整性仍为 `probable_incomplete`。兼容用 legacy `programmes` 仍为 100，没有恢复到
  Step 18 的 102；因此本轮只证明扰动范围缩小，未证明 source composition 或兼容输出不变。
- Step 20 live 使用 `--deterministic-only`，`llm_runtime.enabled=false`；完整离线验证为 `369 passed`，
  `compileall`、fixture smoke 和 `git diff --check` 同时通过。下一轮若继续优化，应针对剩余 source
  差异建立独立收益/兼容性指标，不能继续放宽无 catalog backing 的首轮详情额度。
- Step 21 扩展已有 `run.config.diff`，新增三个相互独立的 impact ledger。`source_mix` 按唯一 source URL
  记录 baseline/current records、retained、added、removed 和 symmetric difference；
  `programme_catalog` 按稳定 programme identity 比较权威语义字段，并把字段变化分为 gained、lost、
  changed；`legacy_programmes` 单独记录兼容输出的 programme 增删和字段变化。列表顺序、evidence path、
  source capture 时间和 warning 文本不进入权威 catalog 语义比较。
- 同名 catalog row 只有在任一侧确实存在重复时才加入 degree award/category 复合身份；同名不同 award
  不会互相覆盖。legacy 同名项以 source URL 区分，并对完全重复项使用稳定 occurrence。仅列表重排、
  source-mix-only、字段 gained/lost/changed 和同名不同 award 均有 deterministic 反例。
- 旧 `changed_sources` 和按列表索引生成的 `changed_fields` 继续保留兼容，也继续产生原有
  `incremental_change` warnings；新账本不新增 warning。列表成员变化时旧 `changed_fields` 可能把索引
  位移报告为字段变化，因此后续判断列表语义必须使用 `programme_catalog`/`legacy_programmes` ledger。
- `outputs/ntu-deterministic-20260722-step21-incremental-impact-ledger-final-live` 使用 Step 18 的
  `result.json` 作为 `--previous-result`。baseline/current 都有 96 条 source records，唯一 URL 为
  94 -> 95，added 8、removed 7、symmetric difference 15；内置结果与独立 URL 集合比较一致。
- 权威 catalog 为 116 -> 116、零新增、零移除，只记录 `Economics and Psychology` 的
  `faculty_or_school` gained 1，lost/changed 均为 0；assessment 因此为 catalog gain true、regression
  false。legacy `programmes` 为 102 -> 100，added 2、removed 4，compatibility stable false，明确揭示
  该 source 调整有权威字段收益但没有保持兼容输出稳定。
- Markdown `Incremental Impact` 输出上述计数及最多 5 条 source URL 样本，完整清单保留在 JSON。
  Step 21 没有改变抓取排序、预算、domain policy、事实写入或 LLM 行为；live 仍为 120 页、
  `llm_runtime.enabled=false`、`missing_faculty=61`、quality-adjusted 53。完整验证为 `373 passed`，
  `compileall`、fixture smoke 和 `git diff --check` 通过。下一轮应处理 legacy index-based warning 噪声，
  但不能删除旧字段或静默改变其兼容契约。
- Step 9 最终按 fail-closed 验收通过。`outputs/ntu-deterministic-20260722-step21-incremental-impact-ledger-final-live`
  的权威 `programme_catalog` 为 116 行，已记录的 CSS/模板/跨校名称污染为 0，canonical candidate
  与 section 可对账，accepted row 保留 official evidence 与 structural anchor。当前仍有 61 行
  `missing_faculty`，因此 completeness 正确保持 `probable_incomplete`；这是本轮允许的保守结论，
  不是通过猜测学院值或放宽质量门来换取 `complete`。legacy `programmes` 仍存在 102 -> 100
  的 source-mix 兼容差异，已由 impact ledger 显式保留，不得解读为权威 catalog 退化。
- Step 22 保留 `changed_sources` 和原样的 index-based `changed_fields`，但将它们与 warning 发射策略解耦。
  `field_warning_policy.strategy=stable-semantic-v2` 把 `/programmes/<index>/...` 标记为不稳定路径：路径继续留在
  JSON 供旧消费端读取，但不再逐条生成 `incremental_change` warning。非 legacy 列表路径仍使用
  原 field path 告警，上限仍为 20。
- legacy 列表是否真正变化改由 Step 21 的稳定身份账本决定。仅重排时 `changed_fields` 仍可见，但 warning 为 0；
  有真实增删或字段变化时，生成一条 field 为 `/programmes` 的聚合 warning，message 记录 added、removed 和
  changed rows。这保留了真实兼容性退化信号，不再让列表位移消耗 20 条 field-warning 限额。
- `field_warning_policy` 明示记录 raw changed paths、stable paths、保留的 legacy index paths、被抑制的 index warnings、
  截断数和实际发射数；Markdown `Incremental Impact` 同步输出该摘要。这是显式的 warning cardinality 变更，
  不是对旧 diff 字段的删除或静默改写。
- deterministic 反例覆盖普通字段仍按原路径告警、纯 programme 重排零告警、真实 prerequisite 变化聚合告警、
  真实 programme 增删聚合告警以及无 baseline 的零值策略。Step 22 不改变 source hash warning、抓取、排序、
  预算、抽取、事实写入或 LLM 行为。
- 使用 Step 18/21 现有 NTU JSON 做无网络重放：12 条 raw `changed_fields` 全部仍在，且全部被识别为
  legacy index path；旧的 12 条逐项 warning 收敛为 1 条 `/programmes` warning，其账本仍是 102 -> 100、
  added 2、removed 4、changed rows 0。权威 catalog 仍为 116 -> 116 且 gained field 1，source URL 对称差仍为 15，
  说明本轮只改 warning 表达，没有改写 Step 21 的影响判断。完整验证为 `375 passed`，`compileall`、
  无 baseline/baseline-provided fixture smoke 和 `git diff --check` 通过。
- Step 23 将 warning policy 升级为 `stable-semantic-v3`，把相同原则扩展到 12 个 `RequirementRecord` 集合：
  admissions 下的 international requirements、accepted qualifications、application periods、required documents、
  English requirements、standardized tests、selection tests/interviews，以及顶层 fees、scholarships、visa、
  housing 和 contacts。`run.config.diff.structured_collections` 为每个集合记录独立稳定账本。
- 普通 row 以规范化 label 为 identity；任一侧有重复 label 时，使用 value、applicant group 和 qualification
  构成复合 identity，完全重复行再使用稳定 occurrence。因此重复 `application deadline` 纯重排不告警；
  重复项的 identity 字段改变会保守地表现为 removed + added，不会被当成纯重排。
- 被追踪集合的 raw index path 仍保留在 `changed_fields`，但不再逐项发射 warning。只要对应稳定账本真实变化，
  就在集合路径发射一条聚合 `incremental_change`；即使整行删除导致 raw `changed_fields` 为空，也不会漏报。
  非追踪结构的 FieldValue 仍按原 path 告警。
- `assessment.structured_collections_stable` 明示记录 12 个集合的整体稳定性；`source_mix_only_change`
  现在同时要求权威 catalog、legacy programmes 和 structured collections 全部稳定，避免把申请期、费用或材料变化
  错标为“仅 source mix 变化”。Markdown 报告输出追踪/变化集合数以及 v3 抑制/发射计数。
- deterministic 反例覆盖重复 label 重排、唯一 label 真值变化、无 raw path 的整行删除、结构化集合变化时
  `source_mix_only_change=false`，以及 Step 22 的 legacy programme 兼容边界。Step 23 仍不改变抓取、排序、
  预算、domain policy、抽取、事实写入或 LLM 行为。
- Step 18/21 NTU JSON 无网络重放继续保留 12 条 legacy raw index path 并抑制对应逐项 warning；
  v3 同时发现 `scholarships` 从 4 -> 5、added 1、removed/changed 0。该变化是整行新增，所以旧
  `changed_fields` 中没有 scholarship path，但新账本仍生成 `/scholarships` warning。加上 legacy 102 -> 100 的
  `/programmes` warning，最终为 2 条真实集合告警，而不是 12 条列表位移告警。完整验证为
  `379 passed`，`compileall`、无 baseline/baseline-provided fixture smoke 和 `git diff --check` 通过。
- Step 24 收紧 incremental diff 的输出契约。`structured/diagnostics.json` 在 `run.config.diff` 存在时，现在将其无损复制到
  `diagnostics.diff`；没有 diff 的旧式运行仍省略该可选键。v3 warning 同时继续进入 `structured/warnings.jsonl`，
  集合路径保留在 `field`，不需要下游从 Markdown 或 warning message 反解析。
- structured facts 原先只导出 12 个被追踪 `RequirementRecord` 集合中的 7 个。本轮追加
  `international_requirements.jsonl`、`standardized_tests.jsonl`、`selection_tests_or_interviews.jsonl`、
  `visa.jsonl` 和 `housing.jsonl`；五类 row 同时进入 `facts.jsonl`、manifest files 和 counts。空集合仍生成
  0 行文件，使 manifest 契约不依赖某次抓取是否找到该类事实。
- `structured-output-v1` 版本号保持不变：本轮只添加可选 diagnostics 键、manifest file/count keys 和新 JSONL，
  没有删除或改写现有文件、row 字段、record ID 算法或 CSV schema。deterministic 契约测试覆盖无 diff 兼容、
  diff 无损导出、semantic warning 导出、五类非空 facts 和五类空 manifest 记录。
- CLI fixture 写盘验证中五个新文件全部存在；visa/housing 各有 1 行，international requirements、
  standardized tests 和 selection tests/interviews 为 0 行但仍在 manifest 中有 file/count。无 baseline CLI 导出
  `diff.baseline=none`，有 baseline 导出 `provided`；后者与 `result.json` diff 结构化比较完全相等。
  完整验证为 `381 passed`，focused 为 `57 passed`，`compileall`、两种 fixture smoke 和 `git diff --check` 通过。
- Step 25 将 Step 24 的 12 类单校 requirement JSONL 对称扩展到 batch 根目录。`STRUCTURED_BATCH_FILE_SPECS`
  直接从 `STRUCTURED_REQUIREMENT_RECORD_SPECS` 派生，生成 `all_<record_type>.jsonl`；因此单校和 batch 不再
  各自维护一份 requirement 类型清单。旧有 `all_programme_catalog`、`all_missing_fields` 和 `all_sources`
  的文件名、row 内容和顺序保持不变。
- batch 根新增 `structured/manifest.json`，记录 `schema_version=structured-output-v1`、`output_type=batch`、
  输入学校目录数、每个聚合表行数和文件映射。manifest 不宣称学校数等于每个表的 coverage；
  空表和学校缺少某类事实仍以 0 行表达。
- batch merge 仍只按输入学校目录顺序连接已生成 JSONL，不重新抓取、解析、去重、推断或改写 row。
  Step 24 以前的单校目录没有新 requirement file 时，`_read_jsonl()` 以空集合兼容；batch 仍生成对应空文件
  和 manifest 0 count，同时继续合并该学校存在的旧表。
- deterministic 验证覆盖两所学校顺序、application periods 两行、单校 visa/housing 行归属、
  12 个 file/count manifest 键、CLI batch 实际写盘和旧目录缺文件兼容。完整验证为 `382 passed`，
  batch focused 为 `42 passed`。Step 25 未新增 batch 去重、legacy programmes 聚合或 warnings/evidence/diagnostics 跨校聚合。
- Step 26 为 batch manifest 的全部 15 张表新增 `input_coverage`。每表记录 expected、present、missing、
  nonempty 和 empty file counts，并保留 missing/nonempty/empty 的 input directory name 清单与
  `all_input_files_present`。manifest 顶层 `input_directory_names` 按调用方输入顺序保留全部目录名。
- coverage 统计与 JSONL 合并在同一遍文件读取中完成，不会为诊断重读所有 row。计数不变量为
  `present + missing = expected` 和 `nonempty + empty = present`，且 `input_coverage`、`counts` 与 `files`
  必须覆盖相同表键。
- present-empty 表示单校输出层已生成该文件，但当次为 0 行；missing 表示输入目录没有该文件，
  常见于 Step 24 之前的旧输出或不完整输出。两者都不能单独证明学校官网没有该类信息；下游需要结合
  per-university missing reasons 和 crawl diagnostics 判断。
- 当前格式的两个单校输出验证了 present-nonempty/present-empty 区分；旧目录反例验证了 missing
  与已有 `all_sources` 继续合并；CLI batch 验证所有新单校文件都会被记为 present。完整验证为
  `382 passed`，batch focused 为 `42 passed`。Step 26 没有改变聚合 row、顺序、文件名或缺文件 fail-open 行为。
- Step 27 在 coverage 之上新增 batch row-envelope 审计。`input_validation` 逐表统计 total、
  valid/invalid rows、invalid files、受影响目录和 reason counts；`input_validation_summary` 提供
  15 表的聚合计数与 `all_rows_valid`。
- 公共校验要求每行是 JSON object、`schema_version=structured-output-v1`、`university_id`
  与输入目录名一致；programme catalog 和 12 类 requirement 还要求 `record_type`
  与所在聚合表一致。一行可同时累计多个原因，但 manifest 只保留文件级聚合，不复制原始招生内容。
- Step 27 仍是只审计的兼容层：异常行保留在 `all_*.jsonl` 且计入 `counts`；缺文件由
  `input_coverage` 表达，不会被记为无效行；JSON 语法损坏仍直接报错。本步未验证每张表全部
  业务字段、跨表 source/evidence 引用完整性，也未将审计异常升级为 batch 阻断。
- deterministic 反例同时覆盖 schema version、学校 ID、record type 的缺少、类型错误与值不匹配，以及非 object row，
  并验证异常行保持原顺序。正常两校和 CLI batch 反例验证 0 invalid rows；旧目录在 Step 27
  只验证 missing coverage，其结构完整性由 Step 28 进一步审计。
  完整验证为 `383 passed`，structured/batch focused 为 `43 passed`，`compileall` 和 `git diff --check` 通过。
- Step 28 将校验从公共 envelope 扩展到表级最小结构。source row 要求 `run_id/source_id/source_url`，
  missing-field row 要求 `run_id/field_key/status/source_urls`，record row 要求
  `run_id/record_id/value/source_refs/evidence_refs`。字段缺失、类型错误和空必需字符串
  使用带字段名的 reason key 分开统计。
- record row 的空引用列表合法；已出现的 source/evidence ref 必须是 object，包含 string ID，
  且能解析到同一学校当前 schema 的 `sources.jsonl` / `evidence.jsonl`。`reference_index_coverage`
  区分 missing、unreadable 和 readable index files，并统计 usable IDs 和 invalid identifier rows。
- 校验按阶段执行：envelope 已无效时不再叠加深层字段/引用噪音。旧目录仍可合并，但缺少
  `run_id/source_id` 会显式成为 invalid row；辅助 evidence index JSON 损坏时标记 unreadable
  和 `evidence_reference_index_unavailable`，不丢弃 record row。被聚合的 JSONL 本身语法损坏仍中断合并。
- deterministic 验证覆盖合法/缺失/错类型最小字段、无法解析的 source/evidence refs、旧目录
  结构缺口、损坏辅助 evidence index 和 CLI 实际写盘。完整验证为 `385 passed`，
  structured/batch focused 为 `45 passed`，`compileall` 和 `git diff --check` 通过。
- Step 29 将可用 ID 从“格式正确”收紧为“同校唯一”。source/evidence index 保留唯一 ID set 和
  ambiguous ID set；`reference_index_coverage` 追加 duplicate identifier count、duplicate row count 和
  受影响目录。指向重复 ID 的 record ref 使用 `ambiguous_source_ref` / `ambiguous_evidence_ref`，
  不再误记为 resolved。
- `evidence_validation` 审计可读 evidence rows 的 envelope、`run_id/evidence_id`、evidence ID 唯一性，
  以及 `source_id` 到同校 source index 的 available/ambiguous/unresolved 链路。缺 source index 与空链接、
  错类型 ID 分开统计。
- programme catalog 和 12 类 requirement 在合并前使用同一 JSONL cache 预扫描 `record_id`；
  同表重复和跨表冲突都将所有相关 row 标记 `duplicate_record_id`。唯一性按学校边界判断，
  本步仍不删除、合并或重排 row。
- CLI fake-live 回归暴露了既有的 6 条 application periods 和 6 条 required documents 重复；
  原因是 fake fetcher 对多个 URL 返回同一页面，不是 Step 29 生成了新重复。验收固定为保留 12 条 row
  并在 manifest 中报告，不通过放宽唯一性规则隐藏。
- deterministic 验证覆盖 source/evidence 重复 ID、指向歧义索引的 record refs、evidence-source
  missing/invalid/ambiguous/unresolved 链路、缺 source index，以及同表/跨表 record ID 重复。
  完整验证为 `388 passed`，structured/batch focused 为 `48 passed`，`compileall` 和 `git diff --check` 通过。
- Step 30 在已有细分审计之上新增顶层 `batch_validation`，避免下游自行组合多组
  coverage/validation 字段得出不一致结论。`valid` 表示当前 structured artifact integrity
  校验通过；`incomplete` 表示仅有聚合输入/引用索引文件缺失，或 batch 没有学校输入；
  `invalid` 表示存在无效输入/evidence row、不可读索引、非法引用 ID 或重复/歧义 ID。
- 状态优先级固定为 `invalid > incomplete > valid`。manifest 同时写入排序后的
  `reason_codes`、`ready_for_structured_consumption` 和稳定聚合 metrics。文件缺口按审计面计数：
  同一物理 `sources.jsonl` 缺失可同时进入 aggregate input 与 reference-index 缺口，这些数字
  不是去重后的物理文件数。
- verdict 保持非阻断：不丢弃、改写、去重或重排任何 row，不改变 CLI 退出码；
  它也不证明官网抓取或招生字段完整。验证覆盖正常两校 `valid`、单文件缺失与空 batch
  `incomplete`、重复 source/evidence ID 及现有 CLI fake-live 重复 record `invalid`。
  完整验证为 `390 passed`，structured/batch focused 为 `50 passed`；本步未新增 strict mode、
  fail-fast 或内容完整性分数。

截至 Step 30，本文列出的 Step 0--9 主计划及后续 structured-output/batch 分批交付均已完成。
未解决的 `missing_faculty`、legacy source-mix 差异和其他后续候选不得重新标记为本计划的未完成 Step。

live 输出只作为当日验收样本，核心正确性仍由离线 fixture tests 保证。

## 实施顺序与停点

严格按以下顺序执行，前一步未验收不得通过放宽后一步规则绕过：

1. Step 0：真实回归 fixture。
2. Step 1：typed HTML blocks。
3. Step 2：block-aware parser。
4. Step 3：programme entity gates。
5. Step 4：source role 与 canonical-first discovery。
6. Step 5：institution profile 隔离。
7. Step 6：去重和 completeness diagnostics。
8. Step 7：output semantics 和兼容性。
9. Step 8：离线全量验证。
10. Step 9：NTU live deterministic 验收（已按 fail-closed 边界完成）。

建议提交边界：

- Commit A：fixtures + typed block contract。
- Commit B：block-aware parser + entity gates + institution isolation。
- Commit C：source roles + canonical discovery + completeness diagnostics。
- Commit D：output/docs alignment + live verification evidence。

每个 commit 都必须保持 focused tests 通过；不能把失败 fixture 和最终修复分散到无法独立审查的提交。

## 每轮汇报格式

每完成一个 Step，固定汇报：

- 改了什么：文件、行为和新增测试。
- 没改什么：明确本轮边界。
- 验证结果：focused tests、full tests、smoke/live 是否执行。
- 当前风险：false negative、兼容性、站点变体和未覆盖 source role。
- 下一步：只进入计划中的下一个 Step。

## 完成定义

本计划只有同时满足以下条件才算完成：

- 所有新增 NTU regression fixtures 通过。
- 现有 NUS/HKU/PolyU/non-standard fixtures 不回归。
- full pytest、compileall、fixture smoke 和 `git diff --check` 通过。
- NTU deterministic live 输出通过零 CSS/正文/课程/related-container 污染验收。
- accepted rows 全部具有 structural anchor 和 official evidence。
- canonical catalog 完整性可证明，或系统明确、保守地报告 incomplete。
- legacy 与 structured 输出路径保持兼容。
- README、PROJECT_MAP、VERSION_NOTES 与本文件更新为实际实现状态，不提前宣称未完成能力。

## 风险总表

| 风险 | 控制措施 |
|---|---|
| 改 HTML normalization 影响其他 extractor | typed blocks additive，plain text 保持兼容，跨 extractor 回归 |
| 规则收紧造成 false negative | quarantine + rejection ledger，不回退到宽松整页扫描 |
| NTU 特判污染通用代码 | domain-scoped profile，generic structural parser 优先 |
| canonical path 在其他学校不存在 | 通用 source-role signals + 可选 profile hints |
| live 官网持续变化 | 最小真实 fixture + 当日 live 验收，禁止硬编码总数 |
| related links 被误当 facts | 只进入 discovery，目标页捕获后再确认 |
| API 不可用阻塞交付 | canonical HTML 可独立完成，API 降为可选增强 |
| diagnostics 再次膨胀 | 只新增验收需要的聚合字段，候选明细单独保存 |
| 下游依赖 manual-review rows | 保留文件兼容，记录 quality tightening，quarantine additive |
| 模型输出改变事实 | deterministic gate 权威，LLM candidates 继续 fail closed |

## 模型边界

模型可以提出 source、API、pagination、filter、mapping 和 candidate 建议，但所有建议都必须由代码抓取并
验证。模型不能编造 URL、绕过权限、替代 canonical source、跳过 entity gate，或在没有 captured
official evidence 的情况下写入 programme facts。
