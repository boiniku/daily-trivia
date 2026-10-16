from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from trivia_photo.image_format import app_frame, frame_size, prepare_image, vision_image


class ImageFormatTests(unittest.TestCase):
    def test_large_photo_fits_the_app_frame(self):
        self.assertEqual(frame_size((4000, 3000)), (1600, 900))

    def test_portrait_and_small_photos_are_not_enlarged(self):
        for size in ((800, 1200), (960, 540), (1500, 3000), (3000, 400)):
            width, height = frame_size(size)
            self.assertLessEqual(width, size[0])
            self.assertLessEqual(height, size[1])
            self.assertEqual(width * 9, height * 16)

    def test_crop_keeps_the_center_that_cover_displays(self):
        image = Image.new("RGB", (1600, 1600), "red")
        ImageDraw.Draw(image).rectangle((0, 350, 1599, 1249), fill="blue")
        framed = app_frame(image)
        self.assertEqual(framed.size, (1600, 900))
        self.assertEqual(framed.getpixel((800, 450)), (0, 0, 255))
        self.assertEqual(framed.getpixel((800, 100)), (0, 0, 255))

    def test_ai_sees_app_crop_instead_of_full_portrait(self):
        image = Image.new("RGB", (800, 1200), "red")
        ImageDraw.Draw(image).rectangle((0, 375, 799, 824), fill="blue")
        data = BytesIO()
        image.save(data, "PNG")
        with Image.open(BytesIO(vision_image(data.getvalue()))) as framed:
            self.assertEqual(framed.size, (512, 288))
            self.assertGreater(framed.getpixel((256, 144))[2], 240)

    def test_source_is_preserved_and_cropping_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Image.new("RGB", (800, 1200), "green")
            data = BytesIO()
            image.save(data, "JPEG")
            asset = prepare_image(data.getvalue())
            with Image.open(BytesIO(asset["data"])) as framed, Image.open(BytesIO(asset["source"]["data"])) as source:
                self.assertEqual(framed.size, (800, 450))
                self.assertEqual(source.size, (800, 1200))
            self.assertTrue(asset["processing"]["cropped"])
            self.assertNotEqual(asset["sha256"], asset["source"]["sha256"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_exif_orientation_is_applied_before_cropping(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Image.new("RGB", (800, 600), "green")
            exif = image.getexif()
            exif[274] = 6
            data = BytesIO()
            image.save(data, "JPEG", exif=exif)
            asset = prepare_image(data.getvalue())
            self.assertEqual(asset["processing"]["source_size"], [600, 800])
            self.assertEqual((asset["width"], asset["height"]), (592, 333))

    def test_existing_app_size_setting_is_honored(self):
        with tempfile.TemporaryDirectory() as directory:
            data = BytesIO()
            Image.new("RGB", (4000, 3000), "green").save(data, "JPEG")
            asset = prepare_image(data.getvalue(), max_dimension=1280, quality=65)
            self.assertEqual((asset["width"], asset["height"]), (1280, 720))
            self.assertEqual(asset["processing"]["webp_quality"], 65)
