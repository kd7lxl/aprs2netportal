import json
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.cache import cache_page, never_cache

from .forms import SysopServerForm, UserForm
from .models import Rotate, Server

EXPORT_CACHE_SECONDS = 60 * 30


# The export views cache the rendered page on the server, but tell clients
# and proxies not to cache it: consumers must see changes as soon as the
# server-side cache has been cleared.

def cached_export(view):
    """Decorator: cache a view's response in the server-side cache only."""
    @never_cache
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        # Authenticated users get more data from servers.json, so they get
        # separate cache entries.
        cached_view = cache_page(
            EXPORT_CACHE_SECONDS,
            key_prefix="_auth_%s_" % request.user.is_authenticated,
        )(view)
        response = cached_view(request, *args, **kwargs)
        # cache_page stamps the response with an Expires half an hour ahead,
        # which never_cache would leave alone. Remove it; never_cache then
        # sets one in the past.
        del response['Expires']
        return response
    return wrapper


@cached_export
def servers_json(request):
    with_email = request.user.is_authenticated
    return HttpResponse(
        json.dumps(dict([
            s.serialize(with_email=with_email)
            for s in Server.objects.select_related('domain', 'owner')
        ])),
        content_type="application/json",
    )


@cached_export
def rotates_json(request):
    return HttpResponse(
        json.dumps(dict([
            r.serialize()
            for r in Rotate.objects.select_related('domain').prefetch_related(
                'eligible__domain')
        ])),
        content_type="application/json",
    )


@cached_export
def server_list(request):
    main_rotate = get_object_or_404(
        Rotate, hostname='rotate', domain__domain='aprs2.net')
    text = render_to_string('sysop/APRServe2.txt', {
        'rotates': Rotate.objects.filter(regional=True).select_related('domain'),
        'servers': main_rotate.eligible.exclude(deleted=True).order_by(
            'hostname').select_related('domain'),
    })
    # The file has always been served with DOS line endings for the APRS
    # client software reading it. Template loading normalises them away.
    text = text.replace('\r\n', '\n').replace('\n', '\r\n')
    return HttpResponse(text, content_type="text/plain; charset=utf-8")


@login_required
def own_servers(request):
    servers = Server.objects.select_related('domain', 'owner')
    return render(request, 'sysop/index.html', {
        'own_servers': servers.filter(owner=request.user),
        'authorized_servers': servers.filter(authorized_sysops=request.user),
    })


@login_required
def all_servers(request):
    return render(request, 'sysop/index.html', {
        'all_servers': Server.objects.exclude(deleted=True).select_related(
            'domain', 'owner'),
    })


@login_required
def server_detail(request, server_id):
    server = get_object_or_404(Server, id=server_id)
    can_edit = server.can_be_edited_by(request.user)
    form = SysopServerForm(instance=server)

    if can_edit and request.method == "POST":
        form = SysopServerForm(request.POST, instance=server)
        if form.is_valid():
            form.save()
            messages.success(request, '%s saved.' % server)
            return redirect('own_servers')
        else:
            messages.warning(request, 'Form validation error. Details below.')

    return render(request, 'sysop/edit_server.html', {
        'server': server,
        'form': form,
        'can_edit': can_edit,
    })


@login_required
def user_detail(request):
    if request.method == "POST":
        form = UserForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'User settings saved.')
            return redirect('own_servers')
        else:
            messages.warning(request, 'Form validation error. Details below.')
    else:
        form = UserForm(instance=request.user)

    return render(request, 'registration/profile.html', {
        'form': form,
    })
