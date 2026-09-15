from flask import Flask, request, redirect, url_for, session, jsonify, send_file, Response
from datetime import datetime
from zoneinfo import ZoneInfo
from werkzeug.utils import secure_filename
from html import escape
from io import BytesIO
import os
import uuid
import json
import base64

import psycopg2
import psycopg2.extras
from PIL import Image
from pywebpush import webpush, WebPushException
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "docasne-tajne-heslo")


# ============================================================
# NASTAVENÍ
# ============================================================

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

VAPID_PRIVATE_KEY_FILE = os.path.join(os.path.dirname(__file__), "private_key.pem")
VAPID_PUBLIC_KEY = os.path.join(os.path.dirname(__file__), "public_key.pem")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")


UZIVATELE = {
    "jiri": {
        "jmeno": "Jiří Prokeš",
        "heslo": "1234",
        "role": "admin"
    },
    "david": {
        "jmeno": "David Galia",
        "heslo": "1234",
        "role": "udrzbar"
    },
    "jaroslav": {
        "jmeno": "Jaroslav Fuksa",
        "heslo": "1234",
        "role": "udrzbar"
    },
    "jan": {
        "jmeno": "Jan Pázner",
        "heslo": "1234",
        "role": "udrzbar"
    }
}


STROJE = [
    "Linka",
    "Odformovací linka",
    "Robot",
    "Betonárka",
    "Vibrační stoly"
]


STAVY = {
    "nova": ("🔴", "Nová"),
    "resi_se": ("🟠", "Řeší se"),
    "hotovo": ("🟢", "Hotovo")
}


# ============================================================
# DATABÁZE
# ============================================================

def db_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "Chybí DATABASE_URL. Na Renderu ji nastav v Environment Variables."
        )

    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor
    )


