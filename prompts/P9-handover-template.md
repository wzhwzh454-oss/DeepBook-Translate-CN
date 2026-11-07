# 任务交接：开始处理《{{BOOK_TITLE}}》第 {{NEXT_CHAPTER_NUM}} 章

## 1. 角色与运行约定
你正在协助我翻译和深度研读改写外文书籍《{{BOOK_TITLE}}》（作者：{{BOOK_AUTHOR}}）。
你必须加载并遵守技能 `book-translator`（位于 `{{SKILL_DIR}}`）的运行规程：
- 采用中文命题组织讲解，独立写作者不读源语言原句，从物理上杜绝翻译腔；
- 严格遵循源文段落物理编号（`[P1]`, `[P2]`...），保留作者归属、量词、否定辖域与模态；
- 真实回源清点承重项，以覆盖反查与证据短引核验语义完整性。

### 运行环境信息
- 技能根目录绝对路径：`{{SKILL_DIR}}`
- Python 解释器路径：`{{PYTHON}}`
- 全书工作区根路径：`{{WORKSPACE}}`
- 本次宿主运行策略：`{{WORKSPACE}}/runtime-strategy.json`（先读取；宿主变化时重新探测并更新）
- 当前处理章节：第 {{NEXT_CHAPTER_NUM}} 章（{{NEXT_CHAPTER_TITLE}}）
- 本章工作区目录：`{{CHAPTER_DIR}}`
- 本章源材料路径：`{{CHAPTER_DIR}}/source.md`
- 本章编号源文路径：`{{CHAPTER_DIR}}/source-numbered.md`

### 宿主路由、最小装载与接续
- 本书源语言：{{SOURCE_LANG}}。完整保留全部实质论述，用自然中文重组，额外解释单独标注。
- 按 `runtime-strategy.json` 选择 A/B/C。模式 A 的子代理只读当前动作 inputs 并直接写 expected_outputs；模式 B 由当前 AI 助手 逐阶段使用磁盘文件；模式 C 仅在无本地工具时生成有限交接卡。上下文政策未公开则保持 `unknown`，不得猜测。
- 默认不加载前序章节完整原文或长篇译文；只使用当前动作材料、相关术语及本提示提供的必要结论/末尾衔接。回源核验按任务读取当前章节原文。
- 实际缺漏和改义先修复；普通风格或篇幅提示不阻断。同一策略无效时缩小任务或重新抽取，不把内部问题交给用户。
- 本章完成后主 AI 助手 重新读取策略和磁盘断点，继续运行 orchestrate_book.py --workspace "{{WORKSPACE}}"，直至整书汇编交付。本提示是内部交接材料，不要求用户搬运；只有模式 C 无法持久化时才输出给用户。

---

## 2. 全书宏观背景与论证弧线（全书主旨与结构）
- **全书核心问题/要旨**：{{BOOK_THESIS}}
- **全书结构规划**：共 {{TOTAL_CHAPTERS}} 章，当前进度：已完成 {{COMPLETED_CHAPTERS}} 章。

---

## 3. 前情提要与脉络承接

### 前序章节核心结论
{{PREVIOUS_CHAPTERS_SUMMARY}}

### 紧邻上一章（第 {{CURRENT_CHAPTER_NUM}} 章）交付详情
- **上一章核心结论**：{{CURRENT_CHAPTER_THESIS}}
- **上一章末尾最后段落（用于本章首尾顺畅衔接）**：
> {{CURRENT_CHAPTER_ENDING_TAIL}}

- **上一章留给本章的待解问题与悬念**：
{{PENDING_QUESTIONS}}

---

## 4. 全局已锁定术语表
以下是全书截至目前已固化和跨章沉淀的译名与界定，本章写作必须严格沿用，严禁自造别名或同义混用：

{{GLOBAL_TERM_TABLE}}

---

## 5. 本章任务与一键启动指令
本章（第 {{NEXT_CHAPTER_NUM}} 章）将围绕解决上一章遗留问题并推进全书论证展开。
开始前先运行 `& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/chapter_status.py" --workspace "{{CHAPTER_DIR}}"`：它依据已有产物给出每节所处阶段与下一条命令（会话中断后从这里续传，不要重做已通过的步骤）。
请严格调用技能 `{{SKILL_DIR}}` 的内嵌工具与解释器 `{{PYTHON}}`，连续推进本章完整生产闭环：

### 阶段 1：大纲规划与术语计划
1. 参考 `{{SKILL_DIR}}/prompts/P1-chapter-outline.md` 生成 `{{CHAPTER_DIR}}/outline.md`；
2. 执行大纲校验转化生成 `{{CHAPTER_DIR}}/outline.json`：
   `& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/check_outline.py" --outline "{{CHAPTER_DIR}}/outline.md" --numbered "{{CHAPTER_DIR}}/source-numbered.md" --out-json "{{CHAPTER_DIR}}/outline.json"`
