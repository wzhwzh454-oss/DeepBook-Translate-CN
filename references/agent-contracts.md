# 按角色装载与检查接口（书籍深度翻译）

主编排器沿用 SKILL.md 的标准，宿主能力与本次路由记录在工作区 `runtime-strategy.json`。各角色遵循“最小装载”原则，只读本轮必需文件；上下文隔离由宿主路由实现，不假定所有宿主都能创建新上下文。

## 角色最小输入与交付契约

| 角色 | 本轮读取材料 | 核心输出及产物 | 验收与质检命令 |
| :--- | :--- | :--- | :--- |
| **材料摄入与分章** | 原始书籍（PDF / MD / TXT） | `book.json`、`chapters/chXX/source-numbered.md`、第1章启动 Prompt | 脚本自动执行 `intake_book.py` 内部校验 |
| **单章大纲与术语** | `P1-chapter-outline.md`、`P1.5-term-plan.md`、`source-numbered.md`、`global-term-ledger.json` | `outline.md` -> `outline.json` 与 `term-plan.json` | 运行 `check_outline.py` 转换为 JSON，运行 `run_stage_checks.py --stage extract` 验证 |
| **分节意义抽取** | `P7-points.md`（十二字段清单）、`P2H-teaching-units.md`、`P3-extract-sheet.md` 任务单 | `{k}-points.md`、`{k}-teaching-units.json` | 运行 `run_stage_checks.py --stage extract --workspace <章节目录> --k <k>` |
| **独立中文写作** | `P2H-write.md`、`P2H-expansion.md`、`P3-write-sheet.md` 任务单（**写作者绝不读源语言原句**） | `{k}-revision.md` -> 拆分出 `{k}-final.md` | 运行 `validate_revision.py` 拆出 final，运行 `run_stage_checks.py --stage draft --workspace <章节目录> --k <k>` |
| **真实回源核验** | `P8-coverage.md`、本节 `source-numbered.md`、`{k}-points.md`、`{k}-final.md` | `coverage-{k}.md`；必要时打单句微编辑补丁 | 运行 `run_stage_checks.py --stage audit --workspace <章节目录> --k <k>` |
| **全章平滑与整合** | `P5-integrate.md`、拼合后全章初稿、术语计划 | `chapter-final.md`（唯一规范定稿；旧版遗留的 `merged-final.md` 仅在 `chapter-final.md` 缺失时回退，两者并存且内容不同即判歧义违规） | 运行 `run_stage_checks.py --stage chapter --workspace <章节目录>` |
| **跨章交接生成** | `prompts/P9-handover-template.md`、本章 `chapter-final.md`、本章大纲与术语 | `handover-to-ch{k+1}.prompt.md`、增量更新 `global-term-ledger.json` | 运行 `generate_handover.py --workspace <全书工作区> --chapter <k>` |
| **全书终局汇编与交付质检** | 全书所有章节 `chapter-final.md`、全局术语台账、脉络账本 | `output/[slug]-全文研读稿.md`、`.docx`、全书术语与概念台账及质检报告 | 运行 `merge_book.py --workspace <全书工作区>` 或 `run_stage_checks.py --stage deliver` |

---

## 分阶段机械入口（Stage Checks）

命令统一使用技能内嵌 Python 解释器。`<skill>` 为技能根目录绝对路径，`<chapter_dir>` 为单章工作区绝对路径（例如 `.../chapters/ch01`），含空格时整体加双引号：

0. **断点续传（先查后做）**：
   ```powershell
   <python> <skill>/scripts/chapter_status.py --workspace <chapter_dir>
   ```
   只读；按产物与时间戳判定每节阶段，并打印下一条应执行的完整命令。任何会话接手、上下文重建后都先跑这一步，不要凭记忆重做已通过的阶段。

1. **大纲转换与校验**：
   ```powershell
   <python> <skill>/scripts/check_outline.py --outline <chapter_dir>/outline.md --numbered <chapter_dir>/source-numbered.md --out-json <chapter_dir>/outline.json
   ```

2. **抽取阶段检查 (extract)**：
   检查术语计划完整性、源段物理覆盖、讲解单元：
   ```powershell
   <python> <skill>/scripts/run_stage_checks.py --stage extract --workspace <chapter_dir> --k <k>
   ```

