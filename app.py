from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date, timedelta
import requests
import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from db import get_db_connection, init_db
import sqlite3
from models import db, Investment, InvestmentGoal, InvestmentTransaction, RiskProfile, Debt, DebtPayment, DebtReminder
import json
import random
import os


app = Flask(__name__)
app.secret_key = "secret123"  # Required for flash messages

# Configure SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy with the app
db.init_app(app)

# In-memory storage (replace with DB in production)
expenses = []               # expense records (amount stored as negative values)
savings_goals = []
goal_id_counter = 1
expense_id_counter = 1

# Portfolio allocations stored with ONLY these keys: expense, savings, investment
user_portfolio = {
    'needs': 0.0,
    'wants': 0.0,     # Changed from 'expense' to 'wants'
    'savings': 0.0
}

# Global monthly income (set from dashboard)
monthly_income = 0.0

# Category budgets (editable in dashboard)
CATEGORY_BUDGETS = {
    'Food': 500.0,
    'Transport': 300.0,
    'Entertainment': 200.0,
    'Bills': 400.0,
    'Other': 100.0
}

# Monthly remainder tracking
monthly_remainder = {
    'needs': 0.0,
    'wants': 0.0,
    'savings': 0.0,
    'last_month': None
}

# Bill reminder tracking
bill_reminders = {
    'last_reminder_date': None,
    'reminder_sent': False
}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def calculate_monthly_remainder():
    """Calculate and apply monthly remainder from previous month"""
    global monthly_remainder, user_portfolio, monthly_income
    
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    # Check if we need to process monthly remainder
    if monthly_remainder['last_month'] is None:
        monthly_remainder['last_month'] = current_month
        return
    
    # If it's a new month, apply remainder from previous month
    if monthly_remainder['last_month'] != current_month:
        # Calculate remainder from previous month
        needs_remainder = max(0, user_portfolio.get('needs', 0))
        wants_remainder = max(0, user_portfolio.get('wants', 0))
        savings_remainder = max(0, user_portfolio.get('savings', 0))
        
        # Store remainder
        monthly_remainder['needs'] = needs_remainder
        monthly_remainder['wants'] = wants_remainder
        monthly_remainder['savings'] = savings_remainder
        
        # Apply new monthly allocation with remainder
        if monthly_income > 0:
            needs_amt = round(monthly_income * 0.50 + needs_remainder, 2)
            wants_amt = round(monthly_income * 0.30 + wants_remainder, 2)
            savings_amt = round(monthly_income * 0.20 + savings_remainder, 2)
            
            user_portfolio['needs'] = needs_amt
            user_portfolio['wants'] = wants_amt
            user_portfolio['savings'] = savings_amt
        
        monthly_remainder['last_month'] = current_month

def check_bill_reminders():
    """Check for upcoming and overdue bills and show reminders"""
    global bill_reminders
    
    try:
        with get_db_connection() as conn:
            # Get today's date
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Check for overdue bills (due date < today and status = unpaid)
            overdue_bills = conn.execute('''
                SELECT * FROM bills 
                WHERE user_id = ? AND due_date < ? AND status = 'unpaid'
                ORDER BY due_date ASC
            ''', (session['user_id'], today)).fetchall()
            
            # Check for upcoming bills (due within next 7 days)
            upcoming_bills = conn.execute('''
                SELECT * FROM bills 
                WHERE user_id = ? AND due_date >= ? AND due_date <= date(?, '+7 days') AND status = 'unpaid'
                ORDER BY due_date ASC
            ''', (session['user_id'], today, today)).fetchall()
            
            # Show reminders if we have bills and haven't shown today (and daily reminders are enabled)
            daily_enabled = bill_reminders.get('daily_enabled', True)  # Default to enabled
            if (overdue_bills or upcoming_bills) and (bill_reminders['last_reminder_date'] != today or not daily_enabled):
                reminder_messages = []
                
                if overdue_bills:
                    overdue_count = len(overdue_bills)
                    overdue_total = sum(bill['amount'] for bill in overdue_bills)
                    reminder_messages.append(f"⚠️ You have {overdue_count} overdue bill(s) totaling ₹{overdue_total:.2f}")
                
                if upcoming_bills:
                    upcoming_count = len(upcoming_bills)
                    upcoming_total = sum(bill['amount'] for bill in upcoming_bills)
                    reminder_messages.append(f"📅 You have {upcoming_count} upcoming bill(s) due within 7 days totaling ₹{upcoming_total:.2f}")
                
                if reminder_messages:
                    flash(" | ".join(reminder_messages), "warning")
                    bill_reminders['last_reminder_date'] = today
                    bill_reminders['reminder_sent'] = True
                    
    except Exception as e:
        print(f"Error checking bill reminders: {e}")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if not username or not email or not password or not confirm_password:
            flash("All fields are required", "error")
            return redirect(url_for('register'))

        # Password validation
        if password != confirm_password:
            flash("Passwords do not match", "error")
            return redirect(url_for('register'))

        if len(password) < 6:
            flash("Password must be at least 6 characters long", "error")
            return redirect(url_for('register'))

        # Basic email validation
        if '@' not in email or '.' not in email:
            flash("Please enter a valid email address", "error")
            return redirect(url_for('register'))

        try:
            with get_db_connection() as conn:
                # Check if username or email already exists
                existing_user = conn.execute(
                    "SELECT username, email FROM users WHERE username = ? OR email = ?", 
                    (username, email)
                ).fetchone()
                
                if existing_user:
                    if existing_user['username'] == username:
                        flash("Username already exists", "error")
                    else:
                        flash("Email already registered", "error")
                    return redirect(url_for('register'))
                
                # Create new user
                conn.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                    (username, email, generate_password_hash(password))
                )
                conn.commit()
            flash("Registration successful! Please log in with your username and password.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            flash("Registration failed. Please try again.", "error")
            print(f"Registration error: {e}")
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_or_email = request.form['username'].strip()
        password = request.form['password']

        with get_db_connection() as conn:
            # Try to find user by username or email
            user = conn.execute(
                "SELECT * FROM users WHERE username = ? OR email = ?", 
                (username_or_email, username_or_email)
            ).fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid username/email or password", "error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for('login'))

# ---------- ROUTES ----------

