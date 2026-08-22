import json
import os
import re

from collections import Counter


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# data/py/grabxp.py -> volta até a raiz do projeto
PROJECT_DIR = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "..")
)

# Pasta local que também é enviada para o Git
IMAGES_DIR = os.path.join(
    PROJECT_DIR,
    "cloud",
    "cache",
    "images"
)

JSON_DIR = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "json")
)

os.makedirs(JSON_DIR, exist_ok=True)

JSON_PATH = os.path.join(JSON_DIR, "images.json")


# =========================================================
# VALIDAÇÃO DE COR
# Cinza/branco/preto (mesmo em tons como #ccc, #333 etc) não
# conta como "cor de identidade" — é sombra, contorno ou luz.
# =========================================================

def _cor_e_valida(cor_hex):
    h = cor_hex.lstrip("#")

    if len(h) == 3:
        h = "".join(c * 2 for c in h)

    if len(h) != 6:
        return False

    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return False

    # Diferença entre o canal mais forte e o mais fraco. Em
    # cinza/branco/preto isso é ~0. Uma cor "de verdade" tem
    # saturação, ou seja, essa diferença é maior.
    saturacao = max(r, g, b) - min(r, g, b)

    return saturacao >= 20


def _cor_media(cores_hex):
    validas = [c for c in cores_hex if _cor_e_valida(c)]

    if not validas:
        return None

    total_r = total_g = total_b = 0

    for cor in validas:
        h = cor.lstrip("#")

        if len(h) == 3:
            h = "".join(c * 2 for c in h)

        total_r += int(h[0:2], 16)
        total_g += int(h[2:4], 16)
        total_b += int(h[4:6], 16)

    n = len(validas)

    return "#{:02x}{:02x}{:02x}".format(
        total_r // n,
        total_g // n,
        total_b // n
    )


# =========================================================
# MAPEIA <linearGradient id="x"> -> lista de stop-colors
# =========================================================

def _extrai_gradientes(svg_texto):
    gradientes = {}

    for bloco in re.finditer(
        r'<linearGradient\b[^>]*\bid=["\']([^"\']+)["\'][^>]*>(.*?)</linearGradient>',
        svg_texto,
        re.DOTALL
    ):
        grad_id = bloco.group(1)
        conteudo = bloco.group(2)

        stops = re.findall(
            r'stop-color\s*[:=]\s*["\']?(#[0-9a-fA-F]{3,6})',
            conteudo
        )

        gradientes[grad_id] = [s.lower() for s in stops]

    return gradientes


# =========================================================
# EXTRAI A COR PRINCIPAL DE UM SVG
# =========================================================

def extrai_cor_principal(svg_texto):
    gradientes = _extrai_gradientes(svg_texto)

    # 1) O primeiro <path> do arquivo costuma ser o "corpo" do
    # badge (o hexágono/casca do ícone) — é a cor de identidade
    # de verdade, mesmo quando ela vem de um gradiente.
    primeiro_path = re.search(r'<path\b[^>]*>', svg_texto)

    if primeiro_path:
        fill_match = re.search(
            r'fill\s*=\s*["\']([^"\']+)["\']',
            primeiro_path.group(0)
        )

        if fill_match:
            fill_valor = fill_match.group(1).strip()

            url_match = re.match(r'url\(#([^)]+)\)', fill_valor)

            if url_match:
                cor = _cor_media(
                    gradientes.get(url_match.group(1), [])
                )

                if cor:
                    return cor

            elif fill_valor.startswith("#") and _cor_e_valida(fill_valor):
                return fill_valor.lower()

    # 2) Fallback: junta cores diretas (fill="#...") com a cor
    # média de cada gradiente do arquivo, e usa a que mais se
    # repete. Cobre ícones fora do padrão do passo 1.
    cores_diretas = re.findall(
        r'fill\s*[:=]\s*["\']?(#[0-9a-fA-F]{3,6})',
        svg_texto
    )

    cores_diretas = [c.lower() for c in cores_diretas]

    cores_gradiente = [
        _cor_media(stops)
        for stops in gradientes.values()
    ]

    cores_gradiente = [c for c in cores_gradiente if c]

    todas = [
        c
        for c in (cores_diretas + cores_gradiente)
        if _cor_e_valida(c)
    ]

    if not todas:
        return None

    cor_mais_comum, _ = Counter(todas).most_common(1)[0]

    return cor_mais_comum


def busca_cor_do_svg(caminho_svg):
    if not caminho_svg:
        return None

    try:
        with open(caminho_svg, "r", encoding="utf-8") as f:
            return extrai_cor_principal(f.read())

    except Exception as e:
        print(
            f"Aviso: não deu pra extrair cor de {caminho_svg}: {e}"
        )
        return None

    try:
        resposta = requests.get(download_url, timeout=15)
        resposta.raise_for_status()

        return extrai_cor_principal(resposta.text)

    except Exception as e:
        print(
            f"Aviso: não deu pra extrair cor de {download_url}: {e}"
        )

        return None



# =========================================================
# BUSCA SVGs NA PASTA LOCAL (INCLUSIVE SUBPASTAS)
# =========================================================

def busca_svgs_locais():
    arquivos_encontrados = []

    if not os.path.isdir(IMAGES_DIR):
        raise FileNotFoundError(
            f"Pasta de imagens não encontrada: {IMAGES_DIR}"
        )

    for raiz, _, arquivos in os.walk(IMAGES_DIR):
        for nome_arquivo in arquivos:
            if not nome_arquivo.lower().endswith(".svg"):
                continue

            caminho_completo = os.path.join(raiz, nome_arquivo)

            caminho_relativo = os.path.relpath(
                caminho_completo,
                IMAGES_DIR
            ).replace("\\", "/")

            arquivos_encontrados.append({
                "name": nome_arquivo,
                "path": caminho_completo,
                "relative_path": caminho_relativo,
            })

    return arquivos_encontrados


arquivos = busca_svgs_locais()


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
    caminho_imagem = arquivo["relative_path"]

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
            "image": caminho_imagem
        })

    # =====================================================
    # EXPANSÕES
    # =====================================================

    else:
        cor = busca_cor_do_svg(
            arquivo["path"]
        )

        item = {
            "name": nome,
            "image": caminho_imagem,
            "color": cor
        }

        expansions.append(item)


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

sem_cor = sum(
    1
    for e in expansions
    if not e["color"]
)

print(
    f"  -> {len(expansions) - sem_cor} com cor detectada, "
    f"{sem_cor} sem cor (caiu no padrão do app)."
)

print(
    f"Gerado com {len(logos)} logos."
)

print(
    f"Salvo em: {JSON_PATH}"
)