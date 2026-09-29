//! Persistent Desktop session (DEC-0142): the rotating refresh token lives in
//! the OS secret store (Windows Credential Manager, macOS Keychain) — never in
//! a settings file, never in the webview storage. One entry per server origin,
//! so a token is only ever presented back to the server that issued it.

/// Upper bound shared with the API (`RefreshRequest.refresh_token`).
const MAX_SECRET_LEN: usize = 256;
const SERVICE: &str = "stable.studio-os.desktop.session";

#[derive(Debug, PartialEq, Eq)]
pub enum VaultError {
    /// The renderer handed something that is not a refresh token.
    InvalidSecret,
    /// The OS secret store refused or is missing.
    Unavailable,
}

/// A refresh token is an opaque URL-safe base64 string; anything else is
/// refused before it reaches the OS store.
pub fn is_valid_secret(secret: &str) -> bool {
    !secret.is_empty()
        && secret.len() <= MAX_SECRET_LEN
        && secret
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

/// The store account for a server origin (`None` = the build default).
pub fn account_for(origin: Option<&str>) -> String {
    origin.unwrap_or("build-default").to_owned()
}

/// The narrow slice of a secret store the shell needs; the OS keyring in the
/// app, an in-memory map in the tests.
pub trait SecretStore {
    fn get(&self, account: &str) -> Result<Option<String>, VaultError>;
    fn set(&self, account: &str, secret: &str) -> Result<(), VaultError>;
    fn delete(&self, account: &str) -> Result<(), VaultError>;
}

pub struct OsKeyring;

impl OsKeyring {
    fn entry(account: &str) -> Result<keyring::Entry, VaultError> {
        keyring::Entry::new(SERVICE, account).map_err(|_| VaultError::Unavailable)
    }
}

impl SecretStore for OsKeyring {
    fn get(&self, account: &str) -> Result<Option<String>, VaultError> {
        match Self::entry(account)?.get_password() {
            Ok(secret) => Ok(Some(secret)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(_) => Err(VaultError::Unavailable),
        }
    }

    fn set(&self, account: &str, secret: &str) -> Result<(), VaultError> {
        Self::entry(account)?
            .set_password(secret)
            .map_err(|_| VaultError::Unavailable)
    }

    fn delete(&self, account: &str) -> Result<(), VaultError> {
        match Self::entry(account)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(_) => Err(VaultError::Unavailable),
        }
    }
}

/// The stored token, or `None`. A stored value that is not a token (tampered
/// or from an older format) is dropped rather than handed to the renderer.
pub fn load(store: &dyn SecretStore, account: &str) -> Result<Option<String>, VaultError> {
    match store.get(account)? {
        Some(secret) if is_valid_secret(&secret) => Ok(Some(secret)),
        Some(_) => {
            store.delete(account)?;
            Ok(None)
        }
        None => Ok(None),
    }
}

pub fn save(store: &dyn SecretStore, account: &str, secret: &str) -> Result<(), VaultError> {
    if !is_valid_secret(secret) {
        return Err(VaultError::InvalidSecret);
    }
    store.set(account, secret)
}

pub fn clear(store: &dyn SecretStore, account: &str) -> Result<(), VaultError> {
    store.delete(account)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::collections::HashMap;

    #[derive(Default)]
    struct Memory(RefCell<HashMap<String, String>>);

    impl SecretStore for Memory {
        fn get(&self, account: &str) -> Result<Option<String>, VaultError> {
            Ok(self.0.borrow().get(account).cloned())
        }
        fn set(&self, account: &str, secret: &str) -> Result<(), VaultError> {
            self.0.borrow_mut().insert(account.into(), secret.into());
            Ok(())
        }
        fn delete(&self, account: &str) -> Result<(), VaultError> {
            self.0.borrow_mut().remove(account);
            Ok(())
        }
    }

    const TOKEN: &str = "k3Jd_9-aZq0vYx7uWm2Nf4Lr8Ts1Pe6Hb5Gc0Da3Qo";

    #[test]
    fn only_url_safe_tokens_up_to_the_api_bound_are_accepted() {
        assert!(is_valid_secret(TOKEN));
        assert!(is_valid_secret(&"a".repeat(256)));
        assert!(!is_valid_secret(""));
        assert!(!is_valid_secret(&"a".repeat(257)));
        for bad in ["a b", "a\nb", "a/b", "a+b", "a=b", "é"] {
            assert!(!is_valid_secret(bad), "{bad:?}");
        }
    }

    #[test]
    fn save_load_clear_round_trip() {
        let store = Memory::default();
        assert_eq!(load(&store, "https://a.example"), Ok(None));
        save(&store, "https://a.example", TOKEN).unwrap();
        assert_eq!(load(&store, "https://a.example"), Ok(Some(TOKEN.into())));
        clear(&store, "https://a.example").unwrap();
        assert_eq!(load(&store, "https://a.example"), Ok(None));
    }

    #[test]
    fn a_token_is_bound_to_its_server_origin() {
        let store = Memory::default();
        save(&store, &account_for(Some("https://a.example")), TOKEN).unwrap();
        assert_eq!(
            load(&store, &account_for(Some("https://b.example"))),
            Ok(None)
        );
        assert_eq!(load(&store, &account_for(None)), Ok(None));
    }

    #[test]
    fn an_invalid_secret_is_never_stored() {
        let store = Memory::default();
        assert_eq!(
            save(&store, "x", "not a token"),
            Err(VaultError::InvalidSecret)
        );
        assert!(store.0.borrow().is_empty());
    }

    #[test]
    fn a_tampered_stored_value_is_dropped_not_returned() {
        let store = Memory::default();
        store.set("x", "<script>").unwrap();
        assert_eq!(load(&store, "x"), Ok(None));
        assert!(store.0.borrow().is_empty());
    }
}
