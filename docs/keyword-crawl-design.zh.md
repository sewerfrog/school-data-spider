# 官网主页自动招生爬取：当前状态与未完成计划

## 文档定位

这份文档只记录当前工程状态、已完成能力的压缩索引，以及下一步可执行计划。旧的 Phase 3/4/5/6
流水账不再保留。

当前产品目标：

- 输入大学官网或招生页 URL 后，自动发现官方招生 source。
- 只从 captured official source 写入 facts；没有证据的字段保持 `unknown`、missing reason 或
  manual-review diagnostics。
- 高基数专业目录写入 `AdmissionsData.programme_catalog`，`programme_catalog.csv` 只是渲染结果，
  不负责发现或补全。
- `result.json` 继续作为完整内部快照和兼容输出；当前已新增清洗友好的
  `structured/` output，并已覆盖 programme catalog、第二批核心 fact records 和 batch 合并输出。
  schema migration / compatibility policy 已同步到 README、PROJECT_MAP 和 VERSION_NOTES。

## 当前进度快照

当前分支：

```bash
feature/structured-output-cleaning
```

最近已合入 `main` 的稳定提交：

```text
c0fe2d7 Improve API catalog discovery diagnostics
```

当前主链路已具备：

- homepage-first discovery、sitemap、bounded frontier、common path probing。
- live HTTP、可选 Playwright browser fallback、fixture scan、可选 PDF parsing。
- source/evidence provenance、claim path validation、missing reasons、template completeness。
- `programme_catalog` schema、CSV renderer、row-level evidence。
- API catalog discovery、safe capture、pagination、filter enumeration、body detector。
- dynamic shell diagnostics、browser/network metadata capture、同源 static JS endpoint hint discovery。
- guarded LLM source planning / classification assist / structured extraction fallback；LLM 不能直接写无证据事实。

当前验证基线：

```bash
.venv314/bin/python -m pytest -q
# 241 passed

git diff --check
# passed
```

## NTU 当前结论

NTU 专业目录仍未通过 API 完整拿到。近期两类输出证明：

- `outputs/ntu-api-live-new-feature`
  - 输入动态目录页。
  - `programme_catalog_rows=0`。
  - 发现 1 个 suggestions API candidate：
    `/api/suggestions/get?...programmesIndex=programmes...`
  - safe capture attempted 1，结果 `capture_failed`。
  - `recommended_next_action=discover_public_catalog_api`。
  - static asset discovery 未触发，因为页面源码已经先发现 embedded API hint。

- `outputs/ntu-live-new-feature-full`
  - 输入 `https://www.ntu.edu.sg/admissions/undergraduate`。
  - `sources=28`。
  - `programme_catalog_rows=5`。
  - `candidate_source_count=17`。
  - `api_endpoint_candidate_count=1`。
  - `api_response_count=0` / `api_accepted_row_count=0`。
  - `html_fallback_used=true`。
  - `probable_incomplete_catalog=true`。
  - `recommended_next_action=improve_table_segmentation`。

结论：

- 当前 NTU CSV 仍是 HTML fallback 的不完整结果，不是完整 API catalog。
- API discovery 已能把普通 search template 噪声收敛掉，但还没有发现真正返回 programme rows 的
  Sitecore/search/listing/Next data endpoint。
- 继续堆 line-based parser 不是最优先事项；仍应先找公开 catalog API 或明确 HTML fallback 的清洗边界。

## 已完成能力压缩索引

### 1. 扫描与证据主链路

已完成：

- `run_scan()` / `run_fixture_scan()` 主入口稳定。
- source record、source text artifact、evidence item、claim path validation 已接入。
- `run_university_scan.py` 已拆出 category extraction、structured fallback、LLM runtime、
  diagnostics、API catalog helper 等模块，主文件仍保留编排职责。

保留风险：

- `run_university_scan.py` 仍是中心编排入口；新增复杂输出或 diagnostics 时应继续抽 helper。
- diagnostics 只能解释本次 run 的 captured-source 和 extractor 状态，不能证明官网不存在字段。

### 2. Programme Catalog 与 CSV

已完成：

