"""Pinned Manager frontend and local catalog; changes use the managed CLI."""
from pathlib import Path
from ._managed import install_routes

install_routes(Path(__file__).parent)
NODE_CLASS_MAPPINGS = {}
WEB_DIRECTORY = 'js'
