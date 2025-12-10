
from office365.sharepoint.client_context import ClientContext
from office365.runtime.auth.user_credential import UserCredential
import os

# ===== CONFIGURATION =====
SITE_URL = "https://lnttsgroup.sharepoint.com/sites/CICD-Automation"
LIBRARY_NAME = "Shared Documents"  # default library
EMAIL = "kare.rakesh@ltts.com"
PASSWORD = "!@qwASzx34ERdfCV"
DOWNLOAD_DIR = "./downloads"
# ==========================

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def download_folder(sp_folder, local_dir):
    """Recursively download all files and subfolders from sp_folder to local_dir."""
    ensure_dir(local_dir)

    # Files in the current folder
    files = sp_folder.files.get().execute_query()
    for f in files:
        file_path = os.path.join(local_dir, f.name)
        print(f"Downloading: {f.serverRelativeUrl} -> {file_path}")
        with open(file_path, "wb") as out:
            f.download(out).execute_query()

    # Subfolders
    subfolders = sp_folder.folders.get().execute_query()
    for sub in subfolders:
        # Ensure we have a usable name
        sub.ensure_properties(["Name"])
        sub_name = sub.properties.get("Name", getattr(sub, "name", "folder"))
        download_folder(sub, os.path.join(local_dir, sub_name))

def main():
    print("Connecting to SharePoint...")
    ctx = ClientContext(SITE_URL).with_credentials(UserCredential(EMAIL, PASSWORD))

    # Get the document list (library) object
    doc_lib = ctx.web.lists.get_by_title(LIBRARY_NAME)

    # Ensure the RootFolder is loaded: provide an action to load it if missing
    doc_lib.ensure_property(
        "RootFolder",
        lambda: doc_lib.root_folder.get().execute_query()
    )

    root_folder = doc_lib.root_folder
    root_folder.ensure_property(
        "ServerRelativeUrl",
        lambda: root_folder.get().execute_query()
    )

    print(f"Library root: {root_folder.serverRelativeUrl}")

    # Download everything
    download_folder(root_folder, DOWNLOAD_DIR)
    print("✅ Download complete.")

if __name__ == "__main__":
    main()
