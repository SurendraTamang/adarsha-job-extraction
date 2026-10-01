"""Shared paths, database schema, HTTP client and URL rules."""
import re
import sqlite3
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DB_PATH = DATA / "adarsha.db"
SITE = "https://www.eadarsha.com"
NEW_BUCKET = "https://eadarsha-epaper-new.s3.ap-south-1.amazonaws.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

SCHEMA = """
CREATE TABLE IF NOT EXISTS issues (
  wp_id INTEGER PRIMARY KEY, wp_date TEXT, title TEXT, link TEXT,
  title_bs TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS pdfs (
  id INTEGER PRIMARY KEY, orig_url TEXT, url TEXT UNIQUE, http_status INTEGER,
  sha256 TEXT, local_path TEXT, page_count INTEGER,
  masthead_bs TEXT, issue_bs TEXT, issue_ad TEXT, date_source TEXT,
  date_conflict INTEGER DEFAULT 0, duplicate_of INTEGER);
CREATE TABLE IF NOT EXISTS pdf_posts (
  pdf_id INTEGER, wp_id INTEGER, PRIMARY KEY (pdf_id, wp_id));
CREATE TABLE IF NOT EXISTS pages (
  pdf_id INTEGER, page_no INTEGER, jpg_path TEXT, PRIMARY KEY (pdf_id, page_no));
CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY, run TEXT, phase TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS triage (
  run TEXT, pdf_id INTEGER, page_no INTEGER, model TEXT, status TEXT,
  has_job_ads INTEGER, masthead_date TEXT, raw TEXT,
  input_tokens INTEGER, output_tokens INTEGER,
  PRIMARY KEY (run, pdf_id, page_no));
CREATE TABLE IF NOT EXISTS tiles (
  run TEXT, pdf_id INTEGER, page_no INTEGER, tile INTEGER,
  x0 INTEGER, y0 INTEGER, scale REAL, model TEXT, status TEXT, raw TEXT,
  input_tokens INTEGER, output_tokens INTEGER,
  PRIMARY KEY (run, pdf_id, page_no, tile));
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, run TEXT, model TEXT, pdf_id INTEGER, page_no INTEGER,
  ad_id TEXT, category TEXT, title TEXT, organization TEXT, location TEXT,
  positions_count TEXT, salary TEXT, qualifications TEXT, deadline_text TEXT,
  deadline_ad TEXT, deadline_derived INTEGER, contact TEXT, text_ne TEXT, text_en TEXT,
  bbox_page TEXT, crop_path TEXT, confidence REAL, dup_group_id INTEGER,
  first_seen TEXT, last_seen TEXT, source_pdf_url TEXT);
"""


def connect(path=DB_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


def migrate(conn):
    """Add columns introduced after a database was first created, idempotently."""
    for table, column, decl in (("jobs", "crop_ok", "INTEGER"),
                                ("jobs", "category_source", "TEXT")):
        cols = {r["name"] for r in conn.execute(f"pragma table_info({table})")}
        if column not in cols:
            conn.execute(f"alter table {table} add column {column} {decl}")
    conn.commit()


def http_client():
    # eadarsha.com answers 406 to non-browser user agents
    return httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True)


def get(http, url, **params):
    """GET with 3 tries; returns the response (any status < 500) or None."""
    for attempt in range(3):
        try:
            r = http.get(url, params=params or None)
            if r.status_code < 500:
                return r
        except httpx.TransportError:
            pass
        time.sleep(2 * (attempt + 1))
    return None


def head_status(http, url):
    try:
        return http.head(url).status_code
    except httpx.TransportError:
        return 0


_OLD_UPLOADS = re.compile(r"^https?://(www\.)?eadarsha\.com/wp-content/uploads/")


def rewrite_url(url):
    """Old wp-content PDFs and the retired bucket both moved to eadarsha-epaper-new."""
    url = _OLD_UPLOADS.sub(f"{NEW_BUCKET}/old/", url)
    return url.replace("https://eadarsha-epaper.s3.", "https://eadarsha-epaper-new.s3.")


def select_pdfs(conn, date_from=None, date_to=None, ids_file=None):
    """PDF rows picked by an id file, or by linked post date (YYYY-MM-DD, inclusive)."""
    if ids_file:
        ids = [int(x) for x in Path(ids_file).read_text().split()]
        return conn.execute(f"select * from pdfs where id in ({','.join('?' * len(ids))}) order by id",
                            ids).fetchall()
    return conn.execute(
        """select distinct p.* from pdfs p
           join pdf_posts pp on pp.pdf_id = p.id join issues i on i.wp_id = pp.wp_id
           where substr(i.wp_date, 1, 10) between ? and ? order by p.id""",
        (date_from or "0000", date_to or "9999")).fetchall()


PATH_COLUMNS = (("pdfs", "local_path"), ("pages", "jpg_path"), ("jobs", "crop_path"))


def relocate(db_path=DB_PATH, old_root=None, new_root=None):
    """Rewrite absolute paths that point at another machine's checkout.

    The database is committed to git but stores absolute paths, so a fresh clone needs
    them re-pointed at its own data/ directory before anything can open a crop or page.

      python common.py --relocate            # use the current checkout's ROOT
      python common.py --relocate --from /old/automations/adarsha
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    new_root = str(new_root or ROOT)
    old_root = str(old_root) if old_root else None
    changed = 0
    for table, column in PATH_COLUMNS:
        for row in conn.execute(f"select rowid, {column} from {table} where {column} is not null"):
            rid, v = row[0], row[1]
            new = v
            if old_root and v.startswith(old_root):
                new = v.replace(old_root, new_root, 1)
            elif not old_root and new_root not in v:
                # no source root given: rebind anything that looks like a data/ path
                i = v.find("/data/")
                if i != -1:
                    new = new_root + v[i:]
            if new != v:
                conn.execute(f"update {table} set {column}=? where rowid=?", (new, rid))
                changed += 1
    conn.commit()
    conn.close()
    print(f"relocated {changed} paths to {new_root}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--relocate", action="store_true")
    ap.add_argument("--from", dest="old_root")
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    relocate(a.db, a.old_root)
