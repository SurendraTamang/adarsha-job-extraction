"""Vision audit helpers driven by `opencode run` (default model: space-bunny-free).

  python vision_audit.py groundtruth            # fill data/groundtruth.csv job_ad_count
  python vision_audit.py spotcheck              # mark the 30 jobs in data/audit_cc.md

Counts are produced by a vision model, not a human: `audit.py` wants hand counts, so treat
these as a second opinion and the spot-check marks as needing review. Both steps cache to
data/vision_<kind>.json and are resumable.
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import DATA, connect

MODEL = "opencode/space-bunny-free"

COUNT_PROMPT = """List the job advertisements on this newspaper page.
A job ad is a boxed notice that hires someone: private vacancies (आवश्यकता, कर्मचारी चाहियो, Staff Wanted),
government or public vacancy notices (पदपूर्ति, दरखास्त आह्वान), foreign employment / manpower ads,
or training, internship and scholarship calls.
NOT job ads: news articles, tenders, public warnings, lost-document notices, missing-person notices,
things for sale or for rent, study-abroad or consultancy promotions, student admission notices,
horoscopes, and boxed advertisements that only sell a product or a service.
The first image is the whole page. The next 4 images are its quarters at high resolution, in order
0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right. Small classified boxes count as ads.
Walk the classified section box by box so none is missed. Ads sharing one outer box count once each.

Output format, and nothing else: first a line `COUNT: n`, then one line per ad as
`n. <short label in the ad's own words>`. No commentary, no reasoning."""

VERIFY_PROMPT = """You are checking one extracted job record against the newspaper image it came from.
Image 1 is the crop that was saved for this ad. Image 2 is the full page, and images 3-6 are its
quarters at high resolution (0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right).

Extracted record:
  title: {title}
  organization: {organization}
  location: {location}
  positions_count: {positions_count}
  salary: {salary}
  deadline: {deadline_text}
  contact: {contact}
  extracted text: {text_ne}

Answer these, each on its own line, with no other text:
FIELDS: one of CORRECT, WRONG, or UNSURE, saying whether the record's fields match the text printed in the ad
CROP: one of MATCHES, WRONG_AD, or UNCLEAR, saying whether the crop really shows this same ad
MISSING: one of NONE, or a short phrase naming any job ad visible on the page that this record does not cover
"""


def run(prompt, images, model=MODEL):
    """One `opencode run` call; returns the reply text or None on failure."""
    cmd = ["opencode", "run", prompt, "-m", model, "--format", "json"]
    for img in images:
        cmd += ["-f", str(img)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return None
    texts = []
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "text":
            texts.append(ev["part"]["text"])
    return "\n".join(texts).strip() or None


def page_images(pdf_id, page_no):
    imgs = [DATA / "pages" / str(pdf_id) / f"p{page_no}.jpg"]
    imgs += [DATA / "tiles" / str(pdf_id) / f"{page_no}-{i}.jpg" for i in range(4)]
    return [i for i in imgs if i.exists()]


def load_cache(kind):
    path = DATA / f"vision_{kind}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_cache(kind, cache):
    (DATA / f"vision_{kind}.json").write_text(json.dumps(cache, indent=1, ensure_ascii=False))


def cmd_groundtruth(workers):
    path = DATA / "groundtruth.csv"
    rows = list(csv.DictReader(path.open()))
    cache = load_cache("groundtruth")
    for r in rows:
        r["key"] = f"{r['pdf_id']}-{r['page_no']}"
    todo = [r for r in rows if not r["job_ad_count"].strip() and r["key"] not in cache]

    def work(r):
        key = r["key"]
        imgs = page_images(r["pdf_id"], r["page_no"])
        out = run(COUNT_PROMPT, imgs)
        m = re.search(r"COUNT:\s*(\d+)", out or "")
        n = int(m.group(1)) if m else None
        listed = len(re.findall(r"^\s*\d+[.)]\s", out or "", re.M))
        return key, n, listed, out

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for key, n, listed, raw in ex.map(work, todo):
                cache[key] = {"count": n, "listed": listed, "raw": raw}
                save_cache("groundtruth", cache)
                print(f"{key}: count={n} listed={listed}", flush=True)

    for r in rows:
        c = cache.get(r["key"], {})
        n = c.get("count")
        # trust the enumerated list when the stated count and the list disagree
        if n is not None and c.get("listed") and c["listed"] != n:
            n = c["listed"]
        if n is not None:
            r["job_ad_count"] = str(n)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pdf_id", "page_no", "jpg_path", "job_ad_count"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}")


CROP_PROMPT = """The image is one cropped advertisement cut out of a Nepali newspaper page.
The text below was extracted from a DIFFERENT part of the page, not from this crop.

