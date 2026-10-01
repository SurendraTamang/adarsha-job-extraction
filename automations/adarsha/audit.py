"""Content audit of an extraction run, and the comparison between runs.

  python audit.py report  --run cc                 # -> data/audit_cc.md
  python audit.py compare --runs cc cc-opus        # -> data/pilot_compare.md (+ data/groundtruth.csv to fill)
"""
import argparse
import csv
import os
import random
import re
from collections import Counter, defaultdict
from datetime import date

from common import DATA, connect
from extract import similar

EMPTY = {"", "none", "n/a", "null", "-"}
PLACEHOLDER = re.compile(r"company name|\bxyz\b|\[.*?\]|lorem|placeholder", re.I)
FIELDS = ["category", "title", "organization", "location", "positions_count", "salary", "qualifications",
          "deadline_text", "deadline_ad", "contact", "text_ne", "text_en"]
EXPECTED = ["title", "organization", "contact", "text_ne", "text_en"]   # nearly every real ad shows these
ERAS = ("2012–2019", "2020+")


def empty(v):
    return v is None or str(v).strip().lower() in EMPTY


def pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "n/a"


def norm(s):
    return re.sub(r"\W+", " ", s or "").strip().lower()


def era(issue_ad):
    return ERAS[0] if (issue_ad or "") < "2020" else ERAS[1]


def rel(path):
    return os.path.relpath(path, DATA) if path else ""


def assign_dup_groups(conn, run):
    """Same organization+title within 14 days of the group's last sighting = the same ad re-run."""
    rows = conn.execute(
        """select j.id, j.organization, j.title, p.issue_ad from jobs j join pdfs p on p.id = j.pdf_id
           where j.run=? order by p.issue_ad, j.id""", (run,)).fetchall()
    open_groups, groups = {}, []
    for r in rows:
        key = (norm(r["organization"]), norm(r["title"]))
        g = open_groups.get(key) if any(key) else None
        if g is None or (date.fromisoformat(r["issue_ad"]) - date.fromisoformat(g["last"])).days > 14:
            g = {"id": r["id"], "first": r["issue_ad"], "last": r["issue_ad"], "jobs": []}
            groups.append(g)
            if any(key):
                open_groups[key] = g
        g["last"] = r["issue_ad"]
        g["jobs"].append(r["id"])
    for g in groups:
        conn.executemany("update jobs set dup_group_id=?, first_seen=?, last_seen=? where id=?",
                         [(g["id"], g["first"], g["last"], j) for j in g["jobs"]])
    conn.commit()


