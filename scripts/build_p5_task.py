"""Assemble chapter integration input from the actual finished sections."""
from pathlib import Path
import argparse
import json
from bt_common import write_text_atomic
from check_points import parse_points

def build(chapter):
    chapter = Path(chapter).resolve()
    outline = json.loads((chapter / 'outline.json').read_text(encoding='utf-8'))
    parts = ['# 章节整合任务', (Path(__file__).resolve().parents[1] / 'prompts/P5-integrate.md').read_text(encoding='utf-8'), '\n## 全章拼合稿', (chapter / 'merged-draft-marked.md').read_text(encoding='utf-8'), '\n## 已定术语', (chapter / 'term-plan.json').read_text(encoding='utf-8')]
    for section in outline['sections']:
        k = section['k']
        records, errors = parse_points((chapter / 'sections' / f'{k}-points.md').read_text(encoding='utf-8'))
        if errors:
            raise ValueError(errors)
        parts += [f'\n## 第{k}节中文意义与覆盖', json.dumps([{key: row.get(key, '') for key in ('id', 'kind', 'holder', 'statement', 'qualifiers', 'force')} for row in records], ensure_ascii=False), (chapter / 'sections' / f'coverage-{k}.md').read_text(encoding='utf-8')]
    parts += ['\n## 本次输出', '检查跨节重复、接缝、术语与论述完整性。仅修无阅读功能的重复，不删除原作的实质铺陈或把全章压成摘要。', '有补丁时按 P5 格式应用到 chapter-final.md；无须修改时明确记录。最后写 p5-review.md，说明实际检查与处理结果；该文件在最终整合之后写入。无据候选需要回源核实，不依据中文清单猜测原作。']
    return '\n\n'.join(parts) + '\n'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    path = args.out or args.workspace / 'p5-task.md'
    write_text_atomic(path, build(args.workspace))
    print(json.dumps({'ok': True, 'task_path': str(path.resolve())}, ensure_ascii=False))

if __name__ == '__main__':
    main()