3. 参考 `{{SKILL_DIR}}/prompts/P1.5-term-plan.md` 规划本章新术语，产出 `{{CHAPTER_DIR}}/term-plan.json`；
4. 运行术语检查：
   `& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/check_term_plan.py" --term-plan "{{CHAPTER_DIR}}/term-plan.json" --outline-json "{{CHAPTER_DIR}}/outline.json" --numbered "{{CHAPTER_DIR}}/source-numbered.md" --global-terms "{{WORKSPACE}}/global-term-ledger.json"`
   （本章需沿用的已锁定术语以 `inherited:true` 写入；跨章依赖写 `c01:T3` 或 `ledger:<中文译名>`）

### 阶段 2：分节生产循环（依序对各小节连续执行：抽取 -> 写作 -> 校验）
对每个小节 k（1..N）：
1. **生成抽取任务单**：
   `& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/build_task_sheet.py" --mode extract --k <k> --outline-json "{{CHAPTER_DIR}}/outline.json" --numbered "{{CHAPTER_DIR}}/source-numbered.md" --sections-dir "{{CHAPTER_DIR}}/sections" --template "{{SKILL_DIR}}/prompts/P3-extract-sheet.md" --out "{{CHAPTER_DIR}}/sections/<k>-extract-task.md"`
2. **抽取与讲解单元**：
   - 依据 `{{SKILL_DIR}}/prompts/P7-points.md` 产出 `{{CHAPTER_DIR}}/sections/<k>-points.md`；
   - 依据 `{{SKILL_DIR}}/prompts/P2H-teaching-units.md` 产出 `{{CHAPTER_DIR}}/sections/<k>-teaching-units.json`；
   - 运行校验：`& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/run_stage_checks.py" --stage extract --workspace "{{CHAPTER_DIR}}" --k <k>`
3. **中文初稿独立写作**：
   - 生成写作任务单：`& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/build_task_sheet.py" --mode write --k <k> --outline-json "{{CHAPTER_DIR}}/outline.json" --points "{{CHAPTER_DIR}}/sections/<k>-points.md" --sections-dir "{{CHAPTER_DIR}}/sections" --template "{{SKILL_DIR}}/prompts/P3-write-sheet.md" --leak-source "{{CHAPTER_DIR}}/source-numbered.md" --out "{{CHAPTER_DIR}}/sections/<k>-write-task.md"`（术语台账、术语计划、讲解单元、上一章结尾由脚本自动发现；若报英文泄漏，回到 points/units 用中文改写）
   - 依据 `{{SKILL_DIR}}/prompts/P2H-write.md` 与 `{{SKILL_DIR}}/prompts/P2H-expansion.md` 产出 `{{CHAPTER_DIR}}/sections/<k>-revision.md`（**由全新上下文的独立写作者完成，见隔离协议**）；
   - 转化定稿：`& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/validate_revision.py" --revision "{{CHAPTER_DIR}}/sections/<k>-revision.md" --out "{{CHAPTER_DIR}}/sections/<k>-final.md"`；
   - 运行校验：`& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/run_stage_checks.py" --stage draft --workspace "{{CHAPTER_DIR}}" --k <k>`
4. **覆盖反查与核验**：
   - 依据 `{{SKILL_DIR}}/prompts/P8-coverage.md` 产出 `{{CHAPTER_DIR}}/sections/coverage-<k>.md`；
   - 运行校验：`& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/run_stage_checks.py" --stage audit --workspace "{{CHAPTER_DIR}}" --k <k>`

### 阶段 3：全章拼合与下一章交接
1. 合并各节初稿：
   `& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/merge_sections.py" --sections-dir "{{CHAPTER_DIR}}/sections" --n <小节总数> --out "{{CHAPTER_DIR}}/chapter-final.md" --out-marked "{{CHAPTER_DIR}}/merged-draft-marked.md"`
2. 若 P5 整合产生补丁：`apply_patches.py ... --out "{{CHAPTER_DIR}}/chapter-final.md"`，只保留这一份整章定稿（不要另存 `merged-final.md`）。
   全章校验（含分节完整性、术语、覆盖证据重核、残留标记；通过后才可交接）：
   `& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/run_stage_checks.py" --stage chapter --workspace "{{CHAPTER_DIR}}"`
3. 写下本章真实结论与遗留问题（交接依据，必须来自 `chapter-final.md` 而非大纲计划）：
   `{{CHAPTER_DIR}}/chapter-summary.json` = `{"conclusion":"本章实际得出并被论证支持的结论（一两句）","pending_questions":["留给下一章的未决问题"]}`
4. 沉淀术语与生成下一章交接 Prompt（要求第 2 步 `--stage chapter` 已通过且定稿未再被修改；术语漂移/歧义会直接拒绝合并）：
   `& "{{PYTHON}}" "{{SKILL_DIR}}/scripts/generate_handover.py" --workspace "{{WORKSPACE}}" --chapter {{NEXT_CHAPTER_NUM}}`

请立即自动连续推进第 {{NEXT_CHAPTER_NUM}} 章的完整生产流水线，直至全章定稿并生成下一章交接 Prompt！


连续执行以 orchestrate_book.py 返回的结构化动作为准，以上命令用于诊断和局部修复，无需用户运行。
