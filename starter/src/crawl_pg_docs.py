"""Phase 1 - Crawl PostgreSQL 16 documentation -> cleaned page units + manifest + log.

Chay tu thu muc starter/:   python -m src.crawl_pg_docs

Dau ra (tinh theo thu muc goc repo):
  data/raw_html/<page_id>.html   HTML goc (cache, khong can commit)
  data/pages/<page_id>.txt       van ban da chuan hoa (chi cac trang hop le)
  data/legal_notice.txt          trang Legal Notice cua docs v16 (bang chung giay phep)
  data/manifest.json             manifest theo GUIDE.md
  results/ingest_log.csv         log tung trang: kept / skipped_short / skipped_empty / error
"""
import csv
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.postgresql.org/docs/16/"
ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw_html"
PAGES_DIR = ROOT / "data" / "pages"
MANIFEST_PATH = ROOT / "data" / "manifest.json"
LEGAL_PATH = ROOT / "data" / "legal_notice.txt"
LOG_PATH = ROOT / "results" / "ingest_log.csv"

MIN_CHARS = 1500   # nguong don vi nguon theo GUIDE.md (HTML khong phan trang)
DELAY_S = 0.7      # nghi giua cac request cho lich su
HEADERS = {"User-Agent": "Day06-lab-student-crawler (educational use)"}

# Slug cac chuong (phan truoc .html). Script se doi chieu voi muc luc v16 va bao loi neu sai.
CHAPTERS = [
    "indexes",              # Part II  - The SQL Language
    "mvcc",                 # Part II  - Concurrency Control
    "performance-tips",     # Part II  - Performance Tips
    "maintenance",          # Part III - Routine Database Maintenance Tasks
    "backup",               # Part III - Backup and Restore
    "high-availability",    # Part III - High Availability, Load Balancing, and Replication
    "wal",                  # Part III - Reliability and the Write-Ahead Log
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s).replace("\xa0", " ")
    return " ".join(s.split())


def fetch(url: str, cache_name: str) -> str:
    """Tai trang (co cache). Loi mang -> raise, khong am tham bo qua."""
    path = RAW_DIR / f"{cache_name}.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(resp.text, encoding="utf-8")
            time.sleep(DELAY_S)
            return resp.text
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed after 3 tries: {url} ({last_err})")


def parse_toc(index_html: str):
    """Tra ve (dict slug -> (part_title, chapter_title), version phat hien)."""
    soup = BeautifulSoup(index_html, "lxml")
    m = re.search(r"PostgreSQL (16\.\d+)", soup.title.get_text() if soup.title else "")
    version = m.group(1) if m else None
    part, chapters = None, {}
    for dt in soup.select("dl.toc dt"):
        span = dt.find("span", recursive=False)
        a = dt.find("a")
        if span is None or a is None:
            continue
        classes = span.get("class", [])
        title = norm(a.get_text())
        slug = a.get("href", "").split("#")[0].removesuffix(".html")
        if "part" in classes:
            part = title
        elif "chapter" in classes and part:
            chapters[slug] = (part, title)
    return chapters, version


def section_slugs(chapter_html: str):
    soup = BeautifulSoup(chapter_html, "lxml")
    out = []
    for a in soup.select("dl.toc dt span.sect1 a"):
        out.append(a.get("href", "").split("#")[0].removesuffix(".html"))
    return out


def extract_text(html: str):
    """Tra ve (tieu de trang, van ban chuan hoa co tieu de dang '## ...')."""
    soup = BeautifulSoup(html, "lxml")
    for sel in (".navheader", ".navfooter", "script", "style"):
        for t in soup.select(sel):
            t.decompose()
    root = (soup.select_one("#docContent") or soup.select_one("div.sect1")
            or soup.select_one("div.chapter") or soup.body)
    if root is None:
        return "", ""
    for t in root.select("div.toc"):
        t.decompose()
    blocks, title = [], ""
    for el in root.find_all(["h1", "h2", "h3", "h4", "pre", "p", "li", "table"]):
        if el.name != "table" and el.find_parent("table"):
            continue
        if el.name[0] == "h":
            text = norm(el.get_text())
            if text:
                title = title or text
                blocks.append("#" * int(el.name[1]) + " " + text)
        elif el.name == "pre":
            lines = [ln.rstrip() for ln in unicodedata.normalize("NFC", el.get_text()).splitlines()]
            code = "\n".join(lines).strip("\n")
            if code:
                blocks.append("```\n" + code + "\n```")
        elif el.name == "table":
            rows = []
            for tr in el.find_all("tr"):
                cells = [norm(c.get_text()) for c in tr.find_all(["th", "td"])]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append("\n".join(rows))
        elif el.name == "li":
            if el.find(["p", "pre", "ul", "ol", "table"]):
                continue  # noi dung nam trong khoi con, se duoc xu ly rieng
            text = norm(el.get_text())
            if text:
                blocks.append("- " + text)
        else:  # p
            text = norm(el.get_text())
            if text:
                blocks.append(text)
    return title, "\n\n".join(blocks)


