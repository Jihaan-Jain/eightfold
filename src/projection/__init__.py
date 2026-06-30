"""src/projection/__init__.py — Public API for the projection layer."""

from src.projection.config_resolver import ConfigResolver, ProjectionConfig
from src.projection.factory import ProjectorFactory
from src.projection.field_selector import FieldSelector
from src.projection.projector import Projector

__all__ = ["Projector", "ProjectorFactory", "FieldSelector", "ConfigResolver", "ProjectionConfig"]
