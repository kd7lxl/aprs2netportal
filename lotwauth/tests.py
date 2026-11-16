from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, modify_settings

from .dn import InvalidDN, parse_dn, callsign_from_dn

User = get_user_model()

# PrintableString "N0CALL"
RFC_DN = ('emailAddress=n0call@example.com,CN=Test Middle Operator,'
          '1.3.6.1.4.1.12348.1.1=#13064E3043414C4C')
LEGACY_DN = ('/1.3.6.1.4.1.12348.1.1=N0CALL/CN=Test Middle Operator'
             '/emailAddress=n0call@example.com')


class DNParsingTests(SimpleTestCase):
    def test_rfc_form(self):
        self.assertEqual(callsign_from_dn(RFC_DN), 'N0CALL')

    def test_legacy_form_is_refused(self):
        with self.assertRaises(InvalidDN):
            callsign_from_dn(LEGACY_DN)

    def test_duplicate_callsign_is_refused(self):
        with self.assertRaises(InvalidDN):
            callsign_from_dn(RFC_DN + ',1.3.6.1.4.1.12348.1.1=N1CALL')

    def test_utf8string_callsign(self):
        dn = 'CN=X,1.3.6.1.4.1.12348.1.1=#0C064E3043414C4C'
        self.assertEqual(callsign_from_dn(dn), 'N0CALL')

    def test_plain_callsign_is_uppercased(self):
        dn = 'CN=X,1.3.6.1.4.1.12348.1.1=n0call'
        self.assertEqual(callsign_from_dn(dn), 'N0CALL')

    def test_non_ascii_lookalikes_are_refused(self):
        # these uppercase to "SM0CALL", "OH1AI" and "DL1SS"
        for callsign in ('\u017fm0call', 'oh1a\u0131', 'dl1\u00df'):
            with self.subTest(callsign=callsign):
                with self.assertRaises(InvalidDN):
                    callsign_from_dn('CN=X,1.3.6.1.4.1.12348.1.1=' + callsign)
        # also when DER encoded as a UTF8String
        der = b'\x0c' + bytes([len('\u017fm0call'.encode())]) + '\u017fm0call'.encode()
        with self.assertRaises(InvalidDN):
            callsign_from_dn('CN=X,1.3.6.1.4.1.12348.1.1=#' + der.hex())

    def test_escapes(self):
        attrs = parse_dn(r'CN=Last\, First,O=J\C3\A4rvi+OU=a\+b')
        self.assertEqual(attrs['cn'], 'Last, First')
        self.assertEqual(attrs['o'], 'Järvi')
        self.assertEqual(attrs['ou'], 'a+b')

    def test_escaped_comma_cannot_inject_callsign(self):
        dn = r'CN=Evil\,1.3.6.1.4.1.12348.1.1=N0CALL,emailAddress=e@example.com'
        with self.assertRaises(InvalidDN):
            callsign_from_dn(dn)

    def test_rejects_garbage(self):
        for dn in ('', '   ', 'CN=No Callsign', 'CN=X,1.3.6.1.4.1.12348.1.1=#zz',
                   'CN=X,1.3.6.1.4.1.12348.1.1=#1306', 'CN=X,1.3.6.1.4.1.12348.1.1=a b',
                   'no-equals-sign'):
            with self.subTest(dn=dn):
                with self.assertRaises(InvalidDN):
                    callsign_from_dn(dn)


CERT_HEADERS = {
    'HTTP_X_SSL_CLIENT_VERIFY': 'SUCCESS',
    'HTTP_X_SSL_CLIENT_S_DN': RFC_DN,
}


@modify_settings(
    MIDDLEWARE={
        'append': 'lotwauth.middleware.LoTWCertificateMiddleware',
    },
    AUTHENTICATION_BACKENDS={
        'prepend': 'lotwauth.backends.LoTWCertificateBackend',
    },
)
class CertificateLoginTests(TestCase):
    def get(self, **extra):
        return self.client.get('/sysop/', secure=True, **extra)

    def assertNotLoggedIn(self, response):
        self.assertRedirects(response, '/accounts/login/?next=/sysop/',
                             fetch_redirect_response=False)

    def test_no_certificate(self):
        User.objects.create_user('N0CALL')
        self.assertNotLoggedIn(self.get())

    def test_logs_in_existing_user(self):
        user = User.objects.create_user('N0CALL', 'old@example.com', 'pw')
        response = self.get(**CERT_HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.user, user)
        # nothing is copied from the certificate
        user.refresh_from_db()
        self.assertEqual(user.email, 'old@example.com')
        self.assertEqual(user.first_name, '')
        # the session persists without the certificate
        self.assertEqual(self.get().status_code, 200)

    def test_matches_username_case_insensitively(self):
        user = User.objects.create_user('n0call')
        response = self.get(**CERT_HEADERS)
        self.assertEqual(response.wsgi_request.user, user)

    def test_never_creates_a_user(self):
        other = User.objects.create_user('other')
        self.assertNotLoggedIn(self.get(**CERT_HEADERS))
        self.assertEqual(list(User.objects.all()), [other])

    def test_ambiguous_callsign(self):
        User.objects.create_user('N0CALL')
        User.objects.create_user('n0call')
        self.assertNotLoggedIn(self.get(**CERT_HEADERS))

    def test_inactive_user(self):
        User.objects.create_user('N0CALL', is_active=False)
        self.assertNotLoggedIn(self.get(**CERT_HEADERS))

    def test_verification_failure(self):
        User.objects.create_user('N0CALL')
        for verify in ('FAILED:certificate has expired', 'NONE', '', 'success'):
            with self.subTest(verify=verify):
                headers = dict(CERT_HEADERS, HTTP_X_SSL_CLIENT_VERIFY=verify)
                self.assertNotLoggedIn(self.get(**headers))

    def test_requires_https(self):
        User.objects.create_user('N0CALL')
        response = self.client.get('/sysop/', **CERT_HEADERS)
        self.assertEqual(response.status_code, 302)

    def test_bad_dn(self):
        User.objects.create_user('N0CALL')
        headers = dict(CERT_HEADERS, HTTP_X_SSL_CLIENT_S_DN='CN=No Callsign')
        self.assertNotLoggedIn(self.get(**headers))

    def test_password_login_still_works(self):
        User.objects.create_user('other', password='pw')
        self.assertTrue(self.client.login(username='other', password='pw'))
        self.assertEqual(self.get().status_code, 200)


class DisabledByDefaultTests(TestCase):
    def test_headers_ignored_when_disabled(self):
        User.objects.create_user('N0CALL')
        response = self.client.get('/sysop/', secure=True, **CERT_HEADERS)
        self.assertEqual(response.status_code, 302)