def main():
    print(f"Docs: {BASE}  | goc repo: {ROOT}")
    index_html = fetch(BASE + "index.html", "index")
    toc, version = parse_toc(index_html)
    if not toc:
        sys.exit("LOI: khong doc duoc muc luc (dl.toc). Kiem tra lai cau truc HTML trang index.")
    print(f"Phien ban phat hien: {version}; {len(toc)} chuong trong muc luc")

    accessed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log_rows, pages = [], []
    chapter_info = []

    for slug in CHAPTERS:
        if slug not in toc:
            print(f"  [LOI] slug '{slug}' khong co trong muc luc v16 -> sua CHAPTERS")
            words = [w for w in re.split(r"[-_]", slug) if len(w) > 3]
            hints = [f"{s} ({t[1]})" for s, t in toc.items()
                     if any(w in s.lower() or w in t[1].lower() for w in words)]
            if hints:
                print("        goi y slug gan giong:", "; ".join(hints[:6]))
            log_rows.append([slug, BASE + slug + ".html", "error", 0, "slug not in TOC"])
            continue
        part_full, ch_title = toc[slug]
        m = re.match(r"(?:Part\s+)?([IVXL]+)\.\s*(.+)", part_full)
        part_no, part_name = (m.group(1), m.group(2)) if m else ("", part_full)
        chapter_name = re.sub(r"^\d+\.\s*", "", ch_title)
        chapter_info.append({"slug": slug, "chapter": ch_title, "part": part_full})
        print(f"- {part_full} > {ch_title}")

        try:
            ch_html = fetch(BASE + slug + ".html", slug)
        except RuntimeError as e:
            log_rows.append([slug, BASE + slug + ".html", "error", 0, str(e)])
            print("  [LOI]", e)
            continue
        page_ids = list(dict.fromkeys([slug] + section_slugs(ch_html)))

        for pid in page_ids:
            url = BASE + pid + ".html"
            try:
                html = ch_html if pid == slug else fetch(url, pid)
                title, text = extract_text(html)
            except RuntimeError as e:
                log_rows.append([pid, url, "error", 0, str(e)])
                print("  [LOI]", e)
                continue
            chars = len(text)
            if chars == 0:
                log_rows.append([pid, url, "skipped_empty", 0, "no text extracted"])
            elif chars < MIN_CHARS:
                log_rows.append([pid, url, "skipped_short", chars, f"< {MIN_CHARS} chars"])
            else:
                PAGES_DIR.mkdir(parents=True, exist_ok=True)
                (PAGES_DIR / f"{pid}.txt").write_text(text, encoding="utf-8")
                log_rows.append([pid, url, "kept", chars, ""])
                pages.append({
                    "page_id": pid, "url": url,
                    "part": part_name, "part_no": part_no,
                    "chapter": chapter_name, "section_title": title,
                    "chars": chars,
                })

    # Trang Legal Notice lam bang chung giay phep
    legal_url = BASE + "legalnotice.html"
    legal_status = "ok"
    try:
        _, legal_text = extract_text(fetch(legal_url, "legalnotice"))
        LEGAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        LEGAL_PATH.write_text(legal_text, encoding="utf-8")
    except RuntimeError as e:
        legal_status = f"error: {e}"
        print("  [CANH BAO] khong tai duoc Legal Notice:", e)

    manifest = {
        "source_id": "pg16-docs",
        "title": "PostgreSQL 16 Documentation",
        "source_path_or_url": BASE,
        "version": version or "16 (khong phat hien duoc ban phu)",
        "license_or_permission": "Xem Legal Notice cua docs v16 (data/legal_notice.txt)",
        "legal_notice_url": legal_url,
        "legal_notice_fetch": legal_status,
        "accessed_at": accessed_at,
        "page_counting_rule": (f"Moi trang section HTML la 1 don vi nguon (page_id = slug). "
                               f"Chi tinh trang co >= {MIN_CHARS} ky tu sau chuan hoa; "
                               f"da bo menu/breadcrumb/footer va muc luc con."),
        "min_chars_per_unit": MIN_CHARS,
        "chapters": chapter_info,
        "counts": {
            "units_total_seen": len(log_rows),
            "units_kept": len(pages),
            "total_chars_kept": sum(p["chars"] for p in pages),
        },
        "pages": pages,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["page_id", "url", "status", "chars", "note"])
        w.writerows(log_rows)

    # Tong ket
    print("\n=== TONG KET ===")
    by_part = {}
    for p in pages:
        by_part[p["part"]] = by_part.get(p["part"], 0) + 1
    for part, n in by_part.items():
        print(f"  {part}: {n} trang hop le")
    skipped = [r for r in log_rows if r[2] != "kept"]
    print(f"  Hop le: {len(pages)} | Bi loai/loi: {len(skipped)} (xem {LOG_PATH})")
    print(f"  Tong ky tu: {manifest['counts']['total_chars_kept']}")
    if len(pages) < 30:
        print("  [CANH BAO] chua du 30 don vi -> them chuong vao CHAPTERS roi chay lai")
    if len(by_part) < 2:
        print("  [CANH BAO] can it nhat 2 Part khac nhau de lam filter")


if __name__ == "__main__":
    main()