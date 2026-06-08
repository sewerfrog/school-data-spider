# 上一阶段上下文交接总结

## 项目状态

项目目录：`/Users/jax/project/school-data-spider`

已实现一个 evidence-first Python MVP 包：

```text
university_admissions_crawler/
  cli.py
  config.py
  crawler/
    discovery.py
    fetcher.py
    filters.py
    sitemap.py
  classifier/page_classifier.py
  evidence/
    provenance.py
    store.py
  extractor/
    schema.py
    html_extractor.py
    normalizer.py
    pdf_extractor.py
    llm_provider.py
  pipeline/run_university_scan.py
  reports/render_report.py
tests/
  test_*.py
  fixtures/mini_university_site/...
README.md
pyproject.toml
```

## 关键实现决策

- 核心运行时不依赖第三方包，主要使用 Python 标准库。
- fixture-first：先保证离线可重复端到端运行。
- live/browser/LLM/ScrapeGraph 能力作为可选接口或 guarded flags，默认 fail closed。
- 证据优先：非 unknown 字段必须有精确 claim-path evidence。
- 输出 warning，而不是编造无法确认的信息。
- warning 类型覆盖 conflict、stale page、missing evidence、fetch/parse/PDF failure、non-official source、ambiguous applicant group 等。

## 已验证事项

上一阶段已确认：

- `python3 -m compileall -q university_admissions_crawler tests` 通过。
- 使用标准库 runner 执行 tests 下函数，结果为 50/50 通过。
- `python3 -m pytest -q` 当时失败原因是环境未安装 pytest，而不是测试失败。
- 子代理 code review 给出 APPROVE。
- 当时项目不是 git repo。

## 用户需求演进

1. 用户先要求阅读 `/Users/jax/something/university-admissions-crawler-codex-prompt.md` 并讨论实现内容。
2. 后续通过 deep-interview 确认：
   - MVP handoff
   - no UI/backend
   - no admission decision
   - broad MVP
   - evidence precision first
   - 结构、crawl limit、依赖、LLM 策略、测试等可由助手自行决定
3. 用户要求直接运行并查看结果。
4. 用户指出“只有报告没有采集内容”“没有看到专业信息”。
5. 用户明确要求访问大学官网采集专业信息。
6. 因未给新大学 URL，按前序默认 NUS 执行真实官网专业采集。

## NUS 真实采集限制

尝试直接抓取：

```text
https://www.nus.edu.sg/oam/undergraduate-programmes
```

本地简单 urllib 返回 Incapsula/WAF challenge 页面，而不是正常专业页面内容。部分 NUS Bulletin 和院系页面也存在类似限制。

因此 NUS 产物说明为：

- 数据来源仍为官方页面 / NUS Bulletin / 院系官网。
- 但不是由当前 stdlib-only MVP crawler 自动完整抓取生成。
- 是在官方来源基础上进行结构化采集，并保留来源 URL 与证据摘要。

## 当前项目内正式产物

```text
outputs/nus-live-programmes/result.json
outputs/nus-live-programmes/programmes.csv
outputs/nus-live-programmes/report.zh.md
outputs/nus-live-programmes/report.md
outputs/nus-live-programmes/sources/official-source-index.md
VERSION_NOTES.zh.md
```
