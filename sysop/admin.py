from django.contrib import admin
from django.db.models import Count

from .models import Domain, ReservedHostname, Rotate, Server

admin.site.site_header = "Tier2 Administration"
admin.site.site_title = "Tier2 Administration"


class RotateInline(admin.TabularInline):
    model = Rotate.eligible.through
    extra = 1


admin.site.register(Domain)
admin.site.register(ReservedHostname)


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = (
        'server_id',
        'fqdn',
        'owner',
        'ipv4',
        'ipv6',
        'out_of_service',
        'deleted',
    )
    list_filter = (
        'deleted',
        'out_of_service',
        'domain',
        'rotate',
    )
    search_fields = ('server_id', 'hostname', 'ipv4', 'ipv6', 'owner__username')
    list_select_related = ('domain', 'owner')
    inlines = (RotateInline,)


@admin.register(Rotate)
class RotateAdmin(admin.ModelAdmin):
    filter_horizontal = (
        'eligible',
    )
    list_display = ('__str__', 'name', 'server_count', 'regional')
    list_select_related = ('domain',)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            server_count=Count('eligible'))

    @admin.display(ordering='server_count')
    def server_count(self, inst):
        return inst.server_count
