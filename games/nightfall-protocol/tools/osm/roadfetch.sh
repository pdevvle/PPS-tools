#!/bin/bash
# roadfetch.sh [out.json] [south,west,north,east]
# Every road in a block with all its tags (lanes, speed limits, turn lanes, destinations, surfaces), plus the nodes
# that control traffic: stops, give ways, signals, speed signs, exit numbers, gates and cattle guards.
# The main Overpass server often drops these, so it tries the mirrors in turn. Default: the New River block.
# Power for the same box (the road pass reads data/roads/osm_power_<block>.json):
#   [out:json];(way["power"~"^(line|minor_line|cable)$"](B);node["power"~"^(tower|pole|portal|transformer)$"](B);node["highway"="street_lamp"](B);way["power"="substation"](B););out body geom;
OUT=${1:-../../data/roads/osm_newriver.json}; B=${2:-33.9025,-112.1575,33.9335,-112.1195}
Q="[out:json][timeout:120];(way[\"highway\"]($B);node[\"highway\"~\"^(traffic_signals|stop|give_way|crossing|street_lamp|milestone|motorway_junction)$\"]($B);node[\"traffic_sign\"]($B);node[\"barrier\"~\"^(cattle_grid|gate)$\"]($B);node[\"railway\"=\"level_crossing\"]($B););out body geom;"
for k in 1 2 3 4; do for U in https://overpass-api.de/api/interpreter https://maps.mail.ru/osm/tools/overpass/api/interpreter https://overpass.kumi.systems/api/interpreter; do
  curl -sS -m 150 -A "pps-tools-prototype/0.1" -G --data-urlencode "data=$Q" "$U" -o "$OUT.tmp" 2>/dev/null && python3 -c "import json; json.load(open('$OUT.tmp'))" 2>/dev/null && mv "$OUT.tmp" "$OUT" && echo "ok $OUT $(wc -c <"$OUT") from $U" && exit 0
done; sleep $((k*10)); done
echo "failed"; exit 1
