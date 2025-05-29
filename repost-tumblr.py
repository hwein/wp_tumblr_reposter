# Komplett überarbeitetes Skript mit Legacy-kompatibler Tumblr-API und WP-API-Paginierung

import json
import os
import webbrowser
from flask import Flask, request
from urllib.parse import urlencode, urlparse
from threading import Thread
import secrets
import datetime
import re
import sys
import requests
import time

# === Konfiguration ===
CLIENT_ID = "XXXXXXXXXXXXXXXXXXXXXXXX"  # Von Tumblr bei App-Registrierung bereitgestellter Client Identifier
CLIENT_SECRET = "XXXXXXXXXXXXXXXXXXXXXXXXXX"  # Geheimschlüssel zur Authentifizierung, ebenfalls von Tumblr
WORDPRESS_BLOG_URL = "https://www.meinblog.de" # URL der Wordpressquelle
REDIRECT_URI = "http://localhost:8080/callback"  # Die URI, an die Tumblr nach erfolgreicher Authentifizierung weiterleitet. Muss mit der App-Registrierung übereinstimmen.
TUMBLR_BLOG_NAME = "TUMBLRBLOG-NAME"  # Der Tumblr-Blogname (nicht die URL), z. B. "leichtgesagt-blog"
TOKENS_FILE = "tumblr_tokens.json"  # Datei zur Speicherung der Access-Tokens für spätere Verwendung
POSTED_LOG = "posted_entries.json"  # Enthält IDs bereits geposteter Beiträge, um Duplikate zu vermeiden
LOG_FILE = "tumblr_post_log.txt"  # Datei für Logs über Vorgänge und Fehler
LOG_LEVEL = "verbose"  # verbose: detaillierte Logs inkl. Fehlertext und Tags | info: nur Anzahl der Tags
DEBUG_MODE = "on"  # Aktiviert zusätzliche Debug-Ausgaben und speichert HTML-Rohdaten sowie Tumblr-Post-Content in separaten Dateien
PAGE_SIZE = 25  # Anzahl von Beiträgen pro Seite bei der WordPress-Paginierung

access_token = ""  # Global gespeicherter OAuth-Zugriffstoken, wird nach erfolgreicher Authentifizierung gesetzt und für API-Requests genutzt

# === Logging ===
def log(action, status, error="", tags=None):
    """
    Schreibt einen Log-Eintrag mit Zeitstempel, Aktion und Status.
    Bei 'verbose' Loglevel zusätzlich mit Fehlerdetails und Tags.
    Bei 'info' nur Anzahl der Tags.
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
    Führt den vollständigen OAuth-2.0-Autorisierungsprozess durch:
    1. Generiert einen Autorisierungslink mit zufälligem 'state'-Token.
    2. Startet einen lokalen Flask-Webserver, der den Redirect mit Code abfängt.
    3. Tauscht den Code gegen ein Access Token aus.
    4. Speichert das Token in einer Datei zur späteren Wiederverwendung.

    Der Ablauf ist interaktiv und öffnet automatisch den Browser zur Freigabe der App-Rechte durch den Nutzer.
    """
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

# === Tokens laden ===
def load_access_token():
    global access_token
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, "r") as f:
            data = json.load(f)
            access_token = data.get("access_token", "")

# === Beitragserkennung ===
def load_posted_log():
    if os.path.exists(POSTED_LOG):
        with open(POSTED_LOG, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_posted_log(log_data):
    with open(POSTED_LOG, "w", encoding="utf-8") as f:
        json.dump(list(log_data), f, ensure_ascii=False, indent=2)

# === WP-API: Ältesten unbehandelten Beitrag finden ===
def get_oldest_unposted_wp_entry():
    """
    Iteriert seitenweise durch die paginierte WordPress-API, um Beiträge zu laden.
    Für jede Seite mit Beiträgen wird geprüft, ob einer davon bereits verarbeitet wurde.
    Gibt den ältesten Beitrag zurück, der noch nicht in der geposteten Liste enthalten ist.
    Falls alle bisherigen Beiträge bereits veröffentlicht wurden, wird None zurückgegeben.
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
    Diese Funktion nimmt eine Liste von Tag-IDs entgegen und verwendet die WordPress-API,
    um die dazugehörigen Tag-Namen aufzulösen. Die Namen werden als Liste zurückgegeben.
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

# === Tumblr Post mit Bild ===
def create_tumblr_post(entry):
    """
    Formatiert und erstellt einen neuen Textbeitrag für Tumblr über die Legacy-API:
    - Fügt dem Inhalt ein Beitragsbild hinzu, falls vorhanden
    - Konvertiert WordPress-Tags in ein Tumblr-konformes Tag-Format
    - Nutzt den Titel und Inhalt des WordPress-Artikels als Basis
    - Bindet die Original-URL als Quellenangabe ein
    Bei Erfolg wird der Beitrag gepostet und geloggt, andernfalls der Fehler festgehalten.
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
    load_access_token()
    if not access_token:
        run_oauth_flow()
        load_access_token()

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
