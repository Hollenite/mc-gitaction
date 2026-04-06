#!/usr/bin/env python3
"""Google Drive helper — two-file swap for safe world backups.

Files on Drive:
  world.tar.gz        = latest save (loaded first)
  world_backup.tar.gz = previous save (fallback if latest is corrupt)

Save flow:
  1. Verify new tar locally (gzip integrity check)
  2. Upload new tar → UPDATE world_backup.tar.gz (staging)
  3. Swap names: world.tar.gz ↔ world_backup.tar.gz
  Result: new data is now "world.tar.gz", old data is now "world_backup.tar.gz"

Load flow:
  1. Download world.tar.gz → verify → use if valid
  2. If corrupt → download world_backup.tar.gz → verify → use as fallback
"""

import json
import os
import sys
import subprocess

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
except ImportError:
    os.system("pip install -q google-api-python-client google-auth")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive']
PRIMARY   = "world.tar.gz"
BACKUP    = "world_backup.tar.gz"


def get_service():
    sa_json = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=SCOPES)
    else:
        sa_file = os.environ.get("GDRIVE_SA_FILE", "/tmp/sa-key.json")
        creds = service_account.Credentials.from_service_account_file(
            sa_file, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


def find_file(service, folder_id, name):
    """Find a file by name in folder. Returns {id, name, size} or None."""
    r = service.files().list(
        q=f"'{folder_id}' in parents and name='{name}' and trashed=false",
        fields="files(id, name, size, modifiedTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = r.get('files', [])
    return files[0] if files else None


def download_file(service, file_id, dest):
    """Download a file by ID."""
    import io
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(dest, 'wb') as f:
        dl = MediaIoBaseDownload(f, request, chunksize=50*1024*1024)
        done = False
        while not done:
            status, done = dl.next_chunk()
            if status:
                print(f"  Download: {int(status.progress() * 100)}%")
    print(f"  Downloaded to {dest}")


def upload_file(service, file_id, src):
    """Update an existing file's content (preserves ownership)."""
    media = MediaFileUpload(src, mimetype='application/gzip',
                            resumable=True, chunksize=50*1024*1024)
    request = service.files().update(
        fileId=file_id, media_body=media, supportsAllDrives=True)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload: {int(status.progress() * 100)}%")
    print(f"  Upload complete (ID: {response.get('id', '?')})")
    return True


def rename_file(service, file_id, new_name):
    """Rename a file (metadata update only)."""
    service.files().update(
        fileId=file_id,
        body={"name": new_name},
        supportsAllDrives=True
    ).execute()
    print(f"  Renamed {file_id} → {new_name}")


def verify_tar(path):
    """Verify tar.gz integrity. Returns True if valid."""
    result = subprocess.run(["gzip", "-t", path],
                            capture_output=True, timeout=120)
    return result.returncode == 0


# ─── Commands ─────────────────────────────────────────────

def cmd_download(folder_id, dest):
    """Download world with fallback to backup if primary is corrupt."""
    service = get_service()

    # Try primary first
    primary = find_file(service, folder_id, PRIMARY)
    if primary and int(primary.get('size', 0)) > 1000:
        print(f"[GDRIVE] Found {PRIMARY} ({int(primary['size'])/(1024*1024):.0f} MB)")
        download_file(service, primary['id'], dest)

        print("[GDRIVE] Verifying integrity...")
        if verify_tar(dest):
            print("[GDRIVE] ✅ Primary world is valid!")
            return True
        else:
            print("[GDRIVE] ❌ Primary world is CORRUPT!")
            os.remove(dest)

    # Fallback to backup
    print("[GDRIVE] Trying backup...")
    backup = find_file(service, folder_id, BACKUP)
    if backup and int(backup.get('size', 0)) > 1000:
        print(f"[GDRIVE] Found {BACKUP} ({int(backup['size'])/(1024*1024):.0f} MB)")
        download_file(service, backup['id'], dest)

        print("[GDRIVE] Verifying backup integrity...")
        if verify_tar(dest):
            print("[GDRIVE] ✅ Backup world is valid! (using previous save)")
            return True
        else:
            print("[GDRIVE] ❌ Backup is also corrupt! Starting fresh.")
            os.remove(dest)
            return False

    print("[GDRIVE] No valid world found on Drive.")
    return False


def cmd_upload(folder_id, src):
    """Safe upload: verify → upload to backup slot → swap names."""
    service = get_service()

    # Step 1: Verify the tar before uploading
    print("[GDRIVE] Verifying archive before upload...")
    if not verify_tar(src):
        print("[GDRIVE] ❌ Local tar is corrupt! NOT uploading to protect backup.")
        return False

    size_mb = os.path.getsize(src) / (1024*1024)
    print(f"[GDRIVE] ✅ Archive OK ({size_mb:.0f} MB)")

    # Step 2: Find both files
    primary = find_file(service, folder_id, PRIMARY)
    backup  = find_file(service, folder_id, BACKUP)

    if not primary or not backup:
        # Fallback: if only one file exists, just update it directly
        target = primary or backup
        if target:
            print(f"[GDRIVE] Only one file found ({target['name']}). Updating directly.")
            upload_file(service, target['id'], src)
            return True
        print("[GDRIVE] No files found on Drive!")
        return False

    # Step 3: Upload new tar → backup slot (staging)
    print(f"[GDRIVE] Uploading to staging ({BACKUP})...")
    upload_file(service, backup['id'], src)

    # Step 4: Swap names (backup becomes primary, old primary becomes backup)
    print("[GDRIVE] Swapping files...")
    # Use temp name to avoid collision
    rename_file(service, primary['id'], "world_swapping.tar.gz")
    rename_file(service, backup['id'],  PRIMARY)
    rename_file(service, primary['id'], BACKUP)

    print("[GDRIVE] ✅ Save complete! Files swapped successfully.")
    print(f"  {PRIMARY} = latest save")
    print(f"  {BACKUP}  = previous save")
    return True


def cmd_check(folder_id):
    """Check if world files exist on Drive."""
    service = get_service()
    for name in [PRIMARY, BACKUP]:
        f = find_file(service, folder_id, name)
        if f:
            size = int(f.get('size', 0)) / (1024*1024)
            modified = f.get('modifiedTime', '?')
            print(f"  ✅ {name}: {size:.0f} MB (modified: {modified})")
        else:
            print(f"  ❌ {name}: not found")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "")

    if not folder_id:
        print("ERROR: GDRIVE_FOLDER_ID not set")
        sys.exit(1)

    if action == "download":
        dest = sys.argv[2] if len(sys.argv) > 2 else "/tmp/world.tar.gz"
        success = cmd_download(folder_id, dest)
        sys.exit(0 if success else 1)

    elif action == "upload":
        src = sys.argv[2] if len(sys.argv) > 2 else "/tmp/world.tar.gz"
        if not os.path.exists(src):
            print(f"ERROR: {src} not found")
            sys.exit(1)
        success = cmd_upload(folder_id, src)
        sys.exit(0 if success else 1)

    elif action == "check":
        cmd_check(folder_id)
