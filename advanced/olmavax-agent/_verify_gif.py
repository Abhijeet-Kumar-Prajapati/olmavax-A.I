"""
Round-trip check for the hand-written GIF encoder.

Pillow is not a dependency of this project, so instead of trusting the
encoder we decode its output with an independent LZW decoder and compare
the result against the frames that went in. If the encoder's code-size
growth or clear-code handling is wrong, this is what catches it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from olmavax_agent.tools.media_tools import encode_gif


def parse_gif(data):
    """Minimal GIF89a reader: returns (width, height, palette, [frame indices])."""
    if data[:6] != b"GIF89a":
        raise ValueError("not a GIF")
    w = int.from_bytes(data[6:8], "little")
    h = int.from_bytes(data[8:10], "little")
    packed = data[10]
    gct_size = 1 << ((packed & 0x07) + 1) if packed & 0x80 else 0
    pos = 13
    palette = []
    for _ in range(gct_size):
        palette.append(tuple(data[pos:pos + 3]))
        pos += 3

    frames = []
    while pos < len(data):
        block = data[pos]
        if block == 0x3B:                     # trailer
            break
        if block == 0x21:                     # extension
            label = data[pos + 1]
            pos += 2
            if label == 0xF9:                 # graphic control
                pos += 1                       # block size
                pos += 5                       # packed, delay, delay, trans, term
                continue
            while data[pos] != 0:              # skip sub-blocks
                pos += data[pos] + 1
            pos += 1
            continue
        if block == 0x2C:                     # image descriptor
            pos += 1
            left = int.from_bytes(data[pos:pos + 2], "little")
            top = int.from_bytes(data[pos + 2:pos + 4], "little")
            iw = int.from_bytes(data[pos + 4:pos + 6], "little")
            ih = int.from_bytes(data[pos + 6:pos + 8], "little")
            ipacked = data[pos + 8]
            pos += 9
            assert left == 0 and top == 0, "only full-frame offsets are used"
            assert iw == w and ih == h, "frame size must match the screen"
            if ipacked & 0x80:                 # local colour table
                pos += 3 * (1 << ((ipacked & 0x07) + 1))
            min_code = data[pos]
            pos += 1
            payload = bytearray()
            while data[pos] != 0:
                size = data[pos]
                payload += data[pos + 1:pos + 1 + size]
                pos += size + 1
            pos += 1
            frames.append(lzw_decode(bytes(payload), min_code, iw * ih))
            continue
        raise ValueError(f"unexpected block 0x{block:02x} at {pos}")
    return w, h, palette, frames


def lzw_decode(payload, min_code, expected):
    clear = 1 << min_code
    end = clear + 1

    table = {i: (i,) for i in range(clear)}
    size = min_code + 1
    out = []
    prev = None

    bitpos = 0
    total = len(payload) * 8

    def read():
        nonlocal bitpos
        if bitpos + size > total:
            return None
        value = 0
        for i in range(size):
            byte = payload[(bitpos + i) >> 3]
            bit = (byte >> ((bitpos + i) & 7)) & 1
            value |= bit << i
        bitpos += size
        return value

    while len(out) < expected:
        code = read()
        if code is None:
            break
        if code == clear:
            table = {i: (i,) for i in range(clear)}
            size = min_code + 1
            prev = None
            continue
        if code == end:
            break
        if code in table:
            entry = table[code]
        elif prev is not None:
            entry = prev + (prev[0],)
        else:
            raise ValueError("bad first code")
        out.extend(entry)
        if prev is not None:
            table[len(table) + end + 1] = prev + (entry[0],)
            if len(table) + end + 1 > (1 << size) - 1 and size < 12:
                size += 1
        prev = entry
    return out


def main() -> int:
    width = height = 48
    frames = []
    for t in range(6):
        px = bytearray()
        for y in range(height):
            for x in range(width):
                px += bytes(((x * 5 + t * 20) % 256,
                             (y * 5) % 256,
                             (t * 40 + y) % 256))
        frames.append(bytes(px))

    gif = encode_gif(frames, width, height, delay_ms=60)
    Path("test.gif").write_bytes(gif)
    w, h, palette, decoded = parse_gif(gif)

    assert (w, h) == (width, height), f"size {w}x{h}"
    assert len(decoded) == len(frames), f"{len(decoded)} frames, expected {len(frames)}"
    assert len(decoded[0]) == width * height, \
        f"frame 0 decoded {len(decoded[0])} pixels, expected {width * height}"

    # Quantisation is lossy by design, so compare with a tolerance rather
    # than exactly. A correct encoder lands within a few units per channel.
    worst = 0
    for original, indices in zip(frames, decoded):
        for i in range(width * height):
            base = i * 3
            pr, pg, pb = palette[indices[i]]
            worst = max(worst,
                        abs(original[base] - pr),
                        abs(original[base + 1] - pg),
                        abs(original[base + 2] - pb))
    print(f"frames decoded : {len(decoded)}")
    print(f"pixels/frame   : {len(decoded[0])}")
    print(f"palette        : {len(palette)} colours")
    print(f"worst error    : {worst} (per channel)")
    print(f"file size      : {len(gif)} bytes")
    ok = worst <= 40
    print("ROUND TRIP OK" if ok else f"ROUND TRIP FAILED (error {worst})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())