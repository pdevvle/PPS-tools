#!/usr/bin/env python3
"""Cut the ranch's ground out of the baked New River block into data/base/ranch_site.json.

The window is 200 x 200 m around the buildable area, all inside block sector s_3_2: heights on the 4 m grid,
the 2 m movement grid (kind and speed), and the features the page draws. Derived from OpenStreetMap
(ODbL); see ../osm/README.md.
"""
import base64, json, os, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
SEC = 's_3_2'
X0, Z0, SIZE = 620, -60, 200          # window in block metres (x east, z south)
AREA = [650, -30, 790, 110]           # buildable area: x0, z0, x1, z1
CLAIMED = {'house': (713, 14), 'barn': (694, 23), 'shed': (710, 53), 'outbuilding_w': (653, 103), 'outbuilding_e': (681, 106)}

d = json.load(open(os.path.join(ROOT, 'mockups/streaming/block', SEC + '.json')))
sx0, sz0, hn = d['x0'], d['z0'], d['hn']
H = struct.unpack('<%dh' % (hn * hn), base64.b64decode(d['H']))
# heights: sector samples start 4 m before x0; take the window plus one sample each side
step = 4; n = SIZE // step + 3
oi, oj = (X0 - 4 - (sx0 - 4)) // step, (Z0 - 4 - (sz0 - 4)) // step
Hs = [H[(oj + j) * hn + oi + i] for j in range(n) for i in range(n)]
# movement grid: 2 m cells
ns, NS = d['nav']['n'], 2
kind = base64.b64decode(d['nav']['kind']); sp = base64.b64decode(d['nav']['sp'])
m = SIZE // NS; ci, cj = (X0 - sx0) // NS, (Z0 - sz0) // NS
K = bytes(kind[(cj + j) * ns + ci + i] for j in range(m) for i in range(m))
S = bytes(sp[(cj + j) * ns + ci + i] for j in range(m) for i in range(m))

def inside(pts, pad=0):
    return any(X0 - pad <= x <= X0 + SIZE + pad and Z0 - pad <= z <= Z0 + SIZE + pad for x, z in pts)
def centroid(pts):
    return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]
buildings = []
for b in d['buildings']:
    if not inside(b['pts']): continue
    c = centroid(b['pts'])
    claim = next((k for k, (x, z) in CLAIMED.items() if abs(c[0] - x) < 6 and abs(c[1] - z) < 6), None)
    buildings.append({'pts': b['pts'], 'house': bool(b.get('house')), 'claim': claim})
site = {
    'name': 'ranch', 'sector': SEC, 'x0': X0, 'z0': Z0, 'size': SIZE, 'area': AREA,
    'hn': n, 'H': base64.b64encode(struct.pack('<%dh' % len(Hs), *Hs)).decode(),
    'nav': {'n': m, 'step': NS, 'kind': base64.b64encode(K).decode(), 'sp': base64.b64encode(S).decode()},
    'buildings': buildings,
    'walls': [w for w in d['walls'] if inside([w[:2], w[2:4]])],
    'plants': [p for p in d['plants'] if X0 <= p[1] <= X0 + SIZE and Z0 <= p[3] <= Z0 + SIZE],
    'roads': [r for r in d['roads'] if inside(r['pts'], 30)],
    'water': [w for w in d['water'] if inside(w['pts'], 30)],
    'beds': [b for b in d['beds'] if inside(b, 30)],
    'areas': [a for a in d['areas'] if inside(a['pts'], 30)],
    'credit': '© OpenStreetMap contributors, ODbL. Elevation: Terrain Tiles on AWS.',
}
out = os.path.join(ROOT, 'data/base/ranch_site.json')
json.dump(site, open(out, 'w'), separators=(',', ':'))
print('wrote', out, os.path.getsize(out), 'bytes;', len(buildings), 'buildings,', len(site['plants']), 'plants')
print('claimed:', [b['claim'] for b in buildings if b['claim']])