3. **初稿阶段检查 (draft)**：
   检查初稿格式规范、禁写套话、篇幅与可读性（独立写作者任务单物理隔绝源语言源句）：
   ```powershell
   <python> <skill>/scripts/run_stage_checks.py --stage draft --workspace <chapter_dir> --k <k>
   ```

4. **核验阶段检查 (audit)**：
   检查覆盖率达标、力度/模态反查（无擅自断言或弱化）与术语一致性（纯导航过渡句自动豁免）：
   ```powershell
   <python> <skill>/scripts/run_stage_checks.py --stage audit --workspace <chapter_dir> --k <k>
   ```

5. **整章整合阶段检查 (chapter)**：
   检查整章定稿合并完整性、消除跨节接缝：
   ```powershell
   <python> <skill>/scripts/run_stage_checks.py --stage chapter --workspace <chapter_dir>
   ```

6. **微编辑打补丁入口 (apply_patches)**：
   无论是针对单节文件 `{k}-final.md` 还是全章拼合稿，均可运行：
   ```powershell
   <python> <skill>/scripts/apply_patches.py --patches <补丁文件路径> --marked <目标文本路径> --out <输出路径> --profile v2
   ```

7. **全书终局交付质检 (deliver)**：
   全面验收全书章节完整性（防空章）、跨章术语一致性（防漂移）与残缺反查覆盖：
   ```powershell
   <python> <skill>/scripts/run_stage_checks.py --stage deliver --workspace <全书工作区根路径>
   ```
   或直接执行独立质检巡检：
   ```powershell
   <python> <skill>/scripts/merge_book.py --workspace <全书工作区根路径> --check
   ```

## 宿主路由与模型适配

先读取工作区 `runtime-strategy.json`。文件不存在时，在进入书籍生产动作前探测当前宿主并按 `references/full-book-runtime.md` 写入；上下文管理方式未公开时记录 `unknown`。总控负责确定性文件流和阶段门禁，AI 助手 负责语义判断、宿主委派与产物落盘。

| 模式 | 适用条件 | AI 助手 执行约定 |
| :--- | :--- | :--- |
| **A 子代理与磁盘协作** | 可派发无父历史的新上下文，且产物能落到当前工作区 | 写作或重核等重任务可委派；只给动作列出的 inputs，要求直接写入 expected_outputs。主 AI 助手 不回传整篇正文，不并行提交依赖顺序的术语账本。 |
| **B 单 AI 助手 磁盘流** | 有文件读写和脚本执行，但没有可用或获准的隔离代理 | 当前 AI 助手 逐动作读写磁盘文件；回复只保留阶段、结果和必要诊断，不将历史全文复制到上下文。 |
| **C 无工具文本流** | 当前宿主没有可用的本地读写或脚本工具 | 生成含当前阶段、最小材料、目标产物和下一动作的交接卡；只有无法在当前宿主持久化时才要求人工转移。 |

路由受当前宿主能力和任务边界约束。模式 A 不要求销毁子代理，也不创建用户侧新聊天。历史章节默认只通过 `book-continuity.json`、相关术语和必要的上一章结尾摘要衔接；不装载无关旧章节原文与长篇译文。抽取、审计按任务读取当前章节源文属于必要输入。

## 模型适配
- **抽取/核验角色**（P7、P8）：需要逐字引文与算子判断，使用最强的非流式或推理模型；推理型模型不必要求显式草稿，只要求最终严格输出行格式。
- **写作角色**（P2H）：优先在全新上下文运行；宿主无法隔离时当前 AI 助手 分阶段写作并回源核验；非推理模型保留“写前规划”私下步骤，推理型模型可内化。写作角色不需要审计脚本、术语台账全文或任何源语言。
- **脚本是唯一裁判**：行格式、`--out` 等参数名以 `scripts/*.py --help` 为准；提示词不得复述脚本未实现的保证。
- 换模型后先在单节上跑 `run_stage_checks --stage extract/draft/audit`，看 advisory 分布是否漂移，再放量。

全书持续执行以 full-book-runtime.md 与 `runtime-strategy.json` 为准。A/B 模式下交接文件由 AI 助手 在工作区自动消费；C 模式仅在无工具宿主下使用文本交接卡。全部章节完成后自动汇编，并检查实际输出。
