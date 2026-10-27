"""Student-facing pages: registration, election-day voting, public results."""

import base64
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import faces
from .audit import log
from .forms import RegistrationForm, VoteStartForm
from .models import AuditLog, Election, Participation, Vote, Voter
from .results import tally

MAX_FAILED_SCANS = 5
LOCKOUT_MINUTES = 15
# Audit actions that count towards the lockout: a wrong face, a face that looks more like
# another registered student (e.g. a sibling), or a photo/screen held up to the camera.
FAILED_SCAN_ACTIONS = ("face_mismatch", "face_closer_to_other", "spoof_rejected")
SESSION_KEYS = ("vote_voter_id", "vote_election_id", "vote_verified_at")


def home(request):
    return render(request, "voting/home.html", {"election": Election.current()})


def register(request):
    if Election.current():
        messages.info(request, "Registration is closed while voting is open.")
        return redirect("home")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        voter = form.cleaned_data["voter"]
        try:
            embedding = faces.get_embedding(form.cleaned_data["face_image"])
            others = Voter.objects.exclude(pk=voter.pk).exclude(face_embedding=None)
            duplicate, nearest = faces.find_duplicate(embedding, others)
        except faces.SpoofError as exc:
            log(request, "spoof_rejected", "registration", voter.reg_number)
            form.add_error(None, str(exc))
        except faces.FaceError as exc:
            log(request, "face_not_read", f"registration: {exc}", voter.reg_number)
            form.add_error(None, str(exc))
        else:
            if duplicate:
                log(
                    request, "register_duplicate_face",
                    f"face matches {duplicate.reg_number}, distance {nearest:.3f}", voter.reg_number,
                )
                form.add_error(
                    None,
                    "This face is already registered to another student. Each student can register "
                    "only once. Contact the electoral committee if this is a mistake.",
                )
            else:
                voter.email = form.cleaned_data["email"]
                voter.phone = form.cleaned_data["phone"]
                voter.face_embedding = embedding
                voter.registered_at = timezone.now()
                photo = form.cleaned_data["face_image"].split(",", 1)[-1]
                voter.face_photo.save(f"{uuid.uuid4().hex}.jpg", ContentFile(base64.b64decode(photo)), save=False)
                voter.save()
                # Distance to the most similar face already registered: shows how
                # close look-alikes (e.g. siblings) come to the duplicate threshold.
                detail = f"nearest other face distance {nearest:.3f}" if nearest is not None else ""
                log(request, "registered", detail, voter.reg_number)
                return render(request, "voting/register_done.html", {"voter": voter})

    roll = Voter.objects.all()
    return render(
        request,
        "voting/register.html",
        {
            "form": form,
            "faculties": roll.values_list("faculty", flat=True).distinct().order_by("faculty"),
            "departments": roll.values_list("department", flat=True).distinct().order_by("department"),
            "levels": roll.values_list("level", flat=True).distinct().order_by("level"),
        },
    )


def _too_many_failures(reg_number):
    since = timezone.now() - timedelta(minutes=LOCKOUT_MINUTES)
    return (
        AuditLog.objects.filter(action__in=FAILED_SCAN_ACTIONS, reg_number=reg_number, created_at__gte=since).count()
        >= MAX_FAILED_SCANS
    )


def _check_face(request, voter, data_url):
    """Return (error message or None, face distance or None).

    The distance of a successful match goes into the audit log, so the false
    rejection rate can be measured after a practice run.
    """
    if _too_many_failures(voter.reg_number):
        return f"Too many failed face scans. Try again in {LOCKOUT_MINUTES} minutes or see an electoral officer.", None
    try:
        embedding = faces.get_embedding(data_url)
        ok, dist = faces.matches(voter.face_embedding, embedding)
    except faces.SpoofError as exc:
        log(request, "spoof_rejected", "election day", voter.reg_number)
        return str(exc), None
    except faces.FaceError as exc:
        log(request, "face_not_read", str(exc), voter.reg_number)
        return str(exc), None
    if not ok:
        log(request, "face_mismatch", f"distance {dist:.3f}", voter.reg_number)
        return "Your face did not match the registered face for this registration number. Please try again.", dist
    # A look-alike (e.g. a sibling) can come under the threshold for someone else's
    # registration, but their own registered face is still the closer one.
    other, other_dist = faces.nearest_face(embedding, Voter.objects.exclude(pk=voter.pk).exclude(face_embedding=None))
    if other is not None and other_dist <= dist:
        log(
            request, "face_closer_to_other",
            f"distance {dist:.3f}, but {other_dist:.3f} to {other.reg_number}", voter.reg_number,
        )
        return "Your face did not match the registered face for this registration number. Please try again.", dist
    return None, dist


