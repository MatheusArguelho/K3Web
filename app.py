from flask import Flask, render_template, request
from simples_script import (
    carregar_deck_moxfield_df,
    validar_deck_por_cmc_df,
    verificar_string_em_creatures_df,
    verificar_combo_commanderspellbook_df,
    verificar_reserved_list_df,
    verificar_gc_df
)

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        deck_url = request.form["deck_url"]
        estirpe = request.form["estirpe"]

        df = carregar_deck_moxfield_df(deck_url, estirpe)

        # CMC
        resumo, total, legal = validar_deck_por_cmc_df(df)

        # Estirpe
        faltantes_estirpe = verificar_string_em_creatures_df(df, estirpe)

        # Combos
        combo = verificar_combo_commanderspellbook_df(df)

        # Reserved / GC
        reserved = verificar_reserved_list_df(df, "reserved.txt")
        gc = verificar_gc_df(df, "gc.txt")

        return render_template(
            "resultado.html",
            resumo=resumo.to_dict(orient="records"),
            total=total,
            legal=legal,
            faltantes=faltantes_estirpe.to_dict(orient="records"),
            combo=combo,
            reserved=reserved.to_dict(orient="records"),
            gc=gc.to_dict(orient="records"),
        )

    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
