"""Electoral committee pages: dashboard, voter roll, elections and candidates,
live results, audit log, committee accounts."""

import csv

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .audit import log
from .forms import CandidateForm, CommitteeMemberForm, ElectionForm, PositionForm, RollUploadForm
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
    level = request.GET.get("level", "")
    status = request.GET.get("status", "")
    if query:
        voters = voters.filter(
            Q(reg_number__icontains=query) | Q(full_name__icontains=query) | Q(department__icontains=query)
        )
    if faculty:
        voters = voters.filter(faculty=faculty)
    if level:
        voters = voters.filter(level=level)
    if status == "registered":
        voters = voters.exclude(registered_at=None)
    elif status == "not_registered":
        voters = voters.filter(registered_at=None)
    return voters, {"q": query, "faculty": faculty, "level": level, "status": status}


def describe_filters(filters):
    parts = []
    if filters["q"]:
        parts.append(f'matching "{filters["q"]}"')
    if filters["faculty"]:
        parts.append(f"in {filters['faculty']}")
    if filters["level"]:
        parts.append(f"at {filters['level']} level")
    if filters["status"]:
        parts.append(ROLL_STATUS[filters["status"]].lower())
    return ", ".join(parts)


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
            "levels": sorted(set(Voter.objects.values_list("level", flat=True)), key=lambda l: (len(l), l)),
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


def delete_voters(voters):
    """Remove students from the roll with their face photos. Past turnout figures are kept."""
    for photo in voters.exclude(face_photo="").values_list("face_photo", flat=True):
        Voter.face_photo.field.storage.delete(photo)
    return voters.delete()[1].get("voting.Voter", 0)


@committee_required
@require_POST
def voter_remove(request, voter_id):
    voter = get_object_or_404(Voter, pk=voter_id)
    if Election.current():
        messages.error(request, "Students cannot be removed while voting is open.")
        return redirect("staff_voter", voter.pk)
    log(request, "voter_removed", voter.full_name, voter.reg_number)
    delete_voters(Voter.objects.filter(pk=voter.pk))
    messages.success(request, f"{voter.full_name} ({voter.reg_number}) was removed from the voter roll.")
    return redirect("staff_roll")


@committee_required
def roll_remove(request):
    """Remove every student the roll filters select (e.g. one level), or the whole roll.
    The committee confirms by typing how many students will go."""
    voters, filters = filtered_roll(request)
    count = voters.count()
    description = describe_filters(filters)
    querystring = request.GET.urlencode()
    if Election.current():
        messages.error(request, "Students cannot be removed while voting is open. Close the election first.")
        return redirect(f"{reverse('staff_roll')}?{querystring}")
    error = ""
    if request.method == "POST":
        if request.POST.get("confirm", "").strip() != str(count):
            error = f"Type {count} to confirm."
        else:
            removed = delete_voters(voters)
            log(request, "roll_removed", f"{removed} students" + (f" {description}" if description else " (whole roll)"))
            messages.success(request, f"{removed} student{'s' if removed != 1 else ''} removed from the voter roll.")
            return redirect("staff_roll")
    return render(request, "staff/roll_remove.html", {
        "count": count, "description": description, "querystring": querystring, "error": error,
        "sample": voters[:10], "whole_roll": not description,
    })


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


# ---------- Committee accounts ----------
# Every committee member has their own account. Chairs can add members, reset their
# passwords and switch accounts off; everyone can change their own password.


def chair_required(view):
    @committee_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Only a chair can manage committee accounts.")
            return redirect("staff_dashboard")
        return view(request, *args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


@chair_required
def committee(request):
    members = User.objects.filter(is_staff=True).order_by("-is_active", "-is_superuser", "username")
    return render(request, "staff/committee.html", {"members": members})


@chair_required
def committee_new(request):
    form = CommitteeMemberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        member = form.save()
        log(request, "committee_added", f"{member.username} ({'chair' if member.is_superuser else 'member'})")
        messages.success(request, f"Account {member.username} created. Give them the password; they can change it after signing in.")
        return redirect("staff_committee")
    return render(request, "staff/form.html", {"form": form, "heading": "Add a committee member", "submit": "Create account", "back_url": "staff_committee"})


@chair_required
def committee_password(request, user_id):
    member = get_object_or_404(User, pk=user_id, is_staff=True)
    form = SetPasswordForm(member, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        if member == request.user:
            update_session_auth_hash(request, member)
        log(request, "committee_password_reset", member.username)
        messages.success(request, f"New password set for {member.username}.")
        return redirect("staff_committee")
    return render(request, "staff/form.html", {"form": form, "heading": f"New password for {member.username}", "submit": "Set password", "back_url": "staff_committee"})


@chair_required
@require_POST
def committee_change(request, user_id):
    member = get_object_or_404(User, pk=user_id, is_staff=True)
    action = request.POST.get("action")
    if member == request.user:
        messages.error(request, "You cannot switch off or demote your own account. Ask another chair.")
        return redirect("staff_committee")
    changes = {
        "disable": ("is_active", False, "switched off"),
        "enable": ("is_active", True, "switched back on"),
        "chair": ("is_superuser", True, "made a chair"),
        "member": ("is_superuser", False, "made an ordinary member"),
    }
    if action not in changes:
        return redirect("staff_committee")
    field, value, words = changes[action]
    setattr(member, field, value)
    member.save(update_fields=[field])
    log(request, f"committee_{action}", member.username)
    messages.success(request, f"{member.username} {words}.")
    return redirect("staff_committee")


@committee_required
def my_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, form.user)
        log(request, "committee_password_changed", request.user.username)
        messages.success(request, "Your password has been changed.")
        return redirect("staff_dashboard")
    return render(request, "staff/form.html", {"form": form, "heading": "Change my password", "submit": "Change password"})
