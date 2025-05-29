"""
WordPress → Tumblr Auto-Reposter
-------------------------------

Dieses Script postet bei jedem Aufruf automatisch den ältesten, noch nicht auf Tumblr veröffentlichten WordPress-Beitrag auf einen gewünschten Tumblr-Blog.
Es unterstützt automatische Token-Erneuerung per Refresh-Token, löst WordPress-Tag-IDs in Tag-Namen auf und ist für jeden beliebigen WordPress-Blog einsetzbar.

Autor: heiko@leichtgesagt.blog
Stand: 2025-05
"""
import json
import os
import webbrowser
from flask import Flask, request
from urllib.parse import urlencode
from threading import Thread
import secrets
import datetime
import sys
import requests
import time

# === Konfiguration Source/Quelle ===
CLIENT_ID = "client id"                             # Von Tumblr bei App-Registrierung bereitgestellter Client Identifier
CLIENT_SECRET = "clientsecret"                      # Geheimschlüssel zur Authentifizierung, ebenfalls von Tumblr
WORDPRESS_BLOG_URL = "source wordpress blog url"    # URL der WordPress-Quelle (ohne Slash am Ende)
TUMBLR_BLOG_NAME = "target tumblr blog"             # Tumblr Blogname (z.B. "mein-super-blog")
PAGE_SIZE = 25                                      # API-Paginierung bei WordPress (max. 100)

# === Konfiguration Lokal ===
REDIRECT_URI = "http://localhost:8080/callback"    # Muss exakt mit der Weiterleitungs-URI der Tumblr-App übereinstimmen
TOKENS_FILE = "tumblr_tokens.json"                 # Lokale Datei für Token-Speicherung
POSTED_LOG = "posted_entries.json"                 # Enthält die IDs bereits geposteter Beiträge
LOG_FILE = "tumblr_post_log.txt"                   # Logfile für Vorgänge & Fehler
LOG_LEVEL = "info"                                 # "verbose" = detailliert, "info" = kurz
DEBUG_MODE = "off"                                 # "on" = zusätzliche Debug-Dateien anlegen

# === Globale Token-Variablen ===
access_token = ""
refresh_token = ""
expires_at = None

