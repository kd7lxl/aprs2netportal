import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .dn import InvalidDN, callsign_from_dn

logger = logging.getLogger(__name__)


class LoTWCertificateBackend(ModelBackend):
    """
    Authenticates the holder of a verified LoTW client certificate.

    A certificate only identifies an existing portal user. Anyone with an
    amateur radio licence can get a LoTW certificate, so a certificate alone
    never gives access: no user is ever created from one.
    """

    def authenticate(self, request, lotw_dn=None, **kwargs):
        if lotw_dn is None:
            return None

        try:
            callsign = callsign_from_dn(lotw_dn)
        except InvalidDN as e:
            logger.warning("Rejecting client certificate DN %r: %s", lotw_dn, e)
            return None

        User = get_user_model()
        try:
            user = User.objects.get(username__iexact=callsign)
        except User.DoesNotExist:
            logger.info("No user for LoTW certificate callsign %s", callsign)
            return None
        except User.MultipleObjectsReturned:
            logger.warning("Several users match callsign %s, not logging in", callsign)
            return None

        if not self.user_can_authenticate(user):
            logger.warning("User %s is inactive", callsign)
            return None
        return user
