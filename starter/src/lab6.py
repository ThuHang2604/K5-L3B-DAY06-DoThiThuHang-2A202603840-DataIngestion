"""Day 06 pipeline: chunk (A/B) -> embed (e5) -> pgvector -> validate / evaluate (A, B, C) -> audit.

Chay tu thu muc starter/ (venv bat, Docker pgvector dang chay):
    python -m src.lab6 ingest      # chunk A + B, embed, luu vao pgvector (chay 2 lan de chung minh khong nhan doi)
    python -m src.lab6 validate    # kiem tra benchmark/questions.jsonl (so cau, split, filter, evidence ton tai)
    python -m src.lab6 evaluate    # top-3 cho A, B, C -> results/trace_*.jsonl + results/metrics.csv
    python -m src.lab6 audit       # tao mau cham thu cong (coherence, metadata, grounding)

Cau hinh:
  A = chunk co dinh 500 ky tu, overlap 50, khong filter
  B = chunk theo heading/doan (toi da 1200 ky tu), khong filter
  C = dung index B, chi them filter metadata `part` khi cau hoi co filter (cau khong co filter chay khong filter)
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data" / "manifest.json"
PAGES_DIR = ROOT / "data" / "pages"
BENCH = ROOT / "benchmark" / "questions.jsonl"
RESULTS = ROOT / "results"

MODEL_NAME = "intfloat/multilingual-e5-base"
DIM = 768
A_SIZE, A_OVERLAP = 500, 50
B_MAX, B_MIN = 1200, 300
TOP_K = 3
FILTER_KEYS = {"part", "chapter"}


# ----------------------------------------------------------------------------- helpers
def norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).replace("\xa0", " ").split())


def load_pages():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pages = []
    for p in manifest["pages"]:
        f = PAGES_DIR / f"{p['page_id']}.txt"
        if not f.exists():
            sys.exit(f"LOI: thieu file {f} (chay lai python -m src.crawl_pg_docs)")
        pages.append({**p, "document_id": manifest["source_id"], "text": f.read_text(encoding="utf-8")})
    return manifest, pages


def load_bench():
    if not BENCH.exists():
        sys.exit(f"LOI: chua co {BENCH}")
    qs = []
    for i, line in enumerate(BENCH.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                qs.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.exit(f"LOI JSON o dong {i} cua {BENCH}: {e}")
    return qs


def gold_pages(q):
    g = q["gold_page"]
    return g if isinstance(g, list) else [g]


# ----------------------------------------------------------------------------- chunking
def chunk_fixed(text, size=A_SIZE, overlap=A_OVERLAP):
    """A: cua so co dinh. Tra ve [(start, end, text)]."""
    out, i, step = [], 0, size - overlap
    while i < len(text):
        piece = text[i:i + size]
        if piece.strip():
            out.append((i, i + len(piece), piece))
        if i + size >= len(text):
            break
        i += step
    return out


def split_blocks(text):
    """Tach thanh cac khoi (start, text) theo dong trong; khoi code ``` giu nguyen."""
    blocks, cur, cur_start, pos, in_fence = [], [], None, 0, False
    for ln in text.split("\n"):
        if ln.strip() == "```":
            in_fence = not in_fence
        if ln == "" and not in_fence:
            if cur:
                blocks.append((cur_start, "\n".join(cur)))
                cur, cur_start = [], None
        else:
            if cur_start is None:
                cur_start = pos
            cur.append(ln)
        pos += len(ln) + 1
    if cur:
        blocks.append((cur_start, "\n".join(cur)))
    return blocks


def is_heading(b):
    return bool(re.match(r"^#{1,4} ", b)) and "\n" not in b


