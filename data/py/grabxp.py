import requests
import json
import os

API_URL = "https://api.github.com/repos/wolinger/cloud_test/contents/cloud/cache/images?ref=master"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

JSON_DIR = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "json")
)

os.makedirs(JSON_DIR, exist_ok=True)

JSON_PATH = os.path.join(JSON_DIR, "expansions.json")

response = requests.get(API_URL)
response.raise_for_status()

arquivos = response.json()

expansions = []

for arquivo in arquivos:
    nome_arquivo = arquivo["name"]

    if arquivo["type"] != "file":
        continue

    if not nome_arquivo.lower().endswith(".svg"):
        continue

    # Advent_2017.svg -> Advent 2017
    nome = nome_arquivo[:-4].replace("_", " ")

    expansions.append({
        "name": nome,
        "image": nome_arquivo
    })

expansions.sort(key=lambda x: x["name"].lower())

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(
        {"expansions": expansions},
        f,
        ensure_ascii=False,
        indent=2
    )

print(f"Gerado com {len(expansions)} expansões.")
print(f"Salvo em: {JSON_PATH}")