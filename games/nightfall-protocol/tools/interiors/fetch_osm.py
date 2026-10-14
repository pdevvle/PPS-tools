#!/usr/bin/env python3
"""Fetch buildings that sit outside the baked sector files straight from the OSM API
and cache them (projected to the Anthem sector frame) in osm_extra.json.

The public Overpass servers were unreachable from the build container, so this uses
api.openstreetmap.org/api/0.6/map, which serves small boxes. Data (c) OpenStreetMap
contributors, ODbL.
"""
import json, math, os, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# Anthem sector frame (tools/osm/prep.py: bbox 33.8628,-112.14,33.8682,-112.1335)
LAT0, LON0 = (33.8628 + 33.8682) / 2, (-112.14 + -112.1335) / 2
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110574
P = lambda la, lo: [round((lo - LON0) * KX, 1), round(-(la - LAT0) * KY, 1)]

WANT = [
    # (way id, bbox to fetch around it, note)
    (1092428601, (-112.1440, 33.8640, -112.1385, 33.8690), '42015 North Venture Drive: the office block west of the Safeway strip, across the wash'),
]

out = []
for wid, bb, note in WANT:
    url = 'https://www.openstreetmap.org/api/0.6/map.json?bbox=%f,%f,%f,%f' % bb
    d = json.load(urllib.request.urlopen(url, timeout=90))
    els = d['elements']
    nodes = {e['id']: e for e in els if e['type'] == 'node'}
    way = next(e for e in els if e['type'] == 'way' and e['id'] == wid)
    pts = [P(nodes[n]['lat'], nodes[n]['lon']) for n in way['nodes'] if n in nodes]
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    roads, water = [], []
    for e in els:
        t = e.get('tags', {})
        if e['type'] != 'way' or not ('highway' in t or 'waterway' in t):
            continue
        rp = [P(nodes[n]['lat'], nodes[n]['lon']) for n in e['nodes'] if n in nodes]
        if len(rp) < 2:
            continue
        if 'highway' in t:
            roads.append({'cls': t['highway'], 'name': t.get('name', ''), 'pts': rp})
        else:
            water.append({'kind': t['waterway'], 'pts': rp})
    out.append({'way': wid, 'note': note, 'tags': way.get('tags', {}), 'pts': pts, 'roads': roads, 'water': water})
    print(wid, len(pts), 'points', len(roads), 'roads', len(water), 'waterways')

json.dump(out, open(os.path.join(HERE, 'osm_extra.json'), 'w'), separators=(',', ':'))
