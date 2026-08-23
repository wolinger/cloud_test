import json
import os
import re
import shutil
import sys
import unicodedata
from difflib import SequenceMatcher
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests


# ============================================================
# CONFIG
# ============================================================

REQUEST_TIMEOUT = 30
FUZZY_THRESHOLD = 0.90
FUZZY_MARGIN = 0.05

# URL oficial de cada produto. Usada como fallback quando o
# produto no products.json não tem (ou tem errado) o campo
# "url" — assim o sync funciona mesmo com o JSON incompleto.
DEFAULT_PRODUCT_URLS = {
    "nexus": "https://refx.com/nexus/",
    "rippler": "https://refx.com/rippler/",
    "vanguard": "https://refx.com/vanguard/",
}

PRODUCTS_CANDIDATES = (
    os.path.join("data", "json", "products.json"),
    "products.json",
)

IMAGES_CANDIDATES = (
    os.path.join("data", "json", "images.json"),
    "images.json",
)


# ============================================================
# UTIL
# ============================================================

def find_json_path(cli_value, candidates, label):
    if cli_value:
        path = os.path.abspath(cli_value)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{label} não encontrado: {path}")
        return path

    # Estrutura esperada:
    #
    # reFX Cloud/
    # └── data/
    #     ├── json/
    #     │   ├── products.json
    #     │   └── images.json
    #     └── py/
    #         └── sync_expansion_urls.py
    #
    # Então: pasta do script = data/py
    #        pasta data      = ..
    #        json            = ../json

    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.dirname(script_dir)
    json_dir = os.path.join(data_dir, "json")

    path = os.path.join(json_dir, label)

    if os.path.isfile(path):
        return path

    raise FileNotFoundError(
        f"{label} não encontrado em: {path}"
    )


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=4
        )
        file.write("\n")


def normalize_name(text):
    if not text:
        return ""

    text = str(text).replace("\xa0", " ").strip()

    # A listagem da reFX pode mostrar NEW antes do nome.
    text = re.sub(r"^\s*new\s+", "", text, flags=re.IGNORECASE)

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = text.casefold()
    text = text.replace("&", " and ")
    text = text.replace("+", " plus ")
    text = text.replace("’", "'")
    text = text.replace("`", "'")

    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def product_relative_prefix(product):
    return (
        product.get("expansion_prefix")
        or f'{product.get("name", product.get("id", ""))}/'
    ).replace("\\", "/")


def belongs_to_product(expansion, product):
    source = (
        expansion.get("_source_image")
        or expansion.get("image")
        or ""
    ).replace("\\", "/")

    prefix = product_relative_prefix(product)

    return source.casefold().startswith(prefix.casefold())


# ============================================================
# HTML PARSER
# ============================================================

class ExpansionLinkParser(HTMLParser):
    def __init__(self, base_url, expansion_path_prefix):
        super().__init__(convert_charrefs=True)

        self.base_url = base_url
        self.expansion_path_prefix = expansion_path_prefix.rstrip("/") + "/"

        self.links = []
        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        attrs = dict(attrs)
        href = attrs.get("href")

        if not href:
            return

        absolute_url = urljoin(self.base_url, href)
        parsed = urlparse(absolute_url)

        if parsed.path.startswith(self.expansion_path_prefix):
            self.current_href = absolute_url.split("#", 1)[0].split("?", 1)[0]
            self.current_text = []

    def handle_data(self, data):
        if self.current_href:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self.current_href:
            return

        text = " ".join(
            "".join(self.current_text).replace("\xa0", " ").split()
        )

        if text:
            self.links.append({
                "name": text,
                "url": self.current_href
            })

        self.current_href = None
        self.current_text = []


def get_expansion_path_prefix(product_url):
    """
    https://refx.com/nexus/
        -> /nexus/expansion/
    """
    parsed = urlparse(product_url)
    base_path = parsed.path.rstrip("/")

    return f"{base_path}/expansion/"


def scrape_expansion_links(product_url):
    print(f"\nLendo página: {product_url}")

    response = requests.get(
        product_url,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            )
        }
    )
    response.raise_for_status()

    parser = ExpansionLinkParser(
        product_url,
        get_expansion_path_prefix(product_url)
    )
    parser.feed(response.text)

    by_url = {}

    for item in parser.links:
        url = item["url"]
        name = item["name"].strip()

        current = by_url.get(url)

        if current is None or len(name) < len(current["name"]):
            by_url[url] = {
                "name": name,
                "url": url
            }

    links = list(by_url.values())

    print(f"Links de expansão encontrados no site: {len(links)}")

    return links


# ============================================================
# MATCH
# ============================================================

def build_site_index(site_links):
    exact = {}
    normalized_links = []

    for item in site_links:
        normalized = normalize_name(item["name"])

        if not normalized:
            continue

        exact.setdefault(normalized, []).append(item)

        normalized_links.append({
            "normalized": normalized,
            "name": item["name"],
            "url": item["url"]
        })

    return exact, normalized_links


