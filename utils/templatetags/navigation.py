from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def active(context, url_name, return_value='active'):
    """Return `return_value` if the current page is the named URL."""
    request = context.get('request')
    match = getattr(request, 'resolver_match', None)
    if match is not None and match.url_name == url_name:
        return return_value
    return ''
