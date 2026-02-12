from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.placement
import ifcopenshell.util.schema
import ifcopenshell.util.unit
import numpy as np


EPS = 1e-9


@dataclass
class LegPlacement:
    leg: ifcopenshell.entity_instance
    axis_start: np.ndarray
    axis_end: np.ndarray
    center_at_height: np.ndarray
    insertion_point: np.ndarray
    direction: np.ndarray
    radial_offset: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wstawia antene z pliku ANTENA.ifc na segment w pliku SEGMENT.ifc."
    )
    parser.add_argument("--segment-ifc", default="SEGMENT.ifc", help="Plik IFC segmentu.")
    parser.add_argument("--antenna-ifc", default="ANTENA.ifc", help="Plik IFC z antena do skopiowania.")
    parser.add_argument(
        "--output-ifc",
        default="SEGMENT_WITH_ANTENNA.ifc",
        help="Plik wyjsciowy IFC po wstawieniu anteny.",
    )
    parser.add_argument(
        "--height-m",
        type=float,
        default=3.0,
        help="Wysokosc osadzenia anteny w metrach (domyslnie 3.0).",
    )
    parser.add_argument(
        "--azimuth-deg",
        type=float,
        default=123.0,
        help="Azymut CCW od osi X w stopniach (domyslnie 123.0).",
    )
    parser.add_argument(
        "--leg-index",
        type=int,
        default=0,
        help="Index nogi (kolumny) wsrod kandydatow przecinajacych zadana wysokosc.",
    )
    return parser.parse_args()


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm < EPS:
        raise ValueError("Nie mozna znormalizowac wektora o zerowej dlugosci.")
    return vector / norm


def read_polycurve_points(curve: ifcopenshell.entity_instance) -> list[np.ndarray]:
    points: list[np.ndarray] = []
    if curve.is_a("IfcIndexedPolyCurve"):
        for xyz in curve.Points.CoordList:
            values = [float(v) for v in xyz]
            if len(values) == 2:
                values.append(0.0)
            points.append(np.array(values, dtype=float))
    elif curve.is_a("IfcPolyline"):
        for point in curve.Points:
            coords = [float(v) for v in point.Coordinates]
            if len(coords) == 2:
                coords.append(0.0)
            points.append(np.array(coords, dtype=float))
    return points


def get_column_axis_points(column: ifcopenshell.entity_instance) -> tuple[np.ndarray, np.ndarray]:
    if not column.IsTypedBy:
        raise ValueError(f"Kolumna #{column.id()} nie ma przypisanego typu.")

    column_type = column.IsTypedBy[0].RelatingType
    for representation_map in column_type.RepresentationMaps or []:
        representation = representation_map.MappedRepresentation
        if representation.RepresentationIdentifier != "Axis":
            continue
        if not representation.Items:
            continue
        curve = representation.Items[0]
        points = read_polycurve_points(curve)
        if len(points) < 2:
            continue
        return points[0], points[-1]

    raise ValueError(f"Nie znaleziono osi dla kolumny #{column.id()}.")


def get_column_profile_info(column: ifcopenshell.entity_instance) -> tuple[float, float]:
    if not column.IsTypedBy:
        return 0.0, 0.0

    column_type = column.IsTypedBy[0].RelatingType
    solid: ifcopenshell.entity_instance | None = None
    for representation_map in column_type.RepresentationMaps or []:
        representation = representation_map.MappedRepresentation
        if representation.RepresentationIdentifier != "Body":
            continue
        for item in representation.Items:
            if item.is_a("IfcExtrudedAreaSolid"):
                solid = item
                break
        if solid:
            break

    if not solid:
        return 0.0, 0.0

    profile = solid.SweptArea
    outer_radius = 0.0
    inner_radius = 0.0

    if hasattr(profile, "OuterCurve") and profile.OuterCurve:
        outer_points = read_polycurve_points(profile.OuterCurve)
        if outer_points:
            outer_radius = max(float(np.linalg.norm(point[:2])) for point in outer_points)

    inner_curves = getattr(profile, "InnerCurves", None) or []
    if inner_curves:
        first_inner_points = read_polycurve_points(inner_curves[0])
        if first_inner_points:
            inner_radius = max(float(np.linalg.norm(point[:2])) for point in first_inner_points)

    return outer_radius, inner_radius


