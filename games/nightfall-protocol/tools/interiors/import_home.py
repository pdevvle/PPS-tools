#!/usr/bin/env python3
"""Import a real home as a hand-crafted interior: step 1, the site.

    python3 import_home.py homes/48918-n-fig-springs.layout.json

The layout file is written by hand from the listing (facts, photos, floor plan if there is
one). It names the house's location and its OSM building way. This script fetches what the map knows
about the spot and caches it next to the layout as <slug>.site.json:
  - the footprint (OSM way, usually traced from aerial imagery),
  - drivable ways within 120 m,
  - real ground: Terrarium elevation tiles on a 4 m grid, 40 m round the footprint.
extract.py then adds the site to the mockup with the layout attached.

Data: (c) OpenStreetMap contributors, ODbL. Elevation: Mapzen Terrain Tiles on AWS.
Listing photos are only looked at for reference; they are not copied into the repo.
"""
import json, math, os, sys, subprocess, zlib, struct

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'homes', 'cache')

def png_rgb(path):
    data = open(path, 'rb').read(); pos = 8; chunks = []; w = h = ct = 0
    while pos < len(data):
        ln = struct.unpack('>I', data[pos:pos + 4])[0]; typ = data[pos + 4:pos + 8]; body = data[pos + 8:pos + 8 + ln]; pos += 12 + ln
        if typ == b'IHDR': w, h, _, ct = struct.unpack('>IIBB', body[:10])
        elif typ == b'IDAT': chunks.append(body)
        elif typ == b'IEND': break
    raw = zlib.decompress(b''.join(chunks)); bpp = {2: 3, 6: 4}[ct]; stride = w * bpp
    out = bytearray(h * stride); prev = bytearray(stride); i = 0
    for y in range(h):
        f = raw[i]; i += 1; line = bytearray(raw[i:i + stride]); i += stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0; b = prev[x]; c = prev[x - bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out[y * stride:(y + 1) * stride] = line; prev = line
    return bpp, out

tiles = {}
def elev(lat, lon, Z=15):
    n = 2 ** Z; fx = (lon + 180) / 360 * n; fy = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    x, y = int(fx), int(fy)
    if (x, y) not in tiles:
        f = os.path.join(CACHE, f't{Z}_{x}_{y}.png')
        if not os.path.exists(f):
            subprocess.run(['curl', '-sS', '-m', '40', '-o', f, f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png'], check=True)
        tiles[(x, y)] = png_rgb(f)
    bpp, px = tiles[(x, y)]; u = (fx - x) * 256; v = (fy - y) * 256
    def at(i, j):
        i = min(255, max(0, i)); j = min(255, max(0, j)); o = (j * 256 + i) * bpp
        return px[o] * 256 + px[o + 1] + px[o + 2] / 256 - 32768
    i, j = int(u - .5), int(v - .5); tx, ty = u - .5 - i, v - .5 - j
    return (at(i, j) * (1 - tx) + at(i + 1, j) * tx) * (1 - ty) + (at(i, j + 1) * (1 - tx) + at(i + 1, j + 1) * tx) * ty

def main(layout_path):
    L = json.load(open(layout_path)); src = L['source']; os.makedirs(CACHE, exist_ok=True)
    lat0, lon0 = src['lat'], src['lon']; kx = 111320 * math.cos(math.radians(lat0)); ky = 110574
    P = lambda la, lo: [(lo - lon0) * kx, -(la - lat0) * ky]           # x east, z south, metres
    d = 0.0015
    url = 'https://www.openstreetmap.org/api/0.6/map.json?bbox=%f,%f,%f,%f' % (lon0 - d, lat0 - d, lon0 + d, lat0 + d)
    f = os.path.join(CACHE, src['slug'] + '.osm.json')
    if not os.path.exists(f): subprocess.run(['curl', '-sS', '-m', '90', '-o', f, url], check=True)
    els = json.load(open(f))['elements']; nodes = {e['id']: e for e in els if e['type'] == 'node'}
    way = next(e for e in els if e['type'] == 'way' and e['id'] == src['osmWay'])
    pts = [P(nodes[n]['lat'], nodes[n]['lon']) for n in way['nodes'] if n in nodes]
    if pts[0] == pts[-1]: pts = pts[:-1]
    cx = sum(p[0] for p in pts) / len(pts); cz = sum(p[1] for p in pts) / len(pts)
    pts = [[round(x - cx, 2), round(z - cz, 2)] for x, z in pts]           # frame centred on the house
    rl = lambda la, lo: [round(v, 1) for v in (P(la, lo)[0] - cx, P(la, lo)[1] - cz)]
    roads = []
    for e in els:
        t = e.get('tags', {})
        if e['type'] != 'way' or 'highway' not in t: continue
        rp = [rl(nodes[n]['lat'], nodes[n]['lon']) for n in e['nodes'] if n in nodes]
        if len(rp) < 2 or min(math.hypot(*p) for p in rp) > 120: continue
        cls = t['highway']; drive = cls not in ('path', 'footway', 'track') or t.get('service') == 'driveway'
        roads.append({'cls': cls, 'name': t.get('name', ''), 'w': {'residential': 8, 'service': 4.5, 'track': 3}.get(cls, 5), 'drive': drive, 'pts': rp})
    # ground: 4 m grid, 40 m round the footprint, metres above the lowest sample
    R = 40; x0 = math.floor((min(p[0] for p in pts) - R) / 4) * 4; z0 = math.floor((min(p[1] for p in pts) - R) / 4) * 4
    nx = int((max(p[0] for p in pts) + R - x0) // 4) + 2; nz = int((max(p[1] for p in pts) + R - z0) // 4) + 2
    H = []
    for j in range(nz):
        for i in range(nx):
            x, z = x0 + i * 4 + cx, z0 + j * 4 + cz
            H.append(elev(lat0 - z / ky, lon0 + x / kx))
    lo = min(H)
    site = {'id': 'home/' + src['slug'], 'area': 'Imported homes', 'block': 'home', 'sector': [0, 0], 'index': src['slug'],
            'note': L['facts'].get('summary', ''), 'pts': pts, 'type': 'house', 'levels': None, 'height': None,
            'name': L['name'], 'loot': None, 'what': '', 'house': True, 'roads': roads, 'walls': [], 'centre': [0, 0],
            'terrain': {'x0': x0, 'z0': z0, 'step': 4, 'nx': nx, 'nz': nz, 'h': [round(v - lo, 2) for v in H]},
            'elevation': round(lo, 1), 'source': {'listing': src['url'], 'osmWay': src['osmWay'], 'footprint': way.get('tags', {}).get('source', 'OSM')}}
    out = os.path.join(os.path.dirname(layout_path), src['slug'] + '.site.json')
    json.dump(site, open(out, 'w'), separators=(',', ':'))
    print(out, len(pts), 'footprint points,', len(roads), 'roads, ground', round(max(H) - lo, 1), 'm of relief')

if __name__ == '__main__':
    main(sys.argv[1])
