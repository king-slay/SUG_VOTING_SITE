"""Electoral committee pages: dashboard, voter roll, elections and candidates,
live results, audit log."""

import csv

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .audit import log
from .forms import CandidateForm, ElectionForm, PositionForm, RollUploadForm
from .models import AuditLog, Candidate, Election, Position, Voter
from .results import tally, turnout
from .roll import REQUIRED_HEADERS, import_roll


def committee_required(view):
    """Committee members sign in on the site's own page rather than the Django admin's."""
    return staff_member_required(view, login_url="staff_login")


def csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # so Excel opens names with accents correctly
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


@committee_required
def dashboard(request):
    voters = Voter.objects.all()
    election = Election.current() or Election.objects.first()
    return render(
        request,
        "staff/dashboard.html",
        {
            "roll_count": voters.count(),
            "registered_count": voters.exclude(registered_at=None).count(),
            "election": election,
            "turnout": turnout(election) if election else None,
            "elections": Election.objects.all(),
        },
    )


@committee_required
def roll_upload(request):
    form = RollUploadForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == "POST" and form.is_valid():
        result = import_roll(form.cleaned_data["file"])
        if result.ok:
            log(request, "roll_uploaded", f"{result.created} added, {result.updated} updated")
            messages.success(
                request, f"Voter roll uploaded: {result.created} students added, {result.updated} updated."
            )
            return redirect("staff_roll")
    return render(
        request,
        "staff/roll_upload.html",
        {"form": form, "result": result, "headers": REQUIRED_HEADERS},
    )