def report(conn, run):
    assign_dup_groups(conn, run)
    jobs = conn.execute("""select j.*, p.issue_ad, p.issue_bs from jobs j join pdfs p on p.id = j.pdf_id
                           where j.run=?""", (run,)).fetchall()
    n = len(jobs)
    tri = conn.execute("select count(*), sum(has_job_ads) from triage where run=? and status='done'", (run,)).fetchone()
    todo = DATA / "cc" / run / "todo.tsv"
    planned = len(todo.read_text().split("\n")) - 1 if todo.exists() else "?"
    bad = len(list((DATA / "cc" / run).glob("*.bad")))
    by_status = dict(conn.execute("select status, count(*) from issues group by status").fetchall())
    conflicts = conn.execute("""select count(*) from pdfs p where date_conflict=1 and exists
                                (select 1 from triage t where t.run=? and t.pdf_id=p.id)""", (run,)).fetchone()[0]

    L = [f"# Audit — run `{run}`", "", "## Limitations (read first)", "",
         f"- Pages read: {tri[0]} of {planned} prepared; {bad} answers were malformed and must be redone.",
         f"- Pages with job ads: {tri[1] or 0}. Whether any ad pages were missed is only known from the "
         "ground-truth sheet (`audit.py compare`).",
         f"- Archive gaps: {by_status.get('dead', 0)} issues with dead links, {by_status.get('no_link', 0)} with no PDF.",
         f"- PDFs in this run whose date sources disagree: {conflicts}.", ""]

    L += [f"## Fields ({n} jobs)", "", "| Field | Empty | Placeholder-like | Kind |", "|---|---|---|---|"]
    for f in FIELDS:
        e = sum(empty(j[f]) for j in jobs)
        ph = sum(bool(PLACEHOLDER.search(str(j[f] or ""))) for j in jobs)
        L.append(f"| {f} | {pct(e, n)} | {pct(ph, n)} | {'expected' if f in EXPECTED else 'conditional'} |")
    same = sum(1 for j in jobs if j["text_ne"] and j["text_ne"] == j["text_en"])
    odd = sum(1 for j in jobs if j["text_ne"] and j["text_en"]
              and not 0.3 <= len(j["text_en"]) / len(j["text_ne"]) <= 3)
    L += ["", f"- text_en identical to text_ne: {same}; translation length ratio outside 0.3–3: {odd}",
          "- Categories: " + ", ".join(f"{k} {v}" for k, v in Counter(j["category"] for j in jobs).most_common()),
          f"- Deadlines parsed to a date: {pct(sum(not empty(j['deadline_ad']) for j in jobs), sum(not empty(j['deadline_text']) for j in jobs))} of ads that print one"]

    groups = Counter(j["dup_group_id"] for j in jobs)
    L += ["", "## Distinctness", "",
          f"- {n} job rows = {len(groups)} distinct ads over time; {sum(c > 1 for c in groups.values())} "
          f"appeared more than once (max {max(groups.values(), default=0)}).", ""]

    random.seed(0)
    L += ["## Spot check (mark each right / wrong)", ""]
    for j in random.sample(list(jobs), min(30, n)):
        page = conn.execute("select jpg_path from pages where pdf_id=? and page_no=?",
                            (j["pdf_id"], j["page_no"])).fetchone()
        L += [f"### job {j['id']} — {j['issue_bs']} p{j['page_no']} [{j['category']}]  ☐ right ☐ wrong", "",
              f"![crop]({rel(j['crop_path'])}) — [full page]({rel(page['jpg_path'] if page else '')})", "",
              f"- title: {j['title']}", f"- organization: {j['organization']}", f"- location: {j['location']}",
              f"- deadline: {j['deadline_text']} → {j['deadline_ad']}{' (derived)' if j['deadline_derived'] else ''}",
              f"- contact: {j['contact']}", f"- text_en: {j['text_en']}", ""]
    path = DATA / f"audit_{run}.md"
    path.write_text("\n".join(L))
    print(path)


def groundtruth(conn, run):
    """15 random pages (10 modern, 5 older), picked regardless of the model's answer, for a manual ad count."""
    path = DATA / "groundtruth.csv"
    if not path.exists():
        pages = conn.execute("""select t.pdf_id, t.page_no, pg.jpg_path, p.issue_ad from triage t
                                join pages pg on pg.pdf_id = t.pdf_id and pg.page_no = t.page_no
                                join pdfs p on p.id = t.pdf_id where t.run=?""", (run,)).fetchall()
        random.seed(1)
        sample = []
        for e, k in zip(ERAS, (5, 10)):
            pool = [p for p in pages if era(p["issue_ad"]) == e]
            sample += random.sample(pool, min(k, len(pool)))
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["pdf_id", "page_no", "jpg_path", "job_ad_count"])
            for p in sample:
                w.writerow([p["pdf_id"], p["page_no"], p["jpg_path"], ""])
        print(f"Open each page in {path}, fill job_ad_count (0 if none), then re-run compare.")
    return [r for r in csv.DictReader(open(path)) if r["job_ad_count"].strip()]


