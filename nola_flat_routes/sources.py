"""Registry of every external dataset used by the project.

Each entry records the URL, the access date, resolution/vintage, licence and
the limitations that matter for this analysis.  ``python -m sf_flat_routes
sources`` prints this table, and it is the single source of truth for the
data-provenance section of the README.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Date on which every URL below was last fetched and verified.
ACCESS_DATE = "2026-10-06"

#: Overture Maps release used for the street network.
OVERTURE_RELEASE = "2026-08-19.0"
OVERTURE_BUCKET = "https://overturemaps-us-west-2.s3.amazonaws.com"
OVERTURE_PREFIX = f"release/{OVERTURE_RELEASE}/theme=transportation"
#: Places and addresses themes of the same release, used only for the route
#: page's offline place search (fetched 2026-10-04).
OVERTURE_PLACES_PREFIX = f"release/{OVERTURE_RELEASE}/theme=places"
OVERTURE_ADDRESSES_PREFIX = f"release/{OVERTURE_RELEASE}/theme=addresses"
OVERTURE_BASE_PREFIX = f"release/{OVERTURE_RELEASE}/theme=base"

#: USGS 3DEP elevation image service. For Orleans Parish the best available
#: source underneath it is the 1 m lidar project LA_2021GreaterNewOrleans_C22.
TNM_BUCKET = "https://prd-tnm.s3.amazonaws.com"
LIDAR_PROJECT = "LA_2021GreaterNewOrleans_C22"
ELEVATION_IMAGE_SERVER = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
)

#: Orleans Parish neighborhood polygons (72 planning neighborhoods plus the
#: eastern marsh units). The ``name`` property is what the loader expects.
NEIGHBORHOOD_URL = (
    "https://raw.githubusercontent.com/codeforamerica/click_that_hood/"
    "master/public/data/new-orleans.geojson"
)


@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    publisher: str
    url: str
    accessed: str
    resolution: str
    licence: str
    limitations: str
    role: str
    local: str = ""
    notes: str = ""
    optional: bool = False
    substituted: bool = False
    substitution_reason: str = ""


DATASETS: tuple[Dataset, ...] = (
    Dataset(
        key="overture_segments",
        title=f"Overture Maps transportation segments (release {OVERTURE_RELEASE})",
        publisher="Overture Maps Foundation (derived from OpenStreetMap)",
        url=f"{OVERTURE_BUCKET}/{OVERTURE_PREFIX}/type=segment/",
        accessed=ACCESS_DATE,
        resolution="Vector linestrings; OSM-equivalent positional accuracy (~1-5 m)",
        licence="ODbL 1.0 (OpenStreetMap contributors); Overture schema CDLA-Permissive 2.0",
        role="Routable street network: geometry, road class, per-mode access "
             "restrictions, bridge/tunnel flags and connector topology.",
        local="data/raw/overture_segments_nola.parquet",
        limitations=(
            "OSM-derived, so completeness and tagging quality vary by area. "
            "Some surface arterials are tagged trunk (Claiborne Avenue, "
            "parts of Broad), so trunk is not excluded from walking or "
            "biking; motorways such as I-10 and the Pontchartrain Expressway "
            "are. Sidewalk and crosswalk geometry is present but of uneven "
            "completeness and is deliberately not used, so travel is modelled "
            "on street centrelines."
        ),
        notes="Read with Parquet row-group bbox pruning against the Orleans "
              "Parish bounding box, so the extract is a few row groups "
              "rather than the global transportation theme.",
    ),
    Dataset(
        key="overture_connectors",
        title=f"Overture Maps transportation connectors (release {OVERTURE_RELEASE})",
        publisher="Overture Maps Foundation (derived from OpenStreetMap)",
        url=f"{OVERTURE_BUCKET}/{OVERTURE_PREFIX}/type=connector/",
        accessed=ACCESS_DATE,
        resolution="Vector points",
        licence="ODbL 1.0; Overture schema CDLA-Permissive 2.0",
        role="Authoritative intersection nodes. Using connector IDs for graph "
             "topology avoids geometric snapping tolerances entirely.",
        local="data/raw/overture_connectors_nola.parquet",
        limitations="Connectors exist only where OSM ways share a node; "
                    "grade-separated crossings correctly do not connect.",
    ),
    Dataset(
        key="dem_3dep",
        title=f"USGS 3DEP bare-earth elevation, lidar project {LIDAR_PROJECT}",
        publisher="U.S. Geological Survey, 3D Elevation Program",
        url=ELEVATION_IMAGE_SERVER,
        accessed=ACCESS_DATE,
        resolution="8 m overview of the 1 m lidar COGs; NAD83 / UTM 15N "
                   "(zone 16 tiles reprojected); metres above NAVD88",
        licence="Public domain (U.S. Government work)",
        role="Primary elevation source for all grade and climbing metrics.",
        local="data/raw/dem/*_ovr8.tif",
        limitations=(
            "A full-resolution 1 m mosaic of Orleans Parish is about 10 GB, "
            "so each cloud-optimised tile is read at its 8 m overview. "
            "The National Map ImageServer export was not used: over the "
            "below-sea-level bowls it returned the smallest float32 instead "
            "of the lidar value (Broadmoor is about -1.3 m on the COG and "
            "on the point service, and missing on the image export). "
            "Bare-earth elevation does not include bridge decks: segments "
            "flagged is_bridge or is_tunnel are a linear ramp between the "
            "ground they meet, the same treatment as Flatten SF. Residual "
            "noise is handled by a 20 m Gaussian, Savitzky-Golay smoothing "
            "and a 0.5 m gain dead-band."
        ),
        notes="Tile list comes from the National Map access API, filtered "
              f"to project {LIDAR_PROJECT}.",
    ),
    Dataset(
        key="neighborhoods",
        title="New Orleans neighborhoods (click_that_hood)",
        publisher="City of New Orleans, mirrored by Code for America "
                  "(click_that_hood)",
        url=NEIGHBORHOOD_URL,
        accessed=ACCESS_DATE,
        resolution="Vector polygons, 73 features covering Orleans Parish",
        licence="Open data (the click_that_hood collection; neighborhood "
                "boundaries originate with the City of New Orleans)",
        role="Neighborhood labels on the map, and the clip that keeps the "
             "street graph inside Orleans Parish.",
        local="data/raw/nola_neighborhoods.geojson",
        limitations=(
            "Planning-neighborhood polygons, including the eastern marsh "
            "units (Lake Catherine, Viavant). A rectangular download bbox "
            "also catches a sliver of Jefferson and St. Bernard Parish; "
            "edges whose midpoint falls outside these polygons (plus 250 m) "
            "are dropped."
        ),
    ),
    Dataset(
        key="overture_places",
        title=f"Overture Maps places (release {OVERTURE_RELEASE})",
        publisher="Overture Maps Foundation (Meta and Microsoft POI data)",
        url=f"{OVERTURE_BUCKET}/{OVERTURE_PLACES_PREFIX}/type=place/",
        accessed="2026-10-04",
        resolution="Point features with names, categories and a confidence score",
        licence="CDLA Permissive 2.0",
        role="Offline place search in the route page (parks, landmarks, "
             "transit, schools, shops, cafes).",
        local="data/raw/overture_places_nola.parquet",
        limitations="Point-of-interest coverage and naming are uneven; only "
                    "records with confidence >= 0.6 in routable categories "
                    "are kept. Not used by the analysis itself.",
        optional=True,
    ),
    Dataset(
        key="overture_base",
        title=f"Overture Maps base theme: land use, infrastructure, land (release {OVERTURE_RELEASE})",
        publisher="Overture Maps Foundation (derived from OpenStreetMap)",
        url=f"{OVERTURE_BUCKET}/{OVERTURE_BASE_PREFIX}/",
        accessed="2026-10-04",
        resolution="Mapped outlines and points with names and OSM-derived classes",
        licence="ODbL 1.0 (OpenStreetMap contributors)",
        role="Mapped parks, schools, hospitals, plazas, stations, piers, "
             "bridges, viewpoints, peaks and beaches for the route page's "
             "offline search; these outrank the POI feed, which places the "
             "same names unreliably.",
        local="data/raw/overture_{land_use,infrastructure,land}_nola.parquet",
        limitations="Only named features in a fixed class list are used. "
                    "Not used by the analysis itself.",
        optional=True,
    ),
    Dataset(
        key="overture_addresses",
        title=f"Overture Maps addresses (release {OVERTURE_RELEASE})",
        publisher="Overture Maps Foundation (OpenAddresses)",
        url=f"{OVERTURE_BUCKET}/{OVERTURE_ADDRESSES_PREFIX}/type=address/",
        accessed="2026-10-04",
        resolution="Address points with street number and street name",
        licence="Open (OpenAddresses sources; SF data is public domain)",
        role="Offline street-address search in the route page.",
        local="data/raw/overture_addresses_nola.parquet",
        limitations="One point per (street, number) is kept; unit numbers "
                    "are dropped. Not used by the analysis itself.",
        optional=True,
    ),
    Dataset(
        key="bike_network",
        title="Bicycle facilities derived from OpenStreetMap tags",
        publisher="OpenStreetMap contributors, via Overture",
        url="https://www.openstreetmap.org/copyright",
        accessed=ACCESS_DATE,
        resolution="n/a",
        licence="ODbL 1.0",
        role="Low-stress and cycleway flags on the packed graph.",
        local="(derived from Overture class and access attributes)",
        limitations=(
            "There is no separate city bike-facility layer in this build. "
            "Cycleways, living streets and pedestrian streets come from "
            "OpenStreetMap tags carried by Overture. That misses some "
            "painted lanes that OSM never marked as a separate way."
        ),
        optional=True,
    ),
)

DATASETS_BY_KEY = {d.key: d for d in DATASETS}


def format_table() -> str:
    """Human-readable provenance report."""
    lines = [f"Data sources (all URLs verified {ACCESS_DATE})", "=" * 78]
    for d in DATASETS:
        flag = " [OPTIONAL]" if d.optional else ""
        flag += " [SUBSTITUTED]" if d.substituted else ""
        lines += [
            f"\n{d.key}{flag}",
            f"  title       : {d.title}",
            f"  publisher   : {d.publisher}",
            f"  url         : {d.url}",
            f"  accessed    : {d.accessed}",
            f"  resolution  : {d.resolution}",
            f"  licence     : {d.licence}",
            f"  local cache : {d.local}",
            f"  role        : {d.role}",
            f"  limitations : {d.limitations}",
        ]
        if d.notes:
            lines.append(f"  notes       : {d.notes}")
        if d.substitution_reason:
            lines.append(f"  substitution: {d.substitution_reason}")
    return "\n".join(lines)


def markdown_table() -> str:
    """Compact markdown table for the README."""
    rows = ["| Dataset | Publisher | Resolution / vintage | Licence | Role |",
            "|---|---|---|---|---|"]
    for d in DATASETS:
        rows.append(
            f"| {d.title} | {d.publisher} | {d.resolution} | {d.licence} | {d.role} |"
        )
    return "\n".join(rows)
