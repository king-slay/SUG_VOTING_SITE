"""Voter roll CSV import.

The admin uploads a CSV with exactly these headers (any order, any case):

    full_name, reg_number, faculty, department, level

Existing students (matched by reg_number) are updated; their face
registration is kept. New students are added.
"""

import csv
import io
from dataclasses import dataclass, field

from django.db import transaction

from .models import Voter

REQUIRED_HEADERS = ["full_name", "reg_number", "faculty", "department", "level"]


def normalize(value):
    """Collapse whitespace and ignore case, for cross-checking typed details."""
    return " ".join((value or "").split()).casefold()


def clean_reg_number(value):
    return "".join((value or "").split()).upper()


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors


def import_roll(uploaded_file):
    """Validate the whole file first; write nothing if any row is bad."""
    result = ImportResult()
    try:
        text = uploaded_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        result.errors.append("The file is not UTF-8 text. Save it from Excel as 'CSV UTF-8'.")
        return result

    reader = csv.DictReader(io.StringIO(text))
    headers = [normalize(h).replace(" ", "_") for h in (reader.fieldnames or [])]
    missing = [h for h in REQUIRED_HEADERS if h not in headers]
    if missing:
        result.errors.append(
            f"Missing column(s): {', '.join(missing)}. Required headers: {', '.join(REQUIRED_HEADERS)}."
        )
        return result
    reader.fieldnames = headers

    rows, seen = [], {}
    for line_no, raw in enumerate(reader, start=2):
        row = {h: " ".join((raw.get(h) or "").split()) for h in REQUIRED_HEADERS}
        if not any(row.values()):
            continue
        row["reg_number"] = clean_reg_number(row["reg_number"])
        empty = [h for h in REQUIRED_HEADERS if not row[h]]
        if empty:
            result.errors.append(f"Row {line_no}: empty {', '.join(empty)}.")
            continue
        if row["reg_number"] in seen:
            result.errors.append(
                f"Row {line_no}: reg number {row['reg_number']} already appears on row {seen[row['reg_number']]}."
            )
            continue
        seen[row["reg_number"]] = line_no
        rows.append(row)

    if not rows and not result.errors:
        result.errors.append("The file has headers but no students.")
    if result.errors:
        return result

    with transaction.atomic():
        existing = {v.reg_number: v for v in Voter.objects.filter(reg_number__in=seen)}
        for row in rows:
            voter = existing.get(row["reg_number"])
            if voter is None:
                Voter.objects.create(**row)
                result.created += 1
            else:
                for key in ("full_name", "faculty", "department", "level"):
                    setattr(voter, key, row[key])
                voter.save()
                result.updated += 1
    return result
