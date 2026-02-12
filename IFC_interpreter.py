from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import ifcopenshell
import ifcopenshell.validate as ifc_validate


def find_ifc_files(directory: Path, recursive: bool = False) -> list[Path]:
    if recursive:
        files = [path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() == ".ifc"]
    else:
        files = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".ifc"]
    return sorted(files, key=lambda p: p.name.lower())


def format_issue(issue: dict) -> str:
    level = str(issue.get("level", "unknown")).upper()
    issue_type = issue.get("type")
    attribute = issue.get("attribute")
    instance = issue.get("instance")
    message = str(issue.get("message", "")).strip().replace("\n", " ")

    extras = []
    if issue_type:
        extras.append(f"type={issue_type}")
    if attribute:
        extras.append(f"attribute={attribute}")
    if instance:
        extras.append(f"instance={instance}")

    prefix = f"[{level}]"
    if extras:
        prefix = f"{prefix} ({', '.join(extras)})"
    return f"{prefix} {message}"


def write_report(path: Path, lines: list[str]) -> Path:
    report_path = path.with_name(f"{path.stem}_VERIFICATION.txt")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def validate_ifc_file(path: Path, express_rules: bool, max_issues: int) -> tuple[int, Path]:
    report_lines: list[str] = [f"=== {path.name} ==="]
    print(f"\n=== {path.name} ===")

    try:
        model = ifcopenshell.open(str(path))
        schema = getattr(model, "schema", "unknown")
        open_line = f"open: OK (schema={schema})"
        print(open_line)
        report_lines.append(open_line)
    except Exception as exc:
        fail_line = f"open: FAIL ({type(exc).__name__}: {exc})"
        print(fail_line)
        report_lines.append(fail_line)
        return 1, write_report(path, report_lines)

    logger = ifc_validate.json_logger()
    try:
        ifc_validate.validate(str(path), logger, express_rules=express_rules)
    except Exception as exc:
        fail_line = f"validate: FAIL ({type(exc).__name__}: {exc})"
        print(fail_line)
        report_lines.append(fail_line)
        return 1, write_report(path, report_lines)

    levels = Counter(str(item.get("level", "unknown")).lower() for item in logger.statements)
    total_findings = sum(levels.values())
    error_count = levels.get("error", 0)
    warning_count = levels.get("warning", 0)

    validate_line = (
        "validate: OK "
        f"(findings={total_findings}, errors={error_count}, warnings={warning_count}, by_level={dict(levels)})"
    )
    print(validate_line)
    report_lines.append(validate_line)

    for issue in logger.statements[:max_issues]:
        issue_line = f"- {format_issue(issue)}"
        print(issue_line)
        report_lines.append(issue_line)

    if total_findings > max_issues:
        more_line = f"- ... and {total_findings - max_issues} more findings"
        print(more_line)
        report_lines.append(more_line)

    return (1 if error_count > 0 else 0), write_report(path, report_lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Weryfikacja wszystkich plikow IFC z wybranego folderu."
    )
    parser.add_argument(
        "--directory",
        default=".",
        help="Folder z plikami IFC (domyslnie: katalog projektu).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Szukaj plikow IFC rekurencyjnie.",
    )
    parser.add_argument(
        "--express-rules",
        action="store_true",
        help="Uruchom dodatkowe reguly EXPRESS (pelniejsza walidacja).",
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        default=10,
        help="Maksymalna liczba wypisanych problemow na plik.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    directory = Path(args.directory).resolve()

    if not directory.exists() or not directory.is_dir():
        print(f"Blad: folder nie istnieje lub nie jest katalogiem: {directory}")
        return 2

    if args.max_issues < 1:
        print("Blad: --max-issues musi byc >= 1")
        return 2

    ifc_files = find_ifc_files(directory, recursive=args.recursive)
    if not ifc_files:
        print(f"Nie znaleziono plikow IFC w folderze: {directory}")
        return 2

    print(f"Znalezione pliki IFC: {len(ifc_files)}")
    print(f"Tryb EXPRESS rules: {'ON' if args.express_rules else 'OFF'}")

    invalid_files = 0
    report_files: list[Path] = []
    for ifc_file in ifc_files:
        invalid, report_path = validate_ifc_file(ifc_file, args.express_rules, args.max_issues)
        invalid_files += invalid
        report_files.append(report_path)

    print("\n=== PODSUMOWANIE ===")
    print(f"Sprawdzone pliki: {len(ifc_files)}")
    print(f"Pliki niepoprawne: {invalid_files}")
    print(f"Pliki poprawne: {len(ifc_files) - invalid_files}")
    print("Raporty:")
    for report in report_files:
        print(f"- {report}")

    return 1 if invalid_files > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
