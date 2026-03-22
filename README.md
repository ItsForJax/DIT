# DIT — Debt and Income Tracker

A Flask web application to track debts and manage income for small vendors.

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000

## Features

- Register / Login with hashed passwords
- Add up to 5 debts with amortization calculation (M = P × [r(1+r)ⁿ / ((1+r)ⁿ − 1)])
- Auto-generated monthly payment schedules
- Mark payments as paid / undo
- Income input with 50/30/20 allocation breakdown
- Dashboard with total debt, monthly due, and income summary
- About and How It Works pages

## Data Storage

All data is saved locally in a `data/` folder as JSON files:
- `data/users.json`
- `data/debts.json`
- `data/income.json`

## Changing the Secret Key

In `app.py`, change:
```python
app.secret_key = 'your-secure-secret-key'
```
