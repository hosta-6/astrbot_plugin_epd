#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小玖 · 墨水屏标准调色管线  (hosta 2026-10-25 定标)
=====================================================
参数面板（默认值 = 定标值）:
  亮度 0 / 对比度 0 / 伽马 1.00 / 饱和度 100
  暖色中心 30   暖色跨度 58   → 暖色区 = 色相 30°±58° = 332°~88°
  冷色抑制 25   冷色上限 60   冷色去饱和 25
  暖色吸引 12   暖色吸引上限 18
  锐化 30       抖动强度 85   FS 扩散 / 标准色域 / 自动色阶
核心原则: 只提亮本来就是暖色的部分，冷色区域保持干净的黑白。
"""
import argparse
import sys
import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont

import os as _os

_HERE = _os.path.dirname(_os.path.abspath(__file__))
sys.path.insert(0, _HERE)


def _find_font():
    """按顺序找一个能用的中文字体（可用 EPD_FONT 环境变量覆盖）。"""
    env = _os.environ.get("EPD_FONT")
    cands = [env] if env else []
    cands += [
        _os.path.join(_HERE, "..", "fonts", "wqy.ttc"),
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    for c in cands:
        if c and _os.path.exists(c):
            return c
    return ""


FONT = _find_font()
from epd_frame import make_canvas, pack, build_frame, W, H, BLACK, WHITE, YELLOW, RED

PAL = np.array([[0, 0, 0], [255, 255, 255], [255, 220, 0], [210, 0, 0]], dtype=np.float32)
# FONT 由 _find_font() 决定
IMG_W = 552
GAP = 12

DEFAULTS = dict(
    bright=0, contrast=0, gamma=1.00, satur=100,
    warm_center=30, warm_span=58,
    cool_suppress=25, cool_cap=60, cool_desat=25,
    warm_attract=12, warm_attract_cap=18,
    sharpen=30, dither=85, autolevel=True,
)


# ---------- 几何 ----------
def square_crop(path, size=IMG_W, focus=0.42):
    im = Image.open(path).convert("RGB")
    w0, h0 = im.size
    s = max(size / w0, size / h0)
    im = im.resize((max(size, round(w0 * s)), max(size, round(h0 * s))), Image.LANCZOS)
    nw, nh = im.size
    left = (nw - size) // 2
    top = max(0, min(nh - size, int((nh - size) * focus)))
    return im.crop((left, top, left + size, top + size))


# ---------- 基础调整 ----------
def auto_levels(im, clip=0.01):
    a = np.asarray(im, dtype=np.float32)
    out = a.copy()
    for c in range(3):
        ch = a[:, :, c].ravel()
        lo = np.percentile(ch, clip * 100)
        hi = np.percentile(ch, 100 - clip * 100)
        if hi - lo < 1:
            hi = lo + 1
        out[:, :, c] = (a[:, :, c] - lo) * 255.0 / (hi - lo)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def base_adjust(im, bright, contrast, gamma, satur):
    if bright or contrast or abs(gamma - 1) > 1e-3:
        lut = []
        for i in range(256):
            v = i + bright
            v = 128 + (v - 128) * (1 + contrast / 100.0)
            v = max(0.0, min(255.0, v))
            v = 255.0 * ((v / 255.0) ** gamma)
            lut.append(int(max(0, min(255, v))))
        im = im.point(lut * 3)
    if abs(satur - 100) > 1e-3:
        hsv = im.convert("HSV")
        Hc, Sc, Vc = hsv.split()
        k = satur / 100.0
        Sc = Sc.point(lambda v: int(max(0, min(255, v * k))))
        im = Image.merge("HSV", (Hc, Sc, Vc)).convert("RGB")
    return im


# ---------- 暖冷分离 ----------
def warm_cool(im, p):
    hsv = np.asarray(im.convert("HSV"), dtype=np.float32)
    Hc, Sc, Vc = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    hue = Hc / 255.0 * 360.0
    sat = Sc / 255.0
    val = Vc / 255.0

    c = p["warm_center"]
    d = p["warm_span"]
    delta = np.abs(((hue - c + 180) % 360) - 180)      # 色相到暖色中心的最短角距
    is_warm = (delta <= d) & (sat >= 0.08)             # 低饱和=近中性，不动
    is_cool = (~is_warm) & (sat >= 0.08)

    # 暖色：提亮（吸引 12%，绝对上限 +18%）
    boost = p["warm_attract"] / 100.0
    cap = p["warm_attract_cap"] / 100.0
    val_w = val.copy()
    val_w[is_warm] = np.minimum(val[is_warm] * (1 + boost), val[is_warm] + cap)
    # 暖色饱和度也略提，让黄红更实
    sat_w = sat.copy()
    sat_w[is_warm] = np.minimum(sat[is_warm] * (1 + boost * 0.6), 1.0)

    # 冷色：抑制饱和 + 上限 + 再去饱和 → 趋近干净黑白
    s_cool = sat.copy()
    s_cool[is_cool] = sat[is_cool] * (1 - p["cool_suppress"] / 100.0)
    s_cool = np.minimum(s_cool, p["cool_cap"] / 100.0)
    s_cool[is_cool] = s_cool[is_cool] * (1 - p["cool_desat"] / 100.0)

    out = np.dstack([Hc,
                     np.clip((sat_w if True else sat) * 255, 0, 255),
                     np.clip(val_w * 255, 0, 255)]).astype(np.uint8)
    # 用 s_cool 覆盖冷色区
    out[:, :, 1] = np.where(is_cool, np.clip(s_cool * 255, 0, 255), out[:, :, 1]).astype(np.uint8)

    return Image.fromarray(out, mode="HSV").convert("RGB")


# ---------- 量化 ----------
def quantize_fs(arr, strength=0.85):
    img = arr.astype(np.float32).copy()
    h, w, _ = img.shape
    out = np.zeros((h, w), dtype=np.uint8)
    for y in range(h):
        row = img[y]
        for x in range(w):
            old = row[x]
            idx = int(((PAL - old) ** 2).sum(1).argmin())
            out[y, x] = idx
            err = (old - PAL[idx]) * strength
            if x + 1 < w:
                row[x + 1] += err * 0.4375
            if y + 1 < h:
                nxt = img[y + 1]
                if x > 0:
                    nxt[x - 1] += err * 0.1875
                nxt[x] += err * 0.3125
                if x + 1 < w:
                    nxt[x + 1] += err * 0.0625
    return out


def process(path, p, focus=0.42, preview=None):
    im = square_crop(path, IMG_W, focus)
    if p["autolevel"]:
        im = auto_levels(im)
    im = base_adjust(im, p["bright"], p["contrast"], p["gamma"], p["satur"])
    im = warm_cool(im, p)
    if p["sharpen"] > 0:
        im = im.filter(ImageFilter.UnsharpMask(radius=2,
                                               percent=int(p["sharpen"] * 2.5),
                                               threshold=3))
    if preview:
        im.save(preview)
    return quantize_fs(np.asarray(im, dtype=np.float32), p["dither"] / 100.0)


def compose(idx, title, sub, foot):
    canvas = make_canvas(WHITE)
    photo = Image.fromarray(idx, mode="P")
    photo.putpalette([0, 0, 0, 255, 255, 255, 255, 220, 0, 210, 0, 0] + [0] * 756)
    canvas.paste(photo, (0, 0))

    d = ImageDraw.Draw(canvas)
    x0 = IMG_W + GAP
    d.line([(x0 - 4, 20), (x0 - 4, H - 20)], fill=BLACK, width=2)

    f_big = ImageFont.truetype(FONT, 84)
    f_mid = ImageFont.truetype(FONT, 30)
    f_sm = ImageFont.truetype(FONT, 20)

    y = 92
    for ch in title:
        bb = d.textbbox((0, 0), ch, font=f_big)
        d.text((x0 + 24 - bb[0], y), ch, font=f_big, fill=RED)
        y += 96
    d.text((x0 + 8, y + 6), sub, font=f_mid, fill=BLACK)
    d.line([(x0 + 6, y + 46), (W - 24, y + 46)], fill=BLACK, width=2)
    d.text((x0 + 6, H - 70), foot, font=f_sm, fill=BLACK)
    d.text((x0 + 6, H - 44), "MOINK", font=f_sm, fill=YELLOW)
    for (cx, cy) in [(W - 26, 18), (W - 26, H - 30)]:
        d.rectangle([cx, cy, cx + 12, cy + 12], fill=RED)
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default=os.path.join(_os.getcwd(), "frame.bin"))
    ap.add_argument("--preview", default=os.path.join(_os.getcwd(), "std_preview.png"))
    ap.add_argument("--photo-preview", default=os.path.join(_os.getcwd(), "std_photo.png"))
    ap.add_argument("--focus", type=float, default=0.42)
    ap.add_argument("--title", default="小玖")
    ap.add_argument("--sub", default="NINE")
    ap.add_argument("--foot", default="2026.10.25")
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=type(v) if not isinstance(v, bool) else str, default=v)
    a = ap.parse_args()

    p = dict(DEFAULTS)
    p.update(dict(bright=a.bright, contrast=a.contrast, gamma=a.gamma, satur=a.satur,
                  warm_center=a.warm_center, warm_span=a.warm_span,
                  cool_suppress=a.cool_suppress, cool_cap=a.cool_cap,
                  cool_desat=a.cool_desat, warm_attract=a.warm_attract,
                  warm_attract_cap=a.warm_attract_cap, sharpen=a.sharpen, dither=a.dither))

    idx = process(a.src, p, a.focus, a.photo_preview)
    canvas = compose(idx, a.title, a.sub, a.foot)
    canvas.save(a.preview)
    body = build_frame(pack(canvas), panel=1)
    open(a.out, "wb").write(body)

    hist = np.bincount(np.asarray(canvas, dtype=np.uint8).ravel(), minlength=4)
    names = ["黑", "白", "黄", "红"]
    print("帧大小:", len(body))
    print("配色:", "  ".join(f"{names[i]}={hist[i]/(W*H)*100:.1f}%" for i in range(4)))


if __name__ == "__main__":
    main()
