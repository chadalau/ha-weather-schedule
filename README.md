# Weather Schedule

Home Assistant integration that turns the temperature and humidity sensors of a
grow room into the numbers you actually steer by — VPD, dew point, condensation
margin, absolute humidity — judges them against the target window of the phase
the room is in, and ships a card that puts all of it, plus the fan buttons, on
one screen.

Written from scratch. It shares no code with any VPD card or integration.

## What it creates

One device per room, with:

| Entity | Unit | What it is |
|--------|------|------------|
| `sensor.<room>_vpd` | kPa | Leaf-to-air vapour pressure deficit |
| `sensor.<room>_leaf_temperature` | °C | The infrared sensor if there is one, otherwise air minus the leaf drop |
| `sensor.<room>_dew_point` | °C | Where the air starts condensing |
| `sensor.<room>_condensation_margin` | °C | How far the room is above that point — the number that predicts mould |
| `sensor.<room>_absolute_humidity` | g/m³ | Water actually held by the air, for sizing a dehumidifier |
| `sensor.<room>_status` | — | `on_target`, `vpd_low`, `vpd_high`, `too_cold`, `too_warm`, `too_dry`, `too_humid` |
| `sensor.<room>_carbon_dioxide_status` | — | `under`, `on_target`, `over` — only when a CO₂ sensor is configured |
| `select.<room>_phase` | — | Propagation, early/late vegetative, early/late flower, drying |
| `number.<room>_leaf_drop` | °C | How much colder the leaf runs than the air |
| `binary_sensor.<room>_alert` | — | On after the room holds off target past the tolerance |

Home Assistant builds `entity_id`s in the language of the instance, so on a
Portuguese install the same room reads `sensor.indoor_ponto_de_orvalho`,
`select.indoor_fase` and `binary_sensor.indoor_alerta`. The card does not care:
it matches entities by translation key, never by their id.

The status sensor carries the entire target window in its attributes
(`vpd_min`, `vpd_max`, `temp_min`, `temp_max`, `rh_min`, `rh_max`, `co2_min`,
`co2_max`, `phase`, `drifts`), so the card reads it in one shot instead of the
integration publishing eight more entities.

## Install

1. Copy `custom_components/weather_schedule/` into your `<config>/custom_components/`.
2. Restart Home Assistant.
3. Settings → Devices & Services → **Add integration** → **Weather Schedule**.
4. Name the room, pick its temperature and humidity sensors, plus an infrared
   leaf sensor and a CO₂ sensor if you have them.

**There is no Lovelace resource to register.** The integration serves the card
itself and loads it into the frontend, so after step 3 the card is already
available in the card picker as **Weather Schedule**.

Add one config entry per room.

## The card

```yaml
type: custom:weather-schedule-card
hours: 24
rooms:
  - name: Indoor
    status: sensor.indoor_status
    fans:
      - entity: fan.exhaust
        name: Exhaust
      - entity: switch.circulator
        name: Circulator
```

That is the whole configuration. From the status sensor the card finds the VPD,
dew point and phase entities on the same device, and reads which raw sensors
feed the room from the status attributes — in any interface language. Every
entity below can still be named by hand when the room is built differently.

### Fans

One tile per fan, two per row: the fan icon spins while it runs, the name and
state sit beside it, and the pill on the right shows the speed. Clicking the
tile toggles the fan; clicking the pill steps through 25 / 50 / 75 / 100%.
A `switch.*` gets the same tile without the speed pill, and an unavailable
entity is dimmed instead of hidden.

### More than one sensor per room

Temperature and humidity accept several sensors. The room then reads the average
of them, and every tile — temperature, humidity, dew point, VPD — shows that
average.

The average is taken after the maths, not before: each sensor is paired with the
humidity sensor picked alongside it, VPD and dew point are computed for that
pair, and those results are averaged. Saturation pressure is exponential in
temperature, so averaging first is not the same thing — in a room with a 6 °C
spread the two answers differ by about 7%. Pairing needs the two lists to be the
same length; when they are not, the room falls back to computing once from the
two averages.

A sensor that goes unavailable simply stops being part of the average; the room
is only unreadable when every sensor of a reading is silent.

VPD and dew point come from the integration already averaged, but temperature
and humidity are read straight off the sensors, and a sensor is always a single
probe — so the card averages those two itself, both for the tile and for the
line its history draws.

### Tapping a tile opens its history

The card's own chart always shows the VPD with its phase bands. Tapping a tile
opens a dialog with that reading's history — temperature, humidity, CO₂ or dew
point — with its own unit on the axis, the target window of the current phase
drawn behind the line, and a range selector (6 h / 24 h / 3 d / 7 d). The dew
point uses air temperature minus 2 °C as its ceiling, which is the line
condensation starts at.

