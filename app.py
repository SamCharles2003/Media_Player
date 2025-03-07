from flask import Flask, jsonify, request, render_template, Response, url_for, abort
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
import os
import requests
import threading
import time

app = Flask(__name__)

# ------------------------------------------------------------------------------
# Google Drive Authentication with Credential Caching
# ------------------------------------------------------------------------------
def get_drive():
    """Authenticate with Google Drive and return a GoogleDrive instance."""
    gauth = GoogleAuth()
    credential_file = "mycreds.txt"
    
    # Attempt to load previously saved credentials
    gauth.LoadCredentialsFile(credential_file)
    
    if gauth.credentials is None:
        # No valid credentials, run the authentication flow
        gauth.LocalWebserverAuth()
    elif gauth.access_token_expired:
        # Refresh expired credentials
        gauth.Refresh()
    else:
        # Use the valid credentials
        gauth.Authorize()
    
    # Save the credentials for the next run
    gauth.SaveCredentialsFile(credential_file)
    return GoogleDrive(gauth)

# ------------------------------------------------------------------------------
# Helper: Scan a Google Drive Folder for Media Files
# ------------------------------------------------------------------------------
def scan_drive_folder(folder_id):
    """
    List all items (folders, audio, video) in the specified Google Drive folder.
    
    Only returns items with:
      - Folder: mimeType 'application/vnd.google-apps.folder'
      - Audio: mimeType starting with 'audio/'
      - Video: mimeType starting with 'video/'
    """
    drive = get_drive()
    # Query to list files in the given folder (excluding trashed items)
    query = f"'{folder_id}' in parents and trashed=false"
    file_list = drive.ListFile({'q': query}).GetList()
    
    items = []
    for file in file_list:
        mime_type = file.get('mimeType')
        # Determine the type of the file
        if mime_type == 'application/vnd.google-apps.folder':
            item_type = 'folder'
        elif mime_type.startswith('audio/'):
            item_type = 'audio'
        elif mime_type.startswith('video/'):
            item_type = 'video'
        else:
            # Skip files that are not folders or supported media types
            continue
        
        # Build the item information
        file_info = {
            'id': file['id'],
            'title': file['title'],
            'mimeType': mime_type,
            'type': item_type,
            # You can include additional metadata if needed:
            'webViewLink': file.get('webViewLink'),
            'webContentLink': file.get('webContentLink')
        }
        items.append(file_info)
    return items

# ------------------------------------------------------------------------------
# Flask Routes
# ------------------------------------------------------------------------------

@app.route('/')
def index():
    """Serve the main page."""
    return render_template('index.html')

@app.route('/api/folders/<folder_id>')
def list_folder_contents(folder_id):
    """API endpoint to list contents of a folder."""
    try:
        items = scan_drive_folder(folder_id)
        return jsonify({'success': True, 'items': items})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stream/<file_id>')
def stream_media(file_id):
    """Stream media content directly from Google Drive."""
    try:
        drive = get_drive()
        file = drive.CreateFile({'id': file_id})
        
        # Get file metadata
        file.FetchMetadata()
        mime_type = file.get('mimeType')
        file_size = int(file.get('fileSize', 0))
        
        # Get download URL
        download_url = file.get('downloadUrl')
        if not download_url:
            download_url = file['alternateLink']
        
        # Get the range header if present
        range_header = request.headers.get('Range')
        headers = {'Authorization': 'Bearer ' + drive.auth.credentials.access_token}
        
        if range_header:
            headers['Range'] = range_header
        
        # Stream the content directly from Google Drive
        drive_response = requests.get(
            download_url, 
            headers=headers, 
            stream=True
        )
        
        # Get content range from response
        content_range = drive_response.headers.get('Content-Range')
        content_length = drive_response.headers.get('Content-Length')
        
        response_headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'no-cache'
        }
        
        if content_range:
            response_headers['Content-Range'] = content_range
        if content_length:
            response_headers['Content-Length'] = content_length
        
        def generate():
            for chunk in drive_response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        
        return Response(
            generate(),
            status=drive_response.status_code,
            headers=response_headers,
            direct_passthrough=True
        )
        
    except Exception as e:
        app.logger.error(f"Streaming error for file {file_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500






def keep_alive():
    """
    Background thread function that sends requests every 14 minutes
    to prevent Render from spinning down the service.
    """
    with app.app_context():
        while True:
            try:
                print("Sending keep-alive request...")
                # Get the deployment URL from environment variable
                deployment_url ="https://media-player-zgvy.onrender.com" #os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:5000')
                # Make the request to the keep-alive endpoint
                response = requests.get(f"{deployment_url}/keepActive")
                print(f"Keep-alive response status: {response.status_code}")
                # Sleep for 14 minutes (840 seconds)
                # This is just under Render's 15-minute timeout
                time.sleep(10)
            except Exception as e:
                print(f"Keep-alive request failed: {e}")
                # If request fails, wait 1 minute before retrying
                time.sleep(60)

@app.route('/keepActive')
def keep_active():
    """Endpoint that confirms the server is active."""
    print("Keep-alive endpoint hit")
    return 200


def activate():
    while True:
        print("Im Active")



if __name__ == '__main__':


    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    
    # Get port from environment variable (Render sets this automatically)
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0',debug=True)
