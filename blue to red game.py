import math
import random
import sys
import pygame

W, H = 1280, 720
FPS = 60

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BLUE = (36, 110, 230)
CYAN = (70, 210, 240)
ORANGE = (240, 130, 50)
RED = (225, 70, 60)
GREEN = (60, 190, 110)
YELLOW = (250, 205, 70)
GRAY = (140, 150, 170)
INK = (35, 45, 80)
PAPER = (251, 252, 254)

R_GAS = 8.314
P_MARS = 0.00636
T_MARS = 210.0
REQ_CH4 = 6978.0
REQ_O2 = 22728.0
O2_RATIO = REQ_O2 / REQ_CH4
SOXE_KWH = 9.0
SOLAR_PEAK = 60.0
SOLAR_CF = 0.35
NUCLEAR_KW = 40.0
STORM_FACTOR = 0.10
BUDGET = 20000.0
CREW = 4
CREW_L_DAY = 3.8
WATER_RECOVERY = 0.98
LOOP_DAYS = 30
NASA_RATE_KG_H = 0.61
TRANSIT_DAYS = 203
H2_COST = 0.5
OPS_COST = 12.0
TANK_FACTOR = 1.5
ICE_WATER = 3000.0

SITES = {
    "polar": dict(name="NORTH MID-LATITUDE (about 45 N)", short="ice-rich mid-latitudes", solar=0.65, ice=True, storm=0.30, safety=0.93),
    "equator": dict(name="EQUATORIAL PLAINS", short="equatorial plains", solar=1.0, ice=False, storm=0.55, safety=0.97),
}
VEHICLES = {
    "light": dict(name="LIGHT", limit=12000.0, cost=3000.0),
    "medium": dict(name="MEDIUM", limit=20000.0, cost=4500.0),
    "heavy": dict(name="HEAVY", limit=30000.0, cost=6500.0),
}
REACTORS = {
    "photo": dict(name="Photocatalytic reactor", power="solar field", cost=2000.0, mass=5500.0, base=0.88),
    "pbr": dict(name="Packed-Bed Reactor (PBR)", power="fission power unit", cost=7000.0, mass=8500.0, base=0.93),
}


def clamp(v, a, b):
    return max(a, min(b, v))


def lerp(a, b, t):
    return a + (b - a) * t


def mixc(c1, c2, t):
    t = clamp(t, 0.0, 1.0)
    return (int(lerp(c1[0], c2[0], t)), int(lerp(c1[1], c2[1], t)), int(lerp(c1[2], c2[2], t)))


def keq(T):
    return math.exp((164900.0 - 172.7 * T) / (R_GAS * T))


def fractions(X, r):
    ntot = 1.0 + r - 2.0 * X
    return (1.0 - X) / ntot, (r - 4.0 * X) / ntot, X / ntot, 2.0 * X / ntot


def sabatier_rate(T, pco2, ph2, pch4, ph2o):
    k = 0.12 * math.exp(-80000.0 / R_GAS * (1.0 / T - 1.0 / 623.0))
    q = (pch4 * ph2o ** 2) / max(pco2 * ph2 ** 4, 1e-30)
    drive = max(0.0, 1.0 - q / keq(T))
    return k * max(pco2, 0.0) ** 0.3 * max(ph2, 0.0) ** 0.7 / (1.0 + 0.35 * ph2o) ** 2 * drive


def x_equilibrium(T, P, r):
    lo, hi = 0.0, min(0.9999, r / 4.0 * 0.9999)
    for _ in range(50):
        X = 0.5 * (lo + hi)
        yc, yh, ym, yw = fractions(X, r)
        q = (ym * yw ** 2) / (max(yc, 1e-12) * max(yh, 1e-12) ** 4) / P ** 2
        if q < keq(T):
            lo = X
        else:
            hi = X
    return 0.5 * (lo + hi)


def pbr_profile(T, P, r, wcat, steps=240):
    dw = wcat / steps
    X = 0.0
    p = P
    xmax = min(0.9999, r / 4.0 * 0.9999)
    for _ in range(steps):
        yc, yh, ym, yw = fractions(X, r)
        rr = sabatier_rate(T, yc * p, max(yh, 0.0) * p, ym * p, yw * p)
        X = min(X + rr * dw, xmax)
        p = max(p - 0.012 * dw * (4.0 / max(p, 0.5)), 0.6 * P)
    return X, p


def avg_power(reactor, site):
    if reactor == "photo":
        return SOLAR_PEAK * SOLAR_CF * site["solar"]
    return NUCLEAR_KW


def default_cfg(reactor, site):
    avg = avg_power(reactor, site)
    if reactor == "pbr":
        return dict(reactor="pbr", T=620.0, P=4.0, r=4.2, w=10.0, fe=0.7, power=min(20.0, avg))
    return dict(reactor="photo", T=520.0, P=4.0, r=4.2, w=1.0, fe=0.7, power=min(15.0, avg))


MW = {"CO2": 44.01, "H2": 2.016, "CH4": 16.04, "H2O": 18.015, "O2": 32.0}


def simulate(cfg, site):
    reactor = cfg["reactor"]
    T, P, r, w, fe, power = cfg["T"], cfg["P"], cfg["r"], cfg["w"], cfg["fe"], cfg["power"]
    xeq = x_equilibrium(T, P, r)
    if reactor == "pbr":
        X, pout = pbr_profile(T, P, r, w)
        light = 0.0
    else:
        eff = 0.72 * (1.0 - math.exp(-1.6 * w))
        X = xeq * eff
        pout = P - 0.05
    X = clamp(X, 0.02, 0.999)
    if reactor == "photo":
        light = 140.0 * w / X
    comp = R_GAS * T_MARS * math.log(P / P_MARS) / 0.35 / 1000.0
    nin = (1.0 + r) / X
    cp = (37.0 + 29.0 * r) / X
    heat = max(0.0, 0.22 * cp * (T - 330.0) / 1000.0)
    blower = 2.0 * max(0.0, nin - 5.0)
    el = 880.0 * fe
    ice = 69.0 if site["ice"] else 0.0
    total = comp + heat + blower + el + light + ice
    F = power / total
    k = F * 3600.0
    cpout = (1.0 / X - 1.0) * 37.0 + (r / X - 4.0) * 29.0 + 36.0 + 68.0
    cool = F * (88.0 + 0.22 * cpout * max(T - 290.0, 0.0) / 1000.0)
    rec_co2 = 1.0 / X - 1.0
    rec_h2 = r / X - 4.0
    raw = [
        ("CO2_FEED", T_MARS, P_MARS, {"CO2": 1.0}),
        ("CO2_COMP", 330.0, P, {"CO2": 1.0}),
        ("H2_EARTH", 288.0, P, {"H2": 4.0 - 1.9 * fe}),
        ("H2_RECYC", 340.0, P, {"H2": 1.9 * fe}),
        ("R_FEED", T, P, {"CO2": 1.0 / X, "H2": r / X}),
        ("R_OUT", T, pout, {"CO2": rec_co2, "H2": rec_h2, "CH4": 1.0, "H2O": 2.0}),
        ("GAS_RCY", 300.0, pout - 0.05, {"CO2": rec_co2, "H2": rec_h2}),
        ("CH4_OUT", 290.0, pout - 0.05, {"CH4": 1.0}),
        ("WATER", 290.0, pout - 0.05, {"H2O": 2.0}),
        ("O2_OUT", 330.0, 1.0, {"O2": fe}),
        ("CREW_H2O", 290.0, 1.0, {"H2O": 2.0 * (1.0 - fe)}),
    ]
    streams = []
    for name, ts, ps, comp_d in raw:
        mol = {c: v * k for c, v in comp_d.items()}
        tot = sum(mol.values())
        kg = sum(v * MW[c] for c, v in mol.items()) / 1000.0
        streams.append(dict(name=name, T=ts, P=ps, mol=tot, kg=kg, x={c: (v / tot if tot > 1e-12 else 0.0) for c, v in mol.items()}))
    h2_kg = max(0.05, (4.0 - 1.9 * fe) * 2.016 / 16.04 - (0.10 if site["ice"] else 0.0))
    return dict(
        X=X, xeq=xeq, pout=pout, dP=P - pout, F=F,
        e_kwh_kg=total / 16.04 / 3.6,
        ch4_kg_h=F * 3600.0 * 0.01604,
        h2_kg_per_kg=h2_kg,
        o2_kg_per_kg=1.995 * fe,
        duties=dict(comp=F * comp, heat=F * heat, blower=F * blower, el=F * el, light=F * light, cool=cool),
        streams=streams,
    )


def crew_water_need(days):
    return CREW * CREW_L_DAY * LOOP_DAYS + CREW * CREW_L_DAY * (1.0 - WATER_RECOVERY) * days


def mission_eval(g, storm=None):
    cfg, res, plan = g.cfg, g.sim, g.plan
    site, rea, veh = SITES[g.site], REACTORS[g.reactor], VEHICLES[plan["vehicle"]]
    days = plan["days"]
    avg = avg_power(g.reactor, site)
    o2_water = 1.995 * cfg["fe"]
    short = max(0.0, O2_RATIO - o2_water)
    e_total = res["e_kwh_kg"] + SOXE_KWH * short
    h2_per_kg = res["h2_kg_per_kg"]
    h2_cap = plan["h2"] * 0.97 / h2_per_kg
    cum = 0.0
    prod = 0.0
    daily = []
    for d in range(days):
        f = 1.0
        if storm and g.reactor == "photo" and storm[0] <= d < storm[0] + storm[1]:
            f = STORM_FACTOR
        cum += min(cfg["power"], avg * f) * 24.0
        prod = min(cum / e_total, plan["target"], h2_cap)
        daily.append(prod)
    e_avail = min(cfg["power"], avg) * 24.0 * days
    nominal = min(e_avail / e_total, plan["target"], h2_cap)
    mass = rea["mass"] + TANK_FACTOR * plan["h2"]
    cost = veh["cost"] + rea["cost"] + H2_COST * plan["h2"] + OPS_COST * days
    water_made = 2.25 * prod
    crew_water = (1.0 - cfg["fe"]) * water_made + (ICE_WATER if site["ice"] else 0.0)
    crew_need = crew_water_need(days)
    crew_ok = crew_water >= crew_need
    storm_hit = bool(storm) and g.reactor == "photo"
    rel = rea["base"] * site["safety"]
    if plan["target"] < REQ_CH4 * 1.03:
        rel *= 0.88
    if storm_hit:
        rel *= 0.95
    e_used = prod * e_total
    e_prop = e_used / max(prod * (1.0 + O2_RATIO), 1e-6)
    success = prod >= REQ_CH4 - 1e-6 and crew_ok
    pts = dict(
        fuel=40.0 * min(1.0, prod / REQ_CH4),
        eff=20.0 * clamp(1.0 - (e_prop - 5.0) / 6.0, 0.0, 1.0),
        cost=15.0 * clamp((BUDGET - cost) / (0.5 * BUDGET), 0.0, 1.0),
        mass=10.0 * clamp((veh["limit"] - mass) / (0.3 * veh["limit"]), 0.0, 1.0),
        rel=15.0 * rel,
    )
    total = sum(pts.values()) * (1.0 if success else 0.6)
    limit = "energy"
    if prod >= plan["target"] - 1e-6:
        limit = "target"
    elif prod >= h2_cap - 1e-6:
        limit = "hydrogen"
    return dict(
        e_total=e_total, e_need=plan["target"] * e_total, e_avail=e_avail, e_used=e_used, e_prop=e_prop,
        h2_need=plan["target"] * h2_per_kg / 0.97, h2_have=plan["h2"], h2_cap=h2_cap,
        mass=mass, mass_limit=veh["limit"], cost=cost, prod=prod, o2=prod * O2_RATIO, nominal=nominal,
        daily=daily, crew_ok=crew_ok, crew_water=crew_water, crew_need=crew_need, rel=rel, pts=pts, score=total,
        success=success, limit=limit, storm=storm, days=days,
    )


def nf(v):
    return "{:,.0f}".format(v)


_fonts = {}


def fnt(size, bold=False):
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont("segoeui,arial,helvetica,dejavusans", size, bold=bold)
    return _fonts[key]


def txt(surf, s, pos, size=20, color=WHITE, bold=False, anchor="topleft"):
    img = fnt(size, bold).render(s, True, color)
    rect = img.get_rect()
    setattr(rect, anchor, (int(pos[0]), int(pos[1])))
    surf.blit(img, rect)
    return rect


_wraps = {}


def wrap(s, size, width, bold=False):
    key = (s, size, width, bold)
    if key in _wraps:
        return _wraps[key]
    f = fnt(size, bold)
    out = []
    for part in s.split("\n"):
        cur = ""
        for word in part.split(" "):
            t = (cur + " " + word).strip()
            if f.size(t)[0] <= width or not cur:
                cur = t
            else:
                out.append(cur)
                cur = word
        out.append(cur)
    _wraps[key] = out
    return out


def para(surf, s, pos, size, color, width, bold=False, gap=5):
    y = pos[1]
    for line in wrap(s, size, width, bold):
        txt(surf, line, (pos[0], y), size, color, bold)
        y += size + gap
    return y


def vgrad(surf, rect, c1, c2, bands=60):
    rect = pygame.Rect(rect)
    h = rect.h / bands
    for i in range(bands):
        y0 = int(rect.y + i * h)
        y1 = int(rect.y + (i + 1) * h) + 1
        pygame.draw.rect(surf, mixc(c1, c2, i / (bands - 1)), (rect.x, y0, rect.w, y1 - y0))


def rrect(surf, rect, fill, border=None, radius=10, width=2):
    pygame.draw.rect(surf, fill, rect, border_radius=radius)
    if border is not None:
        pygame.draw.rect(surf, border, rect, width, border_radius=radius)


def glass(surf, rect, color, alpha, radius=8):
    rect = pygame.Rect(rect)
    s = pygame.Surface((max(1, rect.w), max(1, rect.h)), pygame.SRCALPHA)
    pygame.draw.rect(s, tuple(color) + (int(alpha),), (0, 0, rect.w, rect.h), border_radius=radius)
    surf.blit(s, (rect.x, rect.y))


def glow(surf, pos, radius, color, alpha=60):
    radius = max(2, int(radius))
    s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    for i in range(5):
        rr = max(1, int(radius * (1 - i * 0.18)))
        pygame.draw.circle(s, tuple(color) + (int(alpha * (i + 1) / 5),), (radius, radius), rr)
    surf.blit(s, (int(pos[0]) - radius, int(pos[1]) - radius))


def arrow_head(surf, p0, p1, color, size=9):
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    a = (p1[0] - size * math.cos(ang - 0.45), p1[1] - size * math.sin(ang - 0.45))
    b = (p1[0] - size * math.cos(ang + 0.45), p1[1] - size * math.sin(ang + 0.45))
    pygame.draw.polygon(surf, color, [p1, a, b])


