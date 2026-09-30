"""Typed cross-domain references between master-data tables (Phase 3.2).

A reference is a (domain, key) pair parsed from a string so cross-table
links fail closed at parse time instead of at lookup time. Two syntaxes
are accepted: a bare key ("portland_cement_42_5") resolved against an
expected domain, and an explicitly scoped key
("materials:portland_cement_42_5"). A prefix that is a known domain
name is always a scope; any other prefix (e.g. "user:uuid" for user-
scope overrides) is NOT a domain scope — lenient mode treats the whole
string as a bare key so such ids still fail closed at lookup with
UnknownMasterDataKeyError, while strict mode rejects them at parse.
"""

from dataclasses import dataclass

from ..core.errors import ValidationError
from .schemas import DOMAINS

__all__ = ["CrossDomainReference"]

_DOMAIN_PREFIXES = frozenset(DOMAINS)


@dataclass(frozen=True)
class CrossDomainReference:
    """A typed pointer to one record in one master-data domain."""

    domain: str
    key: str

    @classmethod
    def parse(cls, text, *, domain=None, strict_scope=False):
        """Parse ``text`` into a typed reference.

        * ``domain`` — the expected domain for a bare key (mandatory
          unless ``text`` carries a domain scope).
        * ``strict_scope`` — reject unknown prefixes (e.g. "user:xyz")
          at parse time instead of falling back to bare-key treatment.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValidationError(
                f"cross-domain reference must be a non-empty string; "
                f"got {text!r}")
        text = text.strip()
        if ":" in text:
            prefix, _, key = text.partition(":")
            key = key.strip()
            if prefix in _DOMAIN_PREFIXES:
                if not key:
                    raise ValidationError(
                        f"cross-domain reference {text!r} has an empty key")
                if domain is not None and prefix != domain:
                    raise ValidationError(
                        f"cross-domain reference {text!r} targets domain "
                        f"{prefix!r}; expected {domain!r}")
                return cls(domain=prefix, key=key)
            if strict_scope:
                raise ValidationError(
                    f"cross-domain reference {text!r} has unknown domain "
                    f"prefix {prefix!r}; expected one of "
                    f"{sorted(_DOMAIN_PREFIXES)}")
            if domain is None:
                raise ValidationError(
                    f"cross-domain reference {text!r} is ambiguous; "
                    f"supply the expected domain")
            # User-scope ids ("user:uuid") are bare keys, not scopes.
            return cls(domain=domain, key=text)
        if domain is None:
            raise ValidationError(
                f"bare cross-domain reference {text!r} is ambiguous; "
                f"supply the expected domain or a 'domain:key' scope")
        return cls(domain=domain, key=text)

    def lookup(self, repository):
        """Fetch the referenced record; unknown domains/keys fail closed."""
        return repository.get(self.domain, self.key)

    def __str__(self) -> str:
        return f"{self.domain}:{self.key}"