def find_best_match(expansion_name, exact_index, normalized_links):
    wanted = normalize_name(expansion_name)

    if not wanted:
        return None, "invalid", 0.0

    exact_matches = exact_index.get(wanted, [])

    if len(exact_matches) == 1:
        return exact_matches[0], "exact", 1.0

    scored = []

    for item in normalized_links:
        score = SequenceMatcher(
            None,
            wanted,
            item["normalized"]
        ).ratio()

        scored.append((score, item))

    if not scored:
        return None, "not_found", 0.0

    scored.sort(
        key=lambda pair: pair[0],
        reverse=True
    )

    best_score, best_item = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0

    if (
        best_score >= FUZZY_THRESHOLD
        and (best_score - second_score) >= FUZZY_MARGIN
    ):
        return best_item, "fuzzy", best_score

    return None, "not_found", best_score


# ============================================================
# SYNC
# ============================================================

def sync_product(product, all_expansions):
    product_id = product.get("id", "")
    product_name = product.get("name", product_id)

    # Rippler e Vanguard usam apenas Content Factory.
    # Não coletar expansões e não alterar esses produtos.
    if product_id.casefold() in {"rippler", "vanguard"}:
        print(
            f"\n[{product_name}] mantido sem alterações "
            "(Content Factory)."
        )
        return {
            "matched": 0,
            "unmatched": 0,
            "site_links": 0
        }

    product_url = product.get("url")

    if not product_url:
        product_url = DEFAULT_PRODUCT_URLS.get(
            product_id.casefold()
        )

        if product_url:
            print(
                f"\n[{product_name}] sem campo \"url\" no "
                f"products.json — usando padrão: {product_url}"
            )
            # Já grava de volta no products.json, então da
            # próxima vez isso já vem preenchido.
            product["url"] = product_url

    if not product_url:
        print(
            f"\n[{product_name}] ignorado: "
            'não tem campo "url" no products.json.'
        )
        return {
            "matched": 0,
            "unmatched": 0,
            "site_links": 0
        }

    product_expansions = [
        expansion
        for expansion in all_expansions
        if belongs_to_product(expansion, product)
    ]

    print(
        f"\n[{product_name}] expansões no images.json: "
        f"{len(product_expansions)}"
    )

    site_links = scrape_expansion_links(product_url)
    exact_index, normalized_links = build_site_index(site_links)

    expansion_urls = {}
    unmatched = []
    fuzzy_matches = []

    for expansion in product_expansions:
        expansion_name = expansion.get("name", "").strip()

        if not expansion_name:
            continue

        match, match_type, score = find_best_match(
            expansion_name,
            exact_index,
            normalized_links
        )

        if match:
            expansion_urls[expansion_name] = match["url"]

            if match_type == "fuzzy":
                fuzzy_matches.append({
                    "local": expansion_name,
                    "site": match["name"],
                    "url": match["url"],
                    "score": score
                })
        else:
            unmatched.append({
                "name": expansion_name,
                "best_score": score
            })

    # As URLs ficam no products.json, dentro do produto correto.
    product["expansion_urls"] = dict(
        sorted(
            expansion_urls.items(),
            key=lambda item: normalize_name(item[0])
        )
    )

    print(
        f"[{product_name}] associados: "
        f"{len(expansion_urls)}/{len(product_expansions)}"
    )

    if fuzzy_matches:
        print(f"[{product_name}] matches aproximados:")
        for item in fuzzy_matches:
            print(
                f'  ~ "{item["local"]}" -> "{item["site"]}" '
                f'({item["score"]:.3f})'
            )

    if unmatched:
        print(f"[{product_name}] NÃO encontrados:")
        for item in unmatched:
            print(
                f'  ! {item["name"]} '
                f'(melhor score: {item["best_score"]:.3f})'
            )

    return {
        "matched": len(expansion_urls),
        "unmatched": len(unmatched),
        "site_links": len(site_links)
    }


def main():
    products_arg = sys.argv[1] if len(sys.argv) >= 2 else None
    images_arg = sys.argv[2] if len(sys.argv) >= 3 else None

    products_path = find_json_path(
        products_arg,
        PRODUCTS_CANDIDATES,
        "products.json"
    )

    images_path = find_json_path(
        images_arg,
        IMAGES_CANDIDATES,
        "images.json"
    )

    print(f"products.json: {products_path}")
    print(f"images.json:   {images_path}")

    products_data = load_json(products_path)
    images_data = load_json(images_path)

    products = products_data.get("products", [])
    expansions = images_data.get("expansions", [])

    if not products:
        raise RuntimeError(
            "Nenhum produto encontrado em products.json."
        )

    if not expansions:
        raise RuntimeError(
            "Nenhuma expansão encontrada em images.json."
        )

    total_matched = 0
    total_unmatched = 0

    for product in products:
        result = sync_product(
            product,
            expansions
        )

        total_matched += result["matched"]
        total_unmatched += result["unmatched"]

    backup_path = products_path + ".bak"

    shutil.copy2(
        products_path,
        backup_path
    )

    save_json(
        products_path,
        products_data
    )

    print("\n============================================")
    print("CONCLUÍDO")
    print("============================================")
    print(f"URLs associadas: {total_matched}")
    print(f"Sem correspondência: {total_unmatched}")
    print(f"products.json atualizado: {products_path}")
    print(f"backup: {backup_path}")


if __name__ == "__main__":
    main()
