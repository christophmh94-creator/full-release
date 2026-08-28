"""Render the tracker BBCode from a Jinja2 template (autoescape off - this is BBCode)."""
import os

from jinja2 import Environment, FileSystemLoader


def render_bbcode(template_path, ctx):
    tdir = os.path.dirname(template_path) or "."
    tname = os.path.basename(template_path)
    env = Environment(
        loader=FileSystemLoader(tdir),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(tname)
    return template.render(**ctx)
