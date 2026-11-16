from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from .countries import ISO3166


domain_validator = RegexValidator(
    regex=r'^(?=^.{4,253}$)(^((?!-)[a-zA-Z0-9-]{1,63}(?<!-)\.)+[a-zA-Z]{2,63}$)$',
)
hostname_validator = RegexValidator(
    regex=r'^(?![0-9]+$)(?!-)[a-zA-Z0-9-]{,63}(?<!-)$',
    message="Only letters, numbers and hyphens are allowed.",
)


# C0 and C1 control characters and the Unicode line separators. Free text
# fields end up on single lines of APRServe2.txt; a line break in one would
# let its author add lines, i.e. servers, to that file.
CONTROL_CHARACTERS = r'[\x00-\x1f\x7f-\x9f\u2028\u2029]'

no_control_characters = RegexValidator(
    regex=CONTROL_CHARACTERS,
    inverse_match=True,
    message="Line breaks and other control characters are not allowed.",
)


class Domain(models.Model):
    """APRS server domain, e.g., aprs.net, aprs2.net, firenet.us"""
    domain = models.CharField(max_length=253, validators=[domain_validator])

    def __str__(self):
        return self.domain

    class Meta:
        ordering = ['domain']


class Server(models.Model):
    """Tier2 servers and hubs"""

    # Admin fields:
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="servers_owned",
        help_text="Warning: changing this field could affect your ability "
                  "to administer this server record.")
    server_id = models.CharField(
        max_length=20, null=True, blank=True,
        validators=[no_control_characters],
        help_text="Administrator use only.")
    hostname = models.CharField(
        max_length=63, validators=[hostname_validator],
        help_text="Administrator use only.")
    domain = models.ForeignKey(
        Domain, on_delete=models.PROTECT,
        help_text="Administrator use only.")
    deleted = models.BooleanField(blank=True, default=False)

    # Owner-editable fields:
    out_of_service = models.BooleanField(
        blank=True, default=False,
        help_text="Use this option to remove your server from DNS before "
                  "planned maintenance.")
    ipv4 = models.GenericIPAddressField(
        protocol="IPv4", null=True, blank=True, verbose_name="IPv4")
    ipv6 = models.GenericIPAddressField(
        protocol="IPv6", null=True, blank=True, verbose_name="IPv6")
    latitude = models.FloatField(
        null=True, blank=True, help_text="Decimal (e.g., 00.0000)")
    longitude = models.FloatField(
        null=True, blank=True, help_text="Decimal (e.g., 000.0000)")
    city = models.CharField(
        max_length=255, null=True, blank=True,
        validators=[no_control_characters])
    country = models.CharField(
        max_length=255, null=True, blank=True,
        choices=sorted(ISO3166.items(), key=lambda country: country[1]))
    connection_desc = models.CharField(
        max_length=255, null=True, blank=True,
        validators=[no_control_characters],
        verbose_name="Connection description",
        help_text="ADSL, Fiber, E1, T1, 33.6 Modem, etc.")
    connection_speed = models.CharField(
        max_length=255, null=True, blank=True,
        validators=[no_control_characters])
    site_desc = models.CharField(
        max_length=255, null=True, blank=True,
        validators=[no_control_characters],
        verbose_name="Site description",
        help_text="Data Center, Home, etc.")
    email_alerts = models.BooleanField(blank=True, default=False)
    authorized_sysops = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True,
        related_name="authorized_servers",
        help_text="Selected sysops will be allowed to edit this server record.")

    def __str__(self):
        return self.server_id or self.hostname

    def fqdn(self):
        return '.'.join((self.hostname, str(self.domain)))
    fqdn.short_description = "FQDN"

    def can_be_edited_by(self, user):
        return (
            self.owner_id == user.pk
            or self.authorized_sysops.filter(pk=user.pk).exists()
        )

    def serialize(self, with_email=False):
        serialized = {
            'host': self.hostname,
            'domain': str(self.domain),
            'fqdn': self.fqdn(),
            'ipv4': self.ipv4,
            'ipv6': self.ipv6,
            'deleted': self.deleted,
            'out_of_service': self.out_of_service,
        }
        if with_email:
            serialized['email_alerts'] = self.email_alerts
            if self.email_alerts:
                serialized['email'] = self.owner and self.owner.email
        return (self.server_id, serialized)

    def clean(self):
        if not self.hostname or not self.domain_id:
            return

        # Don't allow saving a reserved name
        if ReservedHostname.objects.filter(
                hostname=self.hostname, domain=self.domain).exists():
            raise ValidationError("%s is a reserved hostname." % self.fqdn())

        # Don't allow a server to have the same name as a rotate
        if Rotate.objects.filter(
                hostname=self.hostname, domain=self.domain).exists():
            raise ValidationError("%s is a rotate." % self.fqdn())

    class Meta:
        ordering = ['server_id', 'hostname']


