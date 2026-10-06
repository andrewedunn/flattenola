"""Data acquisition with local caching.

Everything is cached under ``data/raw`` and re-downloaded only when missing
(or when ``force=True``), so re-running the pipeline never re-fetches the
523 MB of lidar or re-scans the Overture release.

The Overture read is the interesting part: the transportation theme is ~64 GB
spread over 128 Parquet files.  Each file carries per-row-group statistics on
the ``bbox`` struct column, and Overture writes rows in spatial order, so we
read the 128 footers (cheap, a couple of range requests each), keep only the
row groups whose bounding box intersects Orleans Parish, and read just those.
In practice 7 row groups in a single file cover the city.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests

from . import sources
from .config import RAW_DIR, SF_BBOX
from .utils import configure_gdal_for_proxy, get_logger, human_bytes, progress, step

log = get_logger("sf_flat_routes.download")

_S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

DEM_DIR = RAW_DIR / "dem"
SEGMENTS_PARQUET = RAW_DIR / "overture_segments_nola.parquet"
CONNECTORS_PARQUET = RAW_DIR / "overture_connectors_nola.parquet"
PLACES_PARQUET = RAW_DIR / "overture_places_nola.parquet"
ADDRESSES_PARQUET = RAW_DIR / "overture_addresses_nola.parquet"
#: Overture base theme (OpenStreetMap): mapped parks, schools, stations...
BASE_PARQUETS = {typ: RAW_DIR / f"overture_{typ}_nola.parquet"
                 for typ in ("land_use", "infrastructure", "land")}
NEIGHBORHOODS_GEOJSON = RAW_DIR / "nola_neighborhoods.geojson"

#: Columns pulled from the Overture segment table. Everything unused is left
#: on the server -- the nested route/destination columns are large.
SEGMENT_COLUMNS = [
    "id", "names", "subtype", "class", "subclass", "connectors",
    "road_flags", "access_restrictions", "road_surface", "speed_limits",
    "level_rules", "geometry", "bbox", "sources",
]
CONNECTOR_COLUMNS = ["id", "geometry", "bbox"]
PLACE_COLUMNS = ["id", "names", "categories", "confidence", "geometry", "bbox"]
ADDRESS_COLUMNS = ["id", "number", "street", "unit", "postcode", "geometry", "bbox"]
BASE_COLUMNS = ["id", "names", "subtype", "class", "geometry", "bbox"]


# --------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------
def _list_s3_keys(bucket: str, prefix: str, suffix: str = ".parquet") -> list[str]:
    """List keys under a public S3 prefix via the REST list-objects-v2 API."""
    keys: list[str] = []
    token = None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        r = requests.get(bucket + "/", params=params, timeout=120)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        for c in root.findall("s3:Contents", _S3_NS):
            key = c.find("s3:Key", _S3_NS).text
            if key.endswith(suffix):
                keys.append(key)
        if root.findtext("s3:IsTruncated", default="false", namespaces=_S3_NS) == "true":
            token = root.findtext("s3:NextContinuationToken", namespaces=_S3_NS)
        else:
            break
    return keys


def _download_file(url: str, dest: Path, force: bool = False,
                   retries: int = 5) -> Path:
    """Stream a URL to disk with retries and an atomic rename."""
    if dest.exists() and not force:
        log.info("cached %s (%s)", dest.name, human_bytes(dest.stat().st_size))
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    delay = 2.0
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=(30, 300)) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                written = 0
                with open(tmp, "wb") as fh:
                    bar = progress(r.iter_content(chunk_size=1 << 20),
                                   desc=f"  {dest.name}",
                                   total=(total >> 20) + 1 if total else None,
                                   unit="MB")
                    for chunk in bar:
                        fh.write(chunk)
                        written += len(chunk)
            if total and written < total:
                raise IOError(f"short read: {written} of {total} bytes")
            tmp.replace(dest)
            log.info("downloaded %s (%s)", dest.name, human_bytes(dest.stat().st_size))
            return dest
        except Exception as exc:  # network flakiness is expected
            tmp.unlink(missing_ok=True)
            if attempt == retries:
                raise
            import time
            log.warning("attempt %d/%d for %s failed (%s); retrying in %.0fs",
                        attempt, retries, dest.name, exc, delay)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


# --------------------------------------------------------------------------
# Overture
# --------------------------------------------------------------------------
def _bbox_stat_columns(metadata) -> dict[str, int]:
    cols = {c["path_in_schema"]: i
            for i, c in enumerate(metadata.row_group(0).to_dict()["columns"])}
    return {k: cols[k] for k in ("bbox.xmin", "bbox.xmax", "bbox.ymin", "bbox.ymax")}


def _matching_row_groups(metadata, bbox) -> list[int]:
    lon_min, lon_max, lat_min, lat_max = bbox
    ix = _bbox_stat_columns(metadata)
    out = []
    for rg in range(metadata.num_row_groups):
        g = metadata.row_group(rg)
        xmax = g.column(ix["bbox.xmax"]).statistics.max
        xmin = g.column(ix["bbox.xmin"]).statistics.min
        ymax = g.column(ix["bbox.ymax"]).statistics.max
        ymin = g.column(ix["bbox.ymin"]).statistics.min
        if xmax >= lon_min and xmin <= lon_max and ymax >= lat_min and ymin <= lat_max:
            out.append(rg)
    return out


def _read_overture_type(overture_type: str, columns: list[str], dest: Path,
                        bbox=SF_BBOX, force: bool = False,
                        prefix: str = sources.OVERTURE_PREFIX) -> Path:
    """Row-group-pruned read of one Overture type (any theme)."""
    import fsspec
    import pyarrow as pa
    import pyarrow.parquet as pq

    if dest.exists() and not force:
        log.info("cached %s (%s)", dest.name, human_bytes(dest.stat().st_size))
        return dest

    keys = _list_s3_keys(sources.OVERTURE_BUCKET, f"{prefix}/type={overture_type}/")
    log.info("overture %s: %d parquet files in release %s",
             overture_type, len(keys), sources.OVERTURE_RELEASE)

    fs = fsspec.filesystem("https")

    def scan(key: str):
        url = f"{sources.OVERTURE_BUCKET}/{key}"
        with fs.open(url, block_size=8 << 20) as fh:
            md = pq.ParquetFile(fh).metadata
            return key, _matching_row_groups(md, bbox)

    with step(f"scanning {len(keys)} {overture_type} footers for the SF bbox", log):
        with ThreadPoolExecutor(max_workers=16) as pool:
            scanned = list(pool.map(scan, keys))
    hits = [(k, rgs) for k, rgs in scanned if rgs]
    n_rg = sum(len(r) for _, r in hits)
    log.info("overture %s: %d row group(s) in %d file(s) intersect SF",
             overture_type, n_rg, len(hits))
    if not hits:
        raise RuntimeError(f"no Overture {overture_type} row groups intersect {bbox}")

    tables = []
    for key, rgs in progress(hits, desc=f"  reading {overture_type}", unit="file"):
        url = f"{sources.OVERTURE_BUCKET}/{key}"
        with fs.open(url, block_size=16 << 20) as fh:
            t = pq.ParquetFile(fh).read_row_groups(rgs, columns=columns)
        tables.append(t)
    table = pa.concat_tables(tables)

    # Row groups are coarse; clip precisely to the study bbox.
    bb = table.column("bbox").combine_chunks()
    xmin = np.asarray(bb.field("xmin")); xmax = np.asarray(bb.field("xmax"))
    ymin = np.asarray(bb.field("ymin")); ymax = np.asarray(bb.field("ymax"))
    lon_min, lon_max, lat_min, lat_max = bbox
    keep = ((xmax >= lon_min) & (xmin <= lon_max)
            & (ymax >= lat_min) & (ymin <= lat_max))
    table = table.filter(pa.array(keep))
    log.info("overture %s: %d features inside the study bbox", overture_type,
             table.num_rows)

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(dest)
    log.info("wrote %s (%s)", dest.name, human_bytes(dest.stat().st_size))
    return dest


def download_street_network(force: bool = False) -> tuple[Path, Path]:
    seg = _read_overture_type("segment", SEGMENT_COLUMNS, SEGMENTS_PARQUET, force=force)
    con = _read_overture_type("connector", CONNECTOR_COLUMNS, CONNECTORS_PARQUET,
                              force=force)
    return seg, con


def download_places(force: bool = False) -> tuple[Path, Path]:
    """Places and addresses for the route page's offline search.

    Neither is needed by the analysis; the route page degrades to
    intersection-only search when they are missing.
    """
    places = _read_overture_type("place", PLACE_COLUMNS, PLACES_PARQUET,
                                 force=force, prefix=sources.OVERTURE_PLACES_PREFIX)
    addrs = _read_overture_type("address", ADDRESS_COLUMNS, ADDRESSES_PARQUET,
                                force=force, prefix=sources.OVERTURE_ADDRESSES_PREFIX)
    for typ, dest in BASE_PARQUETS.items():
        _read_overture_type(typ, BASE_COLUMNS, dest, force=force,
                            prefix=sources.OVERTURE_BASE_PREFIX)
    return places, addrs


# --------------------------------------------------------------------------
# Elevation
# --------------------------------------------------------------------------
def _projected_bounds(bbox, crs: str, pad_m: float = 300.0) -> tuple[float, float, float, float]:
    """Axis-aligned bounds of a lon/lat box in ``crs``, padded in metres."""
    from pyproj import Transformer

    lon_min, lon_max, lat_min, lat_max = bbox
    t = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    corners = [(lon_min, lat_min), (lon_min, lat_max),
               (lon_max, lat_min), (lon_max, lat_max)]
    xs, ys = zip(*(t.transform(lon, lat) for lon, lat in corners))
    return (min(xs) - pad_m, min(ys) - pad_m, max(xs) + pad_m, max(ys) + pad_m)


def _lidar_cog_urls() -> list[str]:
    """1 m lidar COGs for the Greater New Orleans project over the parish."""
    lon_min, lon_max, lat_min, lat_max = SF_BBOX
    r = requests.get(
        "https://tnmaccess.nationalmap.gov/api/v1/products",
        params={
            "datasets": "Digital Elevation Model (DEM) 1 meter",
            "bbox": f"{lon_min},{lat_min},{lon_max},{lat_max}",
            "q": sources.LIDAR_PROJECT,
            "max": "200",
            "outputFormat": "JSON",
        },
        timeout=120,
    )
    r.raise_for_status()
    urls = []
    for item in r.json().get("items", []):
        href = item.get("downloadURL") or ""
        title = item.get("title") or ""
        if sources.LIDAR_PROJECT not in href and sources.LIDAR_PROJECT not in title:
            continue
        if not href.endswith(".tif"):
            continue
        urls.append(href)
    urls = sorted(set(urls))
    if not urls:
        raise RuntimeError(
            f"no {sources.LIDAR_PROJECT} 1 m tiles intersect {SF_BBOX}")
    return urls


def _write_lidar_overview(url: str, dest: Path) -> Path:
    """Read a 1 m COG at its 8 m overview and store it in EPSG:26915.

    Cloud-optimised overviews mean this is a few range requests, not the
    whole 300–500 MB tile. Averaging eight metres of bare-earth lidar is
    the parish-scale product; the 1 m grid itself is not what a block-long
    street grade needs.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import Affine, array_bounds
    from rasterio.warp import calculate_default_transform, reproject

    from .config import CRS_PROJECTED

    nodata = -9999.0
    configure_gdal_for_proxy()
    with rasterio.open("/vsicurl/" + url) as src:
        overviews = src.overviews(1) or [8]
        factor = 8 if 8 in overviews else min(overviews, key=lambda f: abs(f - 8))
        height = max(1, src.height // factor)
        width = max(1, src.width // factor)
        raw = src.read(1, out_shape=(height, width),
                       resampling=Resampling.average, masked=True)
        data = np.asarray(raw.filled(nodata), dtype="float32")
        bad = ~np.isfinite(data) | (data < -50) | (data > 200)
        # The image service (not these COGs) emits the smallest float32 as a
        # fake elevation. Drop anything that small if it ever appears.
        bad |= (np.abs(data) > 0) & (np.abs(data) < 1e-6)
        data[bad] = np.float32(nodata)
        transform = src.transform * Affine.scale(src.width / width, src.height / height)
        crs = src.crs
    if crs is None or crs.to_epsg() != 26915:
        left, bottom, right, top = array_bounds(data.shape[0], data.shape[1], transform)
        dst_transform, dst_w, dst_h = calculate_default_transform(
            crs, CRS_PROJECTED, data.shape[1], data.shape[0],
            left, bottom, right, top, resolution=8)
        warped = np.full((dst_h, dst_w), nodata, dtype="float32")
        reproject(data, warped, src_transform=transform, src_crs=crs,
                  src_nodata=nodata, dst_transform=dst_transform,
                  dst_crs=CRS_PROJECTED, dst_nodata=nodata,
                  resampling=Resampling.bilinear)
        data, transform, crs = warped, dst_transform, CRS_PROJECTED
    profile = {
        "driver": "GTiff", "height": data.shape[0], "width": data.shape[1],
        "count": 1, "dtype": "float32", "crs": crs, "transform": transform,
        "nodata": nodata, "compress": "lzw", "tiled": True,
        "blockxsize": 256, "blockysize": 256,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.tif")
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(data, 1)
    tmp.replace(dest)
    return dest


def download_dem(force: bool = False, include_seamless: bool = True) -> list[Path]:
    """Fetch 8 m overviews of the Greater New Orleans 1 m lidar COGs.

    ``include_seamless`` is accepted so the upstream call signature still
    works. It is ignored: these overviews are already the lidar, not a
    second-guess DEM.
    """
    del include_seamless
    DEM_DIR.mkdir(parents=True, exist_ok=True)
    # The first cut of this project saved an ImageServer export here. Those
    # files are not the lidar; do not let them into the mosaic.
    for stale in DEM_DIR.glob("3dep_15_*.tif"):
        stale.unlink()
    urls = _lidar_cog_urls()
    log.info("3DEP lidar: %d %s COG(s)", len(urls), sources.LIDAR_PROJECT)
    paths = []
    for url in urls:
        dest = DEM_DIR / (Path(url).stem + "_ovr8.tif")
        if dest.exists() and not force:
            log.info("cached %s (%s)", dest.name, human_bytes(dest.stat().st_size))
            paths.append(dest)
            continue
        log.info("reading 8 m overview of %s", Path(url).name)
        paths.append(_write_lidar_overview(url, dest))
        log.info("wrote %s (%s)", dest.name, human_bytes(dest.stat().st_size))
    return paths


# --------------------------------------------------------------------------
# Neighborhoods
# --------------------------------------------------------------------------
def download_neighborhoods(force: bool = False) -> Path:
    return _download_file(sources.NEIGHBORHOOD_URL, NEIGHBORHOODS_GEOJSON, force=force)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def download_all(force: bool = False) -> dict[str, object]:
    configure_gdal_for_proxy()
    out: dict[str, object] = {}
    with step("downloading street network (Overture)", log):
        out["segments"], out["connectors"] = download_street_network(force=force)
    with step("downloading neighborhood boundaries", log):
        out["neighborhoods"] = download_neighborhoods(force=force)
    with step("downloading places and addresses (Overture)", log):
        try:
            out["places"], out["addresses"] = download_places(force=force)
        except Exception as exc:  # optional: the route page can do without
            log.warning("places/addresses unavailable (%s); the route page "
                        "will offer intersection search only", exc)
    with step("downloading USGS 3DEP elevation", log):
        out["dem"] = download_dem(force=force)
    return out
