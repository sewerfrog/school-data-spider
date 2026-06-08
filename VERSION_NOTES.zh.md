# 版本说明：University Admissions Crawler MVP

版本日期：2026-06-04  
项目目录：`/Users/sewerfrog/work/智能选校/school-data-spider`

## 1. 当前版本定位

本项目是一个“证据优先”的大学官网招生与专业信息采集 MVP。它的目标不是生成录取判断，而是从官方网页、公开 JSON/API、PDF 或本地 fixture 中采集可追溯的信息，并输出结构化 JSON、Markdown 报告、source 文件和 evidence 记录。

当前实现重点：

- 核心流程仍保持 dependency-light：fixture、schema、证据校验、报告、基础抽取不依赖浏览器、PDF 解析器、LLM 或外部服务。
- Live HTTP、Playwright browser、pypdf PDF 解析是显式开启的可选能力。
- 所有非 `unknown` 字段都应有 `claim_path` 对应的 `EvidenceItem`。
- 抓取失败、PDF 失败、可选依赖缺失、冲突、过期、证据缺失等情况进入 warnings，不编造招生事实。
- 当前已经能跑本地 fixture、普通 live HTTP、可选 browser live、可选 PDF、公开 JSON/API source、批量学校配置，以及单 URL `--auto` live 扫描。
- 当前新增了主内容清洗、核心字段覆盖率诊断、source strategy 诊断、核心字段补抽取。真实官网上的抽取质量仍取决于页面结构；复杂专业体系、复杂费用表、PDF 表格还不是生产级。

## 2. 已实现能力

### 2.1 Fixture / 离线端到端流程

当前 CLI 可以在本地 fixture 站点上执行完整流程：

1. 从本地 fixture 根目录和 seed URL 开始。
2. 在 `max_pages` / `max_depth` 限制内发现链接。
3. 对页面分类：本科招生、国际申请要求、申请截止日期、资格要求、专业列表、先修要求、费用、奖学金、签证、住宿、联系方式等。
4. 从 HTML、fixture PDF、JSON fixture 中抽取可证据化字段。
5. 生成 `result.json`、`report.md`、`sources/*.json`、`sources/*.txt`。
6. 如果提供历史结果，可记录 source hash 和字段值变化。

### 2.2 Live HTTP 与 Browser 抓取

当前已有两个 live fetcher：

- `LiveHTTPFetcher`：基于 Python 标准库 `urllib`，适合普通静态 HTML、JSON、PDF URL。
- `PlaywrightBrowserFetcher`：通过可选 `playwright` 依赖抓取 JS 渲染页面，并捕获页面加载中的 JSON/API 响应 URL。

CLI 开关：

```bash
--auto
--enable-live-network
--enable-browser
--browser-wait-until domcontentloaded|load|networkidle|commit
--browser-headed
--timeout-seconds
```

`--auto` 用于“只提供一个大学招生入口 URL”的场景。它会开启 live HTTP 抓取，并从 URL 推断 allowed domain。对于 JS 渲染页面，仍建议显式使用 `--enable-browser`。

注意：browser 模式需要安装 `.[browser]` 并执行 `playwright install chromium`。如果环境未安装 Playwright，结果会包含 `optional_dependency_missing` warning，而不是崩溃。

### 2.3 JSON/API source

当前新增了 `SourceType.JSON`。JSON source 的处理包括：

- 通过 `application/json`、`.json` URL、browser network response 识别。
- 保存 JSON source 到 `sources/`。
- 从常见字段中抽取结构化信息，例如：
  - `programmeName`
  - `applicationDeadline`
  - `tuitionFee`
  - `requiredDocuments`
- evidence snippet 使用 JSON 对象片段。

这只是公开 JSON/API 的保守抽取，不会处理需要登录、token 或个人信息的申请系统。

### 2.4 PDF 解析

当前有两类 PDF extractor：