- `ProgrammeCatalogRecord` / `AdmissionsData.programme_catalog`。
- `programme_catalog.csv` 稳定字段顺序。
- `programme_catalog_summary` 包含 candidate source、accepted rows、low row yield、
  probable incomplete、next action、source family 等指标。
- HTML parser 已有课程表止血规则，阻断 `Course Code`、`Course Title`、`AU`、`Pre-req`、
  `Open to`、`Major PE Courses` 等课程表上下文误写为专业。

保留风险：

- HTML fallback 仍可能误抽长正文、second-major 说明和未知表格变体。
- `programme_catalog.csv` 只覆盖专业目录，不覆盖其他核心字段。
- 当前 CSV 的 `warnings` 是 JSON 字符串，不适合直接做质量统计。

### 3. API Catalog 路径

已完成：

- API candidate discovery diagnostics。
- safe capture 边界：
  - official domain。
  - GET。
  - non-auth/token query。
  - JSON body / JSON source。
  - response size limit。
  - off-domain redirect rejected。
- `extract_programme_catalog_api()` 支持常见 JSON list/items/results/data/edges/nodes 结构。
- pagination proof：page/pageSize、offset/limit、cursor/hasNextPage。
- filter enumeration proof：从官方 metadata 枚举低风险 level/programmeType/studyMode/faculty。
- browser network response metadata 和 body hash/truncated summary。
- dynamic shell + API 0 的 browser second-pass capture。
- dynamic shell + API 0 的同源 static JS asset endpoint hint discovery。
- body-level catalog detector：URL 不明显但 body 像 catalog 时可成为 candidate；body 不像 catalog
  时 rejected。

保留风险：

- NTU 尚未找到真正 catalog JSON/API。
- GraphQL、Algolia、Sitecore、Next.js data、ElasticSearch adapter 尚未实现。
- body detector 只决定 candidate，不直接写 facts；事实仍必须来自 captured JSON object。

### 4. Diagnostics 与 missing reasons

已完成：

- `field_capability_matrix`。
- canonical `missing_reasons`。
- `action_target` / `next_action`。
- `template_completeness`。
- `programme_catalog_summary`。
- API discovery / capture diagnostics。
- Markdown report 展示 source strategy、API discovery、programme catalog diagnostics、missing reasons。

保留风险：

- `run.config` 已成为大型诊断容器；它对工程排查有用，但不适合作为清洗契约。
- rejected-row 级别 ledger 还不完整。
- `false_positive_rejected_count` 是 summary 字段，不等于完整可审计明细。

### 5. LLM guarded 能力

已完成：

- OpenAI 本地配置和 `.env.example`。
- OpenAI Responses API provider：`--llm-provider openai`。
- OpenAI-compatible chat completions provider：`--llm-provider openai-chat` 或
  `UAC_LLM_PROVIDER=openai-chat`。
- guarded source planning。
- low-confidence classification assist diagnostics。
- programme catalog hint。
- structured extraction fallback。
- LLM candidate 必须通过 captured source text、snippet、claim path 白名单验证后才能写 facts。

保留边界：

- `openai-chat` 只是 provider adapter：把 guarded instructions 和 JSON payload 转成
  `/v1/chat/completions` messages，并解析 `choices[0].message.content` 中的严格 JSON object。
- `OPENAI_BASE_URL` / `OPENAI_CHAT_COMPLETIONS_PATH` 只控制中转站 endpoint；
  `OPENAI_CHAT_RESPONSE_FORMAT` 默认 `json_schema`，仅在 relay 或 relay WAF 拒绝大 schema body
  时降级为 `json_object` 或 `none`；
  `OPENAI_REASONING_EFFORT` 只有设置时才传给 chat provider；
  `OPENAI_USER_AGENT` 只影响 OpenAI-compatible relay 请求头，用于兼容拒绝 Python 默认 `urllib`
  client signature 的中转站 WAF。
- 中转站 JSON schema / `response_format` / reasoning 参数兼容性不稳定时，应 fail closed 到 diagnostics，
  不绕过 deterministic validator。
- 模型可以提出 source、candidate、pagination、filter、mapping 建议。
- 模型不能编造事实、接口 URL 或绕过登录/验证码/WAF/token/签名。
- 运行时不能用模型为每条 row 生成招生事实。

## 当前输出治理状态

兼容输出仍然保留：

