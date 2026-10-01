"""Job extraction by Claude Code subagents (no API key needed).

  python extract.py prep   --run cc --from 2026-09-26 --to 2026-09-30   # or --pdfs ids.txt
      renders 2x2 tiles to data/tiles/, lists pages to do in data/cc/<run>/todo.tsv
  (one subagent per page writes data/cc/<run>/<pdf_id>-<page_no>.json, see PAGE_PROMPT)
  python extract.py ingest --run cc --model cc-sonnet
      validates the JSON files, fills triage, builds jobs rows and crops
"""
import argparse
import json
from difflib import SequenceMatcher

import cv2

from common import DATA, connect, select_pdfs
from dates import parse_bs_iso, parse_deadline
from download import mark_duplicates, resolve_pdf_date
from render import crop, detect_boxes, draw_boxes, draw_boxes_on_tile, render_page, tiles

CATEGORIES = ["private", "government", "foreign", "training", "other"]
JOB_FIELDS = ["category", "title", "organization", "location", "positions_count", "salary",
              "qualifications", "deadline_text", "contact"]

PAGE_PROMPT = """You are extracting job ads from one page of Adarsha Samaj, a Nepali daily newspaper from Pokhara.

1. Read the whole-page image (it is {page_w} x {page_h} pixels). Red numbered rectangles mark the boxed
   areas detected on the page: {boxes_jpg}
   has_job_ads = true if the page contains ANY job-like advertisement or notice: private vacancies
   (आवश्यकता, कर्मचारी चाहियो, Staff Wanted), government or public vacancy notices (पदपूर्ति, दरखास्त आह्वान,
   लोक सेवा), foreign employment / manpower ads (वैदेशिक रोजगार), training, internship or scholarship calls.
   Small classified boxes count. News articles about jobs do not count.
   masthead_date: {masthead_rule}
2. If has_job_ads is true, read these 4 tiles to see the small print (the page's quarters at high resolution,
   overlapping by 10%; tile 0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right):
{tile_list}
   List every job-like ad on the page ONCE (an ad seen in two tiles is still one ad):
   - box: the number of the red rectangle that encloses exactly this ad (its outer border, including the
     heading). Use -1 only if no red rectangle fits the ad.
   - bbox: only when box is -1: [x, y, width, height] of the ad in pixels of the whole-page image
     ({page_w} x {page_h}); otherwise [].
   - text_ne: the full ad text as printed, in Unicode Devanagari (keep English parts as printed).
   - text_en: a faithful English translation of text_ne.
   - jobs: one entry per distinct role:
     category: government (government offices, municipalities, public/community schools, public hospitals,
       public banks and corporations), private (companies, hotels, shops, private schools, NGOs, cooperatives),
       foreign (overseas employment / manpower), training (training, internship, scholarship), other;
     title, organization, location, positions_count, salary, qualifications,
     deadline_text (exactly as printed, e.g. "प्रकाशित मितिले ७ दिनभित्र"), contact (phone, email, address),
     confidence (number 0-1: how sure you are the fields are read correctly).
   Use "" for any field the ad does not show. Never guess and never invent placeholder values.
3. Write ONLY this JSON (no markdown) with the Write tool to {out_json}:
{{"has_job_ads": true|false, "masthead_date": "", "ads": [{{"box": 18, "bbox": [], "text_ne": "", "text_en": "", "jobs": [...]}}]}}
   When has_job_ads is false, "ads" is [].
Reply with one line: the number of ads found."""

MASTHEAD_P1 = ('the newspaper\'s own date printed in the masthead, as a Bikram Sambat date YYYY-MM-DD with ASCII '
               'digits (Baisakh=01 ... Chaitra=12; e.g. २०८३ असोज १४ -> 2083-06-14). "" if not visible.')
MASTHEAD_OTHER = 'always "" (not page 1).'


