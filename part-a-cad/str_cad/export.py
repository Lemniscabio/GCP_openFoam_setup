import json
import pathlib

import cadquery as cq
import trimesh

from .geometry.assembly import REGION_NAMES, build_fluid_domain
from .schema import STRParams


def _export_region(shape: cq.Shape, path: pathlib.Path) -> None:
    # Linear (chordal) deflection scaled with the region size. A fixed absolute
    # tolerance makes curved surfaces (e.g. a dished bottom) explode into millions
    # of triangles on large vessels — a 20 m tank produced a 24 MB STL in ~40 s,
    # which times out the web preview. Scaling keeps the triangle budget roughly
    # constant with size; the floor keeps small vessels at the original fidelity.
    bbox = shape.BoundingBox()
    size = max(bbox.xlen, bbox.ylen, bbox.zlen, 1.0)
    # Floor 1e-4 keeps small/reference vessels (size <= ~10 m) at the original fidelity
    # (watertight), so only larger vessels are coarsened.
    tolerance = min(max(size * 1e-5, 1e-4), 5e-3)
    shape.exportStl(
        str(path),
        tolerance=tolerance,
        angularTolerance=0.1,
        relative=False,
        parallel=False,
    )
    mesh = trimesh.load(str(path), process=False)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    mesh.export(str(path))


def export_geometry(p: STRParams, out_dir) -> pathlib.Path:
    out_dir = pathlib.Path(out_dir)
    geometry_dir = out_dir / "geometry"
    geometry_dir.mkdir(parents=True, exist_ok=True)

    regions = build_fluid_domain(p)
    for name in REGION_NAMES:
        _export_region(regions[name], geometry_dir / f"{name}.stl")

    params = json.dumps(p.model_dump(mode="json"), indent=2)
    (out_dir / "str-params.json").write_text(params)
    return out_dir
