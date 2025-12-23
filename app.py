from flask import Flask, render_template, request, jsonify
from simples_script import DeckValidator, ValidacaoResultado, Config
import pandas as pd
import json
from datetime import datetime
import traceback

app = Flask(__name__)

# Configuração global do validador
validator = DeckValidator()


@app.route("/", methods=["GET", "POST"])
def index():
    """Página principal com formulário de validação"""
    if request.method == "POST":
        try:
            deck_url = request.form.get("deck_url", "").strip()
            estirpe = request.form.get("estirpe", "").strip()

            if not deck_url or not estirpe:
                return render_template("index.html",
                                       error="Por favor, preencha todos os campos")

            # Executa validação completa
            resultado = validator.validar_deck_completo(
                deck_url=deck_url,
                estirpe=estirpe,
                caminho_reserved_txt="reserved.txt",
                caminho_gc_txt="gc.txt"
            )

            # Prepara dados para o template
            resumo_data = resultado.resumo_cmc.to_dict(orient="records") if not resultado.resumo_cmc.empty else []

            # Converte DataFrames para listas de dicionários
            faltantes_data = resultado.faltantes_estirpe.to_dict(
                orient="records") if not resultado.faltantes_estirpe.empty else []
            reserved_data = resultado.reserved_hits.to_dict(
                orient="records") if not resultado.reserved_hits.empty else []
            gc_data = resultado.gc_hits.to_dict(orient="records") if not resultado.gc_hits.empty else []

            # Status do combo
            combo_status = None
            if resultado.combo_detectado is not None:
                combo_status = "Combos identificado" if resultado.combo_detectado else "Nenhum"

            return render_template(
                "resultado.html",
                deck_nome=resultado.deck_nome,
                estirpe=resultado.estirpe,
                resumo=resumo_data,
                total=resultado.total_pontos,
                legal=resultado.pontos_valido,
                faltantes=faltantes_data,
                combo=combo_status,
                combo_detectado=resultado.combo_detectado,
                reserved=reserved_data,
                gc=gc_data,
                qtd_faltantes=len(faltantes_data),
                qtd_reserved=len(reserved_data),
                qtd_gc=len(gc_data),
                timestamp=resultado.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                mensagens=resultado.mensagens
            )

        except ValueError as e:
            return render_template("index.html", error=f"Erro de validação: {str(e)}")
        except Exception as e:
            app.logger.error(f"Erro inesperado: {str(e)}\n{traceback.format_exc()}")
            return render_template("index.html",
                                   error=f"Erro interno do servidor: {str(e)}")

    return render_template("index.html")


@app.route("/api/validar", methods=["POST"])
def api_validar():
    """API para validação via JSON"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "Nenhum dado fornecido"}), 400

        deck_url = data.get("deck_url", "").strip()
        estirpe = data.get("estirpe", "").strip()

        if not deck_url or not estirpe:
            return jsonify({"error": "deck_url e estirpe são obrigatórios"}), 400

        # Configurações opcionais
        config_data = data.get("config", {})
        if config_data:
            config = Config(
                MIN_POINTS=config_data.get("min_pontos", 40),
                MAX_POINTS=config_data.get("max_pontos", 100)
            )
            validator_local = DeckValidator(config)
        else:
            validator_local = validator

        resultado = validator_local.validar_deck_completo(
            deck_url=deck_url,
            estirpe=estirpe,
            caminho_reserved_txt="reserved.txt",
            caminho_gc_txt="gc.txt"
        )

        return jsonify(resultado.to_dict()), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Erro na API: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/api/carregar-deck", methods=["POST"])
def api_carregar_deck():
    """API para carregar apenas as cartas do deck"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "Nenhum dado fornecido"}), 400

        deck_url = data.get("deck_url", "").strip()
        estirpe = data.get("estirpe", "").strip()

        if not deck_url:
            return jsonify({"error": "deck_url é obrigatório"}), 400

        df = validator.carregar_deck_moxfield(deck_url, estirpe or "Desconhecida")

        # Formata resposta
        cartas = []
        for _, row in df.iterrows():
            cartas.append({
                "nome": row["Nome"],
                "quantidade": int(row["Quantidade"]),
                "tipo": row["Tipo"],
                "cmc": float(row["CMC"]),
                "cor_identidade": row["Color_Identity"],
                "preco_usd": row["Preço_USD"],
                "edhrec_rank": row["EDHREC_Rank"],
                "e_commander": bool(row["É_Commander"])
            })

        return jsonify({
            "deck_nome": df.loc[0, "Deck"] if not df.empty else "Desconhecido",
            "estirpe": estirpe,
            "total_cartas": int(df["Quantidade"].sum()),
            "cartas_unicas": len(df),
            "cartas": cartas
        }), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Erro na API carregar-deck: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/api/validar-cmc", methods=["POST"])
