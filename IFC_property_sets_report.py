from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import ifcopenshell


@dataclass
class PsetStats:
    definition_count: int = 0
    assigned_items_count: int = 0
    entity_type_counts: Counter[str] = field(default_factory=Counter)
    property_names: set[str] = field(default_factory=set)


def find_ifc_files(directory: Path, recursive: bool = False) -> list[Path]:
    if recursive:
        files = [path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() == ".ifc"]
    else:
        files = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".ifc"]
    return sorted(files, key=lambda p: p.name.lower())


def get_or_create(stats_map: dict[str, PsetStats], pset_name: str) -> PsetStats:
    existing = stats_map.get(pset_name)
    if existing is None:
        existing = PsetStats()
        stats_map[pset_name] = existing
    return existing


def read_name(value: object, fallback: str = "<NO_NAME>") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def collect_pset_stats(model: ifcopenshell.file) -> tuple[dict[str, PsetStats], int, set[int], set[int]]:
    stats_by_name: dict[str, PsetStats] = {}
    pset_id_to_name: dict[int, str] = {}
    defined_ids: set[int] = set()
    assigned_ids: set[int] = set()

    for pset in model.by_type("IfcPropertySet"):
        pset_id = pset.id()
        pset_name = read_name(getattr(pset, "Name", None))
        pset_id_to_name[pset_id] = pset_name
        defined_ids.add(pset_id)

        stats = get_or_create(stats_by_name, pset_name)
        stats.definition_count += 1

        for prop in (getattr(pset, "HasProperties", None) or []):
            prop_name = read_name(getattr(prop, "Name", None), fallback="<UNNAMED_PROPERTY>")
            stats.property_names.add(prop_name)

    for rel in model.by_type("IfcRelDefinesByProperties"):
        definition = getattr(rel, "RelatingPropertyDefinition", None)
        if not definition or not definition.is_a("IfcPropertySet"):
            continue

        pset_id = definition.id()
        pset_name = pset_id_to_name.get(pset_id, read_name(getattr(definition, "Name", None)))
        stats = get_or_create(stats_by_name, pset_name)

        related = getattr(rel, "RelatedObjects", None) or []
        stats.assigned_items_count += len(related)
        for item in related:
            stats.entity_type_counts[item.is_a()] += 1
        assigned_ids.add(pset_id)

    for type_obj in model.by_type("IfcTypeObject"):
        for definition in (getattr(type_obj, "HasPropertySets", None) or []):
            if not definition or not definition.is_a("IfcPropertySet"):
                continue

            pset_id = definition.id()
            pset_name = pset_id_to_name.get(pset_id, read_name(getattr(definition, "Name", None)))
            stats = get_or_create(stats_by_name, pset_name)

            stats.assigned_items_count += 1
            stats.entity_type_counts[type_obj.is_a()] += 1
            assigned_ids.add(pset_id)

    return stats_by_name, len(defined_ids), assigned_ids, defined_ids


def render_report(file_name: str, schema: str, stats_by_name: dict[str, PsetStats], pset_count: int, unassigned_count: int, max_properties: int) -> list[str]:
    lines: list[str] = []
    lines.append(f"FILE: {file_name}")
    lines.append(f"SCHEMA: {schema}")
    lines.append(f"IFCPROPERTYSET_INSTANCES: {pset_count}")
    lines.append(f"UNIQUE_PROPERTYSET_NAMES: {len(stats_by_name)}")
    lines.append(f"UNASSIGNED_IFCPROPERTYSET_INSTANCES: {unassigned_count}")
    lines.append("")
    lines.append("PROPERTY_SETS:")

    if not stats_by_name:
        lines.append("none")
        return lines

    ordered = sorted(stats_by_name.items(), key=lambda item: item[0].casefold())
    for index, (pset_name, stats) in enumerate(ordered, start=1):
        lines.append(f"{index}. {pset_name}")
        lines.append(f"   definitions: {stats.definition_count}")
        lines.append(f"   assigned_items: {stats.assigned_items_count}")

        if stats.entity_type_counts:
            entity_parts = [
                f"{name}:{count}"
                for name, count in sorted(stats.entity_type_counts.items(), key=lambda item: (-item[1], item[0]))
            ]
            lines.append(f"   entity_types: {', '.join(entity_parts)}")
        else:
            lines.append("   entity_types: none")

        property_names = sorted(stats.property_names, key=str.casefold)
        if property_names:
            displayed = property_names[:max_properties]
            suffix = ""
            if len(property_names) > max_properties:
                suffix = f" ... (+{len(property_names) - max_properties} more)"
            lines.append(f"   properties({len(property_names)}): {', '.join(displayed)}{suffix}")
        else:
            lines.append("   properties(0): none")

    return lines


def write_report(report_path: Path, lines: list[str]) -> None:
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report_for_file(ifc_path: Path, max_properties: int, output_dir: Path) -> tuple[bool, Path]:
    report_path = output_dir / f"{ifc_path.stem}_PROPERTYSETS.txt"

    try:
        model = ifcopenshell.open(str(ifc_path))
    except Exception as exc:
        write_report(
            report_path,
            [
                f"FILE: {ifc_path.name}",
                f"open: FAIL ({type(exc).__name__}: {exc})",
            ],
        )
        return False, report_path

    stats_by_name, pset_count, assigned_ids, defined_ids = collect_pset_stats(model)
    lines = render_report(
        file_name=ifc_path.name,
        schema=getattr(model, "schema", "unknown"),
        stats_by_name=stats_by_name,
        pset_count=pset_count,
        unassigned_count=len(defined_ids - assigned_ids),
        max_properties=max_properties,
    )
    write_report(report_path, lines)
    return True, report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tworzy raporty Property Setow dla wszystkich plikow IFC w folderze."
    )
    parser.add_argument(
        "--directory",
        default=".",
        help="Folder z plikami IFC (domyslnie: katalog projektu).",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Folder wyjsciowy raportow txt (domyslnie: katalog projektu).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Szukaj plikow IFC rekurencyjnie.",
    )
    parser.add_argument(
        "--max-properties",
        type=int,
        default=30,
        help="Maksymalna liczba nazw property wypisywanych na jeden Property Set.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    search_dir = Path(args.directory).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not search_dir.exists() or not search_dir.is_dir():
        print(f"Blad: folder z IFC nie istnieje: {search_dir}")
        return 2
    if args.max_properties < 1:
        print("Blad: --max-properties musi byc >= 1")
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    ifc_files = find_ifc_files(search_dir, recursive=args.recursive)
    if not ifc_files:
        print(f"Nie znaleziono plikow IFC w folderze: {search_dir}")
        return 2

    print(f"Znaleziono plikow IFC: {len(ifc_files)}")
    ok_count = 0
    fail_count = 0
    reports: list[Path] = []

    for ifc_path in ifc_files:
        success, report_path = build_report_for_file(ifc_path, max_properties=args.max_properties, output_dir=output_dir)
        reports.append(report_path)
        if success:
            ok_count += 1
            print(f"OK: {ifc_path.name} -> {report_path.name}")
        else:
            fail_count += 1
            print(f"FAIL: {ifc_path.name} -> {report_path.name}")

    print("\nPODSUMOWANIE")
    print(f"Pliki IFC: {len(ifc_files)}")
    print(f"Raporty OK: {ok_count}")
    print(f"Raporty z bledem otwarcia IFC: {fail_count}")
    print("Raporty:")
    for report in reports:
        print(f"- {report}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
