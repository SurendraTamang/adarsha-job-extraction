"""List every e-paper issue and its PDF link(s), rewrite dead hosts, HEAD-check each file.

  python discover.py      # resumable: issues already recorded are skipped
"""
import html
import re
import time

from common import SITE, connect, get, head_status, http_client, rewrite_url
from dates import parse_title

PDF_LINK = re.compile(r'https?://[^\s"\'<>]+?\.pdf', re.I)


def pdf_links(page_html):
    return sorted({u for u in PDF_LINK.findall(page_html)
                   if "RateCard" not in u and "Subscription" not in u})


def list_all(http, endpoint, **params):
    """Page through a WP REST collection (ordered by id so pages don't shift mid-listing).
    WP's X-WP-Total can exceed what it returns (planning run: media said 3,583, listed 3,578),
    so only a shortfall over 1% aborts."""
    items, page, total = [], 1, None
    while True:
        r = get(http, f"{SITE}/wp-json/wp/v2/{endpoint}", per_page=100, page=page,
                orderby="id", order="asc", **params)
        if r is None or r.status_code != 200:     # WP answers 400 past the last page
            break
        total = int(r.headers.get("X-WP-Total", 0))
        batch = r.json()
        if not batch:
            break
        items += batch
        page += 1
        time.sleep(0.5)
    if total is None or len(items) < total * 0.99:
        raise SystemExit(f"{endpoint}: listed {len(items)} of {total}; re-run discover.py")
    if len(items) < total:
        print(f"warning: {endpoint} listed {len(items)} of {total} (WP count mismatch)", flush=True)
    return items


def main():
    conn, http = connect(), http_client()
    issues = list_all(http, "epaper", _fields="id,date,title,link")
    media = {}
    for m in list_all(http, "media", mime_type="application/pdf", _fields="id,post,source_url"):
        media.setdefault(m["post"], []).append(m["source_url"])
    print(f"{len(issues)} issues, {sum(map(len, media.values()))} attached PDFs", flush=True)

    done = {r[0] for r in conn.execute("select wp_id from issues")}
    for n, e in enumerate(issues, 1):
        if e["id"] in done:
            continue
        title = html.unescape(e["title"]["rendered"])
        urls = media.get(e["id"])
        if not urls:
            r = get(http, e["link"])
            time.sleep(0.5)
            urls = pdf_links(r.text) if r is not None else []
        statuses = []
        for orig in urls:
            url = rewrite_url(orig)
            status = head_status(http, url)
            if status != 200 and url != orig and head_status(http, orig) == 200:
                url, status = orig, 200
            conn.execute("insert or ignore into pdfs (orig_url, url, http_status) values (?,?,?)",
                         (orig, url, status))
            pdf_id = conn.execute("select id from pdfs where url=?", (url,)).fetchone()[0]
            conn.execute("insert or ignore into pdf_posts values (?,?)", (pdf_id, e["id"]))
            statuses.append(status)
        bs = parse_title(title)
        status = "ok" if 200 in statuses else "dead" if urls else "no_link"
        conn.execute("insert into issues values (?,?,?,?,?,?)",
                     (e["id"], e["date"], title, e["link"], str(bs) if bs else None, status))
        conn.commit()
        if n % 100 == 0:
            print(f"{n}/{len(issues)}", flush=True)
    print(dict(conn.execute("select status, count(*) from issues group by status").fetchall()))


if __name__ == "__main__":
    main()
