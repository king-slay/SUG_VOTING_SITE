from django.urls import path

from . import staff_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("candidates/", views.candidate_list, name="candidates"),
    path("vote/", views.vote_start, name="vote_start"),
    path("vote/ballot/", views.ballot, name="ballot"),
    path("results/<int:election_id>/", views.public_results, name="public_results"),
    path("staff/", staff_views.dashboard, name="staff_dashboard"),
    path("staff/roll/", staff_views.roll_upload, name="staff_roll_upload"),
    path("staff/roll/template.csv", staff_views.roll_template, name="staff_roll_template"),
    path("staff/results/<int:election_id>/", staff_views.results, name="staff_results"),
    path("staff/results/<int:election_id>/data/", staff_views.results_json, name="staff_results_json"),
    path("staff/audit/", staff_views.audit_log, name="staff_audit"),
]
