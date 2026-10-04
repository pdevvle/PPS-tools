#!/usr/bin/env python3
"""Cut a window of ground out of the baked New River block into data/base/ranch_site.json.

A base is a 140 m square that can be founded anywhere on baked ground; the prototype page carries one window
(760 x 500 m, four sectors) that holds both suggested base points, so a base can be founded anywhere inside it.
The cut holds heights on the 4 m grid, the 2 m movement grid (kind and speed) and the features the page draws.
Derived from OpenStreetMap (ODbL); see ../osm/README.md.
"""
import base64, json, math, os, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
BLOCK = os.path.join(ROOT, 'mockups/streaming/block')
X0, Z0, W, D = 100, -100, 760, 500     # window in block metres (x east, z south)
SEC, HALF = 600, 1500
# suggested base points (block metres): the campaign's ranch lot (region sector 16,31) and the region `home` point (15,31)
PRESETS = [
    {'key': 'ranch', 'label': 'Ranch lot', 'centre': [720, 40], 'note': 'The campaign\'s home sector: a house, barn and shed south of West New River Road'},
    {'key': 'home', 'label': 'Region home point', 'centre': [236, 232], 'note': 'The region map\'s home point by the river: a cluster of small buildings'},
]

def sec_of(x, z):
    return int((x + HALF) // SEC), int((z + HALF) // SEC)
cache = {}
def sector(c, r):
    if (c, r) not in cache:
        d = json.load(open(os.path.join(BLOCK, f's_{c}_{r}.json')))
        d['_H'] = struct.unpack('<%dh' % (d['hn'] ** 2), base64.b64decode(d['H']))
        d['_K'] = base64.b64decode(d['nav']['kind']); d['_S'] = base64.b64decode(d['nav']['sp'])
        cache[(c, r)] = d
    return cache[(c, r)]

# heights: 4 m samples from X0-4 to X0+W+4 (one extra each side for shading), taken from the sector holding each sample
nx, nz = W // 4 + 3, D // 4 + 3
H = []
for j in range(nz):
    for i in range(nx):
        x, z = X0 - 4 + 4 * i, Z0 - 4 + 4 * j
        c, r = sec_of(min(x, X0 + W - 1), min(z, Z0 + D - 1)); s = sector(c, r)
        ii, jj = (x - (s['x0'] - 4)) // 4, (z - (s['z0'] - 4)) // 4
        H.append(s['_H'][jj * s['hn'] + ii])
# movement grid: 2 m cells
mx, mz = W // 2, D // 2
K, S = bytearray(mx * mz), bytearray(mx * mz)
for j in range(mz):
    for i in range(mx):
        x, z = X0 + 2 * i, Z0 + 2 * j
        c, r = sec_of(x, z); s = sector(c, r); n = s['nav']['n']
        k = ((z - s['z0']) // 2) * n + (x - s['x0']) // 2
        K[j * mx + i] = s['_K'][k]; S[j * mx + i] = s['_S'][k]

def near(pts, pad=0):
    return any(X0 - pad <= x <= X0 + W + pad and Z0 - pad <= z <= Z0 + D + pad for x, z in pts)
secs = {sec_of(x, z) for x in range(X0, X0 + W, 100) for z in range(Z0, Z0 + D, 100)}
feat = {k: [] for k in ('buildings', 'walls', 'plants', 'roads', 'water', 'beds', 'areas')}
seen_roads, seen_water = set(), set()
for c, r in sorted(secs):
    s = sector(c, r)
    for b in s['buildings']:
        if near(b['pts']): feat['buildings'].append({'pts': b['pts'], 'house': bool(b.get('house'))})
    feat['walls'] += [w for w in s['walls'] if near([w[:2], w[2:4]])]
    feat['plants'] += [p for p in s['plants'] if X0 <= p[1] <= X0 + W and Z0 <= p[3] <= Z0 + D]
    for rd in s['roads']:   # sectors carry clipped copies: keep each piece once
        key = json.dumps(rd['pts'][:2])
        if near(rd['pts'], 30) and key not in seen_roads: seen_roads.add(key); feat['roads'].append(rd)
    for w in s['water']:
        key = json.dumps(w['pts'][:2])
        if near(w['pts'], 30) and key not in seen_water: seen_water.add(key); feat['water'].append(w)
    feat['beds'] += [b for b in s['beds'] if near(b, 30)]
    feat['areas'] += [a for a in s['areas'] if near(a['pts'], 30)]
# a building cut by a sector edge appears in both sectors: keep one
uniq = {}
for b in feat['buildings']:
    c = (round(sum(p[0] for p in b['pts']) / len(b['pts']), 1), round(sum(p[1] for p in b['pts']) / len(b['pts']), 1))
    uniq.setdefault(c, b)
feat['buildings'] = list(uniq.values())

site = {'name': 'newriver-bases', 'x0': X0, 'z0': Z0, 'w': W, 'd': D, 'baseSize': 140, 'presets': PRESETS,
        'hnx': nx, 'hnz': nz, 'H': base64.b64encode(struct.pack('<%dh' % len(H), *H)).decode(),
        'nav': {'nx': mx, 'nz': mz, 'step': 2, 'kind': base64.b64encode(bytes(K)).decode(), 'sp': base64.b64encode(bytes(S)).decode()},
        **feat, 'credit': '© OpenStreetMap contributors, ODbL. Elevation: Terrain Tiles on AWS.'}
out = os.path.join(ROOT, 'data/base/ranch_site.json')
json.dump(site, open(out, 'w'), separators=(',', ':'))
print('wrote', os.path.relpath(out, ROOT), os.path.getsize(out), 'bytes;', len(feat['buildings']), 'buildings,', len(feat['plants']), 'plants,', len(feat['roads']), 'roads')