```text
outputs/<run>/
  result.json
  report.md
  programme_catalog.csv   # 只有 programme_catalog 非空时存在
  sources/
```

清洗输出已经新增：

```text
outputs/<run>/
  structured/
    manifest.json
    institution.json
    facts.jsonl
    sources.jsonl
    evidence.jsonl
    missing_fields.jsonl
    warnings.jsonl
    diagnostics.json

    records/
      programme_catalog.jsonl
      programme_catalog.csv
      application_periods.jsonl
      fees.jsonl
      english_requirements.jsonl
      accepted_qualifications.jsonl
      required_documents.jsonl
      scholarships.jsonl
      contacts.jsonl
      programmes_legacy.jsonl
```

batch config 扫描还会额外生成跨校合并表：

```text
outputs/batch/
  structured/
    all_programme_catalog.jsonl
    all_missing_fields.jsonl
    all_sources.jsonl
```

已缓解的问题：

- 清洗侧可以优先消费 `structured/`，不再必须直接解析混杂的 `result.json`。
- `programme_catalog` 已有 JSONL 主表和清洗版 CSV。
- `sources.jsonl` / `evidence.jsonl` / `facts.jsonl` 之间可通过稳定 `source_id`、
  `evidence_id`、`record_id` join。
- `missing_fields.jsonl` 直接来自 `run.config["missing_reasons"]`，不需要从 Markdown report
  反向解析。
- batch config 扫描会在 batch 根目录写出 `structured/all_programme_catalog.jsonl`、
  `structured/all_missing_fields.jsonl` 和 `structured/all_sources.jsonl`，便于跨校清洗。
- `all_sources` 行包含 normalized source host/path；programme catalog row 包含
  `normalized_programme_name_key`，可作为初步去重辅助键。
- structured output records 由 `tests/test_structured_output.py` 覆盖，并保留旧输出兼容行为。

仍未解决的问题：

- `result.json` 仍然同时包含 facts、sources、evidence、warnings、discovered categories、
  `run.config` 大量 diagnostics；它仍是内部运行态快照，不是清洗主契约。
- `institution.name` 等 scalar 仍只在 `institution.json` 和 legacy `result.json` 中表达，
  尚未进入统一 fact envelope。
- `international_requirements`、`standardized_tests`、`selection_tests_or_interviews`
  等少数字段仍未进入 structured records 主表。

下一阶段目标不是重构抽取器，而是在现有 export layer 上继续扩展清洗契约。

## 未完成计划

### P0：Structured Output for Cleaning

状态：第一批、第二批和第三批已完成。后续若要把 institution scalar facts 纳入统一 fact
envelope，应作为独立 schema slice 处理。

目标：

- 保留 `result.json`、`report.md`、`programme_catalog.csv` 的兼容行为。
- 新增 `structured/` 输出目录，作为后续数据清洗的主入口。
- 清洗侧优先消费 `structured/`，不直接消费 `result.json`。
- facts、sources、evidence、missing、diagnostics 分文件输出，避免混杂。

目标输出结构：

```text
outputs/<run>/
  result.json
  report.md
  programme_catalog.csv
  sources/

  structured/
    manifest.json
    institution.json
    facts.jsonl
    sources.jsonl
    evidence.jsonl
    missing_fields.jsonl
    warnings.jsonl
    diagnostics.json

    records/
      programme_catalog.jsonl
      programme_catalog.csv
      application_periods.jsonl
      fees.jsonl
      english_requirements.jsonl
      accepted_qualifications.jsonl
      required_documents.jsonl
      scholarships.jsonl
      contacts.jsonl
      programmes_legacy.jsonl
```

batch config 输出结构：

```text
outputs/batch/
  <university-id>/
    result.json
    report.md
    structured/
    sources/

  structured/
    all_programme_catalog.jsonl
    all_missing_fields.jsonl
    all_sources.jsonl
```

核心输出原则：

- `result.json` 是 legacy/debug full snapshot。
- `structured/records/*.jsonl` 是清洗主表。
- `structured/sources.jsonl` 和 `structured/evidence.jsonl` 是可 join 证据表。
- `structured/missing_fields.jsonl` 只放缺失字段和原因。
- `structured/diagnostics.json` 只放 run-level 诊断摘要。
- batch-level `structured/all_*.jsonl` 只合并每所学校已生成的 per-university structured
  JSONL，不重新解析招生事实。
