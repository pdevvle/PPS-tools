// Download raw OpenStreetMap data for the slice from the main OSM API.
// usage: node tools/osm-fetch.mjs [minLon minLat maxLon maxLat]
// Map data © OpenStreetMap contributors, available under the ODbL.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const bbox = process.argv.length >= 6 ? process.argv.slice(2, 6).map(Number) : [26.1405, 44.4392, 26.1565, 44.4478];
const url = `https://api.openstreetmap.org/api/0.6/map?bbox=${bbox.join(',')}`;
const out = path.join(here, '..', 'data', 'osm', 'pantelimon.osm');
console.log('fetching', url);
const res = await fetch(url, { headers: { 'User-Agent': 'pantelimon-1989-engine (game prototype)' } });
if (!res.ok) { console.error('OSM API error', res.status, await res.text()); process.exit(1); }
const text = await res.text();
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, text);
fs.writeFileSync(path.join(path.dirname(out), 'bbox.json'), JSON.stringify({ minLon: bbox[0], minLat: bbox[1], maxLon: bbox[2], maxLat: bbox[3], fetched: new Date().toISOString() }, null, 2));
console.log('wrote', out, (text.length / 1e6).toFixed(1), 'MB');
