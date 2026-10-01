# Data Inventory & Coverage Report

**Project:** Adarsha Samaj job-ad extraction
**Date:** 2026-09-30
**Database:** `automations/adarsha/data/adarsha.db`

Every figure below is a live query against the database. Nothing is estimated except where explicitly labelled.

---

## 1. The short answer

| Stage | Rows | Completeness |
|---|---|---|
| Issues catalogued | **4,708** | **100%** — every issue ever published |
| PDF files located | **4,648** | 98.7% of issues |
| PDFs downloaded | **4,372** | **92.9%** of issues |
| Pages available | **23,595** | — |
| Pages rendered | **680** | 2.9% |
| Pages read by the model | **50** | **0.2%** |
| Job records extracted | **218** | **0.9%** of the archive |

**Discovery and download are finished for the entire archive. Extraction has read 0.2% of it.**

---

## 2. Raw row counts

| Table | Rows | What it holds |
|---|---|---|
| `issues` | 4,708 | one per published issue, 2012→2026 |
| `pdfs` | 4,648 | one per unique PDF file (URL + sha256) |
| `pdf_posts` | 4,653 | PDF↔issue mapping (many-to-many) |
| `pages` | 680 | rendered 1000 px triage JPEGs |
| `triage` | 50 | per-page verdicts: has ads? masthead date? |
| `jobs` | 218 | extracted job records (role-level) |
| `tiles` | 0 | unused — abandoned Batch API path |
| `batches` | 0 | unused — abandoned Batch API path |

218 job rows collapse to **113 distinct ads**, or **93** after excluding non-jobs.

---

## 3. Archive coverage — issues

| Status | Count | % of archive |
|---|---|---|
| `ok` — reachable PDF | 4,069 | 86.4% |
| `no_link` — no PDF link published | 481 | 10.2% |
| `dead` — link exists, file gone | 158 | 3.4% |

**4,333 of 4,708 issues (92.0%) yield a usable PDF.** The 375 missing issues are unrecoverable — the files no longer exist on the publisher's servers.

### By year

| Year | Usable | Published | Coverage |
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
| **Total** | **4,333** | **4,708** | **92.0%** |

**2018 is the one catastrophic gap: 25% coverage against 93–100% everywhere else.** Any trend crossing 2018 has a permanent hole.

Coverage above 100% in 2020+ means some issues carry multiple PDFs — re-uploads, or neighbouring days mis-attached to the wrong post. Byte-identical files are deduplicated (39 marked); the rest are kept deliberately, because same-date dedup proved unsafe (see §7).

---

## 4. File-level status

| HTTP status | Files | Meaning |
|---|---|---|
| 200 | 4,372 | downloaded successfully |
| 403 | 270 | access denied — worth retrying |
| −1 | 5 | connection failure |
| 404 | 1 | not found |

270 files returned 403 and are **candidates for a retry pass** — they may be reachable with different timing or headers. That is up to 6% more archive, currently uncounted.

---

## 5. Date resolution

| Source | Files | % |
|---|---|---|
| `masthead` — read from the printed page | 4,364 | 99.8% |
| `title` — parsed from the issue title | 8 | 0.2% |
| **Undated** | **276** | 6.0% |

- **102 files flagged `date_conflict`** where masthead, title and post date disagree by more than 2 days — mostly mis-attached PDFs.
- 4,279 **distinct issue dates** resolved.

Dates are trustworthy because they come from the newspaper's own printed masthead, not from metadata. This required decoding legacy Preeti-style ASCII-mapped Nepali fonts, since the PDF text layer is unusable.

---

## 6. Extraction progress

| Metric | Value |
|---|---|
| Issues extracted | **10 of 4,372 (0.23%)** |
| Pages triaged | **50 of 23,595 (0.2%)** |
| Pages with ads found | 28 of 50 (56%) |
| Ads extracted | 113 |
| Job rows | 218 |
| Clean ads (non-jobs removed) | 93 |

### Extracted ads by year

| Year | Ads | Rows | Share of sample |
|---|---|---|---|
| 2013 | 31 | 56 | 33% |
| 2016 | 32 | 83 | 34% |
| 2019 | 11 | 22 | 12% |
| 2022 | 6 | 12 | 6% |
| 2026 | 13 | 23 | 14% |

**68% of the extracted data is 2013–2016.** The current market (2026) is 13 ads.

---

## 7. Data quality — verified, not assumed

| Check | Result |
|---|---|
| Crop image matches its ad (`crop_ok=1`) | **216 / 218 — 99.1%** |
| Crop points at a different ad (`crop_ok=0`) | 2 (one ad, two roles) |
| Spot-check fields correct | **30 / 30** |
| Records that are not job ads | 13 (6.0%) — flagged, not deleted |
| Crop files present on disk | 218 / 218 |
| Malformed page answers | 0 |
| Deadline parse rate (where a deadline is printed) | 92.6% (75 of 81) |
| Issue date from printed masthead | 50 / 50 pages |

**Not established: triage recall.** The check that decides whether pages can be skipped is 6/6 on a sample where only 6 of 15 pages had ads — a 95% confidence lower bound of **~61%**, against a required ≥95%.

---

## 8. Storage on disk

| Directory | Size | Committed to git | Rebuildable by |
|---|---|---|---|
| `data/pdfs` | 19 GB | No | `download.py` |
| `data/pages` | 320 MB | No | `render.py` |
| `data/tiles` | 430 MB | No | `extract.py prep` |
| `data/crops` | 31 MB | **Yes** | — (the deliverable) |
| `data/adarsha.db` | 4.7 MB | **Yes** | — |
| **Committed total** | **36 MB** | | |
| Machine free space | 30 GB | | |

A full run additionally needs **~99 GB of tiles** (4.21 MB/page × 23,595). Nothing currently deletes tiles after a page is processed — that cleanup must be added before a full run.

---

## 9. What's missing, and what it would cost

| Gap | Size | To close |
|---|---|---|
| 403 files never retried | up to 270 PDFs | one `download.py` pass |
| 481 issues with no PDF | — | **unrecoverable** |
| 158 dead links | — | **unrecoverable** |
| 2018 coverage at 25% | ~267 issues | **unrecoverable** |
| Pages not rendered | 22,915 | ~6.5 hours, `render.py` |
| Pages not extracted | 23,545 | days of wall-clock, gated on recall |

**Two known corrections to the record:**
- Earlier drafts described "995 near-duplicate box pairs" as a bug. That was wrong — those are genuinely distinct overlapping boxes (52–544 px apart). The real issue is label legibility causing occasional digit misreads.
- 2018 coverage was previously quoted as "70 of ~356." Actual is **89 of 356 (25%)**.

---

## 10. Provenance decisions worth recording

**Same-date deduplication was tried and deliberately dropped.** In the real archive, 28 of 46 same-masthead-date pairs turned out to be *different days* (the paper sometimes reuses the previous day's masthead) or partial files. Only byte-identical `sha256` is deduplicated. The cost is ~1% more extraction; the benefit is not silently losing a day's issues.

**Extraction is driven by `opencode`, not the Anthropic API.** The original design specified the Batch API; that was abandoned (the `batches` and `tiles` tables are empty). No API key is required.

**The database stores absolute paths.** A fresh clone must run `python common.py --relocate` before it can open any crop or page.

---

## Related documents

| Document | Covers |
|---|---|
| `docs/06-pilot-report.md` | Pipeline design, quality verification, blockers |
| `docs/07-job-market-pilot-findings.md` | Market analysis of the 93 extracted ads |
| `docs/08-ted-talk-brief.md` | Talk framing and caveats |
| `automations/adarsha/README.md` | Setup and run order |