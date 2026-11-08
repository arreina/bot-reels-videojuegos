import sys, os, subprocess, math
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
F = "/usr/share/fonts/opentype/inter/"
def font(w, s): return ImageFont.truetype(F + f"Inter-{w}.otf", s)

BG = (14, 14, 18)
WHITE = (245, 245, 245)
GREY = (150, 150, 160)
RED = (230, 57, 70)
YEL = (255, 209, 102)
TEAL = (42, 157, 143)

def clamp(x, a=0, b=1): return max(a, min(b, x))
def ease(t): t = clamp(t); return 1 - (1 - t) ** 3
def prog(t, start, dur): return ease((t - start) / dur)

def text_c(d, y, s, f, fill, alpha=1.0, dy=0, img=None):
    """centered text with fade/slide; draws on RGBA overlay"""
    if alpha <= 0: return
    bbox = d.textbbox((0, 0), s, font=f)
    w = bbox[2] - bbox[0]
    x = (W - w) // 2 - bbox[0]
    c = fill + (int(255 * alpha),)
    d.text((x, y + dy), s, font=f, fill=c)

def lines_c(d, y, lines, f, fill, a, dy, gap=1.18):
    lh = int(f.size * gap)
    for i, l in enumerate(lines):
        text_c(d, y + i * lh, l, f, fill, a, dy)
    return y + len(lines) * lh

def source(d, s, a):
    text_c(d, 1560, s, font("Medium", 30), GREY, a)

