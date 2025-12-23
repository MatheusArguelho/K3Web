from urllib.parse import urlparse
from typing import Dict, Any, Optional, Tuple, Set, List
from dataclasses import dataclass
import pandas as pd
from curl_cffi import requests
import json
import os
import logging
import functools
from datetime import datetime

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Config:
    """Configurações globais da aplicação"""
    MOXFIELD_API_BASE: str = "https://api2.moxfield.com/v2/decks/all"
    COMMANDERSPELLBOOK_API: str = "https://backend.commanderspellbook.com/find-my-combos"
    TIMEOUT: int = 30
    IMPERSONATE: str = "chrome110"
    CMC_POINTS: Dict[int, int] = None
    MIN_POINTS: int = 40
    MAX_POINTS: int = 100

    def __post_init__(self):
        if self.CMC_POINTS is None:
            self.CMC_POINTS = {
                0: 5, 1: 5, 2: 4, 3: 3, 4: 2, 5: 1
            }


@dataclass
class ValidacaoResultado:
    """Resultado da validação completa de um deck"""
    deck_nome: str
    estirpe: str
    resumo_cmc: pd.DataFrame
    total_pontos: float
    pontos_valido: bool
    faltantes_estirpe: pd.DataFrame
    combo_detectado: Optional[bool]
    reserved_hits: pd.DataFrame
    gc_hits: pd.DataFrame
    timestamp: datetime
    mensagens: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Converte resultado para dicionário"""
        return {
            'deck_nome': self.deck_nome,
            'estirpe': self.estirpe,
            'total_pontos': self.total_pontos,
            'pontos_valido': self.pontos_valido,
            'combo_detectado': self.combo_detectado,
            'qtd_faltantes_estirpe': len(self.faltantes_estirpe),
            'qtd_reserved': len(self.reserved_hits),
            'qtd_gc': len(self.gc_hits),
            'resumo_cmc': self.resumo_cmc.to_dict('records'),
            'timestamp': self.timestamp.isoformat(),
            'mensagens': self.mensagens
        }


class DeckValidator:
    """Validador principal de decks EDH"""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self._cache_listas = {}
        logger.info(f"DeckValidator inicializado com timeout: {self.config.TIMEOUT}s")

    def _fazer_requisicao(self, url: str, method: str = "GET",
                          data: Optional[Dict] = None,
                          headers: Optional[Dict] = None,
                          **kwargs) -> requests.Response:
        """Faz requisições HTTP com tratamento de erros"""
        try:
            request_kwargs = {
                'timeout': self.config.TIMEOUT,
                'impersonate': self.config.IMPERSONATE,
                **kwargs
            }

            if method.upper() == "GET":
                response = requests.get(url, **request_kwargs)
            elif method.upper() == "POST":
                if data:
                    request_kwargs['json'] = data
                if headers:
                    request_kwargs['headers'] = headers
                response = requests.post(url, **request_kwargs)
            else:
                raise ValueError(f"Método {method} não suportado")

            response.raise_for_status()
            logger.debug(f"Requisição para {url} bem sucedida")
            return response

        except requests.exceptions.Timeout:
            logger.error(f"Timeout ao acessar {url}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro na requisição para {url}: {e}")
            raise

    def carregar_deck_moxfield(self, deck_url: str, estirpe: str) -> pd.DataFrame:
        """
        Carrega deck do Moxfield e retorna DataFrame

        Args:
            deck_url: URL completa do deck no Moxfield
            estirpe: Estirpe do deck (ex: "Elf", "Dragon")

        Returns:
            DataFrame com cartas do deck
        """
        try:
            # Validação da URL
            parsed = urlparse(deck_url)
            if not parsed.netloc or not parsed.path:
                raise ValueError("URL inválida ou malformada")

            # Extrai ID do deck
            path_parts = parsed.path.strip('/').split('/')
            if not path_parts:
                raise ValueError("URL não contém ID do deck")

            deck_id = path_parts[-1]
            estirpe_safe = estirpe.strip().replace(" ", "_")
            deck_name = f"{estirpe_safe}_{deck_id}"

            logger.info(f"Carregando deck: {deck_name}")

            # Requisição à API
            api_url = f"{self.config.MOXFIELD_API_BASE}/{deck_id}"
            response = self._fazer_requisicao(api_url)
            data = response.json()

            linhas = []

            # Processa mainboard
            for entry in data.get("mainboard", {}).values():
                card = entry.get("card", {})
                prices = card.get("prices", {})

                linhas.append({
                    "Deck": deck_name,
                    "Estirpe": estirpe,
                    "Quantidade": entry.get("quantity", 1),
                    "Nome": card.get("name", ""),
                    "Tipo": card.get("type_line", ""),
                    "CMC": float(card.get("cmc", 0)),
                    "Color_Identity": ",".join(card.get("color_identity", [])),
                    "Preço_USD": prices.get("usd"),
                    "EDHREC_Rank": card.get("edhrec_rank"),
                    "Oracle_Text": card.get("oracle_text", ""),
                    "É_Commander": False
                })

            # Processa commander
            commander = data.get("main")
            if commander:
                prices = commander.get("prices", {})
                linhas.append({
                    "Deck": deck_name,
                    "Estirpe": estirpe,
                    "Quantidade": 1,
                    "Nome": commander.get("name", ""),
                    "Tipo": commander.get("type_line", ""),
                    "CMC": float(commander.get("cmc", 0)),
                    "Color_Identity": ",".join(commander.get("color_identity", [])),
                    "Preço_USD": prices.get("usd"),
                    "EDHREC_Rank": commander.get("edhrec_rank"),
                    "Oracle_Text": commander.get("oracle_text", ""),
                    "É_Commander": True
                })

            if not linhas:
                raise ValueError("Nenhuma carta encontrada no deck")

            df = pd.DataFrame(linhas)
            logger.info(f"Deck carregado: {len(df)} cartas (comandante: {'Sim' if df['É_Commander'].any() else 'Não'})")
            return df

        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar JSON da API: {e}")
            raise ValueError(f"Resposta inválida da API: {e}")
        except KeyError as e:
            logger.error(f"Campo faltante na resposta da API: {e}")
            raise ValueError(f"Formato inesperado da API: campo {e} não encontrado")

    @functools.lru_cache(maxsize=2)
    def _carregar_lista_txt_cached(self, caminho_txt: str) -> Set[str]:
        """Carrega lista de arquivo TXT com cache"""
        try:
            caminho_abs = os.path.abspath(caminho_txt)
            if not os.path.exists(caminho_abs):
                logger.warning(f"Arquivo não encontrado: {caminho_abs}")
                return set()

            with open(caminho_abs, 'r', encoding='utf-8') as f:
                return {linha.strip().lower() for linha in f if linha.strip()}

        except Exception as e:
            logger.error(f"Erro ao carregar arquivo {caminho_txt}: {e}")
            return set()

    def validar_cmc(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, float, bool]:
        """
        Valida distribuição de CMC do deck

        Args:
            df: DataFrame do deck

        Returns:
            Tuple com (resumo, total_pontos, pontos_valido)
        """
        # Filtra criaturas (exclui comandante da contagem)
        df_creatures = df[
            df['Tipo'].str.contains('Creature', na=False) &
            ~df['É_Commander']
            ].copy()

        if df_creatures.empty:
            logger.warning("Nenhuma criatura encontrada no deck (excluindo comandante)")
            return pd.DataFrame(), 0.0, False

        # Calcula pontos baseados no CMC
        def cmc_to_points(cmc: float) -> int:
            cmc_int = int(cmc)
            if cmc_int in self.config.CMC_POINTS:
                return self.config.CMC_POINTS[cmc_int]
            return 0

        df_creatures['Pontos'] = df_creatures['CMC'].apply(cmc_to_points)
        df_creatures['Pontos_Totais'] = df_creatures['Quantidade'] * df_creatures['Pontos']

        # Cria resumo por CMC
        df_creatures['CMC_Categoria'] = df_creatures['CMC'].apply(
            lambda x: str(int(x)) if x < 6 else "6+"
        )

        resumo = df_creatures.groupby('CMC_Categoria').agg(
            Quantidade=('Quantidade', 'sum'),
            Pontos_Totais=('Pontos_Totais', 'sum'),
            Cartas_Unicas=('Nome', 'nunique')
        ).reset_index()

        resumo = resumo.rename(columns={'CMC_Categoria': 'CMC'})
        total_pontos = df_creatures['Pontos_Totais'].sum()
        pontos_valido = self.config.MIN_POINTS <= total_pontos <= self.config.MAX_POINTS

        logger.info(f"Validação CMC: {total_pontos} pontos ({'VÁLIDO' if pontos_valido else 'INVÁLIDO'})")

        return resumo, total_pontos, pontos_valido

    def verificar_estirpe_em_criaturas(self, df: pd.DataFrame, termo: str) -> pd.DataFrame:
        """
        Verifica se criaturas contêm termo da estirpe no tipo ou texto

        Args:
            df: DataFrame do deck
            termo: Termo a verificar

        Returns:
            DataFrame com criaturas que NÃO contêm o termo
        """
        if df.empty:
            return pd.DataFrame()

        # Filtra criaturas (exclui comandante)
        df_creatures = df[
            df['Tipo'].str.contains('Creature', na=False) &
            ~df['É_Commander']
            ].copy()

        if df_creatures.empty:
            return pd.DataFrame()

        # Remove cartas com '/' no nome (cartas duplas)
        df_valid = df_creatures[~df_creatures['Nome'].str.contains('/', na=False)]

        termo_lower = termo.lower()

        # Cria máscara para cartas que CONTÊM o termo
        mask = (
                df_valid['Tipo'].str.lower().str.contains(termo_lower, na=False) |
                df_valid['Oracle_Text'].str.lower().str.contains(termo_lower, na=False)
        )

        # Retorna cartas que NÃO contêm o termo
        faltantes = df_valid[~mask][['Nome', 'Tipo']].copy()

        if not faltantes.empty:
            logger.info(f"{len(faltantes)} criaturas não contêm estirpe '{termo}'")

        return faltantes

    def verificar_combo_commanderspellbook(self, df: pd.DataFrame) -> Optional[bool]:
        """
        Verifica combos no Commander Spellbook

        Args:
            df: DataFrame do deck

        Returns:
            bool: True se encontrou combos simples (1-2 combos), False se mais, None se erro
        """
        if df.empty or len(df) < 2:
            return None

        # Obtém lista de cartas (comandante no final)
        cartas = df['Nome'].tolist()

        # Separa comandante do restante
        commander_card = cartas[-1] if len(cartas) > 0 else None
        main_cards = cartas[:-1] if commander_card else cartas

        if not commander_card or not main_cards:
            return None

        payload = {
            "main": [{"card": c, "quantity": 1} for c in main_cards],
            "commanders": [{"card": commander_card, "quantity": 1}]
        }

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "X-CSRFTOKEN": os.getenv("COMMANDERSPELLBOOK_CSRF", "default_token")
        }

        try:
            logger.debug("Verificando combos no Commander Spellbook...")
            response = self._fazer_requisicao(
                self.config.COMMANDERSPELLBOOK_API,
                method="POST",
                data=payload,
                headers=headers
            )

            data = response.json()
            included = data.get("results", {}).get("included", [])

            total_combos = 0
            for obj in included:
                id_str = obj.get("id", "")
                if id_str:
                    total_combos += len(id_str.split("-"))

            if total_combos == 0:
                logger.info("Nenhum combo encontrado")
                return False
            elif total_combos <= 2:
                logger.info(f"{total_combos} combos simples encontrados")
                return True
            else:
                logger.info(f"{total_combos} combos encontrados (acima do limite)")
                return False

        except Exception as e:
            logger.warning(f"Erro ao verificar combos: {e}")
            return None

    def verificar_reserved_list(self, df: pd.DataFrame, caminho_txt: str) -> pd.DataFrame:
        """
        Verifica cartas da Reserved List

        Args:
            df: DataFrame do deck
            caminho_txt: Caminho para arquivo com reserved list

        Returns:
            DataFrame com cartas encontradas
        """
        reserved_set = self._carregar_lista_txt_cached(caminho_txt)

        if not reserved_set:
            return pd.DataFrame()

        mask = df['Nome'].str.lower().isin(reserved_set)
        hits = df.loc[mask, ['Nome', 'Quantidade']].copy()

        if not hits.empty:
            logger.info(f"Encontradas {len(hits)} cartas da Reserved List")

        return hits

    def verificar_gc(self, df: pd.DataFrame, caminho_txt: str) -> pd.DataFrame:
        """
        Verifica cartas consideradas 'Game Changer' (GC)

        Args:
            df: DataFrame do deck
            caminho_txt: Caminho para arquivo com lista GC

        Returns:
            DataFrame com cartas encontradas
        """
        gc_set = self._carregar_lista_txt_cached(caminho_txt)

        if not gc_set:
            return pd.DataFrame()

        mask = df['Nome'].str.lower().isin(gc_set)
        hits = df.loc[mask, ['Nome', 'Quantidade']].copy()

        if not hits.empty:
            logger.info(f"Encontradas {len(hits)} Game Changers")

        return hits

    def validar_deck_completo(self, deck_url: str, estirpe: str,
                              caminho_reserved_txt: str = "reserved.txt",
                              caminho_gc_txt: str = "gc.txt") -> ValidacaoResultado:
        """
        Validação completa de um deck EDH

        Args:
            deck_url: URL do deck no Moxfield
            estirpe: Estirpe do deck
            caminho_reserved_txt: Caminho para arquivo com reserved list
            caminho_gc_txt: Caminho para arquivo com Game Changer

        Returns:
            ValidacaoResultado com todos os resultados
        """
        mensagens = []
        timestamp = datetime.now()

        try:
            # 1. Carrega deck
            df = self.carregar_deck_moxfield(deck_url, estirpe)
            deck_nome = df.loc[0, 'Deck'] if not df.empty else "Desconhecido"

            mensagens.append(f"Deck carregado com sucesso: {deck_nome}")

            # 2. Valida CMC
            resumo_cmc, total_pontos, pontos_valido = self.validar_cmc(df)

            if pontos_valido:
                mensagens.append(f"Pontos CMC válidos: {total_pontos}")
            else:
                mensagens.append(f"Pontos CMC fora do range: {total_pontos}")

            # 3. Verifica estirpe em criaturas
            faltantes_estirpe = self.verificar_estirpe_em_criaturas(df, estirpe)

            if not faltantes_estirpe.empty:
                mensagens.append(f"{len(faltantes_estirpe)} criaturas não contêm estirpe")

            # 4. Verifica combos
            combo_detectado = self.verificar_combo_commanderspellbook(df)

            if combo_detectado is not None:
                mensagens.append(f"Combos: {'Identificado' if combo_detectado else 'Nenhum'}")

            # 5. Verifica Reserved List
            reserved_hits = self.verificar_reserved_list(df, caminho_reserved_txt)

            if not reserved_hits.empty:
                mensagens.append(f"{len(reserved_hits)} cartas da Reserved List")

            # 6. Verifica Game Changer
            gc_hits = self.verificar_gc(df, caminho_gc_txt)

            if not gc_hits.empty:
                mensagens.append(f"{len(gc_hits)} Game Changer")

            # 7. Cria resultado
            resultado = ValidacaoResultado(
                deck_nome=deck_nome,
                estirpe=estirpe,
                resumo_cmc=resumo_cmc,
                total_pontos=total_pontos,
                pontos_valido=pontos_valido,
                faltantes_estirpe=faltantes_estirpe,
                combo_detectado=combo_detectado,
                reserved_hits=reserved_hits,
                gc_hits=gc_hits,
                timestamp=timestamp,
                mensagens=mensagens
            )

            logger.info(f"Validação completa concluída para {deck_nome}")
            return resultado

        except Exception as e:
            logger.error(f"Erro na validação completa: {e}")
            mensagens.append(f"ERRO: {str(e)}")

            return ValidacaoResultado(
                deck_nome="",
                estirpe=estirpe,
                resumo_cmc=pd.DataFrame(),
                total_pontos=0.0,
                pontos_valido=False,
                faltantes_estirpe=pd.DataFrame(),
                combo_detectado=None,
                reserved_hits=pd.DataFrame(),
                gc_hits=pd.DataFrame(),
                timestamp=timestamp,
                mensagens=mensagens
            )


# Funções de conveniência para compatibilidade com código anterior
def carregar_deck_moxfield_df(deck_url: str, estirpe: str) -> pd.DataFrame:
    """Compatibilidade com código anterior"""
    validator = DeckValidator()
    return validator.carregar_deck_moxfield(deck_url, estirpe)


def validar_deck_por_cmc_df(df: pd.DataFrame, min_pontos: int = 40, max_pontos: int = 100) -> Tuple[
    pd.DataFrame, float, bool]:
    """Compatibilidade com código anterior"""
    config = Config(MIN_POINTS=min_pontos, MAX_POINTS=max_pontos)
    validator = DeckValidator(config)
    return validator.validar_cmc(df)


def verificar_string_em_creatures_df(df: pd.DataFrame, termo: str) -> pd.DataFrame:
    """Compatibilidade com código anterior"""
    validator = DeckValidator()
    return validator.verificar_estirpe_em_criaturas(df, termo)


def verificar_combo_commanderspellbook_df(df: pd.DataFrame) -> Optional[bool]:
    """Compatibilidade com código anterior"""
    validator = DeckValidator()
    return validator.verificar_combo_commanderspellbook(df)


def carregar_lista_txt(caminho_txt: str) -> Set[str]:
    """Compatibilidade com código anterior"""
    validator = DeckValidator()
    return validator._carregar_lista_txt_cached(caminho_txt)


def verificar_reserved_list_df(df: pd.DataFrame, caminho_reserved_txt: str) -> pd.DataFrame:
    """Compatibilidade com código anterior"""
    validator = DeckValidator()
    return validator.verificar_reserved_list(df, caminho_reserved_txt)


def verificar_gc_df(df: pd.DataFrame, caminho_gc_txt: str) -> pd.DataFrame:
    """Compatibilidade com código anterior"""
    validator = DeckValidator()
    return validator.verificar_gc(df, caminho_gc_txt)


def rodar_validacoes(df: pd.DataFrame,
                     caminho_reserved_txt: str = "reserved.txt",
                     caminho_gc_txt: str = "gc.txt") -> Dict[str, Any]:
    """Compatibilidade com código anterior"""
    validator = DeckValidator()

    try:
        if df.empty:
            raise ValueError("DataFrame vazio")

        estirpe = df.loc[0, 'Estirpe'] if 'Estirpe' in df.columns else "Desconhecida"

        # Executa validações individuais
        resumo_cmc, total_pontos, pontos_valido = validator.validar_cmc(df)
        faltantes_estirpe = validator.verificar_estirpe_em_criaturas(df, estirpe)
        combo_detectado = validator.verificar_combo_commanderspellbook(df)
        reserved_hits = validator.verificar_reserved_list(df, caminho_reserved_txt)
        gc_hits = validator.verificar_gc(df, caminho_gc_txt)

        return {
            "resumo": resumo_cmc,
            "total": total_pontos,
            "legal": pontos_valido,
            "faltantes_estirpe": faltantes_estirpe,
            "combo": combo_detectado,
            "reserved_hits": reserved_hits,
            "gc_hits": gc_hits,
        }

    except Exception as e:
        logger.error(f"Erro em rodar_validacoes: {e}")
        raise


# Exemplo de uso
if __name__ == "__main__":
    # Configura variável de ambiente para CSRF token
    os.environ["COMMANDERSPELLBOOK_CSRF"] = "1y7f9CHBsBqGSDOmqP555KS2mt4MLVTd1LPulPGEXkxjcuIatZOKbxzKFW7fCnQR"

    # Exemplo de uso básico
    validator = DeckValidator()

    # Validação completa
    resultado = validator.validar_deck_completo(
        deck_url="https://www.moxfield.com/decks/EXEMPLO123",
        estirpe="Elf",
        caminho_reserved_txt="reserved.txt",
        caminho_gc_txt="gc.txt"
    )

    print(f"Deck: {resultado.deck_nome}")
    print(f"Pontos: {resultado.total_pontos} ({'VÁLIDO' if resultado.pontos_valido else 'INVÁLIDO'})")
    print(f"Mensagens: {resultado.mensagens}")

    # Para uso em batch
    decks = [
        ("https://www.moxfield.com/decks/EXEMPLO123", "Elf"),
        ("https://www.moxfield.com/decks/EXEMPLO456", "Dragon"),
    ]

    resultados = []
    for url, estirpe in decks:
        try:
            resultado = validator.validar_deck_completo(url, estirpe)
            resultados.append(resultado)
        except Exception as e:
            print(f"Erro ao processar {estirpe}: {e}")