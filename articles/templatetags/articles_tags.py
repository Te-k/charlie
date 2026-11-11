from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.dateformat import format as date_format

register = template.Library()


@register.filter
def day_label(value):
    """'Today', 'Yesterday', weekday for the last week, else a full date."""
    day = timezone.localdate(value)
    today = timezone.localdate()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    if today - day < timedelta(days=7):
        return date_format(day, "l")
    if day.year == today.year:
        return date_format(day, "F j")
    return date_format(day, "F j, Y")


@register.filter
def is_relative_day(value):
    """True when day_label() gives a relative name (Today, Yesterday, weekday)."""
    return timezone.localdate() - timezone.localdate(value) < timedelta(days=7)
