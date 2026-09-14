
from flask import Flask, request, redirect, url_for, session, send_from_directory, jsonify, send_file
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import uuid
import json
import base64
from pywebpush import webpush, WebPushException
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

app = Flask(__name__)
app.secret_key = "docasne-tajne-heslo"

UPLOAD_FOLDER = "fotografie_oprav"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ============================================================
# PUSH NOTIFIKACE
# ============================================================

VAPID_PRIVATE_KEY = os.path.join(os.path.dirname(__file__), "private_key.pem")
VAPID_PUBLIC_KEY = os.path.join(os.path.dirname(__file__), "public_key.pem")
PUSH_SUBSCRIPTIONS_FILE = os.path.join(os.path.dirname(__file__), "push_subscriptions.json")

# Můžeš později změnit v Renderu jako proměnnou prostředí VAPID_SUBJECT.
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")


def nacti_push_subscriptions():
    if not os.path.exists(PUSH_SUBSCRIPTIONS_FILE):
        return []

    try:
        with open(PUSH_SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as soubor:
            data = json.load(soubor)
            return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def uloz_push_subscriptions(data):
    with open(PUSH_SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as soubor:
        json.dump(data, soubor, ensure_ascii=False, indent=2)


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


def odesli_push_vsem_ostatnim(nahlasil_login, stroj, zavada):
    if not os.path.exists(VAPID_PRIVATE_KEY):
        print("Push přeskočen: chybí private_key.pem")
        return

    subscriptions = nacti_push_subscriptions()

    if not subscriptions:
        print("Push přeskočen: zatím není registrován žádný telefon.")
        return

    payload = {
        "title": "🔧 Nová porucha stroje",
        "body": f"{stroj}: {zavada[:140]}",
        "url": "/hlavni"
    }

    platne = []

    for zaznam in subscriptions:
        subscription = zaznam.get("subscription")
        login = zaznam.get("uzivatel")

        if not subscription:
            continue

        # Uživateli, který závadu nahlásil, ji neposíláme.
        if login == nahlasil_login:
            platne.append(zaznam)
            continue

        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT}
            )
            platne.append(zaznam)

        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)

            # 404/410 = odběr už na push serveru neexistuje.
            if status in (404, 410):
                print("Odstraňuji neplatné push přihlášení:", login)
            else:
                print("Chyba při odesílání push:", exc)
                platne.append(zaznam)

    if len(platne) != len(subscriptions):
        uloz_push_subscriptions(platne)


# ============================================================
# UŽIVATELÉ
# ============================================================

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


# ============================================================
# STROJE
# ============================================================

STROJE = [
    "Linka",
    "Odformovací linka",
    "Robot",
    "Betonárka",
    "Vibrační stoly"
]


# ============================================================
# PŘIHLÁŠENÍ
# ============================================================

