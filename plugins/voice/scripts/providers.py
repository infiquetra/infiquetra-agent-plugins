"""Provider declarations for the voice package.

Voice ships no provider implementations. Each provider is declared — its
invocation or endpoint, its capabilities, its egress class, and the name of
any credential environment variable it needs, never the value — and Voice
preflights and reports. Nothing is installed, provisioned, discovered, or
silently substituted: an unavailable provider is a named refusal.

Version one declares exactly two providers, built in code from the stated
settings rather than read from a provider configuration file:

- ``voice-forge`` — text-to-speech on the Mac mini over the local network,
  egress class ``local-network``.
- ``hermes-xai`` — speech-to-text through the local Hermes relay; the named
  remote service is xAI. The relay is loopback transport, and a loopback
  address never downgrades the egress class.

Neither declaration carries a credential variable name: the speech-to-text
route's upstream credential is owned by the relay, and the relay's loopback
session token is a transport detail, not a declared credential.

The egress class is a stated value from a closed set of four literals.
"External" is deliberately not a fifth value: it is a derived predicate over
the set, which is the distinction Voice must draw between audio that leaves
the machine and audio that stays on the local network.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

import settings

__all__ = [
    "ProviderRefusal",
    "EgressClass",
    "ProviderDeclaration",
    "VOICE_FORGE",
    "HERMES_XAI",
    "egress_class",
    "is_external_egress",
    "voice_forge_declaration",
    "hermes_xai_declaration",
    "declarations",
    "get",
]

VOICE_FORGE = "voice-forge"
HERMES_XAI = "hermes-xai"


class ProviderRefusal(Exception):
    """A named refusal for one provider.

    Carries the provider name and the missing prerequisite (or, for an
    unknown name, the reason nothing can serve it), so preflight and use can
    report both by name. Nothing ever substitutes for the provider: a
    refusal is terminal for the operation that needed it, never a fallback.
    """

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"provider {provider!r}: {reason}")


class EgressClass(str, enum.Enum):
    """The closed set of egress classes.

    Exactly four literals. ``external`` is not a member: it is the predicate
    :func:`is_external_egress` over this set.
    """

    ON_DEVICE = "on-device"
    LOCAL_NETWORK = "local-network"
    NAMED_REMOTE_SERVICE = "named-remote-service"
    UNOFFICIAL_REMOTE_ENDPOINT = "unofficial-remote-endpoint"


#: The classes whose audio leaves the machine. The other two stay local.
EXTERNAL_EGRESS_CLASSES = frozenset(
    {EgressClass.NAMED_REMOTE_SERVICE, EgressClass.UNOFFICIAL_REMOTE_ENDPOINT}
)


def egress_class(value: object) -> EgressClass:
    """Admit exactly the four literals of the closed set and reject the rest."""
    try:
        return EgressClass(value)
    except ValueError:
        accepted = ", ".join(member.value for member in EgressClass)
        raise ValueError(
            f"unknown egress class {value!r}; the closed set is: {accepted}"
        ) from None


def is_external_egress(value: EgressClass | str) -> bool:
    """True when the class's audio leaves the machine.

    ``named-remote-service`` and ``unofficial-remote-endpoint`` are
    external; ``on-device`` and ``local-network`` are not. A loopback
    transport address never downgrades the class.
    """
    return egress_class(value) in EXTERNAL_EGRESS_CLASSES


#: The credential field carries an environment variable NAME. A value-shaped
#: string — spaces, lowercase payloads, anything that is not an environment
#: identifier — is rejected here so a credential can never ride along in a
#: declaration, even by accident.
_CREDENTIAL_ENV_VAR_NAME = re.compile(r"\A[A-Z][A-Z0-9_]*\Z")


@dataclass(frozen=True)
class ProviderDeclaration:
    """One declared provider.

    ``credential_env_var`` is the name of the environment variable holding
    any credential the provider needs — never a value. Empty is a valid
    contract: it states that the provider needs no credential variable of
    its own, which is true of both version-one providers.
    """

    name: str
    invocation_or_endpoint: str
    capabilities: tuple[str, ...]
    egress_class: EgressClass | str
    credential_env_var: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("a provider declaration must name its provider")
        if (
            not isinstance(self.invocation_or_endpoint, str)
            or not self.invocation_or_endpoint.strip()
        ):
            raise ValueError(
                f"provider {self.name!r} declares no invocation or endpoint"
            )
        if not self.capabilities:
            raise ValueError(f"provider {self.name!r} declares no capabilities")
        for capability in self.capabilities:
            if not isinstance(capability, str) or not capability.strip():
                raise ValueError(
                    f"provider {self.name!r} declares an empty capability"
                )
        object.__setattr__(self, "egress_class", egress_class(self.egress_class))
        if self.credential_env_var:
            if not _CREDENTIAL_ENV_VAR_NAME.match(self.credential_env_var):
                raise ValueError(
                    f"provider {self.name!r} declares a credential value, not a "
                    "name: the field carries an environment variable name only"
                )


def voice_forge_declaration() -> ProviderDeclaration:
    """The Voice Forge text-to-speech declaration.

    Raises :class:`ProviderRefusal` naming the missing prerequisite when a
    stated setting is absent or empty. The voice id is a prerequisite of the
    provider as a whole and is validated here; synthesis itself reads it
    through ``settings``.
    """
    try:
        base_url = settings.forge_base_url()
        settings.forge_voice_id()
    except settings.SettingsRefusal as refusal:
        raise ProviderRefusal(VOICE_FORGE, f"missing prerequisite: {refusal}") from refusal
    return ProviderDeclaration(
        name=VOICE_FORGE,
        invocation_or_endpoint=base_url,
        capabilities=("text-to-speech",),
        egress_class=EgressClass.LOCAL_NETWORK,
    )


def hermes_xai_declaration() -> ProviderDeclaration:
    """The xAI speech-to-text declaration, through the Hermes loopback relay.

    The relay address is loopback transport; the named remote service is
    xAI, so the egress class is ``named-remote-service``. Voice never reads
    the relay's upstream credential, copies it, or declares a variable for
    it, and the loopback session token is a transport detail, never a
    declared credential.
    """
    try:
        base_url = settings.hermes_base_url()
        settings.hermes_profile()
    except settings.SettingsRefusal as refusal:
        raise ProviderRefusal(HERMES_XAI, f"missing prerequisite: {refusal}") from refusal
    return ProviderDeclaration(
        name=HERMES_XAI,
        invocation_or_endpoint=base_url,
        capabilities=("speech-to-text",),
        egress_class=EgressClass.NAMED_REMOTE_SERVICE,
    )


def declarations() -> tuple[ProviderDeclaration, ProviderDeclaration]:
    """Both version-one declarations, in fixed order."""
    return (voice_forge_declaration(), hermes_xai_declaration())


_DECLARED_BUILDERS = {
    VOICE_FORGE: voice_forge_declaration,
    HERMES_XAI: hermes_xai_declaration,
}


def get(name: str) -> ProviderDeclaration:
    """Resolve one declared provider by exact name.

    An unknown name is a refusal, not a search: no other provider is
    offered in its place.
    """
    builder = _DECLARED_BUILDERS.get(name)
    if builder is None:
        raise ProviderRefusal(
            name, "is not a declared provider, and nothing substitutes for it"
        )
    return builder()
