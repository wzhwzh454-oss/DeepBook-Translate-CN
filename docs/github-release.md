# GitHub 发布说明

以下内容用于创建公开仓库。README 会把用户引导至面向 AI 助手的 ZIP 安装说明，不假设所有工具使用同一个技能目录。仓库所有者确定后，请检查公开 ZIP 的根目录是否直接包含 `SKILL.md`。

仓库名称、项目简介和主题标签见 [`github-about.md`](github-about.md)。

## 公开试译证据

README 中的演示来自 Thorstein Veblen《The Theory of the Leisure Class》Oxford World's Classics 版第四章的真实试译，章节标题为“Conspicuous Consumption”（`炫耀性消费`）。核验范围是 PDF 第 86–106 页，共 56 个正文段落、约 8,954 词。运行依次完成摄入、提纲、术语规划、意义抽取、中文写作、回源审计和章节整合，总控最终返回 `all_done: true`。

公开材料只包含一条原文短句、对应中文译文和四个术语（`conspicuous consumption`、`conspicuous waste`、`instinct of workmanship`、`pecuniary comparison`）。短摘和译文已与修订后的第四章定稿核对；这条第 56 段句子和四个术语译名在本轮没有改变。完整源 PDF、整章原文和整章译文留在本地试验工作区，不属于发布资产。`assets/demo-ch04-conspicuous-consumption.svg` 是根据同一条短摘和术语片段制作的自包含展示图。

可复制的短摘、译文、术语表、实测耗时、验证状态和限制见 [`demo-evidence.md`](demo-evidence.md)。已核验的第四章页段使用文本提取，未使用 OCR。完整 PDF 摄入在第 1 页遇到不可读图片；当时本机缺少 Tesseract/tessdata，因此扫描 PDF、复杂版面、表格、公式和图片尚未验证。Word 可用于 DOCX 复核，当时没有 LibreOffice。这组证据只说明单章流程能够运行，不代表整书验收。

本地试验没有创建 GitHub 仓库、远程地址、提交、推送或发布标签。

在 [`release-checklist.md`](release-checklist.md) 所述的长篇端到端试验完成前，不要创建 GitHub 正式发行版标签。仓库可以先以 `3.1.0-dev` 元数据公开；长篇试验通过后再创建 `3.1.0` 发行版。