@app.route("/", methods=["GET", "POST"])
def prihlaseni():

    if "uzivatel" in session:
        return redirect(url_for("hlavni_stranka"))

    chyba = ""

    if request.method == "POST":

        uzivatel = request.form.get("uzivatel")
        heslo = request.form.get("heslo")

        if uzivatel in UZIVATELE and UZIVATELE[uzivatel]["heslo"] == heslo:
            session["uzivatel"] = uzivatel
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
                max-width: 400px;
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
                color: red;
                text-align: center;
                margin-bottom: 15px;
            }}

        </style>

    </head>

    <body>

        <div class="box">

            <h1>Dokumentace oprav</h1>

            <div class="chyba">{chyba}</div>

            <form method="POST" enctype="multipart/form-data">

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

    if "uzivatel" not in session:
        return redirect(url_for("prihlaseni"))

    uzivatel = UZIVATELE[session["uzivatel"]]

    if uzivatel["role"] == "admin":

        obsah = """
        <h2>Přehled oprav</h2>

        <p>Zde později uvidíš všechny nahlášené opravy.</p>

        <button>VŠECHNY OPRAVY</button>
        <button>STROJE</button>
        <button>HISTORIE</button>
        """

    else:

        obsah = """
        <h2>Údržba</h2>

        <a href="/nahlasit-opravu">
            <button>🔧 NAHLÁSIT OPRAVU</button>
        </a>

        <button>MOJE OPRAVY</button>
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
                padding: 20px;
            }}

            .box {{
                max-width: 700px;
                margin: 30px auto;
                background: white;
                padding: 30px;
                border-radius: 15px;
                box-shadow: 0 3px 15px rgba(0,0,0,0.15);
            }}

            h1 {{
                margin-bottom: 5px;
            }}

            h2 {{
                margin-top: 35px;
            }}

            button {{
                width: 100%;
                padding: 16px;
                margin: 8px 0;
                font-size: 17px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
            }}

            .logout {{
                background: #ddd;
            }}

            .notifikace-box {{
                margin-top: 25px;
                padding-top: 20px;
                border-top: 1px solid #ddd;
            }}

            .notifikace-box h3 {{
                margin-bottom: 10px;
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
                <strong>{uzivatel["jmeno"]}</strong>
            </p>


            {obsah}

            <div class="notifikace-box">
                <h3>🔔 Upozornění na poruchy</h3>
                <button id="povolit-notifikace" type="button">
                    🔔 POVOLIT UPOZORNĚNÍ
                </button>
                <div id="notifikace-stav" class="notifikace-stav"></div>
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
                return Uint8Array.from([...rawData].map(char => char.charCodeAt(0)));
            }}

            async function registrovatPush() {{
                const tlacitko = document.getElementById("povolit-notifikace");
                const stav = document.getElementById("notifikace-stav");

                if (!("serviceWorker" in navigator) || !("PushManager" in window)) {{
                    stav.textContent = "⚠️ Tento prohlížeč push upozornění nepodporuje.";
                    return;
                }}

                try {{
                    tlacitko.disabled = true;
                    stav.textContent = "Připravuji upozornění...";

                    const registration = await navigator.serviceWorker.register("/service-worker.js");

                    let permission = Notification.permission;

                    if (permission !== "granted") {{
                        permission = await Notification.requestPermission();
                    }}

                    if (permission !== "granted") {{
                        stav.textContent = "⚠️ Upozornění nebyla povolena.";
                        tlacitko.disabled = false;
                        return;
                    }}

                    const keyResponse = await fetch("/api/vapid-public-key");
                    const keyData = await keyResponse.json();

                    if (!keyResponse.ok) {{
                        throw new Error(keyData.error || "Nepodařilo se načíst VAPID klíč.");
                    }}

                    let subscription = await registration.pushManager.getSubscription();

                    if (!subscription) {{
                        subscription = await registration.pushManager.subscribe({{
                            userVisibleOnly: true,
                            applicationServerKey: urlBase64ToUint8Array(keyData.publicKey)
                        }});
                    }}

                    const response = await fetch("/api/push/subscribe", {{
                        method: "POST",
                        headers: {{
                            "Content-Type": "application/json"
                        }},
                        body: JSON.stringify(subscription)
                    }});

                    const data = await response.json();

                    if (!response.ok) {{
                        throw new Error(data.error || "Registrace telefonu selhala.");
                    }}

                    stav.textContent = "✅ Upozornění jsou na tomto zařízení povolena.";
                    tlacitko.textContent = "✅ UPOZORNĚNÍ POVOLENA";

                }} catch (error) {{
                    console.error(error);
                    stav.textContent = "⚠️ " + error.message;
                    tlacitko.disabled = false;
                }}
            }}

            document.getElementById("povolit-notifikace")
                .addEventListener("click", registrovatPush);

            if (Notification.permission === "granted") {{
                document.getElementById("notifikace-stav").textContent =
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
        os.path.join(os.path.dirname(__file__), "service-worker.js"),
        mimetype="application/javascript"
    )


@app.route("/api/vapid-public-key")
def api_vapid_public_key():
    if "uzivatel" not in session:
        return jsonify({"error": "Nejste přihlášen."}), 401

    try:
        return jsonify({"publicKey": verejny_vapid_klic_base64url()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/push/subscribe", methods=["POST"])
def api_push_subscribe():
    if "uzivatel" not in session:
        return jsonify({"error": "Nejste přihlášen."}), 401

    subscription = request.get_json(silent=True)

    if not subscription or not subscription.get("endpoint"):
        return jsonify({"error": "Neplatná registrace telefonu."}), 400

    subscriptions = nacti_push_subscriptions()
    endpoint = subscription["endpoint"]

    novy_zaznam = {
        "uzivatel": session["uzivatel"],
        "subscription": subscription
    }

    nahrazeno = False

    for index, zaznam in enumerate(subscriptions):
        if zaznam.get("subscription", {}).get("endpoint") == endpoint:
            subscriptions[index] = novy_zaznam
            nahrazeno = True
            break

    if not nahrazeno:
        subscriptions.append(novy_zaznam)

    uloz_push_subscriptions(subscriptions)

    return jsonify({"ok": True})


# ============================================================
# NAHLÁSIT OPRAVU
# ============================================================

@app.route("/nahlasit-opravu", methods=["GET", "POST"])
def nahlasit_opravu():

    if "uzivatel" not in session:
        return redirect(url_for("prihlaseni"))

    uzivatel = UZIVATELE[session["uzivatel"]]

    if request.method == "POST":

        stroj = request.form.get("stroj")
        zavada = request.form.get("zavada")
        provedeno = request.form.get("provedeno")

        datum = datetime.now().strftime("%d.%m.%Y %H:%M")

        # Uložení fotografií.
        ulozene_fotky = []

        fotografie = request.files.getlist("fotografie")

        for fotografie_soubor in fotografie:

            if fotografie_soubor and fotografie_soubor.filename:

                puvodni_nazev = secure_filename(fotografie_soubor.filename)

                pripona = os.path.splitext(puvodni_nazev)[1].lower()

                if not pripona:
                    pripona = ".jpg"

                novy_nazev = (
                    datetime.now().strftime("%Y%m%d_%H%M%S")
                    + "_"
                    + uuid.uuid4().hex[:8]
                    + pripona
                )

                cesta = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    novy_nazev
                )

                fotografie_soubor.save(cesta)

                ulozene_fotky.append(novy_nazev)

        print("")
        print("======================================")
        print("NOVÁ OPRAVA")
        print("======================================")
        print("Nahlásil:", uzivatel["jmeno"])
        print("Datum:", datum)
        print("Stroj:", stroj)
        print("Závada:", zavada)
        print("Provedeno:", provedeno)
        print("Fotografie:", len(ulozene_fotky))

        for fotka in ulozene_fotky:
            print(" -", fotka)

        print("======================================")
        print("")

        # Odeslání push upozornění všem ostatním zaregistrovaným uživatelům.
        odesli_push_vsem_ostatnim(
            session["uzivatel"],
            stroj,
            zavada
        )

        return """
        <html lang="cs">

        <head>

            <meta charset="UTF-8">

            <meta name="viewport"
                  content="width=device-width, initial-scale=1.0">

            <title>Oprava nahlášena</title>

            <style>

                body {
                    font-family: Arial;
                    background: #f2f2f2;
                    padding: 20px;
                }

                .box {
                    max-width: 600px;
                    margin: 40px auto;
                    background: white;
                    padding: 30px;
                    border-radius: 15px;
                    text-align: center;
                }

                a {
                    display: block;
                    background: #333;
                    color: white;
                    padding: 15px;
                    margin-top: 20px;
                    text-decoration: none;
                    border-radius: 8px;
                }

            </style>

        </head>

        <body>

            <div class="box">

                <h1>✅ Oprava nahlášena</h1>

                <p>
                    Oprava byla přijata.
                </p>

                <a href="/nahlasit-opravu">
                    NAHLÁSIT DALŠÍ OPRAVU
                </a>

                <a href="/hlavni">
                    ZPĚT NA HLAVNÍ STRÁNKU
                </a>

            </div>

        </body>

        </html>
        """

    stroje_html = ""

    for stroj in STROJE:
        stroje_html += f'<option value="{stroj}">{stroj}</option>'

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
                padding: 20px;
            }}

            .box {{
                max-width: 700px;
                margin: 20px auto;
                background: white;
                padding: 30px;
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
                min-height: 140px;
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
                <strong>{uzivatel["jmeno"]}</strong>
            </p>

            <form method="POST" enctype="multipart/form-data">

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

                <div id="stav-zavada" class="stav"></div>


                <label>Co bylo provedeno</label>

                <textarea
                    id="provedeno"
                    name="provedeno"
                    placeholder="Sem napište nebo nadiktujte provedenou opravu..."
                ></textarea>

                <button
                    type="button"
                    class="hlas"
                    onclick="diktovat('provedeno', this)"
                >
                    🎤 DIKTOVAT PROVEDENOU OPRAVU
                </button>

                <div id="stav-provedeno" class="stav"></div>


                <label>Fotografie závady / opravy</label>

                <input
                    type="file"
                    name="fotografie"
                    accept="image/*"
                    capture="environment"
                    multiple
                    id="fotografie"
                    class="foto-input"
                >

                <div class="foto-info">
                    📷 Klepnutím vyfotíte závadu. Můžete přidat více fotografií.
                </div>


                <button type="submit">
                    ODESLAT OPRAVU
                </button>

            </form>

            <a class="zpet" href="/hlavni">
                ← Zpět
            </a>

        </div>


        <script>

            function diktovat(id, tlacitko) {{

                const pole = document.getElementById(id);

                const stav = document.getElementById("stav-" + id);


                const SpeechRecognition =
                    window.SpeechRecognition ||
                    window.webkitSpeechRecognition;


                if (!SpeechRecognition) {{

                    stav.innerHTML =
                        "⚠️ Tento prohlížeč hlasové diktování nepodporuje.";

                    return;
                }}


                const recognition = new SpeechRecognition();

                recognition.lang = "cs-CZ";

                recognition.interimResults = true;

                recognition.continuous = false;


                tlacitko.classList.add("posloucham");

                tlacitko.innerHTML = "🔴 POSLOUCHÁM...";

                stav.innerHTML = "Mluvte...";


                let puvodniText = pole.value;


                recognition.onresult = function(event) {{

                    let text = "";

                    for (
                        let i = event.resultIndex;
                        i < event.results.length;
                        i++
                    ) {{

                        text += event.results[i][0].transcript;

                    }}


                    if (puvodniText.trim() !== "") {{

                        pole.value =
                            puvodniText.trim() + " " + text;

                    }} else {{

                        pole.value = text;

                    }}

                }};


                recognition.onerror = function(event) {{

                    stav.innerHTML =
                        "⚠️ Nepodařilo se použít mikrofon: "
                        + event.error;

                }};


                recognition.onend = function() {{

                    tlacitko.classList.remove("posloucham");

                    tlacitko.innerHTML =
                        "🎤 DIKTOVAT ZNOVU";

                    if (pole.value.trim() !== "") {{

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
# ZOBRAZENÍ ULOŽENÝCH FOTOGRAFIÍ
# ============================================================

@app.route("/fotografie/<path:nazev>")
def fotografie(nazev):

    if "uzivatel" not in session:
        return redirect(url_for("prihlaseni"))

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        nazev
    )


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

if __name__ == "__main__":
    app.run(debug=True)
