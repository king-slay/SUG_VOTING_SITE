from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import views as auth_views
from django.urls import path

from . import staff_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("candidates/", views.candidate_list, name="candidates"),
    path("vote/", views.vote_start, name="vote_start"),
    path("vote/ballot/", views.ballot, name="ballot"),
    path("results/<int:election_id>/", views.public_results, name="public_results"),
    # Electoral committee. AdminAuthenticationForm only lets staff accounts sign in.
    path(
        "staff/login/",
        auth_views.LoginView.as_view(template_name="staff/login.html", authentication_form=AdminAuthenticationForm),
        name="staff_login",
    ),
    path("staff/logout/", auth_views.LogoutView.as_view(next_page="staff_login"), name="staff_logout"),
    path("staff/", staff_views.dashboard, name="staff_dashboard"),
    path("staff/roll/", staff_views.roll_list, name="staff_roll"),
    path("staff/roll/upload/", staff_views.roll_upload, name="staff_roll_upload"),
    path("staff/roll/template.csv", staff_views.roll_template, name="staff_roll_template"),
    path("staff/roll/export.csv", staff_views.roll_export, name="staff_roll_export"),
    path("staff/roll/<int:voter_id>/", staff_views.voter_detail, name="staff_voter"),
    path("staff/roll/<int:voter_id>/reset-face/", staff_views.voter_reset_face, name="staff_voter_reset_face"),
    path("staff/roll/<int:voter_id>/remove/", staff_views.voter_remove, name="staff_voter_remove"),
    path("staff/elections/new/", staff_views.election_new, name="staff_election_new"),
    path("staff/elections/<int:election_id>/", staff_views.election_detail, name="staff_election"),
    path("staff/elections/<int:election_id>/rename/", staff_views.election_rename, name="staff_election_rename"),
    path("staff/elections/<int:election_id>/status/", staff_views.election_status, name="staff_election_status"),
    path("staff/elections/<int:election_id>/delete/", staff_views.election_delete, name="staff_election_delete"),
    path("staff/elections/<int:election_id>/positions/new/", staff_views.position_form, name="staff_position_new"),
    path("staff/positions/<int:position_id>/", staff_views.position_form, name="staff_position_edit"),
    path("staff/positions/<int:position_id>/delete/", staff_views.position_delete, name="staff_position_delete"),
    path("staff/positions/<int:position_id>/candidates/new/", staff_views.candidate_form, name="staff_candidate_new"),
    path("staff/candidates/<int:candidate_id>/", staff_views.candidate_form, name="staff_candidate_edit"),
    path("staff/candidates/<int:candidate_id>/delete/", staff_views.candidate_delete, name="staff_candidate_delete"),
    path("staff/results/<int:election_id>/", staff_views.results, name="staff_results"),
    path("staff/results/<int:election_id>/data/", staff_views.results_json, name="staff_results_json"),
    path("staff/results/<int:election_id>/export.csv", staff_views.results_export, name="staff_results_export"),
    path("staff/audit/", staff_views.audit_log, name="staff_audit"),
]