extracted text:
{text_ne}

Does this crop actually show the advertisement described above?
Answer with one line, nothing else:
MATCH: yes if this crop is that same advertisement (same words, same advertiser, same roles)
MATCH: no if this crop is a different advertisement, or is not a job ad at all
"""

SPOT_RE = {"FIELDS": ("CORRECT", "WRONG", "UNSURE"),
           "CROP": ("MATCHES", "WRONG_AD", "UNCLEAR"),
           "MISSING": None}


RECLASS_PROMPT = """The image is one advertisement cut from a Nepali newspaper. The text under it was
extracted from the page.

{text_ne}

Decide whether this advertisement is a genuine JOB-RELATED notice, using this rule:
STUDY-ABROAD AND COURSE-CATALOGUE ADS ARE NOT JOB ADS. Exclude an institute that merely advertises
its own standing courses or sells study-abroad placement, even when those courses lead to work.
Signs: it lists courses instead of recruiting trainees ("courses:", a menu of Basic/Diploma/Hardware,
"कोर्स पनि गरिन्छ", "हामी कहाँ ... अध्ययन"), quotes fees or "IELTS/TOEFL NOT NEEDED", markets a
student visa or "Study in <country>", or names an overseas degree.
Do NOT exclude a training notice that really calls for applicants or trainees: a government or
CTEVT-recognised free course, an admission with seats and eligibility, an application deadline, or
preparation for a named job ("भर्ती तयारी", security guard, cook/waiter, beautician, radio
presenter) tied to placements.

