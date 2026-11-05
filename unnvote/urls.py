from django.contrib import admin
from django.urls import include, path

from voting.views import media_file

admin.site.site_header = "UNN SUG E-Voting Administration"
admin.site.site_title = "UNN SUG E-Voting"
admin.site.index_title = "Electoral committee"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("media/<path:path>", media_file, name="media"),
    path("", include("voting.urls")),
]
