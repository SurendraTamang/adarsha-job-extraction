# Adarsha Samaj Job Extraction — Pilot Report

**Date:** 2026-09-30
**Repo:** https://github.com/SurendraTamang/adarsha-job-extraction
**Status:** Pilot complete and measured. Full archive extraction not started.

---

## 1. Summary

We built a pipeline that scrapes every Adarsha Samaj (Pokhara daily) e-paper issue published since 2012 and extracts job advertisements from the page images, storing each ad with its dates, original Nepali text, English translation, and a cropped image.

**Discovery and download are finished for the entire archive.** Extraction has been run and measured on a **10-issue pilot**.

| Outcome | Status |
|---|---|
| Archive catalogued | **Complete** — 4,708 issues, 4,372 PDFs, 23,595 pages |
| Pipeline code | **Complete** — all 5 stages built, resumable, 22/22 tests pass |
| Pilot extraction | **Complete** — 10 issues → 113 ads → 218 job rows |
| Field & crop accuracy | **Verified** — 30/30 fields, 99.1% crops |
| Full extraction | **Not started** — blocked on disk, time, and one unresolved accuracy gate |

**The single most important caveat:** the pilot covers **0.2% of the archive** (50 of 23,595 pages). Triage recall — the check that lets us skip the ~72% of pages with no ads — is **measured at 6/6 but not statistically established**. See §5.

---

## 2. What was built

Five stages sharing one SQLite database. Every stage records per-row status and skips completed work on re-run, so any stage can be interrupted and resumed.

| Stage | Does | Output |
|---|---|---|
| `discover.py` | Lists issues via the WordPress API, maps PDFs to posts, rewrites dead URLs, HEAD-checks | `issues`, `pdfs` tables |
| `download.py` | Fetches PDFs (~1 req/s, browser UA), fingerprints sha256, decodes masthead dates, marks duplicates | `data/pdfs/` (~21 GB) |
| `render.py` | Renders 1000 px page JPEGs for triage | `data/pages/` |
| `extract.py` | Detects boxed ad regions, renders tiles, drives model extraction, builds crops | `jobs` table, `data/crops/` |
| `audit.py` | Content audit, spot-check sheet, run comparison | `data/audit_*.md` |

### Three problems worth knowing about

**1. The PDFs are on a retired bucket.** Every `eadarsha-epaper` URL returns 404. The files were moved to `eadarsha-epaper-new`. Both the old `wp-content/uploads` scheme and the newer embedded-link scheme needed rewriting. This is why the archive is reachable at all.

**2. The text layer is unusable.** Body text uses legacy ASCII-mapped Nepali fonts (Nagarik, AP, Ganesh, Himalli, ARAP002…). `pdftotext` returns strings like `cfjZostf`. **Extraction therefore reads rendered images, not text.** Some ads are embedded images with no text layer at all.

**3. Issue dates cannot be trusted from titles.** Titles come in two formats with spelling variants. Of 4,708 issues, **4,428 have a parseable BS title, and 26 of those disagree with the post date** — stale years, invalid dates like `३२ भदौ २०८०`. Dates are resolved in priority order: **printed masthead → title (only if it agrees with the post date within 2 days) → post date**, and disagreements are flagged via `date_conflict`.

