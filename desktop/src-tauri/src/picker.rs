//! Semantic native pickers (P3): `choose_folder` and `choose_file`.
//!
//! These are deliberately NOT a filesystem API. The user drives a native OS
//! dialog and the renderer receives only the path the user explicitly chose
//! (plus its display name) — never file contents, never a directory listing,
//! never a path of its own choosing. Nothing is scanned or read here.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

const MAX_TITLE: usize = 80;
const MAX_FILTERS: usize = 8;
const MAX_FILTER_NAME: usize = 40;
const MAX_EXTENSIONS: usize = 16;
const MAX_EXTENSION_LEN: usize = 10;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PickKind {
    Folder,
    File,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FileFilter {
    pub name: String,
    pub extensions: Vec<String>,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, default)]
pub struct PickerOptions {
    pub title: Option<String>,
    pub filters: Vec<FileFilter>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OptionsError {
    Title,
    Filters,
    FilterOnFolder,
}

impl OptionsError {
    pub fn code(self) -> &'static str {
        "invalid_picker_options"
    }
    pub fn message(self) -> &'static str {
        match self {
            Self::Title => "The dialog title is empty, too long or contains control characters.",
            Self::Filters => {
                "The file filters are not valid (name, plain alphanumeric extensions)."
            }
            Self::FilterOnFolder => "A folder picker does not take file filters.",
        }
    }
}