def compare(conn, runs):
    for run in runs:
        assign_dup_groups(conn, run)
    L = [f"# Comparison: {' vs '.join(runs)}", "", "## Per run and era", "",
         "| Run | Era | Pages | With ads | Jobs | Jobs per ad page | Expected fields filled | Masthead dates |",
         "|---|---|---|---|---|---|---|---|"]
    for run in runs:
        tri = conn.execute("""select t.*, p.issue_ad, p.date_source from triage t join pdfs p on p.id = t.pdf_id
                              where t.run=? and t.status='done'""", (run,)).fetchall()
        jobs = conn.execute("""select j.*, p.issue_ad from jobs j join pdfs p on p.id = j.pdf_id
                               where j.run=?""", (run,)).fetchall()
        for e in ERAS:
            t = [r for r in tri if era(r["issue_ad"]) == e]
            js = [j for j in jobs if era(j["issue_ad"]) == e]
            pos = sum(r["has_job_ads"] == 1 for r in t)
            fill = pct(sum(not empty(j[f]) for j in js for f in EXPECTED), len(js) * len(EXPECTED))
            p1 = [r for r in t if r["page_no"] == 1]
            mast = pct(sum(r["date_source"] == "masthead" for r in p1), len(p1))
            L.append(f"| {run} | {e} | {len(t)} | {pos} | {len(js)} | {len(js) / pos if pos else 0:.1f} | {fill} | {mast} |")

    if len(runs) == 2:
        a, b = runs
        flips = conn.execute(
            """select x.pdf_id, x.page_no, x.has_job_ads ha, y.has_job_ads hb, pg.jpg_path from triage x
               join triage y on y.pdf_id = x.pdf_id and y.page_no = x.page_no and y.run=?
               join pages pg on pg.pdf_id = x.pdf_id and pg.page_no = x.page_no
               where x.run=? and x.has_job_ads != y.has_job_ads""", (b, a)).fetchall()
        L += ["", f"## Pages where the runs disagree on ads ({len(flips)}) — look at these", ""]
        L += [f"- pdf {r['pdf_id']} p{r['page_no']}: {a}={r['ha']} {b}={r['hb']} → {rel(r['jpg_path'])}" for r in flips]
        ja = [dict(j) for j in conn.execute("select * from jobs where run=?", (a,))]
        by_page = defaultdict(list)
        for j in conn.execute("select * from jobs where run=?", (b,)):
            by_page[(j["pdf_id"], j["page_no"])].append(dict(j))
        nb = sum(map(len, by_page.values()))
        pairs = []
        for j in ja:
            cands = by_page[(j["pdf_id"], j["page_no"])]
            m = next((c for c in cands if similar(f"{j['organization']} {j['title']}",
                                                  f"{c['organization']} {c['title']}")), None)
            if m:
                cands.remove(m)
                pairs.append((j, m))
        L += ["", "## Matched jobs", "", f"- {len(pairs)} matched ({len(ja)} in {a}, {nb} in {b})"]
        for f in ("title", "organization", "deadline_ad"):
            L.append(f"- {f} identical: {pct(sum(norm(x[f]) == norm(y[f]) for x, y in pairs), len(pairs))}")

    gt = groundtruth(conn, runs[0])
    L += ["", "## Ground truth (manual counts)", ""]
    if not gt:
        L.append("- data/groundtruth.csv not filled yet.")
    for run in runs:
        with_ads = [r for r in gt if int(r["job_ad_count"]) > 0]
        caught = sum(bool(conn.execute(
            "select 1 from triage where run=? and pdf_id=? and page_no=? and has_job_ads=1",
            (run, int(r["pdf_id"]), int(r["page_no"]))).fetchone()) for r in with_ads)
        found = sum(conn.execute("select count(distinct ad_id) from jobs where run=? and pdf_id=? and page_no=?",
                                 (run, int(r["pdf_id"]), int(r["page_no"]))).fetchone()[0] for r in gt)
        truth = sum(int(r["job_ad_count"]) for r in gt)
        if gt:
            L.append(f"- {run}: ad pages caught {pct(caught, len(with_ads))} of {len(with_ads)} "
                     f"(of {len(gt)} checked); ads found {found} vs {truth} counted by hand.")
    path = DATA / "pilot_compare.md"
    path.write_text("\n".join(L))
    print(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["report", "compare"])
    ap.add_argument("--run")
    ap.add_argument("--runs", nargs="+")
    a = ap.parse_args()
    conn = connect()
    if a.cmd == "report":
        report(conn, a.run)
    else:
        compare(conn, a.runs)


if __name__ == "__main__":
    main()
