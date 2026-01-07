import os
import uuid
from datetime import date
import pandas as pd
import streamlit as st
import altair as alt

DATA_PATH = "billing_simple.csv"
DEFAULT_TARGET = 200_000  # 200k€/mois


# -------------------------
# Helpers
# -------------------------
def month_default() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def save_data(df: pd.DataFrame) -> None:
    # Force stable column order
    df = df[["id", "client", "amount", "month", "created_at"]].copy()
    df.to_csv(DATA_PATH, index=False)


def load_data() -> pd.DataFrame:
    """
    Loads CSV and guarantees every row has a stable string 'id' persisted to disk.
    This is CRITICAL for reliable edit/delete.
    """
    if not os.path.exists(DATA_PATH):
        return pd.DataFrame(columns=["id", "client", "amount", "month", "created_at"])

    df = pd.read_csv(DATA_PATH)

    # Ensure columns exist
    for col in ["id", "client", "amount", "month", "created_at"]:
        if col not in df.columns:
            df[col] = "" if col != "amount" else 0.0

    # Clean types
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["month"] = df["month"].astype(str)
    df["client"] = df["client"].astype(str)
    df["created_at"] = df["created_at"].astype(str)

    # IMPORTANT: stable string IDs
    df["id"] = df["id"].astype(str)

    # Detect missing/invalid ids and persist them
    missing = df["id"].isin(["", "nan", "None"]) | df["id"].isna()
    if missing.any():
        df.loc[missing, "id"] = [str(uuid.uuid4()) for _ in range(int(missing.sum()))]
        save_data(df)

    return df[["id", "client", "amount", "month", "created_at"]]


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(r), int(g), int(b))


def color_for_value(value: float, target: float, pivot: float = 0.60) -> str:
    """
    Gradient:
      0 .. pivot*target  : red -> yellow
      pivot .. target    : yellow -> green
      >= target          : green
    pivot=0.60 makes ~120k look yellow-ish for a 200k target.
    Returns HEX string for Altair (scale=None).
    """
    if target <= 0:
        return "#198754"

    ratio = clamp(value / target, 0.0, 1.0)

    red = (220, 53, 69)
    yellow = (255, 193, 7)
    green = (25, 135, 84)

    if ratio <= pivot:
        t = ratio / pivot if pivot > 0 else 1
        r = lerp(red[0], yellow[0], t)
        g = lerp(red[1], yellow[1], t)
        b = lerp(red[2], yellow[2], t)
        return rgb_to_hex(r, g, b)

    t = (ratio - pivot) / (1 - pivot) if (1 - pivot) > 0 else 1
    r = lerp(yellow[0], green[0], t)
    g = lerp(yellow[1], green[1], t)
    b = lerp(yellow[2], green[2], t)
    return rgb_to_hex(r, g, b)


# -------------------------
# UI
# -------------------------
st.set_page_config(page_title="Billing Bars", layout="wide")
st.title("📊 Facturation mensuelle — objectif 200k€/mois")

df = load_data()

# Session state
if "edit_id" not in st.session_state:
    st.session_state.edit_id = None

# Sidebar: input + settings
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
            elif amount <= 0:
                st.error("Le montant doit être > 0.")
            else:
                new_row = {
                    "id": str(uuid.uuid4()),
                    "client": client.strip(),
                    "amount": float(amount),
                    "month": month.strip(),
                    "created_at": pd.Timestamp.utcnow().isoformat(timespec="seconds"),
                }
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                save_data(df)
                st.success("Facture ajoutée ✅")
                st.rerun()

    st.divider()
    st.header("⚙️ Paramètres")
    target = st.number_input("Objectif mensuel (€)", min_value=1.0, value=float(DEFAULT_TARGET), step=10_000.0)
    show_entries = st.checkbox("Afficher / modifier les factures", value=True)
    show_raw_table = st.checkbox("Afficher tableau brut", value=False)

    st.divider()
    st.header("🧨 Danger zone")
    if st.button("Réinitialiser (supprime toutes les données)", type="primary"):
        if os.path.exists(DATA_PATH):
            os.remove(DATA_PATH)
        df = load_data()
        st.session_state.edit_id = None
        st.warning("Données supprimées.")
        st.rerun()

# Empty state
if df.empty:
    st.info("Ajoute une première facture dans la barre latérale.")
    st.stop()

