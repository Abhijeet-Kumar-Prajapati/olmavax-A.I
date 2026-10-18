"""
Open Charvis - Media creation
============================
Image, animation and video generation.

Two engines:

**Offline engine (always available).**  A pure standard library renderer
with its own PNG encoder (zlib + CRC32, no Pillow required).  It produces
genuine generative art - fractal plasma, domain warping, geometric
constellations, circuit fields - deterministically seeded from the prompt,
so the same prompt always paints the same picture and different prompts
paint different ones.

**Online engine (optional).**  If a diffusion API key is present in the
vault or environment, the same prompt is sent to it and the result is
downloaded instead.  If no key exists, nothing breaks: the offline engine
is used and the response says so.

Animation writes a numbered PNG sequence plus a self-contained animated
SVG, and upgrades to MP4/GIF when ffmpeg happens to be installed.
"""

from __future__ import annotations

import colorsys
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import time
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import PATHS, ensure_dirs
from ..logger import log_warn
from ..utils import http_get_bytes, run_command, truncate
from . import tool

MAX_SIDE = 768

# Free, no-API-key image generation. This is what makes "draw me a photo"
# actually work out of the box with nothing configured.
POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"

# Local engines, used automatically when they are installed.
LOCAL_ENGINES = (
    ("automatic1111", "http://127.0.0.1:7860", "/sdapi/v1/txt2img"),
    ("comfyui", "http://127.0.0.1:8188", "/prompt"),
)

# Prompt flavour words. The free endpoint has no style flag, so the style is
# expressed through the prompt itself.
STYLE_HINTS = {
    "realistic": "photorealistic, highly detailed, 8k, cinematic lighting",
    "anime": "anime style illustration, vibrant, clean line art",
    "3d": "3d render, octane render, soft shadows, studio lighting",
    "digital": "digital art, concept art, sharp focus, dramatic lighting",
    "photo": "photograph, natural light, sharp focus, high detail",
    "sketch": "pencil sketch, hand drawn, monochrome",
}

STYLES = (
    "plasma",      # flowing interference field, the most Jarvis looking
    "fractal",     # zoomed fractal noise
    "neon-grid",   # retro wireframe horizon
    "core",        # glowing reactor orb
    "circuit",     # circuitry / data board
    "starfield",   # deep space with parallax stars
    "aurora",      # soft colour bands
)


# --------------------------------------------------------------------------
# PNG encoder (standard library only)
# --------------------------------------------------------------------------


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, pixels: bytes) -> bytes:
    """
    Encode 8-bit RGB pixel data as a PNG.

    ``pixels`` must be exactly ``width * height * 3`` bytes in row-major
    order.  One filter byte (0 = None) is prepended per scanline, which is
    what the format expects.
    """
    stride = width * 3
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        raw.extend(pixels[row * stride : (row + 1) * stride])

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


def save_png(path: Path, width: int, height: int, pixels: bytes) -> int:
    data = encode_png(width, height, pixels)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


# --------------------------------------------------------------------------
# Animated GIF encoder - video that works without ffmpeg
# --------------------------------------------------------------------------


def _quantise(samples: List[Tuple[int, int, int]], max_colors: int = 256
              ) -> List[Tuple[int, int, int]]:
    """
    Median-cut colour quantisation.

    Repeatedly splits the colour box with the widest channel range down its
    median until the requested number of boxes exists, then uses the average
    of each box as that box's colour. Not as good as a perceptual method,
    but it is honest, stable, and about forty lines.
    """
    if not samples:
        return [(0, 0, 0)]

    boxes: List[List[int]] = [list(range(len(samples)))]
    while len(boxes) < max_colors:
        target, spread = -1, 0.0
        for index, box in enumerate(boxes):
            if len(box) < 2:
                continue
            for axis in range(3):
                values = [samples[i][axis] for i in box]
                span = max(values) - min(values)
                if span > spread:
                    spread, target = span, index
                # Track which axis won by re-reading it cheaply below.
        if target < 0:
            break
        box = boxes[target]
        axis = max(range(3),
                   key=lambda a: max(samples[i][a] for i in box) - min(samples[i][a] for i in box))
        box.sort(key=lambda i: samples[i][axis])
        mid = len(box) // 2
        boxes[target] = box[:mid]
        boxes.append(box[mid:])

    palette: List[Tuple[int, int, int]] = []
    for box in boxes:
        if not box:
            continue
        count = len(box)
        palette.append((
            sum(samples[i][0] for i in box) // count,
            sum(samples[i][1] for i in box) // count,
            sum(samples[i][2] for i in box) // count,
        ))
    while len(palette) < max_colors:
        palette.append((0, 0, 0))
    return palette


