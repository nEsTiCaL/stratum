# Manuell gepflegt (Quelle: schemas/result_prob.schema.json).
# findings/risks/recommendations als Top-Level entfernt — liegen jetzt in content.
# confidence wird vom Worker aus dem Modell-Tier berechnet, nicht vom LLM geliefert.

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from . import provenance_schema


class ArtifactType(StrEnum):
    code_summary = 'code_summary'
    code_explanation = 'code_explanation'
    review_findings = 'review_findings'
    refactor_plan = 'refactor_plan'
    debug_analysis = 'debug_analysis'
    test_generation = 'test_generation'
    docstring = 'docstring'
    plan = 'plan'
    patch = 'patch'


class ResultProb(BaseModel):
    model_config = ConfigDict(extra='forbid')

    artifact_type: Annotated[
        ArtifactType,
        Field(
            description='Typ des prob-Artefakts, vom Worker aus task_type abgeleitet'
        ),
    ]
    scope: Annotated[
        str,
        Field(
            description='Scope-Schluessel: [repo-id::]typ:pfad[#symbolpfad[/arity]]',
            pattern=(
                r'^([A-Za-z0-9_.-]+::)?(repo|file|module|symbol):[^#]*'
                r'(#[A-Za-z0-9_.]+(/[0-9]+)?)?$'
            ),
        ),
    ]
    content: Annotated[
        dict[str, Any],
        Field(
            description=(
                'LLM-Ausgabe geparst: text (Pflicht), findings/risks/'
                'recommendations (optional, plain text), model_self_reported (optional)'
            )
        ),
    ]
    confidence: Annotated[
        float,
        Field(
            description='Vertrauenswert aus dem Modell-Tier (Worker-berechnet)',
            ge=0.0,
            le=1.0,
        ),
    ]
    provenance: provenance_schema.Provenance
