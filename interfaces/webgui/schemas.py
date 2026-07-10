"""Request-Bodies der Web-Schicht (I-RW.2).

Frueher Closures/Modulglobale in app.py; ausgelagert, damit die Domaenen-Router
(routers/*) sie teilen koennen, ohne aus app.py zu importieren (kein Zyklus).
"""

from __future__ import annotations

from pydantic import BaseModel


class TaskCreateBody(BaseModel):
    task_type: str
    scope: str
    model: str = "phi4-mini"
    prompt: str = ""


class SubmitBody(BaseModel):
    response: str
    task_type: str
    producer: str = "manual"


class ApplyBody(BaseModel):
    scope: str
    confirm: bool = False


class SettingsBody(BaseModel):
    auto_apply: bool


class PlanGoalBody(BaseModel):
    task_type: str
    scope: str
    depends_on: list[int] = []


class DecomposePromptBody(BaseModel):
    prompt: str


class IntentBody(BaseModel):
    prompt: str
    # I-6.5: Korrekturtext -> an den Prompt angehaengt -> neue Plan-Edition.
    revision: str = ""
    # Manueller Pfad (model:human): vorab-verfasste Zerlegung direkt uebergeben
    # (ohne Modell). goals=None -> Modell-Pfad; gesetzt -> Direkt-Submit.
    goals: list[PlanGoalBody] | None = None
    understanding: str = ""
    not_covered: list[str] = []
    # Manueller Pfad, Variante Rohtext: komplette Zerlegungs-Antwort (Markdown
    # nach core/plan_format, JSON-Altformat toleriert) -- Parsen uebernimmt der
    # Server (EIN Parser fuer Modell- und Copy-Paste-Pfad).
    response: str = ""


class PlanEditBody(BaseModel):
    goals: list[PlanGoalBody]
