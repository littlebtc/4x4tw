from django import template
from django.template.defaultfilters import stringfilter
import re
# http://stackoverflow.com/questions/721035/django-templates-stripping-spaces

register = template.Library()
@register.filter(name='spacify')
@stringfilter
def spacify(text):
    result = re.sub(r"\s", "&nbsp;" , text)
    return result

