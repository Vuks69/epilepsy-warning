#!/usr/bin/env python3
"""
Optimized epilepsy flash detector
"""

import os
import sys
import numpy as np
from PIL import Image
import imageio.v3 as iio


def srgb_to_linear(c):
    c = c / 255.0
    # Vectorized
    mask = c <= 0.04045
    result = np.empty_like(c)
    result[mask] = c[mask] / 12.92
    result[~mask] = ((c[~mask] + 0.055) / 1.055) ** 2.4
    return result


def compute_luminance(frame):
    """Compute relative luminance for entire frame"""
    # frame is H x W x 3 (RGB)
    rgb = frame[:, :, :3].astype(float)
    R = srgb_to_linear(rgb[:, :, 0])
    G = srgb_to_linear(rgb[:, :, 1])
    B = srgb_to_linear(rgb[:, :, 2])
    L = 0.2126 * R + 0.7152 * G + 0.0722 * B
    return L


def is_red_frame(frame):
    """Check if frame has significant saturated red"""
    rgb = frame[:, :, :3].astype(float)
    total = np.sum(rgb, axis=2)
    red_ratio = np.divide(
        rgb[:, :, 0], total, out=np.zeros_like(total), where=total != 0
    )
    return np.mean(red_ratio > 0.8) > 0.1  # >10% of pixels are saturated red


class FlashDetector:
    def __init__(
        self,
        downsample_size=64,  # Smaller for speed
        luminance_threshold=0.1,
        max_flashes_per_sec=3,
        area_threshold=0.25,
    ):
        self.downsample_size = downsample_size
        self.luminance_threshold = luminance_threshold
        self.max_flashes_per_sec = max_flashes_per_sec
        self.area_threshold = area_threshold

    def extract_frames(self, filepath: str):
        ext = os.path.splitext(filepath)[1].lower()
        frames = []
        try:
            if ext == ".gif":
                data = iio.imread(filepath)
                if data.ndim == 3:
                    frames = [data]
                elif data.ndim == 4:
                    frames = [data[i] for i in range(data.shape[0])]
                else:
                    frames = list(data)
            else:
                for frame in iio.imiter(filepath):
                    frames.append(frame)
                    if len(frames) > 1000:  # Limit for safety
                        break
            return frames
        except Exception as e:
            raise

    def analyze(self, filepath: str):
        frames = self.extract_frames(filepath)
        if len(frames) < 2:
            return {"is_triggering": False, "reason": "Too few frames"}

        # Downsample
        small_frames = []
        for frame in frames:
            img = Image.fromarray(frame)
            img = img.convert("RGB")
            img.thumbnail(
                (self.downsample_size, self.downsample_size), Image.Resampling.LANCZOS
            )
            small_frames.append(np.array(img))

        flashes = []
        for i in range(1, len(small_frames)):
            curr_lum = compute_luminance(small_frames[i])
            prev_lum = compute_luminance(small_frames[i - 1])
            diff = np.abs(curr_lum - prev_lum)
            significant = diff >= self.luminance_threshold
            change_area = np.mean(significant)
            if change_area > 0.01:  # At least 1% of pixels changed significantly
                red = is_red_frame(small_frames[i]) or is_red_frame(small_frames[i - 1])
                flashes.append(
                    {
                        "index": i,
                        "change_area": float(change_area),
                        "red": bool(red),
                        "time": i / 30.0,  # estimate
                    }
                )

        # Evaluate
        if not flashes:
            return {
                "is_triggering": False,
                "reason": "No significant flashes",
                "flash_count": 0,
            }

        # Count per second (assuming ~30fps)
        # Better to estimate fps
        duration = len(frames) / 30.0  # rough estimate
        if duration == 0:
            duration = len(flashes) / 30.0

        max_per_sec = 0
        window = 30  # frames = 1 sec at 30fps
        for i in range(len(flashes)):
            count = sum(
                1
                for f in flashes
                if f["index"] >= flashes[i]["index"]
                and f["index"] < flashes[i]["index"] + window
            )
            if count > max_per_sec:
                max_per_sec = count

        result = {
            "flash_count": len(flashes),
            "max_flashes_per_second": max_per_sec,
            "duration_est": duration,
            "frames_analyzed": len(frames),
        }

        if max_per_sec > self.max_flashes_per_sec:
            result["is_triggering"] = True
            result["reason"] = f"Excessive flash rate: {max_per_sec} flashes/sec"
            return result

        if max_per_sec > 0 and max_per_sec <= self.max_flashes_per_sec:
            # Check area
            for i in range(len(flashes)):
                window_flashes = [
                    f
                    for f in flashes
                    if f["index"] >= flashes[i]["index"]
                    and f["index"] < flashes[i]["index"] + window
                ]
                if len(window_flashes) <= self.max_flashes_per_sec:
                    max_area = max(f["change_area"] for f in window_flashes)
                    if max_area > self.area_threshold:
                        result["is_triggering"] = True
                        result["reason"] = f"Large flashing area: {max_area:.1%}"
                        return result

        # If very high total flash density
        if duration > 0 and len(flashes) / duration > 3.5:
            result["is_triggering"] = True
            result["reason"] = f"High average flash rate"
            return result

        result["is_triggering"] = False
        result["reason"] = "Acceptable"
        return result


if __name__ == "__main__":
    d = FlashDetector()
    print(d.analyze(sys.argv[1]))
