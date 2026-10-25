#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MoInk 帧生成器 —— 小玖专用
把一张 768x552 的四色图打包成设备认识的 /api/frame 载荷。

协议要点（docs/CONTRACT.md）：
  body = 16B 头 + 2bpp 载荷(105984B)
  头：0xA5 0x5A | ver=1 | panel(0=A0,1=A1) | W(be) | H(be) | len(be) | crc16(be) | 0x0000
  2bpp：每字节 4 像素，MSB 优先，像素 x 在位 (6 - 2*(x%4))
  色码：00=黑 01=白 10=黄 11=红
  几何：缓冲 = 逻辑图旋转 180°
"""
import struct
import argparse
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 768, 552
PAYLOAD_LEN = W // 4 * H          # 105984

# 色码（CONTRACT §2）
BLACK, WHITE, YELLOW, RED = 0, 1, 2, 3

# FONT 由 _find_font() 决定


def crc16_ccitt_false(data: bytes) -> int:
    """poly 0x1021, init 0xFFFF, 无反射, 无终异或。'123456789' -> 0x29B1"""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def make_canvas(bg=WHITE):
    """建一张 768x552 的四色索引图（P 模式，调色板下标即色码）"""
    img = Image.new("P", (W, H), bg)
    pal = [0, 0, 0,        # 0 黑
           255, 255, 255,  # 1 白
           255, 220, 0,    # 2 黄
           210, 0, 0]      # 3 红
    img.putpalette(pal + [0] * (768 - len(pal)))
    return img


def pack(img) -> bytes:
    """逻辑图 -> 2bpp 载荷（内部自动 180° 旋转）"""
    rot = img.transpose(Image.ROTATE_180)
    px = rot.load()
    out = bytearray(PAYLOAD_LEN)
    i = 0
    for y in range(H):
        for x in range(0, W, 4):
            out[i] = (px[x, y] << 6) | (px[x + 1, y] << 4) | \
                     (px[x + 2, y] << 2) | px[x + 3, y]
            i += 1
    return bytes(out)


def build_frame(payload: bytes, panel: int = 1) -> bytes:
    crc = crc16_ccitt_false(payload)
    hdr = struct.pack(">BBBBHHIHH",
                      0xA5, 0x5A,      # 魔数
                      1,               # 格式版本 1 = 768x552
                      panel,           # 0=A0 1=A1（仅信息性）
                      W, H,
                      len(payload),
                      crc,
                      0)
    assert len(hdr) == 16, len(hdr)
    return hdr + payload


def draw_test(page_ver="R1.2.0"):
    """自检图：校色块 + 方向基准 + 大字"""
    img = make_canvas(WHITE)
    d = ImageDraw.Draw(img)
    f_big = ImageFont.truetype(FONT, 210)
    f_mid = ImageFont.truetype(FONT, 46)
    f_sm = ImageFont.truetype(FONT, 30)

    # 外框
    d.rectangle([6, 6, W - 7, H - 7], outline=BLACK, width=4)

    # 四角色块（校色 + 方向提示）
    box = 92
    d.rectangle([24, 24, 24 + box, 24 + box], fill=BLACK)
    d.rectangle([W - 24 - box, 24, W - 24, 24 + box], fill=RED)
    d.rectangle([24, H - 24 - box, 24 + box, H - 24], fill=YELLOW)
    d.rectangle([W - 24 - box, H - 24 - box, W - 24, H - 24], fill=BLACK)
    d.text((24 + box + 16, 44), "左 上", font=f_sm, fill=BLACK)
    d.text((W - 24 - box - 120, 44), "右 上", font=f_sm, fill=BLACK)

    # 中间大字
    t = "小 玖"
    bb = d.textbbox((0, 0), t, font=f_big)
    d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], 130), t, font=f_big, fill=RED)

    # 副标题
    sub = "墨水屏已接入喵"
    bb = d.textbbox((0, 0), sub, font=f_mid)
    d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], 380), sub, font=f_mid, fill=BLACK)

    # 底部小字
    tiny = f"MoInk {page_ver} · A1 · 768x552 · 4c"
    d.text((30, H - 24 - 40), tiny, font=f_sm, fill=BLACK)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default=None, help="自定义大字（不给就用自检图）")
    ap.add_argument("--panel", type=int, default=1, help="0=A0 1=A1")
    ap.add_argument("--out", default=os.path.join(_os.getcwd(), "frame.bin"))
    a = ap.parse_args()

    assert crc16_ccitt_false(b"123456789") == 0x29B1, "CRC 自检失败！"

    img = draw_test() if not a.text else None
    if a.text:
        img = make_canvas(WHITE)
        d = ImageDraw.Draw(img)
        f = ImageFont.truetype(FONT, 120)
        bb = d.textbbox((0, 0), a.text, font=f)
        d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], (H - (bb[3] - bb[1])) / 2 - bb[1]),
               a.text, font=f, fill=BLACK)

    payload = pack(img)
    frame = build_frame(payload, a.panel)
    with open(a.out, "wb") as f:
        f.write(frame)

    crc = crc16_ccitt_false(payload)
    print(f"载荷长度 : {len(payload)} (期望 {PAYLOAD_LEN})")
    print(f"CRC16    : 0x{crc:04X}")
    print(f"整帧长度 : {len(frame)} (期望 {16 + PAYLOAD_LEN})")
    print(f"面板     : {'A1' if a.panel else 'A0'}")
    print(f"输出     : {a.out}")

    # 同目录留一张 PNG 方便肉眼对照
    png = a.out.rsplit(".", 1)[0] + ".png"
    img.save(png)
    print(f"预览图   : {png}")


if __name__ == "__main__":
    main()