def vote_start(request):
    election = Election.current()
    if not election:
        messages.info(request, "There is no election open for voting right now.")
        return redirect("home")

    form = VoteStartForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        reg_number = form.cleaned_data["reg_number"]
        voter = Voter.objects.filter(reg_number=reg_number).first()
        if voter is None or not voter.is_registered:
            form.add_error("reg_number", "This registration number is not on the registered voters list.")
        elif Participation.objects.filter(election=election, voter=voter).exists():
            form.add_error("reg_number", "You have already voted in this election.")
        else:
            error, dist = _check_face(request, voter, form.cleaned_data["face_image"])
            if error:
                form.add_error(None, error)
            else:
                request.session.cycle_key()
                request.session["vote_voter_id"] = voter.pk
                request.session["vote_election_id"] = election.pk
                request.session["vote_verified_at"] = timezone.now().isoformat()
                log(request, "accredited", f"distance {dist:.3f}", voter.reg_number)
                return redirect("ballot")
    return render(request, "voting/vote_start.html", {"form": form, "election": election})


def _verified_voter(request):
    """Return (voter, election) for a voter who passed the face scan recently, else (None, None)."""
    voter_id = request.session.get("vote_voter_id")
    verified_at = request.session.get("vote_verified_at")
    election = Election.current()
    if not (voter_id and verified_at and election and election.pk == request.session.get("vote_election_id")):
        return None, None
    age = timezone.now() - datetime.fromisoformat(verified_at)
    if age > timedelta(minutes=settings.VOTE_SESSION_MINUTES):
        return None, None
    return Voter.objects.filter(pk=voter_id).first(), election


def _end_vote_session(request):
    for key in SESSION_KEYS:
        request.session.pop(key, None)


def ballot(request):
    voter, election = _verified_voter(request)
    if voter is None:
        _end_vote_session(request)
        messages.warning(request, "Your session has expired. Please scan your face again.")
        return redirect("vote_start")

    positions = list(election.positions.prefetch_related("candidates"))
    selected, error, dist = {}, None, None

    if request.method == "POST":
        for position in positions:
            value = request.POST.get(f"position_{position.pk}")
            candidate = next((c for c in position.candidates.all() if str(c.pk) == value), None)
            if candidate is None:
                error = f"Please choose a candidate for {position.title}."
                break
            selected[position.pk] = candidate

        if error is None:
            # Re-check the face at the moment of submission, so the person casting the
            # ballot is the person who was accredited.
            error, dist = _check_face(request, voter, request.POST.get("face_image"))

        if error is None:
            try:
                with transaction.atomic():
                    Participation.objects.create(election=election, voter=voter)
                    Vote.objects.bulk_create(
                        Vote(election=election, position_id=pid, candidate=c) for pid, c in selected.items()
                    )
            except IntegrityError:
                error = "You have already voted in this election."
            else:
                log(request, "vote_cast", f"distance {dist:.3f}", voter.reg_number)
                _end_vote_session(request)
                return render(request, "voting/vote_done.html", {"election": election, "voter": voter})

    return render(
        request,
        "voting/ballot.html",
        {
            "election": election,
            "voter": voter,
            "positions": positions,
            "selected": {pid: c.pk for pid, c in selected.items()},
            "error": error,
        },
    )


def public_results(request, election_id):
    election = get_object_or_404(
        Election, pk=election_id, status=Election.CLOSED, results_public=True
    )
    return render(request, "voting/results.html", {"election": election, "results": tally(election)})


def candidate_list(request):
    election = Election.current() or Election.objects.exclude(status=Election.DRAFT).first()
    positions = election.positions.prefetch_related("candidates") if election else []
    return render(request, "voting/candidates.html", {"election": election, "positions": positions})

