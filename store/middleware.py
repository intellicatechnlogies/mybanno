import time
from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import redirect

ADMIN_IDLE_TIMEOUT = 30 * 60


class AdminIdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if "admin_id" in request.session:
            now = time.time()
            last_activity = request.session.get("admin_last_activity", now)
            if now - last_activity >= ADMIN_IDLE_TIMEOUT:
                request.session.flush()
                if request.path.startswith("/admin") and request.path != "/admin/login":
                    messages.warning(request, "Your admin session expired after 30 minutes of inactivity.")
                    return redirect(f"/admin/login?{urlencode({'next': request.path})}")
            elif not request.path.startswith("/static/"):
                request.session["admin_last_activity"] = now
        return self.get_response(request)
