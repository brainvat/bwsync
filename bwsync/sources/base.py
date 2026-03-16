"""Abstract base class for password sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from bwsync.schema import NormalizedEntry


class BaseSource(ABC):
    """Base class all password source plugins must inherit from."""

    name: str = "base"

    @abstractmethod
    def extract(self) -> list[NormalizedEntry]:
        """Extract all credentials from this source.

        Returns a list of NormalizedEntry objects with passwords populated.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether this source is available on the current system.

        Returns True if the source can be accessed (e.g., Chrome is installed,
        Keychain is reachable).
        """
