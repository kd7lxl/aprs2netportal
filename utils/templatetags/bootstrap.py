from django import forms, template

register = template.Library()

# Django message level tags that have no Bootstrap alert class of the
# same name.
ALERT_CLASSES = {
    'debug': 'secondary',
    'error': 'danger',
}


@register.filter
def bs_widget(field):
    """Render a bound form field with the Bootstrap class its widget needs."""
    widget = field.field.widget
    if isinstance(widget, forms.CheckboxInput):
        css = 'form-check-input'
    elif isinstance(widget, forms.Select):
        css = 'form-select'
    else:
        css = 'form-control'
    if widget.attrs.get('class'):
        css = '%s %s' % (widget.attrs['class'], css)
    if field.errors:
        css += ' is-invalid'
    return field.as_widget(attrs={'class': css})


@register.filter
def is_checkbox(field):
    return isinstance(field.field.widget, forms.CheckboxInput)


@register.filter
def alert_class(message):
    """Return the Bootstrap alert class for a django.contrib.messages message."""
    tag = message.level_tag
    return 'alert-%s' % ALERT_CLASSES.get(tag, tag or 'info')
