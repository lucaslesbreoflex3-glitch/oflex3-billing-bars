import os
from datetime import date
import pandas as pd
import streamlit as st
import altair as alt

DATA_PATH = "billing_simple.csv"
TARGET = 200_000  # 200k€/mois


# -------------------------
# Helpers
# -------------------------
def load_data() -> pd.DataFrame:
    if not os.path.exists(DATA_PATH):
        return pd.DataFrame(columns=["client", "amount", "month", "created_at"])
    df = pd.read_csv(DATA_PATH)
    # basic cleanup
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["month"] = df["month"].astype(str)
    return df


def save_data(df: pd.DataFrame) -> None:
    df.to_csv(DATA_PATH, index=False)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(r), int(g), int(b))


def color_for_value(value: float, target: float = TARGET) -> str:
    """
    Gradient:
      0 .. 60% of target  : red -> yellow
      60% .. 100% target : yellow -> green
      >= 100% target     : green
    This matches your examples: 10k red, 120k yellow-ish, 200k green.
    """
    ratio = value / target if target > 0 else 0
    ratio = clamp(ratio, 0, 1)

    # Define anchor colors
    red = (220, 53, 69)     # nice red
    yellow = (255, 193, 7)  # warning yellow
    green = (25, 135, 84)   # success green

    pivot = 0.60  # 60% of target becomes clearly "yellow zone"

    if ratio <= pivot:
        t = ratio / pivot  # 0..1
        r = lerp(red[0], yellow[0], t)
        g = lerp(red[1], yellow[1], t)
        b = lerp(red[2], yellow[2], t)
        return rgb_to_hex(r, g, b)

    # pivot..1: yellow -> green
    t = (ratio - pivot) / (1 - pivot)
    r = lerp(yellow[0], green[0], t)
    g = lerp(yellow[1], green[1], t)
    b = lerp(yellow[2], green[2], t)
    return rgb_to_hex(r, g, b)


def month_default() -> str:
    # YYYY-MM (simple, sortable)
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


# -------------------------
# UI
# -------------------------
st.set_page_config(page_title="Billing Bars", layout="wide")
st.title("📊 Facturation mensuelle – Barres (objectif 200k€/mois)")

df = load_data()

with st.sidebar:
    st.header("➕ Ajouter une facture")
    with st.form("add_invoice", clear_on_submit=True):
        client = st.text_input("Nom du client *", placeholder="ex: PETITEFRITURE")
        amount = st.number_input("Montant facture (€) *", min_value=0.0, value=0.0, step=1000.0)
        month = st.text_input("Mois (YYYY-MM) *", value=month_default())
        submitted = st.form_submit_button("Ajouter")

        if submitted:
            if not client.strip():
                st.error("Le nom du client est obligatoire.")
            elif not month.strip():
                st.error("Le mois est obligatoire.")
            else:
                new_row = {
                    "client": client.strip(),
                    "amount": float(amount),
                    "month": month.strip(),
                    "created_at": pd.Timestamp.utcnow().isoformat(timespec="seconds"),
                }
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                save_data(df)
                st.success("Facture ajoutée ✅")

    st.divider()
    st.header("⚙️ Paramètres")
    target = st.number_input("Objectif mensuel (€)", min_value=1.0, value=float(TARGET), step=10_000.0)
    show_table = st.checkbox("Afficher le tableau des factures", value=False)

    st.divider()
    st.header("🧨 Danger zone")
    if st.button("Réinitialiser (supprime toutes les données)", type="primary"):
        if os.path.exists(DATA_PATH):
            os.remove(DATA_PATH)
        df = load_data()
        st.warning("Données supprimées.")

# Aggregate per month
if df.empty:
    st.info("Ajoute une première facture dans la barre latérale.")
    st.stop()

monthly = (
    df.groupby("month", as_index=False)["amount"]
    .sum()
    .rename(columns={"amount": "total"})
)
monthly = monthly.sort_values("month")

monthly["color"] = monthly["total"].apply(lambda v: color_for_value(v, target))
monthly["pct"] = (monthly["total"] / target).replace([float("inf")], 0).fillna(0) * 100
monthly["label"] = monthly.apply(lambda r: f"{r['total']:,.0f} €  ({r['pct']:.0f}%)", axis=1)

# Chart
st.subheader("Barres mensuelles (couleur progressive vers l’objectif)")

base = alt.Chart(monthly).encode(
    x=alt.X("month:N", sort=None, title="Mois (YYYY-MM)"),
)

