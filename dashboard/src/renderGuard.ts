/**
 * Garde anti-race du shell (UI-2).
 *
 * Chaque appel à `render()` prend un jeton (`next()`). Les vues rendent
 * dans un nœud détaché ; seul le rendu dont le jeton est encore courant
 * (`isCurrent()`) est attaché au DOM. Une navigation plus récente invalide
 * les rendus en vol : une ancienne route ne repeint jamais la courante.
 *
 * Pure logique, sans DOM : testée en unitaire. N'introduit ni framework
 * ni state manager. SSE/auth/store inchangés (ils déclenchent `render()`,
 * la garde arbitre).
 */
export interface RenderGuard {
  next(): number;
  isCurrent(id: number): boolean;
}

export function createRenderGuard(): RenderGuard {
  let seq = 0;
  return {
    next: (): number => {
      seq += 1;
      return seq;
    },
    isCurrent: (id: number): boolean => id === seq,
  };
}