def init_db():
    if not DATABASE_URL:
        print("DATABASE_URL není nastavená - databáze se neinicializovala.")
        return

    conn = db_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS repairs (
                        id BIGSERIAL PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        machine TEXT NOT NULL,
                        problem TEXT NOT NULL,
                        initial_work TEXT,
                        status TEXT NOT NULL DEFAULT 'nova',
                        reported_by_login TEXT NOT NULL,
                        reported_by_name TEXT NOT NULL,
                        assigned_to_login TEXT,
                        assigned_to_name TEXT,
                        assigned_at TIMESTAMPTZ,
                        completed_at TIMESTAMPTZ,
                        final_work TEXT
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS repair_photos (
                        id BIGSERIAL PRIMARY KEY,
                        repair_id BIGINT NOT NULL REFERENCES repairs(id) ON DELETE CASCADE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        phase TEXT NOT NULL DEFAULT 'zavada',
                        filename TEXT,
                        mime_type TEXT NOT NULL DEFAULT 'image/jpeg',
                        data BYTEA NOT NULL
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS repair_events (
                        id BIGSERIAL PRIMARY KEY,
                        repair_id BIGINT NOT NULL REFERENCES repairs(id) ON DELETE CASCADE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        user_login TEXT NOT NULL,
                        user_name TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        note TEXT
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS push_subscriptions (
                        id BIGSERIAL PRIMARY KEY,
                        user_login TEXT NOT NULL,
                        endpoint TEXT NOT NULL UNIQUE,
                        subscription_json JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS repair_views (
                        id BIGSERIAL PRIMARY KEY,
                        repair_id BIGINT NOT NULL REFERENCES repairs(id) ON DELETE CASCADE,
                        user_login TEXT NOT NULL,
                        user_name TEXT NOT NULL,
                        first_viewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (repair_id, user_login)
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_repair_views_repair
                    ON repair_views(repair_id)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_repairs_status
                    ON repairs(status)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_repairs_machine
                    ON repairs(machine)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_repairs_assigned
                    ON repairs(assigned_to_login)
                """)

    finally:
        conn.close()


def fetch_all(query, params=()):
    conn = db_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchall()
    finally:
        conn.close()


def fetch_one(query, params=()):
    conn = db_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()
    finally:
        conn.close()


def execute_returning(query, params=()):
    conn = db_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return row
    finally:
        conn.close()


def execute(query, params=()):
    conn = db_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
    finally:
        conn.close()


# ============================================================
# POMOCNÉ FUNKCE
# ============================================================

def prihlaseny():
    return session.get("uzivatel") in UZIVATELE


def aktualni_uzivatel():
    login = session.get("uzivatel")

    if login not in UZIVATELE:
        return None

    data = dict(UZIVATELE[login])
    data["login"] = login
    return data


def je_admin():
    u = aktualni_uzivatel()
    return bool(u and u["role"] == "admin")


def format_datum(value):
    if not value:
        return "—"

    # Všechny časy zobrazujeme v českém časovém pásmu.
    # Europe/Prague automaticky řeší letní i zimní čas.
    cesky_cas = value.astimezone(ZoneInfo("Europe/Prague"))
    return cesky_cas.strftime("%d.%m.%Y %H:%M")


def stav_html(status):
    ikona, text = STAVY.get(status, ("⚪", status))
    return f"{ikona} {escape(text)}"


def url_bezpecne(cil):
    if not cil or not cil.startswith("/"):
        return "/hlavni"

    return cil


def chybova_stranka(nadpis, zprava, zpet_url="/hlavni", zpet_text="← Zpět"):
    return f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{escape(nadpis)}</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f2f2f2;
                margin: 0;
                padding: 18px;
            }}
            .box {{
                max-width: 620px;
                margin: 50px auto;
                background: white;
                padding: 28px;
                border-radius: 15px;
                box-shadow: 0 3px 15px rgba(0,0,0,0.15);
                text-align: center;
            }}
            .message {{
                font-size: 18px;
                line-height: 1.5;
                margin: 20px 0 28px;
            }}
            .btn {{
                display: block;
                text-decoration: none;
                padding: 15px;
                margin-top: 10px;
                border-radius: 8px;
                background: #333;
                color: white;
                font-size: 17px;
            }}
            .btn.secondary {{
                background: #e5e5e5;
                color: #222;
            }}
        </style>
    </head>
    <body>
        <div class="box">
            <h1>{escape(nadpis)}</h1>
            <div class="message">{escape(zprava)}</div>
            <a class="btn" href="{escape(zpet_url)}">{escape(zpet_text)}</a>
            <a class="btn secondary" href="/hlavni">🏠 Hlavní stránka</a>
        </div>
    </body>
    </html>
    """


@app.route("/oprava/<int:repair_id>/smazat", methods=["POST"])
def smazat_opravu(repair_id):
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    if not je_admin():
        return chybova_stranka(
            "⛔ Přístup zamítnut",
            "Opravu může smazat pouze administrátor.",
            f"/oprava/{repair_id}",
            "← Zpět na opravu"
        ), 403

    oprava = fetch_one(
        """
        SELECT id, machine, problem
        FROM repairs
        WHERE id = %s
        """,
        (repair_id,)
    )

    if not oprava:
        return chybova_stranka(
            "⚠️ Oprava nenalezena",
            "Tato oprava už neexistuje nebo byla mezitím odstraněna.",
            "/opravy",
            "← Zpět na opravy"
        ), 404

    execute(
        "DELETE FROM repairs WHERE id = %s",
        (repair_id,)
    )

    return chybova_stranka(
        "✅ Oprava smazána",
        f"Oprava #{repair_id} – {oprava['machine']} byla trvale odstraněna včetně fotografií a historie.",
        "/opravy",
        "← Zpět na opravy"
    )


# ============================================================
# FOTOGRAFIE
# ============================================================

def zpracuj_fotografii(file_storage):
    """
    Fotku zmenší na max. 1600 px a uloží jako JPEG.
    Tím výrazně šetříme místo v DB.
    """
    raw = file_storage.read()

    if not raw:
        return None

    try:
        image = Image.open(BytesIO(raw))
        image = image.convert("RGB")
        image.thumbnail((1600, 1600))

        output = BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=82,
            optimize=True
        )

        return {
            "filename": secure_filename(file_storage.filename or "foto.jpg"),
            "mime_type": "image/jpeg",
            "data": output.getvalue()
        }

    except Exception as exc:
        print("Fotografii se nepodařilo zpracovat:", exc)
        return None


def uloz_fotky(repair_id, files, phase="zavada"):
    conn = db_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                for soubor in files:
                    if not soubor or not soubor.filename:
                        continue

                    photo = zpracuj_fotografii(soubor)

                    if not photo:
                        continue

                    cur.execute(
                        """
                        INSERT INTO repair_photos
                            (repair_id, phase, filename, mime_type, data)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            repair_id,
                            phase,
                            photo["filename"],
                            photo["mime_type"],
                            psycopg2.Binary(photo["data"])
                        )
                    )
    finally:
        conn.close()


def pridej_event(repair_id, event_type, note=""):
    u = aktualni_uzivatel()

    if not u:
        return

    execute(
        """
        INSERT INTO repair_events
            (repair_id, user_login, user_name, event_type, note)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            repair_id,
            u["login"],
            u["jmeno"],
            event_type,
            note
        )
    )


# ============================================================
# PUSH NOTIFIKACE
# ============================================================

def ziskej_vapid_private_key():
    env_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()

    if env_key:
        env_key = env_key.replace("\\n", "\n")
        temp_key_path = "/tmp/vapid_private_key.pem"

        with open(temp_key_path, "w", encoding="utf-8") as soubor:
            soubor.write(env_key)

        return temp_key_path

    if os.path.exists(VAPID_PRIVATE_KEY_FILE):
        return VAPID_PRIVATE_KEY_FILE

    return None


def verejny_vapid_klic_base64url():
    if not os.path.exists(VAPID_PUBLIC_KEY):
        raise FileNotFoundError("Chybí public_key.pem")

    with open(VAPID_PUBLIC_KEY, "rb") as soubor:
        public_key = serialization.load_pem_public_key(soubor.read())

    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ValueError("Veřejný VAPID klíč není EC klíč.")

    raw_key = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )

    return base64.urlsafe_b64encode(raw_key).rstrip(b"=").decode("ascii")


def push_subscriptions():
    return fetch_all(
        """
        SELECT user_login, endpoint, subscription_json
        FROM push_subscriptions
        """
    )


def uloz_push_subscription(user_login, subscription):
    endpoint = subscription.get("endpoint")

    execute(
        """
        INSERT INTO push_subscriptions
            (user_login, endpoint, subscription_json, updated_at)
        VALUES (%s, %s, %s::jsonb, NOW())
        ON CONFLICT (endpoint)
        DO UPDATE SET
            user_login = EXCLUDED.user_login,
            subscription_json = EXCLUDED.subscription_json,
            updated_at = NOW()
        """,
        (
            user_login,
            endpoint,
            json.dumps(subscription)
        )
    )


def odesli_push(
    title,
    body,
    url="/hlavni",
    exclude_login=None,
    only_login=None
):
    vapid_private_key = ziskej_vapid_private_key()

    if not vapid_private_key:
        print("Push přeskočen: chybí privátní VAPID klíč.")
        return

    try:
        subscriptions = push_subscriptions()
    except Exception as exc:
        print("Push subscriptions nelze načíst:", exc)
        return

    payload = {
        "title": title,
        "body": body[:180],
        "url": url_bezpecne(url)
    }

    for zaznam in subscriptions:
        login = zaznam["user_login"]

        if exclude_login and login == exclude_login:
            continue

        if only_login and login != only_login:
            continue

        subscription = zaznam["subscription_json"]

        if isinstance(subscription, str):
            subscription = json.loads(subscription)

        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": VAPID_SUBJECT}
            )

        except WebPushException as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None
            )

            print("Chyba push:", login, status, exc)

            if status in (404, 410):
                execute(
                    "DELETE FROM push_subscriptions WHERE endpoint = %s",
                    (zaznam["endpoint"],)
                )


# ============================================================
# PŘIHLÁŠENÍ
# ============================================================