- 每条事实必须有：
  - `schema_version`
  - `run_id`
  - `university_id`
  - `record_type`
  - `record_id`
  - `status`
  - `confidence`
  - `parse_status`
  - `quality_flags`
  - `source_refs`
  - `evidence_refs`

建议统一事实 envelope：

```json
{
  "schema_version": "structured-output-v1",
  "run_id": "2026-07-07T07:59:52Z__ntu",
  "university_id": "ntu",
  "university_name": "Nanyang Technological University",
  "record_type": "programme_catalog",
  "record_id": "programme_catalog__9b7c2a1f3e",
  "status": "accepted",
  "confidence": "medium",
  "parse_status": "parsed",
  "quality_flags": ["missing_faculty", "category_inferred"],
  "value": {
    "name": "Bachelor of Science in Environmental Earth Systems Science",
    "faculty_or_school": null,
    "degree_or_award": "Bachelor of Science in Environmental Earth Systems Science"
  },
  "raw": {
    "evidence_snippet": "Bachelor of Science in Environmental Earth Systems Science programme accepts..."
  },
  "source_refs": [
    {
      "source_id": "06567c85cd44c8a1",
      "source_url": "https://www.ntu.edu.sg/ase/admissions/undergraduate-programmes/..."
    }
  ],
  "evidence_refs": [
    {
      "evidence_id": "evidence__e12a9c",
      "claim_path": "/programme_catalog/0/name"
    }
  ],
  "retrieved_at": "2026-07-07T07:59:52Z"
}
```

第一批已完成范围：

1. 新增 `university_admissions_crawler/reports/structured_export.py`。
2. 在 `pipeline/output_writer.py` 中追加 `write_structured_outputs(data, output_dir / "structured")`。
3. 生成：
   - `structured/manifest.json`
   - `structured/institution.json`
   - `structured/sources.jsonl`
   - `structured/evidence.jsonl`
   - `structured/missing_fields.jsonl`
   - `structured/warnings.jsonl`
   - `structured/diagnostics.json`
   - `structured/records/programme_catalog.jsonl`
   - `structured/records/programme_catalog.csv`
4. 保留旧输出不变。

第一批已验收：

- fixture scan 会生成 `structured/manifest.json`。
- 即使没有 `programme_catalog`，也生成 manifest、sources、evidence、missing、diagnostics。
- `programme_catalog` 非空时生成 JSONL 和清洗版 CSV。
- `record_id` 稳定，不依赖当前行序。
- `sources.jsonl` / `evidence.jsonl` 能被 facts 通过 `source_id` / `evidence_id` join。
- `missing_fields.jsonl` 来自 `run.config["missing_reasons"]`，不从 report 文本解析。
- 旧 `result.json`、`report.md`、`programme_catalog.csv` 测试不变。

已新增和建议复跑测试：

```text
tests/test_structured_output.py
tests/test_programme_catalog_output.py
tests/test_report_cli.py
```

第一批边界：

- 不改 `AdmissionsData` schema。
- 不删除或移动旧输出。
- 不把 diagnostics 从 `run.config` 迁走。
- 不一次性为所有字段设计宽 CSV。
- 不在 extractor 内处理清洗输出逻辑。

第二批已完成范围：

- 输出 `application_periods.jsonl`。
- 输出 `fees.jsonl`。
- 输出 `english_requirements.jsonl`。
- 输出 `accepted_qualifications.jsonl`。
- 输出 `required_documents.jsonl`。
- 输出 `scholarships.jsonl`。
- 输出 `contacts.jsonl`。
- 输出 `programmes_legacy.jsonl`，明确 legacy 语义。

第三批已完成范围：

- batch 级合并输出：
  - `structured/all_programme_catalog.jsonl`
  - `structured/all_missing_fields.jsonl`
  - `structured/all_sources.jsonl`
- 多校去重辅助字段已进入 structured JSONL：
  - 每行保留 stable `university_id`。
  - source row 提供 `normalized_source_host` 和 `normalized_source_path`。
  - programme catalog / legacy programme row 提供 `normalized_programme_name_key`。
