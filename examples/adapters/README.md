# Adapters P10 — exemples NON NORMATIFS

Ces fichiers illustrent une projection locale d'une même définition
canonique Studi'OS (`ResolvedAgentDefinition` P5) vers deux harnesses.
Ils ne sont **pas** la référence : le contrat générique Studi'OS
(`packages/studio-contracts`, `ResolvedAgentDefinition`) reste la seule
vérité normative (P10/DEC-0074).

- `claude-code/gate-keeper.md` : sortie de `ClaudeCodeAdapter`
  (format observé `.claude/agents/*.md` : `name`/`description`/`model` + corps Markdown).
- `opencode/gate-keeper.md` : sortie de `OpenCodeAdapter`
  (format observé `.opencode/agents/*.md` : `description`/`mode` + corps Markdown).

Même intention canonique des deux côtés : le corps Markdown partagé
(`render_shared_body`) ne diffère que par le marqueur d'adapter.
Les écarts (pas de `tools` inventé, pas de `permission` inventée,
`model` seulement si le runtime résolu nomme un modèle concret)
sont signalés en warnings structurés par l'adapter, jamais tus.

Régénérer depuis l'implémentation réelle (aucune édition manuelle) :
voir la commande documentée dans DEC-0074 § Exemples.
