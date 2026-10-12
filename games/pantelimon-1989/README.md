# Pantelimon, 1989

A first-person walk down a street in Pantelimon, on the eastern edge of Bucharest, on the afternoon of Friday 22 December 1989: the day Ceaușescu fled. The visual style follows the painterly look of *The Long Dark*: warm low light, cool blue shade, heavy atmospheric haze and a paint filter over everything. It is a separate demo from Nightfall Protocol and shares no code with it.

It is one self-contained HTML file with no build step. Open `index.html` in a browser with WebGL. [three.js](https://threejs.org/) r128 loads from cdnjs, so the first load needs an internet connection. Everything else is generated in code: geometry, textures, lettering and sound. The demo has no image or audio files.

## Controls

| Input | Action |
|---|---|
| Mouse | Look (click the view to capture the mouse) |
| `W` `A` `S` `D` or arrow keys | Walk |
| `Shift` | Hurry |
| `F` | Flashlight |
| `Esc` | Pause and settings |

On a touch screen, drag on the left half to walk and on the right half to look.

Walk into the boys' ball to kick it.

The pause panel has these settings:
- time of day
- time flow: stopped, real time, or fast (an hour every 30 seconds)
- weather
- the paint filter
- resolution
- mouse sensitivity
- volume

## What's in the street

- **Șoseaua Pantelimon**:
  - Two carriageways with faded lane paint, and a tram line in the middle on concrete sleepers and ballast.
  - Catenary carried on the Romanian vibrated concrete poles with rectangular holes.
  - A V3A articulated tram, cream with a red band, standing at the stop with route 14 on its blind.
  - Shopfronts along both sides; see *Getting the period right* for the signs.
  - The tram stop sign reads STAŢIE TRAMVAI.
- **The side street** is cobbled in *piatră cubică*, between P+4 prefab panel blocks:
  - Visible panel joints sealed with dark mastic, and grime running down from the sills.
  - Double wooden windows with lace net curtains, and rooms behind the glass. Some rooms are lit in the evening.
  - Balconies with mosaic or panel parapets, many of them glazed in by the residents with frames that don't match.
  - Washing lines and crates on the balconies, entrances under concrete canopies with BL. and SC. plates, and metal bins.
  - Roofs bristling with TV aerials turned south toward Bulgarian television.
  - Bare lindens, planes, poplars and acacias with whitewashed trunks and mistletoe, and a few concrete lamp posts.
- **A courtyard**:
  - A carpet-beating rack with a rug left over it, swings, a slide, a sandpit and benches.
  - A row of tin garages and a refuse container.
  - One Dacia laid up under a tarpaulin and another up on bricks, for want of petrol.
- **Old single-storey houses** left between the blocks:
  - Plaster falling off to brick, tile or tin roofs, a glazed porch (*geamlîc*), and plank or sheet-metal fences.
  - Stove chimneys smoking, and power lines dropping to the eaves.
- **The cars of 1989**: Dacia 1300, Dacia 1310 with four round lamps, Dacia 1310 *break* and Trabant 601. All are in faded solid colours with black-on-white plates such as `2-B-34517`.
- **The revolution**:
  - Tricolours with the coat of arms cut out, hung from balconies and on poles.
  - Brush-painted slogans: JOS CEAUŞESCU!, LIBERTATE, ARMATA E CU NOI!, OLÉ, OLÉ, CEAUŞESCU NU MAI E!, JOS COMUNISMUL, 22 XII 1989.
  - A half-torn TRĂIASCĂ PARTIDUL COMUNIST ROMÂN banner on a roof.
  - A smouldering pile of the dictator's portraits and collected works in the street.
  - The kiosk sells the one-page *Scînteia poporului* that came out that day.
  - After dark the shooting starts somewhere across the city.
- **The city beyond**: rows of blocks fading into the haze, a factory chimney, a church dome.

## People

The clothing follows what people wore in Bucharest that winter.

- **The man**:
  - Charcoal wool *palton* (overcoat), astrakhan *căciulă* (fur hat), grey knitted scarf and a moustache.
  - A folded *Scînteia poporului* in his gloved hand and a Carpați in the other.
  - He walks from the kiosk down the pavement and back. He takes a drag every few seconds and breathes the smoke out.
  - He slows to watch the boys, and glances at you if you come close.
- **The woman**:
  - Quilted floral *capot* (house robe), a hand-knitted cardigan worn open, and a *batic* (headscarf) tied at the nape.
  - She leans out of her open first-floor window and shakes out a small rug (*preș*) in three bursts. The rug is a simulated cloth with dust coming off it.
  - Then she folds her arms on the sill to watch the boys, and goes back inside. A pillow is airing on the sill.
- **Two boys**:
  - One wears a navy quilted anorak, a striped red bobble hat, a blue *trening* (tracksuit) with white stripes and lace-up boots.
  - The other wears a brown quilted jacket, a knitted hat with ear flaps, a green scarf, dark trousers and rubber boots.
  - They dribble, pass and shoot at goals made of schoolbags, chase loose balls and trap them.
  - The ball bounces off kerbs, cars and trees. They go home after dark.

## Getting the period right

Research notes behind the choices, and where they are uncertain:

- **Weather**: 22 December 1989 in Bucharest was mild and dry, about 6 °C, hazy, with no snow on the ground; the 21st was foggy. The first light snow came on the 26th–27th. The weather settings follow those days (Bucharest–Băneasa station records).
- **Light**:
  - The sun's path is computed for Bucharest's latitude at the winter solstice. It peaks at about 22° and sets around 16:45.
  - The moon is a waning crescent that rises before dawn, so evenings are moonless.
  - Street lighting was rationed, so only a few lamps burn and only a minority of windows are lit.
- **Spelling**:
  - Signs use the pre-1993 orthography with *î*: PÎINE, Scînteia.
  - România keeps *â*, as it did then.
- **Things deliberately absent**: satellite dishes, air-conditioning units, PVC windows, insulation cladding, advertising and western cars.
- **Number plates**: the 1966–1992 format, black on white with a category number, the county letters and a serial.
- **Uncertain**:
  - Tram route numbers on the Șoseaua in 1989; route 14 is the long-standing Pantelimon line.
  - Exact original facade colours of the blocks.
  - Factory Dacia colours.
  - Whether there was shooting in Pantelimon itself.
- **Layout**: the street layout is composed from the district's typical forms and is not a survey of one real street.

## How it's drawn

- **One shared material**:
  - A single painterly shader covers every opaque surface. It uses a wrapped, softened diffuse with warm sunlight and cool sky ambient, and height fog that takes its colour from the sky.
  - It also does soft shadow maps from the sun or moon.
  - Surface types (panel concrete, windows, setts, asphalt, plaster, wool, quilting, skin) are selected per vertex.
- **Windows**: interior mapping gives every window real depth, with a reveal, frames, curtains and a room behind it. No textures are used.
- **Paint filter**: a Kuwahara filter, film grade, vignette and grain are applied after the scene renders. Falling snow and the overhead wires are drawn after the filter so they stay crisp.
- **People** are modelled after the cast of *The Long Dark*:
  - Each person is one continuous skinned mesh that bends at the shoulders, elbows, hips and knees, with up to four bone weights per vertex. A coat skirt follows the thighs more strongly toward its hem.
  - Heads are sculpted in code: brow ridge, eye sockets, cheekbones, jaw corner, laugh lines and lips. Each has a faceted nose, eyeballs under heavy upper lids, and ears.
  - Hands have four jointed fingers and a thumb, posed to grip, hold a cigarette or hang relaxed.
  - Clothes have thickness and weight: hems and turned-back cuffs, lapels, a turned-up collar, padded shoulders, folds in the skirts, quilted channels and diamonds, and knit ribbing.
  - The shader paints light from above into the colours, adds brush strokes to the cloth and a soft sky rim around each figure, and reddens noses and cheeks in the cold.
  - Everyone is animated procedurally. The woman's rug is a verlet cloth pinned to her hands.
- **Sound**: all synthesised, including footsteps that change with the surface, the ball, the rug, hooded crows, stray dogs and the city's low hum.
