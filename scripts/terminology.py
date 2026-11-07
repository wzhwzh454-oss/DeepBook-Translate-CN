"""Reader-facing core terminology; editorial provenance stays in the ledger."""
def render_core_table(terms):
    core = [term for term in terms if term.get('level') == '核心' and not term.get('inherited')]
    if not core:
        return ''
    clean = lambda value: str(value or '').replace('|', '／').replace('\n', ' ')
    rows = ['| 术语 | 原词 | 简明解释 |', '| :-- | :-- | :-- |']
    rows += ['| %s | %s | %s |' % tuple(clean(term.get(field)) for field in ('zh', 'orig', 'gloss')) for term in core]
    return '\n'.join(rows)