@app.route("/", methods=["GET", "POST"])
def prihlaseni():
    if prihlaseny():
        return redirect(url_for("hlavni_stranka"))

    chyba = ""

    if request.method == "POST":
        login = request.form.get("uzivatel", "").strip()
        heslo = request.form.get("heslo", "")

        if login in UZIVATELE and UZIVATELE[login]["heslo"] == heslo:
            session["uzivatel"] = login
            return redirect(url_for("hlavni_stranka"))

        chyba = "Nesprávné uživatelské jméno nebo heslo."

    return f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">
        <title>Dokumentace oprav</title>

        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f2f2f2;
                margin: 0;
                padding: 20px;
            }}

            .box {{
                max-width: 420px;
                margin: 60px auto;
                background: white;
                padding: 30px;
                border-radius: 15px;
                box-shadow: 0 3px 15px rgba(0,0,0,0.15);
            }}

            h1 {{
                text-align: center;
                margin-bottom: 30px;
            }}

            input {{
                width: 100%;
                padding: 13px;
                margin: 8px 0 15px 0;
                box-sizing: border-box;
                font-size: 16px;
                border: 1px solid #bbb;
                border-radius: 8px;
            }}

            button {{
                width: 100%;
                padding: 14px;
                background: #333;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 17px;
                cursor: pointer;
            }}

            .chyba {{
                color: #b00020;
                text-align: center;
                margin-bottom: 15px;
            }}
        </style>
    </head>

    <body>
        <div class="box">
            <h1>Dokumentace oprav</h1>
            <div class="chyba">{escape(chyba)}</div>

            <form method="POST">
                <label>Uživatel</label>
                <input
                    type="text"
                    name="uzivatel"
                    placeholder="Uživatelské jméno"
                    required
                >

                <label>Heslo</label>
                <input
                    type="password"
                    name="heslo"
                    placeholder="Heslo"
                    required
                >

                <button type="submit">
                    PŘIHLÁSIT
                </button>
            </form>
        </div>
    </body>
    </html>
    """


# ============================================================
# HLAVNÍ STRÁNKA
# ============================================================

@app.route("/hlavni")
def hlavni_stranka():
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    u = aktualni_uzivatel()

    try:
        counts = fetch_one("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'nova') AS nova,
                COUNT(*) FILTER (WHERE status = 'resi_se') AS resi_se,
                COUNT(*) FILTER (WHERE status = 'hotovo') AS hotovo
            FROM repairs
        """)

        nova = counts["nova"] or 0
        resi = counts["resi_se"] or 0
        hotovo = counts["hotovo"] or 0

    except Exception as exc:
        nova = resi = hotovo = 0
        print("Chyba při načítání počtů:", exc)

    if u["role"] == "admin":
        obsah = f"""
            <h2>Přehled oprav</h2>

            <div class="stat-grid">
                <a class="stat-link" href="/opravy?stav=nova" aria-label="Zobrazit nové opravy">
                    <div class="stat"><strong>🔴 {nova}</strong><span>Nové</span><small>Zobrazit opravy</small></div>
                </a>
                <a class="stat-link" href="/opravy?stav=resi_se" aria-label="Zobrazit opravy, které se řeší">
                    <div class="stat"><strong>🟠 {resi}</strong><span>Řeší se</span><small>Zobrazit opravy</small></div>
                </a>
                <a class="stat-link" href="/opravy?stav=hotovo" aria-label="Zobrazit hotové opravy">
                    <div class="stat"><strong>🟢 {hotovo}</strong><span>Hotovo</span><small>Zobrazit opravy</small></div>
                </a>
            </div>

            <a href="/opravy"><button>📋 VŠECHNY OPRAVY</button></a>
            <a href="/stroje"><button>🏭 STROJE A HISTORIE</button></a>
        """
    else:
        obsah = f"""
            <h2>Údržba</h2>

            <div class="stat-grid">
                <a class="stat-link" href="/opravy?stav=nova" aria-label="Zobrazit nové opravy">
                    <div class="stat"><strong>🔴 {nova}</strong><span>Nové</span><small>Zobrazit opravy</small></div>
                </a>
                <a class="stat-link" href="/opravy?stav=resi_se" aria-label="Zobrazit opravy, které se řeší">
                    <div class="stat"><strong>🟠 {resi}</strong><span>Řeší se</span><small>Zobrazit opravy</small></div>
                </a>
                <a class="stat-link" href="/opravy?stav=hotovo" aria-label="Zobrazit hotové opravy">
                    <div class="stat"><strong>🟢 {hotovo}</strong><span>Hotovo</span><small>Zobrazit opravy</small></div>
                </a>
            </div>

            <a href="/nahlasit-opravu">
                <button>🔧 NAHLÁSIT OPRAVU</button>
            </a>

            <a href="/opravy">
                <button>📋 AKTUÁLNÍ OPRAVY</button>
            </a>

            <a href="/moje-opravy">
                <button>👨‍🔧 MOJE OPRAVY</button>
            </a>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">
        <title>Dokumentace oprav</title>

        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f2f2f2;
                margin: 0;
                padding: 18px;
            }}

            .box {{
                max-width: 760px;
                margin: 20px auto;
                background: white;
                padding: 26px;
                border-radius: 15px;
                box-shadow: 0 3px 15px rgba(0,0,0,0.15);
            }}

            h1 {{ margin-bottom: 5px; }}
            h2 {{ margin-top: 28px; }}

            a {{ text-decoration: none; }}

            button {{
                width: 100%;
                padding: 16px;
                margin: 7px 0;
                font-size: 17px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
            }}

            .logout {{ background: #ddd; }}

            .stat-grid {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 10px;
                margin: 18px 0;
            }}

            .stat-link {{
                display: block;
                color: inherit;
                border-radius: 10px;
            }}

            .stat {{
                background: #f6f6f6;
                border-radius: 10px;
                padding: 14px 8px;
                text-align: center;
                cursor: pointer;
                transition: transform .12s ease, box-shadow .12s ease, background .12s ease;
                min-height: 72px;
            }}

            .stat:hover {{
                background: #eeeeee;
                box-shadow: 0 2px 8px rgba(0,0,0,.10);
                transform: translateY(-1px);
            }}

            .stat:active {{
                transform: scale(.98);
            }}

            .stat strong {{
                display: block;
                font-size: 22px;
            }}

            .stat span {{
                display: block;
                margin-top: 5px;
                font-size: 13px;
            }}

            .stat small {{
                display: block;
                margin-top: 6px;
                font-size: 11px;
                color: #666;
            }}

            .notifikace-box {{
                margin-top: 25px;
                padding-top: 20px;
                border-top: 1px solid #ddd;
            }}

            #povolit-notifikace {{
                background: #1769aa;
                color: white;
            }}

            .notifikace-stav {{
                margin-top: 10px;
                min-height: 20px;
                color: #555;
                font-size: 14px;
                text-align: center;
            }}
        </style>
    </head>

    <body>
        <div class="box">
            <h1>Dokumentace oprav</h1>

            <p>
                Přihlášen:
                <strong>{escape(u["jmeno"])}</strong>
            </p>

            {obsah}

            <div class="notifikace-box">
                <h3>🔔 Upozornění na poruchy</h3>

                <button id="povolit-notifikace" type="button">
                    🔔 POVOLIT UPOZORNĚNÍ
                </button>

                <div id="notifikace-stav"
                     class="notifikace-stav"></div>
            </div>

            <hr>

            <a href="/odhlasit">
                <button class="logout">
                    ODHLÁSIT
                </button>
            </a>
        </div>

        <script>
            function urlBase64ToUint8Array(base64String) {{
                const padding = "=".repeat((4 - base64String.length % 4) % 4);
                const base64 = (base64String + padding)
                    .replace(/-/g, "+")
                    .replace(/_/g, "/");

                const rawData = window.atob(base64);

                return Uint8Array.from(
                    [...rawData].map(
                        char => char.charCodeAt(0)
                    )
                );
            }}

            async function registrovatPush() {{
                const tlacitko =
                    document.getElementById("povolit-notifikace");

                const stav =
                    document.getElementById("notifikace-stav");

                if (
                    !("serviceWorker" in navigator) ||
                    !("PushManager" in window)
                ) {{
                    stav.textContent =
                        "⚠️ Tento prohlížeč push upozornění nepodporuje.";
                    return;
                }}

                try {{
                    tlacitko.disabled = true;
                    stav.textContent = "Připravuji upozornění...";

                    const registration =
                        await navigator.serviceWorker.register(
                            "/service-worker.js"
                        );

                    let permission = Notification.permission;

                    if (permission !== "granted") {{
                        permission =
                            await Notification.requestPermission();
                    }}

                    if (permission !== "granted") {{
                        stav.textContent =
                            "⚠️ Upozornění nebyla povolena.";
                        tlacitko.disabled = false;
                        return;
                    }}

                    const keyResponse =
                        await fetch("/api/vapid-public-key");

                    const keyData =
                        await keyResponse.json();

                    if (!keyResponse.ok) {{
                        throw new Error(
                            keyData.error ||
                            "Nepodařilo se načíst VAPID klíč."
                        );
                    }}

                    let subscription =
                        await registration.pushManager.getSubscription();

                    if (!subscription) {{
                        subscription =
                            await registration.pushManager.subscribe({{
                                userVisibleOnly: true,
                                applicationServerKey:
                                    urlBase64ToUint8Array(
                                        keyData.publicKey
                                    )
                            }});
                    }}

                    const response =
                        await fetch("/api/push/subscribe", {{
                            method: "POST",
                            headers: {{
                                "Content-Type": "application/json"
                            }},
                            body: JSON.stringify(subscription)
                        }});

                    const data = await response.json();

                    if (!response.ok) {{
                        throw new Error(
                            data.error ||
                            "Registrace telefonu selhala."
                        );
                    }}

                    stav.textContent =
                        "✅ Upozornění jsou na tomto zařízení povolena.";

                    tlacitko.textContent =
                        "✅ UPOZORNĚNÍ POVOLENA";

                }} catch (error) {{
                    console.error(error);
                    stav.textContent = "⚠️ " + error.message;
                    tlacitko.disabled = false;
                }}
            }}

            document
                .getElementById("povolit-notifikace")
                .addEventListener(
                    "click",
                    registrovatPush
                );

            if (
                "Notification" in window &&
                Notification.permission === "granted"
            ) {{
                document.getElementById(
                    "notifikace-stav"
                ).textContent =
                    "Upozornění už byla v tomto prohlížeči povolena.";
            }}
        </script>
    </body>
    </html>
    """