@app.route('/')
@login_required
def dashboard():
    global monthly_income, user_portfolio
    
    # Calculate monthly remainder
    calculate_monthly_remainder()
    
    # Check for bill reminders
    check_bill_reminders()

    now = datetime.now()
    curr_m = now.month
    curr_y = now.year

    # total balance = monthly income minus this month's expenses
    this_month_expense_total = sum((-e['amount']) for e in expenses
                                   if datetime.strptime(e['date'], '%Y-%m-%d').month == curr_m
                                   and datetime.strptime(e['date'], '%Y-%m-%d').year == curr_y)

    current_savings = round(monthly_income - this_month_expense_total, 2)

    # recent expenses (descending)
    recent_expenses = sorted(expenses, key=lambda x: x['date'], reverse=True)[:6]

    # category totals (show positive numbers)
    category_totals = {}
    for e in expenses:
        category_totals[e['category']] = category_totals.get(e['category'], 0.0) + (-e['amount'])

    # Get bill summary for dashboard
    try:
        with get_db_connection() as conn:
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Count overdue bills
            overdue_count = conn.execute('''
                SELECT COUNT(*) as count FROM bills 
                WHERE user_id = ? AND due_date < ? AND status = 'unpaid'
            ''', (session['user_id'], today)).fetchone()['count']
            
            # Count upcoming bills (next 7 days)
            upcoming_count = conn.execute('''
                SELECT COUNT(*) as count FROM bills 
                WHERE user_id = ? AND due_date >= ? AND due_date <= date(?, '+7 days') AND status = 'unpaid'
            ''', (session['user_id'], today, today)).fetchone()['count']
            
            # Total unpaid amount
            unpaid_total = conn.execute('''
                SELECT COALESCE(SUM(amount), 0) as total FROM bills 
                WHERE user_id = ? AND status = 'unpaid'
            ''', (session['user_id'],)).fetchone()['total']
            
    except Exception as e:
        overdue_count = 0
        upcoming_count = 0
        unpaid_total = 0

    # Render dashboard with current values
    return render_template('dashboard.html',
                           monthly_income=monthly_income,
                           portfolio=user_portfolio,
                           current_savings=current_savings,
                           recent_expenses=recent_expenses,
                           category_budgets=CATEGORY_BUDGETS,
                           category_totals=category_totals,
                           monthly_remainder=monthly_remainder,
                           overdue_count=overdue_count,
                           upcoming_count=upcoming_count,
                           unpaid_total=unpaid_total)


@app.route('/set_income', methods=['POST'])
@login_required
def set_income():
    global monthly_income, user_portfolio

    try:
        income = float(request.form.get('monthlyIncome', 0))
    except:
        income = 0.0
    monthly_income = income

    # Apply default 50/30/20 split
    needs_amt = round(monthly_income * 0.50, 2)
    wants_amt = round(monthly_income * 0.30, 2)    # Changed variable name
    savings_amt = round(monthly_income * 0.20, 2)

    user_portfolio['needs'] = needs_amt
    user_portfolio['wants'] = wants_amt    # Changed from 'expense' to 'wants'
    user_portfolio['savings'] = savings_amt

    flash(f"Monthly income saved. Default split applied (Needs 50% / Wants 30% / Savings 20%).", "success")
    return redirect(url_for('dashboard'))


@app.route('/save_split', methods=['POST'])
@login_required
def save_split():
    """
    Receives split percentages (needPercent, expensePercent, savingsPercent) via JSON (AJAX).
    Stores allocations using only keys: expense, savings, investment.
    """
    global monthly_income, user_portfolio

    data = request.get_json() or {}
    try:
        needP = float(data.get('needPercent', 50))
        wantsP = float(data.get('wantsPercent', 30))  # Changed from 'expensePercent'
        savingsP = float(data.get('savingsPercent', 20))
    except:
        return jsonify({"error": "Invalid percentages"}), 400

    total = round(needP + wantsP + savingsP, 6)
    if abs(total - 100.0) > 1e-6:
        return jsonify({"error": "Percentages must sum to 100"}), 400

    # Calculate amounts from monthly_income
    needsAmt = round(monthly_income * (needP / 100.0), 2)
    wantsAmt = round(monthly_income * (wantsP / 100.0), 2)  # Changed variable name
    savingsAmt = round(monthly_income * (savingsP / 100.0), 2)

    user_portfolio['needs'] = needsAmt
    user_portfolio['wants'] = wantsAmt    # Changed from 'expense' to 'wants'
    user_portfolio['savings'] = savingsAmt

    return jsonify({
        "status": "ok",
        "needs": user_portfolio['needs'],
        "wants": user_portfolio['wants'],  # Changed from 'expense' to 'wants'
        "savings": user_portfolio['savings']
    })


@app.route('/set_budgets', methods=['POST'])
@login_required
def set_budgets():
    """
    Update category budgets from dashboard form.
    """
    global CATEGORY_BUDGETS
    for k in list(CATEGORY_BUDGETS.keys()):
        val = request.form.get(f'budget_{k}')
        if val is not None and val != '':
            try:
                CATEGORY_BUDGETS[k] = float(val)
            except:
                pass
    flash("Category budgets updated.", "success")
    return redirect(url_for('dashboard'))

@app.route('/expenses')
@login_required
def expense_page():
    return render_template('expenses/expenses.html', expenses=expenses)


@app.route('/expenses/add', methods=['POST'])
@login_required
def add_expense():
    global expense_id_counter, user_portfolio, expenses
    
    try:
        amount_val = float(request.form.get('amount', 0))
        expense_type = request.form.get('expense_type', 'want')  # Default to want if not specified
        
        # Validate amount
        if amount_val <= 0:
            flash("Amount must be positive", "error")
            return redirect(url_for('expense_page'))

        # Create expense record
        new_expense = {
            'id': expense_id_counter,
            'amount': -abs(amount_val),  # Store as negative
            'category': request.form.get('category', 'Other'),
            'date': request.form.get('date', datetime.now().strftime('%Y-%m-%d')),
            'description': request.form.get('description', ''),
            'type': expense_type  # Store expense type
        }
        
        # Deduct from appropriate allocation
        if expense_type == 'need':
            if user_portfolio['needs'] < amount_val:
                flash("Warning: Needs budget exceeded!", "warning")
            user_portfolio['needs'] = round(user_portfolio.get('needs', 0.0) - amount_val, 2)
        else:  # want
            if user_portfolio['wants'] < amount_val:
                flash("Warning: Wants budget exceeded!", "warning")
            user_portfolio['wants'] = round(user_portfolio.get('wants', 0.0) - amount_val, 2)

        expenses.append(new_expense)
        expense_id_counter += 1
        flash(f"Expense added and deducted from {expense_type}s allocation.", "success")
        
    except ValueError:
        flash("Invalid amount", "error")
    
    return redirect(url_for('expense_page'))