def cc_dir(run):
    d = DATA / "cc" / run
    d.mkdir(parents=True, exist_ok=True)
    return d


def tile_path(pdf_id, page_no, i):
    return DATA / "tiles" / str(pdf_id) / f"{page_no}-{i}.jpg"


def boxes_path(pdf_id, page_no, ext):
    """Detected ad boxes (.json, 200 DPI pixels) and the numbered overlay image (.jpg)."""
    return DATA / "tiles" / str(pdf_id) / f"{page_no}-boxes{ext}"


def prep(conn, run, pdfs, grid=2):
    """Render tiles for every page of the selected PDFs; write the page list for subagents."""
    lines = []
    for p in pdfs:
        if not p["local_path"] or p["duplicate_of"]:
            continue
        for pg in conn.execute("select * from pages where pdf_id=? order by page_no", (p["id"],)).fetchall():
            if (cc_dir(run) / f"{p['id']}-{pg['page_no']}.json").exists():
                continue
            if not boxes_path(p["id"], pg["page_no"], ".json").exists():
                img = render_page(p["local_path"], pg["page_no"])
                boxes = detect_boxes(img)
                for i, (t, x0, y0, scale) in enumerate(tiles(img, grid)):
                    path = tile_path(p["id"], pg["page_no"], i)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(path), draw_boxes_on_tile(t, boxes, x0, y0, scale), [cv2.IMWRITE_JPEG_QUALITY, 90])
                page = cv2.imread(pg["jpg_path"])
                cv2.imwrite(str(boxes_path(p["id"], pg["page_no"], ".jpg")),
                            draw_boxes(page, boxes, img.shape[1] / page.shape[1]), [cv2.IMWRITE_JPEG_QUALITY, 90])
                boxes_path(p["id"], pg["page_no"], ".json").write_text(json.dumps(boxes))
            lines.append(f"{p['id']}\t{pg['page_no']}")
    (cc_dir(run) / "todo.tsv").write_text("\n".join(lines) + "\n")
    print(f"{len(lines)} pages to do -> {cc_dir(run) / 'todo.tsv'}")


def page_prompt(run, pdf_id, page_no, grid=2):
    page_jpg = DATA / "pages" / str(pdf_id) / f"p{page_no}.jpg"
    tile_list = "\n".join(f"   tile {i}: {tile_path(pdf_id, page_no, i)}" for i in range(grid * grid))
    page_h, page_w = cv2.imread(str(page_jpg)).shape[:2]
    return PAGE_PROMPT.format(boxes_jpg=boxes_path(pdf_id, page_no, ".jpg"), tile_list=tile_list,
                              page_w=page_w, page_h=page_h,
                              masthead_rule=MASTHEAD_P1 if page_no == 1 else MASTHEAD_OTHER,
                              out_json=cc_dir(run) / f"{pdf_id}-{page_no}.json")


