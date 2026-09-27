"""The retained identity ledger: every bundle a persisted release may name (#271).

Persisted Graph Releases name a protected-assembly bundle and a schema contract by
identity.  Once the compatibility runtime is gone, these code-owned bundles are
the only way such a release is runnable, so removing one strands every release
that names it.  The ledger below is written as literals (C44; epic correction
C-24): it must never be imported from the code it checks.

The resolvable set must be a superset of the ledger.  Removing a bundle turns this
RED; adding one does not, but its identity must then be appended here.
"""

from __future__ import annotations

import pytest

from src.services.agent_runtime import MODEL_DRIVEN_AGENT_KEYS
from src.services.agent_schema_registry import SCHEMA_CONTRACT_BUNDLES, AgentSchemaRegistry
from src.services.agent_schema_types import SchemaContractIdentity, SchemaOverlay
from src.services.graph_definition_manifest import ContentIdentity
from src.services.prompt_assembler import PromptAssembler

PROTECTED_ASSEMBLY_LEDGER = {
    (1, "e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852"),
    (2, "fb651a0d28276a0daf7b0db09f2648eb6b50d9429a7100cfaf69e3fc2b08592a"),
}

SCHEMA_CONTRACT_LEDGER = {
    ("architect", 1, "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd"),
    ("data_analyst", 1, "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281"),
    ("builder", 1, "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387"),
    ("build_reviewer", 1, "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d"),
    ("fixer", 1, "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297"),
    ("fix_reviewer", 1, "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df"),
    ("deck_reviewer", 1, "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467"),
    ("architect", 2, "a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122"),
    ("data_analyst", 2, "0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5"),
    ("builder", 2, "65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad"),
    ("build_reviewer", 2, "20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1"),
    ("fixer", 2, "a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143"),
    ("fix_reviewer", 2, "bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99"),
    ("deck_reviewer", 2, "c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3"),
}


def test_the_ledger_covers_every_role_at_both_schema_versions():
    assert {(role, version) for role, version, _ in SCHEMA_CONTRACT_LEDGER} == {
        (role, version) for role in MODEL_DRIVEN_AGENT_KEYS for version in (1, 2)
    }


@pytest.mark.parametrize(("version", "digest"), sorted(PROTECTED_ASSEMBLY_LEDGER))
def test_each_retained_protected_assembly_resolves(version, digest):
    bundle = PromptAssembler().resolve_bundle(ContentIdentity(version=version, digest=digest))
    assert (bundle.identity.version, bundle.identity.digest) == (version, digest)


@pytest.mark.parametrize(("role", "version", "digest"), sorted(SCHEMA_CONTRACT_LEDGER))
def test_each_retained_schema_contract_resolves(role, version, digest):
    registry = AgentSchemaRegistry()
    identity = SchemaContractIdentity(role, version, digest)
    assert registry.identity_for(role, version) == identity
    composed = registry.compose(role, identity, SchemaOverlay())
    assert composed.model is not None


def test_the_resolvable_bundles_are_a_superset_of_the_ledger():
    resolvable_protected = set(PromptAssembler()._bundles)
    assert PROTECTED_ASSEMBLY_LEDGER <= resolvable_protected

    resolvable_schema = {
        (bundle.identity.agent_key, bundle.identity.version, bundle.identity.digest)
        for bundle in SCHEMA_CONTRACT_BUNDLES.values()
    }
    assert SCHEMA_CONTRACT_LEDGER <= resolvable_schema
