"""Datos Zurdos — identidad visual."""
from PIL import Image, ImageDraw, ImageFont

F = "/usr/share/fonts/opentype/inter/"
def font(w, s): return ImageFont.truetype(F + f"Inter-{w}.otf", s)

BG = (14, 14, 18)
WHITE = (245, 245, 245)
GREY = (150, 150, 160)
RED = (230, 57, 70)
YEL = (255, 209, 102)
TEAL = (42, 157, 143)

SKEW = 0.18  # inclinación hacia la izquierda (zurda)

def clamp(x, a=0, b=1): return max(a, min(b, x))
def ease(t): t = clamp(t); return 1 - (1 - t) ** 3

def backslant(layer, k=SKEW):
    """inclina una capa hacia la izquierda (la parte de arriba se va a la izquierda)"""
    w, h = layer.size
    pad = int(h * k)
    big = Image.new("RGBA", (w + pad, h), (0, 0, 0, 0))
    big.paste(layer, (0, 0))
    # x_src = x_dst + k*(y) - pad ... top shifts left
    return big.transform(big.size, Image.AFFINE, (1, -k, 0, 0, 1, 0), resample=Image.BICUBIC)

def icon(size, p=1.0, bg=None):
    """tres barras de mayor a menor, de izquierda a derecha: los datos que tiran a la izquierda"""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0) if bg is None else bg + (255,))
    d = ImageDraw.Draw(im)
    s = size / 100
    base = 82 * s
    bars = [(14, 70, RED), (40, 50, RED), (66, 30, YEL)]
    bw = 22 * s
    for i, (x, h, col) in enumerate(bars):
        q = ease((p * 1.6) - i * 0.25)
        if q <= 0: continue
        top = base - h * s * q
        d.rounded_rectangle((x * s, top, x * s + bw, base), radius=int(5 * s), fill=col + (255,))
    # línea base
    lp = ease(p * 2)
    d.rounded_rectangle((10 * s, base + 4 * s, 10 * s + 80 * s * lp, base + 9 * s), radius=int(2.5 * s), fill=WHITE + (255,))
    return im

def wordmark(height, p=1.0, stacked=True):
    """DATOS (blanco) / ZURDOS (rojo), inclinado a la izquierda"""
    f = font("Black", height)
    w1 = f.getlength("DATOS"); w2 = f.getlength("ZURDOS")
    if stacked:
        W = int(max(w1, w2) + height * 0.4); H = int(height * 2.15)
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
        a1 = int(255 * ease(p * 2)); a2 = int(255 * ease(p * 2 - 0.6))
        d.text((int(height * 0.3), -int(height * 0.12)), "DATOS", font=f, fill=WHITE + (a1,))
        d.text((int(height * 0.3 - height * 1.05 * SKEW), int(height * 0.95)), "ZURDOS", font=f, fill=RED + (a2,))
    else:
        W = int(w1 + w2 + height * 0.7); H = int(height * 1.25)
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
        d.text((int(height * 0.3), -int(height * 0.12)), "DATOS", font=f, fill=WHITE + (int(255 * ease(p * 2)),))
        d.text((int(height * 0.3 + w1 + height * 0.25), -int(height * 0.12)), "ZURDOS", font=f, fill=RED + (int(255 * ease(p * 2 - 0.6)),))
    return backslant(lay)

def lockup(height, p=1.0):
    """icono + wordmark apilado"""
    ic = icon(int(height * 2.2), p)
    wm = wordmark(height, p)
    W = ic.width + wm.width + int(height * 0.1)
    H = max(ic.height, wm.height)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(ic, (0, (H - ic.height) // 2))
    out.alpha_composite(wm, (ic.width + int(height * 0.1), (H - wm.height) // 2 + int(height * 0.05)))
    return out

if __name__ == "__main__":
    import sys
    out = sys.argv[1]
    # foto de perfil
    pf = Image.new("RGBA", (1080, 1080), BG + (255,))
    ic = icon(620); pf.alpha_composite(ic, ((1080 - 620) // 2, 150))
    wm = wordmark(110, stacked=False);
    pf.alpha_composite(wm, ((1080 - wm.width) // 2, 820))
    pf.convert("RGB").save(f"{out}/datos_zurdos_perfil.png")
    # logo horizontal transparente
    lk = lockup(160)
    lk.save(f"{out}/datos_zurdos_logo.png")
    # logo sobre fondo, para revisar
    prev = Image.new("RGBA", (lk.width + 120, lk.height + 120), BG + (255,))
    prev.alpha_composite(lk, (60, 60)); prev.convert("RGB").save(f"{out}/logo_preview.jpg", quality=90)
