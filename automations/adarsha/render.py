"""Page rendering, API-sized tiles, tile→page coordinates, crops.

  python render.py --from 2026-08-30 --to 2026-09-30   # 1000 px triage JPEGs (or --pdfs ids.txt)
"""
import argparse
import base64
import subprocess
import tempfile

import cv2

from common import DATA, connect, select_pdfs

MAX_EDGE = 2576          # Opus 5 / Sonnet 5 image limit, long edge
MAX_PIXELS = 3_750_000   # and total pixels


def page_count(pdf):
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    return int(next(l.split()[1] for l in out.splitlines() if l.startswith("Pages:")))


def page_text(pdf, page_no=1):
    return subprocess.run(["pdftotext", "-f", str(page_no), "-l", str(page_no), str(pdf), "-"],
                          capture_output=True, text=True).stdout


def render_page(pdf, page_no, dpi=200, width=None):
    """Render one page to a BGR image; `width` scales to that many pixels wide instead of dpi."""
    with tempfile.TemporaryDirectory() as tmp:
        size = ["-scale-to-x", str(width), "-scale-to-y", "-1"] if width else ["-r", str(dpi)]
        subprocess.run(["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-singlefile", "-png",
                        *size, str(pdf), f"{tmp}/p"], check=True, capture_output=True)
        return cv2.imread(f"{tmp}/p.png")


def tiles(img, grid=2, overlap=0.10):
    """Split into grid×grid overlapping tiles. Returns [(tile, x0, y0, scale)];
    scale < 1 when a tile was shrunk to fit the API image limit."""
    h, w = img.shape[:2]
    tw, th = int(w * (1 / grid + overlap / 2)), int(h * (1 / grid + overlap / 2))
    xs = [round(i * (w - tw) / (grid - 1)) for i in range(grid)]
    ys = [round(i * (h - th) / (grid - 1)) for i in range(grid)]
    out = []
    for y in ys:
        for x in xs:
            t = img[y:y + th, x:x + tw]
            scale = min(1.0, MAX_EDGE / max(t.shape[:2]), (MAX_PIXELS / (t.shape[0] * t.shape[1])) ** 0.5)
            if scale < 1:
                t = cv2.resize(t, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            out.append((t, x, y, scale))
    return out


def tile_bbox_to_page(bbox, x0, y0, scale):
    x, y, w, h = bbox
    return [round(x0 + x / scale), round(y0 + y / scale), round(w / scale), round(h / scale)]


def crop(img, bbox, pad=0.03):
    """Cut bbox [x, y, w, h] out of img, padded by `pad` of the page size, clamped to the page."""
    h, w = img.shape[:2]
    x, y, bw, bh = bbox
    px, py = int(w * pad), int(h * pad)
    return img[max(0, y - py):min(h, y + bh + py), max(0, x - px):min(w, x + bw + px)]


def detect_boxes(img):
    """Bordered rectangles on a page (ads are boxed): [x, y, w, h] in img pixels, near-duplicates removed."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    # keep only long straight strokes: box borders, not letters
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (W // 50, 1)))
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, H // 70)))
    lines = cv2.dilate(hor | ver, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    cnts, _ = cv2.findContours(lines, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    rects = [list(cv2.boundingRect(c)) for c in cnts]
    rects = [r for r in rects if r[2] > 0.08 * W and r[3] > 0.04 * H and r[2] * r[3] < 0.5 * W * H]
    def edges(r):
        return r[0], r[1], r[0] + r[2], r[1] + r[3]

    kept = []   # a border's inner and outer contour are the same box: every edge within 1% of page width
    for r in sorted(rects, key=lambda r: -r[2] * r[3]):
        if not any(max(abs(a - b) for a, b in zip(edges(r), edges(k))) < 0.01 * W for k in kept):
            kept.append(r)
    return sorted(kept, key=lambda r: (r[1] // 50, r[0]))


def draw_boxes(page, boxes, k):
    """Draw numbered boxes (given in full-render pixels, k = render/page scale) on a copy of the page image."""
    out = page.copy()
    for i, (x, y, w, h) in enumerate(boxes):
        x, y, w, h = (round(v / k) for v in (x, y, w, h))
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cv2.rectangle(out, (x, y), (x + 30, y + 20), (0, 0, 255), -1)
        cv2.putText(out, str(i), (x + 3, y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    return out


def draw_boxes_on_tile(tile, boxes, x0, y0, scale):
    """Same numbered boxes on a high-res tile, labels large enough to read next to the ad itself."""
    out = tile.copy()
    th, tw = out.shape[:2]
    for i, (x, y, w, h) in enumerate(boxes):
        bx, by = round((x - x0) * scale), round((y - y0) * scale)
        bw, bh = round(w * scale), round(h * scale)
        if bx + bw <= 0 or by + bh <= 0 or bx >= tw or by >= th:
            continue
        cv2.rectangle(out, (bx, by), (bx + bw, by + bh), (0, 0, 255), 3)
        # label sits just above the border when there is room, so it doesn't hide the ad's heading
        lx, ly = min(max(bx, 0), tw - 70), (by - 40 if by >= 40 else min(max(by, 0), th - 40))
        cv2.rectangle(out, (lx, ly), (lx + 70, ly + 40), (0, 0, 255), -1)
        cv2.putText(out, str(i), (lx + 6, ly + 31), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)
    return out


def jpeg_b64(img, quality=85):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--pdfs")
    a = ap.parse_args()
    conn = connect()
    for p in select_pdfs(conn, a.date_from, a.date_to, a.pdfs):
        if not p["local_path"] or p["duplicate_of"]:
            continue
        for page_no in range(1, p["page_count"] + 1):
            if conn.execute("select 1 from pages where pdf_id=? and page_no=?", (p["id"], page_no)).fetchone():
                continue
            path = DATA / "pages" / str(p["id"]) / f"p{page_no}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), render_page(p["local_path"], page_no, width=1000),
                        [cv2.IMWRITE_JPEG_QUALITY, 85])
            conn.execute("insert into pages values (?,?,?)", (p["id"], page_no, str(path)))
        conn.commit()
        print(f"pdf {p['id']}: {p['page_count']} pages", flush=True)


if __name__ == "__main__":
    main()
