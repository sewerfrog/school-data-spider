# Fixture smoke run 摘要

## 原始位置

上一阶段 fixture smoke run 输出曾在：

```text
/tmp/uac-smoke-run/
```

当时文件包括：

```text
/tmp/uac-smoke-run/result.json
/tmp/uac-smoke-run/report.md
/tmp/uac-smoke-run/report.zh.md
/tmp/uac-smoke-run/sources/*.json
/tmp/uac-smoke-run/sources/*.txt
```

## 本轮状态

本轮执行 `find /tmp/uac-smoke-run -maxdepth 3 -type f` 时没有发现可读文件，因此没有复制到项目内的原始 fixture JSON/source 文件。

## 上一阶段已确认统计

- sources：14
- evidence：16
- discovered_categories：14
- warnings：
  - `needs_manual_check` at `/run/diff`
  - `conflict` at `/conflicts/application_deadline`
  - `stale_page` for `https://fixture.test/old-deadlines.html`
- missing evidence warnings：无

## 说明

这些 fixture 输出只代表本地测试站点，不是真实大学官网数据。真实 NUS 采集结果见：

```text
temp_imports/previous-session-archive/nus-live-programmes/
outputs/nus-live-programmes/
```
