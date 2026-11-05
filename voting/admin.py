from django.contrib import admin, messages
from django.utils.html import format_html

from .audit import log
from .models import AuditLog, Candidate, Election, Participation, Position, Voter


@admin.register(Voter)
class VoterAdmin(admin.ModelAdmin):
    list_display = ("reg_number", "full_name", "faculty", "department", "level", "registered")
    list_filter = ("faculty", "level", ("registered_at", admin.EmptyFieldListFilter))
    search_fields = ("reg_number", "full_name", "department", "email")
    readonly_fields = ("face_preview", "registered_at", "created_at", "updated_at")
    fields = (
        "reg_number", "full_name", "faculty", "department", "level",
        "email", "phone", "face_preview", "registered_at", "created_at", "updated_at",
    )
    actions = ["reset_face_registration"]

    @admin.display(boolean=True)
    def registered(self, obj):
        return obj.is_registered

    @admin.display(description="Registered face")
    def face_preview(self, obj):
        if obj.face_photo:
            return format_html('<img src="{}" style="max-width:200px;border-radius:8px">', obj.face_photo.url)
        return "Not registered"

    @admin.action(description="Reset face registration (student must register again)")
    def reset_face_registration(self, request, queryset):
        for voter in queryset:
            if voter.face_photo:
                voter.face_photo.delete(save=False)
            voter.face_embedding = None
            voter.registered_at = None
            voter.save()
            log(request, "registration_reset", reg_number=voter.reg_number)
        self.message_user(request, f"Reset {queryset.count()} registration(s).")


class PositionInline(admin.TabularInline):
    model = Position
    extra = 1


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "results_public", "created_at", "results_link")
    inlines = [PositionInline]
    actions = ["open_voting", "close_voting"]

    @admin.display(description="Results")
    def results_link(self, obj):
        return format_html('<a href="/staff/results/{}/">View results</a>', obj.pk)

    @admin.action(description="Open voting for the selected election")
    def open_voting(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one election to open.", messages.ERROR)
            return
        election = queryset.get()
        problems = election.open_problems()
        if problems:
            self.message_user(request, " ".join(problems), messages.ERROR)
            return
        election.status = Election.OPEN
        election.save()
        log(request, "election_opened", election.title)
        self.message_user(request, f"Voting is now open for {election}.")

    @admin.action(description="Close voting for the selected election(s)")
    def close_voting(self, request, queryset):
        for election in queryset.filter(status=Election.OPEN):
            election.status = Election.CLOSED
            election.save()
            log(request, "election_closed", election.title)
        self.message_user(request, "Voting closed.")

    def get_readonly_fields(self, request, obj=None):
        # Status changes go through the actions so they are validated and logged.
        return ("status",)


class CandidateInline(admin.StackedInline):
    model = Candidate
    extra = 1


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("title", "election", "order")
    list_filter = ("election",)
    inlines = [CandidateInline]


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("name", "position", "department")
    list_filter = ("position__election", "position")
    search_fields = ("name",)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Participation)
class ParticipationAdmin(ReadOnlyAdmin):
    list_display = ("voter", "election", "voted_at")
    list_filter = ("election",)
    search_fields = ("voter__reg_number", "voter__full_name")


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "action", "reg_number", "user", "ip_address", "detail")
    list_filter = ("action",)
    search_fields = ("reg_number", "detail")
