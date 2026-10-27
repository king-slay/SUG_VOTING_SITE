"""Set up, reset and report on a practice (mock) SUG election.

    python manage.py practice_election setup     # roll + election + candidates, opened
    python manage.py practice_election warmup    # download and load the face models
    python manage.py practice_election open      # start voting (registration closes)
    python manage.py practice_election close     # stop voting and publish results
    python manage.py practice_election report    # numbers for the findings sheet
    python manage.py practice_election reset     # wipe votes so the run can be repeated

The practice election is found by its title, so these commands never touch a
real election.
"""

import re
import statistics
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from voting.models import AuditLog, Candidate, Election, Participation, Position, Vote, Voter
from voting.roll import import_roll

TITLE = "SUG Practice Election"
DEFAULT_ROLL = Path(settings.BASE_DIR) / "practice" / "practice_roll.csv"

# Made-up candidates. Positions mirror a real UNN SUG ballot, cut down to three.
BALLOT = [
    ("President", [
        ("Chinedu Okeke", "Mechanical Engineering", "A working shuttle timetable and 24-hour reading rooms in exam season."),
        ("Amaka Nwosu", "Law", "Student welfare desk in every faculty and a published SUG budget each semester."),
    ]),
    ("Vice President", [
        ("Tunde Bakare", "Economics", "Regular town halls and faster complaint handling."),
        ("Ifeoma Eze", "Medicine and Surgery", "Better hostel water and power, tracked publicly."),
    ]),
    ("General Secretary", [
        ("Emeka Udeh", "Mass Communication", "Minutes of every SUG meeting online within a week."),
        ("Zainab Musa", "Computer Science", "One portal for SUG notices instead of scattered WhatsApp groups."),
    ]),
]

AUDIT_ACTIONS = [
    ("registered", "Registrations"),
    ("register_duplicate_face", "Registrations refused: same face as another student"),
    ("accredited", "Accreditations (face matched)"),
    ("vote_cast", "Ballots cast (face matched again)"),
    ("face_mismatch", "Face did not match"),
    ("face_closer_to_other", "Rejected: face closer to another registered student"),
    ("spoof_rejected", "Liveness check rejected (photo/screen)"),
    ("face_not_read", "No face found / photo unreadable"),
]


