# 全书最终交付物质量验证与质检规范

全书所有章节完成研读改写并执行终局汇合后，执行最终交付物的一致性、完整性与排版质量验收。

---

## 1. 交付物矩阵

全书汇编命令：
```powershell
<python> scripts/merge_book.py --workspace <全书工作区根路径>
```

产出物统一归档于 `<workspace>/output/` 目录下：
1. `[slug]-全文研读稿.md`：全书连贯 Markdown 汇编文本（含全书总导读、完整目录导航与各章节定稿）；
2. `[slug]-全文研读稿.docx`：Word 文档（A4；真实 Heading 1/2 样式；TOC 域，在 Word 中按 F9 或打开时更新；正文区页码 PAGE 域；西文 Times New Roman/中文宋体字体分设；〔补充〕层独立样式；6 列术语附录且表头跨页重复）；
3. `[slug]-全书术语与概念台账.md`：跨所有章节沉淀的全局已锁定术语表（含 `locked` 锁定状态、`depends_on` 概念依赖说明与依赖拓扑分析：命名空间 uid、Kahn 分层、Tarjan 环路与前向依赖检测、Mermaid 图）；
4. `[slug]-全书质检报告.json`：全书自动化整体质检详细报告。

---

## 2. 全书交付质检三道防线（v2.1：默认失败关闭）

`merge_book.py` 与 `run_stage_checks.py --stage deliver` 共用同一套判定逻辑（`check_terms.term_variant_report`、`check_coverage`、`bt_common.analyze_term_graph`），不再各自重写。

### 第一道防线：章节完整性
- 整章定稿唯一规范文件为 `chapter-final.md`；若 `merged-final.md` 同时存在且内容不同，按“歧义”判违规（须把批准版本提升为 `chapter-final.md` 并删除另一份）。**缺少整章定稿即违规，分节稿不能冒充，汇编也不会代为写出 `chapter-final.md`。**
- `book.json` 中章节状态非 `done`、正文为空、CJK < 80 字、字数比（CJK ÷ 英文词数×1.7）< 0.40 为违规，< 0.75 为 advisory；
- 占位符残留：`（第 X 章暂未完成定稿）`、`<!-- TODO`、`【待定稿】`、`[待补充]`、`【第k节】` 标记、未渲染 `{{...}}`、`〔待核〕`。

### 第二道防线：术语
- **跨章漂移**：同一英文原词（大小写/连字符/单复数归一）出现多个译名即违规；若相关词条写了 `collision`（义项区分说明）则降为 advisory。
- **禁用词**：`user_banned`（term-plan 顶层、词条级、`book.json`）为硬禁令；`alias_ban` 是模型提出的候选别名，**默认仅 advisory**，加 `--strict-aliases` 才拦截。规范译名自身包含的子串不算命中。
- **概念依赖图**：环路、依赖更晚章节才引入的概念（前向依赖）为违规；无法解析的依赖为 advisory。依赖写法：本章内 `T3`；早前章节 `c01:T3` 或 `ledger:<中文译名>`。

### 第三道防线：覆盖
- 对每个小节用真实的 `{k}-points.md`、`{k}-final.md`、`coverage-{k}.md` 重跑 `check_coverage`（证据存在且不少于 8 字、缺失/改义/无效证据、覆盖率 ≥ 95%）；缺任一文件即违规。
- 大纲锚点与 `未纳入内容` 之外的源段落为 advisory（章阶段 `check_outline` 对非标题段落是硬违规）。

---

## 3. 术语与概念台账交付标准
1. `uid`（`c01:T1`）全局唯一；每条标注 `已锁定 (locked)` 与来源 `provenance`；
2. `depends_on` 以译名展示，并给出分层（第 0 层 = 不依赖其他概念）与 Mermaid 依赖图；
3. 列出候选别名 `alias_ban`（提示性）；硬禁用词不在台账公开列出。

---

## 4. 交付与质检命令

```powershell
<python> scripts/merge_book.py --workspace <全书工作区根路径> --check            # 仅质检，违规退出码 1
<python> scripts/merge_book.py --workspace <全书工作区根路径>                    # 默认：违规则拒绝汇编（退出码 1）
<python> scripts/merge_book.py --workspace <全书工作区根路径> --allow-violations # 仅供人工审阅草稿：照常汇编，JSON 中 ok=false
<python> scripts/merge_book.py --workspace <全书工作区根路径> --strict-aliases   # 把 alias_ban 命中也视为违规
<python> scripts/run_stage_checks.py --stage deliver --workspace <全书工作区根路径> --docx <docx>   # 另会解包校验 Heading/TOC/PAGE/A4
```
