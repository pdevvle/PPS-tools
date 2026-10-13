// Convert raw OSM XML into the engine's compact city file, adjusted to December 1989.
// usage: node tools/osm-1989.mjs
// Input:  data/osm/pantelimon.osm (+ bbox.json)   Output: public/data/city.json
// Map data © OpenStreetMap contributors, available under the ODbL.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..');
const xml = fs.readFileSync(path.join(root, 'data/osm/pantelimon.osm'), 'utf8');
const bbox = JSON.parse(fs.readFileSync(path.join(root, 'data/osm/bbox.json'), 'utf8'));

// ---------------------------------------------------------------- parse
const unesc = (s) => s.replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const tagsOf = (body) => { const t = {}; for (const m of body.matchAll(/<tag k="([^"]*)" v="([^"]*)"\s*\/>/g)) t[unesc(m[1])] = unesc(m[2]); return t; };
const nodes = new Map();
for (const m of xml.matchAll(/<node id="(\d+)"([^>]*?)(\/>|>([\s\S]*?)<\/node>)/g)) {
  const lat = +/lat="([-\d.]+)"/.exec(m[2])[1], lon = +/lon="([-\d.]+)"/.exec(m[2])[1];
  nodes.set(m[1], { lat, lon, tags: m[4] ? tagsOf(m[4]) : {} });
}
const ways = new Map();
for (const m of xml.matchAll(/<way id="(\d+)"[^>]*>([\s\S]*?)<\/way>/g)) {
  ways.set(m[1], { id: m[1], refs: [...m[2].matchAll(/<nd ref="(\d+)"/g)].map((r) => r[1]), tags: tagsOf(m[2]) });
}
const relations = [];
for (const m of xml.matchAll(/<relation id="(\d+)"[^>]*>([\s\S]*?)<\/relation>/g)) {
  relations.push({ id: m[1], members: [...m[2].matchAll(/<member type="(\w+)" ref="(\d+)" role="([^"]*)"/g)].map((r) => ({ type: r[1], ref: r[2], role: r[3] })), tags: tagsOf(m[2]) });
}

// ---------------------------------------------------------------- projection: metres on a local tangent plane, x east, z south
const lat0 = (bbox.minLat + bbox.maxLat) / 2, lon0 = (bbox.minLon + bbox.maxLon) / 2;
const kx = Math.cos((lat0 * Math.PI) / 180) * 111320, kz = 110574;
const P = (n) => [+((n.lon - lon0) * kx).toFixed(2), +(-(n.lat - lat0) * kz).toFixed(2)];
const B = { x0: (bbox.minLon - lon0) * kx, x1: (bbox.maxLon - lon0) * kx, z0: -(bbox.maxLat - lat0) * kz, z1: -(bbox.minLat - lat0) * kz };
const inside = ([x, z], m = 0) => x > B.x0 - m && x < B.x1 + m && z > B.z0 - m && z < B.z1 + m;
const wayPts = (w) => w.refs.map((r) => nodes.get(r)).filter(Boolean).map(P);
const area = (poly) => { let a = 0; for (let i = 0; i < poly.length; i++) { const [x0, z0] = poly[i], [x1, z1] = poly[(i + 1) % poly.length]; a += x0 * z1 - x1 * z0; } return a / 2; };
const centroid = (poly) => { let x = 0, z = 0; for (const p of poly) { x += p[0]; z += p[1]; } return [x / poly.length, z / poly.length]; };

// ---------------------------------------------------------------- what wasn't there in December 1989
const MODERN_NAMES = /mega image|lidl|kaufland|carrefour|profi|penny|shop&go|superbet|mcdonald|kfc|petrom|omv|rompetrol|mol\b|lukoil|dedeman|altex|flanco|bcr|raiffeisen|\bing\b|brd|banca transilvania|vodafone|orange|telekom|catena|sensiblu|dr\.? ?max|la doi pa|auchan|selgros|metro\b|starbucks|5 to go|paco|unicredit|libra|garanti|alpha bank|otp|cec bank|fan courier|sameday|emag|easybox|lukoil|socar|gazprom|benzina/i;
const removed = {};
const drop = (why) => { removed[why] = (removed[why] || 0) + 1; return false; };
function era1989(tags, poly) {
  const sd = parseInt(tags.start_date || tags['building:start_date'] || tags.construction_date || '', 10);
  if (sd >= 1990) return drop('built after 1989 (start_date)');
  if (tags.name && MODERN_NAMES.test(tags.name)) return drop('post-1989 brand');
  if (tags.brand || tags['brand:wikidata']) return drop('post-1989 brand');
  const b = tags.building;
  if (b === 'construction' || tags.construction) return drop('under construction');
  if (b === 'roof') return drop('canopy (petrol station or similar)');
  const a = poly ? Math.abs(area(poly)) : 0;
  if ((b === 'retail' || b === 'supermarket') && a > 900) return drop('big-box retail');
  if (b === 'commercial' && a > 2500) return drop('large commercial building');
  if (b === 'office' && +(tags['building:levels'] || 0) > 6) return drop('office tower');
  return true;
}

// ---------------------------------------------------------------- buildings
const entranceOf = new Map(); // node id -> entrance info
for (const [id, n] of nodes) if (n.tags.entrance || n.tags.door) entranceOf.set(id, { name: n.tags.name || n.tags.ref || n.tags['addr:unit'] || '', kind: n.tags.entrance || 'door' });
const buildings = [];
const used = new Set();
function addBuilding(id, osm, tags, poly, entranceIds) {
  if (poly.length < 4) return;
  if (poly[0][0] === poly[poly.length - 1][0] && poly[0][1] === poly[poly.length - 1][1]) poly = poly.slice(0, -1);
  if (!inside(centroid(poly))) return;
  if (!era1989(tags, poly)) return;
  if (area(poly) < 0) poly.reverse(); // counter-clockwise in x/z (z south) means clockwise on the map; keep one convention
  const a = Math.abs(area(poly));
  if (a < 8) return drop('tiny shed');
  const b = tags.building;
  let levels = parseInt(tags['building:levels'] || '', 10);
  let kind = 'house';
  if (b === 'apartments' || b === 'residential') kind = 'block';
  else if (b === 'industrial' || b === 'warehouse' || b === 'factory') kind = 'industrial';
  else if (b === 'school' || b === 'kindergarten' || b === 'university') kind = 'school';
  else if (b === 'church' || b === 'chapel' || tags.amenity === 'place_of_worship') kind = 'church';
  else if (b === 'garage' || b === 'garages') kind = 'garage';
  else if (b === 'retail' || b === 'commercial' || b === 'kiosk' || tags.shop) kind = 'shop';
  else if (b === 'service' || b === 'transformer_tower' || tags.power) kind = 'service';
  else if (b === 'yes' && (levels >= 4 || a > 350)) kind = 'block';
  if (!levels || Number.isNaN(levels)) levels = kind === 'block' ? (a > 900 ? 11 : 5) : kind === 'house' ? 1 : kind === 'school' ? 3 : kind === 'shop' ? 1 : kind === 'industrial' ? 2 : 1;
  // 1989: blocks were P+4 or P+8 / P+10; anything taller here is a later addition or a mistag
  if (kind === 'block') levels = levels <= 5 ? Math.max(4, levels) : levels <= 9 ? 9 : 11;
  if (kind === 'house' && levels > 2) levels = 2;
  const ents = [];
  for (const nid of entranceIds) { const e = entranceOf.get(nid); if (e) { const n = nodes.get(nid); ents.push({ p: P(n), name: e.name, kind: e.kind }); } }
  buildings.push({ id, osm, kind, levels, name: tags.name || tags['addr:housename'] || '', street: tags['addr:street'] || '', number: tags['addr:housenumber'] || '', poly, entrances: ents });
}
for (const r of relations) {
  if (r.tags.type !== 'multipolygon' || !r.tags.building) continue;
  const outer = r.members.find((m) => m.type === 'way' && m.role === 'outer');
  const w = outer && ways.get(outer.ref);
  if (!w) continue;
  used.add(w.id);
  addBuilding('r' + r.id, 'relation/' + r.id, r.tags, wayPts(w), w.refs);
}
for (const w of ways.values()) if (w.tags.building && !used.has(w.id)) addBuilding('w' + w.id, 'way/' + w.id, w.tags, wayPts(w), w.refs);

// ---------------------------------------------------------------- roads, tram lines, areas, trees
const ROAD_W = { primary: 7.2, secondary: 7, tertiary: 6.5, residential: 6, living_street: 5, unclassified: 5.5, service: 4, pedestrian: 5, footway: 1.8, path: 1.4, steps: 1.6 };
const roads = [], trams = [], areas = [], trees = [];
for (const w of ways.values()) {
  const t = w.tags;
  const pts = wayPts(w);
  if (pts.length < 2 || !pts.some((p) => inside(p, 60))) continue;
  if (t.highway && ROAD_W[t.highway] !== undefined) {
    if (t.highway === 'construction' || t.construction) { drop('road under construction'); continue; }
    if (/extindere/i.test(t.name || '')) { drop('later extension'); continue; }
    const lanes = parseInt(t.lanes || '', 10);
    let width = parseFloat(t.width || '') || (lanes ? lanes * 3.3 : ROAD_W[t.highway]);
    if (t.highway === 'primary' && t.oneway !== 'yes' && !lanes) width = 14;
    if (t.highway === 'primary' && t.oneway === 'yes' && !lanes) width = 9.9;
    // side streets of the old house quarters were cobbled or unpaved in 1989
    let surface = 'asphalt';
    if (/sett|cobble|paving_stones/.test(t.surface || '')) surface = 'cobble';
    else if (/unpaved|dirt|gravel|ground/.test(t.surface || '')) surface = 'dirt';
    else if ((t.highway === 'residential' || t.highway === 'living_street') && !t.surface) surface = 'cobble';
    const kind = ['footway', 'path', 'steps', 'pedestrian'].includes(t.highway) ? 'path' : t.highway;
    roads.push({ id: 'w' + w.id, kind, name: t.name || '', width: +width.toFixed(1), oneway: t.oneway === 'yes', surface, layer: +(t.layer || 0), bridge: t.bridge === 'yes', pts });
  } else if (t.railway === 'tram') {
    if (/extindere/i.test(t.name || '') || t.construction) { drop('later tram extension'); continue; }
    trams.push({ id: 'w' + w.id, pts });
  } else if (t.landuse === 'grass' || t.leisure === 'park' || t.leisure === 'garden' || t.leisure === 'playground' || t.leisure === 'pitch' || t.amenity === 'parking' || t.landuse === 'forest' || t.natural === 'scrub') {
    if (!era1989(t, null)) continue;
    const kind = t.leisure === 'playground' ? 'playground' : t.leisure === 'pitch' ? 'pitch' : t.amenity === 'parking' ? 'parking' : 'grass';
    areas.push({ id: 'w' + w.id, kind, poly: pts.slice(0, -1) });
  }
}
for (const n of nodes.values()) if (n.tags.natural === 'tree') { const p = P(n); if (inside(p)) trees.push(p); }

const city = {
  version: 1,
  name: 'Pantelimon, Bucharest',
  date: '1989-12-22',
  attribution: 'Map data © OpenStreetMap contributors (ODbL), adjusted to December 1989',
  origin: { lat: lat0, lon: lon0 },
  bounds: { x0: +B.x0.toFixed(1), z0: +B.z0.toFixed(1), x1: +B.x1.toFixed(1), z1: +B.z1.toFixed(1) },
  roads, trams, buildings, areas, trees,
  removed,
};
const outPath = path.join(root, 'public/data/city.json');
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(city));
const kinds = {};
for (const b of buildings) kinds[b.kind] = (kinds[b.kind] || 0) + 1;
console.log(`buildings ${buildings.length}`, kinds, `roads ${roads.length} trams ${trams.length} areas ${areas.length} trees ${trees.length}`);
console.log('removed for 1989:', removed);
console.log('bounds', city.bounds, 'size', (fs.statSync(outPath).size / 1024).toFixed(0), 'KB');