class Command(BaseCommand):
    help = "Set up, warm up, report on or reset the practice election."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["setup", "warmup", "open", "close", "report", "reset"])
        parser.add_argument("--roll", default=str(DEFAULT_ROLL), help="Voter roll CSV for setup.")
        parser.add_argument(
            "--faces", action="store_true",
            help="With reset: also clear every student's face registration so they register again.",
        )

    def handle(self, action, **options):
        getattr(self, action)(**options)

    def setup(self, roll, **_):
        path = Path(roll)
        if not path.exists():
            raise CommandError(f"Voter roll not found: {path}")
        result = import_roll(SimpleUploadedFile(path.name, path.read_bytes()))
        if not result.ok:
            raise CommandError("Voter roll rejected:\n  " + "\n  ".join(result.errors))
        self.stdout.write(f"Voter roll: {result.created} added, {result.updated} updated.")

        other = Election.objects.filter(status=Election.OPEN).exclude(title=TITLE).first()
        if other:
            raise CommandError(f"'{other}' is open. Close it in /admin/ first.")

        with transaction.atomic():
            election, created = Election.objects.get_or_create(title=TITLE)
            for order, (title, candidates) in enumerate(BALLOT):
                position, _ = Position.objects.get_or_create(election=election, title=title, defaults={"order": order})
                for name, department, manifesto in candidates:
                    Candidate.objects.get_or_create(
                        position=position, name=name, defaults={"department": department, "manifesto": manifesto}
                    )
            # Leave it in draft: registration closes while an election is open.
            if election.status == Election.CLOSED:
                election.status = Election.DRAFT
                election.save()
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Found'} '{TITLE}' with {len(BALLOT)} positions. "
            "It stays in draft so students can register; run 'practice_election open' when registration is done."
        ))

    def warmup(self, **_):
        """Download and load the models now, so the first student does not wait minutes."""
        import numpy as np
        from deepface import DeepFace

        self.stdout.write("Loading face models (the first time this downloads about 250 MB)...")
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        DeepFace.build_model(settings.FACE_MODEL)
        try:
            DeepFace.represent(
                img_path=blank, model_name=settings.FACE_MODEL, detector_backend=settings.FACE_DETECTOR,
                enforce_detection=False, anti_spoofing=settings.FACE_ANTI_SPOOFING,
            )
        except ValueError:
            pass  # a blank frame may be flagged as a spoof; the models are loaded either way
        self.stdout.write(self.style.SUCCESS("Face models ready."))

    def _election(self):
        election = Election.objects.filter(title=TITLE).first()
        if election is None:
            raise CommandError("No practice election yet. Run setup first.")
        return election

    def open(self, **_):
        election = self._election()
        other = Election.objects.filter(status=Election.OPEN).exclude(pk=election.pk).first()
        if other:
            raise CommandError(f"'{other}' is open. Close it in /admin/ first.")
        election.status = Election.OPEN
        election.save()
        AuditLog.objects.create(action="election_opened", detail=election.title)
        registered = Voter.objects.exclude(registered_at=None).count()
        self.stdout.write(self.style.SUCCESS(f"Voting is open. {registered} students registered. Registration is now closed."))

    def close(self, **_):
        election = self._election()
        election.status = Election.CLOSED
        election.results_public = True
        election.save()
        AuditLog.objects.create(action="election_closed", detail=election.title)
        self.stdout.write(self.style.SUCCESS(f"Voting closed. Public results: /results/{election.pk}/"))

    def reset(self, faces, **_):
        election = self._election()
        with transaction.atomic():
            votes = Vote.objects.filter(election=election).delete()[0]
            voted = Participation.objects.filter(election=election).delete()[0]
            election.status = Election.DRAFT
            election.results_public = False
            election.save()
            AuditLog.objects.create(action="practice_reset", detail=f"{voted} ballots removed")
            cleared = 0
            if faces:
                for voter in Voter.objects.exclude(registered_at=None):
                    if voter.face_photo:
                        voter.face_photo.delete(save=False)
                    voter.face_embedding = None
                    voter.registered_at = None
                    voter.save()
                    cleared += 1
        self.stdout.write(self.style.SUCCESS(
            f"Removed {voted} ballots ({votes} votes); election back in draft."
            + (f" Cleared {cleared} face registrations." if faces else "")
        ))

    def report(self, **_):
        election = self._election()
        # Only count audit entries since the last reset.
        last_reset = AuditLog.objects.filter(action="practice_reset").first()
        entries = AuditLog.objects.all()
        if last_reset:
            entries = entries.filter(created_at__gt=last_reset.created_at)

        out = self.stdout.write
        out(f"\n{TITLE}: {election.get_status_display()}")
        out(f"Students on roll: {Voter.objects.count()}, registered: {Voter.objects.exclude(registered_at=None).count()}, "
            f"voted: {Participation.objects.filter(election=election).count()}\n")
        for action, label in AUDIT_ACTIONS:
            out(f"  {entries.filter(action=action).count():>4}  {label}")

        matched = self._distances(entries.filter(action__in=["accredited", "vote_cast"]))
        mismatched = self._distances(entries.filter(action__in=["face_mismatch", "face_closer_to_other"]))
        out(f"\nFace match threshold: {settings.FACE_MATCH_THRESHOLD}")
        for label, values in (("Accepted scans", matched), ("Rejected scans", mismatched)):
            if values:
                out(f"  {label}: {len(values)}, distance min {min(values):.3f} / "
                    f"median {statistics.median(values):.3f} / max {max(values):.3f}")
        attempts = len(matched) + len(mismatched)
        if attempts:
            out(f"  Wrong-face rejections: {len(mismatched)} of {attempts} scans "
                f"({100 * len(mismatched) / attempts:.0f}%). Check each in /staff/audit/: a real student "
                "rejected is a false rejection (FRR), an impostor rejected is a correct one.")

        out(f"\nDuplicate-face threshold: {settings.FACE_DUPLICATE_THRESHOLD}")
        for action, label in (("registered", "Registered, closest other face"),
                              ("register_duplicate_face", "Refused as duplicate")):
            for entry in entries.filter(action=action).exclude(detail=""):
                out(f"  {label}: {entry.reg_number} {entry.detail}")

        out("\nResults:")
        for position in election.positions.all():
            counts = ", ".join(f"{c.name} {c.votes.count()}" for c in position.candidates.all())
            out(f"  {position.title}: {counts}")

    @staticmethod
    def _distances(entries):
        values = []
        for detail in entries.values_list("detail", flat=True):
            match = re.search(r"distance ([0-9.]+)", detail)
            if match:
                values.append(float(match.group(1)))
        return values