- `FixturePDFExtractor`：用于 fixture 文本 PDF，支持页码标记。
- `PypdfPDFExtractor`：可选真实 PDF parser，使用 `pypdf`，通过 `--enable-pdf` 开启。

限制：

- 真实 PDF 目前主要提取文本。
- 尚未实现 `pdfplumber` 级别的表格结构解析。
- prospectus 中复杂表格仍可能需要后续专项抽取规则。

### 2.5 HTML 表格、主内容清洗与页面文本

HTML fetcher 会在转文本前将 `<table>` 转成行列文本，避免费用表、要求表完全丢失。但当前仍是轻量文本化，不是完整 DOM/table schema parser。

当前也会在 HTML 转文本前优先抽取 `main`、`article`、`role=main`、常见 content 容器，并剥离 `nav`、`header`、`footer`、`aside`、cookie/banner/search/menu/sidebar 等常见噪声。这减少了 NTU 这类全站导航污染导致的分类和字段抽取误判。

### 2.5.1 核心字段补抽取

当前 pipeline 不再完全依赖“单页面单分类”。对于非 irrelevant 页面，主分类抽取之后还会补充尝试以下核心字段：

- application periods / deadlines
- English requirements
- fees
- scholarships
- contacts
- programmes

这解决了真实官网常见情况：一个招生页面同时包含申请周期、英语要求、费用、专业和联系方式。

### 2.5.2 Coverage 与 source strategy 诊断

当前 `result.json` 的 `run.config` 会记录：

- `coverage`：本科核心字段 found/missing、覆盖比例。
- `source_strategy`：每个 source 的粗分类，例如 `html_page`、`pdf_document`、`json_api`、`application_portal`、`blocked_or_challenge`、`irrelevant`。
- `source_strategy_summary`：各 source strategy 的数量。

`report.md` 也会显示 `Core Field Coverage` 和 `Source Strategy`。这用于解释为什么 `overall confidence` 可能是 medium，但某些字段仍未覆盖。

### 2.6 多学校配置与批量输出

当前支持 JSON 配置批量扫描：

```text
configs/universities.example.json
```

配置字段包括：

- `id`
- `name`
- `seed_urls`
- `allowed_domains`
- `allowed_hosts`
- `mode`
- `max_pages`
- `max_depth`

批量运行后，每所学校输出到：

```text
outputs/batch/<university-id>/result.json
outputs/batch/<university-id>/report.md
outputs/batch/<university-id>/sources/
```

如果配置里没有写 `allowed_domains`，当前批量扫描会从 seed URL 推断官方域名。

### 2.7 分类器修正

已修正一个真实网页常见问题：很多大学页面的全站导航会包含 `alumni`、`news`、`giving`、`staff`、`jobs` 等词。旧分类器会因此把真实招生页误判为 `irrelevant`。当前分类器会让强招生信号优先，例如：

- `/admissions/`
- `undergraduate admissions`
- `admission guide`
- `international qualifications`
- `tuition fees`
- `scholarships`
- `undergraduate programmes`

已用 NTU 已保存 source 做过回归验证：旧 NTU source 上，`irrelevant` 页面可从 24 个降到 4 个，更多页面进入 `international_requirements`、`fees`、`scholarships`、`housing`、`programme_list` 等类别。

## 3. 当前产物

### 3.1 Fixture 产物

运行 fixture smoke 会生成：

```text
result.json
report.md
sources/*.json
sources/*.txt
```

fixture 中包含 HTML、PDF-like fixture、JSON/API fixture、HTML 表格 fixture，用于验证多 source 类型。

### 3.2 NUS 既有真实官网专业信息产物

已有 NUS 官方专业信息产物：

```text
outputs/nus-live-programmes/
```

文件：

```text
outputs/nus-live-programmes/result.json
outputs/nus-live-programmes/programmes.csv
outputs/nus-live-programmes/report.zh.md
outputs/nus-live-programmes/report.md
outputs/nus-live-programmes/sources/official-source-index.md
```

