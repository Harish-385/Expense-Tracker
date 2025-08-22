from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

class Expense(db.Model):
    __tablename__ = 'expenses'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)  # Easier to query/filter
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200))
    amount = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class SavingsGoal(db.Model):
    __tablename__ = 'savings_goals'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    target = db.Column(db.Float, nullable=False)
    progress = db.Column(db.Float, default=0.0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Budget(db.Model):
    __tablename__ = 'budgets'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), unique=True, nullable=False)
    limit = db.Column(db.Float, nullable=False)  # Budget limit for the category
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
class Investment(db.Model):
    __tablename__ = 'investments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'stock', 'mutual_fund', 'etf', 'bond', etc.
    symbol = db.Column(db.String(20))  # For stocks/ETFs
    amount_invested = db.Column(db.Float, nullable=False)
    units = db.Column(db.Float)  # Number of shares/units
    purchase_price = db.Column(db.Float)  # Price per unit at purchase
    current_price = db.Column(db.Float)  # Current market price
    purchase_date = db.Column(db.Date, nullable=False)
    investment_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='active')  # 'active', 'sold', 'pending'
    
    # Relationship
    user = db.relationship('User', backref='investments')

class InvestmentGoal(db.Model):
    __tablename__ = 'investment_goals'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    target_amount = db.Column(db.Float, nullable=False)
    target_date = db.Column(db.Date, nullable=False)
    current_amount = db.Column(db.Float, default=0.0)
    monthly_contribution = db.Column(db.Float, default=0.0)
    risk_profile = db.Column(db.String(20), default='moderate')  # 'conservative', 'moderate', 'aggressive'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='investment_goals')

class InvestmentTransaction(db.Model):
    __tablename__ = 'investment_transactions'
    id = db.Column(db.Integer, primary_key=True)
    investment_id = db.Column(db.Integer, db.ForeignKey('investments.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'buy', 'sell', 'dividend', 'sip'
    amount = db.Column(db.Float, nullable=False)
    units = db.Column(db.Float)
    price_per_unit = db.Column(db.Float)
    transaction_date = db.Column(db.DateTime, default=datetime.utcnow)
    fees = db.Column(db.Float, default=0.0)
    notes = db.Column(db.String(200))
    
    # Relationships
    investment = db.relationship('Investment', backref='transactions')
    user = db.relationship('User', backref='investment_transactions')

class RiskProfile(db.Model):
    __tablename__ = 'risk_profiles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    risk_tolerance = db.Column(db.String(20), default='moderate')  # 'conservative', 'moderate', 'aggressive'
    investment_horizon = db.Column(db.String(20), default='medium')  # 'short', 'medium', 'long'
    investment_experience = db.Column(db.String(20), default='beginner')  # 'beginner', 'intermediate', 'advanced'
    monthly_investment_capacity = db.Column(db.Float, default=0.0)
    emergency_fund_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='risk_profile', uselist=False)

class Debt(db.Model):
    __tablename__ = 'debts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'loan', 'credit_card', 'emi', 'mortgage'
    principal_amount = db.Column(db.Float, nullable=False)
    outstanding_amount = db.Column(db.Float, nullable=False)
    interest_rate = db.Column(db.Float, nullable=False)
    emi_amount = db.Column(db.Float, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    payment_day = db.Column(db.Integer, default=1)  # Day of month for payment
    status = db.Column(db.String(20), default='active')  # 'active', 'closed', 'defaulted'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='debts')
    payments = db.relationship('DebtPayment', backref='debt', cascade='all, delete-orphan')
    reminders = db.relationship('DebtReminder', backref='debt', cascade='all, delete-orphan')

class DebtPayment(db.Model):
    __tablename__ = 'debt_payments'
    id = db.Column(db.Integer, primary_key=True)
    debt_id = db.Column(db.Integer, db.ForeignKey('debts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_type = db.Column(db.String(20), default='emi')  # 'emi', 'prepayment', 'late_fee'
    principal_paid = db.Column(db.Float, nullable=False)
    interest_paid = db.Column(db.Float, nullable=False)
    remaining_balance = db.Column(db.Float, nullable=False)
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='debt_payments')

class DebtReminder(db.Model):
    __tablename__ = 'debt_reminders'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    debt_id = db.Column(db.Integer, db.ForeignKey('debts.id'), nullable=False)
    reminder_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'paid', 'overdue'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='debt_reminders')

