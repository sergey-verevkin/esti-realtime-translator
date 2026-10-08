#!/usr/bin/env python3
"""Compare identical prepared text across local models and sentence strategies."""
import argparse
import json
import sys
from approaches import load_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text', help='Default: UTF-8 text from stdin')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--source-lang', choices=['et', 'en'], default='et')
    args = parser.parse_args()
    text = args.text if args.text is not None else sys.stdin.read(16001)
    if not text.strip() or len(text) > 16000:
        parser.error('Provide 1–16000 characters')
    rows = []
    for name in ['nllb', 'nllb-1.3b']:
        try:
            model = load_engine(name)
            model.translate('Good morning!' if args.source_lang == 'en' else 'Tere hommikust!', args.source_lang)
        except Exception as exc:
            rows.append({'engine': name, 'style': 'sentences', 'error': str(exc)})
            continue
        for style in ['sentences']:
            model.style = style
            try:
                translation, ms = model.translate(text, args.source_lang)
                rows.append({'engine': name, 'style': style, 'translation': translation, 'translation_ms': round(ms, 1)})
            except Exception as exc:
                rows.append({'engine': name, 'style': style, 'error': str(exc)})
        del model
    if args.json:
        print(json.dumps({'original': text, 'results': rows}, ensure_ascii=False))
    else:
        for row in rows:
            print(f"{row['engine']} / {row['style']}: {row.get('translation', row.get('error'))}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
