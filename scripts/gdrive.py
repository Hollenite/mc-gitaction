#!/usr/bin/env python3
"""Upload/update world.tar.gz on Google Drive using service account.
Updates the EXISTING file (owned by user) so no quota issues."""

import json
import os
import sys

# Install deps if needed
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    os.system("pip install google-api-python-client google-auth -q")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_service():
    """Create Drive API service from env vars."""
    sa_json = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json:
        # Try file
        sa_file = os.environ.get("GDRIVE_SA_FILE", "/tmp/sa-key.json")
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
    else:
        sa_info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def find_file(service, folder_id, filename):
    """Find a file by name in a folder."""
    results = service.files().list(
        q=f"'{folder_id}' in parents and name='{filename}' and trashed=false",
        fields="files(id, name, size)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get('files', [])
    return files[0] if files else None

def download_file(service, file_id, dest_path):
    """Download a file from Drive."""
    from googleapiclient.http import MediaIoBaseDownload
    import io
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(dest_path, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request, chunksize=50*1024*1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"  Download: {int(status.progress() * 100)}%")
    print(f"  Downloaded to {dest_path}")

def upload_file(service, folder_id, file_path, filename="world.tar.gz"):
    """Upload or update a file on Drive. Updates existing to keep owner's quota."""
    existing = find_file(service, folder_id, filename)
    media = MediaFileUpload(file_path, mimetype='application/gzip', resumable=True, chunksize=50*1024*1024)

    if existing:
        # UPDATE existing file - keeps original owner, no quota issue
        print(f"  Updating existing file (ID: {existing['id']})...")
        request = service.files().update(
            fileId=existing['id'],
            media_body=media,
            supportsAllDrives=True
        )
    else:
        # Create new - will be owned by service account
        print("  Creating new file (warning: owned by service account)...")
        file_metadata = {'name': filename, 'parents': [folder_id]}
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload: {int(status.progress() * 100)}%")

    file_id = response.get('id', existing['id'] if existing else 'unknown')
    print(f"  Done! File ID: {file_id}")
    return file_id

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "")

    if not folder_id:
        print("ERROR: GDRIVE_FOLDER_ID not set")
        sys.exit(1)

    service = get_service()

    if action == "download":
        dest = sys.argv[2] if len(sys.argv) > 2 else "/tmp/world.tar.gz"
        f = find_file(service, folder_id, "world.tar.gz")
        if f:
            print(f"Found world.tar.gz ({int(f.get('size', 0))/(1024*1024):.0f} MB)")
            download_file(service, f['id'], dest)
        else:
            print("No world.tar.gz found on Drive")
            sys.exit(1)

    elif action == "upload":
        src = sys.argv[2] if len(sys.argv) > 2 else "/tmp/world.tar.gz"
        if not os.path.exists(src):
            print(f"ERROR: {src} not found")
            sys.exit(1)
        size_mb = os.path.getsize(src) / (1024*1024)
        print(f"Uploading {src} ({size_mb:.0f} MB)...")
        upload_file(service, folder_id, src)

    elif action == "check":
        f = find_file(service, folder_id, "world.tar.gz")
        if f:
            print(f"✅ world.tar.gz exists ({int(f.get('size', 0))/(1024*1024):.0f} MB)")
        else:
            print("❌ world.tar.gz not found")