def api_validar_cmc():
    """API para validação específica de CMC"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "Nenhum dado fornecido"}), 400

        deck_url = data.get("deck_url", "").strip()
        estirpe = data.get("estirpe", "").strip()

        if not deck_url:
            return jsonify({"error": "deck_url é obrigatório"}), 400

        # Carrega deck
        df = validator.carregar_deck_moxfield(deck_url, estirpe or "Desconhecida")

        # Valida CMC
        resumo_cmc, total_pontos, pontos_valido = validator.validar_cmc(df)

        return jsonify({
            "deck_nome": df.loc[0, "Deck"] if not df.empty else "Desconhecido",
            "resumo": resumo_cmc.to_dict(orient="records"),
            "total_pontos": total_pontos,
            "pontos_valido": pontos_valido,
            "min_pontos": validator.config.MIN_POINTS,
            "max_pontos": validator.config.MAX_POINTS
        }), 200

    except Exception as e:
        app.logger.error(f"Erro na API validar-cmc: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/status")
def status():
    """Endpoint de status da aplicação"""
    return jsonify({
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "timeout": validator.config.TIMEOUT,
            "min_pontos": validator.config.MIN_POINTS,
            "max_pontos": validator.config.MAX_POINTS
        }
    }), 200


# Rotas de compatibilidade (para uso direto das funções antigas)
@app.route("/compatibilidade/validar", methods=["POST"])
def compatibilidade_validar():
    """Rota de compatibilidade com a função rodar_validacoes antiga"""
    try:
        deck_url = request.form.get("deck_url", "").strip()
        estirpe = request.form.get("estirpe", "").strip()

        if not deck_url or not estirpe:
            return jsonify({"error": "Por favor, preencha todos os campos"}), 400

        from simples_script import rodar_validacoes, carregar_deck_moxfield_df

        df = carregar_deck_moxfield_df(deck_url, estirpe)
        resultado = rodar_validacoes(df, "reserved.txt", "gc.txt")

        # Converte DataFrames para listas de dict
        resposta = {
            "resumo": resultado["resumo"].to_dict(orient="records"),
            "total": resultado["total"],
            "legal": resultado["legal"],
            "faltantes_estirpe": resultado["faltantes_estirpe"].to_dict(orient="records"),
            "combo": resultado["combo"],
            "reserved_hits": resultado["reserved_hits"].to_dict(orient="records"),
            "gc_hits": resultado["gc_hits"].to_dict(orient="records")
        }

        return jsonify(resposta), 200

    except Exception as e:
        app.logger.error(f"Erro em compatibilidade_validar: {str(e)}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Configurações do Flask
    app.config['JSON_AS_ASCII'] = False  # Permite caracteres especiais em JSON
    app.config['TEMPLATES_AUTO_RELOAD'] = True

    # Configuração de logging
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Inicia servidor
    app.run(
        host='0.0.0.0',  # Acessível externamente
        port=5000,
        debug=True,
        threaded=True  # Suporta múltiplas requisições simultâneas
    )