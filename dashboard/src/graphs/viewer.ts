import type {
  GraphNode,
  GraphNodeRef,
} from "../platform/generated/local-contracts.generated";
import type { ViewerData } from "./model";
import "./viewer.css";
export type { ViewerData } from "./model";
export const INITIAL_NODE_LIMIT = 80;
export const MAX_VISIBLE_NODES = 200;
export const MAX_VISIBLE_EDGES = 400;
const PAGE = 30;
const key = (r: GraphNodeRef): string =>
  JSON.stringify([r.source_id, r.node_id]);
const ref = (n: GraphNode): GraphNodeRef => ({
  source_id: n.provenance.source_id,
  node_id: n.node_id,
});
function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text = "",
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  e.textContent = text;
  return e;
}
let sequence = 0;
export function mountGraphViewer(
  root: HTMLElement,
  initial: ViewerData,
  options: {
    onExpand?: (ref: GraphNodeRef) => Promise<void>;
    onMore?: () => Promise<void>;
    canLoadMore?: () => boolean;
  } = {},
): { update(data: ViewerData): void; dispose(): void } {
  let data = initial,
    limit = INITIAL_NODE_LIMIT,
    page = 0,
    disposed = false;
  let selected: string | undefined;
  let pinned: string | undefined;
  let positions = new Map<string, [number, number]>();
  let filtered: GraphNode[] = [],
    index = new Map<string, GraphNode>();
  let x = 0,
    y = 0,
    zoom = 1;
  const shell = element("section");
  shell.className = "graph-viewer";
  shell.setAttribute("aria-label", "Explorateur de graphe");
  const controls = element("div");
  controls.className = "graph-controls";
  const search = element("input");
  search.type = "search";
  search.placeholder = "Rechercher un nœud";
  search.setAttribute("aria-label", search.placeholder);
  const kinds = element("select");
  kinds.setAttribute("aria-label", "Type de nœud");
  const sources = element("select");
  sources.setAttribute("aria-label", "Source du nœud");
  const status = element("p");
  status.setAttribute("role", "status");
  const warning = element("p");
  warning.className = "graph-warning";
  const error = element("p");
  error.setAttribute("role", "alert");
  const legend = element("p");
  legend.className = "graph-legend";
  const ns = "http://www.w3.org/2000/svg";
  const svg = <K extends keyof SVGElementTagNameMap>(
    tag: K,
  ): SVGElementTagNameMap[K] => document.createElementNS(ns, tag);
  const canvas = svg("svg");
  canvas.setAttribute("viewBox", "0 0 900 600");
  canvas.setAttribute("tabindex", "0");
  canvas.setAttribute("role", "group");
  canvas.setAttribute(
    "aria-label",
    "Graphe dirigé. Flèches : déplacer. Plus et moins : zoom. Zéro : réinitialiser.",
  );
  const markerId = `graph-arrow-${++sequence}`;
  const defs = svg("defs"),
    marker = svg("marker"),
    arrow = svg("path");
  for (const [k, v] of Object.entries({
    id: markerId,
    viewBox: "0 0 10 10",
    refX: "19",
    refY: "5",
    markerWidth: "7",
    markerHeight: "7",
    orient: "auto",
  }))
    marker.setAttribute(k, v);
  arrow.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
  marker.append(arrow);
  defs.append(marker);
  const scene = svg("g");
  canvas.append(defs, scene);
  const results = element("div");
  results.className = "graph-results";
  results.setAttribute("aria-label", "Résultats des nœuds");
  const pager = element("div");
  pager.className = "graph-controls";
  const details = element("aside");
  details.className = "graph-details";
  details.setAttribute("aria-label", "Détails du nœud");
  const frontier = element("div");
  frontier.className = "graph-frontier";
  const body = element("div");
  body.className = "graph-body";
  const visual = element("div");
  visual.append(canvas, results, pager);
  body.append(visual, details);
  const button = (label: string, action: () => void): HTMLButtonElement => {
    const b = element("button", label);
    b.type = "button";
    b.addEventListener("click", action);
    return b;
  };
  const transform = (): void => {
    scene.setAttribute("transform", `translate(${x} ${y}) scale(${zoom})`);
  };
  const reset = (): void => {
    x = 0;
    y = 0;
    zoom = 1;
    transform();
  };
  const scale = (factor: number): void => {
    zoom = Math.min(4, Math.max(0.25, zoom * factor));
    transform();
  };
  const run = async (
    b: HTMLButtonElement,
    action: () => Promise<void>,
  ): Promise<void> => {
    b.disabled = true;
    error.textContent = "";
    try {
      await action();
    } catch (cause) {
      if (!disposed)
        error.textContent =
          cause instanceof Error ? cause.message : "Chargement impossible";
    } finally {
      if (!disposed) b.disabled = false;
    }
  };
  const expandButton = (r: GraphNodeRef): HTMLButtonElement => {
    const b = button(`Charger ${r.source_id} / ${r.node_id}`, () => {
      if (options.onExpand) void run(b, () => options.onExpand!(r));
    });
    b.disabled = !options.onExpand;
    return b;
  };
  const select = (node: GraphNode): void => {
    selected = key(ref(node));
    centerSelection.disabled = false;
    scene
      .querySelectorAll("[data-node-key]")
      .forEach((item) =>
        item.classList.toggle(
          "is-selected",
          item.getAttribute("data-node-key") === selected,
        ),
      );
    results
      .querySelectorAll("button")
      .forEach((item) =>
        item.setAttribute(
          "aria-pressed",
          String(item.dataset.nodeKey === selected),
        ),
      );
    details.replaceChildren(element("h3", node.label));
    const source = data.sources.find(
      (s) => s.source_id === node.provenance.source_id,
    );
    const rows: [string, string | null | undefined][] = [
      ["Type", node.kind],
      ["Source", node.provenance.source_id],
      ["Fournisseur", source?.provider_id],
      ["Horodatage", source?.generated_at],
      ["Extracteur", node.provenance.extractor],
      ["Confiance", node.provenance.confidence],
      ["Preuve", node.provenance.evidence],
      ["URI", node.uri],
    ];
    const dl = element("dl");
    for (const [label, value] of rows)
      if (value != null) dl.append(element("dt", label), element("dd", value));
    details.append(dl);
    for (const direction of ["Entrantes", "Sortantes"] as const) {
      details.append(element("h4", direction));
      const list = element("ul");
      const edges = data.edges.filter(
        (e) =>
          key(direction === "Entrantes" ? e.target : e.source) === selected,
      );
      let relationPage = 0;
      const renderRelations = (): void => {
        list.replaceChildren();
        for (const edge of edges.slice(
          relationPage * PAGE,
          (relationPage + 1) * PAGE,
        )) {
          const r = direction === "Entrantes" ? edge.source : edge.target,
            other = index.get(key(r));
          const li = element("li", `${edge.kind} → `);
          if (other) li.append(button(other.label, () => select(other)));
          else {
            li.append(
              element("span", `${r.source_id} / ${r.node_id} (non chargé)`),
            );
            if (data.frontier.some((f) => key(f) === key(r)))
              li.append(expandButton(r));
          }
          li.append(
            element(
              "small",
              `${edge.provenance.source_id} · ${edge.provenance.extractor} · ${edge.provenance.confidence}${edge.provenance.evidence ? ` · ${edge.provenance.evidence}` : ""}`,
            ),
          );
          list.append(li);
        }
      };
      const relationControls = element("div");
      relationControls.className = "graph-controls";
      const previous = button("Relations précédentes", () => {
        relationPage--;
        renderRelations();
        refreshRelations();
      });
      const next = button("Relations suivantes", () => {
        relationPage++;
        renderRelations();
        refreshRelations();
      });
      const count = element("span");
      const refreshRelations = (): void => {
        previous.disabled = relationPage === 0;
        next.disabled = (relationPage + 1) * PAGE >= edges.length;
        count.textContent = `${edges.length} relations · page ${relationPage + 1} / ${Math.max(1, Math.ceil(edges.length / PAGE))}`;
      };
      relationControls.append(previous, count, next);
      renderRelations();
      refreshRelations();
      details.append(list, relationControls);
    }
  };
  const renderResults = (): void => {
    const focusedLabel = pager.contains(document.activeElement)
      ? document.activeElement?.textContent
      : undefined;
    results.replaceChildren();
    pager.replaceChildren();
    for (const node of filtered.slice(page * PAGE, (page + 1) * PAGE)) {
      const b = button(
        `${node.label} · ${node.kind} · ${node.provenance.source_id}`,
        () => select(node),
      );
      b.dataset.nodeKey = key(ref(node));
      b.setAttribute("aria-pressed", String(b.dataset.nodeKey === selected));
      results.append(b);
    }
    const previous = button("Résultats précédents", () => {
      page--;
      renderResults();
    });
    previous.disabled = page === 0;
    const next = button("Résultats suivants", () => {
      page++;
      renderResults();
    });
    next.disabled = (page + 1) * PAGE >= filtered.length;
    pager.append(
      previous,
      element(
        "span",
        `Page ${page + 1} / ${Math.max(1, Math.ceil(filtered.length / PAGE))}`,
      ),
      next,
    );
    if (focusedLabel) {
      const requested = focusedLabel === previous.textContent ? previous : next;
      (requested.disabled
        ? previous.disabled
          ? next
          : previous
        : requested
      ).focus();
    }
  };
  const render = (): void => {
    const query = search.value.trim().toLocaleLowerCase();
    filtered = data.nodes.filter(
      (n) =>
        (!kinds.value || n.kind === kinds.value) &&
        (!sources.value || n.provenance.source_id === sources.value) &&
        (!query ||
          `${n.label} ${n.node_id} ${n.kind} ${n.provenance.source_id}`
            .toLocaleLowerCase()
            .includes(query)),
    );
    page = Math.min(page, Math.max(0, Math.ceil(filtered.length / PAGE) - 1));
    const visible = filtered.slice(0, limit);
    const pinnedNode = pinned ? index.get(pinned) : undefined;
    if (pinnedNode && !visible.some((n) => key(ref(n)) === pinned)) {
      if (visible.length >= limit) visible.pop();
      visible.push(pinnedNode);
    }
    positions = new Map<string, [number, number]>();
    visible.forEach((n, i) => {
      const a = i * Math.PI * (3 - Math.sqrt(5)),
        r = 30 + Math.sqrt(i / Math.max(1, visible.length)) * 245;
      positions.set(key(ref(n)), [
        450 + r * Math.cos(a) * 1.5,
        300 + r * Math.sin(a),
      ]);
    });
    scene.replaceChildren();
    let edgeCount = 0;
    for (const edge of data.edges) {
      if (edgeCount >= MAX_VISIBLE_EDGES) break;
      const a = positions.get(key(edge.source)),
        b = positions.get(key(edge.target));
      if (!a || !b) continue;
      const line = svg("line");
      for (const [k, v] of Object.entries({
        x1: a[0],
        y1: a[1],
        x2: b[0],
        y2: b[1],
        "marker-end": `url(#${markerId})`,
      }))
        line.setAttribute(k, String(v));
      const title = svg("title");
      title.textContent = `${edge.source.node_id} → ${edge.kind} → ${edge.target.node_id}`;
      line.append(title);
      scene.append(line);
      edgeCount++;
    }
    for (const node of visible) {
      const id = key(ref(node)),
        p = positions.get(id)!,
        group = svg("g");
      group.dataset.nodeKey = id;
      group.setAttribute(
        "class",
        id === selected ? "graph-node is-selected" : "graph-node",
      );
      group.setAttribute("role", "button");
      group.setAttribute("tabindex", "0");
      group.setAttribute("aria-label", `${node.label}, ${node.kind}`);
      group.setAttribute("transform", `translate(${p[0]} ${p[1]})`);
      const circle = svg("circle");
      circle.setAttribute("r", "8");
      const text = svg("text");
      text.setAttribute("x", "11");
      text.setAttribute("y", "4");
      text.textContent =
        node.label.length > 24 ? `${node.label.slice(0, 24)}…` : node.label;
      group.append(circle, text);
      group.addEventListener("click", () => select(node));
      group.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          e.stopPropagation();
          select(node);
        }
      });
      scene.append(group);
    }
    status.textContent = data.nodes.length
      ? `${visible.length} / ${filtered.length} nœuds correspondants dessinés (${data.nodes.length} en mémoire), ${edgeCount} relations dessinées.${filtered.length ? "" : " Aucune correspondance."}`
      : "Aucun nœud disponible.";
    warning.textContent = data.partial
      ? "Vue partielle : des données restent à charger ou ont été tronquées."
      : "";
    legend.textContent = `Types : ${[...new Set(visible.map((n) => n.kind))].join(", ") || "aucun"} · Relations : ${[...new Set(data.edges.map((e) => e.kind))].join(", ") || "aucune"} · Flèche : source → cible`;
    moreVisible.disabled =
      limit >= MAX_VISIBLE_NODES || visible.length >= filtered.length;
    renderResults();
  };
  const moreVisible = button("Afficher plus de nœuds", () => {
    limit = Math.min(MAX_VISIBLE_NODES, limit + 40);
    render();
  });
  const centerSelection = button("Centrer la sélection", () => {
    if (!selected || !index.has(selected)) return;
    if (!positions.has(selected)) {
      pinned = selected;
      render();
    }
    const position = positions.get(selected);
    if (position) {
      x = 450 - position[0] * zoom;
      y = 300 - position[1] * zoom;
      transform();
    }
    canvas.focus();
  });
  centerSelection.disabled = true;
  controls.append(
    search,
    kinds,
    sources,
    button("Zoom +", () => scale(1.25)),
    button("Zoom −", () => scale(0.8)),
    button("Réinitialiser la vue", reset),
    centerSelection,
    moreVisible,
  );
  const more = options.onMore
    ? button("Charger la page suivante", () => {
        void run(more!, options.onMore!).finally(() => {
          if (more && !disposed)
            more.disabled = options.canLoadMore
              ? !options.canLoadMore()
              : false;
        });
      })
    : undefined;
  if (more) controls.append(more);
  for (const field of [search, kinds, sources])
    field.addEventListener(field === search ? "input" : "change", () => {
      page = 0;
      pinned = undefined;
      render();
    });
  canvas.addEventListener("keydown", (e) => {
    if (e.target !== canvas) return;
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-30, 0],
      ArrowRight: [30, 0],
      ArrowUp: [0, -30],
      ArrowDown: [0, 30],
    };
    const move = moves[e.key];
    if (move) {
      e.preventDefault();
      x += move[0];
      y += move[1];
      transform();
    } else if (e.key === "+" || e.key === "=") {
      e.preventDefault();
      scale(1.25);
    } else if (e.key === "-") {
      e.preventDefault();
      scale(0.8);
    } else if (e.key === "0") {
      e.preventDefault();
      reset();
    }
  });
  let drag: { id: number; x: number; y: number } | undefined;
  canvas.addEventListener("pointerdown", (e) => {
    if (e.target instanceof Element && e.target.closest("[data-node-key]"))
      return;
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag || drag.id !== e.pointerId) return;
    const width = canvas.getBoundingClientRect().width,
      ratio = width ? 900 / width : 1;
    x += (e.clientX - drag.x) * ratio;
    y += (e.clientY - drag.y) * ratio;
    drag.x = e.clientX;
    drag.y = e.clientY;
    transform();
  });
  canvas.addEventListener("pointerup", () => {
    drag = undefined;
  });
  canvas.addEventListener("pointercancel", () => {
    drag = undefined;
  });
  shell.append(controls, status, warning, error, legend, body, frontier);
  root.replaceChildren(shell);
  const update = (next: ViewerData): void => {
    if (disposed) return;
    data = next;
    index = new Map(data.nodes.map((n) => [key(ref(n)), n]));
    if (more)
      more.disabled = options.canLoadMore ? !options.canLoadMore() : false;
    const option = (label: string, value: string): HTMLOptionElement => {
      const item = element("option", label);
      item.value = value;
      return item;
    };
    for (const [field, values, label] of [
      [
        kinds,
        [...new Set(data.nodes.map((n) => n.kind))] as string[],
        "Tous les types",
      ],
      [
        sources,
        [...new Set(data.nodes.map((n) => n.provenance.source_id))],
        "Toutes les sources",
      ],
    ] as const) {
      const value = field.value;
      field.replaceChildren(
        option(label, ""),
        ...values.map((v) => option(v, v)),
      );
      field.value = values.includes(value) ? value : "";
    }
    let frontierPage = 0;
    const renderFrontier = (): void => {
      const focusedLabel = frontier.contains(document.activeElement)
        ? document.activeElement?.textContent
        : undefined;
      frontier.replaceChildren(
        element(
          "h4",
          `Références non chargées (${data.frontier.length}) · page ${frontierPage + 1} / ${Math.max(1, Math.ceil(data.frontier.length / PAGE))}`,
        ),
      );
      data.frontier
        .slice(frontierPage * PAGE, (frontierPage + 1) * PAGE)
        .forEach((r) => frontier.append(expandButton(r)));
      const previous = button("Références précédentes", () => {
        frontierPage--;
        renderFrontier();
      });
      previous.disabled = frontierPage === 0;
      const next = button("Références suivantes", () => {
        frontierPage++;
        renderFrontier();
      });
      next.disabled = (frontierPage + 1) * PAGE >= data.frontier.length;
      frontier.append(previous, next);
      if (
        focusedLabel === previous.textContent ||
        focusedLabel === next.textContent
      ) {
        const requested =
          focusedLabel === previous.textContent ? previous : next;
        (requested.disabled
          ? previous.disabled
            ? next
            : previous
          : requested
        ).focus();
      }
    };
    renderFrontier();
    render();
    const current = selected ? index.get(selected) : undefined;
    if (current) select(current);
    else {
      selected = undefined;
      centerSelection.disabled = true;
      details.replaceChildren(
        element("p", "Sélectionnez un nœud pour consulter sa provenance."),
      );
    }
  };
  update(initial);
  return {
    update,
    dispose: () => {
      disposed = true;
      shell.remove();
      index.clear();
    },
  };
}
