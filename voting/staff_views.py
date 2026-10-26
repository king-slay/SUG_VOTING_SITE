"""Electoral committee pages: dashboard, voter roll upload, live results, audit log."""

import csv

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .audit import log
from .forms import RollUploadForm
from .models import AuditLog, Election, Voter
from .results import tally, turnout
from .roll import REQUIRED_HEADERS, import_roll


@staff_member_required
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


@staff_member_required
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
            return redirect("staff_roll_upload")
    return render(
        request,
        "staff/roll_upload.html",
        {"form": form, "result": result, "headers": REQUIRED_HEADERS},
    )


@staff_member_required
def roll_template(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="voter_roll_template.csv"'
    writer = csv.writer(response)
    writer.writerow(REQUIRED_HEADERS)
    writer.writerow(["Ada Obi", "2021/245678", "Physical Sciences", "Computer Science", "200"])
    return response


@staff_member_required
def results(request, election_id):
    election = get_object_or_404(Election, pk=election_id)
    return render(
        request,
        "staff/results.html",
        {"election": election, "results": tally(election), "turnout": turnout(election)},
    )


@staff_member_required
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


@staff_member_required
def audit_log(request):
    entries = AuditLog.objects.select_related("user")
    query = request.GET.get("q", "").strip()
    if query:
        entries = entries.filter(reg_number__icontains=query) | entries.filter(action__icontains=query)
    page = Paginator(entries, 50).get_page(request.GET.get("page"))
    return render(request, "staff/audit.html", {"page": page, "query": query})