In a room with more than one sensor the dialog also draws one thin, faded line
per sensor behind the average — the spread of the room, without competing with
the reading that drives it.

### Tapping the status chip opens the day

The chip shows what the room is right now; tapping it opens a radar of what the
room *was*, over the same 6 h / 24 h / 3 d / 7 d ranges. One spoke per drift,
each facing its opposite — dry against humid, cold against warm — so a bad day
has a shape before it has numbers, and a good day shrinks to the inner ring. The
scale starts at that ring rather than at the centre: the middle belongs to the
number it holds, the share of the window spent on target.

The spokes come from the `drifts` attribute, not from the state — the state
carries only the first drift, so a room that is warm and dry at once would count
as warm alone. Each moment splits its time between the drifts it had, half and
half for two of them, so the spokes and the centre add up to the whole window:
the chart reads as a day divided, because that is what it is. The printed
percentages are rounded so they still total 100%. Stretches where the room could
not be read stay out of the split and are reported below the chart.

### Hourly dots

The chart carries one dot per hour, placed on the real sample closest to the
hour mark so the dots never disagree with the line. Hovering, tapping or
tabbing to one opens a tooltip with the time and the reading, the lowest and
highest values of that hour when it moved, the VPD band it was in, and whether
it sat inside the target window. The dot at the right edge is the current
reading, labelled **now**.

### The gear

The gear in the header opens the room settings: which sensor feeds each
reading, how much colder the leaf runs than the air, and how long the room has
to hold before the alert reacts. Saving drives the integration's own options
flow, so the card never becomes a second place where settings live — what you
change here is exactly what the Configure dialog would have changed.

| Option | Default | What it does |
|--------|---------|--------------|
| `rooms` | required | One entry per room; the pills at the top switch between them |
| `hours` | `24` | How much history the chart draws |
| `rooms[].status` | — | The status sensor; brings the target windows and lets the card find its siblings |
| `rooms[].temperature`, `rooms[].humidity` | — | Raw sensors. Without the integration the card computes VPD and dew point itself |
| `rooms[].vpd`, `rooms[].dew_point`, `rooms[].phase` | auto | Only needed when auto-discovery cannot find them |
| `rooms[].co2` | — | Adds the CO₂ tile — point it at the raw CO₂ sensor |
| `rooms[].leaf_drop` | `2` | Leaf gap used only when the card has to compute VPD by itself |
| `rooms[].fans` | — | `fan.*` or `switch.*` entities, each with an optional `name`. Usually left out: the gear stores them in the integration |
| `scale` | `auto` | The VPD chart closes in on the range the room actually used, keeping the target window in frame; `full` pins it to the whole 0–2 kPa span |
| `language` | `pt` | The card speaks Brazilian Portuguese by default, whatever the Home Assistant locale is; set `en` for English |

Fans call `fan.toggle` / `switch.toggle`, and `fan.set_percentage` for the
25 / 50 / 75 / 100 buttons, which only appear on fans that report a percentage.
An unavailable entity is shown disabled rather than hidden.

Every part of the card degrades on its own: no `status` means tiles without
target bands, no `phase` hides the phase chip, no `fans` drops the row. A room
with nothing but a temperature and a humidity sensor still gets a VPD reading,
tiles and a chart.

## Phases and their default windows

Editable per room under the integration's **Configure** → Target windows.

| Phase | VPD (kPa) | Temp (°C) | RH (%) | CO₂ (ppm) |
|-------|-----------|-----------|--------|-----------|
| Propagation | 0.4 – 0.6 | 22 – 26 | 68 – 75 | 400 – 800 |
| Early vegetative | 0.8 – 1.0 | 22 – 28 | 57 – 63 | 700 – 1000 |
| Late vegetative | 1.0 – 1.2 | 22 – 28 | 51 – 57 | 800 – 1200 |
| Early flower | 1.0 – 1.2 | 21 – 26 | 47 – 54 | 1000 – 1200 |
| Late flower | 1.1 – 1.3 | 20 – 25 | 41 – 48 | 800 – 1000 |
| Drying | 0.6 – 0.9 | 15 – 18 | 52 – 68 | 400 – 800 |

