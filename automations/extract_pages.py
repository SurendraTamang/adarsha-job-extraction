#!/usr/bin/env python3
"""
Extract all pages from a newspaper PDF as high-quality images.
This makes it easier to crop job ads from each page.

Usage:
    python extract_pages.py newspaper.pdf

Output:
    Creates a folder with each page as a PNG image.
"""

import sys
import subprocess
from pathlib import Path


def check_dependencies():
    """Check if required tools are installed."""
    try:
        subprocess.run(["pdftoppm", "-v"], capture_output=True, check=True)
        return True
    except FileNotFoundError:
        print("❌ 'pdftoppm' not found.")
        print("\nInstall with:")
        print("  brew install poppler")
        return False


def extract_pages(pdf_path: str):
    """Extract all pages from PDF as PNG images."""
    pdf = Path(pdf_path)

    if not pdf.exists():
        print(f"❌ File not found: {pdf_path}")
        return

    # Create output folder
    output_dir = pdf.parent / f"{pdf.stem}_pages"
    output_dir.mkdir(exist_ok=True)

    print(f"📄 Extracting pages from: {pdf.name}")
    print(f"📁 Output folder: {output_dir}")

    # Extract pages using pdftoppm
    output_prefix = output_dir / "page"

    result = subprocess.run([
        "pdftoppm",
        "-png",
        "-r", "150",  # 150 DPI - good balance of quality and size
        str(pdf),
        str(output_prefix)
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Error: {result.stderr}")
        return

    # Count extracted pages
    pages = list(output_dir.glob("*.png"))
    print(f"✅ Extracted {len(pages)} pages")
    print(f"\nNow open the folder and crop job ads from each page:")
    print(f"  open \"{output_dir}\"")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_pages.py <newspaper.pdf>")
        print("\nExample:")
        print("  python extract_pages.py ~/Downloads/annapurna-post.pdf")
        sys.exit(1)

    if not check_dependencies():
        sys.exit(1)

    extract_pages(sys.argv[1])
