"""Connectors: source adapters that implement the `Connector` Protocol."""

from .base import Connector
from ._models import ChangeEvent, ChangeKind, ResourceRef

__all__ = ["Connector", "ChangeEvent", "ChangeKind", "ResourceRef"]
