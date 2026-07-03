# Prob-Dogfooding: eigenen Code per Worker/Human reviewen lassen

Ergaenzung zu `ops_dogfooding-smoketest` (das deckt N1 = det-Index-Queries ab).
Hier: die PROB-Schleife -- Stratum analysiert eigenen Code via LLM-Worker (lokal)
oder Human-Pfad (Dashboard/Chatbot). Ergebnisformat + API: `spec_rest-api`
(Sektion Prob-Tasks). Key: `.local/host.md` (nie in memory/, S9).

## Loop (curl-only -> kein WSL-Churn)

```
1. WSL-Session offen halten (sonst zyklen die Container, siehe ops_docker-server):
   wsl -d Debian -- sleep 3600      # im Hintergrund starten
2. Task anlegen:
   curl -s -X POST localhost:8000/api/task -H "Authorization: Bearer <KEY>" \
     -H "Content-Type: application/json" \
     -d '{"task_type":"explain","scope":"file:core/scope.py","model":"phi4-mini"}'
3. Fortschritt: GET /api/tasks -> Task-Objekt hat .progress {tokens,tok_s,pct}
   (done-Tasks verschwinden aus der Liste). phi4 auf CPU ~1.5 tok/s -> Minuten.
4. Ergebnis: GET /api/result/<id> -> content.text / .findings / .recommendations
   (Ueberschriften-Split, identisch human+LLM).
```

## Routing-Gotcha auf Profil-D-Hosts (CPU-only; aktuelles Host-Profil: .local/host.md)

Der Worker waehlt das Modell NICHT nach dem `model`-Feld des Tasks, sondern per
`core/router.py` (TASK_REQUIREMENTS je task_type). Auf Profil D (nur phi4-mini
lokal, kein Cloud pre-S3) folgt daraus:

- **Lokal lauffaehig** (phi4-mini reicht): `summarize`, `explain` -- verifiziert
  (Task 8 summarize, Task 10 explain -> done, content korrekt gesplittet).
- **Braucht Cloud** (Regel "review->Cloud"): `review`, `architecture`,
  `cross_module`, `crypto_audit` u.a. -> KEIN lokaler Kandidat -> Task failt mit
  `AssertionError` (leer) aus `EscalationLoop` (validator.py:236, leere
  Kandidatenliste, ungraceful; Fix offen). Auf diesem Host daher NUR ueber den
  Human-Pfad: `"model":"human"` -> Dashboard claimen -> Prompt in Chatbot ->
  Antwort einreichen (format-tolerant, gleicher Split).

Merke fuers Dogfooding: fuer echtes Code-Review am eigenen Code hier `model:human`
nehmen (oder ab S3 Cloud). Fuer schnelle Zusammenfassung/Erklaerung phi4-mini.
Genaue Typ->Modell-Grenze: `core/router.py` TASK_REQUIREMENTS + MODEL_CAPABILITIES.

## Warum das fuer die naechste Schleife zaehlt

N1 (det) liefert Struktur (Symbole/Deps); prob liefert Urteil (Bugs, Design).
Ein eigener Review-Task auf gerade geaenderte Dateien deckt Regressionen/Smells
auf, die der Index nicht sieht -- und testet gleichzeitig Worker, Router, Split
und das Ergebnisformat am eigenen wachsenden Code (N2-Vorstufe, `plan_nutzstufen`).
