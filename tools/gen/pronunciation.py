# Mittler（写したときの名前は claude-cut）の写し（元：作者の制作のワークスペースの slideshow-video\pronunciation.py、2026-10-21。中身はそのまま）
"""Literal, non-recursive pronunciation replacement using user-registered entries only."""
import json
from pathlib import Path
import re

TAG = re.compile(r'(<[^<>]*>)')


def load_dictionary(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('entries'), list):
        raise ValueError('Invalid pronunciation dictionary schema.')
    entries = data['entries']
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Pronunciation entries must be objects.')
        word, reading = entry.get('word'), entry.get('reading')
        if (not isinstance(word, str) or not word.strip() or any(c in word for c in '<>\n\r')
                or word in seen or not isinstance(reading, str)
                or not re.fullmatch(r'[ぁ-ゖー]+', reading)):
            raise ValueError('Each pronunciation needs a unique literal word and hiragana reading.')
        seen.add(word)
    return entries


def replace_readings(text, entries):
    """Replace only text outside acting tags; longest match, one pass, no inference."""
    if not isinstance(text, str):
        raise ValueError('Pronunciation input must be text.')
    if not entries:
        return text, []
    lookup = {entry['word']: entry['reading'] for entry in entries}
    pattern = re.compile('|'.join(re.escape(word) for word in sorted(lookup, key=len, reverse=True)))
    counts = {}
    def substitute(match):
        word = match.group()
        counts[word] = counts.get(word, 0) + 1
        return lookup[word]
    segments = TAG.split(text)
    converted = ''.join(segment if i % 2 else pattern.sub(substitute, segment)
                        for i, segment in enumerate(segments))
    return converted, [{'word': word, 'reading': lookup[word], 'count': count}
                       for word, count in counts.items()]