# === Logging-Funktion ===
def log(action, status, error="", tags=None):
    """
    Schreibt einen Log-Eintrag mit Zeitstempel, Aktion und Status.
    Bei 'verbose' zusätzlich Fehlerdetails und Tags.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] Aktion: {action} | Status: {status}"
    if LOG_LEVEL == "verbose":
        if tags:
            entry += f" | Tags: {tags}"
        if error:
            entry += f" | Fehler: {error}"
    elif LOG_LEVEL == "info":
        if tags:
            entry += f" | Tags: {len(tags)} Tags"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry + "\n")

# === OAuth 2.0 Flow ===
def run_oauth_flow():
    """
    Führt einmalig den OAuth2-Flow für Tumblr durch:
    - Öffnet einen lokalen Flask-Webserver, der den Tumblr-Redirect mit Code abfängt.
    - Tauscht den Code gegen ein Access-/Refresh-Token.
    - Speichert das Token + Ablaufzeit in TOKENS_FILE.
    """
    global access_token, refresh_token, expires_at
    app = Flask(__name__)
    state_token = secrets.token_urlsafe(16)
    auth_url = f"https://www.tumblr.com/oauth2/authorize?" + urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": state_token,
        "scope": "basic write offline_access"
    })
    token_container = {}

    @app.route("/callback")
    def callback():
        nonlocal token_container
        code = request.args.get("code")
        state = request.args.get("state")
        if state != state_token:
            return "Ungültiger State", 400

        token_response = requests.post("https://api.tumblr.com/v2/oauth2/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI
        })

        if token_response.status_code == 200:
            tokens = token_response.json()
            expires_in = tokens.get("expires_in", 3600)
            expires = (datetime.datetime.now() + datetime.timedelta(seconds=expires_in)).isoformat()
            tokens["expires_at"] = expires
            with open(TOKENS_FILE, "w") as f:
                json.dump(tokens, f, indent=2)
            print("Token erfolgreich gespeichert.")
            token_container["done"] = True
            return "Erfolgreich authentifiziert. Du kannst dieses Fenster schließen."
        return f"Fehler: {token_response.text}", 500

    def run_flask():
        app.run(port=8080)

    print("Bitte öffne diesen Link zur Autorisierung:")
    print(auth_url)
    Thread(target=run_flask, daemon=True).start()
    webbrowser.open(auth_url)

    timeout = 180
    start_time = time.time()
    while not token_container.get("done"):
        if time.time() - start_time > timeout:
            print("OAuth Autorisierung zeitüberschritten.")
            sys.exit(1)
        time.sleep(1)

# === Token-Handling ===
def load_access_token():
    """
    Läd Tokens aus Datei und prüft expires_at.
    """
    global access_token, refresh_token, expires_at
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, "r") as f:
            data = json.load(f)
            access_token = data.get("access_token", "")
            refresh_token = data.get("refresh_token", "")
            expires_at = data.get("expires_at")

def save_access_token(data):
    """
    Speichert Tokens samt Ablaufzeit (expires_at).
    """
    with open(TOKENS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def refresh_access_token():
    """
    Holt neues Access-Token über Refresh-Token, aktualisiert expires_at.
    """
    global access_token, refresh_token, expires_at
    if not refresh_token:
        return False
    response = requests.post("https://api.tumblr.com/v2/oauth2/token", data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    })
    if response.status_code == 200:
        tokens = response.json()
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", refresh_token)
        expires_in = tokens.get("expires_in", 3600)
        expires_at = (datetime.datetime.now() + datetime.timedelta(seconds=expires_in)).isoformat()
        tokens["expires_at"] = expires_at
        save_access_token(tokens)
        print("Access Token erfolgreich erneuert.")
        return True
    print("Fehler beim Erneuern des Access Tokens.")
    return False

def access_token_valid():
    """
    Prüft, ob Access-Token noch gültig ist.
    """
    if not access_token or not expires_at:
        return False
    return datetime.datetime.now() < datetime.datetime.fromisoformat(expires_at)

def ensure_valid_token():
    """
    Prüft Gültigkeit des Tokens, erneuert falls nötig, oder fordert neue Authentifizierung an.
    """
    load_access_token()
    if access_token_valid():
        return
    if refresh_token and refresh_access_token():
        return
    run_oauth_flow()
    load_access_token()

# === Beitragserkennung ===
def load_posted_log():
    """
    Gibt die Menge der bereits geposteten WP-Beitrags-IDs zurück.
    """
    if os.path.exists(POSTED_LOG):
        with open(POSTED_LOG, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_posted_log(log_data):
    """
    Speichert die Menge aller bereits geposteten Beitrags-IDs.
    """
    with open(POSTED_LOG, "w", encoding="utf-8") as f:
        json.dump(list(log_data), f, ensure_ascii=False, indent=2)

def get_oldest_unposted_wp_entry():
    """
    Sucht seitenweise den ältesten, noch nicht geposteten WordPress-Beitrag.
    """
    posted = load_posted_log()
    page = 1
    while True:
        url = f"{WORDPRESS_BLOG_URL}/wp-json/wp/v2/posts?per_page={PAGE_SIZE}&page={page}&orderby=date&order=asc"
        response = requests.get(url)
        if response.status_code != 200:
            log("WP API", "Fehlgeschlagen", response.text)
            sys.exit(1)
        entries = response.json()
        if not entries:
            break
        for entry in entries:
            if entry['id'] not in posted:
                return entry
        page += 1
    return None

# === WP-API: Tags auflösen ===
def resolve_tag_names(tag_ids):
    """
    Wandelt WordPress-Tag-IDs in Tag-Namen um (liefert Liste mit Namen).
    """
    if not tag_ids:
        return []
    ids_str = ",".join(map(str, tag_ids))
    url = f"{WORDPRESS_BLOG_URL}/wp-json/wp/v2/tags?include={ids_str}"
    response = requests.get(url)
    if response.status_code != 200:
        return []
    tags = response.json()
    return [tag['name'] for tag in tags]

# === Tumblr Post ===
def create_tumblr_post(entry):
    """
    Erstellt einen neuen Textpost auf Tumblr:
    - Fügt ein Beitragsbild ein (falls vorhanden)
    - Konvertiert WP-Tags in Namen und übergibt sie als Komma-getrennte Zeichenkette
    - Nutzt Titel und Inhalt aus dem WP-Artikel
    - Bindet die Original-URL als Quelle ein
    """
    content_html = entry['content']['rendered']
    title = entry['title']['rendered']
    image_url = entry.get('jetpack_featured_media_url', '')
    tag_ids = entry.get('tags', [])
    tags = resolve_tag_names(tag_ids)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    body_with_image = f'<img src="{image_url}" alt="Beitragsbild" /><br><br>{content_html}' if image_url else content_html

    payload = {
        "type": "text",
        "title": title,
        "body": body_with_image,
        "tags": ",".join(tags),
        "source_url": entry['link']
    }

    response = requests.post(
        f"https://api.tumblr.com/v2/blog/{TUMBLR_BLOG_NAME}/post",
        headers=headers,
        json=payload
    )

    if response.status_code == 201:
        log("Post erstellt", "Erfolgreich", tags=tags)
        return True, entry['id']
    else:
        log("Post erstellt", "Fehlgeschlagen", response.text, tags=tags)
        return False, None

# === Hauptfunktion ===
def main():
    """
    Prüft Tokens, sucht den ältesten offenen Beitrag und postet ihn auf Tumblr.
    """
    ensure_valid_token()
    entry = get_oldest_unposted_wp_entry()
    if not entry:
        print("Keine neuen Beiträge zum Posten.")
        log("Beitragsprüfung", "Keine neuen Beiträge")
        return

    print(f"Poste: {entry['title']['rendered']}")
    success, posted_id = create_tumblr_post(entry)
    if success:
        posted = load_posted_log()
        posted.add(posted_id)
        save_posted_log(posted)
        print("Beitrag erfolgreich gepostet.")
    else:
        print("Fehler beim Posten des Beitrags.")
        sys.exit(1)

if __name__ == "__main__":
    main()