ISSUE_PROMPT = """You are extracting job ads from Adarsha Samaj, a Nepali daily newspaper from Pokhara.
Process each page listed at the end, one at a time, and write one JSON file per page.

For each page:
1. Read the page overview image. Red numbered rectangles mark boxed areas detected on the page.
   has_job_ads = true if the page has ANY job-like advertisement or notice: private vacancies (आवश्यकता,
   कर्मचारी चाहियो, Staff Wanted), government/public vacancy notices (पदपूर्ति, दरखास्त आह्वान, लोक सेवा),
   foreign employment / manpower ads (वैदेशिक रोजगार), or training, internship or scholarship calls.
Small classified boxes count. News articles about jobs do not count.
    NOT job ads: tenders / calls for proposals, public warnings, lost-document notices,
    missing-person notices, things for sale or rent, horoscopes, student admission notices, and any
    advertisement that only sells a product or a service.
    STUDY-ABROAD AND COURSE-CATALOGUE ADS ARE NOT JOB ADS. Exclude an institute that merely advertises
    its own standing courses or sells study-abroad placement, even when those courses lead to work.
    Signs: it lists courses instead of recruiting trainees ("courses:", a menu of
    Basic/Diploma/Hardware, "कोर्स पनि गरिन्छ", "हामी कहाँ ... अध्ययन"), quotes fees or
    "IELTS/TOEFL NOT NEEDED", markets a student visa or "Study in <country>", or names an overseas
    degree. Do NOT exclude a training notice that really calls for applicants or trainees: a
    government or CTEVT-recognised free course, an admission with seats and eligibility, an application
    deadline, or preparation for a named job ("भर्ती तयारी", security guard, cook/waiter, beautician,
    radio presenter) tied to placements.
   If the overview shows a classifieds section or any box that might be an ad, read the 4 tiles before
   deciding; small print is only readable there. The tiles carry the same numbered red boxes with large
   labels: take box numbers from the tiles, not from the small overview.
   masthead_date: on page 1 only, the masthead date as Bikram Sambat YYYY-MM-DD with ASCII digits
   (Baisakh=01 ... Chaitra=12; e.g. २०८३ असोज १४ -> 2083-06-14); "" if not visible or not page 1.
2. If has_job_ads is true, read the page's 4 tiles (quarters at high resolution, 10% overlap; 0 top-left,
   1 top-right, 2 bottom-left, 3 bottom-right) and list every job-like ad ONCE:
   - box: number of the red rectangle enclosing the WHOLE ad including its heading (when a heading box
     and a body box are both drawn, use the larger outer one). -1 only if no rectangle fits.
   - bbox: only when box is -1: [x, y, width, height] in pixels of the overview image; otherwise [].
   - text_ne: full ad text as printed, Unicode Devanagari (keep English parts as printed).
   - text_en: faithful English translation.
   - jobs: one entry per distinct role:
     category: government (government offices, municipalities, public/community schools, public
       hospitals, public banks and corporations), private (companies, hotels, shops, private schools,
       NGOs, cooperatives, domestic staffing agencies), foreign (overseas jobs, licensed manpower
       agencies recruiting for abroad), training (training, internship, scholarship), other;
     title, organization, location, positions_count, salary, qualifications,
     deadline_text (exactly as printed), contact (phone, email, address),
     confidence (0-1: how sure you are the fields are read correctly).
   Use "" for any field the ad does not show. Never guess or invent values; write [illegible] for
   unreadable text.
3. Write ONLY this JSON (no markdown) with the Write tool to the page's output path:
{{"has_job_ads": true|false, "masthead_date": "", "ads": [{{"box": 18, "bbox": [], "text_ne": "", "text_en": "", "jobs": [...]}}]}}
   ("ads" is [] when has_job_ads is false.)
Be efficient: read each image once; do not crop or upscale.

Pages:
{pages}

Reply with one line per page: "<page>: <number of ads>"."""


def issue_prompt(run, pdf_id, grid=2):
    """Instructions for one subagent covering every not-yet-done page of one issue."""
    conn = connect()
    blocks = []
    for pg in conn.execute("select page_no from pages where pdf_id=? order by page_no", (pdf_id,)).fetchall():
        n = pg["page_no"]
        out = cc_dir(run) / f"{pdf_id}-{n}.json"
        if out.exists():
            continue
        tiles_ = ", ".join(str(tile_path(pdf_id, n, i).name) for i in range(grid * grid))
        blocks.append(f"- page {n}{' (page 1: read masthead_date)' if n == 1 else ''}: overview "
                      f"{boxes_path(pdf_id, n, '.jpg')}; tiles in {tile_path(pdf_id, n, 0).parent}/ "
                      f"({tiles_}); output {out}")
    return ISSUE_PROMPT.format(pages="\n".join(blocks)) if blocks else ""


