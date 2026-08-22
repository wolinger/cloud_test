import requests
import json
import os


API_URL = "https://api.github.com/repos/wolinger/cloud_test/contents/cloud/cache/images?ref=master"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

JSON_DIR = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "json")
)

os.makedirs(JSON_DIR, exist_ok=True)

JSON_PATH = os.path.join(JSON_DIR, "images.json")


# =========================================================
# BUSCA ARQUIVOS NO GITHUB
# =========================================================

response = requests.get(API_URL)
response.raise_for_status()

arquivos = response.json()


# =========================================================
# CATEGORIAS
# =========================================================

expansions = []
logos = []


# =========================================================
# PROCESSA SVGs
# =========================================================

for arquivo in arquivos:
    nome_arquivo = arquivo["name"]

    if arquivo["type"] != "file":
        continue

    if not nome_arquivo.lower().endswith(".svg"):
        continue

    # Remove .svg e troca _ por espaço
    nome = nome_arquivo[:-4].replace("_", " ")

    nome_lower = nome_arquivo.lower()

    # =====================================================
    # LOGOS
    # =====================================================

    if (
        nome_lower.startswith("header")
        or nome_lower.startswith("nexus")
        or nome_lower.startswith("refx")
    ):
        logos.append({
            "name": nome,
            "image": nome_arquivo
        })

    # =====================================================
    # EXPANSÕES
    # =====================================================

    else:
        expansions.append({
            "name": nome,
            "image": nome_arquivo
        })


# =========================================================
# ORDENA
# =========================================================

expansions.sort(
    key=lambda x: x["name"].lower()
)

logos.sort(
    key=lambda x: x["name"].lower()
)


# =========================================================
# SALVA JSON
# =========================================================

data = {
    "expansions": expansions,
    "logos": logos
}

with open(
    JSON_PATH,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        data,
        f,
        ensure_ascii=False,
        indent=2
    )


# =========================================================
# RESULTADO
# =========================================================

print(
    f"Gerado com {len(expansions)} expansões."
)

print(
    f"Gerado com {len(logos)} logos."
)

print(
    f"Salvo em: {JSON_PATH}"
)