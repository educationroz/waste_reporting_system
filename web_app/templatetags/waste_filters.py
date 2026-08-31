"""Template filters for the waste system UI."""

from django import template

from api_app.thumbnails import generate_thumbnail

register = template.Library()


@register.filter
def thumbnail(file_field, size='100x100'):
    """
    Return a lazily-generated, cached thumbnail URL for an ImageField value.

    Usage in templates:
        <img src="{{ request.photo|thumbnail:'90x90' }}" ...>
    Falls back to the original .url whenever generation is disabled or fails,
    so thumbnails never 404 a page.
    """
    return generate_thumbnail(file_field, size)