# Aggregate per month
monthly = (
    df.groupby("month", as_index=False)["amount"]
    .sum()
    .rename(columns={"amount": "total"})
    .sort_values("month")
)

monthly["pct"] = (monthly["total"] / float(target)) * 100
monthly["label"] = monthly.apply(lambda r: f"{r['total']:,.0f} €  ({r['pct']:.0f}%)", axis=1)
monthly["color"] = monthly["total"].apply(lambda v: color_for_value(float(v), float(target)))

# KPIs
col1, col2, col3, col4 = st.columns(4)
total_all_months = float(monthly["total"].sum())
latest_month = monthly.iloc[-1]["month"]
latest_total = float(monthly.iloc[-1]["total"])
gap = latest_total - float(target)

col1.metric("Total (tous mois)", f"{total_all_months:,.0f} €")
col2.metric("Dernier mois", latest_month)
col3.metric("Facturation du mois", f"{latest_total:,.0f} €")
col4.metric("Écart vs objectif (mois)", f"{gap:,.0f} €")

st.subheader("Barres mensuelles (couleur progressive vers l’objectif)")

# Altair chart
base = alt.Chart(monthly).encode(
    x=alt.X("month:N", sort=None, title="Mois (YYYY-MM)")
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

target_line = alt.Chart(pd.DataFrame({"y": [float(target)]})).mark_rule(strokeDash=[6, 6]).encode(
    y="y:Q"
)

chart = (bars + labels + target_line).properties(height=420)
st.altair_chart(chart, use_container_width=True)

st.caption("Couleur: rouge (faible) → jaune (moyen) → vert (objectif atteint à 200k€).")

# Manage entries (edit / delete) - cards
if show_entries:
    st.divider()
    st.subheader("Factures enregistrées (modifier / supprimer)")

    df_view = df.sort_values(["month", "created_at"], ascending=[False, False]).reset_index(drop=True)

    for _, row in df_view.iterrows():
        rid = str(row["id"])  # ensure string
        is_editing = (st.session_state.edit_id == rid)

        with st.container(border=True):
            if not is_editing:
                st.write(f"**Client :** {row['client']}")
                st.write(f"**Montant :** {float(row['amount']):,.0f} €")
                st.write(f"**Mois :** {row['month']}")
                st.caption(f"Créé le : {row['created_at']}")

                b1, b2 = st.columns(2)
                if b1.button("✏️ Modifier", key=f"edit_{rid}"):
                    st.session_state.edit_id = rid
                    st.rerun()

                if b2.button("❌ Supprimer", key=f"del_{rid}"):
                    df["id"] = df["id"].astype(str)
                    df = df[df["id"] != rid].copy()
                    save_data(df)
                    st.session_state.edit_id = None
                    st.success("Ligne supprimée ✅")
                    st.rerun()

            else:
                st.write("### ✏️ Modification")

                new_client = st.text_input("Client", value=str(row["client"]), key=f"c_{rid}")
                new_amount = st.number_input(
                    "Montant (€)",
                    min_value=0.0,
                    value=float(row["amount"]),
                    step=1000.0,
                    key=f"a_{rid}",
                )
                new_month = st.text_input("Mois (YYYY-MM)", value=str(row["month"]), key=f"m_{rid}")

                b1, b2 = st.columns(2)
                if b1.button("💾 Enregistrer", type="primary", key=f"save_{rid}"):
                    df["id"] = df["id"].astype(str)
                    df.loc[df["id"] == rid, "client"] = new_client.strip()
                    df.loc[df["id"] == rid, "amount"] = float(new_amount)
                    df.loc[df["id"] == rid, "month"] = new_month.strip()
                    save_data(df)
                    st.session_state.edit_id = None
                    st.success("Modifications enregistrées ✅")
                    st.rerun()

                if b2.button("↩️ Annuler", key=f"cancel_{rid}"):
                    st.session_state.edit_id = None
                    st.rerun()

if show_raw_table:
    st.divider()
    st.subheader("Tableau brut")
    st.dataframe(df, use_container_width=True)

st.download_button(
    "⬇️ Télécharger le CSV",
    data=df.to_csv(index=False).encode("utf-8"),
    file_name="billing_simple_export.csv",
    mime="text/csv",
)