The VPD windows follow the literature: about 0.3–0.6 kPa while cuttings root
([MSU Extension](https://www.canr.msu.edu/news/why_should_greenhouse_growers_pay_attention_to_vapor_pressure_deficit_and_n)),
0.8–1.1 through vegetative growth, and 1.0–1.5 in flower — the range cited by
[Frontiers in Plant Science (2025)](https://doi.org/10.3389/fpls.2025.1678142),
whose high-humidity treatment (VPD 0.25 kPa) lost 71% of its flower biomass.
Drying follows the 60/60 rule, 15–18 °C at 55–65% RH.

The humidity windows are not independent: each one is the humidity that produces
that phase's VPD at that phase's mid temperature. Picking the three by feel
leaves a room permanently off target, since obeying one window breaks another.
In the drying phase the leaf gap is dropped altogether — harvested material does
not transpire, so its VPD is the air's own, which is why 60/60 reads 0.7 kPa and
not the 0.5 a leaf offset would give.

The CO₂ windows assume an enriched room. A room without injection sits at
ambient CO₂, so tick **Room is not CO₂ enriched** under Configure → Alert and
CO₂; readings under the window then stop being reported as off target.

## The light cycle

Configure → **Light cycle** takes an hour and a length: lights on at 18:00 for 18
hours, say. It is a schedule rather than an entity on purpose — a schedule says
what the grow intends, while a relay can be flipped by hand at three in the
morning without the night having ended. The default is 24 hours of light, which
means "this room never gets dark" and judges it exactly as before.

Two things change once the room knows it is dark:

**CO₂ leaves the judgement.** Without light there is no photosynthesis, so the
phase's CO₂ window does not apply; `sensor.<room>_co2_status` goes unknown and no
CO₂ drift is raised. The card drops the target band from the CO₂ tile and marks
it *no target in the dark*.

**The leaf gap shrinks.** Under the lamps the leaf sits below air temperature
because transpiration cools it; in the dark the stomata are shut, but the leaf
still loses heat by radiation — field measurements put it 1–3 °C under the air.
So the room keeps a separate, smaller gap for the dark, 1 °C by default. Drying
still uses none, at any hour.

The room also wakes itself at the moment the lights flip, instead of waiting for
the next sensor to report.

## The alert

`binary_sensor.<room>_alert` turns on only after the room has been off target
for 15 minutes, and turns off after 5 minutes back inside — both editable. A
room breathing across the edge of its window does not flap the alert.

Off target means any of VPD, temperature, humidity **or CO₂** outside the window
of the current phase. When temperature or humidity cannot be read at all, the
room reports no status and the alert stays where it is: an unreadable room is
not a healthy room, so nothing is cleared on missing data.

## Fan timers

Each fan can carry a cycle — so many minutes on, so many off — set in the gear
of the card. The countdown on the tile says what happens next (`on in 7 min`),
and `switch.<room>_timers` pauses every cycle without touching the fans. A cycle
anchors on what the fan actually is: after a restart, or after you flip it by
hand, it counts from that state instead of forcing the fan on.

## The maths

Saturation vapour pressure follows the Arden Buck equation (1996) over water,
and dew point is its exact inverse, so both sit on one curve. Absolute humidity
comes straight from the ideal gas law. Sensors reporting °F or K are converted
before anything is calculated.

## Scope

The integration measures and judges, and it switches fans in exactly one case:
a **cyclic timer** you configure per fan (so many minutes on, so many off).
Nothing else is ever switched, and no decision looks at the climate — a timer
that quietly skips a run is a timer nobody trusts. `switch.<room>_timers` pauses
every cycle of the room at once, leaving each fan exactly as it is. Everything
beyond that stays with you, in Home Assistant automations, driven by the
entities above.

Turning a fan on or off by hand re-anchors its cycle from that moment: switch it
off and the next run starts after the off minutes, not on the old schedule.

## Tests

`tests/` holds a pytest suite covering the parts that decide things: the
psychrometry against reference tables, sensor reading (non-numeric states, NaN,
°F/K, humidity out of range, an unreadable room), the drift judgement per phase,
the cyclic timers (validation of stored options, anchoring on the current state
of each fan, manual switching), and the options screen (an inverted window is
refused, saving one phase does not erase the others, every error has a message
in both languages). It deliberately stays out of
`custom_components/`, so Home Assistant never tries to load it.

It never touches Home Assistant's test harness — the fixtures build a coordinator
and a cycle engine by hand — but it does import the integration, which imports
Home Assistant. So run it where Home Assistant is installed: copy `tests/` next
to `custom_components/` in a container and run

```bash
docker exec ha-test sh -c "cd /config && PYTHONPATH=/config python -m pytest tests -q"
```

`tests/test_psychrometrics.py` is the exception: it loads the maths module by
path, imports nothing else, and runs on any Python with `pytest`:

```bash
cd "Weather Schedule" && python -m pytest tests/test_psychrometrics.py -q
```
