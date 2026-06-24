# 关键词爬取、诊断与 Source Planning 设计说明

## 文档定位

本文档记录当前分支的阶段性目标和执行计划。上一轮
`feature/model-assisted-keyword-crawl` 已合入 `main`；当前分支已完成
字段级缺失原因和 NTU fees 边界修复样板，接下来进入新的当前任务目标：

**Phase 3: Source Acquisition Failure and LLM-Assisted Official Source Planning**

中文描述：

**阶段 3：来源获取失败诊断与 LLM 辅助官方来源规划**

项目最终目标是自动化爬取任意大学官网招生信息的关键字段。NTU 对比说明，
当前系统已经能在字段层解释 extractor/no-match/context-gate 问题；NUS 对比
进一步暴露出更靠前的一层瓶颈：有些官网入口会返回 WAF/challenge 页面，导致
extractor 根本没有拿到可用招生文本。

因此当前阶段不应继续盲目补 extractor，而应先让系统能准确表达：

- source 被抓到了，但内容是 WAF/challenge，不是招生页面。
- 字段缺失是 source acquisition 层失败，不是 extractor 本身没写好。
- LLM 可以辅助寻找官方替代来源，但不能绕过 WAF，也不能直接写 facts。
- 所有 facts 仍必须来自实际抓取到的官方 source、snippet 和 evidence path。

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

### NUS 对比结论

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

当前 feature 对 NUS 的 live HTTP 和 browser 跑法都只能抓到 1 个 source，并且内容是：

- `NOINDEX, NOFOLLOW`
- `_Incapsula_Resource`
- `Request unsuccessful`
- `Incapsula incident ID`

当前 report 因此显示 coverage `0/9`。这不是 extractor 回归，而是 source acquisition
失败。当前 diagnostics 能显示 `attempted_no_match`、`context_gate_failed`、
`not_attempted`，但还没有把 WAF/challenge 明确提升为字段级 source acquisition
失败。

## 当前任务目标

本阶段目标是让系统在 NUS 这类站点上不再误导后续修复方向：

- 识别 WAF/challenge/noindex 页面。
- 把这类 source 标记为 `blocked_or_challenge`，而不是普通 `html_page`。
- 让字段级 `missing_reasons` 能表达 source acquisition 层失败，例如
  `source_not_crawled` 或 `blocked_or_challenge`。
- 引入 opt-in、mock-first 的 LLM-assisted source planning。
- LLM 只生成候选官方 URL、候选 query 和页面类型 hint。
- 所有候选 URL 必须通过 deterministic validation。
- LLM 输出只能进入 diagnostics，不能直接写入招生 facts。

LLM 在本阶段的角色是“导航和诊断助手”，不是事实来源，也不是 WAF 绕过工具。

## 执行计划

### Step 1：固定 NUS challenge 失败边界

修改文件：

- `tests/test_pipeline.py`
- 必要时新增 `tests/fixtures/saved_sources/nus/incapsula_challenge.html`

目标：

- 把本次 NUS 抓到的 Incapsula 页面压缩成最小 fixture。
- 用 fixture 固定当前系统应识别 challenge 页面，而不是把它当普通 admissions HTML。
- 先不接 LLM，也不改 extractor。

预期行为：

- 不产生 programme / fee / deadline facts。
- source 应被诊断为 blocked/challenge。
- diagnostics 应说明 source acquisition 层失败，而不是伪装成 extractor no_match。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py
git diff --check
```

风险控制：

- 只使用明确 challenge 特征：`NOINDEX, NOFOLLOW`、`_Incapsula_Resource`、
  `Request unsuccessful`、`incident_id`。
- 不写过宽规则，避免误伤普通招生页面。

### Step 2：实现 deterministic blocked/challenge detection

修改文件：

- 优先在 `university_admissions_crawler/crawler/` 中放置检测逻辑。
- 可能涉及 `university_admissions_crawler/crawler/filters.py`。
- 如 source strategy 写入点需要接入，才小范围修改
  `university_admissions_crawler/pipeline/run_university_scan.py`。

目标：

- 增加 dependency-free detector。
- 检测明显 challenge / WAF / bot-block 页面。
- 把 source strategy 标记为 `blocked_or_challenge`。
- 保留 source 供审计，但不把它当可用招生内容推给 extractor。

检测信号建议：

- HTML meta robots 包含 `NOINDEX, NOFOLLOW`。
- script、iframe 或 URL 包含 `_Incapsula_Resource`。
- 页面文本包含 `Request unsuccessful`、`Incapsula incident ID`、`Access Denied`、
  `captcha`、`bot detection`、`blocked`。
- 正文极短，主要内容是 iframe / challenge script。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_pipeline.py
git diff --check
```

