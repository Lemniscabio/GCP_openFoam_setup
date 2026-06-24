#!/usr/bin/env python3
"""Generate single-phase OpenFOAM stirred-tank cases for parameter sweeps.

Varies: RPM, kinematic viscosity, and fill volume.
For each combination, creates a self-contained case directory.

Usage:
    python generate_cases.py --rpm 50 100 150 --nu 1e-6 1e-5 --fill 22 11 --np 9
"""

import argparse
import json
import math
import re
import shutil
import sys
from itertools import product
from pathlib import Path

# Geometry constants (from the original tank geometry)
TANK_RADIUS = 1.04                  # m, effective fill radius
IMPELLER_Z = [1.12, 2.58, 4.04, 5.50]  # z-centers (m) of 4 impellers
ROTOR_Z = [(0.724, 1.250), (2.184, 2.710),
           (3.644, 4.170), (5.104, 5.630)]
ROTOR_R = 0.42                      # m, MRF zone radius
SAFETY_MARGIN = 0.15                # m, impeller must be submerged by this much
                                    # 0.07 m blade half-height + 0.08 m margin;
                                    # prevents blade tip from poking through LiquidLevel

# blockMesh defaults
BLOCKMESH_MINZ = -0.025
BLOCKMESH_CELL_SIZE = 0.0405        # m, original avg cell size in z
HEADSPACE_MARGIN = 0.0              # m — LiquidLevel is the blockMesh 'top' face at maxZ;
                                    # createPatch renames it to LiquidLevel after snappyHexMesh.

THIS_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = THIS_DIR / "template"
RUNS_DIR = THIS_DIR / "foam_runs"


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def fill_height(volume_m3: float) -> float:
    """Liquid height for a given fill volume in a cylindrical tank."""
    return volume_m3 / (math.pi * TANK_RADIUS**2)


def active_impellers(h_fill: float) -> list[int]:
    """Return 1-based indices of impellers that are submerged."""
    return [i + 1 for i, z in enumerate(IMPELLER_Z)
            if z + SAFETY_MARGIN < h_fill]


def rpm_to_rad_s(rpm: float) -> float:
    return rpm * 2.0 * math.pi / 60.0


# ---------------------------------------------------------------------------
# Block-level dictionary editing (handles nested braces)
# ---------------------------------------------------------------------------