bars = base.mark_bar().encode(
    y=alt.Y("total:Q", title="Facturation (€)"),
    color=alt.Color("color:N", scale=None, legend=None),
    tooltip=[
        alt.Tooltip("month:N", title="Mois"),
        alt.Tooltip("total:Q", title="Total (€)", format=",.0f"),
        alt.Tooltip("pct:Q", title="% objectif", format=".0f"),
    ],
)

labels = base.mark_text(dy=-8).encode(
    y=alt.Y("total:Q"),
    text=alt.Text("label:N"),
)

target_line = alt.Chart(pd.DataFrame({"y": [target]})).mark_rule(strokeDash=[6, 6]).encode(
    y="y:Q"
)

chart = (bars + labels + target_line).properties(height=420).interactive()

st.altair_chart(chart, use_container_width=True)

# Quick KPIs
col1, col2, col3 = st.columns(3)
latest_month = monthly.iloc[-1]["month"]
latest_total = float(monthly.iloc[-1]["total"])
col1.metric("Dernier mois", latest_month)
col2.metric("Facturation du mois", f"{latest_total:,.0f} €")
col3.metric("Écart vs objectif", f"{latest_total - float(target):,.0f} €")

if show_table:
    st.subheader("Factures enregistrées (modifier / supprimer)")

    # On garde une copie triée pour l'affichage
    df_view = df.sort_values(["month", "created_at"], ascending=[False, False]).reset_index(drop=True)

    # Stocke l'index de la ligne en cours d'édition (dans la session)
    if "edit_row" not in st.session_state:
        st.session_state.edit_row = None

    # En-têtes
    h1, h2, h3, h4, h5, h6 = st.columns([3, 2, 2, 3, 1, 1])
    h1.markdown("**Client**")
    h2.markdown("**Montant**")
    h3.markdown("**Mois**")
    h4.markdown("**Créé le**")
    h5.markdown("**Edit**")
    h6.markdown("**Del**")

    st.divider()

    for i, row in df_view.iterrows():
        is_editing = (st.session_state.edit_row == i)

        c1, c2, c3, c4, c5, c6 = st.columns([3, 2, 2, 3, 1, 1])

        if not is_editing:
            c1.write(row["client"])
            c2.write(f'{row["amount"]:,.0f} €')
            c3.write(row["month"])
            c4.write(row["created_at"])

            if c5.button("✏️", key=f"edit_{i}"):
                st.session_state.edit_row = i
                st.experimental_rerun()

            if c6.button("❌", key=f"delete_{i}"):
                # IMPORTANT : df_view est reset_index => on supprime via une clé stable
                # Ici, on identifie la ligne à supprimer via created_at + client + amount + month
                mask = (
                    (df["created_at"] == row["created_at"]) &
                    (df["client"] == row["client"]) &
                    (df["amount"] == row["amount"]) &
                    (df["month"] == row["month"])
                )
                df = df.loc[~mask].copy()
                save_data(df)
                st.success("Ligne supprimée")
                st.session_state.edit_row = None
                st.experimental_rerun()

        else:
            # Mode édition
            new_client = c1.text_input("Client", value=str(row["client"]), key=f"client_{i}")
            new_amount = c2.number_input("Montant (€)", min_value=0.0, value=float(row["amount"]), step=1000.0, key=f"amount_{i}")
            new_month = c3.text_input("Mois (YYYY-MM)", value=str(row["month"]), key=f"month_{i}")
            c4.write(row["created_at"])

            if c5.button("💾", key=f"save_{i}"):
                # Met à jour la ligne dans df (original) via masque unique
                mask = (
                    (df["created_at"] == row["created_at"]) &
                    (df["client"] == row["client"]) &
                    (df["amount"] == row["amount"]) &
                    (df["month"] == row["month"])
                )

                df.loc[mask, "client"] = new_client.strip()
                df.loc[mask, "amount"] = float(new_amount)
                df.loc[mask, "month"] = new_month.strip()

                save_data(df)
                st.success("Modifications enregistrées ✅")
                st.session_state.edit_row = None
                st.experimental_rerun()

            if c6.button("↩️", key=f"cancel_{i}"):
                st.session_state.edit_row = None
                st.experimental_rerun()

    st.download_button(
        "Télécharger le CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="billing_simple_export.csv",
        mime="text/csv",
    )

    st.download_button(
        "Télécharger le CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="billing_simple_export.csv",
        mime="text/csv",
    )
