"""Download discovered PDFs, fingerprint them, decode the masthead date, mark duplicate editions.

  python download.py --from 2026-08-30 --to 2026-09-30   # or --pdfs ids.txt, or no filter for all
"""
import argparse
import datetime
import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from common import DATA, connect, http_client, select_pdfs
from dates import parse_bs_iso, parse_masthead, resolve_issue_date
from render import page_count, page_text


def resolve_pdf_date(conn, pdf_id):
    """Set issue_bs/issue_ad/date_source/date_conflict from masthead, title and date of the first linked post."""
    pdf = conn.execute("select masthead_bs from pdfs where id=?", (pdf_id,)).fetchone()
    post = conn.execute(
        """select i.title_bs, i.wp_date from issues i join pdf_posts pp on pp.wp_id = i.wp_id
           where pp.pdf_id=? order by i.wp_date limit 1""", (pdf_id,)).fetchone()
    bs, source, conflict = resolve_issue_date(parse_bs_iso(pdf["masthead_bs"]), parse_bs_iso(post["title_bs"]),
                                              datetime.date.fromisoformat(post["wp_date"][:10]))
    conn.execute("update pdfs set issue_bs=?, issue_ad=?, date_source=?, date_conflict=? where id=?",
                 (str(bs), str(bs.to_datetime_date()), source, int(conflict), pdf_id))


def mark_duplicates(conn):
    """Keep one PDF per sha256 (lowest id). Same-date dedup is deliberately not done: in the real
    archive, 28 of 46 same-masthead-date pairs were different days (stale masthead left from the
    day before) or partial 'inner' files. Extra copies cost ~1% more extraction; repeated ads are
    grouped later in the audit."""
    conn.execute("update pdfs set duplicate_of = null")
    conn.execute("""update pdfs set duplicate_of = (select min(k.id) from pdfs k where k.sha256 = pdfs.sha256)
                    where local_path is not null
                      and id != (select min(k.id) from pdfs k where k.sha256 = pdfs.sha256)""")


def fetch(http, url, tmp):
    with http.stream("GET", url) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)


def download_one(http, out, url, pdf_id):
    """Fetch one PDF into data/pdfs/<sha256>.pdf. Returns (sha, path, pages, masthead) or an error string."""
    tmp = out / f"{pdf_id}.part"
    try:
        fetch(http, url, tmp)
    except httpx.HTTPError as e:
        return f"failed: {e}"
    sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
    dest = out / f"{sha}.pdf"
    tmp.replace(dest)
    try:
        pages = page_count(dest)
    except subprocess.CalledProcessError:
        dest.unlink(missing_ok=True)
        return "not a PDF"
    return sha, dest, pages, parse_masthead(page_text(dest))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--pdfs")
    ap.add_argument("--workers", type=int, default=5)   # files are on S3, not the newspaper's server
    a = ap.parse_args()
    conn, http = connect(), http_client()
    out = DATA / "pdfs"
    out.mkdir(parents=True, exist_ok=True)
    # status 0 = timed out during discovery; worth another try
    todo = [p for p in select_pdfs(conn, a.date_from, a.date_to, a.pdfs)
            if p["local_path"] is None and p["http_status"] in (0, 200)]
    with ThreadPoolExecutor(a.workers) as pool:
        futures = {pool.submit(download_one, http, out, p["url"], p["id"]): p for p in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            p, res = futures[fut], fut.result()
            if isinstance(res, str):
                print(f"[{n}/{len(todo)}] {res} {p['url']}", flush=True)
                if res == "not a PDF":
                    conn.execute("update pdfs set http_status=-1 where id=?", (p["id"],))
                    conn.commit()
                continue
            sha, dest, pages, masthead = res
            conn.execute("update pdfs set http_status=200, sha256=?, local_path=?, page_count=?, masthead_bs=? where id=?",
                         (sha, str(dest), pages, str(masthead) if masthead else None, p["id"]))
            resolve_pdf_date(conn, p["id"])
            # a status-0 (timed out) link that now downloaded makes its issue usable
            conn.execute("""update issues set status='ok' where status='dead'
                            and wp_id in (select wp_id from pdf_posts where pdf_id=?)""", (p["id"],))
            conn.commit()
            print(f"[{n}/{len(todo)}] {pages}p masthead={masthead} {p['url'].rsplit('/', 1)[-1]}", flush=True)
    mark_duplicates(conn)
    conn.commit()


if __name__ == "__main__":
    main()
