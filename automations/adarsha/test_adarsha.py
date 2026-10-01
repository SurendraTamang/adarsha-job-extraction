import datetime as dt

import nepali_datetime
import numpy as np

from common import connect, rewrite_url

B = nepali_datetime.date


def test_rewrite_old_wp_upload_to_new_bucket():
    assert (rewrite_url("https://www.eadarsha.com/wp-content/uploads/2013/01/poush-17-2069.pdf")
            == "https://eadarsha-epaper-new.s3.ap-south-1.amazonaws.com/old/2013/01/poush-17-2069.pdf")


def test_rewrite_retired_bucket():
    assert (rewrite_url("https://eadarsha-epaper.s3.ap-south-1.amazonaws.com/epapers/2024/01/7%20Magh%202080%20Epaper.pdf")
            == "https://eadarsha-epaper-new.s3.ap-south-1.amazonaws.com/epapers/2024/01/7%20Magh%202080%20Epaper.pdf")


def test_rewrite_leaves_current_urls():
    u = "https://eadarsha-epaper-new.s3.ap-south-1.amazonaws.com/epapers/2026/09/14%20Ashoj%202083%20Epaper.pdf"
    assert rewrite_url(u) == u


def test_connect_creates_schema():
    conn = connect(":memory:")
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert {"issues", "pdfs", "pdf_posts", "pages", "batches", "triage", "tiles", "jobs"} <= tables


from dates import parse_bs_iso, parse_deadline, parse_masthead, parse_title, resolve_issue_date


def test_parse_title_formats():
    assert parse_title("बैशाख 25, 2069") == B(2069, 1, 25)          # pre-2020 style
    assert parse_title("१४ असोज २०८३") == B(2083, 6, 14)            # current style
    assert parse_title("१४ असोज २०८३ बुधबार") == B(2083, 6, 14)
    assert parse_title("ज्येष्ठ ११,  २०७१") == B(2071, 2, 11)       # variant spelling, double space
    assert parse_title("फाल्गुण १, २०६९") == B(2069, 11, 1)
    assert parse_title("२३ भदाै, २०७७") == B(2077, 5, 23)
    assert parse_title("३२ भदौ २०८०") is None                       # Bhadra 2080 has 31 days
    assert parse_title("random") is None


def test_parse_masthead_legacy_font():
    assert parse_masthead("@)*# c;f]h !$ ut] a'waf/") == B(2083, 6, 14)
    assert parse_masthead("jif{ !&  c° @%@  @)^( k'; !& ut] dª\\unaf/") == B(2069, 9, 17)
    assert parse_masthead("no date here") is None
    # real 2013 page: masthead month df3 (माघ), later an article date that must not win
    assert parse_masthead("@)^( df3 % ut] ... @)^! ;fpg @& ut]") == B(2069, 10, 5)
    assert parse_masthead("@)^( xxx % ut] ... @)^! ;fpg @& ut]") is None


def test_parse_bs_iso():
    assert parse_bs_iso("2083-06-14") == B(2083, 6, 14)
    assert parse_bs_iso("") is None
    assert parse_bs_iso(None) is None


def test_resolve_issue_date():
    post = dt.date(2026, 9, 30)                                     # = 2083-06-14 BS
    assert resolve_issue_date(None, B(2083, 6, 14), post) == (B(2083, 6, 14), "title", False)
    assert resolve_issue_date(B(2083, 6, 13), B(2083, 6, 14), post) == (B(2083, 6, 13), "masthead", False)
    assert resolve_issue_date(B(2083, 6, 1), B(2083, 6, 14), post)[2] is True   # mis-attached PDF
    assert resolve_issue_date(None, None, post) == (B(2083, 6, 14), "post", False)
    typo = parse_title("७ फागुन २००७ बिहीबार")                     # real bad title
    assert resolve_issue_date(None, typo, dt.date(2026, 2, 19))[1:] == ("post", True)


def test_parse_deadline():
    issue = B(2083, 6, 14)
    assert issue.to_datetime_date() == dt.date(2026, 9, 30)
    assert parse_deadline("प्रकाशित मितिले ७ दिनभित्र", issue) == (dt.date(2026, 10, 7), True)
    assert parse_deadline("२०८३/०६/२० गतेसम्म", issue) == (dt.date(2026, 10, 6), False)
    assert parse_deadline("असोज २५ गते", issue) == (dt.date(2026, 10, 11), False)
    assert parse_deadline("Deadline 2026-10-05", issue) == (dt.date(2026, 10, 5), False)
    assert parse_deadline("", issue) == (None, False)
    assert parse_deadline("भदौ ५ गते", issue)[0].year == 2027      # month already past -> next BS year