def _nearest_map(palette: List[Tuple[int, int, int]]) -> Dict[int, int]:
    cache: Dict[int, int] = {}
    table = palette

    def nearest(rgb: int) -> int:
        hit = cache.get(rgb)
        if hit is not None:
            return hit
        r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
        best, best_d = 0, 1 << 30
        for index, (pr, pg, pb) in enumerate(table):
            dr, dg, db = r - pr, g - pg, b - pb
            # Weighted by perception - green matters more than blue.
            d = dr * dr * 3 + dg * dg * 6 + db * db
            if d < best_d:
                best_d, best = d, index
                if d == 0:
                    break
        cache[rgb] = best
        return best

    return nearest


def _lzw_encode(indices: Sequence[int], min_code_size: int) -> bytes:
    """GIF's variant of LZW. Codes are packed least-significant bit first."""
    clear_code = 1 << min_code_size
    end_code = clear_code + 1
    max_code = (1 << 12) - 1

    out = bytearray()
    buffer = 0
    bits = 0

    def emit(code: int, size: int) -> None:
        nonlocal buffer, bits
        buffer |= code << bits
        bits += size
        while bits >= 8:
            out.append(buffer & 0xFF)
            buffer >>= 8
            bits -= 8

    code_size = min_code_size + 1
    next_code = end_code + 1
    table = {(i,): i for i in range(clear_code)}
    emit(clear_code, code_size)

    prefix: Tuple[int, ...] = ()
    for value in indices:
        candidate = prefix + (value,)
        found = table.get(candidate)
        if found is not None:
            prefix = candidate
            continue
        emit(table[prefix], code_size)
        if next_code <= max_code:
            table[candidate] = next_code
            next_code += 1
            # Grow the code width the moment the table can no longer be
            # described by the current number of bits.
            if next_code > (1 << code_size) - 1 and code_size < 12:
                code_size += 1
        else:
            # Table full: reset and tell the decoder to start over.
            emit(clear_code, code_size)
            table = {(i,): i for i in range(clear_code)}
            next_code = end_code + 1
            code_size = min_code_size + 1
        prefix = (value,)

    if prefix:
        emit(table[prefix], code_size)
    emit(end_code, code_size)
    if bits:
        out.append(buffer & 0xFF)
    return bytes(out)


def _sub_blocks(data: bytes) -> bytes:
    """GIF carries compressed data in blocks of at most 255 bytes."""
    out = bytearray()
    for start in range(0, len(data), 255):
        part = data[start:start + 255]
        out.append(len(part))
        out += part
    out.append(0)
    return bytes(out)


