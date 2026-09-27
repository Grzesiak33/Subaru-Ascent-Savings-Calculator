# Ashlee's Subaru Ascent Fund

A Python + Streamlit dashboard for planning biweekly savings toward a used Subaru Ascent and seeing exactly how the saved down payment changes the amount financed, estimated monthly payment, and total interest.

## Features

- Adjustable biweekly deposit amount
- Adjustable first deposit and target purchase date
- Savings projection through the purchase date
- Used-car price, tax, fees, trade-in/credit inputs
- Editable APR and loan term
- Side-by-side $0 down vs. saved-down-payment financing
- Total-interest comparison
- Biweekly savings chart and deposit schedule
- Scenario table for different savings amounts
- APR sensitivity table for when you get a real dealer/lender prequalification
- Subaru Ascent image at the top

## Run locally

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Put this project in a GitHub repository.
2. Sign in to Streamlit Community Cloud with GitHub.
3. Choose **Create app** / **Deploy an app**.
4. Select the repository, branch `main`, and file `app.py`.
5. Deploy.

## Starting assumptions

The dashboard starts at:

- Vehicle price: $21,000
- Michigan sales tax input: 6.0%
- Fees: $500 (editable placeholder)
- APR: 19.10% (editable placeholder)
- Term: 72 months
- Biweekly deposit: $300
- First deposit: October 2, 2026
- Target purchase date: December 19, 2026

The APR default is a planning benchmark based on Experian Q2 2026 data for used-auto borrowers in the 501–600 VantageScore tier. It is **not** a personal rate quote. Replace it with your actual dealer, bank, or credit-union prequalification APR.

## Car photo

The app loads a Subaru Ascent photo from Wikimedia Commons:

- Photo: Alexander Migl
- License: CC BY-SA 4.0
- File: `Subaru Ascent IMG 3632.jpg`
