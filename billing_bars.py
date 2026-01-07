import os
import uuid
from datetime import date
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt


DATA_PATH = "billing_simple.csv"
DEFAULT_TARGET = 200_000  # 200k€/mois


# -------------------------
# Data layer
# -------------------------
def month_default() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def load_data() -> pd.DataFrame:
    if not os.path.exists(DATA_PATH):
        return pd.DataFrame(columns=["id", "client", "amount", "month", "created_at"])

    df = pd.read_csv(DATA_PATH)

    # Backward compatibility: older CSV may not have "id"
    if "id" not in df.columns:
        df["id"] = [str(uuid.uuid4()) for _ in range(len(df))]

    # Ensure required cols exist
    for col in ["client", "amount", "month", "created_at"]:
        if col not in df.columns:
            df[col] = "" if col != "amount" else 0.0

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["month"] = df["month"].astype(str)
    df["client"] = df["client"].astype(str)

    # Reorder columns
    df = df[["id", "client", "amount", "month", "created_at"]]
    return df


def save_data(df: pd.DataFrame) -> None:
    df.to_csv(DATA_PATH, index=False)


# -------------------------
# Color logic (red -> yellow -> green)
# -------------------------
def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def color_for_value(value: float, target: float, pivot: float = 0.60):
    """
    Returns an RGB tuple (0..1) for matplotlib.
    0..pivot*target -> red->yellow
    pivot..target -> yellow->green
    >= target -> green
    """
    if target <= 0:
        return (0.1, 0.6, 0.4)

    ratio = clamp(value / target, 0.0, 1.0)

    # Anchor colors (nice, readable)
    red = (220/255, 53/255, 69/255)
    yellow = (255/255, 193/255, 7/255)
    green = (25/255, 135/255, 84/255)

    if ratio <= pivot:
        t = ratio / pivot if pivot > 0 else 1
        r = lerp(red[0], yellow[0], t)
        g = lerp(red[1], yellow[1], t)
        b = lerp(red[2], yellow[2], t)
        return (r, g, b)

    t = (ratio - pivot) / (1 - pivot) if (1 - pivot) > 0 else 1
    r = lerp(yellow[0], green[0], t)
    g = lerp(yellow[1], green[1], t)
    b = lerp(yellow[2], green[2], t)
    return (r, g, b)


# -------------------------
# UI
# -------------------------
st.set_page_config(page_title="Billing Bars", layout="centered")
st.title("📊 Facturation mensuelle — Objectif 200k€/mois")

df = load_data()

# Session state
if "edit_id" not in st.session_state:
    st.session_state.edit_id = None

# Controls (mobile-friendly: not in sidebar)
with st.expander("➕ Ajouter une facture", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        client = st.text_input("Nom du client *", placeholder="ex: PETITEFRITURE")
    with c2:
        amount = st.number_input("Montant (€) *", min_value=0.0, value=0.0, step=1000.0)

    month = st.text_input("Mois (YYYY-MM) *", value=month_default())

    add = st.button("Ajouter", type="primary")
    if add:
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

# Settings
with st.expander("⚙️ Paramètres", expanded=False):
    target = st.number_input("Objectif mensuel (€)", min_value=1.0, value=float(DEFAULT_TARGET), step=10_000.0)
    show_entries = st.checkbox("Afficher / modifier les factures", value=True)
    show_raw_table = st.checkbox("Afficher tableau brut (debug)", value=False)

with st.expander("🧨 Danger zone", expanded=False):
    if st.button("Réinitialiser (supprime toutes les données)", type="secondary"):
        if os.path.exists(DATA_PATH):
            os.remove(DATA_PATH)
        df = load_data()
        st.session_state.edit_id = None
        st.warning("Données supprimées.")
        st.rerun()

# If no data
if df.empty:
    st.info("Ajoute une facture pour voir les barres mensuelles.")
    st.stop()

# Aggregate per month
monthly = df.groupby("month", as_index=False)["amount"].sum().rename(columns={"amount": "total"})
monthly = monthly.sort_values("month")

# KPIs
latest_month = monthly.iloc[-1]["month"]
latest_total = float(monthly.iloc[-1]["total"])
col1, col2, col3 = st.columns(3)
col1.metric("Dernier mois", latest_month)
col2.metric("Facturation du mois", f"{latest_total:,.0f} €")
col3.metric("Écart vs objectif", f"{latest_total - float(target):,.0f} €")

st.subheader("Barres mensuelles (couleur progressive vers l’objectif)")

# Matplotlib chart (very mobile-safe)
fig, ax = plt.subplots(figsize=(7, 4.2), dpi=140)

colors = [color_for_value(v, float(target)) for v in monthly["total"].tolist()]
ax.bar(monthly["month"].tolist(), monthly["total"].tolist(), color=colors)

ax.axhline(float(target), linestyle="--", linewidth=1)
ax.set_ylabel("Facturation (€)")
ax.set_xlabel("Mois (YYYY-MM)")
ax.tick_params(axis="x", rotation=35)

# Add value labels (lightweight)
for x, v in zip(monthly["month"].tolist(), monthly["total"].tolist()):
    ax.text(x, v, f"{v:,.0f}€", ha="center", va="bottom", fontsize=8, rotation=0)

fig.tight_layout()
st.pyplot(fig, clear_figure=True)

# Overdue / heat explanation (simple)
st.caption("Couleur: rouge (faible) → jaune (moyen) → vert (objectif atteint à 200k€).")

st.divider()

# Entries management (mobile-friendly cards)
if show_entries:
    st.subheader("Factures enregistrées (modifier / supprimer)")

    df_view = df.sort_values(["month", "created_at"], ascending=[False, False]).reset_index(drop=True)

    for _, row in df_view.iterrows():
        rid = row["id"]
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

# Raw table (optional)
if show_raw_table:
    st.subheader("Tableau brut (debug)")
    st.dataframe(df, use_container_width=True)

# Export
st.download_button(
    "⬇️ Télécharger le CSV",
    data=df.to_csv(index=False).encode("utf-8"),
    file_name="billing_simple_export.csv",
    mime="text/csv",
)
