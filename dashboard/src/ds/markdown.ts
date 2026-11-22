/**
 * Texte mis en forme sûr (R1-composants) : sous-ensemble Markdown rendu SANS
 * HTML brut. Tout le texte est échappé d'abord ; seules les balises émises
 * ici existent dans la sortie. Pris en charge : titres (#…###), paragraphes,
 * listes à puces/numérotées, citations, blocs et code en ligne, gras, italique,
 * liens http(s)/mailto. Les images ne sont jamais chargées (rendues en
 * texte), les autres schémas (javascript:, data:, vbscript:…) sont refusés.
 */
import { esc } from "../ui";

const SAFE_LINK = /^(https?:\/\/|mailto:)[^\s<>"']+$/i;

function inline(raw: string): string {
  // Code en ligne d'abord : son contenu n'est pas interprété.
  const parts = raw.split(/(`[^`\n]+`)/g);
  return parts
    .map((part) => {
      if (/^`[^`\n]+`$/.test(part)) return `<code>${esc(part.slice(1, -1))}</code>`;
      let out = esc(part);
      // Image : jamais de <img>, on garde l'alternative en texte.
      out = out.replace(/!\[([^\]]*)\]\(([^)]*)\)/g, (_m, alt: string) => alt);
      out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text: string, href: string) => {
        // esc() a déjà encodé &, <, >, " : on teste la forme décodée.
        const plain = href.replace(/&amp;/g, "&");
        return SAFE_LINK.test(plain) ? `<a href="${esc(plain)}" rel="noopener noreferrer" target="_blank">${text}</a>` : text;
      });
      out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
      return out;
    })
    .join("");
}

export function dsMarkdown(source: string): string {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const html: string[] = [];
  let paragraph: string[] = [];
  let list: { tag: "ul" | "ol"; items: string[] } | null = null;

  const flushParagraph = (): void => {
    if (paragraph.length > 0) html.push(`<p>${inline(paragraph.join(" "))}</p>`);
    paragraph = [];
  };
  const flushList = (): void => {
    if (list !== null) html.push(`<${list.tag}>${list.items.map((item) => `<li>${inline(item)}</li>`).join("")}</${list.tag}>`);
    list = null;
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i] ?? "";
    if (/^```/.test(line)) {
      flushParagraph();
      flushList();
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i] ?? "")) {
        code.push(lines[i] ?? "");
        i += 1;
      }
      html.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    const bullet = /^\s*[-*]\s+(.+)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    const quote = /^>\s?(.*)$/.exec(line);
    if (line.trim() === "") {
      flushParagraph();
      flushList();
    } else if (heading !== null) {
      flushParagraph();
      flushList();
      // Un seul h1 par page : les titres du contenu commencent à h3.
      const level = (heading[1] ?? "#").length + 2;
      html.push(`<h${level}>${inline(heading[2] ?? "")}</h${level}>`);
    } else if (bullet !== null || numbered !== null) {
      flushParagraph();
      const tag = bullet !== null ? "ul" : "ol";
      if (list !== null && list.tag !== tag) flushList();
      list ??= { tag, items: [] };
      list.items.push((bullet ?? numbered)?.[1] ?? "");
    } else if (quote !== null) {
      flushParagraph();
      flushList();
      html.push(`<blockquote>${inline(quote[1] ?? "")}</blockquote>`);
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return `<div class="ds-prose">${html.join("")}</div>`;
}
