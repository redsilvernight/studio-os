---
id: DEC-0131
title: B4 clôturée sans Authenticode ni test Smart App Control
status: accepted
date: '2026-09-26'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0131 — B4 clôturée sans Authenticode ni test Smart App Control

Décision humaine du 2026-09-26 : considérer B4 « Signature & confiance » terminée dès lors que tout le périmètre hors Authenticode est livré. Aucun certificat Authenticode ne sera acheté pour raison de coût. Les critères « signtool verify sur tous les exécutables » et « installation propre sous Smart App Control » sont donc explicitement exemptés/non applicables, et la tâche Smart App Control est close sans exécution. La confiance livrée repose sur minisign/Tauri updater, le refus des updates altérées ou non signées, SHA256SUMS/provenance, la plomberie Authenticode dormante et le runbook de rotation/révocation. Cette décision complète DEC-0129 et autorise l'override done de l'étape B4.