def split_long(start, b, limit):
    """Cat khoi qua dai: code theo dong, van ban theo cau."""
    if len(b) <= limit:
        return [(start, b)]
    units = b.split("\n") if b.startswith("```") else re.split(r"(?<=[.!?])\s+", b)
    sep = "\n" if b.startswith("```") else " "
    out, cur, search = [], "", 0
    for u in units:
        cand = (cur + sep + u) if cur else u
        if len(cand) > limit and cur:
            idx = b.find(cur, search)
            out.append((start + max(idx, 0), cur))
            search = max(idx, 0) + len(cur)
            cur = u
        else:
            cur = cand
    if cur:
        idx = b.find(cur, search)
        out.append((start + max(idx, 0), cur))
    final = []
    for s, t in out:  # cat cung neu van dai (dong code cuc dai)
        while len(t) > limit:
            final.append((s, t[:limit]))
            s, t = s + limit, t[limit:]
        final.append((s, t))
    return final


def chunk_by_heading(text, page_title):
    """B: tach theo heading, gom doan toi da B_MAX ky tu, them 'tieu de trang > heading' lam tien to."""
    sections, head, cur = [], None, []
    for start, b in split_blocks(text):
        if is_heading(b):
            if cur:
                sections.append((head, cur))
            head, cur = b.lstrip("#").strip(), []
        else:
            cur.append((start, b))
    if cur:
        sections.append((head, cur))

    out = []
    for head, blocks in sections:
        prefix = page_title if (not head or head == page_title) else f"{page_title} > {head}"
        parts = []
        for s, b in blocks:
            parts.extend(split_long(s, b, B_MAX))
        groups, g, g_len = [], [], 0
        for s, b in parts:
            if g and g_len + len(b) + 2 > B_MAX:
                groups.append(g)
                g, g_len = [], 0
            g.append((s, b))
            g_len += len(b) + 2
        if g:
            groups.append(g)
        if len(groups) > 1 and sum(len(b) for _, b in groups[-1]) < B_MIN:
            groups[-2].extend(groups.pop())  # gop doan cuoi qua nho vao doan truoc
        for g in groups:
            body = "\n\n".join(b for _, b in g)
            out.append((g[0][0], g[-1][0] + len(g[-1][1]), f"{prefix}\n{body}"))
    return out


def build_chunks(pages, strategy):
    chunks = []
    for p in pages:
        raw = chunk_fixed(p["text"]) if strategy == "A" else chunk_by_heading(p["text"], p["section_title"] or p["page_id"])
        for i, (s, e, t) in enumerate(raw):
            chunks.append({
                "chunk_id": f"{strategy}:{p['page_id']}:{i:03d}", "strategy": strategy,
                "document_id": p["document_id"], "source": p["url"], "page": p["page_id"],
                "part": p["part"], "chapter": p["chapter"], "section_title": p["section_title"],
                "chunk_index": i, "start_char": s, "end_char": e, "text": t, "n_chars": len(t),
            })
    return chunks