@app.route('/expenses/delete/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    global expenses, user_portfolio
    
    to_delete = next((e for e in expenses if e['id'] == expense_id), None)
    if to_delete:
        # Add back to appropriate category
        if to_delete['type'] == 'need':
            user_portfolio['needs'] += abs(to_delete['amount'])
        else:  # want
            user_portfolio['wants'] += abs(to_delete['amount'])
            
        expenses.remove(to_delete)
        flash("Expense deleted successfully", "success")
    else:
        flash("Expense not found", "error")
        
    return redirect(url_for('expense_page'))

@app.route('/savings', methods=['GET', 'POST'])
@login_required
def savings_page():
    try:
        # Get total savings from user_portfolio instead of database
        total_savings = user_portfolio.get('savings', 0.0)  # Use the same savings value as dashboard

        # Get all savings goals for the current user
        with get_db_connection() as conn:
            goals = conn.execute('SELECT * FROM savings_goals WHERE user_id = ?', (session['user_id'],)).fetchall()
            goals = [dict(row) for row in goals]  

        # Prepare data for XGBoost prediction
        predictions = []
        try:
            model = XGBRegressor()
            model.load_model('savings_model.json')

            # Create input features using the current savings
            X = np.array([[total_savings]])
            future_preds = model.predict(X)
            predictions = [{"month": i+1, "amount": float(pred)} 
                         for i, pred in enumerate(future_preds)]
        except Exception as e:
            print("Prediction error:", e)

        return render_template(
            'savings/savings.html',
            current_savings=total_savings,  # Pass the same savings value used in dashboard
            goals=goals,
            predictions=predictions
        )
    except sqlite3.Error as e:
        print("Database error:", e)
        flash("Database error occurred", "error")
        return redirect(url_for('dashboard'))

# Add new financial goal
@app.route('/savings/add_goal', methods=['POST'])
@login_required
def add_goal():
    try:
        name = request.form.get('goal_name')
        target = float(request.form.get('target_amount', 0))
        
        if not name or target <= 0:
            flash("Goal name and a positive target amount are required", "error")
            return redirect(url_for('savings_page'))
        
        with get_db_connection() as conn:
            conn.execute(
                'INSERT INTO savings_goals (user_id, name, target, progress) VALUES (?, ?, ?, ?)',
                (session['user_id'], name, target, 0.0)
            )
            conn.commit()
        
        flash(f"Goal '{name}' created successfully!", "success")
        
    except ValueError:
        flash("Invalid amount", "error")
    except Exception as e:
        flash(f"Error creating goal: {str(e)}", "error")
        print(f"Error in add_goal: {str(e)}")
        
    return redirect(url_for('savings_page'))

# Deposit savings into a goal
@app.route('/savings/deposit/<int:goal_id>', methods=['POST'])
@login_required
def deposit_to_goal(goal_id):
    try:
        amount = float(request.form.get('deposit_amount', 0))
        
        # Validate against available savings
        if amount > user_portfolio.get('savings', 0):
            flash("Amount exceeds available savings", "error")
            return redirect(url_for('savings_page'))

        # Update goal progress in database
        with get_db_connection() as conn:
            goal = conn.execute('SELECT * FROM savings_goals WHERE id = ? AND user_id = ?', 
                              (goal_id, session['user_id'])).fetchone()
            if goal:
                new_progress = round(goal['progress'] + amount, 2)
                conn.execute('UPDATE savings_goals SET progress = ? WHERE id = ?', 
                           (new_progress, goal_id))
                conn.commit()
                
                # Deduct from savings allocation
                user_portfolio['savings'] = round(user_portfolio.get('savings', 0) - amount, 2)
                flash(f"Successfully saved ₹{amount}", "success")
            else:
                flash("Goal not found", "error")
            
    except ValueError:
        flash("Invalid amount", "error")
        
    return redirect(url_for('savings_page'))

# Bills functionality
@app.route('/bills')
@login_required
def bills_page():
    try:
        with get_db_connection() as conn:
            bills = conn.execute('SELECT * FROM bills WHERE user_id = ? ORDER BY due_date ASC', 
                               (session['user_id'],)).fetchall()
            bills = [dict(row) for row in bills]
        
        # Get today's date for overdue calculation
        today = datetime.now().strftime('%Y-%m-%d')
        
        return render_template('bills/bills.html', bills=bills, today=today)
    except Exception as e:
        flash("Error loading bills", "error")
        return redirect(url_for('dashboard'))

@app.route('/bills/add', methods=['POST'])
@login_required
def add_bill():
    try:
        title = request.form.get('title', '').strip()
        amount = float(request.form.get('amount', 0))
        due_date = request.form.get('due_date', '')
        description = request.form.get('description', '').strip()
        category = request.form.get('category', 'Bills')
        
        if not title or amount <= 0 or not due_date:
            flash("Title, amount, and due date are required", "error")
            return redirect(url_for('bills_page'))
        
        with get_db_connection() as conn:
            conn.execute('''
                INSERT INTO bills (user_id, title, amount, due_date, description, category) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (session['user_id'], title, amount, due_date, description, category))
            conn.commit()
        
        flash(f"Bill '{title}' added successfully", "success")
        
    except ValueError:
        flash("Invalid amount", "error")
    except Exception as e:
        flash(f"Error adding bill: {str(e)}", "error")
        
    return redirect(url_for('bills_page'))

@app.route('/bills/pay/<int:bill_id>', methods=['POST'])
@login_required
def pay_bill(bill_id):
    try:
        with get_db_connection() as conn:
            bill = conn.execute('SELECT * FROM bills WHERE id = ? AND user_id = ?', 
                              (bill_id, session['user_id'])).fetchone()
            
            if not bill:
                flash("Bill not found", "error")
                return redirect(url_for('bills_page'))
            
            if bill['status'] == 'paid':
                flash("Bill is already paid", "warning")
                return redirect(url_for('bills_page'))
            
            # Check if user has enough in needs allocation
            if user_portfolio.get('needs', 0) < bill['amount']:
                flash("Insufficient funds in needs allocation", "error")
                return redirect(url_for('bills_page'))
            
            # Mark bill as paid
            conn.execute('''
                UPDATE bills SET status = 'paid', paid_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (bill_id,))
            conn.commit()
            
            # Deduct from needs allocation
            user_portfolio['needs'] = round(user_portfolio.get('needs', 0) - bill['amount'], 2)
            
            # Add to expenses
            global expense_id_counter
            new_expense = {
                'id': expense_id_counter,
                'amount': -abs(bill['amount']),
                'category': bill['category'],
                'date': datetime.now().strftime('%Y-%m-%d'),
                'description': f"Bill payment: {bill['title']}",
                'type': 'need'
            }
            expenses.append(new_expense)
            expense_id_counter += 1
            
            flash(f"Bill '{bill['title']}' paid successfully", "success")
            
    except Exception as e:
        flash(f"Error paying bill: {str(e)}", "error")
        
    return redirect(url_for('bills_page'))

@app.route('/bills/delete/<int:bill_id>', methods=['POST'])
@login_required
def delete_bill(bill_id):
    try:
        with get_db_connection() as conn:
            bill = conn.execute('SELECT * FROM bills WHERE id = ? AND user_id = ?', 
                              (bill_id, session['user_id'])).fetchone()
            
            if not bill:
                flash("Bill not found", "error")
                return redirect(url_for('bills_page'))
            
            conn.execute('DELETE FROM bills WHERE id = ?', (bill_id,))
            conn.commit()
            
            flash(f"Bill '{bill['title']}' deleted successfully", "success")
            
    except Exception as e:
        flash(f"Error deleting bill: {str(e)}", "error")
        
    return redirect(url_for('bills_page'))

# Auto-generate monthly bills
@app.route('/bills/generate_monthly', methods=['POST'])
@login_required
def generate_monthly_bills():
    try:
        # Get current month and year
        now = datetime.now()
        current_month = now.month
        current_year = now.year
        
        # Check if bills already exist for this month
        with get_db_connection() as conn:
            existing_bills = conn.execute('''
                SELECT COUNT(*) as count FROM bills 
                WHERE user_id = ? AND strftime('%m', due_date) = ? AND strftime('%Y', due_date) = ?
            ''', (session['user_id'], f"{current_month:02d}", str(current_year))).fetchone()
            
            if existing_bills['count'] > 0:
                flash("Monthly bills already generated for this month", "warning")
                return redirect(url_for('bills_page'))
        
        # Default monthly bills
        default_bills = [
            {'title': 'Rent/Mortgage', 'amount': 15000, 'category': 'Housing'},
            {'title': 'Electricity', 'amount': 2000, 'category': 'Utilities'},
            {'title': 'Water Bill', 'amount': 500, 'category': 'Utilities'},
            {'title': 'Internet', 'amount': 1000, 'category': 'Utilities'},
            {'title': 'Mobile Phone', 'amount': 500, 'category': 'Utilities'},
            {'title': 'Gas Bill', 'amount': 800, 'category': 'Utilities'},
            {'title': 'Groceries', 'amount': 5000, 'category': 'Food'},
            {'title': 'Transportation', 'amount': 2000, 'category': 'Transport'},
            {'title': 'Insurance', 'amount': 1500, 'category': 'Insurance'},
            {'title': 'Entertainment', 'amount': 1000, 'category': 'Entertainment'}
        ]
        
        # Generate bills for current month
        with get_db_connection() as conn:
            for bill in default_bills:
                due_date = f"{current_year}-{current_month:02d}-15"  # Due on 15th of month
                conn.execute('''
                    INSERT INTO bills (user_id, title, amount, due_date, category, status) 
                    VALUES (?, ?, ?, ?, ?, 'unpaid')
                ''', (session['user_id'], bill['title'], bill['amount'], due_date, bill['category']))
            conn.commit()
        
        flash("Monthly bills generated successfully", "success")
        
    except Exception as e:
        flash(f"Error generating monthly bills: {str(e)}", "error")
        
    return redirect(url_for('bills_page'))

# Manual monthly remainder processing
@app.route('/process_monthly_remainder', methods=['POST'])
@login_required
def process_monthly_remainder():
    """Manually process monthly remainder"""
    global monthly_remainder, user_portfolio, monthly_income
    
    try:
        # Calculate remainder from current allocations
        needs_remainder = max(0, user_portfolio.get('needs', 0))
        wants_remainder = max(0, user_portfolio.get('wants', 0))
        savings_remainder = max(0, user_portfolio.get('savings', 0))
        
        # Store remainder
        monthly_remainder['needs'] = needs_remainder
        monthly_remainder['wants'] = wants_remainder
        monthly_remainder['savings'] = savings_remainder
        
        # Apply new monthly allocation with remainder
        if monthly_income > 0:
            needs_amt = round(monthly_income * 0.50 + needs_remainder, 2)
            wants_amt = round(monthly_income * 0.30 + wants_remainder, 2)
            savings_amt = round(monthly_income * 0.20 + savings_remainder, 2)
            
            user_portfolio['needs'] = needs_amt
            user_portfolio['wants'] = wants_amt
            user_portfolio['savings'] = savings_amt
        
        flash(f"Monthly remainder processed! Added ₹{needs_remainder + wants_remainder + savings_remainder:.2f} to this month's budget.", "success")
        
    except Exception as e:
        flash(f"Error processing monthly remainder: {str(e)}", "error")
        
    return redirect(url_for('dashboard'))

# Manual bill reminder check
@app.route('/check_bill_reminders', methods=['POST'])
@login_required
def manual_bill_reminder_check():
    """Manually check for bill reminders"""
    global bill_reminders
    
    try:
        # Reset reminder flag to force check
        bill_reminders['reminder_sent'] = False
        bill_reminders['last_reminder_date'] = None
        
        # Check for reminders
        check_bill_reminders()
        
        flash("Bill reminders checked successfully", "success")
        
    except Exception as e:
        flash(f"Error checking bill reminders: {str(e)}", "error")
        
    return redirect(url_for('dashboard'))

# Enable/disable daily reminders
@app.route('/toggle_daily_reminders', methods=['POST'])
@login_required
def toggle_daily_reminders():
    """Toggle daily bill reminders on/off"""
    global bill_reminders
    
    try:
        # Toggle the reminder setting
        bill_reminders['daily_enabled'] = not bill_reminders.get('daily_enabled', False)
        
        if bill_reminders['daily_enabled']:
            flash("Daily bill reminders enabled! You'll get notifications when you visit the dashboard.", "success")
        else:
            flash("Daily bill reminders disabled.", "info")
            
    except Exception as e:
        flash(f"Error toggling reminders: {str(e)}", "error")
        
    return redirect(url_for('dashboard'))


# ---------- Enhanced Investment Management ----------

def calculate_investment_returns(investment):
    """Calculate returns for an investment"""
    if investment.current_price and investment.purchase_price and investment.units:
        current_value = investment.current_price * investment.units
        invested_value = investment.purchase_price * investment.units
        absolute_return = current_value - invested_value
        percentage_return = (absolute_return / invested_value) * 100 if invested_value > 0 else 0
        return {
            'absolute_return': round(absolute_return, 2),
            'percentage_return': round(percentage_return, 2),
            'current_value': round(current_value, 2)
        }
    return {'absolute_return': 0, 'percentage_return': 0, 'current_value': 0}

def get_portfolio_summary(user_id):
    """Get portfolio summary for a user"""
    investments = Investment.query.filter_by(user_id=user_id, status='active').all()
    
    total_invested = sum(inv.amount_invested for inv in investments)
    total_current_value = 0
    total_returns = 0
    
    for inv in investments:
        returns = calculate_investment_returns(inv)
        total_current_value += returns['current_value']
        total_returns += returns['absolute_return']
    
    # Calculate asset allocation
    asset_allocation = {}
    for inv in investments:
        if inv.type not in asset_allocation:
            asset_allocation[inv.type] = 0
        asset_allocation[inv.type] += inv.amount_invested
    
    return {
        'total_invested': round(total_invested, 2),
        'total_current_value': round(total_current_value, 2),
        'total_returns': round(total_returns, 2),
        'total_return_percentage': round((total_returns / total_invested * 100) if total_invested > 0 else 0, 2),
        'asset_allocation': asset_allocation
    }

def get_risk_recommendations(risk_profile):
    """Get investment recommendations based on risk profile"""
    recommendations = {
        'conservative': {
            'equity': 20,
            'debt': 60,
            'gold': 10,
            'cash': 10,
            'description': 'Low risk, stable returns with focus on capital preservation'
        },
        'moderate': {
            'equity': 50,
            'debt': 35,
            'gold': 10,
            'cash': 5,
            'description': 'Balanced approach with moderate risk and growth potential'
        },
        'aggressive': {
            'equity': 80,
            'debt': 15,
            'gold': 3,
            'cash': 2,
            'description': 'High growth potential with higher risk tolerance'
        }
    }
    return recommendations.get(risk_profile, recommendations['moderate'])

@app.route("/investment/portfolio")
@login_required
def investment_portfolio():
    """View user's investment portfolio"""
    user_id = session['user_id']
    
    # Get user's investments
    investments = Investment.query.filter_by(user_id=user_id, status='active').all()
    
    # Calculate returns for each investment
    investment_data = []
    for inv in investments:
        returns = calculate_investment_returns(inv)
        investment_data.append({
            'investment': inv,
            'returns': returns
        })
    
    # Get portfolio summary
    portfolio_summary = get_portfolio_summary(user_id)
    
    # Get investment goals (using existing savings goals system)
    with get_db_connection() as conn:
        goals = conn.execute('SELECT * FROM savings_goals WHERE user_id = ?', (user_id,)).fetchall()
        goals = [dict(row) for row in goals]
    
    return render_template("investment/investment_portfolio.html",
                         investments=investment_data,
                         portfolio_summary=portfolio_summary,
                         goals=goals)

@app.route("/investment/add", methods=["GET", "POST"])
@login_required
def add_investment():
    """Add a new investment"""
    if request.method == "POST":
        try:
            user_id = session['user_id']
            
            investment = Investment(
                user_id=user_id,
                name=request.form['name'],
                type=request.form['type'],
                symbol=request.form.get('symbol', ''),
                amount_invested=float(request.form['amount_invested']),
                units=float(request.form.get('units', 0)),
                purchase_price=float(request.form.get('purchase_price', 0)),
                current_price=float(request.form.get('current_price', 0)),
                purchase_date=datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date()
            )
            
            db.session.add(investment)
            db.session.commit()
            
            # Add transaction record
            transaction = InvestmentTransaction(
                investment_id=investment.id,
                user_id=user_id,
                transaction_type='buy',
                amount=investment.amount_invested,
                units=investment.units,
                price_per_unit=investment.purchase_price,
                notes=f"Initial investment in {investment.name}"
            )
            
            db.session.add(transaction)
            db.session.commit()
            
            flash("Investment added successfully!", "success")
            return redirect(url_for('investment_portfolio'))
            
        except Exception as e:
            flash(f"Error adding investment: {str(e)}", "error")
    
    return render_template("investment/add_investment.html")

@app.route("/investment/goal/add", methods=["GET", "POST"])
@login_required
def add_investment_goal():
    """Add a new investment goal (using existing savings goals system)"""
    if request.method == "POST":
        try:
            user_id = session['user_id']
            name = request.form['name']
            target_amount = float(request.form['target_amount'])
            
            # Use the existing savings_goals table
            with get_db_connection() as conn:
                conn.execute(
                    'INSERT INTO savings_goals (user_id, name, target, progress) VALUES (?, ?, ?, ?)',
                    (user_id, name, target_amount, 0.0)
                )
                conn.commit()
            
            flash("Investment goal added successfully!", "success")
            return redirect(url_for('investment_portfolio'))
            
        except Exception as e:
            flash(f"Error adding goal: {str(e)}", "error")
    
    return render_template("investment/add_investment_goal.html")

@app.route("/investment/risk-profile", methods=["GET", "POST"])
@login_required
def risk_profile():
    """Manage risk profile"""
    user_id = session['user_id']
    
    if request.method == "POST":
        try:
            # Check if profile exists
            profile = RiskProfile.query.filter_by(user_id=user_id).first()
            
            if not profile:
                profile = RiskProfile(user_id=user_id)
                db.session.add(profile)
            
            profile.risk_tolerance = request.form['risk_tolerance']
            profile.investment_horizon = request.form['investment_horizon']
            profile.investment_experience = request.form['investment_experience']
            profile.monthly_investment_capacity = float(request.form.get('monthly_investment_capacity', 0))
            profile.emergency_fund_available = 'emergency_fund' in request.form
            
            db.session.commit()
            flash("Risk profile updated successfully!", "success")
            return redirect(url_for('investment_portfolio'))
            
        except Exception as e:
            flash(f"Error updating risk profile: {str(e)}", "error")
    
    # Get existing profile
    profile = RiskProfile.query.filter_by(user_id=user_id).first()
    recommendations = get_risk_recommendations(profile.risk_tolerance if profile else 'moderate')
    
    return render_template("investment/risk_profile.html", profile=profile, recommendations=recommendations)

@app.route("/investment/calculator")
@login_required
def investment_calculator():
    """Investment calculator for SIP and lump sum"""
    return render_template("investment/investment_calculator.html")

@app.route("/api/calculate-sip", methods=["POST"])
@login_required
def calculate_sip():
    """Calculate SIP returns"""
    try:
        data = request.get_json()
        monthly_amount = float(data['monthly_amount'])
        years = int(data['years'])
        expected_return = float(data['expected_return'])
        
        # SIP calculation
        monthly_rate = expected_return / 12 / 100
        total_months = years * 12
        
        # Future value of SIP
        future_value = monthly_amount * ((1 + monthly_rate) ** total_months - 1) / monthly_rate
        
        # Total invested
        total_invested = monthly_amount * total_months
        
        # Total returns
        total_returns = future_value - total_invested
        
        return jsonify({
            'total_invested': round(total_invested, 2),
            'future_value': round(future_value, 2),
            'total_returns': round(total_returns, 2),
            'return_percentage': round((total_returns / total_invested * 100), 2)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route("/api/calculate-lumpsum", methods=["POST"])
@login_required
def calculate_lumpsum():
    """Calculate lump sum returns"""
    try:
        data = request.get_json()
        principal = float(data['principal'])
        years = int(data['years'])
        expected_return = float(data['expected_return'])
        
        # Compound interest calculation
        rate = expected_return / 100
        future_value = principal * (1 + rate) ** years
        
        # Total returns
        total_returns = future_value - principal
        
        return jsonify({
            'principal': round(principal, 2),
            'future_value': round(future_value, 2),
            'total_returns': round(total_returns, 2),
            'return_percentage': round((total_returns / principal * 100), 2)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ---------- Original Investment page with enhancements ----------

def fetch_nifty_stocks():
    url = "https://latest-stock-price.p.rapidapi.com/price"
    headers = {
        "x-rapidapi-host": "latest-stock-price.p.rapidapi.com",
        "x-rapidapi-key": "YOUR_RAPID_API_KEY"  # Replace with your actual RapidAPI key
    }
    querystring = {"Indices": "NIFTY 50"}
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=8)
        if response.ok:
            return response.json()
    except Exception as e:
        print("Nifty API error:", e)
    return []


def fetch_mfs():
    mf_list = ["119551", "118834", "100027"]  # Example scheme codes for mutual funds
    mf_data = []
    for code in mf_list:
        try:
            r = requests.get(f"https://api.mfapi.in/mf/{code}", timeout=8)
            if r.ok:
                data = r.json()
                if "meta" in data and "data" in data and len(data["data"]) > 0:
                    mf_data.append({
                        "name": data["meta"]["scheme_name"],
                        "latest_nav": float(data["data"][0]["nav"]),
                        "min_investment": 500  # Typical minimum SIP amount
                    })
        except Exception as e:
            print("mf fetch error", e)
    return mf_data


@app.route("/investment")
@login_required
def investment_page():
    # auto-use portfolio allocations: equity-like funds from 'investment' and 'expense' for small MF investments
    equity_budget = user_portfolio.get('investment', 0.0)
    debt_budget = user_portfolio.get('expense', 0.0)

    stocks = fetch_nifty_stocks()
    mfs = fetch_mfs()

    affordable_stocks = []
    for s in stocks:
        try:
            price = float(s.get("lastPrice") or 0)
            if price <= equity_budget and price > 0:
                affordable_stocks.append(s)
        except:
            continue

    affordable_mfs = [mf for mf in mfs if mf["min_investment"] <= max(0.0, debt_budget)]

    return render_template("investment/investment.html",
                           amount_equity=equity_budget,
                           amount_debt=debt_budget,
                           stocks=affordable_stocks,
                           mutual_funds=affordable_mfs)

# ---------- Debt & EMI Tracking ----------

def calculate_emi(principal, rate, tenure_months):
    """Calculate EMI amount"""
    if rate == 0:
        return principal / tenure_months
    
    monthly_rate = rate / 12 / 100
    emi = principal * (monthly_rate * (1 + monthly_rate) ** tenure_months) / ((1 + monthly_rate) ** tenure_months - 1)
    return round(emi, 2)

def calculate_interest_paid(principal, rate, tenure_months):
    """Calculate total interest to be paid"""
    emi = calculate_emi(principal, rate, tenure_months)
    total_payment = emi * tenure_months
    return round(total_payment - principal, 2)

def calculate_prepayment_savings(principal, rate, tenure_months, prepayment_amount):
    """Calculate savings from prepayment"""
    original_emi = calculate_emi(principal, rate, tenure_months)
    original_total = original_emi * tenure_months
    
    new_principal = principal - prepayment_amount
    if new_principal <= 0:
        return 0, 0, 0
    
    new_emi = calculate_emi(new_principal, rate, tenure_months)
    new_total = new_emi * tenure_months
    
    interest_saved = original_total - new_total - prepayment_amount
    emi_reduction = original_emi - new_emi
    
    return round(interest_saved, 2), round(emi_reduction, 2), round(new_emi, 2)

@app.route("/debts")
@login_required
def debts_page():
    """View all debts and EMIs"""
    user_id = session['user_id']
    
    # Get all active debts
    with get_db_connection() as conn:
        debts = conn.execute('''
            SELECT * FROM debts 
            WHERE user_id = ? AND status = 'active'
            ORDER BY created_at DESC
        ''', (user_id,)).fetchall()
        debts = [dict(row) for row in debts]
        
        # Calculate summary statistics
        total_outstanding = sum(debt['outstanding_amount'] for debt in debts)
        total_monthly_emi = sum(debt['emi_amount'] for debt in debts)
        total_interest_paid = 0
        
        # Get payment history for interest calculation
        for debt in debts:
            payments = conn.execute('''
                SELECT SUM(interest_paid) as total_interest 
                FROM debt_payments 
                WHERE debt_id = ?
            ''', (debt['id'],)).fetchone()
            total_interest_paid += payments['total_interest'] or 0
    
    return render_template("debts/debts.html", 
                         debts=debts,
                         total_outstanding=total_outstanding,
                         total_monthly_emi=total_monthly_emi,
                         total_interest_paid=total_interest_paid)

@app.route("/debts/add", methods=["GET", "POST"])
@login_required
def add_debt():
    """Add a new debt/EMI"""
    if request.method == "POST":
        try:
            user_id = session['user_id']
            
            # Get form data
            name = request.form['name']
            debt_type = request.form['type']
            principal_amount = float(request.form['principal_amount'])
            interest_rate = float(request.form['interest_rate'])
            start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
            payment_day = int(request.form.get('payment_day', 1))
            
            # Calculate tenure in months
            tenure_months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
            if tenure_months <= 0:
                tenure_months = 1
            
            # Calculate EMI
            emi_amount = calculate_emi(principal_amount, interest_rate, tenure_months)
            
            # Insert debt record
            with get_db_connection() as conn:
                conn.execute('''
                    INSERT INTO debts (user_id, name, type, principal_amount, outstanding_amount, 
                                     interest_rate, emi_amount, start_date, end_date, payment_day)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, name, debt_type, principal_amount, principal_amount, 
                     interest_rate, emi_amount, start_date, end_date, payment_day))
                conn.commit()
            
            flash(f"Debt '{name}' added successfully! Monthly EMI: ₹{emi_amount}", "success")
            return redirect(url_for('debts_page'))
            
        except Exception as e:
            flash(f"Error adding debt: {str(e)}", "error")
    
    return render_template("debts/add_debt.html")

@app.route("/debts/<int:debt_id>")
@login_required
def debt_details(debt_id):
    """View detailed debt information"""
    user_id = session['user_id']
    
    with get_db_connection() as conn:
        # Get debt details
        debt = conn.execute('''
            SELECT * FROM debts WHERE id = ? AND user_id = ?
        ''', (debt_id, user_id)).fetchone()
        
        if not debt:
            flash("Debt not found", "error")
            return redirect(url_for('debts_page'))
        
        debt = dict(debt)
        
        # Get payment history
        payments = conn.execute('''
            SELECT * FROM debt_payments 
            WHERE debt_id = ? 
            ORDER BY payment_date DESC
        ''', (debt_id,)).fetchall()
        payments = [dict(row) for row in payments]
        
        # Calculate statistics
        total_paid = sum(payment['amount'] for payment in payments)
        total_interest_paid = sum(payment['interest_paid'] for payment in payments)
        total_principal_paid = sum(payment['principal_paid'] for payment in payments)
        
        # Calculate remaining tenure
        if debt['outstanding_amount'] > 0:
            remaining_emi_count = int(debt['outstanding_amount'] / debt['emi_amount']) + 1
        else:
            remaining_emi_count = 0
    
    return render_template("debts/debt_details.html",
                         debt=debt,
                         payments=payments,
                         total_paid=total_paid,
                         total_interest_paid=total_interest_paid,
                         total_principal_paid=total_principal_paid,
                         remaining_emi_count=remaining_emi_count)

@app.route("/debts/<int:debt_id>/pay", methods=["POST"])
@login_required
def make_payment(debt_id):
    """Make a payment towards debt"""
    try:
        user_id = session['user_id']
        payment_amount = float(request.form['payment_amount'])
        payment_type = request.form.get('payment_type', 'emi')
        notes = request.form.get('notes', '')
        
        with get_db_connection() as conn:
            # Get debt details
            debt = conn.execute('''
                SELECT * FROM debts WHERE id = ? AND user_id = ?
            ''', (debt_id, user_id)).fetchone()
            
            if not debt:
                flash("Debt not found", "error")
                return redirect(url_for('debts_page'))
            
            debt = dict(debt)
            
            # Calculate payment breakdown
            if payment_type == 'emi':
                # Regular EMI payment
                interest_paid = debt['outstanding_amount'] * (debt['interest_rate'] / 12 / 100)
                principal_paid = payment_amount - interest_paid
                if principal_paid < 0:
                    principal_paid = 0
                    interest_paid = payment_amount
            else:
                # Prepayment - all goes to principal
                principal_paid = payment_amount
                interest_paid = 0
            
            # Update outstanding amount
            new_outstanding = max(0, debt['outstanding_amount'] - principal_paid)
            
            # Insert payment record
            conn.execute('''
                INSERT INTO debt_payments (debt_id, user_id, payment_date, amount, payment_type,
                                         principal_paid, interest_paid, remaining_balance, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (debt_id, user_id, datetime.now().date(), payment_amount, payment_type,
                 principal_paid, interest_paid, new_outstanding, notes))
            
            # Update debt outstanding amount
            conn.execute('''
                UPDATE debts SET outstanding_amount = ? WHERE id = ?
            ''', (new_outstanding, debt_id))
            
            # Check if debt is fully paid
            if new_outstanding <= 0:
                conn.execute('''
                    UPDATE debts SET status = 'closed' WHERE id = ?
                ''', (debt_id,))
                flash(f"Congratulations! Debt '{debt['name']}' has been fully paid off!", "success")
            else:
                flash(f"Payment of ₹{payment_amount} recorded successfully", "success")
            
            conn.commit()
            
    except Exception as e:
        flash(f"Error making payment: {str(e)}", "error")
    
    return redirect(url_for('debt_details', debt_id=debt_id))



@app.route("/api/calculate-prepayment", methods=["POST"])
@login_required
def calculate_prepayment():
    """API endpoint for prepayment calculations"""
    try:
        data = request.get_json()
        debt_id = int(data['debt_id'])
        prepayment_amount = float(data['prepayment_amount'])
        user_id = session['user_id']
        
        with get_db_connection() as conn:
            debt = conn.execute('''
                SELECT * FROM debts WHERE id = ? AND user_id = ?
            ''', (debt_id, user_id)).fetchone()
            
            if not debt:
                return jsonify({'error': 'Debt not found'}), 404
            
            debt = dict(debt)
            
            # Calculate remaining tenure
            end_date = datetime.strptime(debt['end_date'], '%Y-%m-%d').date()
            remaining_months = max(1, (end_date.year - datetime.now().year) * 12 + 
                                 (end_date.month - datetime.now().month))
            
            # Calculate savings
            interest_saved, emi_reduction, new_emi = calculate_prepayment_savings(
                debt['outstanding_amount'], debt['interest_rate'], remaining_months, prepayment_amount
            )
            
            return jsonify({
                'interest_saved': interest_saved,
                'emi_reduction': emi_reduction,
                'new_emi': new_emi,
                'prepayment_amount': prepayment_amount
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route("/debts/reminders")
@login_required
def debt_reminders():
    """View upcoming debt reminders - redirect to main debts page"""
    flash("Debt reminders are now available in the debt details page", "info")
    return redirect(url_for('debts_page'))

# Weather API configuration
WEATHER_API_KEY = "YOUR_OPENWEATHER_API_KEY"  # Replace with your actual API key
WEATHER_BASE_URL = "http://api.openweathermap.org/data/2.5"

# Clothing suggestion rules based on weather
CLOTHING_RULES = {
    'hot': {
        'temp_min': 30,
        'temp_max': 50,
        'suggestions': [
            'Light cotton clothes',
            'Sunglasses',
            'Hat or cap',
            'Light-colored clothing',
            'Breathable fabrics'
        ],
        'accessories': ['Sunglasses', 'Hat', 'Sunscreen']
    },
    'warm': {
        'temp_min': 20,
        'temp_max': 29,
        'suggestions': [
            'Light clothing',
            'T-shirt and shorts',
            'Light jacket for evening',
            'Comfortable shoes'
        ],
        'accessories': ['Sunglasses', 'Light scarf']
    },
    'mild': {
        'temp_min': 15,
        'temp_max': 19,
        'suggestions': [
            'Light sweater or jacket',
            'Long pants',
            'Comfortable shoes',
            'Light layers'
        ],
        'accessories': ['Light scarf', 'Umbrella']
    },
    'cool': {
        'temp_min': 10,
        'temp_max': 14,
        'suggestions': [
            'Warm sweater or jacket',
            'Long pants',
            'Closed shoes',
            'Warm layers'
        ],
        'accessories': ['Scarf', 'Gloves', 'Umbrella']
    },
    'cold': {
        'temp_min': 0,
        'temp_max': 9,
        'suggestions': [
            'Heavy jacket or coat',
            'Warm sweater',
            'Long pants',
            'Warm socks and shoes',
            'Thermal wear'
        ],
        'accessories': ['Scarf', 'Gloves', 'Hat', 'Umbrella']
    },
    'very_cold': {
        'temp_min': -50,
        'temp_max': -1,
        'suggestions': [
            'Heavy winter coat',
            'Multiple warm layers',
            'Thermal underwear',
            'Warm boots',
            'Woolen clothes'
        ],
        'accessories': ['Scarf', 'Gloves', 'Hat', 'Thermal socks']
    }
}

def get_weather_data(city="Mumbai", country_code="IN"):
    """Get current weather data from OpenWeatherMap API"""
    try:
        url = f"{WEATHER_BASE_URL}/weather"
        params = {
            'q': f"{city},{country_code}",
            'appid': WEATHER_API_KEY,
            'units': 'metric'
        }
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            # Fallback to mock data if API fails
            return get_mock_weather_data()
    except Exception as e:
        print(f"Weather API error: {e}")
        return get_mock_weather_data()

def get_mock_weather_data():
    """Generate mock weather data for demonstration"""
    current_temp = random.randint(15, 35)
    conditions = ['Clear', 'Clouds', 'Rain', 'Thunderstorm', 'Drizzle']
    condition = random.choice(conditions)
    
    return {
        'main': {
            'temp': current_temp,
            'feels_like': current_temp + random.randint(-2, 2),
            'humidity': random.randint(40, 90),
            'pressure': random.randint(1000, 1020)
        },
        'weather': [{'main': condition, 'description': condition.lower()}],
        'wind': {'speed': random.randint(0, 20)},
        'dt': int(datetime.now().timestamp()),
        'name': 'Mumbai'
    }

def get_clothing_suggestions(weather_data):
    """Generate clothing suggestions based on weather data"""
    temp = weather_data['main']['temp']
    condition = weather_data['weather'][0]['main'].lower()
    
    # Determine temperature category
    temp_category = None
    for category, rules in CLOTHING_RULES.items():
        if rules['temp_min'] <= temp <= rules['temp_max']:
            temp_category = category
            break
    
    if not temp_category:
        temp_category = 'mild'  # Default fallback
    
    suggestions = CLOTHING_RULES[temp_category]['suggestions'].copy()
    accessories = CLOTHING_RULES[temp_category]['accessories'].copy()
    
    # Add weather-specific suggestions
    if 'rain' in condition or 'drizzle' in condition:
        suggestions.append("Don't forget an umbrella 🌂")
        accessories.append("Umbrella")
    elif 'thunderstorm' in condition:
        suggestions.append("Stay indoors if possible")
        suggestions.append("Waterproof clothing")
        accessories.append("Raincoat")
    elif 'clear' in condition and temp > 25:
        suggestions.append("Apply sunscreen")
        accessories.append("Sunscreen")
    
    # Create the main suggestion message
    temp_emoji = "🔥" if temp > 30 else "☀️" if temp > 20 else "🌤️" if temp > 15 else "🌥️" if temp > 10 else "❄️"
    main_message = f"It's {temp}°C, {temp_emoji} wear {', '.join(suggestions[:2])}."
    
    if 'rain' in condition or 'drizzle' in condition:
        main_message += " It's raining, don't forget an umbrella 🌂."
    
    return {
        'main_suggestion': main_message,
        'detailed_suggestions': suggestions,
        'accessories': accessories,
        'temperature': temp,
        'condition': condition,
        'temp_category': temp_category
    }

def get_weather_history(city="Mumbai", days=7):
    """Get weather history for the past week"""
    try:
        # For demo purposes, generate mock historical data
        history_data = []
        for i in range(days):
            date_obj = datetime.now() - timedelta(days=i)
            temp = random.randint(15, 35)
            humidity = random.randint(40, 90)
            rainfall = random.randint(0, 50) if random.random() > 0.7 else 0
            
            history_data.append({
                'date': date_obj.strftime('%Y-%m-%d'),
                'temperature': temp,
                'humidity': humidity,
                'rainfall': rainfall,
                'condition': random.choice(['Clear', 'Clouds', 'Rain', 'Thunderstorm'])
            })
        
        return history_data
    except Exception as e:
        print(f"Weather history error: {e}")
        return []

def get_weather_trends(history_data):
    """Analyze weather trends from historical data"""
    if not history_data:
        return {}
    
    temps = [day['temperature'] for day in history_data]
    humidities = [day['humidity'] for day in history_data]
    rainfalls = [day['rainfall'] for day in history_data]
    
    return {
        'avg_temperature': round(sum(temps) / len(temps), 1),
        'avg_humidity': round(sum(humidities) / len(humidities), 1),
        'total_rainfall': sum(rainfalls),
        'temp_trend': 'increasing' if temps[0] > temps[-1] else 'decreasing' if temps[0] < temps[-1] else 'stable',
        'rainy_days': len([r for r in rainfalls if r > 0])
    }

@app.route('/weather')
@login_required
def weather_page():
    """Weather and clothing suggestions page"""
    try:
        # Get current weather
        weather_data = get_weather_data()
        clothing_suggestions = get_clothing_suggestions(weather_data)
        
        # Get weather history
        weather_history = get_weather_history()
        weather_trends = get_weather_trends(weather_history)
        
        return render_template('weather/weather.html',
                             weather_data=weather_data,
                             clothing_suggestions=clothing_suggestions,
                             weather_history=weather_history,
                             weather_trends=weather_trends)
    except Exception as e:
        flash(f"Error loading weather data: {str(e)}", "error")
        return redirect(url_for('dashboard'))

@app.route('/api/weather/current')
@login_required
def api_current_weather():
    """API endpoint for current weather data"""
    try:
        city = request.args.get('city', 'Mumbai')
        weather_data = get_weather_data(city)
        clothing_suggestions = get_clothing_suggestions(weather_data)
        
        return jsonify({
            'weather': weather_data,
            'clothing_suggestions': clothing_suggestions
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/weather/history')
@login_required
def api_weather_history():
    """API endpoint for weather history"""
    try:
        days = int(request.args.get('days', 7))
        city = request.args.get('city', 'Mumbai')
        history_data = get_weather_history(city, days)
        trends = get_weather_trends(history_data)
        
        return jsonify({
            'history': history_data,
            'trends': trends
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Create SQLAlchemy tables
    init_db()  # Initialize database tables
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