from render import MAX_EDGE, MAX_PIXELS, crop, jpeg_b64, tile_bbox_to_page, tiles


def test_tiles_fit_api_limits_and_cover_page():
    img = np.zeros((3936, 3069, 3), np.uint8)       # 1105x1417 pt page at 200 DPI (largest seen)
    ts = tiles(img)
    assert len(ts) == 4
    for t, x, y, s in ts:
        assert s == 1.0
        assert max(t.shape[:2]) <= MAX_EDGE and t.shape[0] * t.shape[1] <= MAX_PIXELS
    right = max(x + t.shape[1] for t, x, y, s in ts)
    bottom = max(y + t.shape[0] for t, x, y, s in ts)
    assert (right, bottom) == (3069, 3936)


def test_oversized_tile_is_scaled_and_mapped_back():
    t, x0, y0, s = tiles(np.zeros((6000, 5000, 3), np.uint8))[3]
    assert s < 1
    assert tile_bbox_to_page([100, 200, 50, 60], x0, y0, s) == [
        round(x0 + 100 / s), round(y0 + 200 / s), round(50 / s), round(60 / s)]


def test_crop_pads_and_clamps():
    img = np.zeros((1000, 1000, 3), np.uint8)
    assert crop(img, [0, 0, 100, 100]).shape[:2] == (130, 130)      # 3% pad, clamped at 0
    assert crop(img, [450, 450, 100, 100]).shape[:2] == (160, 160)


def test_jpeg_b64_roundtrip():
    import base64, cv2
    b = jpeg_b64(np.full((20, 30, 3), 255, np.uint8))
    assert cv2.imdecode(np.frombuffer(base64.b64decode(b), np.uint8), cv2.IMREAD_COLOR).shape == (20, 30, 3)


from discover import pdf_links


def test_pdf_links_skip_rate_card_and_dedupe():
    html = ('<a href="https://eadarsha-epaper-new.s3.ap-south-1.amazonaws.com/epapers/2026/09/14%20Ashoj%202083%20Epaper.pdf">'
            '<a href="https://eadarsha-epaper-new.s3.ap-south-1.amazonaws.com/epapers/2026/09/14%20Ashoj%202083%20Epaper.pdf">'
            '<a href="https://www.eadarsha.com/wp-content/uploads/2021/04/RateCard_AdarshaSamaj.pdf">'
            '<a href="https://www.eadarsha.com/wp-content/uploads/2019/07/Newspaper-Subscription-Rates.pdf">')
    assert pdf_links(html) == [
        "https://eadarsha-epaper-new.s3.ap-south-1.amazonaws.com/epapers/2026/09/14%20Ashoj%202083%20Epaper.pdf"]


from download import mark_duplicates, resolve_pdf_date


def test_mark_duplicates_only_identical_bytes():
    conn = connect(":memory:")
    conn.executemany(
        "insert into pdfs (id, sha256, issue_ad, date_source, page_count, local_path) values (?,?,?,?,?,'x')",
        [(1, "a", "2026-09-30", "masthead", 4),
         (2, "a", "2026-09-30", "masthead", 4),    # same bytes
         (3, "b", "2026-09-30", "masthead", 4)])   # same masthead date, different file: may be another day
    mark_duplicates(conn)
    assert dict(conn.execute("select id, duplicate_of from pdfs").fetchall()) == {1: None, 2: 1, 3: None}


def test_resolve_pdf_date_uses_masthead_then_flags_conflict():
    conn = connect(":memory:")
    conn.execute("insert into issues values (1, '2026-09-30T02:37:31', 't', 'l', '2083-06-14', 'ok')")
    conn.execute("insert into pdfs (id, masthead_bs) values (7, '2083-06-01')")
    conn.execute("insert into pdf_posts values (7, 1)")
    resolve_pdf_date(conn, 7)
    row = conn.execute("select issue_bs, issue_ad, date_source, date_conflict from pdfs").fetchone()
    assert tuple(row) == ("2083-06-01", "2026-09-17", "masthead", 1)


from extract import merge_ads, similar, validate

GOOD_JOB = {"category": "private", "title": "Waiter", "organization": "Hotel", "location": "", "positions_count": "2",
            "salary": "", "qualifications": "", "deadline_text": "", "contact": "9856000000", "confidence": 0.9}


