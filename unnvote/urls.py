from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "UNN SUG E-Voting Administration"
admin.site.site_title = "UNN SUG E-Voting"
admin.site.index_title = "Electoral committee"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("voting.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
