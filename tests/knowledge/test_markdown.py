from __future__ import annotations

from studio_client.knowledge.markdown import LinkKind, parse_markdown


def test_title_prefers_frontmatter_then_heading_then_fallback() -> None:
    with_frontmatter = parse_markdown("---\ntitle: From FM\n---\n# Heading\n", "stem")
    assert with_frontmatter.title == "From FM"
    without_frontmatter = parse_markdown("# Heading\n", "stem")
    assert without_frontmatter.title == "Heading"
    assert parse_markdown("no heading here\n", "stem").title == "stem"


def test_heading_lines_are_relative_to_the_file() -> None:
    text = "---\ntitle: T\n---\n# First\n\ntext\n\n## Second\n"
    parsed = parse_markdown(text, "stem")
    assert [(heading.level, heading.text, heading.line) for heading in parsed.headings] == [
        (1, "First", 4),
        (2, "Second", 8),
    ]
    assert parsed.headings[1].slug == "second"


def test_body_is_preserved_verbatim() -> None:
    text = "---\ntitle: T\n---\n# H\n\n*user* content  \n"
    parsed = parse_markdown(text, "stem")
    assert parsed.body == "# H\n\n*user* content  \n"


def test_fenced_code_is_never_structure() -> None:
    text = "# Real\n\n```md\n# Not a heading\n[link](x.md)\n#not-a-tag\n```\n"
    parsed = parse_markdown(text, "stem")
    assert [heading.text for heading in parsed.headings] == ["Real"]
    assert parsed.links == ()
    assert parsed.tags == ()


def test_links_and_wikilinks_are_extracted() -> None:
    text = (
        "# H\n\n[design](design.md) and [[combat]] and [[note|Label]] "
        "and ![image](img.png) and ![[embedded]]\n"
    )
    parsed = parse_markdown(text, "stem")
    assert [(link.kind, link.target, link.embed) for link in parsed.links] == [
        (LinkKind.MARKDOWN, "design.md", False),
        (LinkKind.WIKILINK, "combat", False),
        (LinkKind.WIKILINK, "note", False),
        (LinkKind.MARKDOWN, "img.png", True),
        (LinkKind.WIKILINK, "embedded", True),
    ]
    assert parsed.links[2].label == "Label"


def test_anchors_and_fragments_are_kept() -> None:
    parsed = parse_markdown("# H\n\n[x](a.md#L12) and [[b#Heading]] and [y](#local)\n", "stem")
    assert parsed.links[0].path_part == "a.md"
    assert parsed.links[0].fragment == "L12"
    assert parsed.links[1].path_part == "b"
    assert parsed.links[1].fragment == "Heading"
    assert parsed.links[2].path_part == ""
    assert parsed.links[2].fragment == "local"


def test_tags_from_frontmatter_and_inline() -> None:
    text = "---\ntags: [mechanics, balance]\n---\n# H\n\ntext #inline #other/tag\n"
    parsed = parse_markdown(text, "stem")
    assert parsed.tags == ("mechanics", "balance", "inline", "other/tag")


def test_tags_from_a_frontmatter_string() -> None:
    parsed = parse_markdown("---\ntags: alpha, beta\n---\n# H\n", "stem")
    assert parsed.tags == ("alpha", "beta")


def test_headings_and_urls_are_not_tags() -> None:
    parsed = parse_markdown("# Heading\n\nhttps://example.test/#frag and word#notag\n", "stem")
    assert parsed.tags == ()


def test_links_inside_inline_code_are_ignored() -> None:
    parsed = parse_markdown("# H\n\n`[x](a.md)`\n", "stem")
    assert parsed.links == ()