@committee_required
def roll_template(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="voter_roll_template.csv"'
    writer = csv.writer(response)
    writer.writerow(REQUIRED_HEADERS)
    writer.writerow(["Ada Obi", "2021/245678", "Physical Sciences", "Computer Science", "200"])
    return response


ROLL_STATUS = {"registered": "Registered", "not_registered": "Not registered"}


def filtered_roll(request):
    voters = Voter.objects.all()
    query = request.GET.get("q", "").strip()
    faculty = request.GET.get("faculty", "")
    status = request.GET.get("status", "")
    if query:
        voters = voters.filter(
            Q(reg_number__icontains=query) | Q(full_name__icontains=query) | Q(department__icontains=query)
        )
    if faculty:
        voters = voters.filter(faculty=faculty)
    if status == "registered":
        voters = voters.exclude(registered_at=None)
    elif status == "not_registered":
        voters = voters.filter(registered_at=None)
    return voters, {"q": query, "faculty": faculty, "status": status}


@committee_required
def roll_list(request):
    voters, filters = filtered_roll(request)
    page = Paginator(voters, 50).get_page(request.GET.get("page"))
    querystring = request.GET.copy()
    querystring.pop("page", None)
    return render(
        request,
        "staff/roll_list.html",
        {
            "page": page,
            "filters": filters,
            "querystring": querystring.urlencode(),
            "faculties": Voter.objects.order_by("faculty").values_list("faculty", flat=True).distinct(),
            "statuses": ROLL_STATUS,
            "total": Voter.objects.count(),
        },
    )


@committee_required
def roll_export(request):
    voters, _ = filtered_roll(request)
    return csv_response(
        "voter_roll.csv",
        REQUIRED_HEADERS + ["email", "phone", "registered_at"],
        (
            [v.full_name, v.reg_number, v.faculty, v.department, v.level, v.email, v.phone,
             v.registered_at.strftime("%Y-%m-%d %H:%M") if v.registered_at else ""]
            for v in voters
        ),
    )


@committee_required
def voter_detail(request, voter_id):
    voter = get_object_or_404(Voter, pk=voter_id)
    return render(
        request,
        "staff/voter_detail.html",
        {
            "voter": voter,
            "voted_in": voter.participations.select_related("election"),
            "history": AuditLog.objects.filter(reg_number=voter.reg_number)[:20],
            "registration_open": Election.current() is None,
        },
    )


@committee_required
@require_POST
def voter_reset_face(request, voter_id):
    voter = get_object_or_404(Voter, pk=voter_id)
    if voter.face_photo:
        voter.face_photo.delete(save=False)
    voter.face_embedding = None
    voter.registered_at = None
    voter.save()
    log(request, "registration_reset", reg_number=voter.reg_number)
    messages.success(request, f"Face registration cleared. {voter.full_name} can register again.")
    return redirect("staff_voter", voter.pk)


@committee_required
@require_POST
def voter_remove(request, voter_id):
    voter = get_object_or_404(Voter, pk=voter_id)
    if voter.participations.exists():
        messages.error(request, "This student has already voted, so they stay on the roll for the record.")
        return redirect("staff_voter", voter.pk)
    if voter.face_photo:
        voter.face_photo.delete(save=False)
    log(request, "voter_removed", voter.full_name, voter.reg_number)
    voter.delete()
    messages.success(request, f"{voter.full_name} ({voter.reg_number}) was removed from the voter roll.")
    return redirect("staff_roll")


# ---------- Elections, positions and candidates ----------


def editable_or_redirect(request, election):
    """Positions and candidates are frozen once voting opens, so the ballot never changes under voters."""
    if election.is_editable:
        return None
    messages.error(request, "Positions and candidates cannot change after voting has opened.")
    return redirect("staff_election", election.pk)


@committee_required
def election_new(request):
    form = ElectionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        election = form.save()
        log(request, "election_created", election.title)
        messages.success(request, "Election created. Now add its positions and candidates.")
        return redirect("staff_election", election.pk)
    return render(request, "staff/form.html", {"form": form, "heading": "New election", "submit": "Create election",
                                               "back": "staff_dashboard"})


@committee_required
def election_detail(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    positions = election.positions.prefetch_related("candidates")
    return render(
        request,
        "staff/election.html",
        {
            "election": election,
            "positions": positions,
            "problems": election.open_problems() if election.is_editable else [],
            "turnout": turnout(election),
            "rename_form": ElectionForm(instance=election),
        },
    )


@committee_required
@require_POST
def election_rename(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    form = ElectionForm(request.POST, instance=election)
    if form.is_valid():
        form.save()
        messages.success(request, "Election renamed.")
    else:
        messages.error(request, "Enter a title for the election.")
    return redirect("staff_election", election.pk)


@committee_required
@require_POST
def election_status(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    action = request.POST.get("action")
    if action == "open":
        problems = election.open_problems()
        if problems:
            for problem in problems:
                messages.error(request, problem)
        else:
            election.status = Election.OPEN
            election.save()
            log(request, "election_opened", election.title)
            messages.success(request, "Voting is open. Student registration is now closed.")
    elif action == "close" and election.status == Election.OPEN:
        election.status = Election.CLOSED
        election.save()
        log(request, "election_closed", election.title)
        messages.success(request, "Voting is closed. Publish the results when you are ready.")
    elif action in ("publish", "unpublish") and election.status == Election.CLOSED:
        election.results_public = action == "publish"
        election.save()
        log(request, f"results_{action}ed", election.title)
        messages.success(request, "Results are now public." if election.results_public else "Results are hidden again.")
    else:
        messages.error(request, "That change is not possible for this election right now.")
    return redirect("staff_election", election.pk)


@committee_required
@require_POST
def election_delete(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    if not election.is_editable:
        messages.error(request, "Only a draft election can be deleted.")
        return redirect("staff_election", election.pk)
    log(request, "election_deleted", election.title)
    election.delete()
    messages.success(request, f"{election.title} was deleted.")
    return redirect("staff_dashboard")


@committee_required
def position_form(request, election_id=None, position_id=None):
    if position_id:
        position = get_object_or_404(Position, pk=position_id)
        election = position.election
    else:
        position = None
        election = get_object_or_404(Election, pk=election_id)
    blocked = editable_or_redirect(request, election)
    if blocked:
        return blocked
    initial = {} if position else {"order": election.positions.count() + 1}
    form = PositionForm(request.POST or None, instance=position, initial=initial, election=election)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{form.instance.title} saved.")
        return redirect("staff_election", election.pk)
    return render(request, "staff/form.html", {
        "form": form, "election": election,
        "heading": f"Edit {position.title}" if position else "Add a position",
        "submit": "Save position", "back_election": election,
    })


@committee_required
@require_POST
def position_delete(request, position_id):
    position = get_object_or_404(Position, pk=position_id)
    blocked = editable_or_redirect(request, position.election)
    if blocked:
        return blocked
    position.delete()
    messages.success(request, f"{position.title} and its candidates were removed.")
    return redirect("staff_election", position.election.pk)


@committee_required
def candidate_form(request, position_id=None, candidate_id=None):
    if candidate_id:
        candidate = get_object_or_404(Candidate, pk=candidate_id)
        position = candidate.position
    else:
        candidate = None
        position = get_object_or_404(Position, pk=position_id)
    election = position.election
    blocked = editable_or_redirect(request, election)
    if blocked:
        return blocked
    form = CandidateForm(request.POST or None, request.FILES or None, instance=candidate)
    if request.method == "POST" and form.is_valid():
        candidate = form.save(commit=False)
        candidate.position = position
        candidate.save()
        messages.success(request, f"{candidate.name} saved as a candidate for {position.title}.")
        return redirect("staff_election", election.pk)
    return render(request, "staff/form.html", {
        "form": form, "election": election, "multipart": True,
        "heading": f"Edit {candidate.name}" if candidate else f"Add a candidate for {position.title}",
        "submit": "Save candidate", "back_election": election,
    })


@committee_required
@require_POST
def candidate_delete(request, candidate_id):
    candidate = get_object_or_404(Candidate, pk=candidate_id)
    election = candidate.position.election
    blocked = editable_or_redirect(request, election)
    if blocked:
        return blocked
    if candidate.photo:
        candidate.photo.delete(save=False)
    candidate.delete()
    messages.success(request, f"{candidate.name} was removed.")
    return redirect("staff_election", election.pk)


# ---------- Results and audit ----------


@committee_required
def results(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    return render(
        request,
        "staff/results.html",
        {"election": election, "results": tally(election), "turnout": turnout(election)},
    )


@committee_required
def results_json(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    return JsonResponse(
        {
            "turnout": turnout(election),
            "positions": [
                {
                    "id": r["position"].pk,
                    "cast": r["cast"],
                    "rows": [
                        {"id": row["candidate"].pk, "votes": row["votes"], "percent": row["percent"]}
                        for row in r["rows"]
                    ],
                }
                for r in tally(election)
            ],
        }
    )


@committee_required
def results_export(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    rows = [
        [r["position"].title, row["candidate"].name, row["candidate"].department, row["votes"], row["percent"],
         "yes" if row["leading"] else ""]
        for r in tally(election)
        for row in r["rows"]
    ]
    t = turnout(election)
    rows.append([])
    rows.append(["Turnout", f"{t['voted']} of {t['registered']} registered voters", "", t["voted"], t["percent"], ""])
    return csv_response(
        f"results-{slugify(election.title) or election.pk}.csv",
        ["position", "candidate", "department", "votes", "percent", "leading"],
        rows,
    )


@committee_required
def audit_log(request):
    entries = AuditLog.objects.select_related("user")
    query = request.GET.get("q", "").strip()
    if query:
        entries = entries.filter(reg_number__icontains=query) | entries.filter(action__icontains=query)
    page = Paginator(entries, 50).get_page(request.GET.get("page"))
    return render(request, "staff/audit.html", {"page": page, "query": query})