Answer exactly two lines, nothing else:
JOB: yes or no
REASON: under 12 words"""


def cmd_reclass(workers, category, votes):
    """Re-judge the category-boundary ads under the tightened rule and flag, never delete."""
    from common import connect
    conn = connect()
    cache = load_cache("reclass")
    rows = conn.execute("select id, ad_id, title, text_ne, crop_path from jobs where run='cc' and category=?"
                       , (category,)).fetchall()
    seen = {r["ad_id"]: r for r in rows}

    def work(ad_id):
        r = seen[ad_id]
        p = Path(r["crop_path"])
        if not p.exists():
            return ad_id, None, "crop missing"
        tally, last = {"yes": 0, "no": 0}, ""
        for _ in range(votes):
            out = run(RECLASS_PROMPT.format(text_ne=r["text_ne"][:1200]), [p])
            m = re.search(r"JOB:\s*(yes|no)", out or "", re.I)
            if m:
                tally[m.group(1).lower()] += 1
            why = re.search(r"REASON:\s*(.+)", out or "")
            if why:
                last = why.group(1).strip()
        if not sum(tally.values()):
            return ad_id, None, last
        return ad_id, ("yes" if tally["yes"] > tally["no"] else "no"), f"{last} [{tally['yes']}y/{tally['no']}n]"

    todo = sorted({r["ad_id"] for r in rows} - set(cache))
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for ad_id, v, why in ex.map(work, todo):
                cache[ad_id] = {"job": v, "reason": why}
                save_cache("reclass", cache)
                print(f"{ad_id}: job={v} ({why})", flush=True)

    for ad_id, c in cache.items():
        if c.get("job") in ("yes", "no"):
            conn.execute("update jobs set category_source=? where ad_id=? and run='cc'",
                         (f"reclass:{'keep' if c['job'] == 'yes' else 'EXCLUDE'}", ad_id))
    conn.commit()
    drop = [a for a, c in cache.items() if c.get("job") == "no"]
    keep = [a for a, c in cache.items() if c.get("job") == "yes"]
    rows_n = conn.execute("select count(*) from jobs where run='cc' and ad_id in (%s)"
                          % ",".join("?" * len(drop)), drop).fetchone()[0] if drop else 0
    print(f"\nad ids: {len(keep)} keep, {len(drop)} should be EXCLUDED")
    print(f"job rows that would be dropped: {rows_n}")
    for a in drop:
        print(f"  {a}: {cache[a]['reason']}")


def cmd_verify(workers, votes):
    """Majority-vote the crop/text check per ad and record the result in jobs.crop_ok.

    crop_ok: 1 = crop matches the ad, 0 = crop is a different ad, NULL = not checked.
    A single sample is not reliable (the checker flip-flops), so take `votes` samples.
    """
    from common import connect
    conn = connect()
    cache = load_cache("verify")
    rows = conn.execute("select id, text_ne, crop_path from jobs where run='cc' order by id").fetchall()

    def work(r):
        jid, text, path = r["id"], r["text_ne"], Path(r["crop_path"])
        if not path.exists():
            return jid, 0
        tally = {"yes": 0, "no": 0}
        for _ in range(votes):
            out = run(CROP_PROMPT.format(text_ne=text[:1200]), [path])
            m = re.search(r"MATCH:\s*(yes|no)", out or "", re.I)
            if m:
                tally[m.group(1).lower()] += 1
        if not sum(tally.values()):
            return jid, None
        return jid, 1 if tally["yes"] > tally["no"] else 0

    todo = [r for r in rows if str(r["id"]) not in cache]
    print(f"{len(rows)} ads, {len(todo)} to check, {votes} votes each", flush=True)
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, (jid, ok) in enumerate(ex.map(work, todo), 1):
                cache[str(jid)] = {"crop_ok": ok}
                save_cache("verify", cache)
                if i % 10 == 0 or ok == 0:
                    print(f"  {i}/{len(todo)} last={jid} crop_ok={ok}", flush=True)

    for jid, c in cache.items():
        if c.get("crop_ok") is not None:
            conn.execute("update jobs set crop_ok=? where id=?", (c["crop_ok"], int(jid)))
    conn.commit()
    n = conn.execute("select count(*) from jobs where run='cc'").fetchone()[0]
    ok = conn.execute("select count(*) from jobs where run='cc' and crop_ok=1").fetchone()[0]
    bad = conn.execute("select count(*) from jobs where run='cc' and crop_ok=0").fetchone()[0]
    print(f"\nverified {ok + bad}/{n}: {ok} ok, {bad} MISMATCHED")
    for r in conn.execute("select id, ad_id, title from jobs where run='cc' and crop_ok=0 order by id"):
        print(f"  job {r['id']} {r['ad_id']} {r['title'][:40]}")


def cmd_crops(workers, limit):
    """Check every ad in a run: does the saved crop really show the ad that was extracted?

    Cheap (one small image per call) and independent of the box-number step that caused
    the mismatch, so it measures the real error rate rather than re-deriving it.
    """
    conn = connect()
    cache = load_cache("crops")
    rows = conn.execute("""select id, text_ne, crop_path from jobs where run='cc' order by id""").fetchall()
    ids = [r["id"] for r in rows][:limit]
    texts = {r["id"]: r["text_ne"] for r in rows}
    paths = {r["id"]: Path(r["crop_path"]) for r in rows}

    def work(jid):
        if not paths[jid].exists():
            return jid, None, "crop file missing"
        out = run(CROP_PROMPT.format(text_ne=texts[jid][:1200]), [paths[jid]])
        m = re.search(r"MATCH:\s*(yes|no)", out or "", re.I)
        return jid, m.group(1).lower() if m else None, out

    todo = [i for i in ids if str(i) not in cache]
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for jid, v, raw in ex.map(work, todo):
                cache[str(jid)] = {"match": v, "raw": raw}
                save_cache("crops", cache)
                print(f"job {jid}: match={v}", flush=True)

    yes = sum(1 for i in ids if cache.get(str(i), {}).get("match") == "yes")
    no = sum(1 for i in ids if cache.get(str(i), {}).get("match") == "no")
    unk = len(ids) - yes - no
    print(f"\ncrops checked: {len(ids)}  match: {yes}  MISMATCH: {no}  unparsed: {unk}")
    if no:
        bad = [i for i in ids if cache.get(str(i), {}).get("match") == "no"]
        print("mismatched job ids:", bad)
    print(f"error rate: {no / len(ids) * 100:.1f}% ({no}/{len(ids)})" if ids else "")


def cmd_spotcheck(workers, limit):
    """Re-mark the 30 spot-check jobs in data/audit_cc.md from the vision verdict."""
    md = (DATA / "audit_cc.md").read_text().splitlines()
    jobs = {}
    for i, line in enumerate(md):
        m = re.match(r"### job (\d+) — ", line)
        if m:
            jobs[int(m.group(1))] = i
    ids = list(jobs)[:limit]
    conn = connect()
    cache = load_cache("spotcheck")
    # sqlite3 connections are thread-bound, so read every row before fanning out
    recs = {r["id"]: dict(r) for r in conn.execute("select * from jobs where id in (%s)"
            % ",".join("?" * len(ids)), ids)} if ids else {}

    def work(jid):
        j = recs[jid]
        imgs = [Path(j["crop_path"]), *page_images(j["pdf_id"], j["page_no"])]
        imgs = [i for i in imgs if i.exists()]
        out = run(VERIFY_PROMPT.format(**{k: j[k] for k in
               ("title", "organization", "location", "positions_count", "salary",
                "deadline_text", "contact", "text_ne")}), imgs)
        return jid, parse_verdict(out), out

    todo = [i for i in ids if str(i) not in cache]
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for jid, v, raw in ex.map(work, todo):
                cache[str(jid)] = {**v, "raw": raw}
                save_cache("spotcheck", cache)
                print(f"job {jid}: {v}", flush=True)

    # rebuild the sheet in one pass: inserting notes while iterating shifts the saved line numbers
    marked = set()
    out, seen = [], set()
    for line in md:
        m = re.match(r"### job (\d+) — ", line)
        jid = int(m.group(1)) if m else None
        v = cache.get(str(jid)) if jid is not None else None
        if v:
            fields_ok = v.get("FIELDS") == "CORRECT"
            line = re.sub(r"[☑☐] right [☑☐] wrong",
                          f"{'☑' if fields_ok else '☐'} right {'☑' if not fields_ok else '☐'} wrong", line)
            seen.add(jid)
        out.append(line)
        if jid is not None and v and jid not in marked:
            out.append(f"  <!-- vision: fields={v.get('FIELDS')} crop={v.get('CROP')} "
                       f"missing={v.get('MISSING') or 'none'}"
                       + (f" | {v['adjudicated']}" if v.get("adjudicated") else "") + " -->")
            marked.add(jid)
    (DATA / "audit_cc.md").write_text("\n".join(out))
    tally = {}
    for jid in ids:
        v = cache.get(str(jid), {})
        tally[v.get("FIELDS", "?")] = tally.get(v.get("FIELDS", "?"), 0) + 1
    print(f"marked {len(seen)}/{len(ids)} jobs; fields verdicts: {tally}")


def parse_verdict(out):
    v = {}
    for key, allowed in SPOT_RE.items():
        m = re.search(rf"^{key}:\s*([A-Z_a-z ]+)", out or "", re.M)
        val = (m.group(1).strip().split("  ")[0] if m else None)
        if allowed and val not in allowed:
            val = next((a for a in allowed if a.lower() in (val or "").lower()), None)
        v[key] = val
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["groundtruth", "spotcheck", "crops", "verify", "reclass"])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--category", default="training")
    a = ap.parse_args()
    globals()["MODEL"] = a.model
    if a.cmd == "groundtruth":
        cmd_groundtruth(a.workers)
    elif a.cmd == "spotcheck":
        cmd_spotcheck(a.workers, a.limit)
    elif a.cmd == "crops":
        cmd_crops(a.workers, a.limit)
    elif a.cmd == "reclass":
        cmd_reclass(a.workers, a.category, a.votes)
    else:
        cmd_verify(a.workers, a.votes)


if __name__ == "__main__":
    sys.exit(main())