# ============================================================
# PUSH API
# ============================================================

@app.route("/service-worker.js")
def service_worker():
    return send_file(
        os.path.join(
            os.path.dirname(__file__),
            "service-worker.js"
        ),
        mimetype="application/javascript"
    )


@app.route("/api/vapid-public-key")
def api_vapid_public_key():
    if not prihlaseny():
        return jsonify({"error": "Nejste přihlášen."}), 401

    try:
        return jsonify({
            "publicKey":
                verejny_vapid_klic_base64url()
        })

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/push/subscribe", methods=["POST"])
def api_push_subscribe():
    if not prihlaseny():
        return jsonify({"error": "Nejste přihlášen."}), 401

    subscription = request.get_json(silent=True)

    if not subscription or not subscription.get("endpoint"):
        return jsonify({
            "error": "Neplatná registrace telefonu."
        }), 400

    uloz_push_subscription(
        session["uzivatel"],
        subscription
    )

    return jsonify({"ok": True})


# ============================================================
# NAHLÁSIT OPRAVU
# ============================================================

@app.route("/nahlasit-opravu", methods=["GET", "POST"])
def nahlasit_opravu():
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    u = aktualni_uzivatel()

    if request.method == "POST":
        stroj = request.form.get("stroj", "").strip()
        zavada = request.form.get("zavada", "").strip()
        provedeno = request.form.get("provedeno", "").strip()

        if not stroj or stroj not in STROJE or not zavada:
            return chybova_stranka(
                "⚠️ Neplatná data",
                "Zkontrolujte vybraný stroj a popis závady.",
                "/nahlasit-opravu",
                "← Zpět na formulář"
            ), 400

        row = execute_returning(
            """
            INSERT INTO repairs (
                machine,
                problem,
                initial_work,
                status,
                reported_by_login,
                reported_by_name
            )
            VALUES (%s, %s, %s, 'nova', %s, %s)
            RETURNING id
            """,
            (
                stroj,
                zavada,
                provedeno,
                u["login"],
                u["jmeno"]
            )
        )

        repair_id = row["id"]

        uloz_fotky(
            repair_id,
            request.files.getlist("fotografie"),
            phase="zavada"
        )

        pridej_event(
            repair_id,
            "nahlaseno",
            f"Nahlášena závada: {zavada}"
        )

        odesli_push(
            "🔧 Nová porucha stroje",
            f"{stroj}: {zavada}",
            url=f"/oprava/{repair_id}",
            exclude_login=u["login"]
        )

        return redirect(
            url_for(
                "detail_opravy",
                repair_id=repair_id
            )
        )

    stroje_html = "".join(
        f'<option value="{escape(stroj)}">{escape(stroj)}</option>'
        for stroj in STROJE
    )

    return f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">

        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>Nahlásit opravu</title>

        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f2f2f2;
                margin: 0;
                padding: 18px;
            }}

            .box {{
                max-width: 720px;
                margin: 20px auto;
                background: white;
                padding: 26px;
                border-radius: 15px;
                box-shadow: 0 3px 15px rgba(0,0,0,0.15);
            }}

            h1 {{
                text-align: center;
            }}

            label {{
                display: block;
                font-weight: bold;
                margin-top: 20px;
                margin-bottom: 8px;
            }}

            select,
            textarea {{
                width: 100%;
                box-sizing: border-box;
                padding: 14px;
                font-size: 17px;
                border: 1px solid #ccc;
                border-radius: 8px;
            }}

            textarea {{
                min-height: 130px;
                resize: vertical;
            }}

            button {{
                width: 100%;
                padding: 16px;
                margin-top: 10px;
                font-size: 18px;
                border: none;
                border-radius: 8px;
                background: #333;
                color: white;
                cursor: pointer;
            }}

            .hlas {{
                background: #555;
            }}

            .hlas.posloucham {{
                background: #b00020;
            }}

            .stav {{
                text-align: center;
                margin-top: 10px;
                font-size: 15px;
                color: #555;
                min-height: 20px;
            }}

            .zpet {{
                display: block;
                text-align: center;
                margin-top: 20px;
                color: #333;
            }}

            .foto-input {{
                width: 100%;
                box-sizing: border-box;
                padding: 14px;
                font-size: 16px;
                border: 1px solid #ccc;
                border-radius: 8px;
                background: white;
            }}

            .foto-info {{
                margin-top: 8px;
                color: #555;
                font-size: 14px;
            }}
        </style>
    </head>

    <body>
        <div class="box">
            <h1>🔧 Nahlásit opravu</h1>

            <p>
                Nahlásil:
                <strong>{escape(u["jmeno"])}</strong>
            </p>

            <form method="POST"
                  enctype="multipart/form-data">

                <label>Stroj</label>

                <select name="stroj" required>
                    <option value="">
                        -- Vyber stroj --
                    </option>

                    {stroje_html}
                </select>

                <label>Popis závady</label>

                <textarea
                    id="zavada"
                    name="zavada"
                    placeholder="Sem napište nebo nadiktujte závadu..."
                    required
                ></textarea>

                <button
                    type="button"
                    class="hlas"
                    onclick="diktovat('zavada', this)"
                >
                    🎤 DIKTOVAT ZÁVADU
                </button>

                <div id="stav-zavada"
                     class="stav"></div>

                <label>Co už bylo provedeno</label>

                <textarea
                    id="provedeno"
                    name="provedeno"
                    placeholder="Volitelné – pokud jste už něco udělali..."
                ></textarea>

                <button
                    type="button"
                    class="hlas"
                    onclick="diktovat('provedeno', this)"
                >
                    🎤 DIKTOVAT PROVEDENOU OPRAVU
                </button>

                <div id="stav-provedeno"
                     class="stav"></div>

                <label>Fotografie závady</label>

                <input
                    type="file"
                    name="fotografie"
                    accept="image/*"
                    capture="environment"
                    multiple
                    class="foto-input"
                >

                <div class="foto-info">
                    📷 Můžete přidat více fotografií.
                </div>

                <button type="submit">
                    ODESLAT OPRAVU
                </button>
            </form>

            <a class="zpet"
               href="/hlavni">
                ← Zpět
            </a>
        </div>

        <script>
            function diktovat(id, tlacitko) {{
                const pole =
                    document.getElementById(id);

                const stav =
                    document.getElementById(
                        "stav-" + id
                    );

                const SpeechRecognition =
                    window.SpeechRecognition ||
                    window.webkitSpeechRecognition;

                if (!SpeechRecognition) {{
                    stav.innerHTML =
                        "⚠️ Tento prohlížeč hlasové diktování nepodporuje.";
                    return;
                }}

                const recognition =
                    new SpeechRecognition();

                recognition.lang = "cs-CZ";
                recognition.interimResults = true;
                recognition.continuous = false;

                tlacitko.classList.add(
                    "posloucham"
                );

                tlacitko.innerHTML =
                    "🔴 POSLOUCHÁM...";

                stav.innerHTML = "Mluvte...";

                let puvodniText = pole.value;

                recognition.onresult =
                    function(event) {{
                        let text = "";

                        for (
                            let i = event.resultIndex;
                            i < event.results.length;
                            i++
                        ) {{
                            text +=
                                event.results[i][0]
                                    .transcript;
                        }}

                        if (
                            puvodniText.trim() !== ""
                        ) {{
                            pole.value =
                                puvodniText.trim() +
                                " " +
                                text;
                        }} else {{
                            pole.value = text;
                        }}
                    }};

                recognition.onerror =
                    function(event) {{
                        stav.innerHTML =
                            "⚠️ Nepodařilo se použít mikrofon: " +
                            event.error;
                    }};

                recognition.onend =
                    function() {{
                        tlacitko.classList.remove(
                            "posloucham"
                        );

                        tlacitko.innerHTML =
                            "🎤 DIKTOVAT ZNOVU";

                        if (
                            pole.value.trim() !== ""
                        ) {{
                            stav.innerHTML =
                                "✅ Text byl vložen.";
                        }} else {{
                            stav.innerHTML = "";
                        }}
                    }};

                recognition.start();
            }}
        </script>
    </body>
    </html>
    """


# ============================================================
# SEZNAM OPRAV
# ============================================================

@app.route("/opravy")
def vsechny_opravy():
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    status_filter = request.args.get(
        "stav",
        ""
    ).strip()

    params = []
    where = ""

    if status_filter in STAVY:
        where = "WHERE r.status = %s"
        params.append(status_filter)

    opravy = fetch_all(
        f"""
        SELECT
            r.*,
            (
                SELECT COUNT(*)
                FROM repair_photos p
                WHERE p.repair_id = r.id
            ) AS photo_count
        FROM repairs r
        {where}
        ORDER BY
            CASE r.status
                WHEN 'nova' THEN 1
                WHEN 'resi_se' THEN 2
                ELSE 3
            END,
            r.created_at DESC
        """,
        tuple(params)
    )

    cards = ""

    for o in opravy:
        assigned = (
            escape(o["assigned_to_name"])
            if o["assigned_to_name"]
            else "zatím nikdo"
        )

        cards += f"""
        <a class="card-link"
           href="/oprava/{o["id"]}">
            <div class="card">
                <div class="top">
                    <strong>#{o["id"]} · {escape(o["machine"])}</strong>
                    <span>{stav_html(o["status"])}</span>
                </div>

                <div class="problem">
                    {escape(o["problem"])}
                </div>

                <div class="meta">
                    Nahlásil: {escape(o["reported_by_name"])}
                    · {format_datum(o["created_at"])}
                    <br>
                    Převzal: {assigned}
                    · 📷 {o["photo_count"]}
                </div>
            </div>
        </a>
        """

    if not cards:
        cards = """
        <div class="empty">
            Zatím zde nejsou žádné opravy.
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">

        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>Všechny opravy</title>

        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f2f2f2;
                margin: 0;
                padding: 16px;
            }}

            .wrap {{
                max-width: 900px;
                margin: 0 auto;
            }}

            .head {{
                background: white;
                padding: 20px;
                border-radius: 14px;
                margin-bottom: 14px;
            }}

            .filters {{
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 8px;
                margin-top: 14px;
            }}

            .filters a {{
                text-decoration: none;
                text-align: center;
                padding: 10px 6px;
                border-radius: 8px;
                background: #eee;
                color: #222;
                font-size: 14px;
            }}

            .card-link {{
                text-decoration: none;
                color: inherit;
            }}

            .card {{
                background: white;
                padding: 18px;
                border-radius: 14px;
                margin-bottom: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,.08);
            }}

            .top {{
                display: flex;
                justify-content: space-between;
                gap: 10px;
                font-size: 18px;
            }}

            .problem {{
                margin-top: 12px;
                font-size: 16px;
            }}

            .meta {{
                margin-top: 12px;
                color: #666;
                font-size: 13px;
                line-height: 1.5;
            }}

            .back {{
                display: inline-block;
                margin-top: 12px;
                color: #333;
            }}

            .empty {{
                background: white;
                padding: 30px;
                border-radius: 14px;
                text-align: center;
            }}
        </style>
    </head>

    <body>
        <div class="wrap">
            <div class="head">
                <h1>📋 Opravy</h1>

                <div class="filters">
                    <a href="/opravy">Vše</a>
                    <a href="/opravy?stav=nova">🔴 Nové</a>
                    <a href="/opravy?stav=resi_se">🟠 Řeší se</a>
                    <a href="/opravy?stav=hotovo">🟢 Hotovo</a>
                </div>

                <a class="back"
                   href="/hlavni">
                    ← Hlavní stránka
                </a>
            </div>

            {cards}
        </div>
    </body>
    </html>
    """


# ============================================================
# MOJE OPRAVY
# ============================================================

@app.route("/moje-opravy")
def moje_opravy():
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    u = aktualni_uzivatel()

    opravy = fetch_all(
        """
        SELECT *
        FROM repairs
        WHERE assigned_to_login = %s
        ORDER BY
            CASE status
                WHEN 'resi_se' THEN 1
                WHEN 'nova' THEN 2
                ELSE 3
            END,
            created_at DESC
        """,
        (u["login"],)
    )

    rows = ""

    for o in opravy:
        rows += f"""
        <a class="card-link"
           href="/oprava/{o["id"]}">
            <div class="card">
                <strong>
                    #{o["id"]} · {escape(o["machine"])}
                </strong>

                <span>
                    {stav_html(o["status"])}
                </span>

                <p>
                    {escape(o["problem"])}
                </p>

                <small>
                    {format_datum(o["created_at"])}
                </small>
            </div>
        </a>
        """

    if not rows:
        rows = """
        <div class="card">
            Zatím nemáš převzatou žádnou opravu.
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">
        <title>Moje opravy</title>

        <style>
            body {{
                font-family: Arial;
                background: #f2f2f2;
                margin: 0;
                padding: 16px;
            }}

            .wrap {{
                max-width: 800px;
                margin: auto;
            }}

            .head, .card {{
                background: white;
                padding: 18px;
                border-radius: 14px;
                margin-bottom: 12px;
            }}

            .card-link {{
                text-decoration: none;
                color: inherit;
            }}

            .card span {{
                float: right;
            }}

            .back {{
                color: #333;
            }}
        </style>
    </head>

    <body>
        <div class="wrap">
            <div class="head">
                <h1>👨‍🔧 Moje opravy</h1>
                <a class="back"
                   href="/hlavni">
                    ← Hlavní stránka
                </a>
            </div>

            {rows}
        </div>
    </body>
    </html>
    """


# ============================================================
# DETAIL OPRAVY
# ============================================================

@app.route("/oprava/<int:repair_id>")
def detail_opravy(repair_id):
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    u = aktualni_uzivatel()

    oprava = fetch_one(
        """
        SELECT *
        FROM repairs
        WHERE id = %s
        """,
        (repair_id,)
    )

    if not oprava:
        return chybova_stranka(
            "⚠️ Oprava nenalezena",
            "Tato oprava neexistuje nebo už byla odstraněna.",
            "/opravy",
            "← Zpět na opravy"
        ), 404

    execute(
        """
        INSERT INTO repair_views
            (repair_id, user_login, user_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (repair_id, user_login) DO NOTHING
        """,
        (repair_id, u["login"], u["jmeno"])
    )

    zobrazeni = fetch_all(
        """
        SELECT user_name, first_viewed_at
        FROM repair_views
        WHERE repair_id = %s
        ORDER BY first_viewed_at
        """,
        (repair_id,)
    )

    views_html = ""

    for z in zobrazeni:
        views_html += f"""
        <div class="view-row">
            <strong>👁️ {escape(z["user_name"])}</strong>
            <span>{format_datum(z["first_viewed_at"])}</span>
        </div>
        """

    if not views_html:
        views_html = "<p>Zatím nikdo.</p>"

    fotky = fetch_all(
        """
        SELECT id, phase, filename, created_at
        FROM repair_photos
        WHERE repair_id = %s
        ORDER BY created_at
        """,
        (repair_id,)
    )

    events = fetch_all(
        """
        SELECT *
        FROM repair_events
        WHERE repair_id = %s
        ORDER BY created_at
        """,
        (repair_id,)
    )

    photos_html = ""

    for f in fotky:
        photos_html += f"""
        <a href="/foto/{f["id"]}"
           target="_blank">
            <img src="/foto/{f["id"]}"
                 alt="Fotografie opravy">
        </a>
        """

    if not photos_html:
        photos_html = "<p>Žádné fotografie.</p>"

    event_html = ""

    for e in events:
        event_html += f"""
        <div class="event">
            <strong>{escape(e["user_name"])}</strong>
            · {format_datum(e["created_at"])}
            <br>
            {escape(e["note"] or e["event_type"])}
        </div>
        """

    assigned = (
        escape(oprava["assigned_to_name"])
        if oprava["assigned_to_name"]
        else "zatím nikdo"
    )

    action_html = ""

    if oprava["status"] == "nova" and u["role"] == "udrzbar":
        action_html = f"""
        <form method="POST"
              action="/oprava/{repair_id}/prevzit">
            <button class="take"
                    type="submit">
                👨‍🔧 PŘEVZÍT OPRAVU
            </button>
        </form>
        """

    elif (
        oprava["status"] == "resi_se" and
        (
            oprava["assigned_to_login"] == u["login"] or
            u["role"] == "admin"
        )
    ):
        action_html = f"""
        <form method="POST"
              enctype="multipart/form-data"
              action="/oprava/{repair_id}/dokoncit">

            <label>
                Co bylo provedeno
            </label>

            <textarea
                name="final_work"
                required
                placeholder="Popište provedenou opravu..."
            ></textarea>

            <label>
                Fotografie po opravě
            </label>

            <input
                type="file"
                name="fotografie"
                accept="image/*"
                capture="environment"
                multiple
            >

            <button class="finish"
                    type="submit">
                ✅ DOKONČIT OPRAVU
            </button>
        </form>
        """

    delete_html = ""

    if u["role"] == "admin":
        delete_html = f"""
        <form method="POST"
              action="/oprava/{repair_id}/smazat"
              onsubmit="return confirm('Opravdu chcete tuto opravu trvale smazat? Tím se smažou i fotografie a historie.');">
            <button class="delete" type="submit">
                🗑️ SMAZAT OPRAVU
            </button>
        </form>
        """

    initial_work_html = ""

    if oprava["initial_work"]:
        initial_work_html = f"""
        <div class="section">
            <h3>Co bylo provedeno při nahlášení</h3>
            <p>{escape(oprava["initial_work"])}</p>
        </div>
        """

    final_work_html = ""

    if oprava["final_work"]:
        final_work_html = f"""
        <div class="section">
            <h3>Výsledek opravy</h3>
            <p>{escape(oprava["final_work"])}</p>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">

        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>Oprava #{repair_id}</title>

        <style>
            body {{
                font-family: Arial;
                background: #f2f2f2;
                margin: 0;
                padding: 16px;
            }}

            .wrap {{
                max-width: 850px;
                margin: auto;
            }}

            .box {{
                background: white;
                padding: 22px;
                border-radius: 14px;
                margin-bottom: 12px;
            }}

            .status {{
                font-size: 20px;
                font-weight: bold;
            }}

            .meta {{
                color: #666;
                font-size: 14px;
                line-height: 1.6;
            }}

            .view-row {{
                display: flex;
                justify-content: space-between;
                gap: 12px;
                padding: 9px 0;
                border-bottom: 1px solid #eee;
                font-size: 14px;
            }}

            .view-row:last-child {{
                border-bottom: 0;
            }}

            .view-row span {{
                color: #666;
                white-space: nowrap;
            }}

            .section {{
                border-top: 1px solid #ddd;
                margin-top: 18px;
                padding-top: 14px;
            }}

            .photos {{
                display: grid;
                grid-template-columns:
                    repeat(auto-fill, minmax(120px, 1fr));
                gap: 8px;
            }}

            .photos img {{
                width: 100%;
                aspect-ratio: 1;
                object-fit: cover;
                border-radius: 8px;
            }}

            .event {{
                background: #f7f7f7;
                padding: 10px;
                border-radius: 8px;
                margin-bottom: 7px;
                font-size: 14px;
            }}

            textarea, input {{
                width: 100%;
                box-sizing: border-box;
                padding: 12px;
                margin: 7px 0 12px;
                font-size: 16px;
            }}

            textarea {{
                min-height: 120px;
            }}

            button {{
                width: 100%;
                padding: 15px;
                border: 0;
                border-radius: 8px;
                font-size: 17px;
                cursor: pointer;
            }}

            .take {{
                background: #f0a000;
                color: white;
            }}

            .finish {{
                background: #198754;
                color: white;
            }}

            .delete {{
                background: #b00020;
                color: white;
                margin-top: 12px;
            }}

            .back {{
                display: inline-block;
                margin-bottom: 12px;
                color: #333;
            }}
        </style>
    </head>

    <body>
        <div class="wrap">
            <a class="back"
               href="/opravy">
                ← Zpět na opravy
            </a>

            <div class="box">
                <h1>
                    #{repair_id} · {escape(oprava["machine"])}
                </h1>

                <div class="status">
                    {stav_html(oprava["status"])}
                </div>

                <p>
                    <strong>Závada:</strong><br>
                    {escape(oprava["problem"])}
                </p>

                <div class="meta">
                    Nahlásil:
                    {escape(oprava["reported_by_name"])}
                    · {format_datum(oprava["created_at"])}
                    <br>

                    Převzal:
                    {assigned}

                    {(
                        " · " + format_datum(oprava["assigned_at"])
                        if oprava["assigned_at"]
                        else ""
                    )}

                    <br>

                    Dokončeno:
                    {format_datum(oprava["completed_at"])}
                </div>

                <div class="section">
                <h3>👁️ Zobrazeno</h3>
                {views_html}
            </div>

            {initial_work_html}
                {final_work_html}

                <div class="section">
                    <h3>📷 Fotografie</h3>
                    <div class="photos">
                        {photos_html}
                    </div>
                </div>
            </div>

            <div class="box">
                {action_html}
                {delete_html}
            </div>

            <div class="box">
                <h3>🕓 Historie opravy</h3>
                {event_html}
            </div>
        </div>
    </body>
    </html>
    """


@app.route("/oprava/<int:repair_id>/prevzit", methods=["POST"])
def prevzit_opravu(repair_id):
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    u = aktualni_uzivatel()

    if u["role"] != "udrzbar":
        return chybova_stranka(
            "⚠️ Opravu nelze převzít",
            "Pouze údržbář může převzít opravu.",
            f"/oprava/{repair_id}",
            "← Zpět na opravu"
        ), 403

    conn = db_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE repairs
                    SET
                        status = 'resi_se',
                        assigned_to_login = %s,
                        assigned_to_name = %s,
                        assigned_at = NOW()
                    WHERE id = %s
                      AND status = 'nova'
                    RETURNING id, machine, problem
                    """,
                    (
                        u["login"],
                        u["jmeno"],
                        repair_id
                    )
                )

                row = cur.fetchone()

                if not row:
                    return chybova_stranka(
                        "⚠️ Opravu už nelze převzít",
                        "Opravu už mezitím převzal někdo jiný, nebo už neexistuje.",
                        f"/oprava/{repair_id}",
                        "← Zpět na opravu"
                    ), 409

    finally:
        conn.close()

    pridej_event(
        repair_id,
        "prevzato",
        f"Opravu převzal {u['jmeno']}."
    )

    odesli_push(
        "👨‍🔧 Oprava převzata",
        f"{row['machine']}: převzal {u['jmeno']}",
        url=f"/oprava/{repair_id}",
        exclude_login=u["login"]
    )

    return redirect(
        url_for(
            "detail_opravy",
            repair_id=repair_id
        )
    )


