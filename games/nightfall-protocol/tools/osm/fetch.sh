#!/bin/bash
# fetch.sh <outfile> <overpass query> — retries transient resets
for i in 1 2 3 4 5; do
  curl -sS -m 180 -A "pps-tools-prototype/0.1" -G --data-urlencode "data=$2" https://overpass-api.de/api/interpreter -o "$1.tmp" 2>/dev/null && python3 -c "import json,sys; json.load(open('$1.tmp'))" 2>/dev/null && mv "$1.tmp" "$1" && echo "ok $1 $(wc -c <"$1")" && exit 0
  sleep $((i*4))
done
echo "failed $1"; exit 1
