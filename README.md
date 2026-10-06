# Flatten NOLA

The flattest walk or bike ride between two places in New Orleans, and every
route between that and the shortest one.

New Orleans is famous for being flat. It is not *quite* flat. The natural
levee along the Mississippi sits a few metres above the bowls behind it
(Broadmoor, Mid-City, parts of Gentilly), Esplanade Ridge and Gentilly Ridge
are old distributary banks you can feel on a bike, and the lakefront levee
is a wall. Most of the time the flattest route and the shortest route are
the same walk, which is the joke. When they are not, the difference is a
levee, a ridge, or a bridge approach, and the slider is there so you can
watch that happen.

This is a New Orleans adaptation of
[Flatten SF](https://github.com/almostimplemented/flattensf) by Drew Edwards
(MIT). The route page, the cost model, and the in-browser router are that
project's. The city, the elevation, and the street graph are not.

## Try it

The built site is in [`site/`](site/). From this directory:

```bash
python3 -m http.server -d site 8000
```

Open http://localhost:8000. The page opens on **Jackson Square → Audubon
Park**. Two more trips are on the card: **Mid-City → Bywater** and
**Lakeview → French Quarter**. Or type an address, a place, or an
intersection (`Magazine & Napoleon`), or click the map.

Drag the slider from **Shortest** to **Flattest**. Every stop is a real
route, solved in the browser. Faint lines are the other routes in the
family. Walk and Bike use different streets (stairs are walk-only). Copy
link reopens the same trip.

There is also one self-contained file,
[`outputs/nola_flat_route_finder.html`](outputs/nola_flat_route_finder.html),
which opens from disk. It is the same page with the graph embedded.

## The joke, with the slider

A foot of climbing is priced from nothing (shortest) up to 200 feet of
detour (flattest). Past that the router starts wandering, so the slider
stops. Along the way, distance only grows and climbing only falls. In San
Francisco that trade is dramatic. Here the two routes stay close, which is
the point:

| Trip | Shortest | Flattest |
|---|---|---|
| Jackson Square → Audubon Park | 5.3 mi, 29 ft of climbing | 5.4 mi, 25 ft |
| Mid-City → Bywater | 3.8 mi, 21 ft | 3.8 mi, 16 ft |
| Lakeview → French Quarter | 4.7 mi, 30 ft | 4.8 mi, 28 ft |

Lakeview sits about 6 ft below sea level and the Square sits about 11 ft
above it, so most of that 30 ft is the climb you cannot avoid. The ghost
lines are where a small detour ducks a levee ramp or stays up on the ridge
instead of dipping into the bowl and climbing back out.

Climbing is cumulative gain after a 0.5 m dead-band, not the net difference
between the two ends. Without the dead-band, lidar noise would invent a
hill on a street that is level.

## Data

| | |
|---|---|
| Streets | OpenStreetMap via [Overture Maps](https://overturemaps.org) transportation (release 2026-08-19.0). © OpenStreetMap contributors, [ODbL 1.0](https://opendatacommons.org/licenses/odbl/). The packed graph in `site/data/` is a derivative database and carries the same share-alike terms. |
| Elevation | [USGS 3DEP](https://www.usgs.gov/3d-elevation-program), public domain. Project `LA_2021GreaterNewOrleans_C22`, the 1 m bare-earth lidar, read at the COGs' built-in **8 m** overview (a 1 m mosaic of the parish is about 10 GB). Jackson Square comes out around 12 ft; Broadmoor around −4 ft. The bowls are in the model. |
| Neighborhoods | City of New Orleans polygons via [click_that_hood](https://github.com/codeforamerica/click_that_hood). The street graph is clipped to their union, plus 250 m, so Jefferson and St. Bernard Parish stay out. |
| Code | MIT, inherited from Flatten SF. See [LICENSE](LICENSE). |
| Leaflet | 1.9.4, BSD-2-Clause, vendored under `nola_flat_routes/vendor/`. |

Bridge decks are not in a bare-earth model. A segment tagged as a bridge or
tunnel is a ramp between the ground elevations where the structure meets
the earth, the same rule Flatten SF uses. A bridge approach that is fill
shows up. A steel arch whose two ends sit on levees of the same height does
not grow a hump, because the lidar never saw the deck.

## Rebuild

```bash
pip install -r requirements.txt
python -m nola_flat_routes download        # Overture streets, places, 3DEP tiles, neighborhoods
python -m nola_flat_routes build-network   # graph, elevation samples, grades
python -m nola_flat_routes site            # site/ and the single-file page
```

`python -m nola_flat_routes all` runs those three. Cached files under
`data/` are gitignored; the site is what gets committed. `sources` prints
the provenance table.

The upstream commands `analyze`, `validate`, `map`, and `report` are still
here (corridors, passes, the explorer). They run on this graph, not on San
Francisco. The page this repo is for is `site`.

Place search is offline: intersections from the graph (`Magazine & Napoleon`)
and about 6,000 Overture places. This Overture release had no Orleans Parish
address points, so house numbers are not in the page. No geocoding key.

The west bank (Algiers and beyond) is not in the routable component. In
OpenStreetMap the Crescent City Connection is a freeway, and the ferry is
not a street, so there is no walk or bike link to the east bank. The three
demo trips all stay on the east bank, which is where the bowls and the
river levee are.