@app.route("/oprava/<int:repair_id>/dokoncit", methods=["POST"])
def dokoncit_opravu(repair_id):
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    u = aktualni_uzivatel()
    final_work = request.form.get(
        "final_work",
        ""
    ).strip()

    if not final_work:
        return chybova_stranka(
            "⚠️ Chybí popis opravy",
            "Doplňte prosím, co bylo při opravě provedeno.",
            f"/oprava/{repair_id}",
            "← Zpět na opravu"
        ), 400

    oprava = fetch_one(
        """
        SELECT *
        FROM repairs
        WHERE id = %s
        """,
        (repair_id,)
    )

    if not oprava:
        return chybova_stranka(
            "⚠️ Oprava nenalezena",
            "Tato oprava neexistuje nebo už byla odstraněna.",
            "/opravy",
            "← Zpět na opravy"
        ), 404

    if oprava["status"] != "resi_se":
        return chybova_stranka(
            "⚠️ Opravu nelze dokončit",
            "Tato oprava už není ve stavu Řeší se.",
            f"/oprava/{repair_id}",
            "← Zpět na opravu"
        ), 409

    if (
        u["role"] != "admin" and
        oprava["assigned_to_login"] != u["login"]
    ):
        return chybova_stranka(
            "⚠️ Opravu řeší někdo jiný",
            "Tuto opravu má převzatý jiný údržbář.",
            f"/oprava/{repair_id}",
            "← Zpět na opravu"
        ), 403

    execute(
        """
        UPDATE repairs
        SET
            status = 'hotovo',
            final_work = %s,
            completed_at = NOW()
        WHERE id = %s
        """,
        (
            final_work,
            repair_id
        )
    )

    uloz_fotky(
        repair_id,
        request.files.getlist("fotografie"),
        phase="po_oprave"
    )

    pridej_event(
        repair_id,
        "dokonceno",
        f"Oprava dokončena. {final_work}"
    )

    odesli_push(
        "✅ Oprava dokončena",
        f"{oprava['machine']}: {final_work}",
        url=f"/oprava/{repair_id}",
        exclude_login=u["login"]
    )

    return redirect(
        url_for(
            "detail_opravy",
            repair_id=repair_id
        )
    )


