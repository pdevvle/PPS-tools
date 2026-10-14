#!/usr/bin/env python3
"""Cut the test buildings for the interiors mockup out of the baked New River block
and the Anthem town centre sector.

Writes sites.json next to this file: each building's footprint, its identity
(block, sector, index), what the bake knows about it, plus the roads and yard
walls within 60 m so the generator can find the street and the yard.
Positions stay in block metres. Data: (c) OpenStreetMap contributors, ODbL.
"""
import json, math, os, base64, struct

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCK = os.path.join(HERE, '..', '..', 'mockups', 'streaming', 'block')

# (sector, building index, note)
PICKS = [
    ((2, 2), 0, 'Roadrunner: restaurant, 19-point footprint'),
    ((2, 2), 31, 'Ranch house, L-shaped, axis aligned'),
    ((2, 2), 14, 'Ranch house, L-shaped, turned about 45 degrees'),
    ((2, 2), 4, 'Lucky Mane Co.: small shop, plain rectangle'),
    # more houses, picked for spread: lot slope, size, and shape (a 4:1 box reads as a manufactured home)
    ((3, 0), 0, 'House on a hillside lot, about 2 m of fall across it'),
    ((3, 0), 1, 'Small house on a hillside lot'),
    ((3, 1), 3, 'Cabin-sized box, 81 m²'),
    ((3, 2), 43, 'Long narrow box, 4:1: single-wide shape'),
    ((3, 2), 52, 'Long narrow box, 4.4:1: single-wide shape'),
    ((4, 1), 1, 'Wide box, 2.7:1: double-wide shape'),
    ((3, 2), 11, 'Long rambling house, 3:1'),
    ((2, 2), 7, 'Large custom house, 12-point footprint'),
    ((3, 1), 26, 'Large house, 10-point footprint'),
    ((4, 1), 4, 'Irregular house, U-ish footprint'),
    ((3, 1), 14, 'Mid-size house, 12-point footprint'),
    ((3, 2), 56, 'Big plain box, 428 m²'),
    ((3, 1), 25, 'Plain box, 288 m²'),
]
PATCH = 36  # metres of terrain kept round each footprint