def dashed(surf, color, p0, p1, dash=6, width=2):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    dist = math.hypot(dx, dy)
    if dist < 1:
        return
    n = int(dist / dash)
    for i in range(0, n, 2):
        a = (p0[0] + dx * i / n, p0[1] + dy * i / n)
        b = (p0[0] + dx * min(i + 1, n) / n, p0[1] + dy * min(i + 1, n) / n)
        pygame.draw.line(surf, color, a, b, width)


def poly_len(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))


def poly_point(pts, d):
    for i in range(len(pts) - 1):
        seg = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if d <= seg or i == len(pts) - 2:
            u = clamp(d / seg, 0.0, 1.0) if seg > 0 else 0.0
            return (lerp(pts[i][0], pts[i + 1][0], u), lerp(pts[i][1], pts[i + 1][1], u))
        d -= seg
    return pts[-1]


rng = random.Random(7)
STARS = [(rng.randint(0, W), rng.randint(0, H), rng.choice((1, 1, 2, 2, 3)), rng.random() * 6.28) for _ in range(170)]
PELLETS = [(rng.random(), rng.random(), rng.random()) for _ in range(80)]
CRATERS = [(rng.uniform(-0.8, 0.8), rng.uniform(-0.8, 0.8), rng.uniform(0.04, 0.1)) for _ in range(22)]


def draw_stars(surf, t, brightness=1.0):
    for x, y, s, ph in STARS:
        b = (0.55 + 0.45 * math.sin(t * 1.5 + ph)) * clamp(brightness, 0.0, 1.0)
        c = int(clamp(60 + 195 * b, 0, 255))
        pygame.draw.circle(surf, (c, c, min(255, c + 15)), (x, y), s)


class Button:
    def __init__(self, rect, label, color=BLUE, size=22, enabled=True):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.color = color
        self.size = size
        self.enabled = enabled

    def draw(self, surf):
        hover = self.enabled and self.rect.collidepoint(pygame.mouse.get_pos())
        col = self.color if self.enabled else (66, 74, 96)
        if hover:
            col = mixc(col, WHITE, 0.22)
        rrect(surf, self.rect, col, mixc(col, WHITE, 0.45), 12)
        txt(surf, self.label, self.rect.center, self.size, WHITE if self.enabled else (150, 156, 172), True, "center")

    def hit(self, ev):
        return ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.enabled and self.rect.collidepoint(ev.pos)


