#!/bin/bash
# corridorfetch.sh: everything the bake needs for the corridor box, in three latitude bands, from whichever Overpass mirror answers.
# Writes raw/cor_<i>.json (kept out of git; rerun to rebuild). Map data (c) OpenStreetMap contributors, ODbL.
cd "$(dirname "$0")"; mkdir -p raw
S=33.8990; N=33.9642; W=-112.1613; E=-112.1158; LATS=($S 33.9207 33.9425 $N)
for i in 0 1 2; do F=raw/cor_$i.json; [ -s "$F" ] && continue; B="${LATS[$i]},$W,${LATS[$((i+1))]},$E"
  Q="[out:json][timeout:180];(way[\"building\"]($B);way[\"highway\"]($B);way[\"barrier\"]($B);way[\"landuse\"]($B);way[\"leisure\"]($B);way[\"natural\"]($B);way[\"waterway\"]($B);way[\"amenity\"]($B);way[\"man_made\"]($B);relation[\"natural\"=\"water\"]($B);node[\"natural\"=\"tree\"]($B);nwr[\"shop\"]($B);node[\"amenity\"]($B);node[\"place\"]($B););out body geom;"
  for k in 1 2 3 4 5 6; do for U in https://maps.mail.ru/osm/tools/overpass/api/interpreter https://overpass-api.de/api/interpreter; do
    curl -sS -m 200 -A "pps-tools-prototype/0.1" -G --data-urlencode "data=$Q" "$U" -o "$F.tmp" 2>/dev/null && python3 -c "import json; json.load(open('$F.tmp'))" 2>/dev/null && mv "$F.tmp" "$F" && echo "ok $F $(wc -c <$F)" && break 2
  done; sleep $((k*8)); done; done
echo DONE