def compute_leg_placement(
    segment_model: ifcopenshell.file, target_height_model_units: float, leg_index: int
) -> LegPlacement:
    candidates: list[LegPlacement] = []
    global_up = np.array([0.0, 0.0, 1.0], dtype=float)

    for column in segment_model.by_type("IfcColumn"):
        try:
            axis_start, axis_end = get_column_axis_points(column)
        except ValueError:
            continue

        delta = axis_end - axis_start
        if abs(delta[2]) < EPS:
            continue

        t = (target_height_model_units - axis_start[2]) / delta[2]
        if t < 0.0 or t > 1.0:
            continue

        direction = normalize(delta)
        center = axis_start + t * delta

        radial_dir = np.cross(global_up, direction)
        if np.linalg.norm(radial_dir) < EPS:
            radial_dir = np.cross(np.array([1.0, 0.0, 0.0], dtype=float), direction)
        radial_dir = normalize(radial_dir)

        outer_radius, inner_radius = get_column_profile_info(column)
        if outer_radius > 0.0 and inner_radius > 0.0 and inner_radius < outer_radius:
            radial_offset = (outer_radius + inner_radius) * 0.5
        elif outer_radius > 0.0:
            radial_offset = outer_radius * 0.5
        else:
            radial_offset = 0.0

        insertion = center + radial_dir * radial_offset
        candidates.append(
            LegPlacement(
                leg=column,
                axis_start=axis_start,
                axis_end=axis_end,
                center_at_height=center,
                insertion_point=insertion,
                direction=direction,
                radial_offset=radial_offset,
            )
        )

    if not candidates:
        raise ValueError("Nie znaleziono nogi segmentu (IfcColumn) przecinajacej zadana wysokosc.")
    if leg_index < 0 or leg_index >= len(candidates):
        raise ValueError(f"Niepoprawny --leg-index={leg_index}. Dostepny zakres: 0..{len(candidates)-1}.")

    return candidates[leg_index]


def find_source_antenna(antenna_model: ifcopenshell.file) -> ifcopenshell.entity_instance:
    antennas = antenna_model.by_type("IfcCommunicationsAppliance")
    if not antennas:
        raise ValueError("W pliku z antena nie znaleziono IfcCommunicationsAppliance.")

    for antenna in antennas:
        predefined = str(getattr(antenna, "PredefinedType", "") or "")
        if predefined.upper() == "ANTENNA":
            return antenna
    return antennas[0]


def first_owner_history(model: ifcopenshell.file) -> ifcopenshell.entity_instance | None:
    histories = model.by_type("IfcOwnerHistory")
    return histories[0] if histories else None


def create_axis_placement(
    model: ifcopenshell.file,
    reference_placement: ifcopenshell.entity_instance | None,
    point_world: np.ndarray,
    x_world: np.ndarray,
    z_world: np.ndarray,
) -> ifcopenshell.entity_instance:
    if reference_placement:
        reference_matrix = ifcopenshell.util.placement.get_local_placement(reference_placement)
    else:
        reference_matrix = np.identity(4)

    inverse_reference = np.linalg.inv(reference_matrix)
    point_h = np.array([point_world[0], point_world[1], point_world[2], 1.0], dtype=float)
    point_local = inverse_reference @ point_h

    rotation_inverse = inverse_reference[:3, :3]
    x_local = normalize(rotation_inverse @ x_world)
    z_local = normalize(rotation_inverse @ z_world)

    if abs(float(np.dot(x_local, z_local))) > 0.999:
        raise ValueError("Wektory orientacji sa prawie rownolegle.")

    location = model.createIfcCartesianPoint((float(point_local[0]), float(point_local[1]), float(point_local[2])))
    axis = model.createIfcDirection((float(z_local[0]), float(z_local[1]), float(z_local[2])))
    ref_direction = model.createIfcDirection((float(x_local[0]), float(x_local[1]), float(x_local[2])))
    return model.createIfcAxis2Placement3D(location, axis, ref_direction)


