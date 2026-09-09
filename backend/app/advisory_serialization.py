"""JSON-safe serialization for deterministic advisory results.

Money remains integer paise.
Fraction ratios become {"numerator": int, "denominator": int}.
Floats and unsupported objects are rejected.

Use this serializer for both persisted result snapshots and API responses.
Request validation remains the responsibility of strict Pydantic schemas.
"""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from fractions import Fraction


def to_advisory_json(value: object) -> object:
    """Convert engine dataclasses and nested containers to JSON-safe values."""
    return _convert(value, path="$")


def _convert(value: object, path: str) -> object:
    if value is None:
        return None

    # Exact type checks deliberately exclude implicit numeric coercion.
    if type(value) in (str, bool, int):
        return value

    if isinstance(value, Fraction):
        return {
            "numerator": value.numerator,
            "denominator": value.denominator,
        }

    if isinstance(value, float):
        raise TypeError(
            f"{path}: floats are forbidden in advisory payloads; "
            "use integer paise, integer basis points or Fraction"
        )

    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _convert(
                getattr(value, field.name),
                path=f"{path}.{field.name}",
            )
            for field in fields(value)
        }

    if isinstance(value, Mapping):
        result = {}

        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(
                    f"{path}: JSON object keys must be strings, "
                    f"got {type(key).__name__}"
                )

            result[key] = _convert(
                item,
                path=f"{path}[{key!r}]",
            )

        return result

    if isinstance(value, (list, tuple)):
        return [
            _convert(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]

    raise TypeError(
        f"{path}: unsupported advisory value type "
        f"{type(value).__name__}"
    )


def advisory_snapshot(value: object) -> dict:
    """Serialize a result that must be stored as a JSON object.

    Wrap collections explicitly, for example:
        advisory_snapshot({"options": solver_results})

    For Pydantic inputs, pass model_dump(mode="python") explicitly.
    """
    result = to_advisory_json(value)

    if not isinstance(result, dict):
        raise TypeError(
            "An advisory snapshot must be a JSON object, "
            "not a scalar or top-level list"
        )

    return result