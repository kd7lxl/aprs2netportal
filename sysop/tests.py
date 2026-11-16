import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from .models import Domain, ReservedHostname, Rotate, Server

User = get_user_model()


class PortalTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.aprs2 = Domain.objects.create(domain='aprs2.net')
        cls.firenet = Domain.objects.create(domain='firenet.us')

        cls.owner = User.objects.create_user(
            'owner', 'owner@example.com', 'pw', first_name='Olivia')
        cls.helper = User.objects.create_user('helper', 'helper@example.com', 'pw')
        cls.stranger = User.objects.create_user('stranger', 'stranger@example.com', 'pw')

        cls.finland = Server.objects.create(
            owner=cls.owner, server_id='T2FINLAND', hostname='finland',
            domain=cls.aprs2, ipv4='192.0.2.1', ipv6='2001:db8::1',
            city='Helsinki', country='FI', email_alerts=True)
        cls.finland.authorized_sysops.add(cls.helper)
        cls.brazil = Server.objects.create(
            owner=cls.stranger, server_id='T2BRAZIL', hostname='brazil',
            domain=cls.aprs2, ipv4='192.0.2.2', city="Sao Paulo & 'co'",
            country='BR', out_of_service=True)
        cls.gone = Server.objects.create(
            server_id='T2GONE', hostname='gone', domain=cls.aprs2,
            ipv4='192.0.2.3', deleted=True)

        cls.rotate = Rotate.objects.create(
            name='Worldwide', description='Worldwide rotate',
            hostname='rotate', domain=cls.aprs2)
        cls.rotate.eligible.set([cls.finland, cls.brazil, cls.gone])
        cls.euro = Rotate.objects.create(
            name='Europe', description='Europe & Africa', hostname='euro',
            domain=cls.aprs2, regional=True)
        cls.euro.eligible.set([cls.finland])

    def setUp(self):
        cache.clear()


class ServersJsonTests(PortalTestCase):
    def test_anonymous(self):
        response = self.client.get('/servers.json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertEqual(json.loads(response.content), {
            'T2FINLAND': {
                'host': 'finland',
                'domain': 'aprs2.net',
                'fqdn': 'finland.aprs2.net',
                'ipv4': '192.0.2.1',
                'ipv6': '2001:db8::1',
                'deleted': False,
                'out_of_service': False,
            },
            'T2BRAZIL': {
                'host': 'brazil',
                'domain': 'aprs2.net',
                'fqdn': 'brazil.aprs2.net',
                'ipv4': '192.0.2.2',
                'ipv6': None,
                'deleted': False,
                'out_of_service': True,
            },
            'T2GONE': {
                'host': 'gone',
                'domain': 'aprs2.net',
                'fqdn': 'gone.aprs2.net',
                'ipv4': '192.0.2.3',
                'ipv6': None,
                'deleted': True,
                'out_of_service': False,
            },
        })

    def test_authenticated_gets_alert_emails(self):
        self.client.force_login(self.stranger)
        data = json.loads(self.client.get('/servers.json').content)
        self.assertEqual(data['T2FINLAND']['email_alerts'], True)
        self.assertEqual(data['T2FINLAND']['email'], 'owner@example.com')
        # no address unless the sysop has enabled alerts
        self.assertEqual(data['T2BRAZIL']['email_alerts'], False)
        self.assertNotIn('email', data['T2BRAZIL'])
        self.assertNotIn('email', data['T2GONE'])

    def test_cache_does_not_leak_emails_to_anonymous(self):
        self.client.force_login(self.stranger)
        self.assertIn(b'owner@example.com', self.client.get('/servers.json').content)
        self.client.logout()
        self.assertNotIn(b'owner@example.com', self.client.get('/servers.json').content)
        self.assertNotIn(b'email', self.client.get('/sysop/servers.json').content)

    def test_clients_are_told_not_to_cache(self):
        for url in ('/servers.json', '/rotates.json', '/APRServe2.txt'):
            # the first response is generated, the second comes from the cache
            for attempt in ('generated', 'cached'):
                with self.subTest(url=url, attempt=attempt):
                    response = self.client.get(url)
                    self.assertIn('no-store', response['Cache-Control'])
                    self.assertIn('max-age=0', response['Cache-Control'])
                    expires = parsedate_to_datetime(response['Expires'])
                    self.assertLessEqual(expires, datetime.now(timezone.utc))

    def test_also_served_under_sysop(self):
        self.assertEqual(
            self.client.get('/sysop/servers.json').content,
            self.client.get('/servers.json').content)

    def test_cached_and_invalidated_on_save(self):
        self.client.get('/servers.json')
        with self.assertNumQueries(0):
            self.client.get('/servers.json')

        self.finland.ipv4 = '192.0.2.99'
        self.finland.save()
        data = json.loads(self.client.get('/servers.json').content)
        self.assertEqual(data['T2FINLAND']['ipv4'], '192.0.2.99')

    def test_invalidated_on_owner_email_change(self):
        self.client.force_login(self.stranger)
        self.client.get('/servers.json')
        self.owner.email = 'new@example.com'
        self.owner.save()
        data = json.loads(self.client.get('/servers.json').content)
        self.assertEqual(data['T2FINLAND']['email'], 'new@example.com')


    def test_invalidated_on_owner_deletion(self):
        self.client.force_login(self.stranger)
        self.assertIn(b'owner@example.com', self.client.get('/servers.json').content)
        self.owner.delete()
        response = self.client.get('/servers.json')
        self.assertNotIn(b'owner@example.com', response.content)
        self.assertIsNone(json.loads(response.content)['T2FINLAND']['email'])


