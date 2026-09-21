# P5 → P3 : patch d'intégration navigation (isolé, 5 lignes)

Le Workspace Manager n'apporte **aucun** changement AppShell. Pour exposer
l'entrée, P3 (Desktop Shell, lane A) applique ce seul patch après le merge
des deux lanes :

```ts
import { workspaceNavEntry } from "../workspaces/workspaces";

// dans la construction du menu principal, à côté des autres entrées :
menu.push(workspaceNavEntry()); // { hash: "#/workspaces", label: "Dossiers" }
```

Et une route paresseuse vers `workspaceListHtml` / `workspaceDetailHtml`
alimentées par `platform.request("workspace.validate" | "workspace.get_config")`.

En attendant P3, le module reste montable tel quel en web (le pont répond
`not_supported`, les vues affichent l'état sans promesse).