class Slider:
    def __init__(self, x, y, w, label, lo, hi, val, step, fmt, dark=True, hint="", mark=None):
        self.x, self.y, self.w = x, y, w
        self.label, self.lo, self.hi, self.val, self.step = label, lo, hi, clamp(val, lo, hi), step
        self.fmt = fmt
        self.dark = dark
        self.hint = hint
        self.mark = mark
        self.drag = False

    def set_from(self, mx):
        t = clamp((mx - self.x) / self.w, 0.0, 1.0)
        v = self.lo + t * (self.hi - self.lo)
        v = round(v / self.step) * self.step
        self.val = clamp(v, self.lo, self.hi)

    def handle(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            area = pygame.Rect(self.x - 8, self.y + 14, self.w + 16, 30)
            if area.collidepoint(ev.pos):
                self.drag = True
                self.set_from(ev.pos[0])
                return True
        elif ev.type == pygame.MOUSEMOTION and self.drag:
            self.set_from(ev.pos[0])
            return True
        elif ev.type == pygame.MOUSEBUTTONUP:
            self.drag = False
        return False

    def draw(self, surf):
        fg = WHITE if self.dark else INK
        sub = (170, 190, 230) if self.dark else (70, 80, 112)
        txt(surf, self.label, (self.x, self.y), 15, sub, True)
        txt(surf, self.fmt(self.val), (self.x + self.w, self.y), 15, fg, True, "topright")
        t = (self.val - self.lo) / (self.hi - self.lo)
        rrect(surf, (self.x, self.y + 24, self.w, 8), (60, 70, 100) if self.dark else (190, 198, 216), None, 4)
        rrect(surf, (self.x, self.y + 24, max(2, int(self.w * t)), 8), CYAN if self.dark else BLUE, None, 4)
        if self.mark is not None:
            mx = int(self.x + self.w * (self.mark - self.lo) / (self.hi - self.lo))
            pygame.draw.line(surf, YELLOW, (mx, self.y + 18), (mx, self.y + 38), 3)
            txt(surf, "NASA limit", (mx, self.y + 40), 12, YELLOW, True, "midtop")
        pygame.draw.circle(surf, WHITE, (int(self.x + self.w * t), self.y + 28), 10)
        pygame.draw.circle(surf, BLUE, (int(self.x + self.w * t), self.y + 28), 10, 3)
        if self.hint:
            txt(surf, self.hint, (self.x, self.y + (56 if self.mark is not None else 40)), 12, (150, 165, 200) if self.dark else (95, 105, 135))


def draw_engineer(surf, x, y, s, talking, t):
    skin = (238, 190, 152)
    body = pygame.Rect(0, 0, int(112 * s), int(120 * s))
    body.midbottom = (int(x), int(y))
    pygame.draw.rect(surf, (32, 90, 190), body, border_top_left_radius=int(42 * s), border_top_right_radius=int(42 * s))
    pygame.draw.polygon(surf, WHITE, [(x - 16 * s, body.top), (x + 16 * s, body.top), (x, body.top + 26 * s)])
    pygame.draw.circle(surf, WHITE, (int(x - 30 * s), int(body.top + 42 * s)), int(11 * s))
    pygame.draw.circle(surf, (225, 55, 55), (int(x - 27 * s), int(body.top + 45 * s)), int(4 * s))
    pygame.draw.rect(surf, skin, (int(x - 10 * s), int(body.top - 14 * s), int(20 * s), int(22 * s)))
    head = (int(x), int(body.top - 36 * s))
    pygame.draw.circle(surf, (58, 40, 30), (head[0], head[1] - int(4 * s)), int(40 * s))
    pygame.draw.circle(surf, skin, (head[0], head[1] + int(3 * s)), int(36 * s))
    pygame.draw.ellipse(surf, (58, 40, 30), (head[0] - int(38 * s), head[1] - int(42 * s), int(76 * s), int(30 * s)))
    for dx in (-13, 13):
        pygame.draw.circle(surf, WHITE, (head[0] + int(dx * s), head[1] - int(2 * s)), int(6 * s))
        pygame.draw.circle(surf, (30, 40, 60), (head[0] + int(dx * s), head[1] - int(2 * s)), int(3 * s))
    pygame.draw.arc(surf, (25, 28, 40), (head[0] - int(42 * s), head[1] - int(46 * s), int(84 * s), int(84 * s)), 0.2, 2.94, max(2, int(5 * s)))
    for dx in (-41, 41):
        pygame.draw.circle(surf, (25, 28, 40), (head[0] + int(dx * s), head[1] + int(2 * s)), int(9 * s))
    pygame.draw.line(surf, (25, 28, 40), (head[0] - int(41 * s), head[1] + int(8 * s)), (head[0] - int(14 * s), head[1] + int(24 * s)), max(2, int(3 * s)))
    if talking and math.sin(t * 14) > 0:
        pygame.draw.ellipse(surf, (120, 40, 40), (head[0] - int(8 * s), head[1] + int(14 * s), int(16 * s), int(11 * s)))
    else:
        pygame.draw.line(surf, (120, 50, 50), (head[0] - int(8 * s), head[1] + int(19 * s)), (head[0] + int(8 * s), head[1] + int(19 * s)), max(2, int(3 * s)))


class Talk:
    def __init__(self, lines):
        self.lines = lines
        self.i = 0
        self.n = 0.0

    def update(self, dt):
        self.n += dt * 55

    def typing(self):
        return int(self.n) < len(self.lines[self.i])

    def click(self):
        if self.typing():
            self.n = len(self.lines[self.i])
        elif self.i < len(self.lines) - 1:
            self.i += 1
            self.n = 0.0

    def finished(self):
        return self.i == len(self.lines) - 1 and not self.typing()

    def draw(self, surf, rect, t):
        rrect(surf, rect, (12, 20, 44), CYAN, 14, 2)
        txt(surf, "ENGINEER", (rect.x + 18, rect.y + 10), 17, CYAN, True)
        left = int(self.n)
        y = rect.y + 38
        for ln in wrap(self.lines[self.i], 21, rect.w - 36):
            if left <= 0:
                break
            txt(surf, ln[:left], (rect.x + 18, y), 21, WHITE)
            left -= len(ln) + 1
            y += 26
        if not self.typing() and not self.finished() and int(t * 2) % 2 == 0:
            txt(surf, "click to continue >", (rect.right - 16, rect.bottom - 14), 15, (150, 190, 255), False, "bottomright")


def draw_traj(surf, rect, prog, t):
    rect = pygame.Rect(rect)
    rrect(surf, rect, (5, 9, 22), CYAN, 10, 2)
    cx, cy = rect.centerx, rect.centery + 6
    k = rect.w / 340.0
    re, rm = 78 * k, 118 * k
    pygame.draw.circle(surf, (60, 90, 140), (cx, cy), int(re), 1)
    pygame.draw.circle(surf, (130, 80, 64), (cx, cy), int(rm), 1)
    glow(surf, (cx, cy), 34 * k, YELLOW, 70)
    pygame.draw.circle(surf, YELLOW, (cx, cy), int(12 * k))
    a = (re + rm) / 2
    e = (rm - re) / (rm + re)
    pts = []
    for i in range(61):
        th = math.pi * i / 60
        rr = a * (1 - e * e) / (1 + e * math.cos(th))
        pts.append((cx + rr * math.cos(th), cy - rr * math.sin(th)))
    cut = int(prog * 60)
    for i in range(0, 60, 2):
        pygame.draw.line(surf, (255, 255, 255) if i < cut else (80, 170, 230), pts[i], pts[i + 1], 2)
    ex, ey = cx + re, cy
    mx, my = cx - rm, cy
    glow(surf, (ex, ey), 20 * k, BLUE, 90)
    pygame.draw.circle(surf, (50, 130, 255), (int(ex), int(ey)), int(9 * k))
    pygame.draw.circle(surf, (90, 200, 110), (int(ex - 3 * k), int(ey - 2 * k)), int(4 * k))
    pygame.draw.circle(surf, (210, 100, 60), (int(mx), int(my)), int(7 * k))
    txt(surf, "EARTH", (ex, ey + 16 * k), max(11, int(14 * k)), (150, 200, 255), True, "midtop")
    txt(surf, "MARS", (mx, my + 14 * k), max(11, int(14 * k)), (240, 150, 110), True, "midtop")
    idx = clamp(prog * 60, 0, 59.999)
    i0 = int(idx)
    u = idx - i0
    sx = lerp(pts[i0][0], pts[i0 + 1][0], u)
    sy = lerp(pts[i0][1], pts[i0 + 1][1], u)
    glow(surf, (sx, sy), 14 * k, WHITE, 100)
    pygame.draw.circle(surf, WHITE, (int(sx), int(sy)), max(3, int(5 * k)))
    txt(surf, "TRANSFER ORBIT", (rect.centerx, rect.y + 10), max(12, int(15 * k)), CYAN, True, "midtop")
    txt(surf, "NASA Mars 2020: %d days, 293 million miles" % TRANSIT_DAYS, (rect.centerx, rect.bottom - 12), max(11, int(13 * k)), (170, 190, 230), False, "midbottom")


def draw_rocket(surf, x, y, s, flame, t):
    x, y = int(x), int(y)
    bw, bh = int(36 * s), int(150 * s)
    if flame > 0:
        ln = (70 + 30 * math.sin(t * 40)) * s * flame
        pygame.draw.polygon(surf, (255, 140, 40), [(x - 14 * s, y), (x + 14 * s, y), (x, y + ln)])
        pygame.draw.polygon(surf, (255, 235, 140), [(x - 7 * s, y), (x + 7 * s, y), (x, y + ln * 0.6)])
        glow(surf, (x, y + 20 * s), 60 * s * flame, (255, 170, 60), 70)
    pygame.draw.polygon(surf, (210, 50, 50), [(x - bw // 2, y - 40 * s), (x - bw // 2 - 20 * s, y), (x - bw // 2, y - 6 * s)])
    pygame.draw.polygon(surf, (210, 50, 50), [(x + bw // 2, y - 40 * s), (x + bw // 2 + 20 * s, y), (x + bw // 2, y - 6 * s)])
    pygame.draw.rect(surf, (235, 238, 245), (x - bw // 2, y - bh, bw, bh), border_radius=int(6 * s))
    pygame.draw.rect(surf, (200, 205, 220), (x + bw // 4, y - bh, bw // 4, bh), border_radius=int(6 * s))
    pygame.draw.polygon(surf, (210, 50, 50), [(x - bw // 2, y - bh), (x + bw // 2, y - bh), (x, y - bh - 52 * s)])
    pygame.draw.rect(surf, (30, 60, 140), (x - bw // 2, y - bh + 40 * s, bw, 14 * s))
    pygame.draw.circle(surf, (120, 190, 255), (x, int(y - bh + 90 * s)), int(9 * s))
    pygame.draw.circle(surf, WHITE, (x, int(y - bh + 90 * s)), int(9 * s), 2)


def draw_pbr(surf, cx, cy, s, t):
    bw, bh = int(110 * s), int(250 * s)
    body = pygame.Rect(0, 0, bw, bh)
    body.center = (int(cx), int(cy))
    for dx in (8, bw - 22):
        pygame.draw.rect(surf, (80, 88, 106), (body.left + int(dx * s), body.bottom, int(14 * s), int(44 * s)))
    pygame.draw.rect(surf, (60, 66, 82), (body.left - int(10 * s), body.bottom + int(40 * s), bw + int(20 * s), int(10 * s)))
    pipe_in = pygame.Rect(body.left - int(95 * s), body.bottom - int(70 * s), int(95 * s), int(16 * s))
    pipe_out = pygame.Rect(body.right, body.top + int(36 * s), int(95 * s), int(16 * s))
    for p in (pipe_in, pipe_out):
        pygame.draw.rect(surf, (128, 138, 158), p)
        pygame.draw.rect(surf, (80, 90, 110), p, 2)
    pygame.draw.rect(surf, (90, 98, 118), (pipe_in.left, pipe_in.y - int(5 * s), int(10 * s), int(26 * s)))
    pygame.draw.rect(surf, (90, 98, 118), (pipe_out.right - int(10 * s), pipe_out.y - int(5 * s), int(10 * s), int(26 * s)))
    pygame.draw.ellipse(surf, (112, 122, 142), (body.left, body.bottom - int(22 * s), bw, int(44 * s)))
    pygame.draw.rect(surf, (150, 160, 178), body)
    pygame.draw.rect(surf, (198, 208, 224), (body.left, body.top, int(bw * 0.22), bh))
    pygame.draw.rect(surf, (104, 114, 134), (body.right - int(bw * 0.22), body.top, int(bw * 0.22), bh))
    pygame.draw.ellipse(surf, (184, 194, 212), (body.left, body.top - int(22 * s), bw, int(44 * s)))
    pygame.draw.ellipse(surf, (90, 98, 118), (body.left, body.top - int(22 * s), bw, int(44 * s)), 2)
    for fr in (0.14, 0.86):
        yy = body.top + int(bh * fr)
        pygame.draw.line(surf, (88, 96, 116), (body.left, yy), (body.right, yy), 3)
    win = pygame.Rect(0, 0, int(bw * 0.62), int(bh * 0.5))
    win.center = body.center
    pygame.draw.rect(surf, (24, 22, 30), win, border_radius=6)
    for a, b, c in PELLETS:
        px = win.left + 6 + int(a * (win.w - 12))
        py = win.top + 6 + int(b * (win.h - 12))
        pr = max(2, int((3 + 3 * c) * s))
        pygame.draw.circle(surf, mixc((200, 150, 60), (230, 110, 50), c), (px, py), pr)
        pygame.draw.circle(surf, (250, 220, 150), (px - 1, py - 1), max(1, pr // 3))
    glass(surf, win, (255, 90, 30), 40 + 30 * math.sin(t * 2.2), 6)
    pygame.draw.rect(surf, (235, 238, 245), win, 3, border_radius=6)
    gc = (body.left + int(20 * s), body.top + int(34 * s))
    pygame.draw.circle(surf, WHITE, gc, int(10 * s))
    pygame.draw.circle(surf, (60, 66, 82), gc, int(10 * s), 2)
    pygame.draw.line(surf, RED, gc, (gc[0] + int(6 * s * math.cos(t)), gc[1] - int(6 * s)), 2)
    inlet = (pipe_in.left, pipe_in.centery)
    outlet = (pipe_out.right, pipe_out.centery)
    return pygame.Rect(body.left - int(95 * s), body.top - int(30 * s), bw + int(190 * s), bh + int(90 * s)), inlet, outlet


def draw_photo(surf, cx, cy, s, t):
    cw, ch = int(280 * s), int(150 * s)
    box = pygame.Rect(0, 0, cw, ch)
    box.center = (int(cx), int(cy))
    for p in (pygame.Rect(box.left - int(62 * s), box.centery - int(8 * s), int(62 * s), int(16 * s)),
              pygame.Rect(box.right, box.centery - int(8 * s), int(62 * s), int(16 * s))):
        pygame.draw.rect(surf, (128, 138, 158), p)
        pygame.draw.rect(surf, (80, 90, 110), p, 2)
    for i in range(6):
        x = box.left + int(cw * (i + 0.5) / 6)
        c = mixc(YELLOW, WHITE, 0.5 + 0.5 * math.sin(t * 3 + i))
        pygame.draw.line(surf, c, (x - int(24 * s), box.top - int(120 * s)), (x, box.top + int(6 * s)), max(2, int(3 * s)))
        arrow_head(surf, (x - int(24 * s), box.top - int(120 * s)), (x, box.top + int(4 * s)), c, int(10 * s))
    sun = (box.left - int(20 * s), box.top - int(120 * s))
    glow(surf, sun, 50 * s, YELLOW, 90)
    pygame.draw.circle(surf, (255, 230, 120), sun, int(26 * s))
    rrect(surf, box, (70, 82, 106), (186, 196, 216), int(14 * s), 3)
    glass(surf, (box.x + int(10 * s), box.y + int(8 * s), cw - int(20 * s), int(28 * s)), (120, 180, 240), 150, 6)
    plate = pygame.Rect(box.x + int(18 * s), box.y + int(48 * s), cw - int(36 * s), int(80 * s))
    pygame.draw.rect(surf, (28, 32, 44), plate, border_radius=6)
    pygame.draw.rect(surf, (150, 160, 180), plate, 2, border_radius=6)
    cols, rows = 11, 3
    for i in range(cols):
        for j in range(rows):
            px = plate.x + int(plate.w * (i + 1) / (cols + 1))
            py = plate.y + int(plate.h * (j + 1) / (rows + 1))
            c = mixc((70, 55, 30), (255, 200, 70), 0.5 + 0.5 * math.sin(t * 3 + i * 0.7 + j))
            pygame.draw.circle(surf, c, (px, py), max(3, int(6 * s)))
            pygame.draw.circle(surf, (10, 10, 14), (px, py), max(3, int(6 * s)), 1)
    inlet = (box.left - int(62 * s), box.centery)
    outlet = (box.right + int(62 * s), box.centery)
    return pygame.Rect(box.left - int(62 * s), box.top - int(40 * s), cw + int(124 * s), ch + int(60 * s)), inlet, outlet


def draw_astronaut(surf, x, y, s, accent, t, walk=0.0):
    x, y = int(x), int(y)
    sw = math.sin(t * 6) * walk
    pygame.draw.rect(surf, (150, 156, 170), (x - int(34 * s), y - int(100 * s), int(16 * s), int(50 * s)), border_radius=int(5 * s))
    for dx, sgn in ((-11, 1), (3, -1)):
        pygame.draw.rect(surf, (225, 228, 238), (x + int(dx * s), y - int(42 * s), int(16 * s), int(34 * s) + int(sw * sgn * 4 * s)), border_radius=int(5 * s))
        pygame.draw.rect(surf, (90, 96, 112), (x + int(dx * s) - int(2 * s), y - int(10 * s) + int(sw * sgn * 4 * s), int(20 * s), int(10 * s)), border_radius=int(4 * s))
    pygame.draw.rect(surf, (240, 242, 248), (x - int(24 * s), y - int(104 * s), int(48 * s), int(66 * s)), border_radius=int(12 * s))
    pygame.draw.rect(surf, accent, (x - int(14 * s), y - int(86 * s), int(28 * s), int(16 * s)), border_radius=int(3 * s))
    pygame.draw.circle(surf, (225, 55, 55), (x + int(14 * s), y - int(96 * s)), int(4 * s))
    for dx in (-33, 22):
        pygame.draw.rect(surf, (225, 228, 238), (x + int(dx * s), y - int(100 * s), int(11 * s), int(44 * s) ), border_radius=int(5 * s))
        pygame.draw.rect(surf, accent, (x + int(dx * s), y - int(90 * s), int(11 * s), int(6 * s)))
    pygame.draw.circle(surf, (245, 246, 250), (x, y - int(122 * s)), int(25 * s))
    pygame.draw.ellipse(surf, (232, 170, 50), (x - int(17 * s), y - int(132 * s), int(34 * s), int(24 * s)))
    pygame.draw.ellipse(surf, (255, 225, 140), (x - int(12 * s), y - int(129 * s), int(12 * s), int(8 * s)))
    pygame.draw.circle(surf, (170, 176, 190), (x, y - int(122 * s)), int(25 * s), 2)


def draw_co2_unit(surf, cx, base, s, t):
    w, h = int(170 * s), int(190 * s)
    body = pygame.Rect(int(cx) - w // 2, int(base) - h, w, h)
    for i in range(3):
        yy = body.y + int((24 + i * 22) * s)
        c = mixc((255, 215, 130), WHITE, 0.5 + 0.5 * math.sin(t * 3 + i))
        pygame.draw.line(surf, c, (body.x - int(120 * s), yy), (body.x - int(8 * s), yy), 3)
        arrow_head(surf, (body.x - int(120 * s), yy), (body.x - int(8 * s), yy), c, 9)
    rrect(surf, body, (122, 132, 152), (60, 68, 88), 8, 3)
    pygame.draw.rect(surf, (172, 182, 200), (body.x + int(6 * s), body.y + int(6 * s), int(w * 0.2), h - int(12 * s)), border_radius=4)
    pygame.draw.polygon(surf, (90, 98, 118), [(body.x, body.y + int(8 * s)), (body.x - int(26 * s), body.y + int(4 * s)), (body.x - int(26 * s), body.y + int(92 * s)), (body.x, body.y + int(88 * s))])
    fil = pygame.Rect(body.x + int(14 * s), body.y + int(14 * s), int(18 * s), int(72 * s))
    pygame.draw.rect(surf, (40, 46, 60), fil)
    for i in range(1, 8):
        pygame.draw.line(surf, (120, 130, 150), (fil.x, fil.y + int(i * 9 * s)), (fil.right, fil.y + int(i * 9 * s)), 1)
    fc = (body.centerx - int(8 * s), body.y + int(132 * s))
    pygame.draw.circle(surf, (50, 56, 72), fc, int(32 * s))
    for k in range(3):
        a = t * 5 + k * 2.094
        pygame.draw.line(surf, (200, 210, 225), fc, (fc[0] + int(28 * s * math.cos(a)), fc[1] + int(28 * s * math.sin(a))), max(2, int(5 * s)))
    pygame.draw.circle(surf, (230, 235, 245), fc, int(32 * s), 2)
    for i in range(2):
        cyl = pygame.Rect(body.right - int((70 - i * 34) * s), body.y + int(30 * s), int(26 * s), int(110 * s))
        pygame.draw.rect(surf, (205, 214, 228), cyl)
        pygame.draw.rect(surf, (235, 130, 60), (cyl.x, cyl.y + int(40 * s), cyl.w, int(30 * s)))
        pygame.draw.ellipse(surf, (225, 232, 242), (cyl.x, cyl.y - int(6 * s), cyl.w, int(12 * s)))
        pygame.draw.rect(surf, (80, 90, 110), cyl, 2)
    for i in range(3):
        pygame.draw.circle(surf, GREEN if (int(t * 2) + i) % 3 else YELLOW, (body.right - int((18) * s), body.y + int((20 + i * 14) * s)), max(2, int(4 * s)))
    stub = pygame.Rect(body.right, body.bottom - int(66 * s), int(24 * s), int(14 * s))
    pygame.draw.rect(surf, (128, 138, 158), stub)
    pygame.draw.rect(surf, (80, 90, 110), stub, 2)
    txt(surf, "Martian air", (body.x - int(66 * s), body.y - int(12 * s)), 13, (255, 225, 160), True, "midbottom")
    return (stub.right, stub.centery)


def draw_nuclear(surf, cx, base, s, t):
    cx, base = int(cx), int(base)
    for sgn in (-1, 1):
        for i in range(3):
            y0 = base - int((20 + i * 26) * s)
            pts = [(cx + sgn * int(14 * s), y0), (cx + sgn * int(70 * s), y0 - int(6 * s)), (cx + sgn * int(70 * s), y0 - int(22 * s)), (cx + sgn * int(14 * s), y0 - int(18 * s))]
            pygame.draw.polygon(surf, (190, 120, 90), pts)
            pygame.draw.polygon(surf, (110, 70, 56), pts, 2)
    pygame.draw.rect(surf, (96, 104, 122), (cx - int(14 * s), base - int(120 * s), int(28 * s), int(120 * s)))
    pygame.draw.polygon(surf, (150, 160, 180), [(cx, base - int(160 * s)), (cx + int(22 * s), base - int(120 * s)), (cx - int(22 * s), base - int(120 * s))])
    pygame.draw.circle(surf, YELLOW, (cx, base - int(70 * s)), int(11 * s))
    pygame.draw.circle(surf, BLACK, (cx, base - int(70 * s)), int(11 * s), 2)
    glow(surf, (cx, base - int(70 * s)), 26 * s, (255, 220, 80), 50 + 30 * math.sin(t * 3))


def draw_solar_field(surf, cx, base, s):
    for i in range(3):
        x0 = int(cx) - int(110 * s) + i * int(76 * s)
        pts = [(x0, int(base)), (x0 + int(70 * s), int(base)), (x0 + int(88 * s), int(base) - int(56 * s)), (x0 + int(18 * s), int(base) - int(56 * s))]
        pygame.draw.polygon(surf, (40, 80, 170), pts)
        pygame.draw.polygon(surf, (190, 205, 240), pts, 2)
        pygame.draw.line(surf, (150, 170, 220), (x0 + int(35 * s), int(base)), (x0 + int(53 * s), int(base) - int(56 * s)), 1)
        pygame.draw.line(surf, (90, 98, 118), (x0 + int(35 * s), int(base)), (x0 + int(35 * s), int(base) + int(14 * s)), 4)


def draw_tank(surf, cx, cy, r, color, label):
    cx, cy, r = int(cx), int(cy), int(r)
    for dx in (-0.55, 0.55):
        pygame.draw.line(surf, (70, 78, 98), (cx + int(dx * r), cy + int(r * 0.8)), (cx + int(dx * r * 1.2), cy + r + 44), 6)
    pygame.draw.circle(surf, color, (cx, cy), r)
    pygame.draw.circle(surf, mixc(color, WHITE, 0.55), (cx - r // 3, cy - r // 3), r // 3)
    pygame.draw.line(surf, mixc(color, BLACK, 0.4), (cx - r, cy), (cx + r, cy), 3)
    pygame.draw.circle(surf, mixc(color, BLACK, 0.45), (cx, cy), r, 3)
    txt(surf, label, (cx, cy + r // 3), 18, WHITE, True, "center")


def draw_vessel(surf, cx, cy, hw, hh, t):
    body = pygame.Rect(int(cx) - hw, int(cy) - hh, hw * 2, hh * 2)
    pygame.draw.ellipse(surf, (150, 160, 178), (body.x, body.bottom - 14, body.w, 28))
    pygame.draw.rect(surf, (188, 198, 214), body)
    pygame.draw.rect(surf, (110, 160, 235), (body.x, body.y + int(hh * 1.3), body.w, int(hh * 0.7)))
    pygame.draw.rect(surf, (222, 230, 242), (body.x + 4, body.y, hw // 2, body.h))
    pygame.draw.ellipse(surf, (210, 218, 232), (body.x, body.y - 14, body.w, 28))
    pygame.draw.ellipse(surf, (90, 98, 118), (body.x, body.y - 14, body.w, 28), 2)
    pygame.draw.rect(surf, (90, 98, 118), body, 2)
    for i in range(3):
        u = (t * 0.5 + i / 3) % 1.0
        pygame.draw.circle(surf, (240, 245, 255), (body.x + 10 + i * 10, int(body.bottom - 10 - u * hh * 1.6)), 3, 1)


def draw_electro(surf, cx, cy, w, h, t):
    r = pygame.Rect(int(cx) - w // 2, int(cy) - h // 2, w, h)
    rrect(surf, r, (150, 160, 180), (70, 78, 98), 6, 3)
    for i in range(4):
        x = r.x + 16 + i * (w - 32) // 3
        pygame.draw.line(surf, (60, 66, 84), (x, r.y + 8), (x, r.bottom - 8), 4)
        pygame.draw.circle(surf, (190, 225, 255), (x + 8, int(r.bottom - 8 - ((t * 0.6 + i * 0.25) % 1.0) * (h - 16))), 3, 1)
    txt(surf, "+ -", (r.centerx, r.bottom + 2), 13, WHITE, True, "midtop")


def callout(surf, title, sub, pos):
    w = max(fnt(14, True).size(title)[0], fnt(12).size(sub)[0] if sub else 0) + 20
    r = pygame.Rect(0, 0, w, 40 if sub else 24)
    r.center = (int(pos[0]), int(pos[1]))
    rrect(surf, r, (12, 20, 44), CYAN, 8, 2)
    txt(surf, title, (r.centerx, r.y + 4), 14, WHITE, True, "midtop")
    if sub:
        txt(surf, sub, (r.centerx, r.y + 22), 12, (170, 200, 240), False, "midtop")


def draw_pipe(surf, pts, color, t, flow=True):
    pygame.draw.lines(surf, (66, 74, 94), False, pts, 12)
    pygame.draw.lines(surf, color, False, pts, 8)
    if flow:
        total = max(1.0, poly_len(pts))
        n = max(1, int(total / 30))
        for i in range(n):
            p = poly_point(pts, (i * 30 + t * 60) % total)
            pygame.draw.circle(surf, WHITE, (int(p[0]), int(p[1])), 3)


def atom(surf, p, r, color, label=None):
    p = (int(p[0]), int(p[1]))
    r = int(r)
    pygame.draw.circle(surf, color, p, r)
    pygame.draw.circle(surf, mixc(color, WHITE, 0.55), (p[0] - r // 3, p[1] - r // 3), max(1, r // 3))
    pygame.draw.circle(surf, mixc(color, BLACK, 0.4), p, r, 1)
    if label:
        txt(surf, label, p, max(10, int(r * 1.1)), WHITE, True, "center")


CARBON = (70, 72, 84)
OXY = (225, 60, 60)
HYD = (235, 238, 248)


def draw_reaction(surf, rect, t):
    rect = pygame.Rect(rect)
    rrect(surf, rect, (8, 12, 28), CYAN, 12, 2)
    txt(surf, "SABATIER REACTION", (rect.centerx, rect.y + 10), 17, CYAN, True, "midtop")
    ox, oy = rect.x, rect.y

    def w(i):
        return 3 * math.sin(t * 2.6 + i)

    c = (ox + 95, oy + 115)
    pygame.draw.line(surf, GRAY, (c[0] - 30, c[1] + w(0)), (c[0] + 30, c[1] + w(0)), 3)
    atom(surf, (c[0] - 30, c[1] + w(0)), 12, OXY)
    atom(surf, (c[0] + 30, c[1] + w(0)), 12, OXY)
    atom(surf, (c[0], c[1] + w(0)), 14, CARBON, "C")
    txt(surf, "CO2", (c[0], c[1] + 26), 14, WHITE, True, "midtop")
    for i, (hx, hy) in enumerate(((55, 205), (135, 205), (55, 255), (135, 255))):
        p = (ox + hx, oy + hy + w(i + 1))
        pygame.draw.line(surf, GRAY, (p[0] - 8, p[1]), (p[0] + 8, p[1]), 2)
        atom(surf, (p[0] - 8, p[1]), 8, HYD)
        atom(surf, (p[0] + 8, p[1]), 8, HYD)
    txt(surf, "4 H2", (ox + 95, oy + 282), 14, WHITE, True, "midtop")
    txt(surf, "+", (ox + 95, oy + 160), 26, WHITE, True, "center")
    a0, a1 = (ox + 172, oy + 185), (ox + 238, oy + 185)
    pygame.draw.line(surf, YELLOW, a0, a1, 4)
    arrow_head(surf, a0, a1, YELLOW, 14)
    for i in range(3):
        u = (t * 0.8 + i / 3) % 1.0
        pygame.draw.circle(surf, WHITE, (int(lerp(a0[0], a1[0], u)), a0[1]), 3)
    txt(surf, "Ni / Ru", (ox + 205, oy + 160), 13, (255, 220, 140), True, "midbottom")
    txt(surf, "catalyst", (ox + 205, oy + 205), 13, (255, 220, 140), False, "midtop")
    m = (ox + 305, oy + 112)
    for dx, dy in ((-22, -22), (22, -22), (-22, 22), (22, 22)):
        pygame.draw.line(surf, GRAY, (m[0], m[1] + w(5)), (m[0] + dx, m[1] + dy + w(5)), 3)
        atom(surf, (m[0] + dx, m[1] + dy + w(5)), 9, HYD)
    atom(surf, (m[0], m[1] + w(5)), 14, CARBON, "C")
    txt(surf, "CH4", (m[0], m[1] + 40), 14, (150, 255, 180), True, "midtop")
    for i, (wx, wy) in enumerate(((290, 215), (335, 270))):
        p = (ox + wx, oy + wy + w(i + 6))
        for dx in (-17, 17):
            pygame.draw.line(surf, GRAY, p, (p[0] + dx, p[1] + 14), 3)
            atom(surf, (p[0] + dx, p[1] + 14), 8, HYD)
        atom(surf, p, 12, OXY, "O")
    txt(surf, "2 H2O", (ox + 312, oy + 300), 14, (140, 200, 255), True, "midtop")
    txt(surf, "CO2 + 4 H2 -> CH4 + 2 H2O", (rect.centerx, rect.bottom - 44), 17, WHITE, True, "midtop")
    txt(surf, "exothermic: releases 165 kJ per mol", (rect.centerx, rect.bottom - 20), 13, (255, 180, 130), False, "midtop")


class Scene:
    def __init__(self, game):
        self.g = game
        self.t = 0.0

    def enter(self):
        self.t = 0.0

    def event(self, ev):
        pass

    def update(self, dt):
        self.t += dt

    def draw(self, surf):
        pass


CREW_LIST = (
    ("COMMANDER", (60, 140, 230)),
    ("PILOT", (230, 90, 70)),
    ("ISRU ENGINEER", (80, 190, 120)),
    ("MISSION SPECIALIST", (240, 190, 60)),
)


MON = ("TELEMETRY", "FLIGHT DYN", "COMMS", "POWER", "THERMAL", "GUIDANCE", "LIFE SUPPORT")


class ControlScene(Scene):
    def enter(self):
        self.t = 0.0
        self.talk = Talk([
            "Welcome to NASA Mission Control. I am your Engineer. Meet your crew of four astronauts.",
            "NASA studies for a 4-crew Mars ascent vehicle need %s kg of methane and %s kg of oxygen to fly home. That is your production limit. Press S any time to see the NASA sources." % (nf(REQ_CH4), nf(REQ_O2)),
            "The trip follows a transfer orbit. NASA's Perseverance needed %d days to cover 293 million miles from Earth to Mars. You can see the path on the screen to the right." % TRANSIT_DAYS,
            "Everything is ready on the pad. Press LAUNCH MISSION when you are ready.",
        ])
        self.btn = Button((925, 520, 260, 62), "LAUNCH MISSION", GREEN, 24, False)

    def event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.btn.hit(ev):
                self.g.go("launch")
                return
            self.talk.click()
        elif ev.type == pygame.KEYDOWN and ev.key in (pygame.K_SPACE, pygame.K_RETURN):
            self.talk.click()

    def update(self, dt):
        self.t += dt
        self.talk.update(dt)
        self.btn.enabled = self.talk.finished()

    def draw(self, surf):
        vgrad(surf, (0, 0, W, H), (8, 14, 36), (22, 38, 78))
        txt(surf, "NASA MISSION CONTROL  -  BLUE TO RED", (40, 12), 20, (150, 190, 255), True)
        for i in range(7):
            r = pygame.Rect(36 + i * 172, 44, 156, 96)
            rrect(surf, r, (6, 12, 26), (60, 110, 190), 6)
            pts = []
            for k in range(26):
                amp = 22 * math.sin(self.t * (1.2 + i * 0.3) + k * 0.5 + i) * (0.4 + 0.6 * math.sin(k * 0.3 + i) ** 2)
                pts.append((r.x + 8 + k * 5.6, r.centery + 12 + amp))
            pygame.draw.lines(surf, mixc(GREEN, CYAN, i / 6), False, pts, 2)
            txt(surf, MON[i], (r.x + 8, r.y + 6), 13, (130, 170, 230), True)
        pygame.draw.rect(surf, (14, 22, 46), (0, 560, W, 160))
        for i in range(9):
            x = 40 + i * 150
            pygame.draw.circle(surf, (28, 38, 70), (x + 55, 585), 17)
            pygame.draw.rect(surf, (28, 38, 70), (x + 30, 598, 50, 40), border_radius=10)
            rrect(surf, (x, 625, 110, 60), (22, 32, 62), (50, 80, 140), 6, 2)
            glass(surf, (x + 8, 632, 94, 30), CYAN, 40 + 30 * math.sin(self.t * 2 + i), 4)
        txt(surf, "MISSION CREW (4)", (560, 150), 18, CYAN, True, "midtop")
        for i, (role, col) in enumerate(CREW_LIST):
            ax = 345 + i * 150
            draw_astronaut(surf, ax, 478, 1.15, col, self.t + i)
            txt(surf, role, (ax, 482), 13, WHITE, True, "midtop")
        draw_traj(surf, (880, 150, 340, 340), (self.t * 0.12) % 1.0, self.t)
        draw_engineer(surf, 150, H, 1.5, self.talk.typing(), self.t)
        self.talk.draw(surf, pygame.Rect(290, 505, 570, 190), self.t)
        self.btn.draw(surf)
        if self.btn.enabled:
            glow(surf, self.btn.rect.center, 90, GREEN, 30)
            self.btn.draw(surf)


class LaunchScene(Scene):
    def enter(self):
        self.t = 0.0
        self.smoke = []
        self.r = random.Random(5)
        self.skip = Button((1110, 668, 150, 40), "SKIP >>", (60, 70, 100), 18)

    def alt(self):
        return clamp((self.t - 3.0) / 6.0, 0.0, 1.0) ** 1.6

    def rocket_y(self):
        return lerp(600, 330, clamp(self.alt() * 3.0, 0.0, 1.0))

    def event(self, ev):
        if self.skip.hit(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_SPACE):
            self.g.go("site")

    def update(self, dt):
        self.t += dt
        if 2.0 < self.t < 9.0:
            for _ in range(3):
                self.smoke.append([W / 2 + self.r.uniform(-14, 14), self.rocket_y() + 8, self.r.uniform(-50, 50), self.r.uniform(40, 130), 1.0, self.r.uniform(10, 22)])
        for p in self.smoke:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[4] -= dt * 0.7
        self.smoke = [p for p in self.smoke if p[4] > 0]
        if self.t > 17.5:
            self.g.go("site")

    def draw(self, surf):
        t = self.t
        if t < 9.0:
            alt = self.alt()
            vgrad(surf, (0, 0, W, H), mixc((70, 140, 230), (2, 4, 14), alt * 1.6), mixc((175, 215, 245), (10, 14, 34), alt * 1.3))
            if alt > 0.25:
                draw_stars(surf, t, (alt - 0.25) * 1.5)
            gy = int(620 + alt * 1200)
            if gy < H:
                pygame.draw.rect(surf, (70, 120, 70), (0, gy, W, H - gy))
                pygame.draw.rect(surf, (110, 112, 120), (W // 2 - 140, gy - 6, 280, 14))
                pygame.draw.rect(surf, (150, 60, 50), (W // 2 + 70, gy - 330, 26, 330))
                for yy in range(0, 330, 40):
                    pygame.draw.line(surf, (110, 40, 36), (W // 2 + 70, gy - yy), (W // 2 + 96, gy - yy - 40), 2)
                pygame.draw.rect(surf, (90, 160, 90), (0, gy - 60, 220, 60))
                pygame.draw.polygon(surf, (110, 160, 120), [(260, gy), (480, gy - 110), (700, gy)])
            for p in self.smoke:
                glow(surf, (p[0], p[1]), p[5] * (2.2 - p[4]), (225, 225, 230), 90 * p[4])
            flame = 0.0 if t < 2.0 else (0.3 if t < 3.0 else 1.0)
            draw_rocket(surf, W // 2, self.rocket_y(), 1.3, flame, t)
            if t < 3.0:
                label = "T-%d" % (3 - int(t)) if t < 3 else ""
                txt(surf, label, (W // 2, 110), 80, WHITE, True, "center")
            elif t < 5.0:
                txt(surf, "LIFTOFF!", (W // 2, 110), 80, YELLOW, True, "center")
            if t > 5.5:
                txt(surf, "Altitude %d km" % int(alt * 400), (40, 40), 24, WHITE, True)
        else:
            surf.fill((3, 6, 18))
            draw_stars(surf, t, 0.8)
            prog = clamp((t - 9.0) / 8.0, 0.0, 1.0)
            prog = prog * prog * (3 - 2 * prog)
            draw_traj(surf, (340, 30, 600, 600), prog, t)
            txt(surf, "Day %d / %d" % (int(prog * TRANSIT_DAYS), TRANSIT_DAYS), (W // 2, 650), 30, WHITE, True, "center")
            for i, (role, col) in enumerate(CREW_LIST):
                draw_astronaut(surf, 70 + i * 62, 690, 0.5, col, t)
            txt(surf, "Crew of 4 aboard", (40, 596), 16, WHITE, True)
            txt(surf, "Cruise to Mars", (40, 40), 26, CYAN, True)
        self.skip.draw(surf)


class SiteScene(Scene):
    def enter(self):
        self.t = 0.0
        self.phase = "choose"
        self.pick = None
        self.lt = 0.0
        self.card = {"polar": pygame.Rect(30, 110, 400, 490), "equator": pygame.Rect(850, 110, 400, 490)}
        self.btn = Button((490, 640, 300, 56), "LAND HERE", GREEN, 24, False)
        self.pos = {"polar": (640, 218), "equator": (660, 360)}

    def event(self, ev):
        if self.phase != "choose":
            return
        if self.btn.hit(ev):
            self.g.site = self.pick
            self.phase = "landing"
            self.lt = 0.0
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for k, r in self.card.items():
                if r.collidepoint(ev.pos):
                    self.pick = k
            for k, p in self.pos.items():
                if math.hypot(ev.pos[0] - p[0], ev.pos[1] - p[1]) < 40:
                    self.pick = k

    def update(self, dt):
        self.t += dt
        self.btn.enabled = self.pick is not None
        if self.phase == "landing":
            self.lt += dt
            if self.lt > 7.0:
                self.g.go("explain")

    def draw_mars(self, surf):
        cx, cy, r = 640, 340, 175
        glow(surf, (cx, cy), r + 40, (255, 150, 90), 45)
        pygame.draw.circle(surf, (196, 98, 56), (cx, cy), r)
        pygame.draw.circle(surf, (176, 84, 48), (cx + 30, cy + 20), r - 30)
        pygame.draw.circle(surf, (160, 74, 42), (cx + 60, cy + 40), r - 70)
        for dx, dy, rr in CRATERS:
            px, py = cx + dx * r * 0.8, cy + dy * r * 0.8
            if math.hypot(px - cx, py - cy) < r - 20:
                pygame.draw.circle(surf, (150, 70, 40), (int(px), int(py)), int(rr * r))
                pygame.draw.circle(surf, (205, 112, 70), (int(px), int(py)), int(rr * r), 2)
        pygame.draw.polygon(surf, (120, 58, 40), [(cx - 90, cy + 10), (cx - 20, cy - 20), (cx + 60, cy + 10), (cx + 20, cy + 50), (cx - 60, cy + 50)])
        th0 = math.acos(0.78)
        pts = []
        for i in range(21):
            a = -th0 + 2 * th0 * i / 20
            pts.append((cx + r * math.sin(a), cy - r * math.cos(a)))
        for i in range(21):
            u = 1 - i / 10
            pts.append((cx + r * math.sin(th0) * u, cy - 0.78 * r + 14 * (1 - u * u)))
        pygame.draw.polygon(surf, (240, 246, 252), pts)
        pygame.draw.circle(surf, (20, 14, 22), (cx, cy), r, 3)
        for k, p in self.pos.items():
            sel = self.pick == k
            pulse = 0.5 + 0.5 * math.sin(self.t * 4)
            glow(surf, p, 24 + 8 * pulse, YELLOW if sel else CYAN, 110)
            pygame.draw.circle(surf, YELLOW if sel else WHITE, p, 9)
            pygame.draw.circle(surf, BLACK, p, 9, 2)
        txt(surf, "A", (self.pos["polar"][0] + 18, self.pos["polar"][1] - 8), 20, WHITE, True)
        txt(surf, "B", (self.pos["equator"][0] + 18, self.pos["equator"][1] - 8), 20, WHITE, True)

    def draw_card(self, surf, key, title, pros, cons, tag):
        r = self.card[key]
        sel = self.pick == key
        hover = r.collidepoint(pygame.mouse.get_pos())
        rrect(surf, r, (14, 22, 46) if not hover else (20, 32, 62), YELLOW if sel else (70, 100, 170), 14, 4 if sel else 2)
        txt(surf, tag, (r.x + 20, r.y + 14), 16, CYAN, True)
        txt(surf, title, (r.x + 20, r.y + 38), 24, WHITE, True)
        y = r.y + 86
        for s in pros:
            txt(surf, "+", (r.x + 20, y), 20, GREEN, True)
            y = para(surf, s, (r.x + 46, y + 1), 18, (200, 240, 215), r.w - 70) + 6
        y += 10
        for s in cons:
            txt(surf, "-", (r.x + 23, y), 20, RED, True)
            y = para(surf, s, (r.x + 46, y + 1), 18, (250, 205, 200), r.w - 70) + 6

    def draw(self, surf):
        if self.phase == "landing":
            self.draw_landing(surf)
            return
        vgrad(surf, (0, 0, W, H), (5, 8, 22), (20, 12, 30))
        draw_stars(surf, self.t, 0.7)
        txt(surf, "CHOOSE THE LANDING SITE", (W // 2, 24), 34, WHITE, True, "midtop")
        txt(surf, "Click a card or a marker on the map", (W // 2, 70), 18, (170, 190, 230), False, "midtop")
        self.draw_mars(surf)
        self.draw_card(surf, "polar", "NORTH MID-LATITUDE (about 45 N)", [
            "NASA: subsurface water ice exists from the mid-latitudes to the poles",
            "Ice water helps the crew and gives extra hydrogen",
            "Fewer dust storms in the game model (30% chance)",
        ], [
            "NASA: Viking 2 at 48 N got only about 7 hours of weak winter sunlight",
            "Colder: mid-latitudes range about -100 to 0 C",
            "Game estimate: solar power only 65% of the equator, landing safety 93%",
        ], "SITE A")
        self.draw_card(surf, "equator", "NEAR THE EQUATOR", [
            "NASA: sites closer to the equator get the strongest sunlight",
            "Milder temperatures: about -73 to 20 C",
            "Game estimate: landing safety 97%",
        ], [
            "No easy ice: hydrogen must come from Earth or be recycled",
            "Hydrated minerals need a lot of energy to extract water",
            "Game estimate: dust storm chance 55% for solar plants",
        ], "SITE B")
        self.btn.draw(surf)

    def draw_landing(self, surf):
        lt = self.lt
        vgrad(surf, (0, 0, W, 560), (230, 175, 130), (170, 100, 70))
        pygame.draw.rect(surf, (140, 70, 40), (0, 560, W, 160))
        vgrad(surf, (0, 560, W, 160), (150, 76, 44), (90, 44, 28))
        for i in range(10):
            pygame.draw.ellipse(surf, (110, 56, 34), (60 + i * 130, 590 + (i % 3) * 30, 70, 18))
        pygame.draw.polygon(surf, (120, 66, 48), [(0, 560), (200, 500), (420, 560)])
        pygame.draw.polygon(surf, (130, 70, 50), [(800, 560), (1020, 480), (1280, 560)])
        ground = 520
        y = lerp(-80, ground, clamp(lt / 5.0, 0, 1) ** 0.8)
        x = 640
        if lt < 3.5:
            pygame.draw.ellipse(surf, (240, 240, 245), (x - 90, y - 190, 180, 110))
            pygame.draw.ellipse(surf, (200, 60, 50), (x - 90, y - 190, 180, 110), 3)
            for dx in (-80, -40, 40, 80):
                pygame.draw.line(surf, (230, 230, 235), (x + dx, y - 100), (x + dx // 3, y - 22), 1)
        pygame.draw.polygon(surf, (90, 90, 100), [(x - 30, y - 24), (x + 30, y - 24), (x + 22, y), (x - 22, y)])
        pygame.draw.polygon(surf, (225, 228, 238), [(x - 24, y - 24), (x + 24, y - 24), (x + 12, y - 62), (x - 12, y - 62)])
        pygame.draw.circle(surf, (120, 190, 255), (x, y - 44), 7)
        if 3.5 <= lt < 5.2:
            ln = 40 + 20 * math.sin(lt * 40)
            pygame.draw.polygon(surf, (255, 150, 50), [(x - 16, y), (x + 16, y), (x, y + ln)])
            glow(surf, (x, y + 10), 70, (255, 190, 100), 80)
        if lt > 4.8:
            for i in range(10):
                a = (lt - 4.8) * 0.8
                px = x + (i - 5) * 60 * (0.3 + a)
                glow(surf, (px, ground + 10 - 14 * a * (i % 3)), 30 + 20 * a, (210, 140, 100), 60 * clamp(1.6 - a, 0, 1))
        if lt > 5.4:
            targets = (470, 550, 730, 810)
            for i, (role, col) in enumerate(CREW_LIST):
                k = clamp((lt - 5.4 - i * 0.3) / 1.8, 0.0, 1.0)
                draw_astronaut(surf, lerp(640, targets[i], k), 600, 0.8, col, lt, 1.0 if k < 1.0 else 0.0)
        if lt > 5.2:
            txt(surf, "TOUCHDOWN! Crew of 4 is on Mars", (W // 2, 110), 52, WHITE, True, "center")
        else:
            txt(surf, "ENTRY, DESCENT AND LANDING", (W // 2, 60), 32, WHITE, True, "center")
            txt(surf, "Site: %s" % SITES[self.pick]["name"], (W // 2, 100), 20, (255, 235, 210), False, "center")


class ExplainScene(Scene):
    def enter(self):
        self.t = 0.0
        self.talk = Talk([
            "Touchdown confirmed! Your crew of four and your cargo are safe on Mars.",
            "To fly home we need fuel, and carrying it all from Earth is far too heavy. Mars air is 95% carbon dioxide at only 6.36 millibar (NASA Mars Fact Sheet), so we make fuel from it.",
            "NASA's MOXIE on Perseverance already made oxygen from Martian CO2: 12 grams per hour at best. You need a full-scale plant: a CO2 acquisition unit feeding a reactor.",
            "The recipe is the Sabatier reaction: CO2 plus 4 H2 gives methane (CH4) and 2 water (H2O). It releases heat. We run it in a PBR, a Packed-Bed Reactor: a tube filled with catalyst pellets.",
            "Water is split into O2, the oxidizer, and H2 that goes back into the reaction. Now decide how to power the plant.",
        ])
        self.btn = Button((830, 545, 400, 56), "CHOOSE POWER", GREEN, 22, False)

    def event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.btn.hit(ev):
                self.g.go("choose")
                return
            self.talk.click()
        elif ev.type == pygame.KEYDOWN and ev.key in (pygame.K_SPACE, pygame.K_RETURN):
            self.talk.click()

    def update(self, dt):
        self.t += dt
        self.talk.update(dt)
        self.btn.enabled = self.talk.finished()

    def draw(self, surf):
        vgrad(surf, (0, 0, W, 470), (225, 165, 120), (160, 92, 62))
        vgrad(surf, (0, 470, W, 250), (150, 76, 44), (80, 40, 26))
        pygame.draw.polygon(surf, (120, 64, 44), [(0, 470), (260, 380), (520, 470)])
        pygame.draw.polygon(surf, (132, 72, 50), [(500, 470), (800, 360), (1100, 470)])
        draw_engineer(surf, 120, H - 10, 1.5, self.talk.typing(), self.t)
        self.talk.draw(surf, pygame.Rect(230, 440, 580, 250), self.t)
        draw_reaction(surf, (830, 120, 400, 400), self.t)
        txt(surf, "ENGINEER'S SCREEN", (1030, 98), 14, (60, 30, 20), True, "midbottom")
        for i, (role, col) in enumerate(CREW_LIST):
            draw_astronaut(surf, 330 + i * 70, 430, 0.6, col, self.t + i)
        self.btn.draw(surf)


class ChooseScene(Scene):
    def enter(self):
        self.t = 0.0
        self.pick = None
        self.card = {"photo": pygame.Rect(40, 90, 590, 530), "pbr": pygame.Rect(650, 90, 590, 530)}
        self.btn = Button((500, 640, 280, 56), "CONFIRM", GREEN, 24, False)

    def event(self, ev):
        if self.btn.hit(ev):
            self.g.reactor = self.pick
            self.g.cfg = None
            self.g.sim = None
            self.g.go("reactor")
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for k, r in self.card.items():
                if r.collidepoint(ev.pos):
                    self.pick = k

    def update(self, dt):
        self.t += dt
        self.btn.enabled = self.pick is not None

    def draw(self, surf):
        vgrad(surf, (0, 0, W, H), (8, 14, 34), (18, 26, 58))
        txt(surf, "CHOOSE YOUR REACTOR AND POWER SOURCE", (W // 2, 24), 32, WHITE, True, "midtop")
        site = SITES[self.g.site]
        txt(surf, "Landing site: %s" % site["name"], (W // 2, 64), 18, (170, 190, 230), False, "midtop")
        info = {
            "photo": ("PHOTOCATALYTIC REACTOR", "Powered by sunlight (solar field)", [
                "Cheaper: about $%.1f B and about %.1f t of equipment" % (REACTORS["photo"]["cost"] / 1000.0, REACTORS["photo"]["mass"] / 1000.0),
                "Average power about %.0f kW at this site (game solar field)" % avg_power("photo", site),
                "Light does part of the work, so less heating is needed",
            ], [
                "Dust storms can cut power to 10% for 60 to 120 days (NASA studies assume up to 120 sols)",
                "Lower conversion per pass than the PBR",
                "Storm chance at this site: %d%% (game estimate)" % int(site["storm"] * 100),
            ]),
            "pbr": ("PACKED-BED REACTOR (PBR)", "Powered by a nuclear fission unit", [
                "Steady %d kWe day and night (NASA fission surface power goal)" % NUCLEAR_KW,
                "High conversion with a proven catalyst bed",
                "Plenty of power: the fuel can be made in less time",
            ], [
                "Expensive: about $%.1f B of the $%.0f B budget" % (REACTORS["pbr"]["cost"] / 1000.0, BUDGET / 1000.0),
                "Heavy: NASA's design limit for the 40 kWe unit is 6,000 kg, about %.1f t with the plant" % (REACTORS["pbr"]["mass"] / 1000.0),
                "Nuclear safety and licensing burden",
            ]),
        }
        for k, r in self.card.items():
            sel = self.pick == k
            hover = r.collidepoint(pygame.mouse.get_pos())
            rrect(surf, r, (20, 32, 62) if hover else (14, 22, 46), YELLOW if sel else (70, 100, 170), 16, 4 if sel else 2)
            icon_bg = pygame.Rect(r.x + 20, r.y + 20, r.w - 40, 220)
            vgrad(surf, icon_bg, (200, 130, 90), (120, 64, 42))
            pygame.draw.rect(surf, (230, 200, 170), icon_bg, 2)
            if k == "photo":
                draw_photo(surf, icon_bg.centerx, icon_bg.centery + 30, 0.6, self.t)
            else:
                draw_pbr(surf, icon_bg.centerx, icon_bg.centery - 8, 0.52, self.t)
            title, sub, pros, cons = info[k]
            txt(surf, title, (r.x + 24, r.y + 250), 26, WHITE, True)
            txt(surf, sub, (r.x + 24, r.y + 284), 18, CYAN, False)
            y = r.y + 314
            for s in pros:
                txt(surf, "+", (r.x + 24, y), 17, GREEN, True)
                y = para(surf, s, (r.x + 46, y), 15, (205, 240, 218), r.w - 70, False, 3) + 3
            for s in cons:
                txt(surf, "-", (r.x + 27, y), 17, RED, True)
                y = para(surf, s, (r.x + 46, y), 15, (250, 208, 202), r.w - 70, False, 3) + 3
        self.btn.draw(surf)


class ReactorScene(Scene):
    def enter(self):
        self.t = 0.0
        self.hit = pygame.Rect(0, 0, 10, 10)

    def event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.hit.collidepoint(ev.pos):
            self.g.go("sim")

    def draw(self, surf):
        g = self.g
        t = self.t
        pbr = g.reactor == "pbr"
        vgrad(surf, (0, 0, W, 470), (232, 178, 130), (170, 100, 70))
        vgrad(surf, (0, 470, W, 250), (160, 82, 48), (84, 42, 28))
        pygame.draw.polygon(surf, (126, 66, 46), [(0, 470), (240, 390), (520, 470)])
        pygame.draw.polygon(surf, (138, 76, 52), [(760, 470), (1040, 380), (1280, 470)])
        pygame.draw.ellipse(surf, (230, 235, 245), (0, 440, 200, 140))
        pygame.draw.ellipse(surf, (150, 190, 230), (40, 470, 120, 60))
        pygame.draw.rect(surf, (200, 206, 220), (0, 540, 200, 14))
        if pbr:
            draw_nuclear(surf, 430, 462, 0.65, t)
            txt(surf, "FISSION POWER UNIT", (430, 350), 13, WHITE, True, "midbottom")
        else:
            draw_solar_field(surf, 430, 462, 0.7)
            txt(surf, "SOLAR FIELD", (430, 395), 13, WHITE, True, "midbottom")
        base = 610
        sep = (910, 520)
        if pbr:
            cx, cy, s = 640, 425, 1.1
        else:
            cx, cy, s = 640, 520, 1.15
        if pbr:
            hit, inlet, outlet = draw_pbr(pygame.Surface((1, 1)), cx, cy, s, t)
        else:
            hit, inlet, outlet = draw_photo(pygame.Surface((1, 1)), cx, cy, s, t)
        out_co2 = (330 + 24, base - 58)
        draw_pipe(surf, [out_co2, (400, out_co2[1]), (400, inlet[1]), (inlet[0] + 4, inlet[1])], (200, 170, 120), t)
        if pbr:
            draw_pipe(surf, [(outlet[0] - 4, outlet[1]), (sep[0], outlet[1]), (sep[0], sep[1] - 75)], (120, 180, 130), t)
        else:
            draw_pipe(surf, [(outlet[0] - 4, outlet[1]), (sep[0] - 22, outlet[1])], (120, 180, 130), t)
        draw_pipe(surf, [(sep[0] + 22, 480), (985, 480), (985, 500), (1075, 500)], (110, 200, 120), t)
        draw_pipe(surf, [(sep[0] + 12, 590), (950, 590)], (100, 150, 235), t)
        draw_pipe(surf, [(1060, 590), (1230, 590), (1230, 568)], (150, 210, 240), t)
        draw_co2_unit(surf, 250, base, 1.0, t)
        if pbr:
            draw_pbr(surf, cx, cy, s, t)
        else:
            draw_photo(surf, cx, cy, s, t)
        draw_vessel(surf, sep[0], sep[1], 22, 75, t)
        draw_electro(surf, 1005, 588, 110, 52, t)
        draw_tank(surf, 1125, 500, 50, (210, 120, 60), "CH4")
        draw_tank(surf, 1230, 522, 46, (70, 140, 220), "O2")
        callout(surf, "CO2 ACQUISITION UNIT", "Mars air: 95.32% CO2 at 6.36 mbar (NASA)", (250, 388))
        callout(surf, "R-100 PACKED-BED REACTOR" if pbr else "R-100 PHOTOCATALYTIC REACTOR", "CO2 + 4 H2 -> CH4 + 2 H2O" if pbr else "light + catalyst plate with holes", (640, 232))
        callout(surf, "V-100 SEPARATOR", "CH4 gas up, water down", (910, 640))
        callout(surf, "ELECTROLYZER", "water -> O2 + H2 recycle", (1000, 535))
        callout(surf, "CH4 TANK", "", (1125, 424))
        callout(surf, "O2 TANK", "", (1215, 452))
        for i, (role, col) in enumerate(CREW_LIST):
            draw_astronaut(surf, 330 + i * 70, 716, 0.75, col, t + i)
        self.hit = hit
        pulse = 0.5 + 0.5 * math.sin(t * 4)
        hov = self.hit.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surf, mixc(WHITE, YELLOW, pulse) if not hov else YELLOW, self.hit.inflate(10, 10), 3 if not hov else 5, border_radius=12)
        name = REACTORS[g.reactor]["name"]
        rrect(surf, (300, 24, 680, 92), (12, 20, 44), CYAN, 14, 2)
        txt(surf, "Your %s plant is assembled at the base." % name, (640, 44), 24, WHITE, True, "midtop")
        txt(surf, "CLICK THE REACTOR to open the process simulation", (640, 80), 20, mixc(YELLOW, WHITE, pulse), True, "midtop")


STREAM_TAGS = {}
OY = 45


def pt(x, y):
    return (x, y + OY)


ROW = 170
ROW2 = 330
LINES = [
    ("CO2_FEED", [pt(187, ROW), pt(218, ROW)]),
    ("CO2_COMP", [pt(262, ROW), pt(300, ROW)]),
    ("MIX", [pt(370, ROW), pt(405, ROW)]),
    ("R_FEED", [pt(445, ROW), pt(500, ROW)]),
    ("R_OUT", [pt(562, ROW), pt(610, ROW)]),
    ("COOLED", [pt(650, ROW), pt(702, ROW)]),
    ("GAS", [pt(738, ROW), pt(793, ROW)]),
    ("CH4_OUT", [pt(847, ROW), pt(882, ROW)]),
    ("GAS_RCY", [pt(820, ROW - 32), pt(820, ROW - 72), pt(352, ROW - 72), pt(352, ROW - 17)]),
    ("H2_EARTH", [pt(318, ROW - 100), pt(318, ROW - 26)]),
    ("WATER", [pt(720, ROW + 44), pt(720, ROW2 - 14)]),
    ("CREW_H2O", [pt(734, ROW2), pt(855, ROW2)]),
    ("TO_EL", [pt(706, ROW2), pt(610, ROW2)]),
    ("H2_RECYC", [pt(530, ROW2), pt(335, ROW2), pt(335, ROW + 21)]),
    ("O2_OUT", [pt(570, ROW2 + 28), pt(570, ROW2 + 90)]),
]
TAGS = [
    ("CO2_FEED", pt(150, ROW)), ("CH4_OUT", pt(915, ROW)), ("H2_EARTH", pt(318, ROW - 112)),
    ("CREW_H2O", pt(895, ROW2)), ("O2_OUT", pt(570, ROW2 + 102)),
]
PALETTE = ("Material Stream", "Energy Stream", "Mixer", "Splitter", "Pump", "Compressor", "Heater", "Cooler", "Valve", "Pipe", "Separator", "CSTR", "PFR", "Conversion Rx", "Heat Exchanger", "Distillation")


def unit_name(surf, text, pos, anchor="midtop"):
    txt(surf, text, pos, 12, INK, True, anchor)


def sym_circle(surf, c, r, color=INK):
    pygame.draw.circle(surf, (238, 244, 252), c, r)
    pygame.draw.circle(surf, color, c, r, 2)


class SimScene(Scene):
    def enter(self):
        g = self.g
        self.t = 0.0
        site = SITES[g.site]
        if not (g.cfg and g.cfg["reactor"] == g.reactor):
            g.cfg = default_cfg(g.reactor, site)
        cfg = g.cfg
        pbr = g.reactor == "pbr"
        avg = avg_power(g.reactor, site)
        x, w = 975, 280
        self.sl = {}
        specs = [
            ("T", "Reactor temperature", 500.0 if pbr else 450.0, 750.0 if pbr else 600.0, 5.0, lambda v: "%.0f K" % v, "Hotter: faster, but lower equilibrium limit", 144),
            ("P", "Operating pressure", 1.0, 10.0, 0.5, lambda v: "%.1f bar" % v, "More conversion, more compressor energy", 202),
            ("w", "Catalyst bed W/F0 (kg s/mol)" if pbr else "Light intensity (suns)", 2.0 if pbr else 0.2, 30.0 if pbr else 3.0, 1.0 if pbr else 0.1, (lambda v: "%.0f" % v) if pbr else (lambda v: "%.1f" % v), "More catalyst: more conversion, more drop" if pbr else "More light: more conversion, more energy", 260),
            ("r", "H2 : CO2 inlet ratio", 3.5, 5.0, 0.1, lambda v: "%.1f" % v, "Extra H2: more conversion, more recycle", 342),
            ("power", "Plant power", 2.0, math.floor(avg * 10) / 10.0, 0.5, lambda v: "%.1f kW" % v, "Less power = less energy; limited by source", 424),
            ("fe", "Water sent to electrolyzer", 0.0, 1.0, 0.05, lambda v: "%d %%" % round(v * 100), "More: more O2 and H2, less crew water", 482),
        ]
        for key, label, lo, hi, step, fmt, hint, yy in specs:
            self.sl[key] = Slider(x, yy, w, label, lo, hi, cfg[key], step, fmt, False, hint)
        self.solve_btn = Button((975, 674, 135, 40), "SOLVE (F5)", (40, 150, 90), 17)
        self.accept_btn = Button((1120, 674, 140, 40), "ACCEPT >", BLUE, 17, False)
        self.solving = False
        self.st = 0.0
        self.res = None
        self.dirty = True
        self.log = []
        self.used = None
        if g.sim:
            self.res = g.sim
            self.dirty = False
            self.used = dict(cfg)

    def cfg_now(self):
        c = dict(self.g.cfg)
        for k, s in self.sl.items():
            c[k] = s.val
        return c

    def start_solve(self):
        self.solving = True
        self.st = 0.0
        self.res = None
        self.dirty = False

    def event(self, ev):
        if self.solving:
            return
        for s in self.sl.values():
            if s.handle(ev):
                self.dirty = True
        if self.solve_btn.hit(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_F5):
            self.start_solve()
        if self.accept_btn.hit(ev):
            self.g.cfg = self.used
            self.g.sim = self.res
            self.g.go("plan")

    def update(self, dt):
        self.t += dt
        if self.solving:
            self.st += dt
            n = int(self.st / 0.22)
            lines = ["Reading flowsheet Mars_ISRU_Sabatier ...", "Sequential-modular solver started", "Recycle loop: gas return to MIX-100"]
            for i in range(6):
                lines.append("Iteration %d  recycle error = %.2e" % (i + 1, 0.31 * 0.2 ** i))
            lines.append("Electrolyzer EL-100 balanced")
            lines.append("CONVERGED")
            self.log = lines[:n]
            if self.st > 3.0:
                self.used = self.cfg_now()
                self.res = simulate(self.used, SITES[self.g.site])
                self.solving = False
        self.accept_btn.enabled = self.res is not None and not self.dirty and not self.solving

    def draw_units(self, surf, solved):
        t = self.t
        g = self.g
        pbr = g.reactor == "pbr"
        c = pt(240, ROW)
        sym_circle(surf, c, 22)
        pygame.draw.polygon(surf, INK, [(c[0] - 14, c[1] - 12), (c[0] + 14, c[1] - 5), (c[0] + 14, c[1] + 5), (c[0] - 14, c[1] + 12)], 2)
        unit_name(surf, "K-100", (c[0], c[1] + 26))
        mx = pt(335, ROW)
        poly = [(mx[0] - 35, mx[1] - 30), (mx[0] + 35, mx[1] - 12), (mx[0] + 35, mx[1] + 12), (mx[0] - 35, mx[1] + 30)]
        pygame.draw.polygon(surf, (238, 244, 252), poly)
        pygame.draw.polygon(surf, INK, poly, 2)
        unit_name(surf, "MIX-100", (mx[0] - 40, mx[1] - 44), "midright")
        h = pt(425, ROW)
        sym_circle(surf, h, 20)
        pygame.draw.lines(surf, RED, False, [(h[0] - 12, h[1] + 4), (h[0] - 6, h[1] - 6), (h[0], h[1] + 4), (h[0] + 6, h[1] - 6), (h[0] + 12, h[1] + 4)], 2)
        unit_name(surf, "E-100", (h[0], h[1] + 24))
        rc = pt(530, ROW)
        if pbr:
            body = pygame.Rect(rc[0] - 26, rc[1] - 38, 52, 76)
            pygame.draw.rect(surf, (238, 244, 252), body)
            pygame.draw.ellipse(surf, (238, 244, 252), (body.x, body.y - 8, 52, 16))
            pygame.draw.ellipse(surf, (238, 244, 252), (body.x, body.bottom - 8, 52, 16))
            for i in range(14):
                px = body.x + 8 + (i % 4) * 12
                py = body.y + 10 + (i // 4) * 15
                pygame.draw.circle(surf, (210, 150, 70), (px, py), 4)
                pygame.draw.circle(surf, INK, (px, py), 4, 1)
            pygame.draw.lines(surf, INK, False, [(body.x, body.y), (body.x, body.bottom)], 2)
            pygame.draw.lines(surf, INK, False, [(body.right, body.y), (body.right, body.bottom)], 2)
            pygame.draw.arc(surf, INK, (body.x, body.y - 8, 52, 16), 0, math.pi, 2)
            pygame.draw.arc(surf, INK, (body.x, body.bottom - 8, 52, 16), math.pi, 2 * math.pi, 2)
            unit_name(surf, "R-100  PBR", (rc[0], rc[1] + 48))
        else:
            body = pygame.Rect(rc[0] - 34, rc[1] - 34, 68, 68)
            pygame.draw.rect(surf, (238, 244, 252), body)
            pygame.draw.rect(surf, INK, body, 2)
            for i in range(4):
                for j in range(4):
                    pygame.draw.circle(surf, (230, 170, 40), (body.x + 12 + i * 15, body.y + 12 + j * 15), 4)
                    pygame.draw.circle(surf, INK, (body.x + 12 + i * 15, body.y + 12 + j * 15), 4, 1)
            sun = (rc[0], rc[1] - 52)
            pygame.draw.circle(surf, YELLOW, sun, 8)
            for a in range(8):
                ang = a * math.pi / 4 + t
                pygame.draw.line(surf, ORANGE, (sun[0] + 11 * math.cos(ang), sun[1] + 11 * math.sin(ang)), (sun[0] + 16 * math.cos(ang), sun[1] + 16 * math.sin(ang)), 2)
            unit_name(surf, "R-100  PHOTO", (rc[0], rc[1] + 40))
        cl = pt(630, ROW)
        sym_circle(surf, cl, 20)
        pygame.draw.lines(surf, BLUE, False, [(cl[0] - 12, cl[1] + 4), (cl[0] - 6, cl[1] - 6), (cl[0], cl[1] + 4), (cl[0] + 6, cl[1] - 6), (cl[0] + 12, cl[1] + 4)], 2)
        unit_name(surf, "E-101", (cl[0], cl[1] + 24))
        v = pt(720, ROW)
        body = pygame.Rect(v[0] - 18, v[1] - 36, 36, 72)
        pygame.draw.rect(surf, (238, 244, 252), body)
        pygame.draw.rect(surf, (150, 200, 245), (body.x, body.y + 46, 36, 26))
        pygame.draw.ellipse(surf, (238, 244, 252), (body.x, body.y - 8, 36, 16))
        pygame.draw.ellipse(surf, (150, 200, 245), (body.x, body.bottom - 8, 36, 16))
        pygame.draw.lines(surf, INK, False, [(body.x, body.y), (body.x, body.bottom)], 2)
        pygame.draw.lines(surf, INK, False, [(body.right, body.y), (body.right, body.bottom)], 2)
        pygame.draw.arc(surf, INK, (body.x, body.y - 8, 36, 16), 0, math.pi, 2)
        pygame.draw.arc(surf, INK, (body.x, body.bottom - 8, 36, 16), math.pi, 2 * math.pi, 2)
        unit_name(surf, "V-100", (v[0] + 40, v[1] - 36), "midleft")
        m = pt(820, ROW)
        mr = pygame.Rect(m[0] - 27, m[1] - 30, 54, 60)
        pygame.draw.rect(surf, (238, 244, 252), mr)
        pygame.draw.rect(surf, INK, mr, 2)
        for i in range(-2, 3):
            dashed(surf, (120, 140, 190), (mr.x + 4, mr.centery + i * 10 + 12), (mr.right - 4, mr.centery + i * 10 - 12), 5, 1)
        unit_name(surf, "MEM-100", (m[0], m[1] + 34))
        s = pt(720, ROW2)
        pygame.draw.polygon(surf, (238, 244, 252), [(s[0] - 14, s[1] - 14), (s[0] + 14, s[1]), (s[0] - 14, s[1] + 14)])
        pygame.draw.polygon(surf, INK, [(s[0] - 14, s[1] - 14), (s[0] + 14, s[1]), (s[0] - 14, s[1] + 14)], 2)
        unit_name(surf, "SP-100", (s[0], s[1] + 20))
        e = pt(570, ROW2)
        er = pygame.Rect(e[0] - 40, e[1] - 28, 80, 56)
        pygame.draw.rect(surf, (238, 244, 252), er)
        pygame.draw.rect(surf, INK, er, 2)
        pygame.draw.line(surf, INK, (er.x + 22, er.y + 8), (er.x + 22, er.bottom - 8), 3)
        pygame.draw.line(surf, INK, (er.right - 22, er.y + 8), (er.right - 22, er.bottom - 8), 3)
        txt(surf, "-", (er.x + 10, er.centery), 18, RED, True, "center")
        txt(surf, "+", (er.right - 10, er.centery), 18, BLUE, True, "center")
        if solved:
            for i in range(5):
                u = (t * 0.6 + i * 0.2) % 1.0
                pygame.draw.circle(surf, (150, 200, 245), (er.x + 30 + (i * 7) % 20, int(er.bottom - 6 - u * 40)), 3, 1)
        unit_name(surf, "EL-100", (e[0], e[1] - 32), "midbottom")

    def draw(self, surf):
        g = self.g
        surf.fill((222, 228, 240))
        pygame.draw.rect(surf, (30, 60, 110), (0, 0, W, 26))
        txt(surf, "Mars_ISRU_Sabatier.sim  [%s]" % ("Solved" if (self.res and not self.dirty) else "Not calculated"), (12, 4), 15, WHITE, True)
        pygame.draw.rect(surf, (236, 240, 248), (0, 26, W, 24))
        x = 10
        for m in ("File", "Edit", "View", "Simulation", "Tools", "Utilities", "Results", "Help"):
            r = txt(surf, m, (x, 30), 15, INK)
            x = r.right + 22
        pygame.draw.rect(surf, (214, 222, 238), (0, 50, W, 34))
        for i, col in enumerate(((60, 120, 200), (80, 170, 100), (230, 170, 50), (200, 80, 80), (120, 120, 200), (60, 160, 180))):
            pygame.draw.rect(surf, col, (12 + i * 40, 56, 24, 22), border_radius=4)
        txt(surf, "NASA limit for the 4-crew ascent vehicle: %s kg CH4 + %s kg O2     NASA ISRU reference rate: %.2f kg/h CH4" % (nf(REQ_CH4), nf(REQ_O2), NASA_RATE_KG_H), (270, 60), 14, INK, True)
        pygame.draw.rect(surf, (232, 236, 246), (0, 84, 108, H - 84))
        txt(surf, "Object Palette", (8, 90), 14, INK, True)
        for i, name in enumerate(PALETTE):
            yy = 116 + i * 24
            pygame.draw.rect(surf, (90, 130, 200) if i % 3 == 0 else (150, 160, 190), (8, yy + 2, 14, 14), border_radius=3)
            txt(surf, name, (28, yy), 12, INK)
        canvas = pygame.Rect(108, 84, 842, 421)
        pygame.draw.rect(surf, PAPER, canvas)
        for gx in range(canvas.x + 10, canvas.right, 20):
            for gy in range(canvas.y + 10, canvas.bottom, 20):
                surf.set_at((gx, gy), (205, 212, 228))
        solved = self.res is not None and not self.dirty and not self.solving
        for name, pts in LINES:
            col = (30, 80, 190) if solved else (130, 140, 160)
            if name == "GAS_RCY":
                col = (40, 150, 90) if solved else (130, 140, 160)
            pygame.draw.lines(surf, col, False, pts, 3)
            arrow_head(surf, pts[-2], pts[-1], col, 10)
            if solved:
                total = poly_len(pts)
                n = max(1, int(total / 26))
                for i in range(n):
                    d = (i * 26 + self.t * 55) % total
                    p = poly_point(pts, d)
                    pygame.draw.circle(surf, WHITE, (int(p[0]), int(p[1])), 3)
        self.draw_units(surf, solved)
        for name, p in TAGS:
            r = pygame.Rect(0, 0, 76, 20)
            r.center = p
            rrect(surf, r, (80, 140, 230) if solved else (150, 160, 178), INK, 5, 1)
            txt(surf, name, r.center, 12, WHITE, True, "center")
        if self.res:
            d = self.res["duties"]
            for nm, key, xx in (("K-100", "comp", 240), ("E-100", "heat", 425), ("E-101", "cool", 630)):
                p0, p1 = pt(xx, ROW + 40), pt(xx, ROW + 62)
                dashed(surf, RED, p0, p1, 4, 2)
                txt(surf, "%.2f kW" % d[key], (xx, p1[1] + 3), 12, RED, True, "midtop")
            if g.reactor == "photo":
                p0, p1 = pt(530, ROW + 58), pt(530, ROW + 84)
                dashed(surf, ORANGE, p0, p1, 4, 2)
                txt(surf, "light %.2f kW" % d["light"], (530, p1[1] + 3), 12, ORANGE, True, "midtop")
            txt(surf, "%.2f kW" % d["el"], (e_x(), pt(0, ROW2)[1] + 26), 12, RED, True, "midleft")
        if self.solving:
            box = pygame.Rect(250, 150, 460, 220)
            rrect(surf, box, (20, 24, 36), (120, 150, 210), 8, 2)
            txt(surf, "Calculator Log", (box.x + 12, box.y + 8), 15, (150, 190, 255), True)
            for i, ln in enumerate(self.log[-9:]):
                txt(surf, ln, (box.x + 12, box.y + 34 + i * 20), 14, GREEN if ln == "CONVERGED" else (210, 220, 240))
        self.draw_table(surf)
        self.draw_panel(surf)

    def draw_table(self, surf):
        area = pygame.Rect(108, 505, 842, 215)
        pygame.draw.rect(surf, (236, 240, 248), area)
        pygame.draw.rect(surf, (150, 160, 190), area, 1)
        txt(surf, "Master Property Table - Material Streams", (area.x + 8, area.y + 3), 13, INK, True)
        cols = [("Stream", 8), ("T [K]", 108), ("P [bar]", 160), ("mol/h", 222), ("kg/h", 284), ("CO2", 346), ("H2", 410), ("CH4", 474), ("H2O", 538), ("O2", 602)]
        pygame.draw.rect(surf, (200, 210, 232), (area.x + 1, area.y + 20, area.w - 2, 18))
        for name, off in cols:
            txt(surf, name, (area.x + off, area.y + 22), 13, INK, True)
        txt(surf, "mole fractions", (area.x + 668, area.y + 22), 13, INK, False)
        if not self.res:
            txt(surf, "Press SOLVE to calculate the flowsheet", (area.centerx, area.centery + 15), 18, GRAY, False, "center")
            return
        for i, s in enumerate(self.res["streams"]):
            yy = area.y + 41 + i * 15.5
            if i % 2 == 0:
                pygame.draw.rect(surf, (246, 248, 253), (area.x + 1, yy - 1, area.w - 2, 15))
            vals = [s["name"], "%.0f" % s["T"], ("%.4f" % s["P"]) if s["P"] < 0.1 else "%.2f" % s["P"], "%.2f" % s["mol"], "%.3f" % s["kg"]]
            vals += ["%.3f" % s["x"].get(c, 0.0) for c in ("CO2", "H2", "CH4", "H2O", "O2")]
            for (name, off), v in zip(cols, vals):
                txt(surf, v, (area.x + off, yy), 12, INK)

    def draw_panel(self, surf):
        g = self.g
        panel = pygame.Rect(955, 84, 325, H - 84)
        pygame.draw.rect(surf, (236, 240, 248), panel)
        pygame.draw.line(surf, (150, 160, 190), (955, 84), (955, H), 2)
        txt(surf, "PROCESS CONTROLS - your decisions", (975, 88), 16, INK, True)
        site = SITES[g.site]
        txt(surf, "%s | %s" % (REACTORS[g.reactor]["name"].split(" (")[0], site["short"]), (975, 108), 12, (80, 90, 120))
        for label, yy in (("1  REACTOR CONDITIONS", 126), ("2  FEED GAS", 324), ("3  ENERGY AND WATER", 406)):
            pygame.draw.rect(surf, (200, 210, 232), (975, yy - 2, 280, 17), border_radius=4)
            txt(surf, label, (981, yy), 13, INK, True)
        for s in self.sl.values():
            s.draw(surf)
        y = 546
        if self.solving:
            status, col = "SOLVING ...", ORANGE
        elif self.res and not self.dirty:
            status, col = "SOLVED - flowsheet converged", GREEN
        elif self.res:
            status, col = "OUT OF DATE - press SOLVE", ORANGE
        else:
            status, col = "NOT SOLVED - press SOLVE", RED
        txt(surf, status, (975, y), 15, col, True)
        y += 22
        if self.res and not self.dirty:
            r = self.res
            rows = [
                ("Conversion per pass", "%.1f %%  (limit %.1f %%)" % (r["X"] * 100, r["xeq"] * 100)),
                ("Energy per kg CH4", "%.1f kWh" % r["e_kwh_kg"]),
                ("CH4 production", "%.2f kg/h (NASA ref %.2f)" % (r["ch4_kg_h"], NASA_RATE_KG_H)),
                ("H2 needed from Earth", "%.2f kg per kg CH4" % r["h2_kg_per_kg"]),
                ("O2 from electrolysis", "%.2f kg per kg CH4" % r["o2_kg_per_kg"]),
                ("Pressure drop", "%.2f bar" % r["dP"]),
            ]
            for a, b in rows:
                txt(surf, a, (975, y), 13, (70, 80, 112))
                txt(surf, b, (1255, y), 13, INK, True, "topright")
                y += 16
        else:
            para(surf, "Set the conditions above, then solve. Save as much energy as you can.", (975, y), 13, (70, 80, 112), 280, False, 2)
        self.solve_btn.draw(surf)
        self.accept_btn.draw(surf)


def e_x():
    return 620


DAY_OPTIONS = (360, 480, 600)


class PlanScene(Scene):
    def enter(self):
        g = self.g
        self.t = 0.0
        p = g.plan
        self.veh = {k: Button((40 + i * 205, 90, 190, 56), "%s  %d t" % (VEHICLES[k]["name"], VEHICLES[k]["limit"] / 1000), BLUE, 19) for i, k in enumerate(("light", "medium", "heavy"))}
        self.days = {d: Button((40 + i * 205, 200, 190, 52), "%d DAYS" % d + (" (NASA)" if d == 480 else ""), BLUE, 19) for i, d in enumerate(DAY_OPTIONS)}
        self.sl_h2 = Slider(40, 278, 600, "3  Hydrogen brought from Earth", 500, 4500, p["h2"], 100, lambda v: "%s kg" % nf(v), True, "Hydrogen is heavy to carry: more water recycling means less")
        self.sl_t = Slider(40, 352, 600, "4  Propellant to produce (CH4)", 3000, 9000, p["target"], 100, lambda v: "%s kg CH4" % nf(v), True, "Aim close to the NASA limit: less cannot reach orbit, more wastes energy", REQ_CH4)
        self.back = Button((40, 16, 230, 36), "< BACK TO SIMULATOR", (60, 70, 100), 16)
        self.go_btn = Button((760, 650, 400, 56), "LAUNCH RETURN MISSION", GREEN, 22)

    def event(self, ev):
        p = self.g.plan
        for k, b in self.veh.items():
            if b.hit(ev):
                p["vehicle"] = k
        for k, b in self.days.items():
            if b.hit(ev):
                p["days"] = k
        self.sl_h2.handle(ev)
        self.sl_t.handle(ev)
        p["h2"] = self.sl_h2.val
        p["target"] = self.sl_t.val
        if self.back.hit(ev):
            self.g.go("sim")
        if self.go_btn.hit(ev):
            m = mission_eval(self.g)
            if m["cost"] > BUDGET or m["mass"] > m["mass_limit"]:
                return
            storm = None
            site = SITES[self.g.site]
            if self.g.reactor == "photo" and random.random() < site["storm"]:
                dur = random.randint(60, 120)
                storm = (random.randint(20, max(21, p["days"] - dur)), dur)
            self.g.result = mission_eval(self.g, storm)
            self.g.go("result")

    def bar(self, surf, y, label, need, have, unit, scale=1.0):
        txt(surf, label, (680, y), 18, WHITE, True)
        ratio = need / have if have > 0 else 9.9
        col = GREEN if ratio <= 0.9 else (YELLOW if ratio <= 1.0 else RED)
        rrect(surf, (680, y + 28, 520, 20), (30, 40, 70), (90, 110, 160), 8, 1)
        rrect(surf, (680, y + 28, max(6, int(520 * min(1.0, ratio))), 20), col, None, 8)
        txt(surf, "need %s %s   |   available %s %s" % (nf(need * scale), unit, nf(have * scale), unit), (680, y + 52), 14, (190, 205, 235))
        return ratio <= 1.0

    def draw(self, surf):
        g = self.g
        p = g.plan
        vgrad(surf, (0, 0, W, H), (8, 14, 34), (18, 26, 58))
        self.back.draw(surf)
        txt(surf, "MISSION PLANNING", (W // 2, 18), 32, WHITE, True, "midtop")
        txt(surf, "1  LANDER (cargo limit and cost)", (40, 66), 16, CYAN, True)
        for k, b in self.veh.items():
            b.color = (50, 150, 100) if p["vehicle"] == k else (50, 70, 120)
            b.draw(surf)
            txt(surf, "$%.1f B" % (VEHICLES[k]["cost"] / 1000.0), (b.rect.centerx, b.rect.bottom + 4), 14, (190, 205, 235), False, "midtop")
        txt(surf, "2  PRODUCTION TIME BEFORE ASCENT (NASA baseline: 480 days)", (40, 176), 16, CYAN, True)
        for k, b in self.days.items():
            b.color = (50, 150, 100) if p["days"] == k else (50, 70, 120)
            b.draw(surf)
        self.sl_h2.draw(surf)
        self.sl_t.draw(surf)
        draw_engineer(surf, 90, H - 6, 0.9, False, self.t)
        rrect(surf, (150, 470, 490, 230), (12, 20, 44), CYAN, 14, 2)
        txt(surf, "ENGINEER", (166, 480), 15, CYAN, True)
        para(surf, "NASA limit: the 4-crew ascent vehicle needs %s kg CH4 and %s kg O2 (mixture about 3.3 to 1). Producing less cannot reach orbit. At NASA's reference rate of %.2f kg/h CH4 this takes about 480 days. Crew water: %d astronauts use about %.1f L each per day and NASA recycles 98%%." % (nf(REQ_CH4), nf(REQ_O2), NASA_RATE_KG_H, CREW, CREW_L_DAY), (166, 504), 15, WHITE, 455, False, 4)
        m = mission_eval(g)
        rrect(surf, (650, 76, 590, 560), (12, 20, 44), (70, 100, 170), 14, 2)
        txt(surf, "FEASIBILITY CHECK", (680, 86), 18, YELLOW, True)
        self.bar(surf, 116, "Energy", m["e_need"], max(m["e_avail"], 1.0), "MWh", 0.001)
        self.bar(surf, 188, "Hydrogen from Earth", m["h2_need"], m["h2_have"], "kg")
        ok3 = self.bar(surf, 260, "Cargo mass", m["mass"], m["mass_limit"], "kg")
        ok4 = self.bar(surf, 332, "Cost", m["cost"], BUDGET, "$M")
        self.bar(surf, 404, "Crew water", m["crew_need"], max(m["crew_water"], 1.0), "kg")
        y = 482
        lines = [
            "Expected CH4: %s kg (NASA limit %s kg)   O2: %s kg" % (nf(m["nominal"]), nf(REQ_CH4), nf(m["nominal"] * O2_RATIO)),
            "Plant power %.1f kW   energy per kg CH4 incl. O2 make-up: %.1f kWh" % (min(g.cfg["power"], avg_power(g.reactor, SITES[g.site])), m["e_total"]),
        ]
        for s in lines:
            y = para(surf, s, (680, y), 14, (210, 225, 250), 540, False, 3)
        if g.reactor == "photo":
            y = para(surf, "Dust storm risk here: %d%% (power falls to 10%% for 60 to 120 days)." % int(SITES[g.site]["storm"] * 100), (680, y), 14, (255, 200, 150), 540, False, 3)
        if p["target"] < REQ_CH4:
            y = para(surf, "Target is below the NASA limit: the vehicle cannot reach orbit.", (680, y), 14, (255, 150, 140), 540, False, 3)
        if m["nominal"] < REQ_CH4:
            y = para(surf, "Not enough propellant expected: add power, more days, or better efficiency.", (680, y), 14, (255, 150, 140), 540, False, 3)
        self.go_btn.enabled = ok3 and m["cost"] <= BUDGET
        self.go_btn.draw(surf)
        if not self.go_btn.enabled:
            txt(surf, "Cargo or budget exceeded", (960, 646), 14, (255, 150, 140), True, "midbottom")


class ResultScene(Scene):
    def enter(self):
        self.t = 0.0
        self.btn = Button((900, 650, 300, 52), "PLAY AGAIN", BLUE, 22)

    def event(self, ev):
        if self.btn.hit(ev):
            self.g.reset_state()
            self.g.go("control")

    def draw_chart(self, surf, area, m):
        rrect(surf, area, (10, 16, 36), (70, 100, 170), 12, 2)
        txt(surf, "RETURN PROPELLANT PRODUCTION (CH4, kg)", (area.x + 16, area.y + 10), 16, CYAN, True)
        pl = pygame.Rect(area.x + 70, area.y + 44, area.w - 100, area.h - 90)
        ymax = max(REQ_CH4 * 1.3, max(m["daily"]) * 1.1, self.g.plan["target"] * 1.05)
        for i in range(5):
            yy = pl.bottom - pl.h * i / 4
            pygame.draw.line(surf, (40, 56, 90), (pl.x, yy), (pl.right, yy), 1)
            txt(surf, nf(ymax * i / 4), (pl.x - 8, yy), 13, (160, 180, 220), False, "midright")
        days = m["days"]
        if m["storm"]:
            s0, dur = m["storm"]
            x0 = pl.x + pl.w * s0 / days
            x1 = pl.x + pl.w * min(days, s0 + dur) / days
            glass(surf, (x0, pl.y, x1 - x0, pl.h), ORANGE, 70, 0)
            txt(surf, "dust storm", (x0 + 4, pl.y + 4), 13, (255, 200, 140), True)
        yr = pl.bottom - pl.h * REQ_CH4 / ymax
        dashed(surf, RED, (pl.x, yr), (pl.right, yr), 8, 2)
        txt(surf, "NASA limit %s kg" % nf(REQ_CH4), (pl.right - 4, yr - 4), 13, (255, 150, 140), True, "bottomright")
        pts = [(pl.x, pl.bottom)]
        for i, v in enumerate(m["daily"]):
            pts.append((pl.x + pl.w * (i + 1) / days, pl.bottom - pl.h * v / ymax))
        pygame.draw.lines(surf, CYAN, False, pts, 3)
        for d in range(0, days + 1, 60):
            xx = pl.x + pl.w * d / days
            txt(surf, str(d), (xx, pl.bottom + 6), 13, (160, 180, 220), False, "midtop")
        txt(surf, "day on Mars", (pl.centerx, pl.bottom + 24), 14, (160, 180, 220), False, "midtop")

    def draw(self, surf):
        g = self.g
        m = g.result
        vgrad(surf, (0, 0, W, H), (8, 14, 34), (18, 26, 58))
        ok = m["success"]
        txt(surf, "MISSION SCORECARD", (40, 18), 32, WHITE, True)
        txt(surf, "MISSION SUCCESS - the crew of 4 can fly home" if ok else "MISSION FAILED - not enough return propellant", (40, 58), 22, GREEN if ok else RED, True)
        self.draw_chart(surf, pygame.Rect(40, 100, 640, 320), m)
        rrect(surf, (40, 440, 640, 260), (12, 20, 44), (70, 100, 170), 12, 2)
        txt(surf, "MISSION LOG", (56, 450), 16, CYAN, True)
        site = SITES[g.site]
        veh = VEHICLES[g.plan["vehicle"]]
        log = [
            "Launched on the %s lander with %.1f t of cargo and a crew of %d." % (veh["name"].lower(), m["mass"] / 1000.0, CREW),
            "Landed on the %s. %s commissioned." % (site["short"], REACTORS[g.reactor]["name"]),
        ]
        if g.reactor == "photo":
            if m["storm"]:
                log.append("Day %d: dust storm! Solar power fell to 10%% for %d days." % (m["storm"][0] + 1, m["storm"][1]))
            else:
                log.append("No dust storm hit during the production window.")
        else:
            log.append("The nuclear unit ran at full power, unaffected by dust.")
        log.append("Produced %s kg CH4 and %s kg O2 (limited by %s)." % (nf(m["prod"]), nf(m["o2"]), m["limit"]))
        log.append("Crew water: %s kg available, %s kg needed (%s)." % (nf(m["crew_water"]), nf(m["crew_need"]), "enough" if m["crew_ok"] else "NOT enough"))
        y = 478
        for s in log:
            y = para(surf, s, (56, y), 15, (215, 228, 250), 600, False, 3) + 1
        rrect(surf, (710, 100, 530, 530), (12, 20, 44), (70, 100, 170), 12, 2)
        txt(surf, "SCORECARD", (730, 112), 18, YELLOW, True)
        rows = [
            ("Fuel produced", "%s kg (limit %s)" % (nf(m["prod"]), nf(REQ_CH4)), m["pts"]["fuel"] / 40.0),
            ("Cost", "$%.1f B of $%.0f B" % (m["cost"] / 1000.0, BUDGET / 1000.0), m["pts"]["cost"] / 15.0),
            ("Launch mass", "%.1f of %.0f t" % (m["mass"] / 1000.0, m["mass_limit"] / 1000.0), m["pts"]["mass"] / 10.0),
            ("Energy efficiency", "%.1f kWh per kg propellant" % m["e_prop"], m["pts"]["eff"] / 20.0),
            ("Reliability", "%.0f %%" % (m["rel"] * 100), m["pts"]["rel"] / 15.0),
        ]
        y = 150
        for a, b, f in rows:
            txt(surf, a, (730, y), 18, WHITE, True)
            txt(surf, b, (1220, y + 2), 15, (190, 205, 235), False, "topright")
            rrect(surf, (730, y + 30, 490, 16), (30, 40, 70), None, 6)
            rrect(surf, (730, y + 30, max(6, int(490 * clamp(f, 0, 1))), 16), mixc(RED, GREEN, f), None, 6)
            y += 70
        txt(surf, "TOTAL SCORE", (730, 510), 20, WHITE, True)
        txt(surf, "%.0f / 100" % m["score"], (1220, 496), 46, GREEN if ok else ORANGE, True, "topright")
        self.btn.draw(surf)


SOURCES = [
    ("Flight Earth to Mars: 203 days, 293 million miles; Earth laps Mars about every 26 months", "NASA JPL, Mars 2020 press kit", "https://www.jpl.nasa.gov/news/press_kits/mars_2020/landing/mission"),
    ("Perseverance launch date, landing at Jezero Crater (about 18 N)", "NASA JPL quick facts", "https://www.jpl.nasa.gov/news/press_kits/mars_2020/landing/quick_facts"),
    ("Landing site criteria: ice, sunlight, temperature, altitude, dust", "NASA Red Planet Dispatch blog", "https://blogs.nasa.gov/redplanetdispatch/2022/12"),
    ("Mars air 95.32% CO2, pressure 6.36 mbar, about 210 K", "NASA Mars Fact Sheet", "https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html"),
    ("4-crew ascent vehicle needs 6,978 kg CH4 and 22,728 kg O2; 0.61 kg/h CH4 over 480 days", "NASA Glenn, Kleinhenz and Paz, AIAA 2017-0423", "https://sciences.ucf.edu/class/wp-content/uploads/sites/23/2017/02/An-ISRU-propellant-production-system-for-a-fully-fueled-Mars-Ascent-Vehicle-AIAA-2017-0423.pdf"),
    ("Mars Ascent Vehicle crew capacity of 4 (methane element)", "NASA NTRS 20170004427", "https://ntrs.nasa.gov/api/citations/20170004427/downloads/20170004427.pdf"),
    ("Cargo pre-deployed, nuclear reactor powers ISRU, crew arrives later (DRA 5.0)", "NASA NTRS 20100028285", "https://ntrs.nasa.gov/api/citations/20100028285/downloads/20100028285.pdf"),
    ("Solar vs fission for Mars ISRU; dust storm outage up to 120 sols", "NASA NTRS 20160011275, Rucker", "https://ntrs.nasa.gov/api/citations/20160011275/downloads/20160011275.pdf"),
    ("Fission Surface Power: 40 kWe, 6,000 kg mass limit", "NASA NTRS 20220014952", "https://ntrs.nasa.gov/api/citations/20220014952/downloads/Tofil%20ASCEND%20Oct%202022%20Rev%20C.pdf"),
    ("MOXIE made oxygen from Mars CO2: 122 g total, 12 g/h at best", "NASA", "https://www.nasa.gov/missions/mars-2020-perseverance/nasas-oxygen-generating-experiment-moxie-completes-mars-mission/"),
    ("Global dust storm of 2018 and its effect on solar power", "NASA", "https://www.nasa.gov/missions/martian-dust-storm-grows-global-curiosity-captures-photos-of-thickening-haze/"),
    ("Crew water: about 1 gallon per astronaut per day, 98% recovered", "NASA ISS water recovery", "https://www.nasa.gov/missions/station/iss-research/nasa-achieves-water-recovery-milestone-on-international-space-station"),
]
SRC_NOTE = "Game estimates, not NASA numbers: solar field size, costs, lander classes, plant masses, storm odds, reaction kinetics, O2 make-up energy."


def draw_sources(surf):
    glass(surf, (0, 0, W, H), (0, 0, 0), 190, 0)
    box = pygame.Rect(40, 30, W - 80, H - 60)
    rrect(surf, box, (10, 16, 36), CYAN, 14, 2)
    txt(surf, "NASA DATA SOURCES   (press S or click to close)", (box.x + 20, box.y + 12), 22, CYAN, True)
    y = box.y + 50
    for fact, who, url in SOURCES:
        y = para(surf, fact, (box.x + 20, y), 15, WHITE, box.w - 40, True, 2)
        txt(surf, who + "  -  " + url, (box.x + 20, y), 12, (140, 200, 255))
        y += 22
    para(surf, SRC_NOTE, (box.x + 20, y + 4), 14, (255, 200, 150), box.w - 40, False, 3)


class Game:
    def __init__(self):
        pygame.init()
        try:
            self.screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
        except Exception:
            self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Blue to Red - Mars ISRU Mission")
        self.clock = pygame.time.Clock()
        self.sources = False
        self.reset_state()
        self.scenes = {
            "control": ControlScene(self), "launch": LaunchScene(self), "site": SiteScene(self),
            "explain": ExplainScene(self), "choose": ChooseScene(self), "reactor": ReactorScene(self),
            "sim": SimScene(self), "plan": PlanScene(self), "result": ResultScene(self),
        }
        self.go("control")

    def reset_state(self):
        self.site = None
        self.reactor = None
        self.cfg = None
        self.sim = None
        self.result = None
        self.plan = dict(vehicle="medium", days=480, h2=2400.0, target=7200.0)

    def go(self, name):
        self.scene = self.scenes[name]
        self.scene.enter()

    def run(self):
        tab = pygame.Rect(W - 150, 2, 144, 20)
        while True:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                    pygame.quit()
                    sys.exit()
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_F11:
                    pygame.display.toggle_fullscreen()
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_s:
                    self.sources = not self.sources
                    continue
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and (self.sources or tab.collidepoint(ev.pos)):
                    self.sources = not self.sources
                    continue
                if not self.sources:
                    self.scene.event(ev)
            if not self.sources:
                self.scene.update(dt)
            self.scene.draw(self.screen)
            rrect(self.screen, tab, (30, 90, 160), WHITE, 6, 1)
            txt(self.screen, "SOURCES (S)", tab.center, 13, WHITE, True, "center")
            if self.sources:
                draw_sources(self.screen)
            pygame.display.flip()


def main():
    Game().run()


if __name__ == "__main__":
    main()
