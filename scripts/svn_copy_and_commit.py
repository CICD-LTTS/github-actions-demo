import os
import sys
import shutil
import subprocess
import tempfile
import datetime
import xml.etree.ElementTree as ET

def run(cmd, cwd=None, check=True, capture=False):
    """Run a command with logging."""
    print("> " + " ".join(cmd) + (f"  (cwd={cwd})" if cwd else ""))
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture
    )

def ensure_tool(name):
    """Ensure a CLI tool exists."""
    try:
        run([name, "--version"], check=True)
    except Exception as e:
        print(f"ERROR: Required tool not found: {name}")
        raise

def get_env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        print(f"ERROR: Missing required environment variable: {name}")
        sys.exit(1)
    return val

def parse_missing_paths_from_svn_status_xml(wc_root):
    """Return list of paths marked as 'missing' in svn status --xml."""
    cp = run(["svn", "status", "--xml"], cwd=wc_root, check=True, capture=True)
    missing = []
    root = ET.fromstring(cp.stdout)
    for entry in root.findall(".//entry"):
        wcstatus = entry.find("wc-status")
        if wcstatus is not None:
            item = wcstatus.get("item", "")
            if item == "missing":
                path = entry.get("path")
                if path:
                    missing.append(path)
    return missing

def get_pending_status(wc_root):
    """Return raw svn status text and a boolean indicating if changes exist."""
    cp = run(["svn", "status"], cwd=wc_root, check=True, capture=True)
    text = cp.stdout.strip()
    return text, bool(text)

def main():
    # Read configuration from environment (recommended for Actions)
    source_path   = get_env("SOURCE_PATH", required=True)
    svn_url       = get_env("SVN_URL", required=True)
    svn_username  = get_env("SVN_USERNAME")
    svn_password  = get_env("SVN_PASSWORD")
    commit_msg    = get_env("COMMIT_MESSAGE") or \
        f"Automated sync from {os.environ.get('COMPUTERNAME', 'unknown')} at {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"

    # Basic validations
    if not os.path.exists(source_path):
        print(f"ERROR: Source path not found: {source_path}")
        sys.exit(1)

    # Tools availability
    ensure_tool("svn")
    if os.name == "nt":
        # robocopy is built-in on Windows
        pass
    else:
        print("WARNING: Non-Windows OS detected; falling back to Python copy (slower).")

    # Prepare a working copy directory (unique per run)
    runner_temp = os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()
    wc_root = os.path.join(runner_temp, f"svn-wc-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(wc_root, exist_ok=True)
    print(f"Working copy root: {wc_root}")

    # SVN checkout
    checkout_cmd = ["svn", "checkout", svn_url, wc_root, "--non-interactive", "--trust-server-cert"]
    if svn_username and svn_password:
        checkout_cmd += ["--username", svn_username, "--password", svn_password, "--no-auth-cache"]
    run(checkout_cmd)

    # Ensure up to date (helps avoid later conflicts)
    update_cmd = ["svn", "update"]
    run(update_cmd, cwd=wc_root)

    # Copy files into working copy
    if os.name == "nt":
        # Mirror source into wc_root WITHOUT touching .svn
        # /MIR mirrors (adds/removes), /XD .svn excludes .svn folder.
        # robocopy returns non-zero for normal outcomes; don't check return code strictly.
        robocopy_cmd = [
            "robocopy", source_path, wc_root,
            "/MIR", "/XD", ".svn",
            "/MT:8", "/R:2", "/W:2", "/NFL", "/NDL", "/NP"
        ]
        run(robocopy_cmd, check=False)
    else:
        # Portable fallback: copy everything; deletions handled via SVN status missing if you also remove extras.
        # We'll do a naive mirror: remove anything in wc_root that is not in source (except .svn)
        for root_dir, dirs, files in os.walk(wc_root):
            rel = os.path.relpath(root_dir, wc_root)
            if rel == ".":
                # Exclude .svn in root
                dirs[:] = [d for d in dirs if d != ".svn"]
            src_dir = os.path.join(source_path, rel) if rel != "." else source_path
            # Delete files not present in source
            for f in files:
                src_file = os.path.join(src_dir, f)
                wc_file = os.path.join(root_dir, f)
                if not os.path.exists(src_file):
                    os.remove(wc_file)
            # Delete directories not present in source
            for d in list(dirs):
                src_sub = os.path.join(src_dir, d)
                wc_sub = os.path.join(root_dir, d)
                if not os.path.exists(src_sub):
                    shutil.rmtree(wc_sub, ignore_errors=True)
        # Copy from source to wc_root
        for root_dir, dirs, files in os.walk(source_path):
            rel = os.path.relpath(root_dir, source_path)
            dest_dir = os.path.join(wc_root, rel) if rel != "." else wc_root
            os.makedirs(dest_dir, exist_ok=True)
            for f in files:
                shutil.copy2(os.path.join(root_dir, f), os.path.join(dest_dir, f))

    # Schedule deletes for items missing after mirror
    missing_paths = parse_missing_paths_from_svn_status_xml(wc_root)
    for p in missing_paths:
        print(f"Scheduling delete: {p}")
        run(["svn", "rm", "--force", p], cwd=wc_root)

    # Add new/unversioned files (recursively)
    run(["svn", "add", "--force", ".", "--auto-props", "--parents", "--depth", "infinity", "--no-ignore"], cwd=wc_root)

    # Show status summary
    status_text, has_changes = get_pending_status(wc_root)
    print("\nSVN status after add/rm:\n" + (status_text if status_text else "(no changes)"))

    if not has_changes:
        print("No changes detected. Skipping commit.")
        return

    # Commit changes
    commit_cmd = ["svn", "commit", "-m", commit_msg, "--non-interactive", "--trust-server-cert"]
    if svn_username and svn_password:
        commit_cmd += ["--username", svn_username, "--password", svn_password, "--no-auth-cache"]
    run(commit_cmd, cwd=wc_root)

    print("\nCommit finished successfully.")

if __name__ == "__main__":
    main()