风险控制：

- detector 只改变 diagnostics/source strategy，不删除 source。
- 不把 blocked source 写成 admissions facts。
- 不把 challenge 解释成“官网没有提供字段”。

### Step 3：调整 missing reason 的 source acquisition 边界

修改文件：

- `university_admissions_crawler/pipeline/diagnostics.py`
- `tests/test_pipeline.py`

目标：

- 当核心 source 是 blocked/challenge 且没有 usable text 时，字段缺失应归因为 source
  acquisition 层问题，而不是 extractor no-match。
- 建议新增或使用 `source_not_crawled`，note 说明：

```text
Captured source was blocked/challenge content, so extractors did not receive usable official page text.
```

优先级建议：

1. challenge source 上的 acquisition failure 优先于该 challenge source 上产生的
   `no_match`。
2. usable source 上的 `attempted_no_match` 仍高于 context gate。
3. context gate 高于 portal/manual check。
4. portal/manual check 高于普通 `not_attempted`。
5. 不能归类时才用 `manual_check_required`。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py
git diff --check
```

风险控制：

- 只改变 diagnostics/missing reasons。
- 不改变 facts。
- 不改变 coverage 计算。

### Step 4：引入 LLM-assisted source planning 的 opt-in 入口

修改文件：

- 复用现有 LLM plumbing：
  - `university_admissions_crawler/extractor/llm_provider.py`
  - `university_admissions_crawler/config.py`
  - `university_admissions_crawler/cli.py`
- 新增小模块，例如：
  - `university_admissions_crawler/crawler/source_planner.py`
  - 或 `university_admissions_crawler/pipeline/source_planning.py`

目标：

- 新增显式开关，例如 `--enable-source-planning`。
- 仅在用户显式启用 `--enable-llm --llm-provider mock --enable-source-planning`
  时运行。
- 触发条件优先包括：
  - 检测到 `blocked_or_challenge` source。
  - captured sources 对核心字段全部 missing。
- LLM 输出只写 diagnostics，例如 `run.config.llm_source_plan`。

候选输出形态：

```json
{
  "candidate_urls": [
    {
      "url": "https://www.nus.edu.sg/nusbulletin/ay202526/programmes/",
      "reason": "Official NUS Bulletin programmes index",
      "expected_category": "programme_list"
    }
  ],
  "candidate_queries": [
    "site:nus.edu.sg undergraduate admissions application period NUS",
    "site:nus.edu.sg nus bulletin undergraduate programmes"
  ],
  "warnings": []
}
```

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_compatibility_boundaries.py
git diff --check
```

风险控制：

- 默认不开启。
- mock-first，不接 hosted provider。
- LLM plan 不直接 follow URL，不写 facts。

### Step 5：deterministic validation LLM 候选 URL

修改文件：

- `university_admissions_crawler/crawler/`
- `tests/test_discovery.py`
- `tests/test_filters.py`
- `tests/test_pipeline.py`

目标：

- LLM 生成的 URL 必须通过 deterministic validator 才能进入候选队列。
- validator 至少检查：
  - HTTPS。
  - official allowed domain / allowed subdomain。
  - 不允许 social media、forum、tracking、marketing redirect。
  - category 只能作为 hint，不能直接决定 facts。
- rejected candidate 进入 diagnostics，不静默丢弃。

NUS 场景中，如果用户配置 `--allowed-domain nus.edu.sg`，可以接受官方子域：

- `www.nus.edu.sg`
- `nus.edu.sg`
- `chs.nus.edu.sg`
- `dentistry.nus.edu.sg`

但这不应硬编码成全局特殊规则。全局规则应以 allowed domain 和 official domain
validation 为准。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_discovery.py tests/test_filters.py tests/test_pipeline.py
git diff --check
```

风险控制：

- LLM 只提出候选。
- validator 决定能否进入 crawl frontier。
- facts 仍必须来自实际抓取并通过 evidence validation 的 source。

### Step 6：报告展示 source planning diagnostics

修改文件：

- `university_admissions_crawler/reports/markdown.py`
- `tests/test_report_cli.py`

目标：

- 在 facts 前新增 diagnostics section，例如 `Source Planning Diagnostics`。
- 报告应显示：
  - blocked/challenge sources 数量。
  - LLM source planning 是否启用。
  - accepted candidate URLs。
  - rejected candidate URLs。
  - 明确 note：source planning diagnostics are not admissions facts。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_report_cli.py tests/test_pipeline.py
git diff --check
```

