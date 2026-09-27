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
            --pink: #E74C9B;
            --pink-bright: #FF78B9;
            --pink-soft: #FFD4E8;
            --blush: #FFF1F8;
            --blue: #67C8FF;
            --blue-deep: #277EAE;
            --blue-soft: #DDF4FF;
            --cream: #FFFDFB;
            --plum: #3E2434;
            --teal: #1E6F74;
        }
        .stApp {
            background:
                radial-gradient(circle at 7% 4%, rgba(255,120,185,.22), transparent 24%),
                radial-gradient(circle at 94% 8%, rgba(103,200,255,.24), transparent 26%),
                linear-gradient(180deg, #FFF5FA 0%, #F6FBFF 52%, #FFF0F8 100%);
            color: #332831;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #6B1B49 0%, #C23D82 48%, #277EAE 100%);
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
            background: linear-gradient(135deg, #6B1B49 0%, #E74C9B 56%, #67C8FF 145%);
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

        .whiteboard-title {
            text-align: center;
            font-size: 1.55rem;
            font-weight: 900;
            color: #5A163A;
            margin: .15rem 0 .1rem 0;
        }
        .whiteboard-subtitle {
            text-align: center;
            color: #277EAE;
            font-weight: 750;
            margin-bottom: .45rem;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: #FFFFFF;
            border: 9px solid #D6DCE4 !important;
            border-radius: 22px !important;
            box-shadow: 0 12px 28px rgba(49,74,94,.14), inset 0 0 0 2px #F1F4F7;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:after {
            content: "";
            display: block;
            width: 42%;
            height: 8px;
            border-radius: 999px;
            margin: .45rem auto -.2rem auto;
            background: linear-gradient(90deg, #E74C9B 0 47%, #67C8FF 47% 100%);
            box-shadow: 0 3px 8px rgba(0,0,0,.12);
        }
        .board-note {
            text-align: center;
            color: #6F6170;
            font-size: .85rem;
            margin: .2rem 0 .8rem 0;
        }
        .balance-panel {
            background: linear-gradient(145deg, #FFF8FC 0%, #F1FAFF 100%);
            border: 2px solid #F1B8D6;
            border-radius: 24px;
            padding: 1.1rem;
            box-shadow: 0 10px 25px rgba(83,58,78,.08);
        }
        .balance-ring {
            width: 220px;
            height: 220px;
            margin: .25rem auto .65rem auto;
            border-radius: 50%;
            display: grid;
            place-items: center;
            position: relative;
            box-shadow: 0 10px 25px rgba(103,200,255,.15);
        }
        .balance-ring:before {
            content: "";
            width: 164px;
            height: 164px;
            border-radius: 50%;
            background: white;
            position: absolute;
            box-shadow: inset 0 0 0 1px #F4D7E6;
        }
        .balance-center {
            position: relative;
            z-index: 2;
            text-align: center;
        }
        .balance-number {
            color: #5A163A;
            font-weight: 950;
            font-size: 2.2rem;
            line-height: 1;
        }
        .balance-label {
            color: #786573;
            text-transform: uppercase;
            letter-spacing: .08em;
            font-weight: 800;
            font-size: .72rem;
            margin-top: .45rem;
        }
        .goal-line {
            color: #277EAE;
            text-align: center;
            font-weight: 850;
            margin-top: .35rem;
        }
        .projection-card {
            background: linear-gradient(135deg, #FFE4F1 0%, #E6F6FF 100%);
            border: 1px solid #E5B7D1;
            border-radius: 20px;
            padding: 1rem 1.1rem;
            min-height: 145px;
            box-shadow: 0 8px 22px rgba(86,81,105,.07);
        }
        .projection-big {
            color: #5A163A;
            font-weight: 950;
            font-size: 2rem;
            margin-top: .2rem;
        }
        .blue-chip {
            display: inline-block;
            background: #DDF4FF;
            color: #277EAE;
            border: 1px solid #AEDFFF;
            border-radius: 999px;
            padding: .3rem .65rem;
            font-weight: 800;
            font-size: .8rem;
            margin-top: .45rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- Hero ----------
hero_text, board_col = st.columns([0.92, 1.35], gap="large", vertical_alignment="center")

with hero_text:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">December car goal</div>
            <h1>💗 Ashlee's Subaru Ascent Fund</h1>
            <p>Every deposit moves the goal from “someday” to a real down payment, a lower amount financed, and a payment you can see before dealership day.</p>
            <div class="hero-love">Cotton-candy colors. Real numbers. Her future Ascent. ✨</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with board_col:
    with st.container(border=True):
        st.markdown('<div class="whiteboard-title">🖊️ Visualization Board</div>', unsafe_allow_html=True)
        st.markdown('<div class="whiteboard-subtitle">Ashlee + the goal we are building toward</div>', unsafe_allow_html=True)
        wife_pic, car_pic = st.columns([0.58, 1.0], gap="small", vertical_alignment="center")
        with wife_pic:
            st.image("assets/ashlee.jpg", caption="Ashlee 💗", use_container_width=True)
        with car_pic:
            st.image(
                "https://commons.wikimedia.org/wiki/Special:FilePath/Subaru%20Ascent%20IMG%203632.jpg?width=1200",
                caption="Her future Subaru Ascent 🚙",
                use_container_width=True,
            )
        st.markdown('<div class="board-note">See it. Fund it. Drive it. 💗💙</div>', unsafe_allow_html=True)
# ---------- Sidebar inputs ----------
st.sidebar.header("💗 Build the plan")

st.sidebar.subheader("💰 Savings")
current_saved = st.sidebar.number_input(
    "Current balance right now",
    min_value=0.0,
    value=0.0,
    step=50.0,
    format="%.0f",
    help="Update this when a real deposit hits the car fund. The live balance graphic updates instantly.",
)
down_payment_goal = st.sidebar.number_input(
    "Down payment goal",
    min_value=500.0,
    value=4000.0,
    step=250.0,
    format="%.0f",
)
biweekly_amount = st.sidebar.number_input(
    "Recurring deposit every 2 weeks",
    min_value=0.0,
    value=300.0,
    step=25.0,
    format="%.0f",
)
first_deposit = st.sidebar.date_input("Next / first recurring deposit", value=date(2026, 10, 2))
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

current_progress_pct = 0.0 if down_payment_goal <= 0 else min(100.0, (current_saved / down_payment_goal) * 100)
projected_progress_pct = 0.0 if down_payment_goal <= 0 else min(100.0, (saved_by_target / down_payment_goal) * 100)
remaining_to_goal = max(0.0, down_payment_goal - current_saved)
projected_over_under = saved_by_target - down_payment_goal

# ---------- Live savings status ----------
st.markdown("## 💗💙 Live car-fund balance")
balance_col, projection_col = st.columns([0.95, 1.35], gap="large", vertical_alignment="center")

with balance_col:
    st.markdown(
        f"""
        <div class="balance-panel">
            <div class="metric-label" style="text-align:center;">CURRENT ACTUAL BALANCE</div>
            <div class="balance-ring" style="background: conic-gradient(#E74C9B 0 {current_progress_pct:.1f}%, #67C8FF {current_progress_pct:.1f}% 100%);">
                <div class="balance-center">
                    <div class="balance-number">{money(current_saved)}</div>
                    <div class="balance-label">{current_progress_pct:.0f}% of goal</div>
                </div>
            </div>
            <div class="goal-line">Goal: {money(down_payment_goal)} • {money(remaining_to_goal)} to go</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with projection_col:
    p1, p2 = st.columns(2)
    with p1:
        st.markdown(
            f"""
            <div class="projection-card">
                <div class="metric-label">RECURRING PLAN</div>
                <div class="projection-big">{money(biweekly_amount)}</div>
                <div class="metric-note">every 2 weeks • {num_deposits} scheduled deposits</div>
                <div class="blue-chip">Next: {first_deposit.strftime('%b %d')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with p2:
        projected_note = (
            f"{money(abs(projected_over_under))} over goal"
            if projected_over_under >= 0
            else f"{money(abs(projected_over_under))} short of goal"
        )
        st.markdown(
            f"""
            <div class="projection-card">
                <div class="metric-label">PROJECTED BY {target_date.strftime('%b %d').upper()}</div>
                <div class="projection-big">{money(saved_by_target)}</div>
                <div class="metric-note">{projected_progress_pct:.0f}% of the {money(down_payment_goal)} goal</div>
                <div class="blue-chip">{projected_note}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.caption("The big ring is the real balance you have today. The projection uses that balance plus the recurring deposits you set in the sidebar.")

# ---------- Main dashboard ----------
st.subheader("💗 Your December snapshot")
cols = st.columns(4)
metrics = [
    ("Scheduled deposits", f"{num_deposits}", f"{money(biweekly_amount)} every 14 days"),
    ("Projected by target", money(saved_by_target), target_date.strftime("By %b %d, %Y")),
    ("Projected cash down", money(cash_down), f"{(cash_down / out_the_door * 100) if out_the_door else 0:.1f}% of estimated OTD price"),
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
