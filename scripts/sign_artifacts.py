"""Windows code-signing pipeline (release tooling).

Resolves Microsoft SignTool, signs executables with SHA-256 plus an
RFC 3161 timestamp, and fail-closed verifies signatures. No secrets
live here: credentials arrive only via environment variables, and
secret arguments are redacted from every log line.
"""

import glob
import os
import shutil
import subprocess

DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"
SIGNTOOL_EXE = "signtool.exe"
ISCC_EXE = "iscc.exe"

ENV_CERT_PATH = "CIVOLINK_SIGN_CERT_PATH"
ENV_CERT_PASS = "CIVOLINK_SIGN_CERT_PASS"
ENV_THUMBPRINT = "CIVOLINK_SIGN_THUMBPRINT"
ENV_TIMESTAMP_URL = "CIVOLINK_TIMESTAMP_URL"
ENV_ALLOW_UNSIGNED = "CIVOLINK_ALLOW_UNSIGNED"

_RUN_TIMEOUT = 300


class SigningError(Exception):
    """Signing failed: fail-closed, never mark the build successful."""


class VerificationError(Exception):
    """Signature verification failed: fail-closed."""


class ToolNotFoundError(Exception):
    """Required external build tool is not installed."""


def _program_files_dirs():
    """Candidate Program Files roots (x86 SDK path first)."""
    candidates = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(variable, "").strip()
        if root:
            candidates.append(root)
    return candidates


def find_signtool():
    """Absolute signtool.exe path, or None when not installed."""
    found = shutil.which(SIGNTOOL_EXE)
    if found:
        return found
    for root in _program_files_dirs():
        pattern = os.path.join(root, "Windows Kits", "10", "bin",
                               "*", "*", SIGNTOOL_EXE)
        for candidate in sorted(glob.glob(pattern), reverse=True):
            if os.path.isfile(candidate):
                return candidate
    return None


def find_iscc():
    """Absolute ISCC.exe path, or None when Inno Setup is missing."""
    found = shutil.which(ISCC_EXE)
    if found:
        return found
    for root in _program_files_dirs():
        for relative in (os.path.join("Inno Setup 6", "ISCC.exe"),
                         os.path.join("Inno Setup 5", "ISCC.exe")):
            candidate = os.path.join(root, relative)
            if os.path.isfile(candidate):
                return candidate
    return None


class SigningConfig:
    """Signing credentials (never logged in full)."""

    def __init__(self, cert_path="", cert_pass="",
                 thumbprint="", timestamp_url="", allow_unsigned=False):
        self.cert_path = str(cert_path or "").strip()
        self.cert_pass = str(cert_pass or "")
        self.thumbprint = str(thumbprint or "").strip()
        self.timestamp_url = (
            str(timestamp_url or "").strip() or DEFAULT_TIMESTAMP_URL)
        self.allow_unsigned = bool(allow_unsigned)

    def __repr__(self):
        masked = "***" if self.cert_pass else ""
        return (f"SigningConfig(cert_path={self.cert_path!r}, "
                f"cert_pass={masked!r}, "
                f"thumbprint={self.thumbprint!r}, "
                f"timestamp_url={self.timestamp_url!r}, "
                f"allow_unsigned={self.allow_unsigned!r})")

    def credentials_ok(self):
        """True when signing can proceed (or is explicitly waived)."""
        return bool(self.allow_unsigned or self.cert_path
                    or self.thumbprint)

    @classmethod
    def from_env(cls, env=None):
        """Build from CIVOLINK_SIGN_* environment variables."""
        source = env if env is not None else os.environ
        raw_flag = str(source.get(ENV_ALLOW_UNSIGNED, "") or "").strip()
        return cls(
            cert_path=source.get(ENV_CERT_PATH, ""),
            cert_pass=source.get(ENV_CERT_PASS, ""),
            thumbprint=source.get(ENV_THUMBPRINT, ""),
            timestamp_url=source.get(ENV_TIMESTAMP_URL, ""),
            allow_unsigned=raw_flag.lower() in ("1", "true", "yes"))


def redact_command(args):
    """Copy of a command line with secret values masked."""
    redacted = []
    mask_next = False
    for token in args:
        if mask_next:
            redacted.append("***")
            mask_next = False
        elif token == "/p":
            redacted.append(token)
            mask_next = True
        else:
            redacted.append(token)
    return redacted


def _run(cmd, timeout=_RUN_TIMEOUT):
    """Run a tool, capturing output (callers classify failures)."""
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout)


def sign_file(signtool, target, config):
    """Sign one executable; raises SigningError on any failure."""
    if not os.path.isfile(target):
        raise SigningError(f"Nothing to sign (missing file): {target}")
    if not config.cert_path and not config.thumbprint:
        raise SigningError(
            "No signing credential: set CIVOLINK_SIGN_CERT_PATH or "
            "CIVOLINK_SIGN_THUMBPRINT (or pass --allow-unsigned for "
            "local dev builds only).")
    if config.cert_path and not os.path.isfile(config.cert_path):
        raise SigningError(
            f"Certificate file not found: {config.cert_path}")
    cmd = [signtool, "sign", "/fd", "sha256",
           "/tr", config.timestamp_url, "/td", "sha256"]
    if config.thumbprint:
        cmd += ["/sha1", config.thumbprint]
    else:
        cmd += ["/f", config.cert_path]
        if config.cert_pass:
            cmd += ["/p", config.cert_pass]
    cmd.append(target)
    print("sign:", " ".join(redact_command(cmd)))
    try:
        completed = _run(cmd)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SigningError(f"signtool failed to launch: {exc}") from exc
    if completed.returncode != 0:
        raise SigningError(
            "signtool signing failed for "
            f"{target} (exit {completed.returncode}): "
            f"{(completed.stdout + completed.stderr).strip()[-2000:]}")
    return (completed.stdout or "").strip()


def verify_file(signtool, target):
    """Verify signature + trust chain; raises VerificationError."""
    if not os.path.isfile(target):
        raise VerificationError(
            f"Nothing to verify (missing file): {target}")
    cmd = [signtool, "verify", "/pa", "/v", target]
    try:
        completed = _run(cmd)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(
            f"signtool verify failed to launch: {exc}") from exc
    output = ((completed.stdout or "")
              + "\n" + (completed.stderr or "")).strip()
    if completed.returncode != 0 or "Successfully verified" not in output:
        raise VerificationError(
            f"Signature verification failed for {target} "
            f"(exit {completed.returncode}): {output[-2000:]}")
    return output
