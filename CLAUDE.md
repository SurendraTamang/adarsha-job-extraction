# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Planning-stage weekend project: a local job platform for Pokhara, Nepal, built on an existing Facebook page (~4k followers). Mostly docs; the only working code is a newspaper job-ad cropping tool. Not a git repo.

## Layout Gotchas

- `automations/` (plural) holds the real scripts. `automation/facebook-posting/`, `automation/job-management/` and `website/` are **empty placeholders** from the README plan.
- README's "Project Structure" is out of date (lists `automation/`, omits `automations/`).
- `docs/01..05-*.md` are the source of truth for product decisions: brainstorming, business model (free → freemium → subscriptions), daily SOPs, Facebook content templates, growth plan. Read the relevant one before proposing features or copy.

## automations/ — Newspaper Job Ad Cropper

Pipeline: newspaper PDF → page PNGs → manually cropped job ads → uploaded to Facebook.

```bash
brew install poppler          # provides pdftoppm
pip install opencv-python

python automations/extract_pages.py ~/Downloads/newspaper.pdf   # → <pdf_dir>/<pdf_stem>_pages/page-N.png (150 DPI)
python automations/quick_crop.py <pdf_dir>/<pdf_stem>_pages      # OpenCV GUI; keys: s save, n/p page, r reset, q quit
```

- `quick_crop.py` downscales pages to 900px height for display, then maps the selection back to the full-res image via `self.scale` before cropping.
- Crops go to `cropped_jobs/` as a **sibling** of the pages folder, named `job_NNN.png`. The counter restarts at 1 each run, so re-running overwrites earlier crops.
- No tests, linter, or dependency file.

## Content Rules (from docs/03-sop-operations.md, docs/04-content-strategy.md)

- Job posts follow the fixed emoji template in `docs/03-sop-operations.md` (title/company, 📍 location, requirements, 💰 salary, 📅 deadline, 📩 how to apply) and always end with `#JobSolutionPokhara #PokharaJobs`.
- Never post listings that ask seekers for money, have vague company info, too-good-to-be-true salaries, request documents upfront, or are MLM.
