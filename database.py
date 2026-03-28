import sqlite3
import hashlib
import json
from datetime import datetime

# --- FUNKCJE BAZY DANYCH ---

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    conn = sqlite3.connect('osce_history.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS results 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT, 
                  date TEXT, 
                  score INTEGER)''')
                  
    try:
        c.execute("ALTER TABLE results ADD COLUMN history TEXT")
    except sqlite3.OperationalError:
        pass 
        
    try:
        c.execute("ALTER TABLE results ADD COLUMN category TEXT DEFAULT 'inne'")
    except sqlite3.OperationalError:
        pass 

    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, 
                  password_hash TEXT)''')
                  
    # --- NOWE KOLUMNY W TABELI USERS ---
    try:
        c.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass 
        
    try:
        c.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'Polski'")
    except sqlite3.OperationalError:
        pass 
        
    conn.commit()
    conn.close()

# --- STARE FUNKCJE (PRZYWRÓCONE) ---

def register_user(username, password):
    if not username or not password:
        return False
    conn = sqlite3.connect('osce_history.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", 
                  (username, hash_password(password)))
        conn.commit()
        sukces = True
    except sqlite3.IntegrityError:
        sukces = False
    conn.close()
    return sukces

def login_user(username, password):
    conn = sqlite3.connect('osce_history.db')
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    if result and result[0] == hash_password(password):
        return True
    return False

def update_password(username, old_password, new_password):
    if login_user(username, old_password):
        conn = sqlite3.connect('osce_history.db')
        c = conn.cursor()
        c.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                  (hash_password(new_password), username))
        conn.commit()
        conn.close()
        return True
    return False

# --- NOWE FUNKCJE BAZODANOWE ---

def update_user_email(username, email):
    conn = sqlite3.connect('osce_history.db')
    c = conn.cursor()
    c.execute("UPDATE users SET email = ? WHERE username = ?", (email, username))
    conn.commit()
    conn.close()

def update_user_language(username, language):
    conn = sqlite3.connect('osce_history.db')
    c = conn.cursor()
    c.execute("UPDATE users SET language = ? WHERE username = ?", (language, username))
    conn.commit()
    conn.close()

def get_user_info(username):
    """Pobiera dodatkowe dane użytkownika po zalogowaniu"""
    conn = sqlite3.connect('osce_history.db')
    c = conn.cursor()
    c.execute("SELECT email, language FROM users WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    if result:
        return {"email": result[0], "language": result[1]}
    return {"email": "", "language": "Polski"}

def delete_user_account(username):
    """Usuwa konto i wszystkie powiązane z nim wyniki"""
    conn = sqlite3.connect('osce_history.db')
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE username = ?", (username,))
    c.execute("DELETE FROM results WHERE username = ?", (username,)) # Usuwa też wyniki
    conn.commit()
    conn.close()

def save_result_to_db(username, score, history_messages, category="inne"):
    if not username or username == "":
        return
    conn = sqlite3.connect('osce_history.db')
    c = conn.cursor()

    historia_json = json.dumps(history_messages)
    c.execute("INSERT INTO results (username, date, score, history, category) VALUES (?, ?, ?, ?, ?)",
              (username, datetime.now().strftime("%Y-%m-%d %H:%M"), score, historia_json, category))
    conn.commit()
    conn.close()

init_db()