统计：

- 官方来源页：14 个
- OAM 招生 A-Z 入口：28 个
- 结构化专业/主修记录：85 条
- 特殊项目记录：6 条
- CSV 数据行：91 条记录 + 表头

重要说明：这份 NUS 产物仍是一次性官方来源结构化产物，不是当前通用 crawler 自动稳定复现出来的完整结果。当前通用 pipeline 已支持 browser/config/PDF/API，但还没有达到自动复现该 NUS 产物全部专业分类的水平。

### 3.3 NTU 试跑产物

当前已有 NTU 试跑结果：

```text
outputs/batch/ntu/result.json
outputs/batch/ntu/report.md
outputs/batch/ntu/sources/
```

旧结果抓到 29 个 HTML source，但因为分类器被全站导航负面词污染，只有 1 条 evidence。分类器修正后，使用旧 source 离线重分类可明显改善类别覆盖和 evidence 数量。不过 live 重新抓取需要本地安装 Playwright；如果没装，会得到 `optional_dependency_missing`。

NTU 当前剩余问题：

- 费用、奖学金、住宿等抽取仍会受到导航文本污染。
- 专业抽取仍是粗粒度 regex，不能稳定区分 degree、major、minor、second major、special programme。
- 申请入口 `admissions.ntu.edu.sg` 可能连接关闭或需要特殊处理。
- `application period` 区间格式、`closing date on ...` 等写法尚未完整覆盖。

## 4. 如何运行

### 4.1 Python 环境

项目要求 Python 3.11+。本机已确认可用：

```bash
/opt/homebrew/bin/python3.14
```

推荐：

```bash
cd /Users/sewerfrog/work/智能选校/school-data-spider
/opt/homebrew/bin/python3.14 -m venv .venv314
source .venv314/bin/activate
python -m pip install -U pip
python -m pip install -e '.[dev]'
```

### 4.2 Fixture 端到端运行

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --output-dir /tmp/uac-smoke \
  --max-pages 30 \
  --max-depth 3
```

### 4.3 Live HTTP

```bash
python -m university_admissions_crawler.cli https://www.example.edu/admissions \
  --enable-live-network \
  --output-dir outputs/example-live-test \
  --allowed-domain example.edu \
  --max-pages 20 \
  --max-depth 2
```

### 4.4 Browser live

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium

python -m university_admissions_crawler.cli https://www.ntu.edu.sg/admissions/undergraduate \
  --enable-browser \
  --output-dir outputs/ntu-browser-test \
  --allowed-domain ntu.edu.sg \
  --browser-wait-until domcontentloaded \
  --timeout-seconds 45 \
  --max-pages 30 \
  --max-depth 2
```

### 4.5 PDF

```bash
python -m pip install -e '.[pdf]'

python -m university_admissions_crawler.cli https://www.example.edu/admissions/prospectus.pdf \
  --enable-live-network \
  --enable-pdf \
  --output-dir outputs/example-pdf-test \
  --allowed-domain example.edu \
  --max-pages 1 \
  --max-depth 0
```

### 4.6 批量配置

示例配置：

```text
configs/universities.example.json
```

运行：

```bash
python -m pip install -e '.[browser,pdf]'
python -m playwright install chromium

python -m university_admissions_crawler.cli \
  --config configs/universities.example.json \
  --output-dir outputs/batch \
  --browser-wait-until domcontentloaded \
  --timeout-seconds 45 \
  --enable-pdf
```

## 5. 如何验证

### 5.1 编译检查

```bash
python -m compileall -q university_admissions_crawler tests
```

### 5.2 pytest

```bash
python -m pytest -q
```

如果当前环境没有安装 `pytest`，先运行：

```bash
python -m pip install -e '.[dev]'
```

### 5.3 当前已做过的验证

在 Python 3.14 下已做过：

