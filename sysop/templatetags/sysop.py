import re

from django import template

from ..models import CONTROL_CHARACTERS

register = template.Library()


@register.inclusion_tag('sysop/servertable.html')
def servertable(servers):
    return {'servers': servers}


@register.filter
def oneline(value):
    """
    Make a value safe to print on one line of a line-based text file:
    line breaks and other control characters become spaces.
    """
    # None prints as "None", as it always has in APRServe2.txt.
    return re.sub(CONTROL_CHARACTERS + '+', ' ', str(value)).strip()

