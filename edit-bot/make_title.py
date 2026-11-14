#!/usr/bin/env python3
"""Draw the white title box (Montserrat Black + Noto Color Emoji) on a transparent 1080x1920 PNG,
centred on the facecam/gameplay seam at y=608. Lines split with |.
  python3 -I make_title.py "“We can't fail now” 😭🥀" out.png
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter
HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "fonts", "Montserrat-Black.ttf")
EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"  # apt-get install fonts-noto-color-emoji


def is_emoji(ch):
    return ord(ch) >= 0x1F000 or 0x2600 <= ord(ch) <= 0x27BF or ord(ch) in (0xFE0F, 0x200D)


def main(text, out, seam=608):
    lines = text.split("|") if "|" in text else [text]
    size = 58 if len(lines) == 1 and len(text) <= 26 else 54
    F = ImageFont.truetype(FONT, size)
    E = ImageFont.truetype(EMOJI, 109)
    EH = size + 4

    def emoji(ch):
        im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((0, 0), ch, font=E, embedded_color=True)
        im = im.crop(im.getbbox())
        return im.resize((round(im.width * EH / im.height), EH), Image.LANCZOS)

    def runs(line):
        out, cur = [], ""
        for ch in line:
            if is_emoji(ch):
                if ch in ("️", "‍"):
                    continue
                if cur:
                    out.append((cur, "t")); cur = ""
                out.append((ch, "e"))
            else:
                cur += ch
        if cur:
            out.append((cur, "t"))
        return out

    L = [runs(l.strip()) for l in lines]
    width = lambda l: sum(F.getlength(s) if k == "t" else emoji(s).width + 6 for s, k in l)
    lh, pw, ph = size + 18, 36, 24
    W = int(max(width(l) for l in L)) + 2 * pw
    H = lh * len(L) + 2 * ph
    c = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    x0, y0 = (1080 - W) // 2, seam - H // 2
    sh = Image.new("RGBA", c.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0, y0 + 6, x0 + W, y0 + H + 6], 20, fill=(0, 0, 0, 90))
    c = Image.alpha_composite(c, sh.filter(ImageFilter.GaussianBlur(9)))
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([x0, y0, x0 + W, y0 + H], 20, fill=(255, 255, 255, 255))
    for i, l in enumerate(L):
        x, y = (1080 - width(l)) / 2, y0 + ph + i * lh
        for s, k in l:
            if k == "t":
                d.text((x, y + lh / 2), s, font=F, fill=(0, 0, 0, 255), anchor="lm"); x += F.getlength(s)
            else:
                em = emoji(s); c.alpha_composite(em, (int(x), int(y + (lh - EH) / 2))); d = ImageDraw.Draw(c); x += em.width + 6
    c.save(out)
    if W > 1040:
        print("warning: title wider than the frame; split it with |", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