- `compileall` 通过。
- 使用无 pytest 的 stdlib direct runner 跑过 65 个 `test_` 函数，通过。
- fixture CLI 跑通，且 JSON/API、HTML table、PDF fixture 进入输出。
- 使用已保存的 NTU source 验证分类器修正有效。

说明：标准 `pytest -q` 是否可直接运行取决于当前虚拟环境是否已安装 `pytest`。

## 6. 当前限制

1. **真实官网抽取仍不是生产级**  
   抓到网页不等于能高质量抽取。当前专业、费用、日期、奖学金等 extractor 仍偏规则/fixture 风格。

2. **NUS 完整专业产物还不能由通用 pipeline 稳定复现**  
   `outputs/nus-live-programmes/` 是一次性官方来源结构化产物。当前 pipeline 有 browser/config/API/PDF 基础，但还没有专门的 NUS 专业体系抽取器。

3. **Browser 抓取依赖本地 Playwright 环境**  
   没装 `playwright` 或没安装 Chromium 时，browser 模式会返回 `optional_dependency_missing`。

4. **WAF/anti-bot/portal 页面不可保证稳定**  
   例如申请 portal、WAF challenge、连接关闭、cookie banner、长轮询页面都可能导致 fetch warning 或抓到无效内容。

5. **Confidence 不是覆盖率指标**  
   当前 `overall confidence` 主要反映已抽取字段的证据/冲突状态。它不表示申请周期、英语要求、费用、专业等字段已经完整覆盖。

6. **中文报告尚未通用化**  
   通用 pipeline 当前只输出英文 `report.md`。NUS 的 `report.zh.md` 是既有派生产物，不是通用 renderer 输出。

7. **定时任务尚未实现**  
   当前只有 `--previous-result` 增量 diff；没有 scheduler、来源失效监控、专业新增/删除专项报告。

## 7. 下一版本方向

按当前真实进度，建议下一步优先级：

1. **增强 DOM 级主内容与表格解析**  
   当前已有轻量主内容清洗；下一步应从 regex 清洗升级到更稳的 DOM/table section 提取，减少复杂 CMS 和 mega menu 的残留污染。

2. **增强专业抽取器**  
   区分 degree programme、major、second major、minor、special programme，并支持卡片、列表、表格、JSON API。

3. **增强日期与申请周期抽取**  
   当前已支持部分 `Application Period | start - end`、`closing date`、`deadline` 写法；下一步应覆盖多轮申请、多申请人群/资格组日期和非英文月份格式。

4. **增强费用和奖学金抽取**  
   当前可抽取简单金额和表格文本；下一步应稳定结构化 applicant group、citizenship、subsidy、tuition grant、academic year、年度/学期费用。

5. **增强 PDF 表格解析**  
   在 `pypdf` 文本基础上增加 `pdfplumber` 或同类表格解析，面向 prospectus prerequisites。

6. **将 NUS/NTU 变成可重复学校 adapter**  
   为特定学校加入配置和抽取 profile，但仍保持通用 schema 和证据合同。

7. **增加中文/英文统一报告 renderer**  
   让通用 pipeline 同时输出 `report.md` 和 `report.zh.md`。

8. **增加业务级 diff**  
   在 source hash 和字段变化之外，增加专业新增/删除、费用变化、日期变化、来源失效等报告。

## 8. 文件索引

核心代码：

```text
university_admissions_crawler/cli.py
university_admissions_crawler/config_loader.py
university_admissions_crawler/config.py
university_admissions_crawler/crawler/
university_admissions_crawler/classifier/page_classifier.py
university_admissions_crawler/evidence/
university_admissions_crawler/extractor/
university_admissions_crawler/pipeline/run_university_scan.py
university_admissions_crawler/reports/render_report.py
```

示例配置：

```text
configs/universities.example.json
```

测试：

```text
tests/test_*.py
tests/fixtures/mini_university_site/
```

真实/试跑输出：

```text
outputs/nus-live-programmes/
outputs/batch/ntu/
```
