from urllib.parse import urlparse
import pandas as pd
from curl_cffi import requests
import json


def carregar_deck_moxfield_df(deck_url: str, estirpe: str) -> pd.DataFrame:
    estirpe = estirpe.strip().replace(" ", "_")

    deck_id = urlparse(deck_url).path.split("/")[-1]
    deck_name = f"{estirpe}_{deck_id}"

    api_url = f"https://api2.moxfield.com/v2/decks/all/{deck_id}"

    response = requests.get(api_url, impersonate="chrome110")
    response.raise_for_status()

    data = response.json()
    linhas = []

    for entry in data["mainboard"].values():
        card = entry.get("card", {})
        prices = card.get("prices", {})

        linhas.append({
            "Deck": deck_name,
            "Estirpe": estirpe,
            "Quantidade": entry.get("quantity", 1),
            "Nome": card.get("name"),
            "Tipo": card.get("type_line"),
            "CMC": card.get("cmc"),
            "Color_Identity": ",".join(card.get("color_identity", [])),
            "Preço_USD": prices.get("usd"),
            "EDHREC_Rank": card.get("edhrec_rank"),
            "Oracle_Text": card.get("oracle_text"),
        })

    # Commander (última linha)
    commander = data.get("main")
    if commander:
        prices = commander.get("prices", {})
        linhas.append({
            "Deck": deck_name,
            "Estirpe": estirpe,
            "Quantidade": 1,
            "Nome": commander.get("name"),
            "Tipo": commander.get("type_line"),
            "CMC": commander.get("cmc"),
            "Color_Identity": ",".join(commander.get("color_identity", [])),
            "Preço_USD": prices.get("usd"),
            "EDHREC_Rank": commander.get("edhrec_rank"),
            "Oracle_Text": commander.get("oracle_text"),
        })

    return pd.DataFrame(linhas)


def validar_deck_por_cmc_df(df, min_pontos=40, max_pontos=100):
    df_creature = df[df['Tipo'].str.contains('Creature', na=False)].iloc[:-1].copy()

    def cmc_to_points(cmc):
        if cmc <= 1: return 5
        if cmc == 2: return 4
        if cmc == 3: return 3
        if cmc == 4: return 2
        if cmc == 5: return 1
        return 0

    df_creature['Pontos'] = df_creature['CMC'].apply(cmc_to_points)
    df_creature['Pontos_Totais'] = df_creature['Quantidade'] * df_creature['Pontos']

    resumo = (
        df_creature
        .assign(CMC_Int=lambda x: x['CMC'].apply(lambda v: int(v) if v < 6 else 6))
        .groupby('CMC_Int')
        .agg(Quantidade=('Quantidade', 'sum'),
             Pontos_Totais=('Pontos_Totais', 'sum'))
        .reset_index()
    )

    resumo['CMC_Label'] = resumo['CMC_Int'].apply(lambda x: str(x) if x < 6 else "6+")
    total_pontos = df_creature['Pontos_Totais'].sum()

    return resumo[['CMC_Label', 'Quantidade', 'Pontos_Totais']], total_pontos, 40 <= total_pontos <= 100


def verificar_string_em_creatures_df(df, termo):
    df_creature = df[df['Tipo'].str.startswith('Creature', na=False)].iloc[:-1]
    termo = termo.lower()

    df_valid = df_creature[~df_creature['Nome'].str.contains('/', na=False)]

    mask = (
            df_valid['Tipo'].str.lower().str.contains(termo, na=False) |
            df_valid['Oracle_Text'].str.lower().str.contains(termo, na=False)
    )

    return df_valid.loc[~mask, ['Nome', 'Tipo']]


def verificar_combo_commanderspellbook_df(df):
    if 'Nome' not in df.columns or df.empty:
        return None

    cartas = df['Nome'].tolist()
    if not cartas:
        return None

    main_cards = [{"card": c, "quantity": 1} for c in cartas[:-1]]
    commander_card = [{"card": cartas[-1], "quantity": 1}]

    payload = {
        "main": main_cards,
        "commanders": commander_card
    }

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "X-CSRFTOKEN": "1y7f9CHBsBqGSDOmqP555KS2mt4MLVTd1LPulPGEXkxjcuIatZOKbxzKFW7fCnQR"
    }

    try:
        response = requests.post(
            "https://backend.commanderspellbook.com/find-my-combos",
            headers=headers,
            data=json.dumps(payload),
            impersonate="chrome110",
            timeout=20
        )
        response.raise_for_status()
    except Exception:
        return None

    try:
        data = response.json()
    except Exception:
        return None

    included = data.get("results", {}).get("included", [])

    total_ids = 0
    for obj in included:
        id_str = obj.get("id", "")
        if id_str:
            total_ids += len(id_str.split("-"))

    return 0 < total_ids <= 2

def carregar_lista_txt(caminho_txt):
    with open(caminho_txt, encoding="utf-8") as f:
        return {linha.strip().lower() for linha in f if linha.strip()}

def verificar_reserved_list_df(df, caminho_reserved_txt):
    reserved = carregar_lista_txt(caminho_reserved_txt)

    if 'Nome' not in df.columns:
        return df.iloc[0:0][['Nome']]

    mask = df['Nome'].str.lower().isin(reserved)

    return df.loc[mask, ['Nome']]

def verificar_gc_df(df, caminho_gc_txt):
    gc = carregar_lista_txt(caminho_gc_txt)

    if 'Nome' not in df.columns:
        return df.iloc[0:0][['Nome']]

    mask = df['Nome'].str.lower().isin(gc)

    return df.loc[mask, ['Nome']]



def rodar_validacoes(df, caminho_reserved_txt="reserved.txt", caminho_gc_txt="gc.txt"):
    estirpe = df.loc[0, 'Estirpe']

    # CMC
    resumo, total, legal = validar_deck_por_cmc_df(df)

    # Estirpe
    faltantes_estirpe = verificar_string_em_creatures_df(df, estirpe)

    # Combos
    combo = verificar_combo_commanderspellbook_df(df)

    # Reserved / GC
    reserved_hits = verificar_reserved_list_df(df, caminho_reserved_txt)
    gc_hits = verificar_gc_df(df, caminho_gc_txt)

    return {
        "resumo": resumo,
        "total": total,
        "legal": legal,
        "faltantes_estirpe": faltantes_estirpe,
        "combo": combo,
        "reserved_hits": reserved_hits,
        "gc_hits": gc_hits,
    }


