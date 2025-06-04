# Tumblr Poster für WordPress-Blog-Beiträge

Dieses Python-Skript automatisiert die Veröffentlichung von Blogbeiträgen von einem WordPress-Blog auf Tumblr. Es wird jeweils der älteste noch nicht veröffentlichte Beitrag identifiziert, aufbereitet und gepostet – inklusive Bild, Tags und Backlink.

---

## 🔧 Funktionsweise

### 1. Autorisierung via OAuth 2.0
Beim ersten Start leitet das Skript zur Tumblr-OAuth-Freigabe weiter. Nach erfolgreicher Autorisierung wird ein Zugriffstoken gespeichert (`tumblr_tokens.json`).

### 2. Beitragsermittlung via WordPress REST-API
Das Skript nutzt die WP-API:
- `wp-json/wp/v2/posts?order=asc&orderby=date` – um Beiträge seitenweise (25 Stück) zu laden
- `wp-json/wp/v2/tags?include=...` – um zugehörige Schlagwörter aufzulösen

### 3. Veröffentlichung auf Tumblr
Über den Legacy-Endpunkt der Tumblr-API (`/v2/blog/{blogname}/post`) wird der Beitrag als Text-Post veröffentlicht. Dabei:
- wird der Titel übernommen
- der HTML-Content inklusive Beitragsbild eingebettet
- alle Tags übernommen
- die Quelle (`source_url`) gesetzt

### 4. Persistenz
Bereits gepostete WordPress-Post-IDs werden in `posted_entries.json` gespeichert, um doppelte Veröffentlichungen zu vermeiden.

---

## 📁 Verwendete Dateien

| Datei                   | Zweck                                           |
|------------------------|--------------------------------------------------|
| `repost-tumblr.py`     | Hauptskript                                     |
| `tumblr_tokens.json`   | Speichert das OAuth-Token                        |
| `posted_entries.json`  | Liste bereits geposteter WordPress-Beiträge     |
| `tumblr_post_log.txt`  | Detail-Logging aller Aktionen                   |

---

## 🖥️ Nutzung

### Vorbereitung
1. `Python 3.10+` installieren
2. Bibliotheken installieren:
   ```bash
   pip install flask requests
   ```
3. `CLIENT_ID`, `CLIENT_SECRET`, `WORDPRESS_BLOG_URL` und `TUMBLR_BLOG_NAME` im Skript `repost-tumblr.py` eintragen

### Start
```bash
python repost-tumblr.py
```

---

## ⚙️ Einstellungen

- `PAGE_SIZE`: Anzahl der Beiträge pro WP-API-Page
- `LOG_LEVEL`: `verbose` oder `info`
- `DEBUG_MODE`: Für zukünftige Erweiterung vorgesehen

---

## 📌 Hinweis

Das Skript nutzt **nur öffentliche WordPress-APIs** – es sind keine WP-Zugangsdaten notwendig. Es erwartet, dass dein WordPress-Blog den Standard-REST-Endpunkt bereitstellt (typisch bei Jetpack, WP.com oder selbst gehosteten Blogs mit REST).

