from __future__ import annotations

from datetime import date, timedelta
import math

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Ashlee's Subaru Ascent Fund",
    page_icon="🚙",
    layout="wide",
)

# ---------- Helpers ----------
def money(value: float) -> str:
    return f"${value:,.0f}"


def monthly_payment(principal: float, annual_rate_pct: float, months: int) -> float:
    if principal <= 0 or months <= 0:
        return 0.0
    monthly_rate = annual_rate_pct / 100 / 12
    if monthly_rate == 0:
        return principal / months
    return principal * (monthly_rate * (1 + monthly_rate) ** months) / (((1 + monthly_rate) ** months) - 1)


def biweekly_dates(first_deposit: date, target_date: date) -> list[date]:
    if first_deposit > target_date:
        return []
    dates = []
    d = first_deposit
    while d <= target_date:
        dates.append(d)
        d += timedelta(days=14)
    return dates


def total_interest(payment: float, months: int, principal: float) -> float:
    return max(0.0, payment * months - principal)


# ---------- Styling ----------
st.markdown(
    """
    <style>
        :root {
            --pink-dark: #5A163A;
            --pink-deep: #7A1F4E;
            --pink: #D9468B;
            --pink-bright: #F062A6;
            --pink-soft: #F9C8DD;
            --blush: #FFF1F7;
            --cream: #FFFDFB;
            --plum: #3E2434;
            --teal: #1E6F74;
        }
        .stApp {
            background: radial-gradient(circle at top right, rgba(240,98,166,.16), transparent 30%), linear-gradient(180deg, #FFF5FA 0%, #FFFDFB 48%, #FCEEF5 100%);
            color: #332831;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #5A163A 0%, #8C2859 52%, #3E2434 100%);
        }
        [data-testid="stSidebar"] * { color: white; }
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] [data-baseweb="select"] > div {
            background: rgba(255,255,255,.11) !important;
            border-color: rgba(255,255,255,.24) !important;
        }
        .hero {
            padding: 2rem 1.8rem;
            border-radius: 26px;
            background: linear-gradient(135deg, #5A163A 0%, #A8326B 55%, #F062A6 100%);
            color: white;
            margin-bottom: 1rem;
            box-shadow: 0 16px 38px rgba(90,22,58,.22);
        }
        .hero-kicker {
            display: inline-block;
            padding: .35rem .7rem;
            border-radius: 999px;
            background: rgba(255,255,255,.16);
            border: 1px solid rgba(255,255,255,.24);
            font-weight: 800;
            font-size: .78rem;
            letter-spacing: .08em;
            text-transform: uppercase;
            margin-bottom: .75rem;
        }
        .hero h1 { margin: 0; font-size: 2.65rem; line-height: 1.03; color: white; }
        .hero p { margin: .65rem 0 0 0; opacity: .94; font-size: 1.02rem; }
        .hero-love { margin-top: .95rem; color: #FFE4F0; font-weight: 800; }
        .metric-card {
            background: rgba(255,255,255,.95);
            border: 1px solid #F0C0D5;
            border-radius: 20px;
            padding: 1rem 1.1rem;
            min-height: 130px;
            box-shadow: 0 8px 22px rgba(90,22,58,.08);
        }
        .metric-label { color: #86566D; font-size: .8rem; font-weight: 800; text-transform: uppercase; letter-spacing: .07em; }
        .metric-value { color: #5A163A; font-size: 2rem; font-weight: 900; margin-top: .25rem; }
        .metric-note { color: #725D68; font-size: .86rem; margin-top: .25rem; }
        h1, h2, h3, h4 { color: #5A163A; }
        [data-testid="stMetricValue"] { color: #5A163A; }
        [data-testid="stMetricDelta"] { color: #1E6F74 !important; }
        div[data-testid="stProgress"] > div > div > div > div { background-color: #D9468B; }
        .good { color: #1E6F74; font-weight: 800; }
        .small-note { color: #725D68; font-size: .85rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- Hero ----------
left, right = st.columns([1.25, 1], vertical_alignment="center")
with left:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">December car goal</div>
            <h1>💗 Ashlee's Subaru Ascent Fund</h1>
            <p>Build the down payment every two weeks and see exactly how each deposit changes the payment before you walk into the dealership.</p>
            <div class="hero-love">Pink dashboard. Sensible SUV. Smarter payment.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with right:
    st.image(
        "https://commons.wikimedia.org/wiki/Special:FilePath/Subaru%20Ascent%20IMG%203632.jpg?width=1200",
        caption="Subaru Ascent • Photo: Alexander Migl / Wikimedia Commons (CC BY-SA 4.0)",
        use_container_width=True,
    )

# ---------- Sidebar inputs ----------
st.sidebar.header("💗 Build the plan")

st.sidebar.subheader("💰 Savings")
current_saved = st.sidebar.number_input("Already saved", min_value=0.0, value=0.0, step=100.0, format="%.0f")
biweekly_amount = st.sidebar.number_input("Deposit every 2 weeks", min_value=0.0, value=300.0, step=25.0, format="%.0f")
first_deposit = st.sidebar.date_input("First deposit date", value=date(2026, 10, 2))
target_date = st.sidebar.date_input("Target purchase date", value=date(2026, 12, 19))

st.sidebar.subheader("🚙 Subaru target")
car_price = st.sidebar.number_input("Negotiated vehicle price", min_value=5000.0, value=21000.0, step=250.0, format="%.0f")
sales_tax_pct = st.sidebar.number_input("Sales tax %", min_value=0.0, max_value=15.0, value=6.0, step=0.1)
fees = st.sidebar.number_input("Title / registration / dealer fees", min_value=0.0, value=500.0, step=50.0, format="%.0f")
trade_credit = st.sidebar.number_input("Trade-in / other credit", min_value=0.0, value=0.0, step=250.0, format="%.0f")

st.sidebar.subheader("💳 Financing")
apr = st.sidebar.number_input("APR %", min_value=0.0, max_value=35.0, value=19.10, step=0.25, help="Starting placeholder based on Experian Q2 2026 average used-auto APR for the 501–600 VantageScore band. Replace this with your actual prequalification APR.")
term_months = st.sidebar.selectbox("Loan term", options=[36, 48, 60, 66, 72, 75, 84], index=4)

# ---------- Calculations ----------
deposit_dates = biweekly_dates(first_deposit, target_date)
num_deposits = len(deposit_dates)
future_deposits = num_deposits * biweekly_amount
saved_by_target = current_saved + future_deposits

sales_tax = car_price * sales_tax_pct / 100
out_the_door = car_price + sales_tax + fees

cash_down = min(saved_by_target, max(0.0, out_the_door - trade_credit))
principal_zero_down = max(0.0, out_the_door - trade_credit)
principal_with_savings = max(0.0, out_the_door - trade_credit - cash_down)

payment_zero = monthly_payment(principal_zero_down, apr, term_months)
payment_saved = monthly_payment(principal_with_savings, apr, term_months)
monthly_savings = payment_zero - payment_saved
interest_zero = total_interest(payment_zero, term_months, principal_zero_down)
interest_saved = total_interest(payment_saved, term_months, principal_with_savings)
interest_reduction = interest_zero - interest_saved

# ---------- Main dashboard ----------
st.subheader("💗 Your December snapshot")
cols = st.columns(4)
metrics = [
    ("Biweekly deposits", f"{num_deposits}", f"{money(biweekly_amount)} every 14 days"),
    ("Saved by target", money(saved_by_target), target_date.strftime("By %b %d, %Y")),
    ("Estimated cash down", money(cash_down), f"{(cash_down / out_the_door * 100) if out_the_door else 0:.1f}% of estimated OTD price"),
    ("Payment reduction", money(monthly_savings), "per month vs. $0 cash down"),
]
for col, (label, value, note) in zip(cols, metrics):
    with col:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>',
            unsafe_allow_html=True,
        )

st.markdown("### 💖 $0 down vs. using the savings fund")
a, b = st.columns(2)
with a:
    st.markdown("#### If you walked in with $0 down")
    st.metric("Amount financed", money(principal_zero_down))
    st.metric("Estimated monthly payment", f"${payment_zero:,.0f}/mo")
    st.metric("Estimated total interest", money(interest_zero))

with b:
    st.markdown("#### If you use the saved down payment")
    st.metric("Amount financed", money(principal_with_savings), delta=f"-{money(cash_down)} borrowed")
    st.metric("Estimated monthly payment", f"${payment_saved:,.0f}/mo", delta=f"-{money(monthly_savings)}/mo")
    st.metric("Estimated total interest", money(interest_saved), delta=f"-{money(interest_reduction)} interest")

st.success(
    f"At the current settings, saving {money(biweekly_amount)} every two weeks gives you about {money(saved_by_target)} by {target_date.strftime('%B %d')}. "
    f"That lowers the estimated payment from about ${payment_zero:,.0f}/month to ${payment_saved:,.0f}/month — roughly {money(monthly_savings)} less each month."
)

# ---------- Savings schedule ----------
st.markdown("### 🌸 Biweekly savings path")
if deposit_dates:
    rows = []
    running = current_saved
    for i, d in enumerate(deposit_dates, start=1):
        running += biweekly_amount
        rows.append({"Deposit #": i, "Date": d, "Deposit": biweekly_amount, "Running savings": running})
    schedule = pd.DataFrame(rows)
    chart_df = schedule.set_index("Date")[["Running savings"]]
    st.line_chart(chart_df)
    with st.expander("See every scheduled deposit"):
        st.dataframe(
            schedule.style.format({"Deposit": "${:,.0f}", "Running savings": "${:,.0f}"}),
            use_container_width=True,
            hide_index=True,
        )
else:
    st.warning("Your first deposit date is after the target purchase date. Move one of those dates to create a savings schedule.")

# ---------- Scenario table ----------
st.markdown("### 💕 What different biweekly deposits would do")
scenario_amounts = sorted(set([100, 150, 200, 250, 300, 400, 500, 600, int(biweekly_amount)]))
scenario_rows = []
for amount in scenario_amounts:
    scenario_saved = current_saved + num_deposits * amount
    scenario_down = min(scenario_saved, max(0.0, out_the_door - trade_credit))
    scenario_principal = max(0.0, out_the_door - trade_credit - scenario_down)
    scenario_payment = monthly_payment(scenario_principal, apr, term_months)
    scenario_rows.append(
        {
            "Every 2 weeks": amount,
            "Saved by target": scenario_saved,
            "Amount financed": scenario_principal,
            "Est. payment": scenario_payment,
            "Monthly improvement": payment_zero - scenario_payment,
        }
    )
scenario_df = pd.DataFrame(scenario_rows)
st.dataframe(
    scenario_df.style.format(
        {
            "Every 2 weeks": "${:,.0f}",
            "Saved by target": "${:,.0f}",
            "Amount financed": "${:,.0f}",
            "Est. payment": "${:,.0f}",
            "Monthly improvement": "${:,.0f}",
        }
    ),
    use_container_width=True,
    hide_index=True,
)

# ---------- Rate sensitivity ----------
st.markdown("### 💳 When you get your real APR, plug it in")
rate_floor = max(0.0, apr - 6)
rate_ceiling = min(35.0, apr + 6)
rate_points = [round(rate_floor + i * (rate_ceiling - rate_floor) / 6, 2) for i in range(7)]
rate_rows = []
for rate in rate_points:
    pmt = monthly_payment(principal_with_savings, rate, term_months)
    rate_rows.append({"APR": rate, "Monthly payment": pmt, "Total interest": total_interest(pmt, term_months, principal_with_savings)})
rate_df = pd.DataFrame(rate_rows)
st.dataframe(
    rate_df.style.format({"APR": "{:.2f}%", "Monthly payment": "${:,.0f}", "Total interest": "${:,.0f}"}),
    use_container_width=True,
    hide_index=True,
)

# ---------- Deal math ----------
st.markdown("### ✨ Deal math")
d1, d2, d3, d4 = st.columns(4)
d1.metric("Vehicle price", money(car_price))
d2.metric("Estimated sales tax", money(sales_tax))
d3.metric("Fees", money(fees))
d4.metric("Estimated out-the-door", money(out_the_door))

st.caption(
    "Planning tool only. Actual APR, taxes, dealer fees, lender requirements, trade-in tax treatment, warranties/add-ons, and final payment can differ. "
    "The 19.10% default APR is only a benchmark for the 501–600 VantageScore tier from Experian Q2 2026; replace it with your actual prequalified rate."
)
