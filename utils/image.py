import os
from PIL import Image

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_image(filename):
    return "." in filename and \
        filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def optimize_image(image_path, quality=85, max_size=(1280, 1280)):
    try:
        img = Image.open(image_path)

        img.thumbnail(max_size)

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        img.save(
            image_path,
            optimize=True,
            quality=quality
        )

        return True

    except Exception as e:
        print(f"Image Error: {e}")
        return False