def copy_inverse_relations(
    source_model: ifcopenshell.file,
    target_model: ifcopenshell.file,
    source_antenna: ifcopenshell.entity_instance,
    target_antenna: ifcopenshell.entity_instance,
    migrator: ifcopenshell.util.schema.Migrator,
) -> None:
    owner_history = first_owner_history(target_model) or target_antenna.OwnerHistory
    migrated_type_cache: dict[int, ifcopenshell.entity_instance] = {}

    for relation in source_model.get_inverse(source_antenna):
        if relation.is_a("IfcRelDefinesByType"):
            source_type = relation.RelatingType
            target_type = migrated_type_cache.get(source_type.id())
            if target_type is None:
                target_type = migrator.migrate(source_type, target_model)
                migrated_type_cache[source_type.id()] = target_type

            target_model.create_entity(
                "IfcRelDefinesByType",
                GlobalId=ifcopenshell.guid.new(),
                OwnerHistory=owner_history,
                Name=relation.Name,
                Description=relation.Description,
                RelatedObjects=[target_antenna],
                RelatingType=target_type,
            )

        elif relation.is_a("IfcRelDefinesByProperties"):
            target_pset = migrator.migrate(relation.RelatingPropertyDefinition, target_model)
            target_model.create_entity(
                "IfcRelDefinesByProperties",
                GlobalId=ifcopenshell.guid.new(),
                OwnerHistory=owner_history,
                Name=relation.Name,
                Description=relation.Description,
                RelatedObjects=[target_antenna],
                RelatingPropertyDefinition=target_pset,
            )

        elif relation.is_a("IfcRelAssociatesMaterial"):
            target_material = migrator.migrate(relation.RelatingMaterial, target_model)

            related_objects: list[ifcopenshell.entity_instance] = []
            for source_related in relation.RelatedObjects:
                if source_related.id() == source_antenna.id():
                    related_objects.append(target_antenna)
                elif source_related.is_a("IfcTypeObject"):
                    related_objects.append(migrator.migrate(source_related, target_model))

            if related_objects:
                target_model.create_entity(
                    "IfcRelAssociatesMaterial",
                    GlobalId=ifcopenshell.guid.new(),
                    OwnerHistory=owner_history,
                    Name=relation.Name,
                    Description=relation.Description,
                    RelatedObjects=related_objects,
                    RelatingMaterial=target_material,
                )


def attach_to_container(
    model: ifcopenshell.file,
    container: ifcopenshell.entity_instance,
    product: ifcopenshell.entity_instance,
) -> None:
    if getattr(container, "ContainsElements", None):
        relation = container.ContainsElements[0]
        current = list(relation.RelatedElements or [])
        if product not in current:
            current.append(product)
            relation.RelatedElements = current
        return

    owner_history = first_owner_history(model) or product.OwnerHistory
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=owner_history,
        Name=None,
        Description=None,
        RelatedElements=[product],
        RelatingStructure=container,
    )


def refresh_migrated_root_guids(target_model: ifcopenshell.file, migrator: ifcopenshell.util.schema.Migrator) -> None:
    for target_id in migrator.migrated_ids.values():
        entity = target_model.by_id(target_id)
        if entity and entity.is_a("IfcRoot"):
            entity.GlobalId = ifcopenshell.guid.new()


def remove_if_orphan(model: ifcopenshell.file, entity: ifcopenshell.entity_instance | None) -> None:
    if not entity:
        return
    if model.get_inverse(entity):
        return
    model.remove(entity)


