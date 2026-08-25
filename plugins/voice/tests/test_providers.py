"""Tests for the provider declaration contract (R20, R21, R23; KTD4, KTD5)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import providers  # noqa: E402


def _stated_environment() -> dict[str, str]:
    """Inert values for every stated setting both providers read."""
    return {
        "VOICE_FORGE_BASE_URL": "http://voice-forge.internal.example",
        "VOICE_FORGE_VOICE_ID": "example-voice",
        "VOICE_HERMES_BASE_URL": "http://127.0.0.1:8765",
        "VOICE_HERMES_PROFILE": "mimir-engineer",
    }


class DeclarationContractTests(unittest.TestCase):
    """A declaration carries endpoint, capabilities, egress, credential name."""

    def test_both_declarations_carry_the_contract_fields(self) -> None:
        with mock.patch.dict(os.environ, _stated_environment(), clear=True):
            forge, hermes = providers.declarations()

        self.assertEqual(forge.name, providers.VOICE_FORGE)
        self.assertEqual(
            forge.invocation_or_endpoint, "http://voice-forge.internal.example"
        )
        self.assertEqual(forge.capabilities, ("text-to-speech",))
        self.assertEqual(forge.egress_class, providers.EgressClass.LOCAL_NETWORK)
        self.assertEqual(forge.credential_env_var, "")

        self.assertEqual(hermes.name, providers.HERMES_XAI)
        self.assertEqual(
            hermes.invocation_or_endpoint, "http://127.0.0.1:8765"
        )
        self.assertEqual(hermes.capabilities, ("speech-to-text",))
        self.assertEqual(
            hermes.egress_class, providers.EgressClass.NAMED_REMOTE_SERVICE
        )
        self.assertEqual(hermes.credential_env_var, "")

    def test_declarations_carry_credential_names_and_never_values(self) -> None:
        with mock.patch.dict(os.environ, _stated_environment(), clear=True):
            declarations = providers.declarations()
        for declaration in declarations:
            with self.subTest(provider=declaration.name):
                self.assertIsInstance(declaration.credential_env_var, str)
                # Both version-one providers declare no credential variable;
                # the field is a name in every case, never a value.
                self.assertEqual(declaration.credential_env_var, "")

    def test_the_empty_credential_name_is_valid(self) -> None:
        declaration = providers.ProviderDeclaration(
            name="example-provider",
            invocation_or_endpoint="http://example.invalid",
            capabilities=("example-capability",),
            egress_class="on-device",
            credential_env_var="",
        )
        self.assertEqual(declaration.credential_env_var, "")

    def test_a_declared_credential_name_is_accepted(self) -> None:
        declaration = providers.ProviderDeclaration(
            name="example-provider",
            invocation_or_endpoint="http://example.invalid",
            capabilities=("example-capability",),
            egress_class="named-remote-service",
            credential_env_var="EXAMPLE_PROVIDER_TOKEN",
        )
        self.assertEqual(declaration.credential_env_var, "EXAMPLE_PROVIDER_TOKEN")

    def test_the_credential_field_rejects_value_shaped_strings(self) -> None:
        for shaped_like_a_value in (
            "a value, not a name",
            "lower-case-name",
            "WITH SPACE",
            "12345678",
        ):
            with self.subTest(candidate=shaped_like_a_value):
                with self.assertRaises(ValueError):
                    providers.ProviderDeclaration(
                        name="example-provider",
                        invocation_or_endpoint="http://example.invalid",
                        capabilities=("example-capability",),
                        egress_class="on-device",
                        credential_env_var=shaped_like_a_value,
                    )

    def test_a_declaration_requires_an_invocation_or_endpoint(self) -> None:
        for missing in ("", "   "):
            with self.subTest(candidate=missing):
                with self.assertRaises(ValueError):
                    providers.ProviderDeclaration(
                        name="example-provider",
                        invocation_or_endpoint=missing,
                        capabilities=("example-capability",),
                        egress_class="on-device",
                    )


class EgressClosedSetTests(unittest.TestCase):
    """Exactly the four R21 literals; external is a predicate, not a value."""

    def test_exactly_the_four_literals_are_accepted(self) -> None:
        accepted = {
            literal: providers.egress_class(literal)
            for literal in (
                "on-device",
                "local-network",
                "named-remote-service",
                "unofficial-remote-endpoint",
            )
        }
        self.assertEqual(
            set(accepted), {member.value for member in providers.EgressClass}
        )
        for literal, member in accepted.items():
            self.assertEqual(member.value, literal)

    def test_anything_else_is_rejected(self) -> None:
        for candidate in ("external", "lan", "local", "internet", ""):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    providers.egress_class(candidate)

    def test_external_is_a_predicate_over_the_closed_set(self) -> None:
        self.assertNotIn(
            "external", [member.value for member in providers.EgressClass]
        )
        self.assertTrue(providers.is_external_egress("named-remote-service"))
        self.assertTrue(
            providers.is_external_egress(
                providers.EgressClass.UNOFFICIAL_REMOTE_ENDPOINT
            )
        )
        self.assertFalse(providers.is_external_egress("local-network"))
        self.assertFalse(providers.is_external_egress("on-device"))

    def test_a_declaration_rejects_an_unknown_egress_class(self) -> None:
        with self.assertRaises(ValueError):
            providers.ProviderDeclaration(
                name="example-provider",
                invocation_or_endpoint="http://example.invalid",
                capabilities=("example-capability",),
                egress_class="external",
            )


class NamedRefusalTests(unittest.TestCase):
    """An unavailable provider raises a named refusal, never a fallback."""

    def test_an_unavailable_provider_names_itself_and_its_prerequisite(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(providers.ProviderRefusal) as caught:
                providers.voice_forge_declaration()
        refusal = caught.exception
        self.assertEqual(refusal.provider, providers.VOICE_FORGE)
        self.assertIn("VOICE_FORGE_BASE_URL", refusal.reason)
        self.assertIn(providers.VOICE_FORGE, str(refusal))

    def test_the_missing_voice_id_is_named_when_the_url_is_stated(self) -> None:
        env = {"VOICE_FORGE_BASE_URL": "http://voice-forge.internal.example"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(providers.ProviderRefusal) as caught:
                providers.voice_forge_declaration()
        refusal = caught.exception
        self.assertEqual(refusal.provider, providers.VOICE_FORGE)
        self.assertIn("VOICE_FORGE_VOICE_ID", refusal.reason)

    def test_no_fallback_to_the_other_provider(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(providers.ProviderRefusal):
                providers.declarations()
            with self.assertRaises(providers.ProviderRefusal):
                providers.get(providers.VOICE_FORGE)
            # The other provider is unaffected and never offered as a
            # substitute: it resolves on its own stated settings alone.
            hermes = providers.get(providers.HERMES_XAI)
            self.assertEqual(hermes.name, providers.HERMES_XAI)

    def test_an_unknown_provider_is_refused_not_substituted(self) -> None:
        with mock.patch.dict(os.environ, _stated_environment(), clear=True):
            with self.assertRaises(providers.ProviderRefusal) as caught:
                providers.get("whisper-cpp")
            refusal = caught.exception
            self.assertEqual(refusal.provider, "whisper-cpp")
            self.assertIn("not a declared provider", refusal.reason)
            # Nothing else is offered in its place: the declared providers
            # still resolve under their own names, and only under them.
            self.assertEqual(
                providers.get(providers.VOICE_FORGE).name, providers.VOICE_FORGE
            )
            self.assertEqual(
                providers.get(providers.HERMES_XAI).name, providers.HERMES_XAI
            )


if __name__ == "__main__":
    unittest.main()