_WM = None
def base():
    global _WM
    if _WM is None:
        import brand as _b
        _WM = _b.wordmark(34, stacked=False)
    im = Image.new("RGBA", (W, H), BG + (255,))
    im.alpha_composite(_WM, ((W - _WM.width) // 2, 200))
    return im

def tag(d, label, a):
    # small top label
    f = font("Bold", 34)
    text_c(d, 310, label, f, GREY, a)

# ---------- scenes ----------
def s1(t):  # hook, 3.5s
    im = base(); d = ImageDraw.Draw(im)
    a = prog(t, 0, 0.5); dy = int(40 * (1 - a))
    lines_c(d, 560, ["«Los inmigrantes", "vienen a vivir", "de las paguitas»"], font("Black", 96), WHITE, a, dy)
    # stamp
    p = prog(t, 2.0, 0.35)
    if p > 0:
        sc = 1.6 - 0.6 * p
        st = Image.new("RGBA", (620, 240), (0, 0, 0, 0)); sd = ImageDraw.Draw(st)
        sd.rounded_rectangle((10, 10, 610, 230), 24, outline=RED + (255,), width=14)
        f = font("Black", 150); b = sd.textbbox((0, 0), "BULO", font=f)
        sd.text(((620 - (b[2]-b[0])) // 2 - b[0], (240 - (b[3]-b[1])) // 2 - b[1]), "BULO", font=f, fill=RED + (255,))
        st = st.rotate(-8, expand=True, resample=Image.BICUBIC)
        st = st.resize((int(st.width * sc), int(st.height * sc)), Image.BICUBIC)
        alpha = st.split()[3].point(lambda v: int(v * p))
        st.putalpha(alpha)
        im.alpha_composite(st, ((W - st.width) // 2, 1000 - st.height // 2 + 120))
    a2 = prog(t, 3.3, 0.5)
    text_c(d, 1420, "Vamos a los datos ↓", font("Bold", 48), YEL, a2)
    return im

def s2(t):  # IMV split, 5s
    im = base(); d = ImageDraw.Draw(im)
    a = prog(t, 0, 0.5); dy = int(30 * (1 - a))
    tag(d, "INGRESO MÍNIMO VITAL", a)
    lines_c(d, 380, ["¿Quién lo cobra", "de verdad?"], font("Black", 88), WHITE, a, dy)
    # bars
    bx, bw, bh = 140, 800, 110
    for i, (lab, pct, col, y) in enumerate([("Españoles", 82, TEAL, 760), ("Extranjeros", 17, RED, 1040)]):
        pa = prog(t, 0.7 + i * 0.3, 1.2)
        la = prog(t, 0.6 + i * 0.3, 0.4)
        d.text((bx, y - 80), lab, font=font("Bold", 52), fill=WHITE + (int(255 * la),))
        d.rounded_rectangle((bx, y, bx + bw, y + bh), 18, fill=(40, 40, 48, int(255 * la)))
        if pa > 0:
            d.rounded_rectangle((bx, y, bx + max(36, int(bw * pct / 100 * pa)), y + bh), 18, fill=col + (255,))
        n = f"{int(round(pct * pa))}%"
        d.text((bx + bw - d.textlength(n, font=font("Black", 64)), y - 92), n, font=font("Black", 64), fill=WHITE + (int(255 * la),))
    a3 = prog(t, 3.2, 0.5)
    lines_c(d, 1260, ["8 de cada 10 titulares", "son españoles"], font("Bold", 58), YEL, a3, int(20 * (1 - a3)))
    source(d, "Fuente: Seguridad Social, ene–jun 2026 (vía Maldita.es)", prog(t, 0.5, 0.5))
    return im

def s3(t):  # irregular, 4.5s
    im = base(); d = ImageDraw.Draw(im)
    a = prog(t, 0, 0.5); dy = int(30 * (1 - a))
    tag(d, "¿Y LOS «SIN PAPELES»?", a)
    pa = prog(t, 0.4, 0.6)
    sc = 0.85 + 0.15 * pa
    f = font("Black", int(300 * sc))
    text_c(d, 560 + int(40 * (1 - pa)), "0 €", f, RED, pa)
    a2 = prog(t, 1.3, 0.5)
    lines_c(d, 960, ["de Ingreso Mínimo Vital"], font("Bold", 60), WHITE, a2, int(20 * (1 - a2)))
    a3 = prog(t, 2.8, 0.5)
    lines_c(d, 1130, ["Hace falta al menos 1 año", "de residencia LEGAL,", "efectiva y continuada"], font("Medium", 54), GREY, a3, int(20 * (1 - a3)))
    source(d, "Fuente: requisitos del IMV, Seguridad Social", prog(t, 0.5, 0.5))
    return im

def fmt(n): return f"{n:,}".replace(",", ".")

def s4(t):  # cotizantes, 4.5s
    im = base(); d = ImageDraw.Draw(im)
    a = prog(t, 0, 0.5); dy = int(30 * (1 - a))
    tag(d, "LO QUE NO TE CUENTAN", a)
    lines_c(d, 400, ["Trabajadores extranjeros", "cotizando a la", "Seguridad Social"], font("Bold", 64), WHITE, a, dy)
    p = prog(t, 1.5, 2.2)
    text_c(d, 780, fmt(int(3_550_000 * p)), font("Black", 150), YEL, prog(t, 0.5, 0.3))
    a3 = prog(t, 4.6, 0.5)
    lines_c(d, 1040, ["Récord histórico.", "Pagan tu sanidad,", "tus carreteras y", "las pensiones de hoy."], font("Bold", 62), WHITE, a3, int(20 * (1 - a3)))
    source(d, "Fuente: Ministerio de Inclusión, agosto 2026", prog(t, 0.5, 0.5))
    return im

def s5(t):  # OECD, 4.5s
    im = base(); d = ImageDraw.Draw(im)
    a = prog(t, 0, 0.5); dy = int(30 * (1 - a))
    tag(d, "SEGÚN LA OCDE", a)
    lines_c(d, 440, ["Los inmigrantes", "aportan más de lo", "que reciben en"], font("Black", 84), WHITE, a, dy)
    items = [("Sanidad", 0.7), ("Educación", 1.0), ("Protección social", 1.3)]
    for i, (s, st) in enumerate(items):
        p = prog(t, st, 0.4)
        y = 860 + i * 130
        d.ellipse((190, y + 10, 250, y + 70), fill=TEAL + (int(255 * p),))
        d.text((206, y + 4), "✓", font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 46), fill=BG + (int(255 * p),))
        d.text((290 + int(30 * (1 - p)), y), s, font=font("Bold", 64), fill=WHITE + (int(255 * p),))
    source(d, "Fuente: OCDE, 25 países, 2006–2018 (vía El Orden Mundial)", prog(t, 0.5, 0.5))
    return im

def s6(t):  # mensaje de cierre
    im = base(); d = ImageDraw.Draw(im)
    a = prog(t, 0, 0.6); dy = int(30 * (1 - a))
    lines_c(d, 520, ["El bulo no busca", "informarte."], font("Black", 92), WHITE, a, dy)
    a2 = prog(t, 1.2, 0.6)
    lines_c(d, 810, ["Busca que el de abajo", "culpe al de", "más abajo."], font("Black", 82), RED, a2, int(30 * (1 - a2)))
    a4 = prog(t, 3.0, 0.5)
    text_c(d, 1290, "Compártelo con quien lo necesite", font("Medium", 44), GREY, a4)
    return im

import brand
HANDLE = "@datoszurdos"
TAGLINE = "Con datos, no con bulos."

def paste_c(im, layer, y):
    im.alpha_composite(layer, ((W - layer.width) // 2, y))

SECTION = os.environ.get("DZ_SECTION", "BULOS vs. DATOS")
SECTION_COLOR = {"BULOS vs. DATOS": RED}.get(SECTION, TEAL)

def intro(t):  # 1.6s: logo + etiqueta de la sección del vídeo
    im = Image.new("RGBA", (W, H), BG + (255,))
    p = clamp(t / 1.4)
    lk = brand.lockup(120, p)
    paste_c(im, lk, 760)
    d = ImageDraw.Draw(im)
    a = prog(t, 1.3, 0.4)
    if a > 0:
        f = font("Black", 50)
        tw = d.textlength(SECTION, font=f)
        pw, ph = tw + 80, 96
        sc = 0.9 + 0.1 * a
        x0 = (W - pw * sc) / 2; y0 = 1110 + (1 - a) * 20
        d.rounded_rectangle((x0, y0, x0 + pw * sc, y0 + ph * sc), radius=int(ph * sc / 2), fill=SECTION_COLOR + (int(255 * a),))
        fs = font("Black", int(50 * sc))
        bb = d.textbbox((0, 0), SECTION, font=fs)
        d.text((x0 + (pw * sc - (bb[2] - bb[0])) / 2 - bb[0], y0 + (ph * sc - (bb[3] - bb[1])) / 2 - bb[1]), SECTION, font=fs, fill=WHITE + (int(255 * a),))
    return im

def outro(t):  # 4s
    im = Image.new("RGBA", (W, H), BG + (255,))
    p = clamp(t / 1.0)
    lk = brand.lockup(120, p)
    paste_c(im, lk, 560)
    d = ImageDraw.Draw(im)
    a = prog(t, 0.6, 0.5)
    text_c(d, 960, TAGLINE, font("Black", 64), YEL, a, int(20 * (1 - a)))
    a2 = prog(t, 1.2, 0.5)
    text_c(d, 1110, HANDLE, font("Bold", 60), WHITE, a2)
    a3 = prog(t, 1.6, 0.5)
    text_c(d, 1200, "Síguenos para más", font("Medium", 44), GREY, a3)
    return im

SCENES = [(intro, 3.0), (s1, 5.6), (s2, 8.2), (s3, 7.1), (s4, 7.7), (s5, 6.1), (s6, 4.6), (outro, 4.6)]

def render(i, out):
    fn, dur = SCENES[i]
    n = int(dur * FPS)
    tmp = out[:-4] + ".part.mp4"
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", tmp],
                         stdin=subprocess.PIPE)
    for k in range(n):
        t = k / FPS
        im = fn(t)
        # fade out last 0.3s
        fo = clamp((dur - t) / 0.3)
        if fo < 1:
            im = Image.blend(Image.new("RGBA", (W, H), BG + (255,)), im, fo)
        p.stdin.write(im.convert("RGB").tobytes())
    p.stdin.close()
    if p.wait() == 0: os.rename(tmp, out)

if __name__ == "__main__":
    mode = sys.argv[1]
    outdir = sys.argv[2]
    if mode == "preview":
        for i, (fn, dur) in enumerate(SCENES):
            fn(dur - 0.4).convert("RGB").save(f"{outdir}/p{i+1}.jpg", quality=85)
    else:
        i = int(mode)
        render(i, f"{outdir}/scene{i+1}.mp4")