def harmonize_migrated_owner_history(
    target_model: ifcopenshell.file,
    migrator: ifcopenshell.util.schema.Migrator,
    target_owner_history: ifcopenshell.entity_instance | None,
) -> None:
    if not target_owner_history:
        return

    migrated_entities: list[ifcopenshell.entity_instance] = []
    for target_id in migrator.migrated_ids.values():
        entity = target_model.by_id(target_id)
        if entity:
            migrated_entities.append(entity)

    migrated_owner_histories: set[ifcopenshell.entity_instance] = set()
    for entity in migrated_entities:
        if entity.is_a("IfcOwnerHistory"):
            migrated_owner_histories.add(entity)
        if entity.is_a("IfcRoot"):
            owner_history = entity.OwnerHistory
            if owner_history and owner_history != target_owner_history:
                migrated_owner_histories.add(owner_history)
            entity.OwnerHistory = target_owner_history

    # Remove migrated OwnerHistory objects that are no longer referenced, and their metadata if orphaned.
    for owner_history in migrated_owner_histories:
        if owner_history == target_owner_history:
            continue
        if target_model.get_inverse(owner_history):
            continue

        owning_application = owner_history.OwningApplication
        owning_user = owner_history.OwningUser
        person = owning_user.ThePerson if owning_user else None
        organization = owning_user.TheOrganization if owning_user else None

        target_model.remove(owner_history)
        remove_if_orphan(target_model, owning_application)
        remove_if_orphan(target_model, owning_user)
        remove_if_orphan(target_model, person)
        remove_if_orphan(target_model, organization)


def main() -> int:
    args = parse_args()

    segment_path = Path(args.segment_ifc)
    antenna_path = Path(args.antenna_ifc)
    output_path = Path(args.output_ifc)

    if not segment_path.exists():
        print(f"Blad: nie znaleziono pliku segmentu: {segment_path}")
        return 2
    if not antenna_path.exists():
        print(f"Blad: nie znaleziono pliku anteny: {antenna_path}")
        return 2
    if args.height_m <= 0:
        print("Blad: --height-m musi byc > 0.")
        return 2

    segment_model = ifcopenshell.open(str(segment_path))
    antenna_model = ifcopenshell.open(str(antenna_path))

    unit_scale_to_si = ifcopenshell.util.unit.calculate_unit_scale(segment_model)
    target_height_units = args.height_m / unit_scale_to_si

    leg_placement = compute_leg_placement(segment_model, target_height_units, args.leg_index)
    if not leg_placement.leg.ContainedInStructure:
        print(f"Blad: noga #{leg_placement.leg.id()} nie jest przypisana do struktury przestrzennej.")
        return 2
    target_container = leg_placement.leg.ContainedInStructure[0].RelatingStructure

    source_antenna = find_source_antenna(antenna_model)
    migrator = ifcopenshell.util.schema.Migrator()
    target_antenna = migrator.migrate(source_antenna, segment_model)

    target_owner_history = first_owner_history(segment_model)
    if target_owner_history:
        target_antenna.OwnerHistory = target_owner_history

    azimuth_rad = math.radians(args.azimuth_deg)
    azimuth_x_world = np.array([math.cos(azimuth_rad), math.sin(azimuth_rad), 0.0], dtype=float)
    azimuth_z_world = np.array([0.0, 0.0, 1.0], dtype=float)

    axis_placement = create_axis_placement(
        model=segment_model,
        reference_placement=target_container.ObjectPlacement,
        point_world=leg_placement.insertion_point,
        x_world=azimuth_x_world,
        z_world=azimuth_z_world,
    )
    target_antenna.ObjectPlacement = segment_model.createIfcLocalPlacement(target_container.ObjectPlacement, axis_placement)

    copy_inverse_relations(
        source_model=antenna_model,
        target_model=segment_model,
        source_antenna=source_antenna,
        target_antenna=target_antenna,
        migrator=migrator,
    )
    attach_to_container(segment_model, target_container, target_antenna)
    refresh_migrated_root_guids(segment_model, migrator)
    harmonize_migrated_owner_history(segment_model, migrator, target_owner_history)
    target_antenna.GlobalId = ifcopenshell.guid.new()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    segment_model.write(str(output_path))

    print("Wstawienie zakonczone.")
    print(f"Plik wyjsciowy: {output_path}")
    print(f"Noga (IfcColumn): #{leg_placement.leg.id()} | {leg_placement.leg.Name}")
    print(
        "Punkt wstawienia [jednostki modelu]: "
        f"({leg_placement.insertion_point[0]:.3f}, {leg_placement.insertion_point[1]:.3f}, {leg_placement.insertion_point[2]:.3f})"
    )
    print(f"Wysokosc docelowa: {args.height_m:.3f} m")
    print(f"Azymut: {args.azimuth_deg:.3f} deg (CCW od +X)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
