from __future__ import annotations

from pathlib import Path
from typing import List

from jsonschema import Draft202012Validator, RefResolver

from .util import load_yaml, load_json

class ValidationError(Exception):
    pass

def validate_table(table_yaml: Path, schema_json: Path, common_schema_json: Path) -> None:
    instance = load_yaml(table_yaml)
    schema = load_json(schema_json)
    common = load_json(common_schema_json)

    store = {
        # allow refs by filename (as used in our generated schemas)
        "table_common.schema.json": common,
        schema.get("$id", schema_json.name): schema,
    }

    resolver = RefResolver(base_uri=schema_json.resolve().as_uri(), referrer=schema, store=store)
    Draft202012Validator(schema, resolver=resolver).validate(instance)

def validate_all_tables(src_tables_dir: Path, src_schemas_dir: Path) -> None:
    common_schema = src_schemas_dir / "table_common.schema.json"
    if not common_schema.exists():
        raise FileNotFoundError(f"Missing common schema: {common_schema}")

    yamls = sorted(src_tables_dir.glob("table-*.yaml"))
    if not yamls:
        raise FileNotFoundError(f"No table YAML files found in {src_tables_dir}")

    errors: List[str] = []
    for y in yamls:
        schema = src_schemas_dir / f"{y.stem}.schema.json"
        if not schema.exists():
            errors.append(f"Missing schema for {y.name}: expected {schema.name}")
            continue
        try:
            validate_table(y, schema, common_schema)
        except Exception as e:
            errors.append(f"{y.name}: {e}")

    if errors:
        msg = "Table validation failed:\n- " + "\n- ".join(errors)
        raise ValidationError(msg)

    print(f"Validated {len(yamls)} tables OK.")