class RotatesJsonTests(PortalTestCase):
    def test_content(self):
        response = self.client.get('/rotates.json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        data = json.loads(response.content)
        self.assertEqual(sorted(data), ['euro.aprs2.net', 'rotate.aprs2.net'])
        self.assertEqual(data['euro.aprs2.net'], {
            'name': 'Europe',
            'description': 'Europe & Africa',
            'host': 'euro',
            'domain': 'aprs2.net',
            'fqdn': 'euro.aprs2.net',
            'servers': {
                'T2FINLAND': {
                    'host': 'finland',
                    'domain': 'aprs2.net',
                    'fqdn': 'finland.aprs2.net',
                    'ipv4': '192.0.2.1',
                    'ipv6': '2001:db8::1',
                    'deleted': False,
                    'out_of_service': False,
                },
            },
        })
        self.assertEqual(
            sorted(data['rotate.aprs2.net']['servers']),
            ['T2BRAZIL', 'T2FINLAND', 'T2GONE'])

    def test_never_contains_emails(self):
        self.client.force_login(self.owner)
        self.assertNotIn(b'email', self.client.get('/rotates.json').content)

    def test_invalidated_on_membership_change(self):
        self.client.get('/rotates.json')
        self.euro.eligible.add(self.brazil)
        data = json.loads(self.client.get('/rotates.json').content)
        self.assertEqual(
            sorted(data['euro.aprs2.net']['servers']), ['T2BRAZIL', 'T2FINLAND'])


class ServerListTests(PortalTestCase):
    def test_content(self):
        response = self.client.get('/APRServe2.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
        text = response.content.decode()
        self.assertTrue(text.startswith(';\r\n; This file lists the Tier2 servers'))
        # Regional rotates, then a separator, then the non-deleted servers of
        # rotate.aprs2.net ordered by hostname. Nothing is HTML-escaped.
        self.assertTrue(text.endswith(
            "; Please use the regional Tier2 DNS addresses as described in the Wiki.\r\n"
            ";\r\n"
            "euro.aprs2.net:14580;Europe & Africa\r\n"
            ";\r\n"
            "brazil.aprs2.net:14580;User Definable Filter Port: T2BRAZIL Sao Paulo & 'co' BR\r\n"
            "finland.aprs2.net:14580;User Definable Filter Port: T2FINLAND Helsinki FI\r\n"
        ), text[-400:])

    def test_also_served_under_sysop(self):
        self.assertEqual(self.client.get('/sysop/APRServe2.txt').status_code, 200)

    def test_stored_line_breaks_cannot_add_lines(self):
        # values that got into the database before they were validated
        Server.objects.filter(pk=self.finland.pk).update(
            city='Helsinki\r\nevil.example.com:14580;User Definable Filter Port: T2EVIL',
            server_id='T2FIN\nLAND')
        Rotate.objects.filter(pk=self.euro.pk).update(
            description='Europe\u2028evil2.example.com:14580;x\x00\x85y')
        text = self.client.get('/APRServe2.txt').content.decode()
        lines = text.split('\r\n')
        self.assertNotIn('\n', text.replace('\r\n', ''))
        self.assertNotIn('\r', text.replace('\r\n', ''))
        self.assertEqual([line for line in lines if line.startswith('evil')], [])
        self.assertIn(
            'finland.aprs2.net:14580;User Definable Filter Port: T2FIN LAND '
            'Helsinki evil.example.com:14580;User Definable Filter Port: T2EVIL FI',
            lines)
        self.assertIn('euro.aprs2.net:14580;Europe evil2.example.com:14580;x y', lines)
        # one line per regional rotate and per server, as before
        self.assertEqual(len([line for line in lines if ':14580;' in line]), 3)

    def test_missing_main_rotate_is_404(self):
        self.rotate.delete()
        self.assertEqual(self.client.get('/APRServe2.txt').status_code, 404)


class ServerPageTests(PortalTestCase):
    def test_login_required(self):
        for url in ('/sysop/', '/sysop/all', '/sysop/server/%d/' % self.finland.id,
                    '/accounts/profile/'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(
                    response, '/accounts/login/?next=' + url,
                    fetch_redirect_response=False)

    def test_own_servers(self):
        self.client.force_login(self.owner)
        response = self.client.get('/sysop/')
        self.assertContains(response, 'Your servers')
        self.assertContains(response, 'T2FINLAND')
        self.assertNotContains(response, 'T2BRAZIL')
        self.assertNotContains(response, 'Your other authorized servers')

    def test_authorized_servers(self):
        self.client.force_login(self.helper)
        response = self.client.get('/sysop/')
        self.assertContains(response, 'Your other authorized servers')
        self.assertContains(response, 'T2FINLAND')

    def test_all_servers_excludes_deleted(self):
        self.client.force_login(self.stranger)
        response = self.client.get('/sysop/all')
        self.assertContains(response, 'T2FINLAND')
        self.assertContains(response, 'T2BRAZIL')
        self.assertContains(response, 'Out of service')
        self.assertNotContains(response, 'T2GONE')

    def test_legacy_root_urls(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/all').status_code, 200)
        self.assertEqual(reverse('own_servers'), '/sysop/')

    def test_unknown_server_is_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/sysop/server/999999/').status_code, 404)

    def form_data(self, server, **changes):
        data = {
            'owner': server.owner_id or '',
            'server_id': server.server_id,
            'hostname': server.hostname,
            'domain': server.domain_id,
            'ipv4': server.ipv4 or '',
            'ipv6': server.ipv6 or '',
            'city': server.city or '',
            'country': server.country or '',
            'authorized_sysops': [u.pk for u in server.authorized_sysops.all()],
        }
        if server.email_alerts:
            data['email_alerts'] = 'on'
        data.update(changes)
        return data

    def test_owner_can_edit(self):
        self.client.force_login(self.owner)
        url = reverse('server_detail', args=[self.finland.id])
        self.assertContains(self.client.get(url), 'Submit')
        response = self.client.post(url, self.form_data(
            self.finland, ipv4='198.51.100.7', out_of_service='on'))
        self.assertRedirects(response, '/sysop/')
        self.finland.refresh_from_db()
        self.assertEqual(self.finland.ipv4, '198.51.100.7')
        self.assertTrue(self.finland.out_of_service)
        self.assertEqual(list(self.finland.authorized_sysops.all()), [self.helper])

    def test_authorized_sysop_can_edit(self):
        self.client.force_login(self.helper)
        url = reverse('server_detail', args=[self.finland.id])
        response = self.client.post(url, self.form_data(self.finland, city='Tampere'))
        self.assertRedirects(response, '/sysop/')
        self.finland.refresh_from_db()
        self.assertEqual(self.finland.city, 'Tampere')

    def test_other_user_can_view_but_not_edit(self):
        self.client.force_login(self.stranger)
        url = reverse('server_detail', args=[self.finland.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Submit')
        # shown as a disabled field set instead of an editable-looking form
        self.assertContains(response, 'This record is read-only')
        self.assertContains(response, '<fieldset disabled>')
        self.assertNotContains(response, '<form class="portal-form"')
        response = self.client.post(url, self.form_data(self.finland, city='Hacked'))
        self.assertEqual(response.status_code, 200)
        self.finland.refresh_from_db()
        self.assertEqual(self.finland.city, 'Helsinki')

    def test_admin_only_fields_are_locked(self):
        self.client.force_login(self.owner)
        url = reverse('server_detail', args=[self.finland.id])
        response = self.client.post(url, self.form_data(
            self.finland, server_id='T2EVIL', hostname='evil',
            domain=self.firenet.id, city='Espoo'))
        self.assertRedirects(response, '/sysop/')
        self.finland.refresh_from_db()
        self.assertEqual(self.finland.server_id, 'T2FINLAND')
        self.assertEqual(self.finland.hostname, 'finland')
        self.assertEqual(self.finland.domain, self.aprs2)
        self.assertEqual(self.finland.city, 'Espoo')

    def test_line_breaks_are_refused(self):
        self.client.force_login(self.owner)
        url = reverse('server_detail', args=[self.finland.id])
        for field in ('city', 'connection_desc', 'connection_speed', 'site_desc'):
            for bad in ('Helsinki\r\nevil.example.com:14580;x', 'a\nb', 'a\rb',
                        'a\x00b', 'a\x0bb', 'a\x85b', 'a\u2028b'):
                with self.subTest(field=field, value=bad):
                    response = self.client.post(
                        url, self.form_data(self.finland, **{field: bad}))
                    # Django has its own check, and message, for NUL
                    self.assertContains(
                        response,
                        'Null characters are not allowed.' if '\x00' in bad else
                        'Line breaks and other control characters are not allowed.')
        self.finland.refresh_from_db()
        self.assertEqual(self.finland.city, 'Helsinki')
        # ordinary punctuation and non-ASCII text are fine
        response = self.client.post(
            url, self.form_data(self.finland, city="Jyv\u00e4skyl\u00e4; O'Hare & co"))
        self.assertRedirects(response, '/sysop/')

    def test_invalid_input(self):
        self.client.force_login(self.owner)
        url = reverse('server_detail', args=[self.finland.id])
        response = self.client.post(url, self.form_data(self.finland, ipv4='not-an-ip'))
        self.assertContains(response, 'Enter a valid IPv4 address')
        self.assertContains(response, 'is-invalid')
        self.assertContains(response, 'alert-warning')
        self.finland.refresh_from_db()
        self.assertEqual(self.finland.ipv4, '192.0.2.1')


class AccountTests(PortalTestCase):
    def test_login_and_logout(self):
        response = self.client.post(
            '/accounts/login/', {'username': 'owner', 'password': 'pw'})
        self.assertRedirects(response, '/sysop/')
        self.assertContains(self.client.get('/sysop/'), 'Welcome, owner!')

        # logging out takes a POST
        self.assertEqual(self.client.get('/accounts/logout/').status_code, 405)
        response = self.client.post('/accounts/logout/')
        self.assertRedirects(response, '/accounts/login/')
        self.assertEqual(self.client.get('/sysop/').status_code, 302)

    def test_bad_login(self):
        response = self.client.post(
            '/login/', {'username': 'owner', 'password': 'wrong'})
        self.assertContains(response, 'Please enter a correct username and password')

    def test_profile(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get('/accounts/profile/'), 'Olivia')
        response = self.client.post('/accounts/profile/', {
            'first_name': 'Olga', 'last_name': 'Owner', 'email': 'olga@example.com'})
        self.assertRedirects(response, '/sysop/')
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.first_name, 'Olga')
        self.assertEqual(self.owner.email, 'olga@example.com')

    def test_password_change(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/accounts/password/change/').status_code, 200)
        response = self.client.post('/accounts/password/change/', {
            'old_password': 'pw',
            'new_password1': 'correct horse battery',
            'new_password2': 'correct horse battery',
        })
        self.assertRedirects(response, '/accounts/password/change/done/')
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password('correct horse battery'))

    def test_password_reset(self):
        self.assertEqual(self.client.get('/accounts/password/reset/').status_code, 200)
        response = self.client.post(
            '/accounts/password/reset/', {'email': 'owner@example.com'})
        self.assertRedirects(response, '/accounts/password/reset/done/')
        self.assertEqual(len(mail.outbox), 1)
        link = [line for line in mail.outbox[0].body.splitlines()
                if '/accounts/password/reset/' in line][0]
        path = '/' + link.split('/', 3)[3]

        response = self.client.get(path, follow=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(response.request['PATH_INFO'], {
            'new_password1': 'correct horse battery',
            'new_password2': 'correct horse battery',
        })
        self.assertRedirects(response, '/accounts/password/done/')
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password('correct horse battery'))


class ValidationTests(PortalTestCase):
    def test_reserved_hostname(self):
        ReservedHostname.objects.create(hostname='ns1', domain=self.aprs2)
        with self.assertRaisesMessage(ValidationError, 'ns1.aprs2.net is a reserved hostname.'):
            Server(hostname='ns1', domain=self.aprs2).full_clean()
        with self.assertRaisesMessage(ValidationError, 'ns1.aprs2.net is a reserved hostname.'):
            Rotate(hostname='ns1', domain=self.aprs2).full_clean()
        # reserved in one domain only
        Server(hostname='ns1', domain=self.firenet).full_clean()

    def test_server_cannot_shadow_rotate(self):
        with self.assertRaisesMessage(ValidationError, 'euro.aprs2.net is a rotate.'):
            Server(hostname='euro', domain=self.aprs2).full_clean()

    def test_rotate_cannot_shadow_server(self):
        with self.assertRaisesMessage(ValidationError, 'finland.aprs2.net is a server.'):
            Rotate(hostname='finland', domain=self.aprs2).full_clean()

    def test_admin_only_text_fields_refuse_line_breaks(self):
        with self.assertRaises(ValidationError):
            Rotate(hostname='x', domain=self.aprs2, description='a\nb').full_clean()
        with self.assertRaises(ValidationError):
            Rotate(hostname='x', domain=self.aprs2, name='a\rb').full_clean()
        with self.assertRaises(ValidationError):
            Server(hostname='x', domain=self.aprs2, server_id='T2\nX').full_clean()

    def test_hostname_syntax(self):
        for hostname in ('-leading', 'trailing-', '12345', 'under_score', 'dot.ted', 'a' * 64):
            with self.subTest(hostname=hostname):
                with self.assertRaises(ValidationError):
                    Server(hostname=hostname, domain=self.aprs2).full_clean()
        Server(hostname='ok-name2', domain=self.aprs2).full_clean()

    def test_domain_syntax(self):
        for domain in ('nodot', '-bad.net', 'bad-.net', 'x.y_z'):
            with self.subTest(domain=domain):
                with self.assertRaises(ValidationError):
                    Domain(domain=domain).full_clean()
        Domain(domain='example.org').full_clean()

    def test_deleting_owner_keeps_server(self):
        self.owner.delete()
        self.finland.refresh_from_db()
        self.assertIsNone(self.finland.owner)


class AdminTests(PortalTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw')

    def test_changelists_and_forms(self):
        self.client.force_login(self.admin)
        for url in (
            '/admin/',
            '/admin/sysop/server/',
            '/admin/sysop/server/?q=finland',
            '/admin/sysop/server/%d/change/' % self.finland.id,
            '/admin/sysop/rotate/',
            '/admin/sysop/rotate/?o=3',
            '/admin/sysop/rotate/%d/change/' % self.rotate.id,
            '/admin/sysop/domain/',
            '/admin/sysop/reservedhostname/',
            '/admin/auth/user/',
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_rotate_server_count(self):
        self.client.force_login(self.admin)
        response = self.client.get('/admin/sysop/rotate/')
        self.assertContains(response, '<td class="field-server_count">3</td>', html=True)

    def test_non_staff_has_no_admin_link(self):
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get('/sysop/'), '/admin/')
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/sysop/'), '/admin/')


class FrontendTests(PortalTestCase):
    """The pages load nothing from third parties and suit a strict CSP."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw')

    def pages(self):
        """Yield (description, response) for every kind of HTML page."""
        anonymous = (
            '/accounts/login/',
            '/accounts/password/reset/',
            '/accounts/password/reset/done/',
            '/accounts/password/reset/bad/link/',
            '/accounts/password/done/',
            '/no-such-page/',
        )
        authenticated = (
            '/sysop/',
            '/sysop/all',
            '/sysop/server/%d/' % self.finland.id,
            '/sysop/server/%d/' % self.brazil.id,
            '/accounts/profile/',
            '/accounts/password/change/',
            '/accounts/password/change/done/',
            '/no-such-page/',
        )
        for url in anonymous:
            yield 'anonymous ' + url, self.client.get(url)
        self.client.post(
            '/accounts/login/', {'username': 'owner', 'password': 'wrong'})
        yield 'failed login', self.client.post(
            '/accounts/login/', {'username': 'owner', 'password': 'wrong'})
        for user in (self.owner, self.admin):
            self.client.force_login(user)
            for url in authenticated:
                yield '%s %s' % (user, url), self.client.get(url)
        self.client.force_login(self.owner)
        yield 'invalid server form', self.client.post(
            '/sysop/server/%d/' % self.finland.id, {'ipv4': 'not-an-ip'})
        yield 'invalid profile form', self.client.post(
            '/accounts/profile/', {'email': 'not-an-address'})

    def test_assets_are_local(self):
        count = 0
        for description, response in self.pages():
            html = response.content.decode()
            with self.subTest(page=description):
                self.assertIn(response.status_code, (200, 404))
                self.assertIn('text/html', response['Content-Type'])
                assets = re.findall(
                    r'<(?:link|script|img|source|iframe)\b[^>]*?\s(?:href|src)="([^"]*)"',
                    html)
                self.assertGreaterEqual(len(assets), 4)
                for asset in assets:
                    self.assertTrue(asset.startswith('/static/'), asset)
                    self.assertIsNotNone(
                        finders.find(asset.removeprefix('/static/')), asset)
                for needle in ('netdna', 'bootstrapcdn', 'googleapis', 'maxcdn',
                               'jsdelivr', 'cdnjs', 'unpkg', 'jquery', '@import'):
                    self.assertNotIn(needle, html.lower())
                # the only absolute URLs are links, never something loaded
                for tag in re.findall(r'<[^>]*(?:https?:)?//[^>]*>', html):
                    self.assertRegex(tag, r'^<(a|svg) ', tag)
            count += 1
        self.assertGreater(count, 20)

    def test_sidebar_logo(self):
        self.client.force_login(self.owner)
        response = self.client.get('/sysop/')
        # one rendering for each colour mode; CSS shows the right one
        self.assertContains(response, 'src="/static/aprs2net-logo.png"')
        self.assertContains(response, 'src="/static/aprs2net-logo-dark.png"')
        self.assertContains(response, 'alt="APRS Tier 2 Network"', count=2)
        self.assertContains(
            response,
            '<a class="portal-logo" href="https://www.aprs2.net/" target="_blank" rel="noopener">')
        # pages without the sidebar have no logo
        self.client.logout()
        self.assertNotContains(self.client.get('/accounts/login/'), 'aprs2net-logo')

    def test_no_inline_script_or_style(self):
        for description, response in self.pages():
            html = response.content.decode()
            with self.subTest(page=description):
                self.assertNotIn('<style', html)
                self.assertNotRegex(html, r'<[^>]*\sstyle=')
                self.assertNotRegex(html, r'<[^>]*\son[a-z]+=')
                self.assertNotIn('javascript:', html)
                for attrs, body in re.findall(r'<script\b([^>]*)>(.*?)</script>', html, re.S):
                    self.assertIn('src="/static/', attrs)
                    self.assertEqual(body.strip(), '')

    def test_no_bootstrap_3_leftovers(self):
        leftovers = re.compile(
            r'col-xs-|col-(sm|md|lg)-offset-|navbar-inverse|navbar-right|navbar-toggle\b'
            r'|btn-default|btn-xs|form-group|form-horizontal|control-label|has-error'
            r'|help-inline|help-block|sr-only|glyphicon|data-toggle|data-target'
            r'|table-condensed|pull-(left|right)|img-responsive|page-header|sub-header')
        for description, response in self.pages():
            with self.subTest(page=description):
                self.assertNotRegex(response.content.decode(), leftovers)

    def test_logout_is_a_post_form_with_csrf_token(self):
        self.client.force_login(self.owner)
        for url in ('/sysop/', '/sysop/all', '/accounts/profile/'):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                forms = re.findall(
                    r'<form\b[^>]*\baction="/accounts/logout/"[^>]*>.*?</form>',
                    html, re.S)
                self.assertEqual(len(forms), 1)
                self.assertRegex(forms[0], r'^<form\b[^>]*\bmethod="post"')
                self.assertRegex(
                    forms[0],
                    r'<input type="hidden" name="csrfmiddlewaretoken" value="\w+">')
                self.assertRegex(forms[0], r'<button type="submit"[^>]*>Logout</button>')
                self.assertNotRegex(html, r'<a\b[^>]*href="/accounts/logout/"')
        # no logout control for anonymous visitors
        self.client.logout()
        self.assertNotContains(self.client.get('/accounts/login/'), '/accounts/logout/')

    def test_logout_form_passes_csrf_checks(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.owner)
        html = client.get('/sysop/').content.decode()
        token = re.search(r'name="csrfmiddlewaretoken" value="(\w+)"', html).group(1)
        self.assertEqual(client.post('/accounts/logout/').status_code, 403)
        response = client.post('/accounts/logout/', {'csrfmiddlewaretoken': token})
        self.assertRedirects(response, '/accounts/login/', fetch_redirect_response=False)

    def test_active_nav_link(self):
        self.client.force_login(self.owner)
        current = r'<a class="nav-link active" aria-current="page" href="%s">'
        response = self.client.get('/sysop/all')
        self.assertContains(response, current % '/sysop/all')
        self.assertNotContains(response, current % '/sysop/')
        self.assertContains(response, 'aria-current="page"', count=1)
        response = self.client.get('/sysop/')
        self.assertContains(response, current % '/sysop/')
        self.assertContains(response, 'aria-current="page"', count=1)
        # legacy root URLs highlight the same link
        self.assertContains(self.client.get('/all'), current % '/sysop/all')

    def test_external_links(self):
        self.client.force_login(self.stranger)
        html = self.client.get('/sysop/all').content.decode()
        # status pages of the servers are plain http
        self.assertIn('<a href="http://finland.aprs2.net:14501/">finland.aprs2.net</a>', html)
        self.assertIn('<a href="http://192.0.2.1:14501/">192.0.2.1</a>', html)
        self.assertIn('<a href="http://[2001:db8::1]:14501/">2001:db8::1</a>', html)
        for tag in re.findall(r'<a\b[^>]*target="_blank"[^>]*>', html):
            self.assertIn('rel="noopener"', tag)

    def test_form_widget_classes(self):
        self.client.force_login(self.owner)
        html = self.client.get('/sysop/server/%d/' % self.finland.id).content.decode()

        def tag(name):
            return re.search(r'<(?:input|select)\b[^>]*\bname="%s"[^>]*>' % name, html).group(0)

        self.assertIn('class="form-control"', tag('ipv4'))
        self.assertIn('class="form-select"', tag('country'))
        self.assertIn('class="form-select"', tag('authorized_sysops'))
        self.assertIn('class="form-check-input"', tag('email_alerts'))
        self.assertIn(' disabled', tag('hostname'))
        # every field has a label tied to it
        for field_id in re.findall(r'<(?:input|select)\b[^>]*\bid="(id_\w+)"', html):
            self.assertIn('for="%s"' % field_id, html)

    def test_message_alert_classes(self):
        from utils.templatetags.bootstrap import alert_class

        class Message:
            def __init__(self, level):
                self.level_tag = messages.DEFAULT_TAGS[level]

        self.assertEqual(alert_class(Message(messages.ERROR)), 'alert-danger')
        self.assertEqual(alert_class(Message(messages.WARNING)), 'alert-warning')
        self.assertEqual(alert_class(Message(messages.SUCCESS)), 'alert-success')
        self.assertEqual(alert_class(Message(messages.INFO)), 'alert-info')
        self.assertEqual(alert_class(Message(messages.DEBUG)), 'alert-secondary')

    def test_saved_message_is_shown(self):
        self.client.force_login(self.owner)
        response = self.client.post('/accounts/profile/', {
            'first_name': 'Olga', 'last_name': 'Owner', 'email': 'olga@example.com',
        }, follow=True)
        self.assertContains(
            response,
            '<div class="alert alert-success" role="alert">User settings saved.</div>',
            html=True)

    def test_error_pages(self):
        response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')
        self.assertContains(response, '404 Not Found', status_code=404)
        # the 500 page renders without a request or any context
        html = render_to_string('500.html')
        self.assertIn('500 Server Error', html)
        self.assertIn('/static/portal.css', html)
        self.assertNotIn('csrf', html)
        self.assertIn('403 Forbidden', render_to_string('403.html'))


class SecurityHeaderTests(PortalTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw')

    def test_headers_on_pages_and_exports(self):
        self.client.force_login(self.owner)
        for url in ('/sysop/', '/accounts/profile/', '/servers.json',
                    '/APRServe2.txt', '/sysop/server/999999/'):
            with self.subTest(url=url):
                response = self.client.get(url)
                csp = response['Content-Security-Policy']
                self.assertIn("default-src 'none'", csp)
                self.assertIn("script-src 'self'", csp)
                self.assertIn("style-src 'self'", csp)
                self.assertIn("frame-ancestors 'none'", csp)
                self.assertNotIn('unsafe', csp)
                self.assertEqual(response['X-Frame-Options'], 'DENY')
                self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_login_page_has_policy(self):
        response = self.client.get('/accounts/login/')
        self.assertIn("form-action 'self'", response['Content-Security-Policy'])

    def test_hsts_only_behind_tls_proxy(self):
        # not configured in the test settings: plain HTTP development setups
        # must not get pinned to HTTPS
        response = self.client.get('/accounts/login/', secure=True)
        self.assertNotIn('Strict-Transport-Security', response)
        with self.settings(SECURE_HSTS_SECONDS=3600):
            # the middleware reads the setting when it is created
            client = Client()
            response = client.get('/accounts/login/', secure=True)
            self.assertEqual(response['Strict-Transport-Security'], 'max-age=3600')
            self.assertNotIn(
                'Strict-Transport-Security', client.get('/accounts/login/'))

    def test_admin_pages_work_under_the_policy(self):
        """The admin must not need inline scripts, handlers or styles."""
        self.client.force_login(self.admin)
        for url in (
            '/admin/',
            '/admin/sysop/server/',
            '/admin/sysop/server/add/',
            '/admin/sysop/server/%d/change/' % self.finland.id,
            '/admin/sysop/rotate/%d/change/' % self.rotate.id,
            '/admin/auth/user/',
            '/admin/auth/user/%d/change/' % self.owner.id,
            '/admin/auth/user/%d/password/' % self.owner.id,
            '/admin/sysop/server/%d/delete/' % self.gone.id,
            '/admin/sysop/server/%d/history/' % self.finland.id,
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn('Content-Security-Policy', response)
                html = response.content.decode()
                for tag in re.findall(r'<script\b[^>]*>', html):
                    # from this site (static files, the admin's /admin/jsi18n/)
                    # or data that is not executed
                    self.assertTrue(
                        re.search(r' src="/[^/]', tag)
                        or 'type="application/json"' in tag, tag)
                self.assertEqual(re.findall(r'<style\b', html), [])
                self.assertEqual(re.findall(r'<[^>]*\son[a-z]+\s*=[^>]*>', html), [])
                self.assertEqual(re.findall(r'<[^>]*\sstyle\s*=[^>]*>', html), [])
                for asset in re.findall(
                        r'<(?:link|script|img)\b[^>]*?\s(?:href|src)="([^"]*)"', html):
                    # same origin: not a URL with a scheme or another host
                    self.assertRegex(asset, r'^/[^/]')