# ============================================================
# FOTOGRAFIE
# ============================================================

@app.route("/foto/<int:photo_id>")
def foto(photo_id):
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    row = fetch_one(
        """
        SELECT mime_type, data
        FROM repair_photos
        WHERE id = %s
        """,
        (photo_id,)
    )

    if not row:
        return "Fotografie nebyla nalezena.", 404

    return Response(
        bytes(row["data"]),
        mimetype=row["mime_type"]
    )


# ============================================================
# STROJE / HISTORIE
# ============================================================

@app.route("/stroje")
def stroje():
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    rows = fetch_all(
        """
        SELECT
            machine,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'nova') AS nova,
            COUNT(*) FILTER (WHERE status = 'resi_se') AS resi_se,
            COUNT(*) FILTER (WHERE status = 'hotovo') AS hotovo
        FROM repairs
        GROUP BY machine
        ORDER BY machine
        """
    )

    data = {
        row["machine"]: row
        for row in rows
    }

    cards = ""

    for stroj in STROJE:
        r = data.get(
            stroj,
            {
                "total": 0,
                "nova": 0,
                "resi_se": 0,
                "hotovo": 0
            }
        )

        cards += f"""
        <a class="card-link"
           href="/stroj/{escape(stroj)}">
            <div class="card">
                <strong>{escape(stroj)}</strong>
                <span>
                    Celkem: {r["total"]}
                    · 🔴 {r["nova"]}
                    · 🟠 {r["resi_se"]}
                    · 🟢 {r["hotovo"]}
                </span>
            </div>
        </a>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">
        <title>Stroje</title>

        <style>
            body {{
                font-family: Arial;
                background: #f2f2f2;
                margin: 0;
                padding: 16px;
            }}

            .wrap {{
                max-width: 800px;
                margin: auto;
            }}

            .head, .card {{
                background: white;
                padding: 18px;
                border-radius: 14px;
                margin-bottom: 12px;
            }}

            .card-link {{
                text-decoration: none;
                color: inherit;
            }}

            .card span {{
                display: block;
                margin-top: 8px;
                color: #666;
            }}
        </style>
    </head>

    <body>
        <div class="wrap">
            <div class="head">
                <h1>🏭 Stroje</h1>

                <a href="/hlavni">
                    ← Hlavní stránka
                </a>
            </div>

            {cards}
        </div>
    </body>
    </html>
    """