class Rotate(models.Model):
    """Primary and regional rotates."""
    name = models.CharField(
        max_length=63, blank=True, null=True,
        validators=[no_control_characters])
    description = models.CharField(
        max_length=255, blank=True, validators=[no_control_characters])
    hostname = models.CharField(max_length=63, validators=[hostname_validator])
    domain = models.ForeignKey(Domain, on_delete=models.PROTECT)
    regional = models.BooleanField(
        blank=True, default=False,
        help_text="This rotate is an APRS-IS Tier2 primary regional rotate.")
    eligible = models.ManyToManyField(Server, blank=True)

    def __str__(self):
        return self.fqdn()

    def fqdn(self):
        return '.'.join((self.hostname, str(self.domain)))
    fqdn.short_description = "FQDN"

    def serialize(self):
        return (self.fqdn(), {
            'name': self.name,
            'description': self.description,
            'host': self.hostname,
            'domain': str(self.domain),
            'fqdn': self.fqdn(),
            'servers': dict([s.serialize() for s in self.eligible.all()]),
        })

    def clean(self):
        if not self.hostname or not self.domain_id:
            return

        # Don't allow saving a reserved name
        if ReservedHostname.objects.filter(
                hostname=self.hostname, domain=self.domain).exists():
            raise ValidationError("%s is a reserved hostname." % self.fqdn())

        # Don't allow a rotate to have the same name as a server
        if Server.objects.filter(
                hostname=self.hostname, domain=self.domain).exists():
            raise ValidationError("%s is a server." % self.fqdn())

    class Meta:
        ordering = ['hostname']


class ReservedHostname(models.Model):
    """Reserved hostnames, like ns1, used as a blacklist when naming servers"""
    hostname = models.CharField(max_length=63, validators=[hostname_validator])
    domain = models.ForeignKey(Domain, on_delete=models.PROTECT)

    def __str__(self):
        return self.fqdn()

    def fqdn(self):
        return '.'.join((self.hostname, str(self.domain)))
    fqdn.short_description = "FQDN"

    class Meta:
        ordering = ['hostname', 'domain']


# The export views (servers.json, rotates.json, APRServe2.txt) are cached.
# Drop the cache whenever something they are built from changes.

@receiver(post_save, sender=Server)
@receiver(post_delete, sender=Server)
@receiver(post_save, sender=Rotate)
@receiver(post_delete, sender=Rotate)
@receiver(post_save, sender=Domain)
@receiver(m2m_changed, sender=Rotate.eligible.through)
def clear_export_cache(sender, **kwargs):
    cache.clear()


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
@receiver(post_delete, sender=settings.AUTH_USER_MODEL)
def clear_export_cache_on_user_change(sender, update_fields=None, **kwargs):
    # servers.json carries the owner's email address for authenticated users.
    # Deleting a user sets Server.owner to NULL with a bulk update, which
    # sends no signal for the servers, so the user's own deletion has to
    # clear the cache.
    # Logging in saves only last_login, which is not worth a cache flush.
    if update_fields is None or 'email' in update_fields:
        cache.clear()
