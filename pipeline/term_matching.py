"""Candidate recall only: never entity identity resolution or a writeback gate."""
import re
from functools import lru_cache

POLICY = 'en-noun-lemma-zh-literal-v3'
DASHES = str.maketrans({c: '-' for c in '‐‑‒–—−'})


def language_for(name, language='auto'):
    if language not in ('auto', 'en', 'zh'):
        raise ValueError('Supported matching languages: auto, en, zh')
    # Even an English document can contain Chinese candidate names and vice versa.
    if re.search(r'[\u3400-\u9fff]', name):
        return 'zh'
    return 'en' if language != 'zh' and re.search('[A-Za-z]', name) else 'zh'


@lru_cache(maxsize=1)
def english_pipeline():
    try:
        import spacy
        return spacy.load('en_core_web_sm', disable=['parser', 'ner'])
    except (ImportError, OSError) as exc:
        raise RuntimeError('English matching requires spaCy and en_core_web_sm; no silent literal fallback') from exc


@lru_cache(maxsize=1024)
def proper_plural_lemma(word):
    # spaCy's English default preserves PROPN lemmas, even for NNPS.
    # Only after its tagger identifies NNPS, apply its noun rules to a scratch token.
    from spacy.tokens import Doc
    from spacy.symbols import NOUN
    nlp = english_pipeline()
    doc = Doc(nlp.vocab, words=[word.casefold()])
    doc[0].pos = NOUN
    doc[0].tag = nlp.vocab.strings.add('NNS')
    doc[0].set_morph('Number=Plur')
    lemmas = nlp.get_pipe('lemmatizer').rule_lemmatize(doc[0])
    return lemmas[0] if lemmas else word.casefold()


@lru_cache(maxsize=1024)
def tokens(text):
    # Preserve offsets while keeping Chinese runs out of the English tagger.
    masked = re.sub(r'[\u3400-\u9fff]', ' ', text.translate(DASHES))
    result = []
    for t in english_pipeline()(masked):
        if t.is_space:
            continue
        literal = t.text.casefold()
        base = literal
        # Let spaCy identify plural nouns, including uppercase abbreviations.
        # Other parts of speech remain unchanged.
        if t.pos_ == 'NOUN' and t.tag_ == 'NNS' and t.text.isalpha():
            base = t.lemma_.casefold()
        elif t.pos_ == 'PROPN' and t.tag_ == 'NNPS' and t.text.isalpha():
            base = proper_plural_lemma(t.text)
        result.append((literal, base, t.idx, t.idx + len(t.text)))
    return tuple(result)


def find_matches(text, name, language='auto'):
    if not isinstance(name, str) or not name.strip():
        return []
    name = name.strip()
    lang = language_for(name, language)
    normalized_name = name.translate(DASHES)
    pattern = r'\s+'.join(re.escape(x) for x in normalized_name.split())
    if lang == 'en':
        pattern = r'(?<![A-Za-z0-9_])' + pattern + r'(?![A-Za-z0-9_])'
    found = {}
    for m in re.finditer(pattern, text.translate(DASHES), re.I):
        found[(m.start(), m.end())] = {
            'start': m.start(), 'end': m.end(),
            'match_method': 'exact' if text[m.start():m.end()] == name else 'normalized',
            'language': lang,
        }
    if lang == 'en':
        source, candidate = tokens(text), tokens(name)
        bases = tuple(t[1] for t in candidate)
        size = len(bases)
        if size:
            for i in range(len(source)-size+1):
                window = source[i:i+size]
                if tuple(t[1] for t in window) != bases:
                    continue
                # Masked Chinese must not turn separated English words into one phrase.
                if any(text[a[3]:b[2]].strip() for a,b in zip(window,window[1:])):
                    continue
                a,b = window[0][2],window[-1][3]
                found.setdefault((a,b), {'start':a,'end':b,'match_method':'english_noun_lemma','language':'en'})
    return [found[k] for k in sorted(found)]


def matching_key(name, language='auto'):
    if language_for(name, language) == 'en':
        return ' '.join(t[1] for t in tokens(name))
    return ' '.join(name.translate(DASHES).casefold().split())


def query_matches(query, name, language='auto'):
    # Phrase-boundary matching, not substring matching (model must not match modeling).
    return bool(find_matches(name, query, language) or find_matches(query, name, language))


def associate_candidates(rows, shards, language='auto'):
    """Append positions, preserve names, IDs, legacy spans, definitions and provenance."""
    for row in rows:
        row['matching'] = {'policy':POLICY, 'language':language_for(row['name'], language),
                           'key':matching_key(row['name'], language)}
        mentions = row.setdefault('mentions', [])
        for shard in shards:
            for hit in find_matches(shard['text'], row['name'], language):
                ref = {'shard_id':shard['id'], 'start':hit['start'], 'end':hit['end']}
                old = next((m for m in mentions if m['highlight_spans'] == [ref]), None)
                if old is None:
                    old = {'highlight_spans':[ref]}
                    mentions.append(old)
                old.update(match_method=hit['match_method'], language=hit['language'])
        row['mention_shard_ids'] = list(dict.fromkeys(r['shard_id'] for m in mentions for r in m['highlight_spans']))
        row['occurrences'] = len(mentions)
    return rows