def remove_named_block(text: str, name: str) -> str:
    """Remove every top-level dictionary block named *name* from *text*.

    Each block is matched at any indentation as
        <indent><name>\\s*{ ... matching } ...
    Brace depth is tracked so nested {} are handled correctly.
    All occurrences in *text* are removed.
    """
    pattern = re.compile(
        rf'^([ \t]*){re.escape(name)}[ \t]*\r?\n?[ \t]*\{{',
        re.MULTILINE,
    )
    while True:
        m = pattern.search(text)
        if not m:
            return text
        start = m.start()
        i = m.end() - 1  # position of opening '{'
        depth = 0
        removed = False
        while i < len(text):
            c = text[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    while end < len(text) and text[end] in ' \t':
                        end += 1
                    if end < len(text) and text[end] == '\n':
                        end += 1
                    text = text[:start] + text[end:]
                    removed = True
                    break
            i += 1
        if not removed:
            return text  # malformed


# ---------------------------------------------------------------------------
# Per-file editors
# ---------------------------------------------------------------------------

def edit_mrf_properties(path: Path, rpm: float, active: list[int]) -> None:
    text = path.read_text()
    # Remove inactive impeller blocks
    for i in range(1, 5):
        if i not in active:
            text = remove_named_block(text, f"Rotor_Impeller{i}")
    # Set omega
    text = re.sub(
        r'omega\s+[\d.]+\s*\[rpm\]\s*;',
        f'omega      {rpm} [rpm];',
        text,
    )
    path.write_text(text)


def edit_physical_properties(path: Path, nu: float) -> None:
    text = path.read_text()
    # Replace nu value, preserving dimensions
    text = re.sub(
        r'(nu\s+\[\s*0\s+2\s+-1\s+0\s+0\s+0\s+0\s*\]\s*)\S+\s*;',
        rf'\g<1>{nu};',
        text,
    )
    path.write_text(text)


def edit_U_field(path: Path, rpm: float, active: list[int]) -> None:
    text = path.read_text()
    # Set Shaft omega in rad/s
    omega_rad = rpm_to_rad_s(rpm)
    text = re.sub(
        r'(omega\s+constant\s+)[\d.eE+-]+\s*;',
        rf'\g<1>{omega_rad:.6f};',
        text,
    )
    # Remove inactive impeller BC blocks
    for i in range(1, 5):
        if i not in active:
            text = remove_named_block(text, f"Impeller_{i}")
    path.write_text(text)


def edit_scalar_field(path: Path, active: list[int]) -> None:
    """Remove inactive impeller BC blocks from a scalar 0/ field."""
    text = path.read_text()
    for i in range(1, 5):
        if i not in active:
            text = remove_named_block(text, f"Impeller_{i}")
    path.write_text(text)


def edit_block_mesh(path: Path, h_fill: float) -> None:
    """Set maxZ and Nz in blockMeshDict."""
    new_maxZ = h_fill + HEADSPACE_MARGIN
    new_Nz = max(20, round((new_maxZ - BLOCKMESH_MINZ) / BLOCKMESH_CELL_SIZE))
    text = path.read_text()
    text = re.sub(r'maxZ\s+[\d.eE+-]+\s*;', f'maxZ  {new_maxZ:.4f};', text)
    text = re.sub(r'\bNz\s+\d+\s*;', f'Nz {new_Nz};', text)
    path.write_text(text)


def edit_topo_set(path: Path, active: list[int]) -> None:
    """Write system/topoSetDict with cylinderToCell actions for active MRF zones.

    Each active impeller i (1-based) gets a cellZone MRF_Rotor{i} built from
    ROTOR_Z[i-1] and ROTOR_R.  Inactive impellers are simply omitted so topoSet
    does not create empty zones that MRFProperties would complain about.
    """
    header = """\
/*--------------------------------*- C++ -*----------------------------------*\\
  =========                 |
  \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\\\    /   O peration     | Website:  https://openfoam.org
    \\\\  /    A nd           | Version:  12
     \\\\/     M anipulation  |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    format      ascii;
    class       dictionary;
    object      topoSetDict;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

// MRF rotor cell zones built from exact cylinder geometry.
// Replaces STL-derived zones (wrong z-extents) from snappyHexMesh.
// Run after createPatch, before decomposePar.

actions
(
"""
    footer = """\
);

// ************************************************************************* //
"""
    action_tpl = """\
    {{
        name    MRF_Rotor{i};
        type    cellZoneSet;
        action  new;
        source  cylinderToCell;
        point1  (0 0 {z0});
        point2  (0 0 {z1});
        radius  {r};
    }}

"""
    actions = ""
    for i in active:
        z0, z1 = ROTOR_Z[i - 1]
        actions += action_tpl.format(i=i, z0=z0, z1=z1, r=ROTOR_R)

    path.write_text(header + actions + footer)


def edit_snappy_hex_mesh(path: Path, h_fill: float, active: list[int]) -> None:
    """Remove inactive Impeller_N and Rotor_ImpellerN entries from all sections.
    Also adjusts locationInMesh to stay inside the (possibly shorter) domain."""
    text = path.read_text()
    for i in range(1, 5):
        if i not in active:
            text = remove_named_block(text, f"Impeller_{i}")
            text = remove_named_block(text, f"Rotor_Impeller{i}")
    # locationInMesh: keep it safely inside the liquid (avoid shaft + impellers)
    safe_z = max(0.3, min(h_fill / 2.0, IMPELLER_Z[0] - 0.2))
    text = re.sub(
        r'locationInMesh\s+\([^)]+\)\s*;',
        f'locationInMesh ( 0.5 0 {safe_z:.4f} );',
        text,
    )
    path.write_text(text)



# ---------------------------------------------------------------------------
# Case generation
# ---------------------------------------------------------------------------

def generate_case(case_dir: Path, rpm: float, nu: float, V_fill: float) -> dict:
    """Build a complete OpenFOAM case in *case_dir* for the given parameters."""
    h_fill = fill_height(V_fill)
    active = active_impellers(h_fill)
    if not active:
        raise ValueError(
            f"Fill volume {V_fill} m^3 (h={h_fill:.3f} m) leaves no impellers "
            f"submerged (need at least one). Minimum is "
            f"{math.pi*TANK_RADIUS**2*(IMPELLER_Z[0]+SAFETY_MARGIN):.2f} m^3."
        )

    # Wipe + copy template
    if case_dir.exists():
        shutil.rmtree(case_dir)
    shutil.copytree(TEMPLATE_DIR, case_dir)

    # Edit constant/
    edit_mrf_properties(case_dir / "constant" / "MRFProperties", rpm, active)
    edit_physical_properties(case_dir / "constant" / "physicalProperties", nu)

    # Edit 0/
    edit_U_field(case_dir / "0" / "U", rpm, active)
    for f in ("p", "k", "epsilon", "nut"):
        edit_scalar_field(case_dir / "0" / f, active)

    # Edit system/
    edit_block_mesh(case_dir / "system" / "blockMeshDict", h_fill)
    edit_snappy_hex_mesh(case_dir / "system" / "snappyHexMeshDict",
                         h_fill, active)
    edit_topo_set(case_dir / "system" / "topoSetDict", active)

    # Remove unused impeller STLs (clean rather than confusing)
    for i in range(1, 5):
        if i not in active:
            for name in (f"Impeller_{i}.stl", f"Rotor_Impeller{i}.stl"):
                p = case_dir / "constant" / "triSurface" / name
                if p.exists():
                    p.unlink()

    params = {
        "rpm": rpm,
        "nu": nu,
        "fill_volume": V_fill,
        "fill_height": round(h_fill, 4),
        "active_impellers": active,
    }
    (case_dir / "params.json").write_text(json.dumps(params, indent=2) + "\n")
    return params


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def write_run_script(case_dir: Path, params: dict, np_cores: int) -> None:
    """Write a self-contained run.sh inside *case_dir*.

    Intended to be uploaded to a single compute instance (e.g. a GCE VM)
    and executed there. The script cd's to its own location so it can be
    invoked from anywhere.
    """
    lines = [
        "#!/bin/bash",
        "# Generated by generate_cases.py",
        f"# rpm={params['rpm']}  nu={params['nu']}  V={params['fill_volume']} m^3"
        f"  active_impellers={params['active_impellers']}",
        "set -e",
        'cd "$(dirname "$0")"',
        "",
        "blockMesh > log.blockMesh 2>&1",
        "snappyHexMesh -overwrite > log.snappyHexMesh 2>&1",
        "createPatch -overwrite > log.createPatch 2>&1",
        "topoSet > log.topoSet 2>&1",
        "decomposePar > log.decomposePar 2>&1",
        f"mpirun -np {np_cores} foamRun -parallel > log.foamRun 2>&1",
        "reconstructPar -latestTime > log.reconstructPar 2>&1",
        "",
    ]
    run_sh = case_dir / "run.sh"
    run_sh.write_text("\n".join(lines))
    run_sh.chmod(0o755)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rpm", type=float, nargs="+", required=True,
                    help="Impeller RPM values to sweep")
    ap.add_argument("--nu", type=float, nargs="+", required=True,
                    help="Kinematic viscosity values (m^2/s) to sweep")
    ap.add_argument("--fill", type=float, nargs="+", required=True,
                    help="Fill volumes (m^3) to sweep")
    ap.add_argument("--np", type=int, default=9,
                    help="MPI processes for foamRun (default: 9)")
    args = ap.parse_args()

    if not TEMPLATE_DIR.is_dir():
        sys.exit(f"Template directory missing: {TEMPLATE_DIR}")

    RUNS_DIR.mkdir(exist_ok=True)

    combos = list(product(args.rpm, args.nu, args.fill))
    runs_map: dict[str, dict] = {}

    for n, (rpm, nu, V) in enumerate(combos):
        case_dir = RUNS_DIR / str(n)
        params = generate_case(case_dir, rpm, nu, V)
        write_run_script(case_dir, params, args.np)
        runs_map[str(n)] = params
        print(f"[{n+1}/{len(combos)}] dir={n}  rpm={rpm}  nu={nu}  V={V} m^3 "
              f"-> h={params['fill_height']} m, impellers={params['active_impellers']}")

    (THIS_DIR / "runs_map.json").write_text(
        json.dumps(runs_map, indent=2) + "\n"
    )

    print(f"\nGenerated {len(combos)} case(s) under {RUNS_DIR}")
    print(f"Map written to {THIS_DIR / 'runs_map.json'}")
    print(f"Each case has its own run.sh (upload the case dir to a VM and execute).")


if __name__ == "__main__":
    main()
