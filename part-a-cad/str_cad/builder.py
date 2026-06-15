import json
import pathlib
import sys

from .export import export_geometry
from .schema import STRParams


def build_from_schema_file(schema_path, out_dir) -> pathlib.Path:
    schema = json.loads(pathlib.Path(schema_path).read_text())
    params = STRParams.model_validate(schema)
    export_geometry(params, out_dir)
    return pathlib.Path(out_dir)


if __name__ == "__main__":
    output_dir = build_from_schema_file(sys.argv[1], sys.argv[2])
    print(output_dir)