**One deliberate design decision worth recording:** we tried deduplicating same-date editions and **dropped it**. In the real archive, 28 of 46 same-masthead-date pairs turned out to be *different days* (the paper sometimes reuses the previous day's masthead) or partial files. Byte-identical `sha256` is the only safe dedup.

---

## 3. Archive coverage

| | Count | % |
|---|---|---|
| Issues published 2012→today | 4,708 | 100% |
| Issues with a reachable PDF (`ok`) | 4,069 | 86.4% |
| Issues with only dead links (`dead`) | 158 | 3.4% |
| Issues with no PDF link at all (`no_link`) | 481 | 10.2% |
| Unique PDFs downloaded | 4,372 | |
| Pages inside them | 23,595 | |
| Distinct issue dates covered | 4,279 | |

Weakest year by a wide margin is **2018: 89 usable PDFs from 356 published issues (25%)**. Every other year is 93–100%. (Counts above 100% in 2020+ reflect issues carrying more than one PDF — re-uploads or neighbouring days mis-attached to the wrong post. Byte-identical files are deduplicated; the rest are kept, since dropping them wrongly cost us a day of discovery work.)

**These gaps are permanent** — the files no longer exist on the publisher's servers. No amount of extra effort recovers them. Any historical analysis must treat **2018 as effectively missing** and expect small shortfalls elsewhere.

| Year | Usable PDFs | Issues published | Coverage |
|---|---|---|---|
| 2012 | 3 | 3 | 100% |
| 2013 | 331 | 347 | 95% |
| 2014 | 323 | 346 | 93% |
| 2015 | 330 | 344 | 96% |
| 2016 | 322 | 344 | 94% |
| 2017 | 323 | 347 | 93% |
| **2018** | **89** | **356** | **25%** |
| 2019 | 322 | 345 | 93% |
| 2020 | 316 | 305 | 104% |
| 2021 | 355 | 349 | 102% |
| 2022 | 346 | 343 | 101% |
| 2023 | 349 | 350 | 100% |
| 2024 | 345 | 345 | 100% |
| 2025 | 323 | 328 | 98% |
| 2026 | 256 | 256 | 100% |

---

## 4. Pilot results

10 issues sampled across five eras to prove the method works on old and new typesetting (2012–2019 uses different fonts, page size and layout than 2020+).

| Year | Issues | Pages | Ads found |
|---|---|---|---|
| 2013 | 2 | 6 | 43 |
| 2016 | 1 | 8 | 39 |
| 2019 | 1 | 8 | 12 |
| 2022 | 1 | 4 | 6 |
| 2026 | 5 | 4 | 13 |
| **Total** | **10** | **50** | **113** |

### Extracted records

113 ads → **218 job rows** (one row per distinct role, so multi-role ads expand).

| Category | Rows | Flagged as not-a-job |
|---|---|---|
| private | 162 | — |
| foreign | 23 | — |
| training | 22 | **13** |
| government | 8 | — |
| other | 3 | — |

Most ads are single-role (70 of 113). Multi-role ads are genuine — e.g. one "Hotel Staff Wanted" box listing Cook, Dishwasher and Night Staff correctly becomes 3 rows sharing one `ad_id`.

### Field completeness

| Field | Kind | Empty | Note |
|---|---|---|---|
| title | expected | 0.0% | |
| contact | expected | 0.5% | 217/218 rows have one |
| organization | expected | 12.4% | genuine — small classifieds often omit it |
| location | conditional | 6.4% | |
| positions_count | conditional | 25.2% | |
| qualifications | conditional | 27.5% | |
| salary | conditional | **57.3%** | genuinely absent from most small ads |
| deadline_text | conditional | **62.8%** | most ads print no deadline |

The high empty rates are **conditional, not gated** — these fields are truly absent from small classifieds, not withheld by the source. No placeholder values ("Company Name", "XYZ", "[illegible]") appear anywhere in the dataset.

### Deadlines and dates

- **92.6%** of ads that print a deadline parse to a real date (75 of 81)
- Relative wording ("प्रकाशित मितिले ७ दिनभित्र") is resolved to `issue_date + N days` and flagged `deadline_derived` (6 rows)
- **50/50 pages** resolved their issue date from the printed masthead

---

## 5. Quality verification

We did not report success from row counts. Every claim below comes from inspecting actual content, and each was checked against the source image.

### Spot check — 30 randomly sampled jobs

**30/30 fields correct.** Two rows were initially flagged wrong by the automated checker; both crops were then inspected directly and **both turned out correct** — the checker had confused other ads on the same page for errors in the record. Verdicts and reasons are recorded inline in `data/audit_cc.md`.

### Crop accuracy — all 218 rows

**216/218 correct (99.1%).** The 2 failures are two roles of the *same single ad* whose saved image points at an unrelated advertisement on the page. The **text was correct in both cases; only the image is wrong.**

Every row now carries `jobs.crop_ok`: `1` = image matches the ad, `0` = image is a different ad, `NULL` = unchecked. This means a wrong image can never reach a Facebook post unnoticed.

**Known cause:** the model picks a box by reading its drawn number. On dense classified pages the numbers interleave in non-reading order, and one digit was misread (box 38 recorded as 48). It is a labelling-legibility problem, not a detection problem.

### Data contamination — 13 rows (6.0%) are not job ads

All 13 are in `training`: institutes advertising their own standing course catalogues, and study-abroad placement ads (Japan, South Africa, Cyprus, MBBS/MD abroad). These are **flagged, not deleted**, via `jobs.category_source = 'reclass:EXCLUDE'`.

We tightened the extraction rule with an explicit test: an institute advertising its own courses or selling study-abroad placement is **out of scope**; a notice that genuinely calls for applicants (CTEVT-recognised free course, seats and eligibility, application deadline, named-job preparation tied to placements) is **in scope**.

The `other` category (3 rows) is still unreviewed and may contain more of the same.

### Triage recall — NOT ESTABLISHED

This is the gate that decides whether a full run is viable, and it is **not met**.

Triage flags which pages contain ads so the rest can be skipped. Against ground truth: **6 of 6 ad pages were caught.** But only **6 of the 15 sampled pages had any ads**, so the 95% confidence lower bound on true recall is only **~61%** — against a required ≥95%.

This result is consistent with recall being anywhere from 61% to 100%. It does not disprove the pipeline; it fails to prove it. **If true recall is 85%, a full run would silently omit ~15% of all job ads** while looking successful — and would have cost days of compute to discover.

**Recommendation: settle this before scaling.** It costs roughly one hour.

### Additional limitations

- **Counts are non-deterministic.** The same page yielded 10, 11 and 13 ads on three separate runs. Ground truth is a *model* judgement, not a human count.
- **Single model, single run.** No Opus-vs-Sonnet comparison exists, so the cost decision the design calls for cannot be made from this data.
- **Automated verdicts need majority voting.** A single vision sample flip-flopped on the same crop. One pass produced 2 false "wrong crop" verdicts out of 30. Three-vote majority eliminated both problems — always use `--votes 3`.

---

## 6. Coverage and cost projection

Pilot density is 113 ads per 50 pages. Applied to the archive:

| Measure | Value |
|---|---|
| Pages in archive | 23,595 |
| Pages triaged so far | 680 (**2.9%**) |
| Pages with ads (est. ~56%) | ~13,200 |
| **Ads recoverable (extrapolated)** | **~53,000** |

This is an **extrapolation from 50 pages, not a measurement.** It should not be quoted as a result.

---

## 7. Blockers to a full run

### 1. Disk — currently a hard fail

| Asset | Needed | Available |
|---|---|---|
| PDFs | ~21 GB | |
| Page JPEGs | ~12 GB | |
| **Tiles (4.21 MB/page)** | **~99 GB** | |
| **Total** | **~132 GB** | **25 GB free** |

Machine is 94% full. Tiles are the problem: nothing currently deletes them after a page is processed. **Fix: add per-page tile cleanup, and free space.** PDFs are re-downloadable from the public web, so they are the safest thing to move off this machine.

### 2. Time

Measured on this machine: ~16 s for a small crop, **4m43s for one cold full-resolution tile**, and >5 min (timeout) for a full page. A complete pass is **days of wall-clock**, not hours. Throughput does not scale past ~4 concurrent calls on the free tier.

### 3. The recall gate

See §5. Cheap to resolve relative to the cost of getting it wrong.

---

## 8. Recommended next step

**Run a 500-page slice before committing to the full archive.**

- ~1 hour of wall-clock
- Produces a defensible recall number on our actual page mix
- Yields real per-page cost, letting us choose a model on evidence rather than estimate
- Confirms the disk and throughput assumptions at 1/47th scale
- Surfaces contamination and crop-error rates at a rate we can act on

If recall holds ≥95% and disk is freed, the full run becomes a scheduling problem rather than a technical unknown.

**Do not** start a multi-day full run before this slice. The pipeline is proven accurate on what it has seen; what is unproven is whether it sees everything.

---

## Appendix: reproducing this

Full setup, run order and known limits are in [`automations/adarsha/README.md`](automations/adarsha/README.md).

```bash
git clone https://github.com/SurendraTamang/adarsha-job-extraction.git
brew install poppler
pip install -r automations/adarsha/requirements.txt
python automations/adarsha/common.py --relocate   # required: rebinds stored absolute paths

cd automations/adarsha && pytest test_adarsha.py -q   # 22 tests
```

**Committed:** database (4.7 MB), 113 ad crops (31 MB), all per-page model answers, audit reports, ground truth, cached vision verdicts.
**Not committed:** PDFs (19 GB), page JPEGs, tiles — all re-downloadable or regenerable.