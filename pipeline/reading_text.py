"""Reading-only English hyphen normalization; never produces source offsets."""
import re

# Protect code, math, links and structural tags before touching prose.
PROTECTED = re.compile(
    r'```[\s\S]*?```|`[^`\n]*`|\$\$[\s\S]*?\$\$|\$[^$\n]*\$'
    r'|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)'
    r'|https?://[^\s<>]+|<[^>\n]+>'
    r'|^[^\n]*[=−×∈√<>][^\n]*(?:\n|$)', re.M)
WORD = re.compile(r'(?<![\w])[A-Za-z]{2,}(?![\w])')
WRAP = re.compile(r'(?<![\w])([A-Za-z]{2,})[-‐]\s*\n[ \t]*([a-z]{2,})(?![\w])')
COMPOUND = re.compile(r'(?<=[A-Za-z])[-‐‑](?=[A-Za-z])')


class ReadingText:
    def __init__(self, texts, candidate_names=()):
        # Only restore a wrap when its intact spelling is independently attested.
        # No vocabulary content is added to a shard, only spelling is reconciled.
        self.words = set()
        for text in texts:
            prose = WRAP.sub(' ', PROTECTED.sub(' ', text))
            self.words.update(w.casefold() for w in WORD.findall(prose))
        self.joined_words = self.words | {
            w.casefold() for name in candidate_names for w in WORD.findall(name)}

    def __call__(self, text):
        def prose(part):
            def join(m):
                left, right = m.group(1), m.group(2)
                if ((left + right).casefold() in self.joined_words
                        and not (left.casefold() in self.words and right in self.words)):
                    return left + right
                return m.group(0)
            part = WRAP.sub(join, part)
            # Whole alphabetic chains only: do not change x-y, 1e-3, ranges,
            # or hyphens adjacent to digits/underscores. Ambiguous wraps stay.
            def chain(m):
                words = re.split('[-‐‑]', m.group(0))
                if all(len(w) >= 2 for w in words):
                    return COMPOUND.sub(' ', m.group(0))
                return m.group(0)
            return re.sub(r'(?<![\w-])[A-Za-z]+(?:[-‐‑][A-Za-z]+)+(?![\w-])', chain, part)
        result, start = [], 0
        for match in PROTECTED.finditer(text):
            result.extend((prose(text[start:match.start()]), match.group(0)))
            start = match.end()
        result.append(prose(text[start:]))
        return ''.join(result)