风险控制：

- diagnostics 位于 facts 前。
- 不把候选 URL 当作已抓取 source。
- 不把候选来源写入 admissions facts。

### Step 7：建立 NUS mock source-planning 回归样板

修改文件：

- `tests/test_pipeline.py`
- `tests/test_discovery.py`
- 必要时新增：
  - `tests/fixtures/saved_sources/nus/incapsula_challenge.html`
  - `tests/fixtures/llm/source_plan_nus.json`

目标：

用 mock LLM 固定一个 NUS 场景：

- seed URL: `https://www.nus.edu.sg/oam/undergraduate-programmes`
- captured source: Incapsula challenge
- allowed domain: `nus.edu.sg`
- mock candidate URLs:
  - `https://www.nus.edu.sg/nusbulletin/ay202526/programmes/`
  - `https://www.nus.edu.sg/nusbulletin/ay202526/programmes/school-of-computing/undergraduate-education/`
  - `https://chs.nus.edu.sg/programmes/`

测试断言：

- challenge source 标记为 `blocked_or_challenge`。
- missing reason 包含 source acquisition failure。
- accepted candidates 只包含官方 NUS domain。
- rejected candidates 不进入 crawl。
- facts 仍为空，直到真实 source 被抓取并抽取。

验证方式：

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_pipeline.py tests/test_discovery.py
git diff --check
```

风险控制：

- 只用 mock LLM。
- 不依赖 live network。
- 不把旧 NUS programme collection 直接当自动 crawler 输出。

### Step 8：live smoke 验证 NUS 诊断表达

修改文件：

- 无。输出写入 `/tmp`。

目标：

- 验证 live NUS 不再表现为普通 extractor failure。
- 即使 coverage 仍为 `0/9`，报告也应清楚说明：
  - source blocked/challenge。
  - 字段缺失是 source acquisition 层问题。
  - mock planner 给出了官方候选来源。
  - facts 没有被 LLM 填充。

验证命令示例：

```bash
.venv314/bin/python -B -m university_admissions_crawler.cli \
  https://www.nus.edu.sg/oam/undergraduate-programmes \
  --enable-browser \
  --browser-wait-until domcontentloaded \
  --timeout-seconds 45 \
  --output-dir /tmp/nus-source-planning-check \
  --allowed-domain nus.edu.sg \
  --max-pages 30 \
  --max-depth 2
```

如果启用 mock source planning：

```bash
.venv314/bin/python -B -m university_admissions_crawler.cli \
  https://www.nus.edu.sg/oam/undergraduate-programmes \
  --enable-browser \
  --enable-llm \
  --llm-provider mock \
  --enable-source-planning \
  --output-dir /tmp/nus-source-planning-check \
  --allowed-domain nus.edu.sg \
  --max-pages 30 \
  --max-depth 2
```

## 本阶段不做

- 不使用 LLM 绕过 WAF、人机验证或访问控制。
- 不把 LLM 输出写入 admissions facts。
- 不在没有实际抓取 source 的情况下生成 programme、fee、requirement 等事实。
- 不直接重写 extractor 来“适配”challenge 页面。
- 不把旧 NUS programme collection 当成当前自动 crawler 已达成能力。
- 不全面重写 `run_university_scan.py`。
- 不刷新或提交大批 `outputs/` 历史产物。
- 不做无关格式化、无关依赖升级或全仓重排。

## 完成标准

本阶段可以认为完成，当且仅当：

- NUS / Incapsula 类 challenge 页面有 fixture-backed 测试。
- challenge source 被标记为 `blocked_or_challenge` 或等价 source-acquisition
  diagnostic。
- 字段级 `missing_reasons` 能把 challenge 场景解释为 source acquisition failure，
  而不是普通 extractor no-match。
- LLM source planning 是显式 opt-in、mock-first、diagnostics-only。
- LLM candidate URL 经过 deterministic validation，accepted/rejected 都可审计。
- 报告在 facts 前展示 source planning diagnostics，并明确它不是招生事实。
- 完整 deterministic 测试通过。

最终，本阶段的价值不是让 NUS 立刻产出 85 条 programme records，而是把“官网入口
被 WAF/challenge 阻断”从模糊缺失变成可诊断、可规划、可验证的 source acquisition
问题，为后续自动发现官方替代 source 打基础。
