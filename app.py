from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
import os, uuid, time
from datetime import datetime, date, timezone
from functools import wraps
from math import pow
from sqlalchemy.exc import OperationalError

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dit-secret-key-change-in-prod')

# ── Database config ───────────────────────────────────────────────────────────

_DB_HOST = os.environ.get('DB_HOST', 'localhost')
_DB_PORT = os.environ.get('DB_PORT', '3306')
_DB_NAME = os.environ.get('DB_NAME', 'dit_db')
_DB_USER = os.environ.get('DB_USER', 'dit_user')
_DB_PASS = os.environ.get('DB_PASSWORD', 'dit_password')

app.config['SQLALCHEMY_DATABASE_URI'] = (
    f'mysql+pymysql://{_DB_USER}:{_DB_PASS}@{_DB_HOST}:{_DB_PORT}/{_DB_NAME}'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ── Models ────────────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'
    id         = db.Column(db.String(36), primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    debts      = db.relationship('Debt',   back_populates='user', cascade='all, delete-orphan')
    incomes    = db.relationship('Income', back_populates='user', cascade='all, delete-orphan')


class Debt(db.Model):
    __tablename__ = 'debts'
    id              = db.Column(db.String(36), primary_key=True)
    user_id         = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    name            = db.Column(db.String(100), nullable=False)
    principal       = db.Column(db.Float, nullable=False)
    rate            = db.Column(db.Float, nullable=False)
    months          = db.Column(db.Integer, nullable=False)
    monthly_payment = db.Column(db.Float, nullable=False)
    start_date      = db.Column(db.String(10), nullable=False)
    user            = db.relationship('User', back_populates='debts')
    payments        = db.relationship(
        'Payment', back_populates='debt',
        cascade='all, delete-orphan',
        order_by='Payment.month_num',
    )


class Payment(db.Model):
    __tablename__ = 'payments'
    id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    debt_id   = db.Column(db.String(36), db.ForeignKey('debts.id'), nullable=False)
    month_num = db.Column(db.Integer, nullable=False)
    due_date  = db.Column(db.String(20), nullable=False)
    amount    = db.Column(db.Float, nullable=False)
    paid      = db.Column(db.Boolean, default=False, nullable=False)
    paid_date = db.Column(db.String(30), nullable=True)
    debt      = db.relationship('Debt', back_populates='payments')

    # Templates reference p.month — map to month_num
    @property
    def month(self):
        return self.month_num


class Income(db.Model):
    __tablename__ = 'income'
    id         = db.Column(db.String(36), primary_key=True)
    user_id    = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    amount     = db.Column(db.Float, nullable=False)
    # stored as 'YYYY-MM'; column named month_key to avoid MySQL reserved word
    month      = db.Column('month_key', db.String(7), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user       = db.relationship('User', back_populates='incomes')


# ── DB startup with retry ─────────────────────────────────────────────────────
# Runs on import so it works with both `python app.py` and gunicorn.

def _init_db(retries=15, delay=3):
    for attempt in range(retries):
        try:
            with app.app_context():
                db.create_all()
            print("Database tables ready.")
            return
        except OperationalError:
            if attempt < retries - 1:
                print(f"Database not ready, retrying in {delay}s "
                      f"({attempt + 1}/{retries})...")
                time.sleep(delay)
            else:
                raise

_init_db()

# ── Helpers ───────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def calculate_monthly_payment(principal, rate, months):
    """M = P × [r(1+r)^n / ((1+r)^n − 1)]"""
    if rate == 0:
        return principal / months
    r = rate / 100
    factor = pow(1 + r, months)
    return principal * (r * factor / (factor - 1))


def php(amount):
    return f"₱ {amount:,.2f}"

app.jinja_env.globals['php'] = php

# ── Public routes ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/how-it-works')
def how_it_works():
    return render_template('how_it_works.html')

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user     = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id']   = user.id
            session['user_name'] = user.name
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
        elif password != confirm:
            flash('Passwords do not match.', 'error')
        elif len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
        else:
            db.session.add(User(
                id       = str(uuid.uuid4()),
                name     = name,
                email    = email,
                password = generate_password_hash(password),
            ))
            db.session.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    uid       = session['user_id']
    debts     = Debt.query.filter_by(user_id=uid).all()
    month_key = datetime.now().strftime('%Y-%m')
    income_row = Income.query.filter_by(user_id=uid, month=month_key).first()

    total_debt        = sum(p.amount for d in debts for p in d.payments if not p.paid)
    monthly_due       = sum(next((p.amount for p in d.payments if not p.paid), 0) for d in debts)
    income_this_month = income_row.amount if income_row else 0

    return render_template('dashboard.html',
        user_name=session['user_name'],
        total_debt=total_debt,
        monthly_due=monthly_due,
        income_this_month=income_this_month,
        debts=debts,
    )

# ── Debts ─────────────────────────────────────────────────────────────────────

@app.route('/debts', methods=['GET', 'POST'])
@login_required
def debts():
    uid        = session['user_id']
    user_debts = Debt.query.filter_by(user_id=uid).all()

    if request.method == 'POST':
        if len(user_debts) >= 5:
            flash('You can only add up to 5 debts.', 'error')
            return redirect(url_for('debts'))
        name = request.form.get('name', '').strip()
        try:
            principal = float(request.form.get('principal', 0))
            rate      = float(request.form.get('rate', 0))
            months    = int(request.form.get('months', 1))
        except ValueError:
            flash('Invalid numbers entered.', 'error')
            return redirect(url_for('debts'))
        if not name or principal <= 0 or months <= 0:
            flash('Please fill in all fields correctly.', 'error')
            return redirect(url_for('debts'))

        monthly = calculate_monthly_payment(principal, rate, months)
        debt = Debt(
            id              = str(uuid.uuid4()),
            user_id         = uid,
            name            = name,
            principal       = principal,
            rate            = rate,
            months          = months,
            monthly_payment = round(monthly, 2),
            start_date      = date.today().isoformat(),
        )
        db.session.add(debt)
        db.session.flush()  # obtain debt.id before adding payments

        start = date.today()
        for i in range(months):
            mo     = (start.month - 1 + i) % 12
            yr_add = (start.month - 1 + i) // 12
            due    = date(start.year + yr_add, mo + 1, start.day)
            db.session.add(Payment(
                debt_id   = debt.id,
                month_num = i + 1,
                due_date  = due.strftime('%b %Y'),
                amount    = round(monthly, 2),
                paid      = False,
            ))

        db.session.commit()
        flash(f'Debt "{name}" added successfully!', 'success')
        return redirect(url_for('debts'))

    return render_template('debts.html', debts=user_debts, count=len(user_debts))


@app.route('/debts/delete/<debt_id>', methods=['POST'])
@login_required
def delete_debt(debt_id):
    uid  = session['user_id']
    debt = Debt.query.filter_by(id=debt_id, user_id=uid).first_or_404()
    db.session.delete(debt)
    db.session.commit()
    flash('Debt removed.', 'success')
    return redirect(url_for('debts'))

# ── Repayment ─────────────────────────────────────────────────────────────────

@app.route('/repayment')
@login_required
def repayment():
    uid         = session['user_id']
    debts       = Debt.query.filter_by(user_id=uid).all()
    selected_id = request.args.get('debt_id')
    selected    = next((d for d in debts if d.id == selected_id), debts[0] if debts else None)
    return render_template('repayment.html', debts=debts, selected=selected)


@app.route('/repayment/pay/<int:payment_id>', methods=['POST'])
@login_required
def mark_paid(payment_id):
    uid     = session['user_id']
    payment = (
        Payment.query
        .join(Debt)
        .filter(Payment.id == payment_id, Debt.user_id == uid)
        .first_or_404()
    )
    payment.paid      = not payment.paid
    payment.paid_date = datetime.now().isoformat() if payment.paid else None
    db.session.commit()
    return redirect(url_for('repayment', debt_id=payment.debt_id))

# ── Income ────────────────────────────────────────────────────────────────────

@app.route('/income', methods=['GET', 'POST'])
@login_required
def income():
    uid        = session['user_id']
    income_val = None
    allocation = None

    if request.method == 'POST':
        try:
            income_val = float(request.form.get('income', 0))
        except ValueError:
            flash('Please enter a valid amount.', 'error')
            return redirect(url_for('income'))
        if income_val <= 0:
            flash('Income must be greater than 0.', 'error')
            return redirect(url_for('income'))

        month_key = datetime.now().strftime('%Y-%m')
        row = Income.query.filter_by(user_id=uid, month=month_key).first()
        if row:
            row.amount = income_val
        else:
            db.session.add(Income(
                id      = str(uuid.uuid4()),
                user_id = uid,
                amount  = income_val,
                month   = month_key,
            ))
        db.session.commit()

    if not income_val:
        latest = (
            Income.query
            .filter_by(user_id=uid)
            .order_by(Income.month.desc())
            .first()
        )
        if latest:
            income_val = latest.amount

    if income_val:
        allocation = {
            'needs':   round(income_val * 0.5, 2),
            'wants':   round(income_val * 0.3, 2),
            'savings': round(income_val * 0.2, 2),
        }

    return render_template('income.html', income=income_val, allocation=allocation)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