def block_heights(S):
    n = S['hn']; raw = base64.b64decode(S['H']); H = struct.unpack('<%dh' % (len(raw) // 2), raw)
    def h(x, z):
        fx = (x - S['x0'] + 4) / 4; fz = (z - S['z0'] + 4) / 4
        i = max(0, min(n - 2, int(math.floor(fx)))); j = max(0, min(n - 2, int(math.floor(fz)))); u = fx - i; v = fz - j
        g = lambda a, b: H[b * n + a] / 100
        return (g(i, j) * (1 - u) + g(i + 1, j) * u) * (1 - v) + (g(i, j + 1) * (1 - u) + g(i + 1, j + 1) * u) * v
    return h

def sector_heights(T):
    nx, nz, st = T['nx'], T['nz'], T['step']; hx, hz = (nx - 1) * st / 2, (nz - 1) * st / 2; H = T['h']
    def h(x, z):
        fx = (x + hx) / st; fz = (z + hz) / st
        i = max(0, min(nx - 2, int(math.floor(fx)))); j = max(0, min(nz - 2, int(math.floor(fz)))); u = fx - i; v = fz - j
        g = lambda a, b: H[b * nx + a]
        return (g(i, j) * (1 - u) + g(i + 1, j) * u) * (1 - v) + (g(i, j + 1) * (1 - u) + g(i + 1, j + 1) * u) * v
    return h

def patch(pts, h):
    """Heights on a 4 m grid round the footprint, in metres above the lowest sample."""
    x0 = math.floor((min(p[0] for p in pts) - PATCH) / 4) * 4; z0 = math.floor((min(p[1] for p in pts) - PATCH) / 4) * 4
    nx = int((max(p[0] for p in pts) + PATCH - x0) // 4) + 2; nz = int((max(p[1] for p in pts) + PATCH - z0) // 4) + 2
    H = [h(x0 + i * 4, z0 + j * 4) for j in range(nz) for i in range(nx)]; lo = min(H)
    return {'x0': x0, 'z0': z0, 'step': 4, 'nx': nx, 'nz': nz, 'h': [round(v - lo, 2) for v in H]}

REACH = 60

def seg_dist(p, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dz * dz or 1
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / L))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dz - p[1])

sites = []
for (c, r), i, note in PICKS:
    S = json.load(open(os.path.join(BLOCK, f's_{c}_{r}.json')))
    b = S['buildings'][i]
    pts = b['pts']
    terrain = patch(pts, block_heights(S))
    cx = sum(p[0] for p in pts) / len(pts)
    cz = sum(p[1] for p in pts) / len(pts)
    site = {'id': f'newriver/{c}_{r}/{i}', 'block': 'newriver', 'sector': [c, r], 'index': i, 'note': note,
            'pts': pts, 'type': b.get('type'), 'levels': b.get('levels'), 'height': b.get('height'),
            'name': b.get('name'), 'loot': b.get('loot'), 'what': b.get('what'), 'house': bool(b.get('house'))}
    # The bake keeps shop tags on a point of interest; copy it onto the building when it sits on it.
    for p in S['pois']:
        if math.hypot(p['p'][0] - cx, p['p'][1] - cz) < 20:
            site['loot'] = site['loot'] or p.get('kind')
            site['what'] = site['what'] or p.get('what')
    roads = []
    for rd in S['roads']:
        if not rd.get('drive') and rd['cls'] not in ('pedestrian', 'footway'):
            continue
        if min(seg_dist((cx, cz), rd['pts'][k], rd['pts'][k + 1]) for k in range(len(rd['pts']) - 1)) < REACH + 40:
            roads.append({'cls': rd['cls'], 'name': rd.get('name') or '', 'w': rd['w'], 'drive': rd.get('drive', False),
                          'pts': [[round(x, 1), round(z, 1)] for x, z in rd['pts']]})
    walls = [w for w in S['walls'] if math.hypot((w[0] + w[2]) / 2 - cx, (w[1] + w[3]) / 2 - cz) < REACH]
    site['roads'] = roads
    site['walls'] = walls
    site['centre'] = [round(cx, 2), round(cz, 2)]
    site['terrain'] = terrain
    sites.append(site)

for s in sites:
    s['area'] = 'New River'

# ---- Anthem town centre (data/sectors/sector_anthem.json): strip malls hold several tenants,
# so every point of interest inside a footprint is kept as a tenant.
ANTHEM = os.path.join(HERE, '..', '..', 'data', 'sectors', 'sector_anthem.json')
A_PICKS = [
    (15, 'Safeway strip: a supermarket anchor and eight smaller tenants'),
    (3, 'Strip of six: jeweller, Subway, two restaurants, Baskin-Robbins, a vet'),
    (5, "McDonald's"),
    (9, 'Starbucks'),
    (17, 'MidFirst Bank'),
    (10, 'Work Hard Play Hard Marketing: offices'),
    (18, 'Ace Hardware'),
    (61, 'Grease Monkey: auto service'),
    (22, 'Circle K fuel canopy'),
    (8, 'Circle K store'),
    (4, 'Legends Bar and Grill, KOBE Hotpot and Ramen'),
    (23, "Supercuts, Filiberto's Mexican Restaurant"),
]
ROAD_W = {'secondary': 13, 'tertiary': 10, 'residential': 8, 'secondary_link': 7, 'tertiary_link': 7, 'service': 5, 'path': 2, 'footway': 2}

def pip(x, y, P):
    c = False; j = len(P) - 1
    for i in range(len(P)):
        xi, yi = P[i]; xj, yj = P[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c

A = json.load(open(ANTHEM))
AH = sector_heights(A['terrain'])
for i, note in A_PICKS:
    b = A['buildings'][i]
    pts = b['pts']
    cx = sum(p[0] for p in pts) / len(pts)
    cz = sum(p[1] for p in pts) / len(pts)
    tenants = [{'p': p['p'], 'what': p['what'], 'loot': p['kind'], 'name': p['name']} for p in A['pois'] if pip(p['p'][0], p['p'][1], pts)]
    site = {'id': f'anthem/centre/{i}', 'area': 'Anthem', 'block': 'anthem', 'sector': [0, 0], 'index': i, 'note': note,
            'pts': pts, 'type': b.get('type'), 'levels': b.get('levels'), 'height': b.get('height'),
            'name': b.get('name'), 'loot': b.get('loot'), 'what': b.get('what'), 'house': False, 'tenants': tenants}
    if len(tenants) == 1:
        t = tenants[0]
        site['name'] = site['name'] or t['name']; site['what'] = site['what'] or t['what']; site['loot'] = site['loot'] or t['loot']
    roads = []
    for rd in A['roads']:
        if min(seg_dist((cx, cz), rd['pts'][k], rd['pts'][k + 1]) for k in range(len(rd['pts']) - 1)) < REACH + 40:
            roads.append({'cls': rd['cls'], 'name': rd.get('name') or '', 'w': ROAD_W.get(rd['cls'], 6),
                          'drive': rd['cls'] not in ('path', 'footway'), 'pts': [[round(x, 1), round(z, 1)] for x, z in rd['pts']]})
    walls = []
    for w in A['barriers']:
        for k in range(len(w['pts']) - 1):
            a, c = w['pts'][k], w['pts'][k + 1]
            if math.hypot((a[0] + c[0]) / 2 - cx, (a[1] + c[1]) / 2 - cz) < REACH:
                walls.append([a[0], a[1], c[0], c[1], 1.8, .2, 0])
    site['roads'] = roads; site['walls'] = walls; site['centre'] = [round(cx, 2), round(cz, 2)]
    site['terrain'] = patch(pts, AH)
    sites.append(site)

# ---- Buildings outside the baked sector, cached from the OSM API by fetch_osm.py.
# 42015 North Venture Drive is tagged building=house in OSM with no level count; it is a
# multi-storey office block; Anthem's office stock is two-storey multi-tenant Class B, so it is built as two (assumed).
EXTRA = os.path.join(HERE, 'osm_extra.json')
if os.path.exists(EXTRA):
    for x in json.load(open(EXTRA)):
        pts = x['pts']
        cx = sum(p[0] for p in pts) / len(pts)
        cz = sum(p[1] for p in pts) / len(pts)
        roads = []
        for rd in x['roads']:
            if min(seg_dist((cx, cz), rd['pts'][k], rd['pts'][k + 1]) for k in range(len(rd['pts']) - 1)) < REACH + 60:
                roads.append({'cls': rd['cls'], 'name': rd['name'], 'w': ROAD_W.get(rd['cls'], 6),
                              'drive': rd['cls'] not in ('path', 'footway'), 'pts': rd['pts']})
        t = x['tags']
        sites.append({'id': f"anthem/osm/{x['way']}", 'area': 'Anthem', 'block': 'anthem', 'sector': [0, 0], 'index': x['way'], 'note': x['note'] + ' (tagged building=' + t.get('building', '?') + ' in OSM, built here as offices)',
                      'pts': pts, 'type': 'commercial', 'levels': 2, 'levelsAssumed': True, 'height': None,
                      'name': t.get('name') or (t.get('addr:housenumber', '') + ' N Venture Dr offices'), 'loot': None, 'what': '', 'house': False,
                      'tenants': [], 'roads': roads, 'walls': [], 'water': x['water'], 'centre': [round(cx, 2), round(cz, 2)], 'terrain': patch(pts, AH)})

# ---- Imported homes (import_home.py): a hand-made layout from a listing, laid on the real footprint and ground.
import glob
for lp in sorted(glob.glob(os.path.join(HERE, 'homes', '*.layout.json'))):
    L = json.load(open(lp)); sp = lp.replace('.layout.json', '.site.json')
    if not os.path.exists(sp):
        print('  (run import_home.py on', os.path.basename(lp), 'first)'); continue
    site = json.load(open(sp)); site['layout'] = {k: L[k] for k in ('design', 'floors', 'facts') if k in L}; site['layout']['source'] = L['source']['url']
    sites.append(site)

out = os.path.join(HERE, 'sites.json')
json.dump(sites, open(out, 'w'), separators=(',', ':'))
print(out, os.path.getsize(out), 'bytes')
for s in sites: print(' ', s['id'], s['name'], s['what'], len(s.get('tenants') or []), 'tenants', len(s['roads']), 'roads')