def encode_gif(frames: List[bytes], width: int, height: int, delay_ms: int = 80,
               loops: int = 0, max_colors: int = 256) -> bytes:
    """
    Assemble raw RGB frames into an animated GIF89a.

    This is the format that actually travels: WhatsApp, Telegram, email and
    every image viewer take a GIF, and none of them need a codec. It needs
    nothing from the standard library beyond what is already imported here,
    which is the point - it means animation works on a machine that has
    never heard of ffmpeg.

    One palette is shared by every frame (that is what the format's global
    colour table is for), built by median cut over a sample of all frames so
    the colours do not flicker between frames.
    """
    if not frames:
        raise ValueError("no frames")

    stride = width * 3
    # Sample rather than read every pixel: quantisation only needs a rough
    # view of the colour distribution, and this keeps a 40-frame render fast.
    samples: List[Tuple[int, int, int]] = []
    step = max(1, (stride * height) // 512)
    for frame in frames[:: max(1, len(frames) // 6)]:
        for offset in range(0, stride * height, step * 3):
            samples.append((frame[offset], frame[offset + 1], frame[offset + 2]))
    if not samples:
        samples = [(0, 0, 0)]

    palette = _quantise(samples, max_colors)
    nearest = _nearest_map(palette)
    table_bits = max(1, (max_colors - 1).bit_length())
    table_size = 1 << table_bits

    delay_cs = max(1, round(delay_ms / 10))

    out = bytearray(b"GIF89a")
    out += struct.pack("<HHBBB", width, height, 0x80 | ((table_bits - 1) & 0x07), 0, 0)
    for index in range(table_size):
        r, g, b = palette[index] if index < len(palette) else (0, 0, 0)
        out += bytes((r, g, b))

    # Netscape extension - this is what makes it loop forever.
    out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01" + struct.pack("<H", loops) + b"\x00"

    for frame in frames:
        # Graphic Control Extension: delay, and disposal 2 (restore to
        # background) so frames do not smear into each other.
        out += b"\x21\xF9\x04" + bytes((0x04,)) + struct.pack("<H", delay_cs) + b"\x00\x00"
        out += b"\x2C" + struct.pack("<HHHHB", 0, 0, width, height, 0)

        indices = bytearray(width * height)
        for i in range(width * height):
            base = i * 3
            rgb = (frame[base] << 16) | (frame[base + 1] << 8) | frame[base + 2]
            indices[i] = nearest(rgb)
        out += bytes((8,))
        out += _sub_blocks(_lzw_encode(indices, 8))

    out += b"\x3B"
    return bytes(out)


# --------------------------------------------------------------------------
# APNG encoder - a real animated image, with no external tools at all
# --------------------------------------------------------------------------


def encode_apng(frames: List[bytes], width: int, height: int, delay_ms: int = 100,
                loops: int = 0) -> bytes:
    """
    Assemble raw RGB frames into an animated PNG (APNG).

    APNG is an extension of PNG that lives in the same file format, so this
    needs nothing but :mod:`zlib` and :mod:`struct`. It gives a genuinely
    animated file that plays in every browser and image viewer, which is
    what makes animation work on a machine with no ffmpeg installed.

    Args:
        frames: one ``width * height * 3`` RGB buffer per frame.
        delay_ms: time each frame is shown.
        loops: 0 means play forever.
    """
    if not frames:
        raise ValueError("no frames")

    stride = width * 3
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    out += _chunk(b"acTL", struct.pack(">II", len(frames), loops))

    sequence = 0
    for index, pixels in enumerate(frames):
        raw = bytearray()
        for row in range(height):
            raw.append(0)
            raw.extend(pixels[row * stride : (row + 1) * stride])
        compressed = zlib.compress(bytes(raw), 6)
        out += _chunk(
            b"fcTL",
            # sequence, width, height, x_offset, y_offset,
            # delay_num, delay_den, dispose_op(NONE), blend_op(SOURCE)
            struct.pack(
                ">IIIIIHHBB", sequence, width, height, 0, 0, delay_ms, 100, 0, 0
            ),
        )
        out += _chunk(b"IDAT" if index == 0 else b"fdAT",
                      compressed if index == 0
                      else struct.pack(">I", sequence) + compressed)
        sequence += 1

    out += _chunk(b"IEND", b"")
    return bytes(out)


# --------------------------------------------------------------------------
# Deterministic seeding
# --------------------------------------------------------------------------


def seed_from(text: str) -> int:
    digest = hashlib.blake2b((text or "charvis").encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


class Rng:
    """Tiny deterministic PRNG so output is reproducible across runs."""

    def __init__(self, seed: int):
        self.state = (seed ^ 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF

    def next(self) -> int:
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        return (self.state >> 33) & 0x7FFFFFFF

    def unit(self) -> float:
        return self.next() / float(0x7FFFFFFF)

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self.unit()

    def choice(self, options: List[Any]) -> Any:
        return options[self.next() % len(options)]


def _hsv(h: float, s: float, v: float) -> Tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return int(r * 255), int(g * 255), int(b * 255)


# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------


def _render_plasma(width: int, height: int, rng: Rng) -> bytearray:
    """
    Interference field with two levels of domain warping.

    The warp is what stops this looking like plain diagonal stripes: each
    point is displaced by the field itself before being sampled again, which
    produces the folded, flowing structure.
    """
    base = rng.uniform(0.0, 1.0)
    # Two colour stops for the hue ramp (cyan -> violet -> amber).
    stops = [base + rng.uniform(-0.06, 0.06), base + rng.uniform(0.18, 0.42)]
    ramp = (stops[1] - stops[0]) % 1.0

    waves = [
        (rng.uniform(1.4, 2.6), rng.uniform(1.8, 3.6), rng.uniform(0.0, 6.28))
        for _ in range(3)
    ]
    fine = [
        (rng.uniform(7.0, 13.0), rng.uniform(0.0, 6.28), rng.uniform(0.10, 0.22))
        for _ in range(3)
    ]
    warp_amount = rng.uniform(0.35, 0.70)
    core_bias = rng.uniform(0.15, 0.45)

    out = bytearray(width * height * 3)
    tau = 6.28318
    aspect = width / height

    for y in range(height):
        v = y / height
        # per-row sine cache keeps the inner loop to two trig calls
        row_cos = [math.cos(v * tau * f + phase) for f, phase, _a in waves]
        row_cos_fine = [math.cos(v * tau * f + phase) for f, phase, _a in fine]
        for x in range(width):
            u = x / width

            # first warp
            wx = u + warp_amount * 0.18 * math.sin(v * 5.1 + waves[0][2])
            wy = v + warp_amount * 0.18 * math.cos(u * 4.7 + waves[1][2])

            # second warp, sampling the field
            field_a = sum(a * math.sin(fx * wx * tau + cx) for fx, cx, a in waves)
            wx += warp_amount * 0.14 * field_a
            wy += warp_amount * 0.14 * math.cos(field_a * 2.1 + waves[2][2])

            value = 0.0
            for index, (fx, cx, amplitude) in enumerate(waves):
                value += amplitude * math.sin(fx * wx * tau + cx + row_cos[index] * 1.1)
            total = sum(w[2] for w in waves)
            value = value / (total * 2.0) + 0.5

            # fine detail on top
            detail = 0.0
            for index, (fx, cx, amplitude) in enumerate(fine):
                detail += amplitude * math.sin(fx * wx * tau * 1.7 + cx + row_cos_fine[index])
            value = max(0.0, min(1.0, value + detail * 0.35))

            # radial core glow so it reads as a reactor rather than a texture
            dx = (u - 0.5) * aspect
            dy = v - 0.5
            radius = math.sqrt(dx * dx + dy * dy) / 0.5
            core = max(0.0, 1.0 - radius) ** 2.4
            value = max(0.0, min(1.0, value + core * core_bias))

            hue = stops[0] + ramp * value
            saturation = 0.58 + 0.38 * (1.0 - core * 0.4)
            lightness = 0.04 + 0.94 * (value ** 1.5)
            r, g, b = _hsv(hue, saturation, lightness)
            offset = (y * width + x) * 3
            out[offset] = r
            out[offset + 1] = g
            out[offset + 2] = b
    return out


def _render_fractal(width: int, height: int, rng: Rng) -> bytearray:
    """Value noise summed over octaves."""
    octaves = 5
    grids = []
    for octave in range(octaves):
        size = 2 * (octave + 1)
        grids.append([[rng.unit() for _ in range(size + 1)] for _ in range(size + 1)])

    def sample(grid: List[List[float]], size: int, u: float, v: float) -> float:
        fx, fy = u * size, v * size
        x0, y0 = int(fx) % size, int(fy) % size
        x1, y1 = (x0 + 1) % size, (y0 + 1) % size
        tx, ty = fx - int(fx), fy - int(fy)
        tx = tx * tx * (3 - 2 * tx)
        ty = ty * ty * (3 - 2 * ty)
        top = grid[y0][x0] * (1 - tx) + grid[y0][x1] * tx
        bottom = grid[y1][x0] * (1 - tx) + grid[y1][x1] * tx
        return top * (1 - ty) + bottom * ty

    base = rng.uniform(0, 1)
    out = bytearray(width * height * 3)
    for y in range(height):
        v = y / height
        for x in range(width):
            u = x / width
            total, amplitude, norm = 0.0, 1.0, 0.0
            for octave, grid in enumerate(grids):
                total += sample(grid, 2 * (octave + 1), u, v) * amplitude
                norm += amplitude
                amplitude *= 0.5
            value = total / norm
            hue = base + 0.35 * value
            r, g, b = _hsv(hue, 0.65, 0.08 + 0.9 * value)
            offset = (y * width + x) * 3
            out[offset] = r
            out[offset + 1] = g
            out[offset + 2] = b
    return out


def _render_core(width: int, height: int, rng: Rng) -> bytearray:
    """Glowing orb in the centre, like an arc reactor."""
    cx, cy = width / 2.0, height / 2.0
    radius = min(width, height) * 0.34
    hue = rng.uniform(0.05, 0.65)
    out = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            dx, dy = x - cx, y - cy
            distance = math.hypot(dx, dy) / radius
            if distance < 1.0:
                glow = (1.0 - distance) ** 2.2
                ring = 0.35 * math.sin(distance * 26.0) ** 2
                value = glow * (0.75 + ring)
            else:
                fade = max(0.0, 1.0 - (distance - 1.0) * 1.6)
                value = fade * fade * 0.22
            value = max(0.0, min(1.0, value))
            r, g, b = _hsv(hue + value * 0.22, 0.55 + 0.45 * value, 0.04 + 0.96 * value)
            offset = (y * width + x) * 3
            out[offset] = r
            out[offset + 1] = g
            out[offset + 2] = b
    return out


def _render_neon_grid(width: int, height: int, rng: Rng) -> bytearray:
    """Wireframe horizon with a sun and a glowing ground plane."""
    horizon = height * 0.58
    hue = rng.uniform(0.78, 0.95)
    sun_hue = rng.uniform(0.02, 0.14)
    sun_x, sun_r = width * 0.5, min(width, height) * 0.19
    tau = 6.28318
    out = bytearray(width * height * 3)

    for y in range(height):
        for x in range(width):
            if y < horizon:
                depth = (horizon - y) / horizon
                # sky gradient with horizontal scan bands
                band = 0.5 + 0.5 * math.sin(depth * 26.0)
                glow = depth ** 0.55
                r, g, b = _hsv(hue + 0.12 * glow, 0.80, 0.03 + 0.30 * glow + 0.03 * band)
            else:
                depth = (y - horizon) / max(1.0, height - horizon)
                # perspective ground plane
                scale = 1.0 / (depth * 16.0 + 0.05)
                line_y = abs(((depth * 16.0) % 1.0) - 0.5) * 2.0
                horiz = max(0.0, 1.0 - line_y) * min(1.0, scale * 0.70)
                column = (x / width) * 24.0
                vert = max(0.0, 1.0 - abs((column % 1.0) - 0.5) * 2.0) * min(1.0, scale * 0.42)
                value = min(1.0, horiz + vert)
                r, g, b = _hsv(hue, 0.92, 0.03 + 0.88 * value)

            # the sun sits on the horizon and overdraws both halves
            dx, dy = x - sun_x, y - (horizon - sun_r * 0.55)
            distance = math.hypot(dx, dy) / sun_r
            if distance < 1.0:
                inside = distance < 0.82
                if inside:
                    slats = 0.5 + 0.5 * math.sin(y / (sun_r * 0.16) + 1.2)
                    r, g, b = _hsv(sun_hue + 0.16 * slats, 0.85, 0.55 + 0.45 * slats)
                else:
                    halo = (1.0 - distance) ** 2.0
                    r, g, b = _hsv(sun_hue, 0.8, 0.10 + 0.85 * halo)

            offset = (y * width + x) * 3
            out[offset], out[offset + 1], out[offset + 2] = r, g, b
    return out


def _render_circuit(width: int, height: int, rng: Rng) -> bytearray:
    """Circuit traces and glowing nodes."""
    hue = rng.uniform(0.35, 0.6)
    canvas = bytearray(width * height * 3)
    for index in range(0, len(canvas), 3):
        canvas[index] = 6
        canvas[index + 1] = 14
        canvas[index + 2] = 12

    def dot(px: int, py: int, radius: int, intensity: float) -> None:
        for oy in range(-radius, radius + 1):
            for ox in range(-radius, radius + 1):
                x, y = px + ox, py + oy
                if 0 <= x < width and 0 <= y < height:
                    falloff = max(0.0, 1.0 - math.hypot(ox, oy) / (radius + 1))
                    add = falloff * intensity
                    offset = (y * width + x) * 3
                    r, g, b = _hsv(hue + add * 0.15, 0.7, min(1.0, 0.45 + add))
                    canvas[offset] = min(255, int(canvas[offset] + r * add))
                    canvas[offset + 1] = min(255, int(canvas[offset + 1] + g * add))
                    canvas[offset + 2] = min(255, int(canvas[offset + 2] + b * add))

    traces = max(8, (width * height) // 9000)
    for _ in range(traces):
        x, y = rng.uniform(0, width), rng.uniform(0, height)
        horizontal = rng.unit() > 0.5
        for _ in range(rng.randint(12, 46)):
            step = rng.randint(3, 18)
            if horizontal:
                x += step * rng.choice([-1, 1])
            else:
                y += step * rng.choice([-1, 1])
            if 0 <= int(x) < width and 0 <= int(y) < height:
                dot(int(x), int(y), 1, 0.55)
                if rng.unit() > 0.93:
                    dot(int(x), int(y), rng.randint(3, 6), 0.95)
    return canvas


def _render_starfield(width: int, height: int, rng: Rng) -> bytearray:
    """Deep space with parallax stars and a nebula wash."""
    out = bytearray(width * height * 3)
    hue = rng.uniform(0.55, 0.75)
    for y in range(height):
        for x in range(width):
            nebula = (
                math.sin(x / width * 4.0 + math.cos(y / height * 3.0) * 2.0)
                * math.cos(y / height * 3.5)
            )
            value = 0.06 + 0.10 * max(0.0, nebula)
            r, g, b = _hsv(hue, 0.7, value)
            offset = (y * width + x) * 3
            out[offset], out[offset + 1], out[offset + 2] = r, g, b
    for layer, count in enumerate(((width * height) // 900, (width * height) // 3200)):
        brightness = 0.9 - layer * 0.35
        radius = 1 if layer == 0 else 2
        for _ in range(count):
            x, y = rng.uniform(0, width), rng.uniform(0, height)
            tint = rng.uniform(0.85, 1.0)
            offset = (int(y) * width + int(x)) * 3
            out[offset] = min(255, int(out[offset] + 255 * tint * brightness))
            out[offset + 1] = min(255, int(out[offset + 1] + 255 * tint * brightness))
            out[offset + 2] = min(255, int(out[offset + 2] + 255 * brightness))
            if radius > 1:
                for ox, oy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
                    nxp, nyp = int(x) + ox, int(y) + oy
                    if 0 <= nxp < width and 0 <= nyp < height:
                        nidx = (nyp * width + nxp) * 3
                        out[nidx] = min(255, out[nidx] + 120)
    return out


def _render_aurora(width: int, height: int, rng: Rng) -> bytearray:
    """Soft flowing colour bands."""
    bands = rng.randint(3, 6)
    palette = [rng.uniform(0, 1) for _ in range(bands)]
    out = bytearray(width * height * 3)
    for y in range(height):
        v = y / height
        for x in range(width):
            u = x / width
            value = 0.0
            for index, hue in enumerate(palette):
                value += math.sin(u * (2 + index) + v * 3.0 + hue * 6.28) / (index + 2)
            value = value / bands + 0.5
            hue = palette[int(max(0.0, min(0.999, value))) * bands]
            r, g, b = _hsv(hue + 0.1, 0.55, 0.06 + 0.85 * max(0.0, min(1.0, value)))
            offset = (y * width + x) * 3
            out[offset], out[offset + 1], out[offset + 2] = r, g, b
    return out


RENDERERS = {
    "plasma": _render_plasma,
    "fractal": _render_fractal,
    "core": _render_core,
    "neon-grid": _render_neon_grid,
    "circuit": _render_circuit,
    "starfield": _render_starfield,
    "aurora": _render_aurora,
}


def render(style: str, width: int, height: int, seed: int) -> bytearray:
    rng = Rng(seed)
    return RENDERERS.get(style, _render_plasma)(width, height, rng)


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


def _exports() -> Path:
    ensure_dirs()
    folder = PATHS["exports"] / "media"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _safe_name(prompt: str) -> str:
    keep = "".join(ch if ch.isalnum() else "-" for ch in (prompt or "image").lower())
    return "-".join(filter(None, keep.split("-")))[:50] or "image"


# --------------------------------------------------------------------------
# Real AI image generation
# --------------------------------------------------------------------------


def _local_engine():
    """Find a locally installed diffusion engine, if there is one."""
    from ..utils import http_get

    for name, host, _endpoint in LOCAL_ENGINES:
        if http_get(f"{host}/", timeout=2)[0] in (200, 404):
            return name, host
    return None, None


def _prompt_url(prompt: str, flavour: str, width: int, height: int, seed: int) -> str:
    import urllib.parse

    text = f"{prompt}, {STYLE_HINTS.get(flavour, STYLE_HINTS['digital'])}"
    return POLLINATIONS.format(prompt=urllib.parse.quote(text, safe="")) + (
        f"?width={width}&height={height}&nologo=true&seed={seed}"
    )


def _fetch_ai_image(prompt: str, flavour: str, width: int, height: int,
                    seed: int, attempts: int = 4) -> Dict[str, Any]:
    """
    Ask a diffusion model for a real image. No key, no signup.

    The free endpoint answers 402 when its anonymous rate limit is hit, which
    is a *wait* condition rather than a failure, so it is retried with a
    backoff. A local Automatic1111 or ComfyUI install is used first if one is
    running, since that is unlimited and free.
    """
    import time as _time

    # 1. Prefer a local engine when one is running.
    name, host = _local_engine()
    if host:
        if name == "automatic1111":
            from ..utils import http_post_json

            payload = {"prompt": prompt, "width": width, "height": height,
                       "steps": 25, "cfg_scale": 7}
            status, body = http_post_json(f"{host}/sdapi/v1/txt2img", payload, timeout=180)
            try:
                images = json.loads(body).get("images", [])
                if images:
                    import base64

                    raw = base64.b64decode(images[0])
                    return {"ok": True, "engine": "local:automatic1111", "bytes": raw,
                            "content_type": "image/png"}
            except (json.JSONDecodeError, ValueError):
                pass

    # 2. Otherwise the keyless hosted engine.
    url = _prompt_url(prompt, flavour, width, height, seed)
    signatures = (
        b"\x89PNG\r\n\x1a\n",   # PNG
        b"\xff\xd8\xff",        # JPEG
        b"RIFF",                # WEBP / AVIF container
        b"<svg",
    )
    last = ""
    for attempt in range(attempts):
        status, data, content_type = http_get_bytes(url, timeout=120)
        # startswith, not a slice comparison: a JPEG body begins with three
        # bytes, and comparing data[:4] against a two-byte signature can
        # never match - which silently sent every real photo to the fallback.
        if status == 200 and len(data) > 2000 and any(
            data.startswith(sig) for sig in signatures
        ):
            suffix = None
            kind = "png"
            if data.startswith(b"\xff\xd8\xff"):
                kind = "jpg"
            elif data.startswith(b"RIFF"):
                kind = "webp"
            elif data.startswith(b"<svg"):
                kind = "svg"
            return {"ok": True, "engine": "pollinations (free, no key)",
                    "bytes": data, "content_type": content_type or f"image/{kind}",
                    "kind": kind}
        last = f"HTTP {status} ({len(data)} bytes)"
        if status in (402, 429, 503):         # rate limited: back off and retry
            _time.sleep(3 + attempt * 3)
            continue
        break
    return {"ok": False, "error": f"image engine unreachable: {last}"}


@tool("media.image", "Generate a real image or painting from a text prompt",
      capabilities=["media.create", "files.write", "net.fetch"], risk=0.15,
      tags=["media", "image", "art"])
def media_image(
    prompt: str,
    style: str = "auto",
    width: int = 512,
    height: int = 512,
) -> Dict[str, Any]:
    """
    Draw a picture.

    ``style="auto"`` (the default) uses a real diffusion model - a local
    Automatic1111/ComfyUI install if one is running, otherwise a free hosted
    engine that needs no API key. Requires internet the first time.

    Naming one of the procedural styles (plasma, fractal, core, neon-grid,
    circuit, starfield, aurora) renders locally with no network at all.
    """
    ensure_dirs()
    width = max(64, min(1024, int(width)))
    height = max(64, min(1024, int(height)))
    seed = seed_from(f"{prompt}|{style}|{width}x{height}") % 100000
    target = _exports() / f"{_safe_name(prompt)}-{seed}.png"
    started = time.perf_counter()

    if style != "auto":
        pixels = render(style if style in RENDERERS else "plasma", width, height, seed)
        size = save_png(target, width, height, bytes(pixels))
        return {
            "ok": True, "engine": "offline-generative", "style": style,
            "path": str(target), "width": width, "height": height, "bytes": size,
            "seed": seed, "render_seconds": round(time.perf_counter() - started, 2),
            "prompt": prompt, "note": "same prompt always produces the same image",
        }

    result = _fetch_ai_image(prompt, "realistic", width, height, seed)
    if not result["ok"]:
        # Never just fail: fall back to the offline renderer and say why.
        pixels = render("plasma", min(width, 512), min(height, 512), seed)
        fallback = _exports() / f"{_safe_name(prompt)}-{seed}-offline.png"
        save_png(fallback, min(width, 512), min(height, 512), bytes(pixels))
        return {
            "ok": True,
            "engine": "offline-generative (fallback)",
            "style": "plasma",
            "path": str(fallback),
            "width": min(width, 512), "height": min(height, 512),
            "bytes": fallback.stat().st_size, "seed": seed,
            "render_seconds": round(time.perf_counter() - started, 2),
            "prompt": prompt,
            "warning": result["error"] + " - drew a local pattern instead of a real picture",
        }

    raw = result["bytes"]
    kind = result.get("kind", "png")
    target = target.with_suffix({"jpg": ".jpg", "webp": ".webp", "svg": ".svg"}.get(kind, ".png"))
    target.write_bytes(raw)
    return {
        "ok": True,
        "engine": result["engine"],
        "style": "realistic",
        "path": str(target),
        "width": width, "height": height,
        "bytes": len(raw), "seed": seed,
        "render_seconds": round(time.perf_counter() - started, 2),
        "prompt": prompt,
        "note": "generated by a real diffusion model - no key required",
    }


@tool("media.styles", "List the available generative art styles",
      capabilities=["chat"], risk=0.02, tags=["media", "info"])
def media_styles() -> List[str]:
    return list(STYLES)


@tool("media.animation", "Create an animation from a prompt",
      capabilities=["media.create", "files.write"], risk=0.25, tags=["media", "animation"])
def media_animation(
    prompt: str,
    style: str = "core",
    frames: int = 24,
    size: int = 256,
    fps: int = 12,
) -> Dict[str, Any]:
    """
    Render a frame sequence and package it three ways:

    * a numbered PNG sequence (always works)
    * a self contained animated SVG (always works, plays in any browser)
    * MP4 and/or GIF when ffmpeg is installed

    The animated SVG is built from base64 frames played by SMIL, so it needs
    no JavaScript and no network.
    """
    style = style if style in RENDERERS else "core"
    frames = max(6, min(48, int(frames)))
    size = max(96, min(384, int(size)))
    fps = max(6, min(30, int(fps)))
    base_seed = seed_from(prompt)
    stamp_id = int(time.time())

    folder = _exports() / f"anim-{stamp_id}"
    folder.mkdir(parents=True, exist_ok=True)
    frame_paths: List[str] = []
    started = time.perf_counter()

    for index in range(frames):
        phase = index / frames
        pixels = render(style, size, size, base_seed + index)
        if style in {"core", "plasma", "aurora"}:
            # breathing pulse so short clips still read as motion
            pulse = 0.85 + 0.15 * math.sin(phase * math.tau)
            _apply_brightness(pixels, pulse)
        path = folder / f"frame-{index:03d}.png"
        save_png(path, size, size, bytes(pixels))
        frame_paths.append(str(path))

    svg_path = _write_animated_svg(folder / "animation.svg", frame_paths, size, fps)

    # APNG: a real animated file, built here with nothing but zlib. This is
    # what works when ffmpeg is not installed.
    apng_path = None
    try:
        raw_frames = []
        for index in range(frames):
            pixels = render(style, size, size, base_seed + index)
            raw_frames.append(bytes(pixels))
        apng_path = folder / "animation.png"
        apng_path.write_bytes(
            encode_apng(raw_frames, size, size, delay_ms=max(20, int(1000 / fps)))
        )
    except Exception as exc:
        log_warn(f"APNG encode failed: {exc}", "media")

    video: Dict[str, Any] = {"mp4": None, "gif": None}
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        mp4 = folder / "animation.mp4"
        code, _, err = run_command(
            [ffmpeg, "-y", "-framerate", str(fps), "-i",
             str(folder / "frame-%03d.png"),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(mp4)],
            timeout=180,
        )
        if code == 0 and mp4.exists():
            video["mp4"] = str(mp4)
        else:
            log_warn(f"ffmpeg mp4 failed: {truncate(err, 200)}", "media")

        gif = folder / "animation.gif"
        code, _, _ = run_command(
            [ffmpeg, "-y", "-framerate", str(fps), "-i",
             str(folder / "frame-%03d.png"), "-vf", "scale=iw:ih:flags=lanczos", str(gif)],
            timeout=180,
        )
        if code == 0 and gif.exists():
            video["gif"] = str(gif)

    return {
        "ok": True,
        "folder": str(folder),
        "frames": frames,
        "frame_size": size,
        "fps": fps,
        "animated_svg": str(svg_path),
        "animated_png": str(apng_path) if apng_path else None,
        "frame_sequence": str(folder / "frame-%03d.png"),
        **video,
        "render_seconds": round(time.perf_counter() - started, 2),
        "ffmpeg_available": bool(ffmpeg),
    }


def _apply_brightness(pixels: bytearray, factor: float) -> None:
    for index in range(0, len(pixels), 3):
        pixels[index] = min(255, int(pixels[index] * factor))
        pixels[index + 1] = min(255, int(pixels[index + 1] * factor))
        pixels[index + 2] = min(255, int(pixels[index + 2] * factor))


def _write_animated_svg(path: Path, frames: List[str], size: int, fps: int) -> Path:
    """SMIL animation that cycles base64 PNG frames. Pure SVG, no scripts."""
    import base64

    duration = len(frames) / max(1, fps)
    images = []
    for index, frame in enumerate(frames):
        encoded = base64.b64encode(Path(frame).read_bytes()).decode("ascii")
        images.append(
            f'<image x="0" y="0" width="{size}" height="{size}" '
            f'href="data:image/png;base64,{encoded}" '
            f'begin="{index / fps:.3f}s" dur="{duration:.3f}s" />'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<rect width="{size}" height="{size}" fill="#05080f" />' + "".join(images) + "</svg>"
    )
    path.write_text(svg, encoding="utf-8")
    return path


@tool("media.video", "Turn an animation into a video file",
      capabilities=["media.create", "files.write"], risk=0.30, tags=["media", "video"])
def media_video(prompt: str, style: str = "core", seconds: int = 4, size: int = 320, fps: int = 15) -> Dict[str, Any]:
    """
    Create a video.  Needs ffmpeg on the machine - the response says so
    clearly if it is missing rather than pretending to succeed.
    """
    ffmpeg = shutil.which("ffmpeg")
    frames = max(12, min(120, int(seconds) * int(fps)))
    clip = media_animation(prompt, style=style, frames=frames, size=size, fps=fps)
    if clip.get("mp4"):
        return {"ok": True, "video": clip["mp4"], "format": "mp4", "frames": frames, "fps": fps}
    return {
        "ok": False,
        "error": "ffmpeg is not installed, so MP4 could not be produced",
        "how_to_fix": "install ffmpeg (winget install ffmpeg, or choco install ffmpeg) and ask again",
        "delivered_anyway": {
            "animated_svg": clip.get("animated_svg"),
            "gif": clip.get("gif"),
            "frames": clip.get("folder"),
        },
    }


@tool("media.gallery", "List everything the agent has generated",
      capabilities=["files.read"], risk=0.10, tags=["media"])
def media_gallery(limit: int = 40) -> List[Dict[str, Any]]:
    folder = _exports()
    items: List[Dict[str, Any]] = []
    for item in sorted(folder.rglob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if not item.is_file():
            continue
        # .jpg must be here: real AI images come back as JPEG, and leaving
        # it out made the gallery silently empty for the best results.
        if item.suffix.lower() not in {".png", ".jpg", ".jpeg", ".svg",
                                       ".gif", ".apng", ".mp4", ".webp"}:
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        items.append(
            {
                "name": item.name,
                "path": str(item),
                "type": item.suffix.lstrip("."),
                "kb": round(stat.st_size / 1024, 1),
                "created": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
            }
        )
        if len(items) >= limit:
            break
    return items