- schema version migration notes 已写入 README、PROJECT_MAP 和 VERSION_NOTES。

schema migration / compatibility policy：

- 当前 schema version 是 `structured-output-v1`。
- 本阶段只做 additive 输出：保留 legacy `result.json`、`report.md`、root
  `programme_catalog.csv`，新增或扩展 `structured/` 文件。
- 下游清洗应优先按 `schema_version` 分支读取；不能把旧 `result.json` 当作稳定清洗 schema。
- `structured/facts.jsonl` 是统一事实入口；record-specific JSONL 是清洗主表；diagnostics 不写入 facts。
- batch `all_*.jsonl` 是 per-university structured JSONL 的合并，不代表重新去重、补全或改写事实。
- 任何破坏性字段删除、重命名或语义改变都必须升级 schema version，并保留 migration notes 与 focused tests。

### P1：继续找 NTU 公开 catalog API

目标：

- 找到真正返回 programme rows 的公开 JSON/API。
- 验证是否属于 Sitecore/search/listing/Next data/GraphQL/Algolia/ElasticSearch。
- 若存在可枚举分页或筛选参数，接入 API extractor，而不是依赖 HTML fallback。

验收：

- NTU dynamic shell -> captured official JSON -> `programme_catalog` rows。
- `api_response_count > 0`。
- `api_accepted_row_count > 0`。
- `programme_catalog_summary.api_to_csv_ratio` 不再是 0。
- 如果 API 总数可见，pagination/filter diagnostics 能解释完整性。

### P1：HTML False-Positive Cleanup

目标：

- 继续收紧 long prose、second-major 说明、unknown table variant。
- rejected row reason 进入可审计 ledger。

验收：

- `BEng SCE`、`BEng Design Stream` 这类 course-table `Open to` 列不进入 CSV。
- 长篇 overview 不进入 `name`。
- rejected row 有 reason 和 source。

### P1：NTU/HASS Segment Fallback

目标：

- API 不可用时，对 HASS-like 段落式目录做较可靠 fallback。
- 识别 `School -> Degree -> Majors/Specialisations` 层级。

验收：

- HASS-like fixture 能拆出多条 degree rows。
- majors 进入 `specialisations_or_majors`。
- `faculty_or_school` 明显减少 unknown。

### P2：API Adapter Layer

目标：

- 为高价值、可复现结构补 adapter registry。
- 支持 Sitecore、Next.js data、GraphQL、Algolia、ElasticSearch 等结构。

验收：

- 没有 adapter 时通用 extractor 继续工作。
- adapter 命中时 diagnostics 可追踪 `api_adapter_used`。
- adapter 不绕过 safe capture 边界。

### P2：输出契约与兼容层治理

状态：README / PROJECT_MAP / VERSION_NOTES 已同步 `structured/` records、batch `all_*.jsonl`
输出和 schema migration notes。

目标：

- 把 legacy output、structured output、diagnostics output 的边界写清楚。
- 稳定 schema version 和 compatibility policy。

验收：

- README / PROJECT_MAP / VERSION_NOTES 同步 structured output records。已完成。
- schema migration / compatibility policy 已成文。
- schema 变动有 focused tests。
- 不再用旧 `outputs/` 证明当前行为；旧 outputs 只能当历史样例。

## 下一步推荐执行顺序

1. 继续 NTU public catalog API discovery。
2. 继续 HTML false-positive cleanup 和 NTU/HASS fallback。
3. 评估是否把 `institution` scalar facts 纳入统一 fact envelope；如果做，必须作为 schema
   additive slice，并补 focused tests。

每个 slice 的交付要求：

- 修改前先加或更新 focused tests。
- 自己跑 focused tests。
- focused tests 通过后跑完整 `pytest -q`。
- 跑 `git diff --check`。
- 汇报：
  - 改动。
  - 结果。
  - 风险。
  - 未覆盖项。

## 常用验证入口

完整验证：

```bash
.venv314/bin/python -m pytest -q
git diff --check
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

structured output records focused tests：

```bash
.venv314/bin/python -m pytest -q \
  tests/test_structured_output.py \
  tests/test_programme_catalog_output.py \
  tests/test_report_cli.py
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
