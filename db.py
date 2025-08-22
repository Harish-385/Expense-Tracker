import sqlite3
 
from contextlib import contextmanager

DATABASE = 'tracker.db'

@contextmanager
def get_db_connection():
    """Create a database connection with context management"""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def init_db():
    """Initialize database tables"""
    with get_db_connection() as conn:
        cur = conn.cursor()

        # Users table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Expenses table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            type TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        # Savings goals
        cur.execute("""
        CREATE TABLE IF NOT EXISTS savings_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target REAL NOT NULL,
            progress REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        # Portfolio allocations
        cur.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            user_id INTEGER PRIMARY KEY,
            needs REAL DEFAULT 0,
            wants REAL DEFAULT 0,
            savings REAL DEFAULT 0,
            monthly_income REAL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        # Bills table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            due_date TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'unpaid',
            category TEXT DEFAULT 'Bills',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        # Investment table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            symbol TEXT,
            amount_invested REAL NOT NULL,
            units REAL,
            purchase_price REAL,
            current_price REAL,
            purchase_date TEXT NOT NULL,
            investment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        # Investment goals table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS investment_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target_amount REAL NOT NULL,
            target_date TEXT NOT NULL,
            current_amount REAL DEFAULT 0,
            monthly_contribution REAL DEFAULT 0,
            risk_profile TEXT DEFAULT 'moderate',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        # Investment transactions table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS investment_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            investment_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            amount REAL NOT NULL,
            units REAL,
            price_per_unit REAL,
            transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fees REAL DEFAULT 0,
            notes TEXT,
            FOREIGN KEY(investment_id) REFERENCES investments(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        # Risk profile table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS risk_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            risk_tolerance TEXT DEFAULT 'moderate',
            investment_horizon TEXT DEFAULT 'medium',
            investment_experience TEXT DEFAULT 'beginner',
            monthly_investment_capacity REAL DEFAULT 0,
            emergency_fund_available BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        # Debt tracking tables
        cur.execute("""
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,  -- 'loan', 'credit_card', 'emi', 'mortgage'
            principal_amount REAL NOT NULL,
            outstanding_amount REAL NOT NULL,
            interest_rate REAL NOT NULL,
            emi_amount REAL NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            payment_day INTEGER DEFAULT 1,  -- Day of month for payment
            status TEXT DEFAULT 'active',  -- 'active', 'closed', 'defaulted'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS debt_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debt_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            payment_date TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_type TEXT DEFAULT 'emi',  -- 'emi', 'prepayment', 'late_fee'
            principal_paid REAL NOT NULL,
            interest_paid REAL NOT NULL,
            remaining_balance REAL NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (debt_id) REFERENCES debts (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS debt_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            debt_id INTEGER NOT NULL,
            reminder_date TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',  -- 'pending', 'paid', 'overdue'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (debt_id) REFERENCES debts (id)
        )
        """)

        conn.commit()
