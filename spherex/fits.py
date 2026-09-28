import io
import math

import numpy as np
from PIL import Image
from astropy.io import fits


def read_fits_image(data):
    """
    Read the first usable 2D image HDU from a FITS file.

    Returns:
        numpy.ndarray containing the image pixels.
    """

    with fits.open(
        io.BytesIO(data),
        memmap=False
    ) as hdul:

        for hdu in hdul:
            image = hdu.data

            if image is None:
                continue

            if not isinstance(image, np.ndarray):
                continue

            if image.ndim < 2:
                continue

            # We only want the image itself.
            # If there are extra dimensions, take the first plane.
            while image.ndim > 2:
                image = image[0]

            return np.asarray(image, dtype=np.float64)

    raise ValueError("FITS image extension not found.")


def image_to_png(image):
    """
    Convert a FITS image array into a PNG preview.

    Uses:
      - 1st percentile as the low limit
      - 99.5th percentile as the high limit
      - asinh stretch

    This is equivalent to the image stretching performed
    by the original Node implementation.
    """

    values = np.asarray(image, dtype=np.float64)

    # Flatten and remove NaN / infinity
    finite = values[
        np.isfinite(values)
    ]

    if finite.size == 0:
        raise ValueError(
            "FITS image contains no finite pixels."
        )

    low = float(
        np.percentile(finite, 1)
    )

    high = float(
        np.percentile(finite, 99.5)
    )

    if not math.isfinite(high):
        high = low + 1

    if high <= low:
        high = low + 1

    image_range = high - low

    # Same general stretch as the original:
    #
    # stretchScale = range / 3
    # stretchMax = asinh(range / stretchScale)
    stretch_scale = image_range / 3

    stretch_max = np.arcsinh(
        image_range / stretch_scale
    )

    # Shift by low percentile.
    normalized = np.maximum(
        0,
        values - low
    )

    # asinh stretch
    normalized = np.arcsinh(
        normalized / stretch_scale
    ) / stretch_max

    # Clamp to 0..1
    normalized = np.clip(
        normalized,
        0,
        1
    )

    # Convert to 8-bit
    pixel_values = np.round(
        normalized * 255
    ).astype(np.uint8)

    # Replace invalid pixels with black
    pixel_values[
        ~np.isfinite(values)
    ] = 0

    # The original Node implementation produces
    # an RGB image with a slight blue tint:
    #
    # R = value * 0.72
    # G = value * 0.86
    # B = value
    #
    red = np.round(
        pixel_values * 0.72
    ).astype(np.uint8)

    green = np.round(
        pixel_values * 0.86
    ).astype(np.uint8)

    blue = pixel_values

    rgb = np.stack(
        [red, green, blue],
        axis=-1
    )

    png = Image.fromarray(
        rgb,
        mode="RGB"
    )

    output = io.BytesIO()

    png.save(
        output,
        format="PNG"
    )

    return output.getvalue()


def fits_to_png(data):
    """
    Convert raw FITS bytes directly to PNG bytes.
    """

    image = read_fits_image(data)

    return image_to_png(image)