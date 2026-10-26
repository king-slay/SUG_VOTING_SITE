from django.db.models import Count

from .models import Participation, Voter


def tally(election):
    """Per-position vote counts, highest first, with percentages."""
    results = []
    for position in election.positions.all():
        candidates = list(
            position.candidates.annotate(total=Count("votes", distinct=True)).order_by("-total", "name")
        )
        cast = sum(c.total for c in candidates)
        top = candidates[0].total if candidates else 0
        rows = [
            {
                "candidate": c,
                "votes": c.total,
                "percent": round(100 * c.total / cast, 1) if cast else 0,
                "leading": cast > 0 and c.total == top,
            }
            for c in candidates
        ]
        results.append({"position": position, "rows": rows, "cast": cast})
    return results


def turnout(election):
    registered = Voter.objects.exclude(registered_at=None).count()
    voted = Participation.objects.filter(election=election).count()
    return {
        "registered": registered,
        "voted": voted,
        "percent": round(100 * voted / registered, 1) if registered else 0,
    }
