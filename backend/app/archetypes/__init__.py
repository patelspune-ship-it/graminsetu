import json
from pathlib import Path
from types import MappingProxyType

from pydantic import ValidationError

from app.archetypes.schema import Archetype

CONFIG_DIR = Path(__file__).resolve().parent / "configs"


def load_archetypes(directory: Path = CONFIG_DIR):
    files = sorted(directory.glob("*.json"))

    if not files:
        raise RuntimeError(f"No archetype JSON files found in {directory}")

    loaded: dict[str, Archetype] = {}

    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            archetype = Archetype.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(
                f"Invalid archetype configuration: {path}\n{exc}"
            ) from exc

        if path.stem != archetype.id:
            raise RuntimeError(
                f"{path.name}: filename must match archetype id "
                f"{archetype.id!r}"
            )

        if archetype.id in loaded:
            raise RuntimeError(
                f"Duplicate archetype id: {archetype.id}"
            )

        loaded[archetype.id] = archetype

    return MappingProxyType(loaded)


# Import fails immediately if any configuration is invalid.
ARCHETYPES = load_archetypes()


def get_archetype(archetype_id: str) -> Archetype:
    try:
        return ARCHETYPES[archetype_id]
    except KeyError as exc:
        raise KeyError(
            f"Unknown archetype {archetype_id!r}. "
            f"Available: {', '.join(ARCHETYPES)}"
        ) from exc