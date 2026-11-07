# 面向 AI 助手的 ZIP 安装说明

用户将 `book-translator-*.zip` 交给 AI 助手时，请由助手按当前宿主实际提供的技能机制执行安装。ZIP 出现在对话附件中，并不代表技能已经自动安装或生效。

## 安装步骤

1. 将 ZIP 解压到临时目录，保留 UTF-8 文件名。检查解压后的目标目录中直接存在 `SKILL.md`，并同时看到 `scripts/`、`references/`、`prompts/` 和 `tests/`。如果出现外层下载目录，继续向下找到真正的仓库根目录。
2. 查询当前宿主明确提供的 skills 目录或安装 API。目录规则会随工具和安装范围变化；查不到时先检查宿主文档或当前会话提供的技能发现信息，不要凭经验把文件写入未知目录。
3. 将包含 `SKILL.md` 的仓库根目录复制或移动为 `<实际 skills 目录>/book-translator/`。安装后的关键路径必须是 `<实际 skills 目录>/book-translator/SKILL.md`，不能多一层 `book-translator/book-translator/`。如果目标位置已有同名技能，先检查并保留现有版本或本地改动；需要更新时先做可恢复的备份，再放入新版本。
4. 检查 `SKILL.md` 的 YAML 头中 `name: book-translator`，并确认入口引用的目录与文件均存在。使用宿主提供的技能校验器（如果有），再运行脚本编译检查和回归测试：

   ```text
   python -m compileall -q <实际 skills 目录>/book-translator/scripts <实际 skills 目录>/book-translator/tests
   python <实际 skills 目录>/book-translator/tests/run_all.py
   ```

   如果测试依赖缺失，优先使用宿主已有的 Python 环境；确需安装时仅创建该技能自己的隔离环境，并从 `requirements.txt` 安装依赖，不要改动系统 Python。若当前环境无法安装依赖，记录哪些检查完成、哪些未完成，不要虚报测试通过。
5. 按宿主要求重新载入或刷新技能索引。只有在 `SKILL.md` 位于正确路径、校验完成且宿主重新发现它之后，才告诉用户安装完成。

## 环境适配

安装完成后，先按 `SKILL.md` 和 `references/full-book-runtime.md` 探查文件读写、脚本、工作区恢复、OCR、上下文切换和子代理能力。每本书的运行路由写入该书工作区的 `runtime-strategy.json`。如果宿主差异会长期影响运行方式，且安装目录可写，可以在安装副本中新增 `references/host-adaptation.local.md`，记录最小适配、证据、日期和回退方法；此文件是本机私有配置，不能放回公共 ZIP。

如果安装目录只读、路径不明，或宿主不允许修改技能文件，只在书籍工作区记录适配，并在开工前告诉用户会采用连续推进还是手动交接。不要修改公共上传包，也不要仅凭上下文压缩推测宿主会自动开启新对话。

## 失败处理

- ZIP 无法解压、缺少根目录 `SKILL.md` 或校验失败：保留现场，报告具体路径和错误，不声称已安装。
- 找不到宿主技能目录或没有写权限：向用户说明需要它提供的安装位置或权限；可以先在临时目录运行只读检查。
- 宿主不支持自动刷新：告知用户需要按该工具的方式重新载入；在重新载入前不要声称已生效。
- 安装后书籍是图片 PDF 且没有 OCR：按技能中的 OCR 说明暂停并征得用户同意，不能猜译。
