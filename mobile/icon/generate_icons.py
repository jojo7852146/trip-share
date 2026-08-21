# -*- coding: utf-8 -*-
"""生成旅行分享 App 图标：蓝色渐变圆角方块 + 白色纸飞机"""
import os
from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.abspath(__file__))

SIZES = {
    'mdpi': 48,
    'hdpi': 72,
    'xhdpi': 96,
    'xxhdpi': 144,
    'xxxhdpi': 192,
}

# 纸飞机(send icon)在 24x24 viewport 中的多边形，缩放到 512 画布
def send_polygon(scale=20, offset=16):
    pts = [
        (2.01, 21), (23, 12), (2.01, 3),
        (2, 10), (15, 12), (2, 14),
    ]
    return [(x * scale + offset, y * scale + offset) for x, y in pts]

def make_icon(size, rounded=True, radius_ratio=0.22):
    canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    # 垂直渐变背景
    grad = Image.new('RGB', (size, size))
    gd = grad.load()
    top = (78, 155, 235)     # 4E9AF1
    bottom = (27, 92, 200)   # 1B5CC8
    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(size):
            gd[x, y] = (r, g, b)

    mask = Image.new('L', (size, size), 0)
    md = ImageDraw.Draw(mask)
    if rounded:
        radius = int(size * radius_ratio)
        md.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    else:
        md.ellipse([0, 0, size - 1, size - 1], fill=255)

    icon = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    icon.paste(grad, (0, 0), mask)

    # 画白色纸飞机（按比例缩放到当前尺寸）
    s = size / 24.0 * 20 / 20  # 相对 viewport 缩放：size/24 每单位
    # 用与 512 相同的形状，按比例映射
    pts = send_polygon(scale=size / 24.0, offset=(size - 20 * size / 24.0) / 2)
    draw = ImageDraw.Draw(icon)
    draw.polygon(pts, fill=(255, 255, 255, 255))

    return icon

for d, sz in SIZES.items():
    outdir = os.path.join(BASE, d)
    os.makedirs(outdir, exist_ok=True)
    make_icon(sz, rounded=True).save(os.path.join(outdir, 'ic_launcher.png'))
    make_icon(sz, rounded=False).save(os.path.join(outdir, 'ic_launcher_round.png'))
    print(d, 'done')

# 额外生成一张 512 预览
make_icon(512, rounded=True).save(os.path.join(BASE, 'icon_preview.png'))
print('preview done')