/// Bounded, plain-text options only: nothing here can widen what the dialog
/// may reach (the OS dialog decides what the user can browse).
pub fn validate_options(kind: PickKind, options: &PickerOptions) -> Result<(), OptionsError> {
    if let Some(title) = &options.title {
        let t = title.trim();
        if t.is_empty() || t.chars().count() > MAX_TITLE || t.chars().any(char::is_control) {
            return Err(OptionsError::Title);
        }
    }
    if kind == PickKind::Folder && !options.filters.is_empty() {
        return Err(OptionsError::FilterOnFolder);
    }
    if options.filters.len() > MAX_FILTERS {
        return Err(OptionsError::Filters);
    }
    for f in &options.filters {
        let name = f.name.trim();
        if name.is_empty()
            || name.chars().count() > MAX_FILTER_NAME
            || name.chars().any(char::is_control)
        {
            return Err(OptionsError::Filters);
        }
        if f.extensions.is_empty() || f.extensions.len() > MAX_EXTENSIONS {
            return Err(OptionsError::Filters);
        }
        for e in &f.extensions {
            let ok = !e.is_empty()
                && e.len() <= MAX_EXTENSION_LEN
                && e.chars().all(|c| c.is_ascii_alphanumeric());
            if !ok {
                return Err(OptionsError::Filters);
            }
        }
    }
    Ok(())
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum PickOutcome {
    Selected { path: String, display_name: String },
    Cancelled,
}

/// Where the choice comes from. The real implementation opens a native dialog;
/// tests inject a canned answer.
pub trait Chooser {
    fn choose(&self, kind: PickKind, options: &PickerOptions) -> Option<PathBuf>;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PickError {
    Options(OptionsError),
    /// The chosen path cannot be represented as text for the renderer.
    UnsupportedPath,
}

pub fn pick(
    chooser: &dyn Chooser,
    kind: PickKind,
    options: &PickerOptions,
) -> Result<PickOutcome, PickError> {
    validate_options(kind, options).map_err(PickError::Options)?;
    let Some(path) = chooser.choose(kind, options) else {
        return Ok(PickOutcome::Cancelled);
    };
    let text = path.to_str().ok_or(PickError::UnsupportedPath)?.to_owned();
    let display_name = path
        .file_name()
        .and_then(|n| n.to_str())
        .map(str::to_owned)
        .unwrap_or_else(|| text.clone());
    Ok(PickOutcome::Selected {
        path: text,
        display_name,
    })
}

/// The native OS dialog, parented to the main window.
pub struct NativeChooser {
    pub parent: tauri::WebviewWindow,
}

impl Chooser for NativeChooser {
    fn choose(&self, kind: PickKind, options: &PickerOptions) -> Option<PathBuf> {
        let mut dialog = rfd::FileDialog::new().set_parent(&self.parent);
        if let Some(title) = &options.title {
            dialog = dialog.set_title(title.trim());
        }
        match kind {
            PickKind::Folder => dialog.pick_folder(),
            PickKind::File => {
                for f in &options.filters {
                    let ext: Vec<&str> = f.extensions.iter().map(String::as_str).collect();
                    dialog = dialog.add_filter(f.name.trim(), &ext);
                }
                dialog.pick_file()
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Canned(Option<PathBuf>);
    impl Chooser for Canned {
        fn choose(&self, _: PickKind, _: &PickerOptions) -> Option<PathBuf> {
            self.0.clone()
        }
    }

    struct MustNotOpen;
    impl Chooser for MustNotOpen {
        fn choose(&self, _: PickKind, _: &PickerOptions) -> Option<PathBuf> {
            panic!("a dialog must not open for invalid options");
        }
    }

    fn opts(title: Option<&str>, filters: Vec<(&str, Vec<&str>)>) -> PickerOptions {
        PickerOptions {
            title: title.map(str::to_owned),
            filters: filters
                .into_iter()
                .map(|(n, e)| FileFilter {
                    name: n.into(),
                    extensions: e.into_iter().map(String::from).collect(),
                })
                .collect(),
        }
    }

    #[test]
    fn a_selected_folder_returns_only_its_path_and_name() {
        let out = pick(
            &Canned(Some(PathBuf::from("C:/Jeux/Mon Projet"))),
            PickKind::Folder,
            &PickerOptions::default(),
        )
        .unwrap();
        assert_eq!(
            out,
            PickOutcome::Selected {
                path: "C:/Jeux/Mon Projet".into(),
                display_name: "Mon Projet".into()
            }
        );
    }

    #[test]
    fn a_selected_file_returns_path_and_display_name() {
        let out = pick(
            &Canned(Some(PathBuf::from("C:/x/notes.md"))),
            PickKind::File,
            &opts(Some("Choisir"), vec![("Markdown", vec!["md"])]),
        )
        .unwrap();
        assert_eq!(
            out,
            PickOutcome::Selected {
                path: "C:/x/notes.md".into(),
                display_name: "notes.md".into()
            }
        );
    }

    #[test]
    fn cancelling_is_a_normal_outcome_not_an_error() {
        assert_eq!(
            pick(&Canned(None), PickKind::Folder, &PickerOptions::default()).unwrap(),
            PickOutcome::Cancelled
        );
        assert_eq!(
            pick(&Canned(None), PickKind::File, &PickerOptions::default()).unwrap(),
            PickOutcome::Cancelled
        );
    }

    #[test]
    fn invalid_options_are_refused_before_any_dialog_opens() {
        let bad = [
            (PickKind::File, opts(Some(""), vec![])),
            (PickKind::File, opts(Some(&"t".repeat(81)), vec![])),
            (PickKind::File, opts(Some("a\u{0}b"), vec![])),
            (PickKind::Folder, opts(None, vec![("Tous", vec!["md"])])),
            (PickKind::File, opts(None, vec![("Tous", vec!["*"])])),
            (PickKind::File, opts(None, vec![("Tous", vec!["*.md"])])),
            (PickKind::File, opts(None, vec![("Tous", vec![".md"])])),
            (PickKind::File, opts(None, vec![("Tous", vec![])])),
            (PickKind::File, opts(None, vec![("", vec!["md"])])),
            (
                PickKind::File,
                opts(None, (0..9).map(|_| ("F", vec!["md"])).collect()),
            ),
        ];
        for (kind, o) in bad {
            assert!(
                matches!(pick(&MustNotOpen, kind, &o), Err(PickError::Options(_))),
                "{o:?}"
            );
        }
    }

    #[test]
    fn options_reject_unknown_fields_so_no_path_can_be_smuggled_in() {
        let ok: PickerOptions = serde_json::from_str(r#"{"title":"Choisir"}"#).unwrap();
        assert_eq!(ok.title.as_deref(), Some("Choisir"));
        for hostile in [
            r#"{"directory":"C:/Windows"}"#,
            r#"{"path":"C:/"}"#,
            r#"{"filters":[{"name":"a","extensions":["md"],"glob":"*"}]}"#,
        ] {
            assert!(
                serde_json::from_str::<PickerOptions>(hostile).is_err(),
                "{hostile}"
            );
        }
    }

    #[test]
    fn the_outcome_serialises_with_a_status_tag() {
        let v = serde_json::to_value(PickOutcome::Cancelled).unwrap();
        assert_eq!(v, serde_json::json!({"status":"cancelled"}));
        let v = serde_json::to_value(PickOutcome::Selected {
            path: "p".into(),
            display_name: "n".into(),
        })
        .unwrap();
        assert_eq!(
            v,
            serde_json::json!({"status":"selected","path":"p","display_name":"n"})
        );
    }
}
