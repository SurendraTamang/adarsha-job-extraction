# Newspaper Job Cropping Automation

Speed up extracting job ads from newspaper PDFs.

## Setup (One-time)

```bash
# Install dependencies
brew install poppler
pip install opencv-python
```

## Workflow

### Step 1: Extract PDF pages to images

```bash
python extract_pages.py ~/Downloads/newspaper.pdf
```

This creates a folder with each page as a PNG image.

### Step 2: Quick crop job ads

```bash
python quick_crop.py ./newspaper_pages
```

This opens a visual tool:
- **Click & drag** to select a job ad
- **Press 's'** to save the selection
- **Press 'n'** for next page
- **Press 'p'** for previous page
- **Press 'q'** to quit

All cropped jobs are saved in a `cropped_jobs` folder.

### Step 3: Post to Facebook

Upload the cropped images from `cropped_jobs/` folder to your Facebook page.

## Time Savings

| Method | Time per job |
|--------|-------------|
| Manual (Preview app) | 2-3 mins |
| This tool | 15-30 secs |

For 10 jobs: **20+ minutes saved**

## Folder Structure After Use

```
automations/
├── extract_pages.py
├── quick_crop.py
├── newspaper_pages/      # Extracted page images
│   ├── page-1.png
│   ├── page-2.png
│   └── ...
└── cropped_jobs/         # Your cropped job ads
    ├── job_001.png
    ├── job_002.png
    └── ...
```

## Tips

- Use 's' immediately after selecting - don't wait
- Skip pages with no jobs using 'n'
- Cropped images are numbered automatically
- Re-run on new newspapers anytime