def validate(data):
    """Return an error message, or None when the subagent's JSON has the expected shape."""
    if not isinstance(data, dict) or not isinstance(data.get("has_job_ads"), bool):
        return "has_job_ads missing"
    if not isinstance(data.get("masthead_date"), str) or not isinstance(data.get("ads"), list):
        return "masthead_date/ads missing"
    for ad in data["ads"]:
        box, bbox = ad.get("box"), ad.get("bbox")
        if not isinstance(box, int) or box < -1:
            return f"bad box {box}"
        if box == -1 and not (isinstance(bbox, list) and len(bbox) == 4 and bbox[2] > 0 and bbox[3] > 0
                              and all(isinstance(v, (int, float)) and v >= 0 for v in bbox)):
            return f"bad bbox {bbox}"
        if not all(isinstance(ad.get(k), str) for k in ("text_ne", "text_en")) or not isinstance(ad.get("jobs"), list):
            return "ad text/jobs missing"
        for job in ad["jobs"]:
            if not all(isinstance(job.get(f), str) for f in JOB_FIELDS) or job["category"] not in CATEGORIES:
                return f"bad job {job}"
            if not isinstance(job.get("confidence"), (int, float)):
                return "confidence missing"
    return None


def ingest(conn, run, model):
    """Load every finished page JSON into triage. Bad files are renamed *.bad for a redo."""
    done = bad = 0
    for path in sorted(cc_dir(run).glob("*.json")):
        pdf_id, page_no = map(int, path.stem.split("-"))
        if conn.execute("select 1 from triage where run=? and pdf_id=? and page_no=? and status='done'",
                        (run, pdf_id, page_no)).fetchone():
            continue
        try:
            data = json.loads(path.read_text())
            err = validate(data)
        except json.JSONDecodeError as e:
            err = f"invalid JSON: {e}"
        if err:
            print(f"{path.name}: {err}")
            path.rename(path.with_suffix(".bad"))
            bad += 1
            continue
        conn.execute("""insert or replace into triage (run, pdf_id, page_no, model, status, has_job_ads, masthead_date, raw)
                        values (?,?,?,?,'done',?,?,?)""",
                     (run, pdf_id, page_no, model, int(data["has_job_ads"]), data["masthead_date"], path.read_text()))
        conn.commit()
        done += 1
    print(f"ingested {done} pages, {bad} bad files")


def apply_vision_mastheads(conn, run):
    """Fill masthead dates the legacy-font decoder missed from page-1 answers."""
    rows = conn.execute(
        """select t.pdf_id, t.masthead_date from triage t join pdfs p on p.id = t.pdf_id
           where t.run=? and t.page_no=1 and t.status='done' and p.masthead_bs is null
             and t.masthead_date != ''""", (run,)).fetchall()
    for r in rows:
        bs = parse_bs_iso(r["masthead_date"])
        if bs:
            conn.execute("update pdfs set masthead_bs=? where id=?", (str(bs), r["pdf_id"]))
            resolve_pdf_date(conn, r["pdf_id"])
    mark_duplicates(conn)
    conn.commit()


def similar(a, b, threshold=0.8):
    """True when most of the shorter text appears in the longer one (a tile-cut ad vs the whole ad)."""
    short, long_ = sorted((a or "", b or ""), key=len)
    if not short:
        return False
    matched = sum(m.size for m in SequenceMatcher(None, short, long_, autojunk=False).get_matching_blocks())
    return matched / len(short) >= threshold