def test_validate_page_json():
    ad = {"box": 18, "bbox": [], "text_ne": "आवश्यकता", "text_en": "Wanted", "jobs": [GOOD_JOB]}
    ok = {"has_job_ads": True, "masthead_date": "", "ads": [ad]}
    assert validate(ok) is None
    assert validate({"has_job_ads": False, "masthead_date": "", "ads": []}) is None
    assert validate({**ok, "ads": [{**ad, "box": -1, "bbox": [330, 1140, 120, 180]}]}) is None
    assert "bbox" in validate({**ok, "ads": [{**ad, "box": -1, "bbox": [330, 1140, 0, 180]}]})
    assert "bad box" in validate({**ok, "ads": [{**ad, "box": "18"}]})
    assert "bad job" in validate({**ok, "ads": [{**ad, "jobs": [{**GOOD_JOB, "category": "hotel"}]}]})
    assert validate({"masthead_date": ""}) == "has_job_ads missing"


def test_similar_and_merge_ads():
    full = "आवश्यकता होटल कर्मचारी चाहियो सम्पर्क ९८५६०१२३४५ लेकसाइड पोखरा"
    part = "आवश्यकता होटल कर्मचारी चाहियो"
    assert similar(part, full) and not similar("", full)
    ads = [{"bbox": [1300, 100, 300, 200], "text_ne": part},
           {"bbox": [1250, 100, 500, 200], "text_ne": full},
           {"bbox": [0, 3000, 200, 100], "text_ne": "अर्को विज्ञापन शिक्षक चाहियो"}]
    merged = merge_ads(ads)
    assert len(merged) == 2 and merged[0]["bbox"] == [1250, 100, 500, 200]


from audit import assign_dup_groups, empty


def test_empty_values():
    assert all(empty(v) for v in (None, "", "  ", "None", "N/A", "null", "-"))
    assert not empty("Hotel Barahi")


def test_dup_groups_join_reruns_within_14_days():
    conn = connect(":memory:")
    conn.executemany("insert into pdfs (id, issue_ad) values (?,?)",
                     [(1, "2026-09-01"), (2, "2026-09-04"), (3, "2026-10-10")])
    conn.executemany("insert into jobs (id, run, pdf_id, organization, title) values (?,?,?,?,?)",
                     [(10, "r", 1, "Hotel Barahi", "Waiter"), (11, "r", 2, "Hotel Barahi ", "waiter"),
                      (12, "r", 3, "Hotel Barahi", "Waiter"), (13, "r", 1, "", "")])
    assign_dup_groups(conn, "r")
    g = dict(conn.execute("select id, dup_group_id from jobs").fetchall())
    assert g[10] == g[11] != g[12]
    assert g[13] not in (g[10], g[12])
    assert tuple(conn.execute("select first_seen, last_seen from jobs where id=10").fetchone()) == \
           ("2026-09-01", "2026-09-04")


def test_detect_boxes_finds_bordered_rectangles():
    import cv2
    from render import detect_boxes
    img = np.full((2000, 1500, 3), 255, np.uint8)
    cv2.rectangle(img, (100, 100), (600, 500), (0, 0, 0), 4)       # ad box
    cv2.rectangle(img, (700, 900), (1300, 1600), (0, 0, 0), 4)     # ad box
    cv2.putText(img, "text only", (100, 1200), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
    boxes = detect_boxes(img)
    assert len(boxes) == 2
    assert all(abs(a - b) <= 12 for a, b in zip(boxes[0], [100, 100, 500, 400]))   # border thickness


def test_parse_deadline_real_formats_from_pilot():
    issue = B(2072, 12, 20)
    ad = lambda y, m, d: B(y, m, d).to_datetime_date()
    assert parse_deadline("27th Chaitra, 2072", issue) == (ad(2072, 12, 27), False)
    assert parse_deadline("On or Before 24th Chaitra, 2072.", issue) == (ad(2072, 12, 24), False)
    assert parse_deadline("Chaitra 28th, 2072", issue) == (ad(2072, 12, 28), False)
    assert parse_deadline("28th of Chaitra, 2072", issue) == (ad(2072, 12, 28), False)
    assert parse_deadline("26th Chaitra", issue) == (ad(2072, 12, 26), False)          # year from issue
    assert parse_deadline("before 5 pm, 14 August, 2019", issue) == (dt.date(2019, 8, 14), False)
    assert parse_deadline("सूचना प्रकाशन भएको मितिले एक हप्ता (कार्यालय समय) भित्र", issue) == \
           (issue.to_datetime_date() + dt.timedelta(days=7), True)
    assert parse_deadline("यथाशीघ्र", issue) == (None, False)                          # "as soon as possible"