@app.route("/stroj/<path:nazev>")
def historie_stroje(nazev):
    if not prihlaseny():
        return redirect(url_for("prihlaseni"))

    if nazev not in STROJE:
        return chybova_stranka(
            "⚠️ Stroj nenalezen",
            "Požadovaný stroj nebyl nalezen.",
            "/stroje",
            "← Zpět na stroje"
        ), 404

    rows = fetch_all(
        """
        SELECT *
        FROM repairs
        WHERE machine = %s
        ORDER BY created_at DESC
        """,
        (nazev,)
    )

    cards = ""

    for o in rows:
        cards += f"""
        <a class="card-link"
           href="/oprava/{o["id"]}">
            <div class="card">
                <strong>
                    #{o["id"]} · {stav_html(o["status"])}
                </strong>

                <p>{escape(o["problem"])}</p>

                <small>
                    {format_datum(o["created_at"])}
                    · {escape(o["reported_by_name"])}
                </small>
            </div>
        </a>
        """

    if not cards:
        cards = """
        <div class="card">
            Tento stroj zatím nemá žádný záznam.
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">

        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>Historie {escape(nazev)}</title>

        <style>
            body {{
                font-family: Arial;
                background: #f2f2f2;
                margin: 0;
                padding: 16px;
            }}

            .wrap {{
                max-width: 800px;
                margin: auto;
            }}

            .head, .card {{
                background: white;
                padding: 18px;
                border-radius: 14px;
                margin-bottom: 12px;
            }}

            .card-link {{
                text-decoration: none;
                color: inherit;
            }}
        </style>
    </head>

    <body>
        <div class="wrap">
            <div class="head">
                <h1>🏭 {escape(nazev)}</h1>
                <a href="/stroje">
                    ← Zpět na stroje
                </a>
            </div>

            {cards}
        </div>
    </body>
    </html>
    """


# ============================================================
# ODHLÁŠENÍ
# ============================================================

@app.route("/odhlasit")
def odhlasit():
    session.clear()
    return redirect(url_for("prihlaseni"))


# ============================================================
# SPUŠTĚNÍ
# ============================================================

try:
    init_db()
except Exception as exc:
    print("CHYBA PŘI INICIALIZACI DATABÁZE:", exc)


if __name__ == "__main__":
    app.run(debug=True)