# ----------------------------------------------------------------------------- db + model
def connect():
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(ROOT / "starter" / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("LOI: thieu DATABASE_URL trong starter/.env")
    try:
        return psycopg.connect(url)
    except Exception as e:  # bao loi ro, khong fallback am tham
        sys.exit(f"LOI: khong ket noi duoc database ({e}). Docker pgvector co dang chay khong?")


def load_model():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(MODEL_NAME)
    m.max_seq_length = 512
    return m


def vec_literal(v):
    return "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"


SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id text PRIMARY KEY, strategy text NOT NULL, document_id text, source text, page text,
    part text, chapter text, section_title text, chunk_index int, start_char int, end_char int,
    n_chars int, text text, embedding vector({DIM})
);
CREATE INDEX IF NOT EXISTS chunks_strategy_part ON chunks (strategy, part);
"""


# ----------------------------------------------------------------------------- ingest
def cmd_ingest(_):
    import sentence_transformers
    import torch
    _, pages = load_pages()
    model = load_model()
    RESULTS.mkdir(parents=True, exist_ok=True)
    stats_path = RESULTS / "ingest_stats.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    with connect() as conn:
        conn.execute(SCHEMA)
        conn.commit()
        for strategy in ("A", "B"):
            t0 = time.time()
            chunks = build_chunks(pages, strategy)
            t_chunk = time.time() - t0
            t1 = time.time()
            embs = model.encode(["passage: " + c["text"] for c in chunks], batch_size=16,
                                normalize_embeddings=True, show_progress_bar=True)
            t_embed = time.time() - t1
            t2 = time.time()
            before = conn.execute("SELECT count(*) FROM chunks WHERE strategy=%s", (strategy,)).fetchone()[0]
            with conn.transaction():
                conn.execute("DELETE FROM chunks WHERE strategy=%s", (strategy,))
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO chunks (chunk_id,strategy,document_id,source,page,part,chapter,section_title,"
                        "chunk_index,start_char,end_char,n_chars,text,embedding) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)",
                        [(c["chunk_id"], c["strategy"], c["document_id"], c["source"], c["page"], c["part"],
                          c["chapter"], c["section_title"], c["chunk_index"], c["start_char"], c["end_char"],
                          c["n_chars"], c["text"], vec_literal(e)) for c, e in zip(chunks, embs)])
            t_db = time.time() - t2
            after = conn.execute("SELECT count(*) FROM chunks WHERE strategy=%s", (strategy,)).fetchone()[0]
            lens = sorted(c["n_chars"] for c in chunks)
            stats[strategy] = {
                "n_chunks": len(chunks), "total_chars": sum(lens),
                "len_min": lens[0], "len_median": statistics.median(lens),
                "len_mean": round(statistics.mean(lens), 1), "len_p90": lens[int(0.9 * (len(lens) - 1))],
                "len_max": lens[-1],
                "seconds_chunk": round(t_chunk, 2), "seconds_embed": round(t_embed, 1), "seconds_db": round(t_db, 2),
                "seconds_total": round(t_chunk + t_embed + t_db, 1), "cost_usd": 0,
                "reload_rows_before": before, "reload_rows_after": after,
                "model": MODEL_NAME, "dim": DIM, "metric": "cosine (exact scan, khong index ANN)",
                "versions": {"sentence_transformers": sentence_transformers.__version__, "torch": torch.__version__},
                "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            print(f"[{strategy}] {len(chunks)} chunk | truoc nap: {before} -> sau nap: {after} | "
                  f"{stats[strategy]['seconds_total']}s")
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Da luu {stats_path}. Chay lenh nay lan 2: 'sau nap' phai bang lan 1 (khong nhan doi).")


# ----------------------------------------------------------------------------- validate
def cmd_validate(_):
    manifest, pages = load_pages()
    by_id = {p["page_id"]: p for p in pages}
    qs = load_bench()
    problems = []
    ids = [q.get("id") for q in qs]
    if len(set(ids)) != len(ids):
        problems.append("id bi trung")
    dev = [q for q in qs if q.get("split") == "dev"]
    test = [q for q in qs if q.get("split") == "test"]
    filt = [q for q in qs if q.get("filter")]
    filt_test = [q for q in filt if q.get("split") == "test"]
    for q in qs:
        for field in ("id", "split", "question", "expected_answer", "gold_source_id", "gold_page", "evidence_quote"):
            if not q.get(field):
                problems.append(f"{q.get('id')}: thieu truong {field}")
        ev = norm(q.get("evidence_quote", ""))
        ok_page = False
        for gp in gold_pages(q):
            if gp not in by_id:
                problems.append(f"{q['id']}: gold_page '{gp}' khong co trong manifest")
            elif ev and ev in norm(by_id[gp]["text"]):
                ok_page = True
        if ev and not ok_page:
            problems.append(f"{q['id']}: evidence_quote KHONG nam nguyen van trong gold_page")
        for k, v in (q.get("filter") or {}).items():
            if k not in FILTER_KEYS:
                problems.append(f"{q['id']}: filter key '{k}' khong ho tro")
            elif not any(by_id[g].get(k) == v for g in gold_pages(q) if g in by_id):
                problems.append(f"{q['id']}: filter {k}='{v}' khong khop metadata cua gold_page")
    print(f"Tong: {len(qs)} cau | dev {len(dev)} | test {len(test)} | co filter {len(filt)} (test: {len(filt_test)})")
    kinds = {}
    for q in qs:
        kinds[q.get("type", "?")] = kinds.get(q.get("type", "?"), 0) + 1
    print("Loai cau:", kinds)
    if len(qs) < 20: problems.append("can >= 20 cau")
    if len(dev) < 15: problems.append("can >= 15 cau dev")
    if len(test) < 5: problems.append("can >= 5 cau test")
    if len(filt) < 3: problems.append("can >= 3 cau co filter")
    if len(filt_test) < 1: problems.append("can >= 1 cau test co filter")
    if problems:
        print("\nVAN DE:")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    print("Benchmark HOP LE.")


# ----------------------------------------------------------------------------- evaluate
def search(conn, qvec, strategy, flt):
    where, params = "strategy = %s", [strategy]
    for k, v in (flt or {}).items():
        if k in FILTER_KEYS:
            where += f" AND {k} = %s"
            params.append(v)
    v = vec_literal(qvec)
    sql = (f"SELECT chunk_id, page, source, part, chapter, text, 1 - (embedding <=> %s::vector) AS score "
           f"FROM chunks WHERE {where} ORDER BY embedding <=> %s::vector LIMIT {TOP_K}")
    return conn.execute(sql, [v] + params + [v]).fetchall()


def cmd_evaluate(_):
    qs = load_bench()
    RESULTS.mkdir(parents=True, exist_ok=True)
    model = load_model()
    qvecs = model.encode(["query: " + q["question"] for q in qs], normalize_embeddings=True)
    configs = [("A", "A", False), ("B", "B", False), ("C", "B", True)]
    metrics = []
    with connect() as conn:
        for name, store, use_filter in configs:
            n_rows = conn.execute("SELECT count(*) FROM chunks WHERE strategy=%s", (store,)).fetchone()[0]
            if n_rows == 0:
                sys.exit(f"LOI: chua co chunk strategy {store}. Chay 'ingest' truoc.")
            traces, t0 = [], time.time()
            for q, v in zip(qs, qvecs):
                flt = q.get("filter") if use_filter else None
                rows = search(conn, v, store, flt)
                ev, gold = norm(q["evidence_quote"]), set(gold_pages(q))
                top = []
                for rank, (cid, page, src, part, chap, text, score) in enumerate(rows, 1):
                    hit = page in gold and ev in norm(text)
                    top.append({"rank": rank, "chunk_id": cid, "page": page, "source": src, "part": part,
                                "chapter": chap, "score": round(float(score), 4), "hit": hit, "text": text})
                filter_ok = None
                if flt:
                    filter_ok = all(all(t.get(k) == val for k, val in flt.items()) for t in top)
                traces.append({"id": q["id"], "split": q["split"], "question": q["question"],
                               "filter_used": flt, "gold_page": sorted(gold), "evidence_quote": q["evidence_quote"],
                               "hit1": bool(top and top[0]["hit"]), "hit3": any(t["hit"] for t in top),
                               "filter_ok": filter_ok, "top3": top})
            secs = time.time() - t0
            with (RESULTS / f"trace_{name}.jsonl").open("w", encoding="utf-8") as f:
                for t in traces:
                    f.write(json.dumps(t, ensure_ascii=False) + "\n")
            for split in ("dev", "test", "all"):
                sub = [t for t in traces if split == "all" or t["split"] == split]
                if not sub:
                    continue
                fsub = [t for t in sub if t["filter_used"]]
                metrics.append({
                    "strategy": name, "split": split, "N": len(sub),
                    "hit1": f"{sum(t['hit1'] for t in sub)}/{len(sub)}",
                    "hit3": f"{sum(t['hit3'] for t in sub)}/{len(sub)}",
                    "filter_compliance": f"{sum(bool(t['filter_ok']) for t in fsub)}/{len(fsub)}" if fsub else "N/A",
                    "seconds_all_queries": round(secs, 2),
                })
    with (RESULTS / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(metrics[0].keys()))
        w.writeheader()
        w.writerows(metrics)
    print(f"{'Strat':6}{'Split':6}{'Hit@1':9}{'Hit@3':9}{'Filter':9}")
    for m in metrics:
        print(f"{m['strategy']:6}{m['split']:6}{m['hit1']:9}{m['hit3']:9}{m['filter_compliance']:9}")
    print("Da luu results/trace_A|B|C.jsonl va results/metrics.csv")


# ----------------------------------------------------------------------------- audit
def cmd_audit(_):
    _, pages = load_pages()
    RESULTS.mkdir(parents=True, exist_ok=True)
    # 1) Coherence: 10 page_id dau (sap xep), vi tri = giua trang; cham chunk A va B (C dung chunk B)
    sample = sorted(pages, key=lambda p: p["page_id"])[:10]
    rows = []
    for strategy in ("A", "B"):
        chunks = build_chunks(sample, strategy)
        for p in sample:
            pos = len(p["text"]) // 2
            same = [c for c in chunks if c["page"] == p["page_id"]]
            cover = [c for c in same if c["start_char"] <= pos < c["end_char"]]
            # vi tri co the roi vao khoang trong giua cac chunk (heading/dong trong) -> lay chunk gan nhat
            c = cover[0] if cover else min(same, key=lambda x: min(abs(x["start_char"] - pos), abs(x["end_char"] - pos)))
            rows.append([strategy, p["page_id"], pos, c["chunk_id"] if c else "", c["text"] if c else "", "", ""])
    with (RESULTS / "audit_coherence.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "page_id", "position_char", "chunk_id", "chunk_text", "score_0_1_2", "reason"])
        w.writerows(rows)
    # 2) Metadata + 3) Grounding: 5 cau test dau tien (theo id) x top-3 x A/B/C
    meta_rows, ground_rows = [], []
    for name in ("A", "B", "C"):
        tp = RESULTS / f"trace_{name}.jsonl"
        if not tp.exists():
            sys.exit("LOI: chua co trace. Chay 'evaluate' truoc.")
        tests = sorted((json.loads(l) for l in tp.read_text(encoding="utf-8").splitlines() if l.strip()),
                       key=lambda t: t["id"])
        tests = [t for t in tests if t["split"] == "test"][:5]
        for t in tests:
            for r in t["top3"]:
                meta_rows.append([name, t["id"], r["rank"], r["chunk_id"], r["source"], r["page"], r["part"],
                                  r["chapter"], ",".join(t["gold_page"]), "", "", "", ""])
            ground_rows.append([name, t["id"], t["question"], t["evidence_quote"], ",".join(t["gold_page"]),
                                " || ".join(f"[{r['rank']}] {r['page']}: {r['text']}" for r in t["top3"]), "", ""])
    with (RESULTS / "audit_metadata.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "qid", "rank", "chunk_id", "source", "page", "part", "chapter", "gold_page",
                    "source_ok", "page_ok", "part_ok", "note"])
        w.writerows(meta_rows)
    with (RESULTS / "audit_grounding.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "qid", "question", "evidence_quote", "gold_page", "top3_text",
                    "grounding_0_1_2", "reason"])
        w.writerows(ground_rows)
    print("Da tao results/audit_coherence.csv, audit_metadata.csv, audit_grounding.csv - hay tu cham cac cot trong.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["ingest", "validate", "evaluate", "audit"])
    args = ap.parse_args()
    {"ingest": cmd_ingest, "validate": cmd_validate, "evaluate": cmd_evaluate, "audit": cmd_audit}[args.cmd](args)


if __name__ == "__main__":
    main()