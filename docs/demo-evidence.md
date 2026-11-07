# 第四章试译证据

## 试验范围

这是一次真实的单章试译，使用 Thorstein Veblen 的 *The Theory of the Leisure Class*（Oxford World's Classics 版）。核验的是 PDF 第 86–106 页正文，共 56 段、约 8,954 词。Oxford 编者导言、注释、封面及其他编辑材料均未纳入。

第四章译稿经独立中文冷读、局部可读性修订和第二轮冷读。最终回源审计通过 24 项检查，章节门禁通过 4 项检查。最终 DOCX 共 18 页，已逐页渲染并目视检查。

## 原文短摘

第 56 段：

> An article may be useful and wasteful both, and its utility to the consumer may be made up of use and waste in the most varying proportions.

## 对应译文

> 一件物品可以同时有用又浪费，它对消费者的效用，可以由使用和浪费按各种比例组成。

## 术语表片段

| 原词 | 中文译名 |
| :-- | :-- |
| `conspicuous consumption` | 炫耀性消费 |
| `conspicuous waste` | 炫耀性浪费 |
| `instinct of workmanship` | 做工本能 |
| `pecuniary comparison` | 金钱比较 |

## 实测耗时

| 阶段 | 墙钟耗时 | 范围 |
| :-- | --: | :-- |
| 第 7 节回源审计 | 597.654 秒 | 仅一个审计片段 |
| 最终章节门禁 | 0.670 秒 | 可读性修订后 |
| Word 排版刷新与 PDF 导出 | 8.413 秒 | 18 页 DOCX |

摄入、提纲、术语规划、意义抽取和中文写作均未计时，不据此推算端到端耗时。

## 限制

- 本次核验的第四章页段含可抽取文本，试译未使用 OCR。
- 完整 PDF 摄入在第 1 页遇到不可读图片；当时本机缺少 Tesseract/tessdata，流程因此暂停。
- 扫描页、复杂版面、表格、公式及图片提取尚未在本次试验中验证。
- DOCX 使用 Microsoft Word 刷新域、重新分页、导出 PDF 预览并检查全部 18 页；当时没有 LibreOffice。
- 本结果证明单章流程能够运行，不代表整书验收。稳定发布 `3.1.0` 前仍需完成 100–200 页端到端试验。

原书 PDF、整章原文和整章译文保留在本地试验工作区，不属于公开发布材料。
