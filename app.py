
from flask import Flask, request, redirect, url_for, session, send_from_directory
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import uuid

app = Flask(__name__)
app.secret_key = "docasne-tajne-heslo"

UPLOAD_FOLDER = "fotografie_oprav"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


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

            <hr>

            <a href="/odhlasit">
                <button class="logout">
                    ODHLÁSIT
                </button>
            </a>

        </div>

    </body>

    </html>
    """


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

            <form method="POST">

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