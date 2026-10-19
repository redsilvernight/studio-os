# read_only — messagerie Claude Code

Tâche `b24705d8-5ee3-44e9-a49e-7408c1f233e7`, 16 octobre 2026.
Base : `origin/dev` à `09a2a01b` (PR #154).

## Cause

La démonstration P04 a rapporté un message envoyé à une autre session Claude
locale depuis un lancement `read_only`. L'adaptateur utilisait
`--allowedTools Read,Grep,Glob,mcp__studio-os` et refusait les outils d'écriture.
Cette liste préapprouve les outils ; elle ne retire pas les autres outils
intégrés. Le canal intégré `SendMessage` atteint les autres sessions et ne
requiert pas de permission.

Sources consultées avec Claude Code installé `2.1.287` (`claude --help`) :

- [CLI : allowedTools, tools, disallowedTools](https://code.claude.com/docs/en/cli-reference).
- [Outils : SendMessage et ListAgents](https://code.claude.com/docs/en/tools-reference).
- Code : `packages/studio-client/src/studio_client/harness/claude_code.py`,
  méthodes `headless_argv` et `headless_extra_argv`.

## Correctif

`read_only` fournit maintenant `--tools Read,Grep,Glob` et ajoute `SendMessage`
aux refus explicites. La liste des outils intégrés exclut donc aussi
`ListAgents`, `Agent` et les autres outils non nommés. Les outils MCP restent
indépendants de `--tools` ; l'isolation MCP Studio existante est conservée.

`workspace_write` conserve ses arguments et sa politique. Ce mode n'offre
pas de garantie d'interdiction de la messagerie intégrée ; sa politique
n'est pas modifiée par ce correctif.

## Validation locale

- `uv run --all-packages pytest tests/client tests/harness -q -k
  'not test_real_claude_headless_run_with_strict_isolated_mcp'` :
  **460 passed, 767 skipped, 1 deselected**, 53,31 s.
- Les 767 tests nécessitant PostgreSQL et/ou MinIO n'ont pas tourné.
  `scripts/test-env.ps1` a échoué sur Docker ; une relance normale de Desktop
  a également expiré. Aucune validation PostgreSQL/MinIO n'est revendiquée.
- `uv run --all-packages pytest --noconftest
  tests/client/test_launch_profile_enforce.py::test_claude_read_only_argv_denies_every_writing_tool
  tests/client/test_launch_runner.py -q` : **16 passed**. Ces tests ciblés ne
  dépendent pas de la base ; les conftest sont volontairement désactivés.
- Ruff check et format sur les trois fichiers Python modifiés : succès.
- Mypy sur l'adaptateur : succès. `git diff --check` : succès.
- Revue indépendante en lecture seule : aucun défaut identifié.

Preuves : `output/readonly-messaging/client-harness.{log,xml}` dans le worktree.
La sonde de l'inventaire réel de Claude, API neutralisée sur localhost et
sans tour modèle, a expiré ; elle n'établit aucune garantie runtime.
Le test headless réel authentifié est explicitement non lancé.
La suite complète du dépôt et la CI ne sont pas exécutées à ce stade.

## Suite

Avant clôture : restaurer Docker, rejouer les suites client/harness sans tests
ignorés faute d'infrastructure, obtenir l'accord de push/PR vers `dev`, puis
vérifier la CI et le merge. La tâche reste `in_progress`.
