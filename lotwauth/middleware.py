import logging

from django.conf import settings
from django.contrib import auth

logger = logging.getLogger(__name__)


class LoTWCertificateMiddleware:
    """
    Logs in the holder of a verified client certificate.

    Must be placed after AuthenticationMiddleware. See the package docstring
    for what the reverse proxy has to do.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self.process_request(request)
        return self.get_response(request)

    def process_request(self, request):
        if request.user.is_authenticated:
            return
        if not request.is_secure():
            return
        if request.META.get(settings.LOTW_VERIFY_HEADER) != 'SUCCESS':
            return
        dn = request.META.get(settings.LOTW_DN_HEADER)
        if not dn:
            return

        user = auth.authenticate(request, lotw_dn=dn)
        if user is not None:
            logger.info("Logging in %s with LoTW certificate", user.get_username())
            auth.login(request, user)
