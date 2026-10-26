from django.conf import settings
from django.db import models


class Voter(models.Model):
    """A student on the voter roll.

    Rows are created by the admin's CSV upload. A student becomes a
    registered voter once they complete self-registration with their face.
    """

    reg_number = models.CharField("registration number", max_length=30, unique=True)
    full_name = models.CharField(max_length=150)
    faculty = models.CharField(max_length=100)
    department = models.CharField(max_length=100)
    level = models.CharField(max_length=10)

    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    face_embedding = models.JSONField(null=True, blank=True, editable=False)
    face_photo = models.FileField(upload_to="faces/", blank=True)
    registered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["faculty", "department", "full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.reg_number})"

    @property
    def is_registered(self):
        return self.registered_at is not None and self.face_embedding is not None


class Election(models.Model):
    DRAFT, OPEN, CLOSED = "draft", "open", "closed"
    STATUS_CHOICES = [(DRAFT, "Draft"), (OPEN, "Open for voting"), (CLOSED, "Closed")]

    title = models.CharField(max_length=150)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    results_public = models.BooleanField(
        default=False, help_text="Show results to students after the election closes."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @classmethod
    def current(cls):
        return cls.objects.filter(status=cls.OPEN).first()


class Position(models.Model):
    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="positions")
    title = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("election", "title")]

    def __str__(self):
        return f"{self.title} ({self.election})"


class Candidate(models.Model):
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="candidates")
    name = models.CharField(max_length=150)
    department = models.CharField(max_length=100, blank=True)
    manifesto = models.TextField(blank=True)
    photo = models.FileField(upload_to="candidates/", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Participation(models.Model):
    """Records THAT a voter voted, never WHAT they voted.

    The unique constraint is what guarantees one ballot per voter.
    """

    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="participations")
    voter = models.ForeignKey(Voter, on_delete=models.PROTECT, related_name="participations")
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["election", "voter"], name="one_ballot_per_voter")
        ]


class Vote(models.Model):
    """One choice on a ballot. Deliberately not linked to the voter (ballot secrecy)."""

    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="votes")
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name="votes")
    candidate = models.ForeignKey(Candidate, on_delete=models.PROTECT, related_name="votes")
    # Date only, so vote rows cannot be matched to Participation rows by timestamp.
    cast_at = models.DateField(auto_now_add=True)


class AuditLog(models.Model):
    action = models.CharField(max_length=50)
    detail = models.TextField(blank=True)
    reg_number = models.CharField(max_length=30, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"
