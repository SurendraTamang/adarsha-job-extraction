#!/usr/bin/env python3
"""
Quick Crop Tool - Select and save multiple job ads from newspaper pages.

Opens each page image and lets you draw rectangles around job ads.
Each selection is saved as a separate cropped image.

Usage:
    python quick_crop.py <folder_with_page_images>

Controls:
    - Click and drag to select a job ad
    - Press 's' to save the selection
    - Press 'n' for next page
    - Press 'p' for previous page
    - Press 'r' to reset current selection
    - Press 'q' to quit
"""

import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    print("❌ OpenCV not found.")
    print("\nInstall with:")
    print("  pip install opencv-python")
    sys.exit(1)


class QuickCropper:
    def __init__(self, image_folder: str):
        self.folder = Path(image_folder)
        self.images = sorted(self.folder.glob("*.png"))

        if not self.images:
            print(f"❌ No PNG images found in: {image_folder}")
            sys.exit(1)

        self.current_idx = 0
        self.crop_count = 0
        self.output_dir = self.folder.parent / "cropped_jobs"
        self.output_dir.mkdir(exist_ok=True)

        # Selection state
        self.start_point = None
        self.end_point = None
        self.selecting = False
        self.current_image = None
        self.display_image = None
        self.scale = 1.0

    def mouse_callback(self, event, x, y, flags, param):
        """Handle mouse events for selection."""
        if event == cv2.EVENT_LBUTTONDOWN:
            self.start_point = (x, y)
            self.selecting = True

        elif event == cv2.EVENT_MOUSEMOVE and self.selecting:
            self.end_point = (x, y)
            self.update_display()

        elif event == cv2.EVENT_LBUTTONUP:
            self.end_point = (x, y)
            self.selecting = False
            self.update_display()

    def update_display(self):
        """Update display with current selection rectangle."""
        self.display_image = self.current_image.copy()

        if self.start_point and self.end_point:
            cv2.rectangle(
                self.display_image,
                self.start_point,
                self.end_point,
                (0, 255, 0),  # Green
                2
            )

    def load_image(self):
        """Load and scale current image for display."""
        img_path = self.images[self.current_idx]
        img = cv2.imread(str(img_path))

        if img is None:
            print(f"❌ Could not load: {img_path}")
            return False

        # Scale down if too large for screen
        h, w = img.shape[:2]
        max_height = 900

        if h > max_height:
            self.scale = max_height / h
            new_w = int(w * self.scale)
            img = cv2.resize(img, (new_w, max_height))
        else:
            self.scale = 1.0

        self.current_image = img
        self.display_image = img.copy()
        self.start_point = None
        self.end_point = None

        return True

    def save_crop(self):
        """Save the current selection as a cropped image."""
        if not self.start_point or not self.end_point:
            print("⚠️  No selection made")
            return

        # Get coordinates (handle any direction of selection)
        x1 = min(self.start_point[0], self.end_point[0])
        y1 = min(self.start_point[1], self.end_point[1])
        x2 = max(self.start_point[0], self.end_point[0])
        y2 = max(self.start_point[1], self.end_point[1])

        # Scale back to original image size
        orig_img = cv2.imread(str(self.images[self.current_idx]))
        x1_orig = int(x1 / self.scale)
        y1_orig = int(y1 / self.scale)
        x2_orig = int(x2 / self.scale)
        y2_orig = int(y2 / self.scale)

        # Crop from original image
        cropped = orig_img[y1_orig:y2_orig, x1_orig:x2_orig]

        if cropped.size == 0:
            print("⚠️  Invalid selection")
            return

        # Save
        self.crop_count += 1
        output_path = self.output_dir / f"job_{self.crop_count:03d}.png"
        cv2.imwrite(str(output_path), cropped)
        print(f"✅ Saved: {output_path.name}")

        # Reset selection
        self.start_point = None
        self.end_point = None
        self.display_image = self.current_image.copy()

    def run(self):
        """Main loop."""
        window_name = "Quick Crop - Job Ads"
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, self.mouse_callback)

        print(f"\n📁 Loading images from: {self.folder}")
        print(f"📁 Saving crops to: {self.output_dir}")
        print(f"\n🖱️  Click and drag to select job ads")
        print("⌨️  Keys: [s]ave | [n]ext | [p]rev | [r]eset | [q]uit\n")

        self.load_image()

        while True:
            # Show page info
            page_info = f"Page {self.current_idx + 1}/{len(self.images)} | Saved: {self.crop_count}"
            display = self.display_image.copy()
            cv2.putText(display, page_info, (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.putText(display, "[s]ave [n]ext [p]rev [r]eset [q]uit", (10, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)

            cv2.imshow(window_name, display)

            key = cv2.waitKey(1) & 0xFF

            if key == ord('q'):
                break
            elif key == ord('s'):
                self.save_crop()
            elif key == ord('n'):
                if self.current_idx < len(self.images) - 1:
                    self.current_idx += 1
                    self.load_image()
                    print(f"📄 Page {self.current_idx + 1}")
            elif key == ord('p'):
                if self.current_idx > 0:
                    self.current_idx -= 1
                    self.load_image()
                    print(f"📄 Page {self.current_idx + 1}")
            elif key == ord('r'):
                self.start_point = None
                self.end_point = None
                self.display_image = self.current_image.copy()

        cv2.destroyAllWindows()
        print(f"\n✅ Done! Saved {self.crop_count} job ads to: {self.output_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python quick_crop.py <folder_with_page_images>")
        print("\nExample:")
        print("  python quick_crop.py ./annapurna-post_pages")
        sys.exit(1)

    cropper = QuickCropper(sys.argv[1])
    cropper.run()
