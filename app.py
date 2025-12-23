from flask import Flask, render_template, request
from simples_script import (
    carregar_deck_moxfield_df,
    validar_deck_por_cmc_df,
    verificar_string_em_creatures_df,
    verificar_combo_commanderspellbook_df
)

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        deck_url = request.form["deck_url"]
        estirpe = request.form["estirpe"]

        df = carregar_deck_moxfield_df(deck_url, estirpe)

        resumo, total, legal = validar_deck_por_cmc_df(df)
        faltantes = verificar_string_em_creatures_df(df, estirpe)
        combo = verificar_combo_commanderspellbook_df(df)

        return render_template(
            "resultado.html",
            resumo=resumo.to_dict(orient="records"),
            total=total,
            legal=legal,
            faltantes=faltantes.to_dict(orient="records"),
            combo=combo
        )


    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)
