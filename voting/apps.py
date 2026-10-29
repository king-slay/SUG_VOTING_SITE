import os
import sys
import threading

from django.apps import AppConfig


class VotingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "voting"

    def ready(self):
        # Loading the face models takes 30 s or more, and otherwise happens during the
        # first voter's scan after every restart. Under runserver, load them in the
        # background as soon as the server starts (in the process that serves requests).
        serving = "runserver" in sys.argv and (os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv)
        if serving:
            from . import faces

            threading.Thread(target=faces.warm_up, daemon=True).start()
