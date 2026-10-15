import sqlite3
import unicodedata
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="MacroFit Proxy & Cache API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "alimentos_cache.db"

def remover_acentos(texto: str) -> str:
    """Remove acentos, cedilhas e caracteres especiais para busca insensível."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize('NFKD', texto)
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                nome_limpo TEXT NOT NULL,
                marca TEXT,
                marca_limpa TEXT,
                calorias REAL DEFAULT 0,
                proteinas REAL DEFAULT 0,
                carboidratos REAL DEFAULT 0,
                gorduras REAL DEFAULT 0,
                fonte TEXT DEFAULT 'CACHE'
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nome_limpo ON alimentos(nome_limpo);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_marca_limpa ON alimentos(marca_limpa);")
        conn.commit()

init_db()

@app.get("/")
def home():
    return {"status": "ok", "mensagem": "MacroFit API Brasil ativa e sem diferenciação de acento"}

@app.get("/api/alimentos")
async def buscar_alimentos(q: str = Query(..., min_length=2, description="Nome do produto ou marca")):
    # Normaliza a busca do usuário (remove acentos e põe em minúsculas)
    termo_limpo = remover_acentos(q)
    palavras = termo_limpo.split()
    resultados_cache = []

    # 1. Procura no banco local SQLite comparando campos sem acento
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        filtros = " AND ".join(["(nome_limpo LIKE ? OR marca_limpa LIKE ?)"] * len(palavras))
        parametros = []
        for p in palavras:
            parametros.extend([f"%{p}%", f"%{p}%"])

        cursor.execute(f"""
            SELECT nome, marca, calorias, proteinas, carboidratos, gorduras, fonte 
            FROM alimentos 
            WHERE {filtros}
            LIMIT 50
        """, parametros)

        for r in cursor.fetchall():
            resultados_cache.append(dict(r))

    # Se já encontrou um catálogo satisfatório no cache, entrega de imediato
    if len(resultados_cache) >= 12:
        return {"origem": "local_cache", "total": len(resultados_cache), "itens": resultados_cache}

    # 2. Busca na API do Open Food Facts focada no mercado brasileiro
    headers = {
        "User-Agent": "MacroFitProApp/2.0 (contato@macrofit.com.br)"
    }

    url = (
        f"https://world.openfoodfacts.org/cgi/search.pl"
        f"?search_terms={termo_limpo}"
        f"&search_simple=1"
        f"&action=process"
        f"&json=1"
        f"&tagtype_0=countries&tag_contains_0=contains&tag_0=brazil"
        f"&page_size=60"
        f"&fields=product_name,product_name_pt,brands,countries_tags,nutriments"
    )

    novos_itens = []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                produtos = data.get("products", [])

                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    for p in produtos:
                        nome = p.get("product_name_pt") or p.get("product_name")
                        if not nome or len(nome.strip()) < 2:
                            continue

                        paises = p.get("countries_tags", [])
                        eh_do_brasil = any("brazil" in str(c).lower() or "brasil" in str(c).lower() for c in paises)
                        if not eh_do_brasil and not p.get("product_name_pt"):
                            continue

                        marca = p.get("brands") or "Genérico"
                        nutri = p.get("nutriments", {})

                        kcal = float(
                            nutri.get("energy-kcal_100g") or 
                            nutri.get("energy-kcal_value") or 
                            nutri.get("energy-kcal") or 0
                        )
                        prot = float(nutri.get("proteins_100g") or nutri.get("proteins_value") or 0)
                        carb = float(nutri.get("carbohydrates_100g") or nutri.get("carbohydrates_value") or 0)
                        fat = float(nutri.get("fat_100g") or nutri.get("fat_value") or 0)

                        if kcal == 0 and prot == 0 and carb == 0 and fat == 0 and "agua" not in remover_acentos(nome):
                            continue

                        nome_limpo = remover_acentos(nome)
                        marca_limpa = remover_acentos(marca)

                        cursor.execute("SELECT id FROM alimentos WHERE nome_limpo = ? AND marca_limpa = ?", (nome_limpo, marca_limpa))
                        if not cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO alimentos (nome, nome_limpo, marca, marca_limpa, calorias, proteinas, carboidratos, gorduras, fonte)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'BRASIL')
                            """, (nome.strip(), nome_limpo, marca.strip(), marca_limpa, round(kcal, 1), round(prot, 1), round(carb, 1), round(fat, 1)))
                            conn.commit()

                        novos_itens.append({
                            "nome": nome.strip(),
                            "marca": marca.strip(),
                            "calorias": round(kcal, 1),
                            "proteinas": round(prot, 1),
                            "carboidratos": round(carb, 1),
                            "gorduras": round(fat, 1),
                            "fonte": "BRASIL"
                        })
    except Exception as e:
        print(f"Aviso na busca externa: {e}")

    # Mescla resultados locais e novos sem duplicados
    nomes_vistos = set()
    lista_final = []
    for item in resultados_cache + novos_itens:
        chave = (remover_acentos(item["nome"]), remover_acentos(item.get("marca", "")))
        if chave not in nomes_vistos:
            nomes_vistos.add(chave)
            lista_final.append(item)

    return {"origem": "busca_sem_acento", "total": len(lista_final), "itens": lista_final}
