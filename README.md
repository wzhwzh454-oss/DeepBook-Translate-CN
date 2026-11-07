# book-translator

把一本 400 页的书译完并整理成中文研读版，而不是只翻译一个段落。

本项目面向中文读者，操作指南和译文说明以中文呈现。为便于核对，原书引文、术语原词、文件名、字段名和命令会保留原样。

## 试译示例：第四章《炫耀性消费》

这是一次真实的单章试译运行，不是凭记忆补写的示例。输入是 Thorstein Veblen《The Theory of the Leisure Class》Oxford World's Classics 版；本次核验范围为 PDF 第 86–106 页，共 56 个正文段落、约 8,954 词。流程按摄入、提纲、术语规划、意义抽取、中文写作、回源核验和章节整合顺序完成。Oxford 编者导言、注释、封面及其他编辑材料被排除。

整章定稿经独立人工冷读、局部修订和复读；最终覆盖审计 24 项通过，整章门禁 4 项通过。下面只展示一条短摘和四个术语，不包含完整原文或整章译文。

**原文短摘（第 56 个正文段落）**

> An article may be useful and wasteful both, and its utility to the consumer may be made up of use and waste in the most varying proportions.

**对应译文**

> 一件物品可以同时有用又浪费，它对消费者的效用，可以由使用和浪费按各种比例组成。

**术语表片段**

| 原词 | 中文译名 |
| :-- | :-- |
| `conspicuous consumption` | 炫耀性消费 |
| `conspicuous waste` | 炫耀性浪费 |
| `instinct of workmanship` | 做工本能 |
| `pecuniary comparison` | 金钱比较 |

**已记录的局部耗时**

| 阶段 | 墙钟耗时 |
| :-- | --: |
| 摄入与边界核验 | 未记录 |
| 提纲 | 未记录 |
| 术语规划 | 未记录 |
| 意义抽取 | 未记录 |
| 中文写作 | 未记录 |
| 回源核验（第 7 节审计片段） | 597.654 秒（仅片段） |
| 最终修订后的整章门禁 | 0.670 秒 |
| 最终 DOCX 域刷新、重新分页、PDF 导出 | 8.413 秒 |

摄入、提纲、术语规划、意义抽取和中文写作等早期阶段当时没有计时，因此不补估整章端到端耗时。第四章页段是可抽取文本，本次未使用 OCR；完整 PDF 摄入在第 1 页的不可读图片处因本机缺少 Tesseract/tessdata 被阻断，所以本次只对已验证的第 86–106 页正文试译。扫描页、复杂版面、表格、公式和图片处理能力未在本次试译中验证。DOCX 使用 Microsoft Word 刷新域并导出，最终 18 页 PNG 已逐页检查；本机未提供 LibreOffice。这个演示只证明第四章试译流程可运行，不代表整书验收。

![第四章试译展示图](assets/demo-ch04-conspicuous-consumption.svg)

## 它解决什么问题

- **术语跨章一致**：核心术语进入全书台账，沿用已锁定译名并记录释义。
- **章节衔接不断裂**：每章交付摘要、未决问题和下一章交接信息，整合时回看全书脉络。
- **中断可续跑**：工作区保存摄入报告、状态账本、任务单和产物，重新运行总控即可从断点继续。

## 安装

技能通常由 AI 助手安装，不要求用户把 ZIP 当作可执行程序运行。将 GitHub ZIP 或本地 ZIP 交给助手时，请让它按[面向 AI 助手的 ZIP 安装说明](docs/agent-zip-install.md)检查、解压、定位并验证 `SKILL.md`。不同工具的技能目录由各自宿主决定，不能凭经验猜路径。

### ZIP 安装路径

```text
ZIP 文件
  -> 解压到临时目录
  -> 找到直接包含 SKILL.md 的仓库根目录
  -> 复制/移动为 <宿主实际 skills 目录>/book-translator/
  -> 确认 <宿主实际 skills 目录>/book-translator/SKILL.md
  -> 检查技能入口并运行编译检查和回归冒烟测试
  -> 重新载入宿主的技能索引后再向用户报告安装成功
```

不要把 ZIP 文件本身、外层下载目录，或 `book-translator/book-translator/` 这样的双层目录当成安装结果。没有技能目录写权限时，AI 助手应如实说明限制并保留解压路径，不得声称已经安装。

## 支持范围

输入格式为文本型 PDF、EPUB、Markdown 和 TXT；支持英语、德语、法语、西班牙语、俄语和日语。输出为中文 DOCX、Markdown 和核心术语表。开始每本书前，AI 助手会按当前宿主能力选择连续处理、在当前对话中续跑，或由用户携带交接材料开启新对话，并先用日常语言说明需要用户配合的事项。

扫描 PDF、复杂表格、公式和图片需要宿主提供 OCR 或页面检查能力；无法读取的内容会被报告，不会被默认为已翻译。它适合整书研读，不适合单篇论文的快速润色，也不适合不做核验的纯机翻速读。

## 本地验证

```text
py -3 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" tests/run_all.py
& ".\.venv\Scripts\python.exe" -m compileall -q scripts tests
```

PDF 摄入需要 `PyMuPDF`，DOCX 汇编需要 `python-docx`。可选的 Word 排版复核脚本还需要 Windows Word 和 `pywin32`；详见[架构说明](docs/architecture.md)。

## 目录

- `SKILL.md`：技能入口、触发描述和运行契约
- `prompts/`：规划、抽取、写作、核验与交接提示词
- `scripts/`：摄入、总控、检查、术语和导出脚本
- `references/`：保真、术语、运行和交付约束
- `tests/`：回归测试
- `docs/`：公开架构和发布清单

## 许可证

[MIT 许可证](LICENSE)
