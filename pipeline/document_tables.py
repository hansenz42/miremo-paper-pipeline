"""Reusable preparation contract: original text lives only in shards."""
import hashlib
import copy
import math
from term_matching import associate_candidates
from reading_order import annotate_reading_order


def prepare_tables(raw, prepared, user_rows=(), language='auto', *, include_user_seeds=False):
    version = hashlib.sha256(raw.encode()).hexdigest()
    if version != prepared["source_sha256"]:
        raise ValueError("Document version mismatch")
    shards = []
    source_shards = {s["id"]: s for s in prepared["shards"]}
    for chapter in prepared["chapters"]:
        for chapter_order, sid in enumerate(chapter["shard_ids"]):
            s = source_shards[sid]
            assert s["chapter_id"] == chapter["id"]
            assert chapter["start"] <= s["start"] < s["end"] <= chapter["end"]
            assert raw[s["start"]:s["end"]] == s["text"], sid
            shards.append({**{k: copy.deepcopy(s[k]) for k in
                             ("id", "chapter_id", "start", "end", "text")},
                           "order": len(shards), "chapter_order": chapter_order,
                           "document_version": version,
                           "continuation_group": s.get("continuation_group"),
                           "heading_path": s.get("heading_path", []), "kind": s.get("kind")})
    assert len(shards) == len(prepared["shards"])
    annotate_reading_order(shards)
    byid = {s["id"]: s for s in shards}
    assert len(byid) == len(shards)

    def references(start, end):
        refs = [{"shard_id": s["id"], "start": max(start, s["start"])-s["start"],
                 "end": min(end, s["end"])-s["start"]}
                for s in shards if s["start"] < end and start < s["end"]]
        # Paragraph separators may be omitted by the established splitter.
        covered = sorted((byid[r["shard_id"]]["start"]+r["start"],
                          byid[r["shard_id"]]["start"]+r["end"]) for r in refs)
        cursor = start
        for a, b in covered:
            if a > cursor and raw[cursor:a].strip():
                raise ValueError("Uncovered content in reference")
            cursor = max(cursor, b)
        if cursor < end and raw[cursor:end].strip():
            raise ValueError("Uncovered content in reference")
        return refs

    chapters = []
    for order, c in enumerate(prepared["chapters"]):
        assert all(byid[i]["chapter_id"] == c["id"] for i in c["shard_ids"])
        ids = c["shard_ids"]
        n = math.ceil(len(ids) * .1)
        samples = list(ids) if len(ids) <= 3 else list(dict.fromkeys(ids[:n] + ids[-n:]))
        chapters.append({"id": c["id"], "title": c["title"], "order": order,
                         "document_version": version, "start": c["start"], "end": c["end"],
                         "shard_ids": c["shard_ids"], "sample_shard_ids": samples,
                         "subheadings": c.get("subheadings", [])})
    candidates = []
    for k in prepared["keywords"]:
        mentions = [{"highlight_spans": references(p["start"], p["end"])} for p in k["positions"]]
        mention_ids = list(dict.fromkeys(r["shard_id"] for m in mentions for r in m["highlight_spans"]))
        candidates.append({
            "id": k["id"], "name": k["keyword"], "document_version": version,
            "source_status": "document_only", "source_kinds": ["document"],
            "origins": [{"kind": "document", "method": "keyword_algorithm"}],
            "algorithm_scores": copy.deepcopy(k["sources"]), "rank": k["rank"],
            "mention_shard_ids": mention_ids, "mentions": mentions, "occurrences": len(mentions), "definition": "",
            "definition_shard_ids": [], "reference_classifications": [], "classification": None,
            "classification_shard_ids": [], "sense": "", "status": "preselected",
            "revision": 0, "history": [], "conflicts": []})
    for row in (user_rows if include_user_seeds else ()) :
        candidates.append({
            "id": row["id"], "name": row["keyword"], "document_version": version,
            "source_status": row["source_status"], "source_kinds": row["source_kinds"],
            "origins": copy.deepcopy(row["origins"]), "algorithm_scores": {}, "rank": None,
            "mention_shard_ids": [], "mentions": [], "occurrences": 0,
            "definition": row["definition"], "definition_shard_ids": [],
            "reference_classifications": copy.deepcopy(row["reference_classifications"]),
            "classification": copy.deepcopy(row["classification"]), "classification_shard_ids": [],
            "definition_origin": "user_reference",
            "sense": row.get("sense", ""), "status": "preselected",
            "revision": 0, "history": [], "conflicts": []})
    associate_candidates(candidates, shards, language)
    for shard in shards:
        shard["candidate_ids"] = [r["id"] for r in candidates
                                  if shard["id"] in r.get("mention_shard_ids", [])]
    return {"document_version": version, "candidates": candidates,
            "chapters": chapters, "shards": shards}


class DocumentStore:
    """The reader resolves refs on demand, without persisting context in candidates."""
    def __init__(self, tables):
        self.version = tables["document_version"]
        self.shards = {s["id"]: s for s in tables["shards"]}
        self.chapters = {c["id"]: c for c in tables["chapters"]}

    def read_shard(self, shard_id, version):
        if version != self.version:
            raise ValueError("Stale document reference")
        return self.shards[shard_id]["text"]

    def read(self, ref, version):
        """Highlight helper only; agent reading uses read_shard."""
        if version != self.version:
            raise ValueError("Stale document reference")
        s = self.shards[ref["shard_id"]]
        a, b = ref["start"], ref["end"]
        if not (isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= len(s["text"])):
            raise ValueError("Invalid shard character range")
        return s["text"][a:b]
