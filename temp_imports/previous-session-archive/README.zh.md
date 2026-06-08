# 临时归档：之前未集中放入项目的总结和采集内容

归档日期：2026-06-03  
位置：`temp_imports/previous-session-archive/`

## 说明

用户要求：“把之前不在项目中的总结和爬取内容，临时放到项目中来”。

当前检查结果：之前提到的临时目录 `/tmp/uac-smoke-run` 在本轮环境中已经没有可读文件，因此本目录做了两件事：

1. 将项目中已经存在的 NUS 真实官网采集产物复制到本临时归档目录，便于集中查看。
2. 根据上一轮会话中已经确认的信息，重建了 fixture smoke run 摘要、NUS live 采集摘要、上下文交接摘要。

如果之后 `/tmp/uac-smoke-run` 恢复或重新生成，可以再把原始临时文件补充进来。

## 目录结构

```text
temp_imports/previous-session-archive/
  README.zh.md
  context/
    handoff-summary.zh.md
  fixture-smoke-run/
    summary.zh.md
  nus-live-programmes/
    result.json
    programmes.csv
    report.zh.md
    report.md
    sources/official-source-index.md
    summary.zh.md
```

## 当前包含内容

### NUS 真实官网专业采集

来源于项目现有正式产物：

```text
outputs/nus-live-programmes/
```

已复制到：

```text
temp_imports/previous-session-archive/nus-live-programmes/
```

### Fixture smoke run 摘要

原始临时目录曾为：

```text
/tmp/uac-smoke-run/
```

但本轮检查时该目录无可读文件，因此只保留已确认摘要，不声称恢复了原始 JSON/source 文件。

### 上下文/交接总结

将上一轮关于项目状态、实现范围、NUS WAF 限制、产物路径等信息整理为中文 handoff 文档。
