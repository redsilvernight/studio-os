use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::sync::Mutex;

use serde::Serialize;

const PROJECT: &str = "studio-os-desktop-dev";
const COMPOSE_FILE: &str = "docker-compose.yml";
const ENV_FILE: &str = ".env";

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Where the packaged Dev stack stands, surfaced by the diagnostics so a Docker
/// failure is visible without opening `server.log`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum LocalServerState {
    NotStarted,
    Starting,
    Ready,
    Failed { error: String },
}

#[derive(Debug, Serialize)]
pub struct LocalServerReport {
    #[serde(flatten)]
    pub state: LocalServerState,
    pub log_file: Option<String>,
}

static STATE: Mutex<LocalServerState> = Mutex::new(LocalServerState::NotStarted);

fn set_state(state: LocalServerState) {
    if let Ok(mut current) = STATE.lock() {
        *current = state;
    }
}

/// The Dev stack report; `None` on Prod, which never runs a local server.
pub fn report() -> Option<LocalServerReport> {
    if !crate::info::dev_channel() {
        return None;
    }
    let state = STATE
        .lock()
        .map(|state| state.clone())
        .unwrap_or(LocalServerState::NotStarted);
    Some(LocalServerReport {
        state,
        log_file: state_dir().map(|dir| dir.join("server.log").display().to_string()),
    })
}

pub fn start(resource_dir: PathBuf) {
    if !crate::info::dev_channel() {
        return;
    }
    set_state(LocalServerState::Starting);
    std::thread::spawn(move || match run(resource_dir) {
        Ok(()) => set_state(LocalServerState::Ready),
        Err(error) => {
            let _ = append_fallback_log(&format!("local server failed: {error}"));
            set_state(LocalServerState::Failed { error });
        }
    });
}

fn run(resource_dir: PathBuf) -> Result<(), String> {
    let source = resource_dir.join("dev-server");
    let compose = source.join(COMPOSE_FILE);
    if !compose.is_file() {
        return Err(format!(
            "missing packaged compose file: {}",
            compose.display()
        ));
    }

    let state = state_dir().ok_or_else(|| "user data directory is unavailable".to_owned())?;
    let mail = state.join("mail");
    fs::create_dir_all(&mail).map_err(|error| format!("create local server data: {error}"))?;
    let env_file = state.join(ENV_FILE);
    ensure_env(&env_file, &mail)
        .map_err(|error| format!("prepare local server environment: {error}"))?;
    let log_path = state.join("server.log");

    compose_command(
        &source,
        &env_file,
        &log_path,
        &["up", "-d", "--build", "postgres", "minio", "minio-init"],
    )?;
    compose_command(
        &source,
        &env_file,
        &log_path,
        &[
            "run",
            "--rm",
            "--build",
            "--no-deps",
            "api",
            "alembic",
            "upgrade",
            "head",
        ],
    )?;
    compose_command(
        &source,
        &env_file,
        &log_path,
        &[
            "up",
            "-d",
            "--build",
            "--wait",
            "api",
            "mcp",
            "dashboard",
            "caddy",
        ],
    )?;
    Ok(())
}

fn state_dir() -> Option<PathBuf> {
    dirs::data_dir().map(|root| root.join("StudioOS-Dev").join("server"))
}

fn ensure_env(path: &Path, mail_dir: &Path) -> io::Result<()> {
    if path.is_file() {
        return Ok(());
    }
    let postgres = random_secret()?;
    let minio = random_secret()?;
    let jwt = random_secret()?;
    let mail = mail_dir
        .to_string_lossy()
        .replace('\\', "/")
        .replace('"', "\\\"");
    let contents = format!(
        "POSTGRES_PASSWORD={postgres}\nMINIO_ROOT_PASSWORD={minio}\nSTUDIO_JWT_SECRET={jwt}\nSTUDIO_DEV_MAIL_DIR=\"{mail}\"\n"
    );
    let temporary = path.with_extension("tmp");
    fs::write(&temporary, contents)?;
    fs::rename(temporary, path)
}

fn random_secret() -> io::Result<String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|error| io::Error::other(error.to_string()))?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn compose_command(
    source: &Path,
    env_file: &Path,
    log_path: &Path,
    operation: &[&str],
) -> Result<(), String> {
    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
        .map_err(|error| format!("open {}: {error}", log_path.display()))?;
    let stdout = log
        .try_clone()
        .map_err(|error| format!("clone server log: {error}"))?;
    let mut command = Command::new("docker");
    command
        .current_dir(source)
        .args(["compose", "--project-name", PROJECT, "--env-file"])
        .arg(env_file)
        .args(["--file", COMPOSE_FILE])
        .args(operation)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(log));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let status = command
        .status()
        .map_err(|error| format!("start Docker Desktop CLI: {error}"))?;
    require_success(status, operation)
}

fn require_success(status: ExitStatus, operation: &[&str]) -> Result<(), String> {
    if status.success() {
        Ok(())
    } else {
        Err(format!(
            "docker compose {} exited with {status}",
            operation.join(" ")
        ))
    }
}

fn append_fallback_log(message: &str) -> io::Result<()> {
    let Some(state) = state_dir() else {
        return Ok(());
    };
    fs::create_dir_all(&state)?;
    let mut log = File::options()
        .create(true)
        .append(true)
        .open(state.join("server.log"))?;
    writeln!(log, "{message}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_environment_is_stable_and_does_not_embed_backslashes() {
        let root = std::env::temp_dir().join(format!("studio-local-server-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let mail = root.join("mail folder");
        fs::create_dir_all(&mail).unwrap();
        let env = root.join(ENV_FILE);
        ensure_env(&env, &mail).unwrap();
        let first = fs::read_to_string(&env).unwrap();
        ensure_env(&env, &mail).unwrap();
        assert_eq!(fs::read_to_string(&env).unwrap(), first);
        assert!(first.contains("STUDIO_DEV_MAIL_DIR=\""));
        assert!(!first.contains('\\'));
        assert!(!first.contains("change-me"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn a_docker_failure_is_reported_with_its_reason() {
        let report = LocalServerReport {
            state: LocalServerState::Failed {
                error: "docker compose up -d exited with exit code: 1".to_owned(),
            },
            log_file: Some("server.log".to_owned()),
        };
        let json = serde_json::to_value(&report).unwrap();
        assert_eq!(json["state"], "failed");
        assert_eq!(
            json["error"],
            "docker compose up -d exited with exit code: 1"
        );
        assert_eq!(json["log_file"], "server.log");
        let ready = LocalServerReport {
            state: LocalServerState::Ready,
            log_file: None,
        };
        assert_eq!(serde_json::to_value(&ready).unwrap()["state"], "ready");
    }
}
