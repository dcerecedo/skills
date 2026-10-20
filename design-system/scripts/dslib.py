"""Shared helpers for the ds-* skills: CSS value parsing, OKLab distance, WCAG contrast.

Standard library only, so the scripts run wherever python3 does.
"""
import math
import re

# ---------------------------------------------------------------- colors

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?"


def _channel(tok, scale):
    tok = tok.strip()
    if tok == "none":
        return 0.0
    if tok.endswith("%"):
        return float(tok[:-1]) / 100.0 * scale
    return float(tok)


def _args(body):
    body = body.replace(",", " ").replace("/", " / ")
    parts = body.split()
    alpha = 1.0
    if "/" in parts:
        i = parts.index("/")
        alpha = _channel(parts[i + 1], 1.0)
        parts = parts[:i]
    return parts, alpha


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _oklab_to_srgb(L, a, b):
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bb = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return _gam(r), _gam(g), _gam(bb)


def parse_color(s):
    """CSS color -> (r, g, b, a) with channels in 0..1, or None if not understood."""
    if s is None:
        return None
    s = str(s).strip().lower()
    if s in ("transparent",):
        return (0.0, 0.0, 0.0, 0.0)
    if s in ("canvas", "white"):
        return (1.0, 1.0, 1.0, 1.0)
    if s == "black":
        return (0.0, 0.0, 0.0, 1.0)
    m = re.fullmatch(r"#([0-9a-f]{3,8})", s)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8):
            return None
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (r, g, b, a)
    m = re.fullmatch(r"(rgba?|hsla?|oklch|oklab|color)\((.*)\)", s)
    if not m:
        return None
    fn, body = m.groups()
    try:
        if fn in ("rgb", "rgba"):
            parts, alpha = _args(body)
            if len(parts) == 4:
                alpha = _channel(parts[3], 1.0)
            r, g, b = (_channel(p, 255.0) / 255.0 for p in parts[:3])
            return (r, g, b, alpha)
        if fn in ("hsl", "hsla"):
            parts, alpha = _args(body)
            if len(parts) == 4:
                alpha = _channel(parts[3], 1.0)
            h = float(parts[0].replace("deg", "")) % 360
            sat, lig = _channel(parts[1], 1.0), _channel(parts[2], 1.0)
            if not parts[1].endswith("%"):
                sat /= 100.0
            if not parts[2].endswith("%"):
                lig /= 100.0
            c = (1 - abs(2 * lig - 1)) * sat
            x = c * (1 - abs((h / 60) % 2 - 1))
            mm = lig - c / 2
            r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
            return (r + mm, g + mm, b + mm, alpha)
        if fn == "oklab":
            parts, alpha = _args(body)
            L = _channel(parts[0], 1.0)
            a, b = _channel(parts[1], 0.4), _channel(parts[2], 0.4)
            return (*_oklab_to_srgb(L, a, b), alpha)
        if fn == "oklch":
            parts, alpha = _args(body)
            L = _channel(parts[0], 1.0)
            C = _channel(parts[1], 0.4)
            H = math.radians(float(parts[2].replace("deg", "")) if parts[2] != "none" else 0.0)
            return (*_oklab_to_srgb(L, C * math.cos(H), C * math.sin(H)), alpha)
        if fn == "color":
            parts, alpha = _args(body)
            if parts[0] != "srgb":
                return None
            r, g, b = (_channel(p, 1.0) for p in parts[1:4])
            return (r, g, b, alpha)
    except (ValueError, IndexError):
        return None
    return None


def composite(fg, bg):
    """Alpha-composite fg over an opaque bg."""
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


WHITE = (1.0, 1.0, 1.0, 1.0)


def to_oklab(c):
    r, g, b = (_lin(x) for x in c[:3])
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def delta_e(c1, c2, over=WHITE):
    """ΔE OK between two parsed colors, both composited over `over` first.

    Compositing alone would let a fully transparent token match the background it sits on,
    so a difference in alpha counts at least as much as the composited difference.
    """
    a, b = to_oklab(composite(c1, over)), to_oklab(composite(c2, over))
    return max(math.dist(a, b), abs(c1[3] - c2[3]))


def hex_of(c):
    c = composite(c, WHITE) if c[3] < 1 else c
    return "#" + "".join(f"{round(max(0, min(1, x)) * 255):02x}" for x in c[:3])


def luminance(c):
    r, g, b = (_lin(x) for x in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg):
    """WCAG 2.x contrast ratio; fg composited over bg, bg over white."""
    bgo = composite(bg, WHITE)
    fgo = composite(fg, bgo)
    l1, l2 = sorted((luminance(fgo), luminance(bgo)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


# ------------------------------------------------------------ dimensions

def px(v, root=16.0):
    """CSS length (or bare number) -> px float, or None."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower()
    m = re.fullmatch(rf"({_NUM})(px|rem|em)?", s)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    return n * root if unit in ("rem", "em") else n


def ms(v):
    s = str(v).strip().lower()
    m = re.fullmatch(rf"({_NUM})(ms|s)", s)
    if not m:
        return None
    n = float(m.group(1))
    return n * 1000 if m.group(2) == "s" else n


def family(v):
    first = str(v).split(",")[0].strip().strip("'\"").lower()
    return first


def norm(v):
    return re.sub(r"\s+", " ", str(v).strip().lower())


def oklch_to_srgb(L, C, H_deg, alpha=1.0):
    """OKLCH -> (r, g, b, a) in 0..1, clipped to sRGB. For building ramps."""
    h = math.radians(H_deg)
    return (*_oklab_to_srgb(L, C * math.cos(h), C * math.sin(h)), alpha)


def to_oklch(c):
    """Parsed color -> (L, C, H_deg), ignoring alpha."""
    L, a, b = to_oklab(c)
    return (L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360)


def font_stack(v):
    return [f.strip().strip("'\"").lower() for f in str(v).split(",") if f.strip()]


def _split_top(s, sep=","):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [x.strip() for x in out if x.strip()]


def parse_shadow(s):
    """CSS box-shadow -> list of layers {inset, x, y, blur, spread, color}, or None."""
    s = str(s).strip()
    if s.lower() in ("none", ""):
        return []
    layers = []
    for layer in _split_top(s):
        color, lengths, inset = None, [], False
        for tok in re.findall(r"[a-z-]+\([^)]*\)|#[0-9a-fA-F]+|[^\s]+", layer):
            if tok.lower() == "inset":
                inset = True
                continue
            p = px(tok)
            if p is not None:
                lengths.append(p)
                continue
            c = parse_color(tok)
            if c is None:
                return None
            color = c
        if len(lengths) < 2:
            return None
        lengths += [0.0] * (4 - len(lengths))
        layers.append({"inset": inset, "x": lengths[0], "y": lengths[1], "blur": lengths[2],
                       "spread": lengths[3], "color": color or (0.0, 0.0, 0.0, 1.0)})
    return layers


def shadow_distance(a, b):
    """(max px difference, max ΔE) between two parsed shadows; (inf, inf) if not comparable."""
    if a is None or b is None or len(a) != len(b):
        return math.inf, math.inf
    dpx, de = 0.0, 0.0
    for la, lb in zip(a, b):
        if la["inset"] != lb["inset"]:
            return math.inf, math.inf
        dpx = max(dpx, *(abs(la[k] - lb[k]) for k in ("x", "y", "blur", "spread")))
        de = max(de, delta_e(la["color"], lb["color"]))
    return dpx, de
