#!/bin/bash
# fetch the pilot region in 8 small tiles, retrying until Overpass answers
cd "$(dirname "$0")"
LATS=(33.80 33.8725 33.945 34.0175 34.09); LONS=(-112.24 -112.14 -112.04)
for i in 0 1 2 3; do for j in 0 1; do
  B="${LATS[$i]},${LONS[$j]},${LATS[$((i+1))]},${LONS[$((j+1))]}"; F="reg_${i}_${j}.json"
  [ -s "$F" ] && continue
  Q="[out:json][timeout:90];(way[\"highway\"~\"^(motorway|motorway_link|trunk|primary|secondary|tertiary|unclassified|residential|track)$\"]($B);nwr[\"shop\"]($B);nwr[\"amenity\"~\"^(pharmacy|fuel|hospital|clinic|doctors|fire_station|police|school|veterinary|dentist|restaurant|fast_food|place_of_worship|community_centre|library)$\"]($B);node[\"place\"]($B);node[\"natural\"=\"peak\"]($B);way[\"landuse\"~\"^(residential|retail|commercial|industrial|farmland|farmyard)$\"]($B);way[\"waterway\"~\"^(river|stream)$\"]($B);nwr[\"natural\"=\"water\"]($B);nwr[\"man_made\"~\"^(water_well|water_tower|storage_tank)$\"]($B);way[\"building\"]($B););out body center geom;"
  for k in $(seq 1 14); do ok=0
    for U in https://overpass-api.de/api/interpreter https://maps.mail.ru/osm/tools/overpass/api/interpreter https://overpass.kumi.systems/api/interpreter; do   # the main server often drops these; try the mirrors in turn
      curl -sS -m 150 -A "pps-tools-prototype/0.1" -G --data-urlencode "data=$Q" "$U" -o "$F.tmp" 2>/dev/null && python3 -c "import json; json.load(open('$F.tmp'))" 2>/dev/null && mv "$F.tmp" "$F" && echo "ok $F $(wc -c <$F) from $U" && ok=1 && break
    done; [ $ok = 1 ] && break
    sleep 20
  done
done; done
echo DONE
