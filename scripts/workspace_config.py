"""One configuration path shared by intake, writers, checks and export."""
from pathlib import Path
from copy import deepcopy
import json

DEFAULTS = {
    'book': {'source_lang': 'en', 'style_profile': {'genre_family': 'humanities_scholarly'}},
    'translation': {
        'profile': 'v2', 'mode': 'full-study-reader', 'search_grounding': 'core-as-needed',
        'coverage_min_rate': 1.0, 'preserve_all_content': True,
        'readability': {'sent_p50_max': 24, 'sent_p90_max': 45, 'sent_hard': 65, 'para_soft': 180, 'para_hard': 300},
    },
    'layout': {'include_chapter_vernacular_table': True, 'include_glossary_appendix': True},
}

def overlay(base, extra):
    result = deepcopy(base)
    for key, value in extra.items():
        result[key] = overlay(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else deepcopy(value)
    return result

def book_root(path):
    path = Path(path).resolve()
    if path.is_file():
        path = path.parent
    for folder in (path, *path.parents):
        if (folder / 'book.json').is_file():
            return folder
    return path

def load_config(path):
    root = book_root(path)
    config = deepcopy(DEFAULTS)
    book = json.loads((root / 'book.json').read_text(encoding='utf-8-sig')) if (root / 'book.json').exists() else {}
    config['book'].update({key: value for key, value in book.items() if key not in ('translation', 'layout')})
    for key in ('translation', 'layout'):
        config[key] = overlay(config[key], book.get(key, {}))
    for name in ('book-config.json', 'config.json'):
        if (root / name).is_file():
            config = overlay(config, json.loads((root / name).read_text(encoding='utf-8-sig')))
            break
    # Old builds wrote cognitive_load; maintain one canonical readability view.
    if config['translation'].get('cognitive_load'):
        config['translation']['readability'] = overlay(config['translation']['readability'], config['translation']['cognitive_load'])
    if config['book'].get('source_lang') in ('auto', None, ''):
        config['book']['source_lang'] = book.get('source_lang', 'en')
    return config

def source_language(path):
    return load_config(path)['book'].get('source_lang', 'en')
