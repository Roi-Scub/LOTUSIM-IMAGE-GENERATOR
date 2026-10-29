"""Bounded report links and filesystem resolution; independent of HTTP routing."""

import html
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

EXTENSIONS = {
    '.html',
    '.htm',
    '.png',
    '.jpg',
    '.jpeg',
    '.webp',
    '.json',
    '.txt',
    '.css',
    '.js',
    '.svg',
}

_HTML_ATTRIBUTES = re.compile(
    r'''(?P<prefix>\s+)(?P<name>[^\s=/>]+)(?P<assign>\s*=\s*)(?:(?P<double>"[^"]*")|(?P<single>'[^']*')|(?P<bare>[^\s>]+))''',
    re.S,
)


def rewrite_report_html(data, path, server):
    """Retokenize existing artifact links, not request traversal permissions.

    Only href/src attributes in actual HTML start tags are inspected. Text,
    scripts, CSS and all unrelated markup are byte-for-byte preserved. A link
    may refer to another allowed artifacts root, but never arbitrary host files.
    Existing request paths still pass safe_child and cannot contain '..'.
    """
    register = getattr(server.hub.collector, 'file_url', None)
    if register is None:
        return data
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return data
    source = Path(path).resolve()
    offsets = [0]
    for index, character in enumerate(text):
        if character == '\n':
            offsets.append(index + 1)
    replacements = []

    def link_url(value):
        value = html.unescape(value)
        if '\\' in value or '\0' in value:
            return None
        try:
            parts = urlsplit(value)
        except ValueError:
            return None
        if parts.scheme or parts.netloc or not parts.path or parts.path.startswith('/'):
            return None
        decoded = unquote(parts.path)
        if '\\' in decoded or '\0' in decoded:
            return None
        pieces = decoded.split('/')
        if any(p.startswith('.') and p not in ('.', '..') for p in pieces):
            return None
        candidate = source.parent.joinpath(decoded)
        if candidate.suffix.lower() not in EXTENSIONS or not candidate.is_file():
            return None
        if not server.allowed_file(candidate):
            return None
        target = register(candidate, 'report_asset')
        return parts._replace(path=target).geturl() if target else None

    class Links(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)

        def handle_starttag(self, tag, attrs):
            raw = self.get_starttag_text()
            line, column = self.getpos()
            base = offsets[line - 1] + column
            for found in _HTML_ATTRIBUTES.finditer(raw):
                if found.group('name').lower() not in ('href', 'src'):
                    continue
                group = next(
                    name for name in ('double', 'single', 'bare') if found.group(name) is not None
                )
                token = found.group(group)
                value = token[1:-1] if group != 'bare' else token
                replacement = link_url(value)
                if replacement is not None:
                    replacements.append(
                        (
                            base + found.start(group),
                            base + found.end(group),
                            '"' + html.escape(replacement, quote=True) + '"',
                        )
                    )

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)

    parser = Links()
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, OSError):
        return data
    if not replacements:
        return data
    rebuilt = []
    cursor = 0
    for start, end, replacement in sorted(replacements):
        if start < cursor:
            continue
        rebuilt.extend((text[cursor:start], replacement))
        cursor = end
    rebuilt.append(text[cursor:])
    return ''.join(rebuilt).encode('utf-8')


def safe_child(root, relative):
    """Resolve only non-hidden relative assets inside an allowed directory."""
    root = Path(root).resolve()
    if not isinstance(relative, str) or not relative or '\\' in relative or '\0' in relative:
        return None
    parts = relative.split('/')
    if any(not p or p in {'.', '..'} or p.startswith('.') for p in parts):
        return None
    path = root.joinpath(*parts).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if path.suffix.lower() not in EXTENSIONS or not path.is_file():
        return None
    return path