def _intersects(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _union(a, b):
    x1, y1 = min(a[0], b[0]), min(a[1], b[1])
    x2, y2 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return [x1, y1, x2 - x1, y2 - y1]


def merge_ads(ads):
    """Merge the same ad seen in overlapping tiles. `ads` carry page-space `bbox` and `text_ne`;
    the longest text wins and its bbox grows to cover the other copies."""
    kept = []
    for ad in sorted(ads, key=lambda a: -len(a["text_ne"])):
        dup = next((k for k in kept if _intersects(k["bbox"], ad["bbox"]) and similar(k["text_ne"], ad["text_ne"])),
                   None)
        if dup:
            dup["bbox"] = _union(dup["bbox"], ad["bbox"])
        else:
            kept.append(dict(ad))
    return kept


def build_jobs(conn, run):
    """Turn finished pages' answers into jobs rows and crop images. Bboxes come in pixels of the
    1000 px page JPEG and are scaled to the 200 DPI render."""
    pages = conn.execute("""select t.*, pg.jpg_path from triage t
                            join pages pg on pg.pdf_id = t.pdf_id and pg.page_no = t.page_no
                            where t.run=? and t.status='done' and t.has_job_ads=1""", (run,)).fetchall()
    for pg in pages:
        if conn.execute("select 1 from jobs where run=? and pdf_id=? and page_no=?",
                        (run, pg["pdf_id"], pg["page_no"])).fetchone():
            continue
        pdf = conn.execute("select * from pdfs where id=?", (pg["pdf_id"],)).fetchone()
        model = pg["model"]
        img = render_page(pdf["local_path"], pg["page_no"])
        k = img.shape[1] / cv2.imread(pg["jpg_path"]).shape[1]
        boxes = json.loads(boxes_path(pg["pdf_id"], pg["page_no"], ".json").read_text())
        ads = [{**ad, "bbox": boxes[ad["box"]] if 0 <= ad["box"] < len(boxes) else [round(v * k) for v in ad["bbox"] or [0, 0, 0, 0]]}
               for ad in json.loads(pg["raw"])["ads"]]
        ads = merge_ads([ad for ad in ads if ad["bbox"][2] > 0])
        if not ads:
            continue
        issue_bs = parse_bs_iso(pdf["issue_bs"])
        out_dir = DATA / "crops" / run / str(pdf["id"])
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, ad in enumerate(ads):
            ad_id = f"{run}-{pdf['id']}-{pg['page_no']}-{i}"
            crop_path = out_dir / f"{ad_id}.png"
            piece = crop(img, ad["bbox"])
            if piece.size:
                cv2.imwrite(str(crop_path), piece)
            for job in ad["jobs"]:
                deadline, derived = parse_deadline(job["deadline_text"], issue_bs) if issue_bs else (None, False)
                conn.execute(
                    """insert into jobs (run, model, pdf_id, page_no, ad_id, category, title, organization, location,
                       positions_count, salary, qualifications, deadline_text, deadline_ad, deadline_derived, contact,
                       text_ne, text_en, bbox_page, crop_path, confidence, source_pdf_url)
                       values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (run, model, pdf["id"], pg["page_no"], ad_id, *(job[f] for f in JOB_FIELDS[:8]),
                     str(deadline) if deadline else None, int(derived), job["contact"],
                     ad["text_ne"], ad["text_en"], json.dumps(ad["bbox"]), str(crop_path),
                     job["confidence"], pdf["url"]))
        conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["prep", "prompt", "ingest"])
    ap.add_argument("--run", default="cc")
    ap.add_argument("--model", default="cc-sonnet")
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--pdfs")
    ap.add_argument("--page", help="pdf_id-page_no, for the prompt step")
    ap.add_argument("--pdf", type=int, help="pdf_id: one prompt covering the whole issue")
    a = ap.parse_args()
    conn = connect()
    if a.step == "prep":
        prep(conn, a.run, select_pdfs(conn, a.date_from, a.date_to, a.pdfs))
    elif a.step == "prompt":
        print(issue_prompt(a.run, a.pdf) if a.pdf else page_prompt(a.run, *map(int, a.page.split("-"))))
    else:
        ingest(conn, a.run, a.model)
        apply_vision_mastheads(conn, a.run)
        build_jobs(conn, a.run)
        print(conn.execute("select count(*), count(distinct ad_id) from jobs where run=?", (a.run,)).fetchone()[:])


if __name__ == "__main__":
    main()
