# Импорты
import token

from flask import Flask, render_template, request, redirect, session
import sqlite3
import smtplib
from email.mime.text import MIMEText
import os
from datetime import datetime
from dotenv import load_dotenv
import secrets
import time
import hashlib
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # Секретный ключ для сессии
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0




# Загружаем переменные окружения из .env файла
load_dotenv()

# Подключение к базе данных
conn = sqlite3.connect('users.db', check_same_thread=False)
cur = conn.cursor()

# Создание таблицы пользователей
cur.execute('''CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            password TEXT,
            last_login TIMESTAMP
)''')

# Создание таблицы постов


# Создание таблицы уведомлений
cur.execute('''CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
)''')

# Таблица подписчиков на события (email подписки)
cur.execute('''CREATE TABLE IF NOT EXISTS subscribers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

# Локальная таблица входящих уведомлений (локальный inbox)
cur.execute('''CREATE TABLE IF NOT EXISTS inbox_entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_email TEXT,
            subject TEXT,
            body TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')



# Создание таблицы категорий
cur.execute('''CREATE TABLE IF NOT EXISTS categories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT
)''')

# Создание таблицы постов
cur.execute('''CREATE TABLE IF NOT EXISTS posts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                content TEXT,
                user_id INTEGER,
                category_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (category_id) REFERENCES categories(id)

)''')





# Сохранение изменений в базе данных
conn.commit()


default_categories = [
    ('Программирование', 'Статьи о программировании и разработке'),
    ('Дизайн', 'Статьи о дизайнее и UX/UI'),
    ('Путешествия', 'Рассказы о путешествиях'),
    ('Кулинария', 'Рецепты и кулинарные советы'),
    ('Спорт', 'Новости и статьи о спорте')
]

for category in default_categories:
    cur.execute('INSERT OR IGNORE INTO categories(name, description) VALUES (?, ?)', category)



def get_all_categories():
    cur.execute('SELECT * FROM categories ORDER BY name')
    return cur.fetchall()

def get_all_users():
    cur.execute('SELECT * FROM users')
    return cur.fetchall()



def get_posts_by_category(category_id):
    cur.execute('''SELECT posts.*, users.name, categories.name as category_name
                    FROM posts
                    JOIN users ON posts.user_id = users.id
                    LEFT JOIN categories ON posts.category_id = categories.id
                    WHERE posts.category_id = ?
                    ORDER BY posts.created_at DESC''',
                [category_id])
    return cur.fetchall()



# Создает токен аутентификации
def create_auth_token(user_id, remember=False):
    token = secrets.token_hex(32)
    if remember:
        expires_at = time.time() + 30 * 24 * 60 * 60 # 30 дней
    else:
        expires_at = time.time() + 60 * 60 # 1 час
    cur.execute('INSERT INTO auth_tokens(user_id, token, expires_at) VALUES (?, ?, ?);',
        [user_id, token, expires_at])
    conn.commit()
    return token

# Проверяет токен аутентификации
def validate_auth_token(token):
    cur.execute('SELECT user_id FROM auth_tokens WHERE token = ? AND expires_at > ?', [token, time.time()])
    result = cur.fetchone()
    if result:
        return result[0]
    return None

# Обновляет время последнего входа
def update_last_login(user_id):
    last_login = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute('UPDATE users SET last_login = ? WHERE id = ?', [last_login, user_id])
    conn.commit()



# Функция отправки welcome-письма
def send_welcome_email(to_email, username):
    # Получаем данные из переменных окружения
    from_email = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")    
    # Проверяем, что переменные загружены
    if not from_email or not password:
        print("ОШИБКА: EMAIL_USER или EMAIL_PASSWORD не установлены в переменных окружения!")
        return False
    subject = "Добро пожаловать в наш блог!"
    body = f"""
    Привет, {username}!
    Спасибо за регистрацию в нашем блоге.
    С уважением,
    Команда блога
    """
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email    
    try:
        # Настройки для Gmail
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Включаем шифрование
        server.login(from_email, password)
        server.send_message(msg)
        server.quit()        
        print(f"  Письмо успешно отправлено на {to_email}")
        return True
    except smtplib.SMTPAuthenticationError:
        print(" Ошибка аутентификации. Проверьте email и пароль приложения.")
    except Exception as e:
        print(f" Ошибка отправки письма: {e}")   
    return False


# Универсальная функция отправки уведомлений подписчикам и записи в локальный inbox
def send_notification_email(to_email, subject, body):
    from_email = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")
    if not from_email or not password:
        print("ОШИБКА: EMAIL_USER или EMAIL_PASSWORD не установлены в переменных окружения!")
        return False
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(from_email, password)
        server.send_message(msg)
        server.quit()
        # Сохраняем в локальный inbox для истории
        try:
            cur.execute('INSERT INTO inbox_entries(recipient_email, subject, body) VALUES (?, ?, ?)',
                        [to_email, subject, body])
            conn.commit()
        except Exception as e:
            print(f"Не удалось записать в inbox_entries: {e}")
        print(f"  Уведомление успешно отправлено на {to_email}")
        return True
    except Exception as e:
        print(f"Ошибка при отправке уведомления на {to_email}: {e}")
        return False


# Создание таблицы токенов аутентификации
cur.execute("""CREATE TABLE IF NOT EXISTS auth_tokens(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    token TEXT UNIQUE,
    expires_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
)""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON posts(user_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_notif_user_id ON notifications(user_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_token ON auth_tokens(token)")

cur.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON posts(user_id)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_notif_user_id ON notifications(user_id)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_token ON auth_tokens(token)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_category_id ON posts(category_id)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_post_title ON posts(title)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_post_content ON posts(content)')

cur.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON posts(user_id)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_notif_user_id ON notifications(user_id)')
cur.execute('CREATE INDEX IF NOT EXISTS idx_subscriber_email ON subscribers(email)')

# Функция для поиска постов
def search_posts(query):
    search_pattern = f'%{query}%'
    cur.execute('''SELECT posts.*, users.name, categories.name as category_name
                    FROM posts
                    JOIN users ON posts.user_id = users.id
                    LEFT JOIN categories ON posts.category_id = categories.id
                    WHERE posts.title LIKE ? OR posts.content LIKE ?
                    ORDER BY posts.created_at DESC''',
                [search_pattern, search_pattern])
    return cur.fetchall()

# Добавление/удаление/получение подписчиков
def add_subscriber(email):
    try:
        cur.execute('INSERT INTO subscribers(email) VALUES (?)', [email])
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Уже подписан
        return False
    except Exception as e:
        print(f"Ошибка при добавлении подписчика: {e}")
        return False


def remove_subscriber(email):
    cur.execute('DELETE FROM subscribers WHERE email = ?', [email])
    conn.commit()


def get_subscribers():
    cur.execute('SELECT email FROM subscribers')
    return [r[0] for r in cur.fetchall()]


# Уведомление всех подписчиков о новой регистрации
def notify_subscribers_about_new_user(new_name, new_email):
    subscribers = get_subscribers()
    subject = "Новый пользователь зарегистрировался"
    body = f"Пользователь {new_name} зарегистрировался с почтой: {new_email}"
    for s in subscribers:
        sent = send_notification_email(s, subject, body)
        # Логируем каждое уведомление в таблице notifications (user_id NULL для внешних подписчиков)
        status = 'sent' if sent else 'failed'
        try:
            cur.execute('INSERT INTO notifications(user_id, action, details) VALUES (?, ?, ?)',
                        [None, 'new_user_registered', f'{new_name} <{new_email}> -> {s} : {status}'])
            conn.commit()
        except Exception as e:
            print(f"Не удалось залогировать уведомление: {e}")

# Добавляет нового пользователя и возвращает его ID
def add_user(name, email, password):
    cur.execute('INSERT INTO users(name, email, password) VALUES (?, ?, ?)', [name, email, password])
    conn.commit()
    cur.execute('SELECT id FROM users WHERE email = ?', [email])
    return cur.fetchone()[0]

# Возвращает пользователя по его ID
def get_user_by_id(user_id):
    cur.execute('SELECT * FROM users WHERE id = ?', [user_id])
    return cur.fetchone()

# Возвращает пользователя по его электронной почте
def get_user_by_email(email):
    cur.execute('SELECT * FROM users WHERE email = ?', [email])
    return cur.fetchone()

# Добавляет новый пост с привязкой к пользователю
def add_new_post(title, content, user_id, category_id):
    cur.execute('INSERT INTO posts(title, content, user_id, category_id) VALUES (?, ?, ?, ?)',[title, content, user_id, category_id])
    conn.commit()

# Возвращает посты пользователя
def get_posts_by_user(user_id):
    cur.execute('SELECT * FROM posts WHERE user_id = ? ORDER BY created_at DESC', [user_id])
    return cur.fetchall()

# Логирует уведомление
def log_notification(user_id, action, details):
    cur.execute('INSERT INTO notifications(user_id, action, details) VALUES (?, ?, ?)',
                [user_id, action, details])
    conn.commit()

# Возвращает уведомления пользователя
def get_notifications_by_user(user_id):
    cur.execute('SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC', [user_id])
    return cur.fetchall()

def delete_auth_token(token):
    cur.execute('DELETE FROM auth_tokens WHERE token = ?', [token])
    conn.commit()

# Middleware для проверки аутентификации
@app.before_request
def check_auth():
    if 'user_id' not in session:
        token = request.cookies.get('auth_token')
        if token:
            user_id = validate_auth_token(token)
            if user_id:
                user = get_user_by_id(user_id)
                if user:
                    session['user_id'] = user[0]  # исправлено с user[e] на user[0]
                    session['user_name'] = user[1]

# Удаляет токен аутентификации


# Выход из системы








  





# Рендерим стартовую страницу
@app.route('/')
def main():
    cur.execute('''SELECT posts.*, users.name, categories.name as category_name
                   FROM posts
                   JOIN users ON posts.user_id = users.id
                   LEFT JOIN categories ON posts.category_id = categories.id
                   ORDER BY posts.created_at DESC''')
    posts = cur.fetchall()
    users = get_all_users()

    user_name = None
    if 'user_id' in session:
        user_name = session['user_name']

    return render_template('main.html', posts=posts, users=users, user_name=user_name)

@app.route('/logout')
def logout():
    token = request.cookies.get('auth_token')
    if token:
        delete_auth_token(token)
    session.clear()
    response = redirect('/')
    response.set_cookie('auth_token', '', expires=0)
    return response

# Подписка на уведомления о новых пользователях
@app.route('/subscribe/', methods=['GET', 'POST'])
def subscribe():
    message = None
    if request.method == 'POST':
        email = request.form.get('email')
        if email:
            added = add_subscriber(email)
            if added:
                send_notification_email(email, 'Подписка оформлена', 'Вы подписаны на уведомления о новых пользователях.')
                message = 'Подписка успешно оформлена.'
            else:
                message = 'Этот email уже подписан.'
    return render_template('subscribe.html', message=message)


# Отписка от уведомлений
@app.route('/unsubscribe/', methods=['GET', 'POST'])
def unsubscribe():
    message = None
    if request.method == 'POST':
        email = request.form.get('email')
        if email:
            remove_subscriber(email)
            message = 'Email удалён из подписчиков (если он там был).'
    return render_template('unsubscribe.html', message=message)


# Просмотр списка подписчиков (простая страница)
@app.route('/subscribers/')
def subscribers_list():
    subs = get_subscribers()
    return render_template('subscribers.html', subscribers=subs)

# Регистрация пользователя
@app.route('/register/', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        user = get_user_by_email(email)
        if user is None:
            user_id = add_user(name, email, password)
            # Отправляем письмо
            email_sent = send_welcome_email(email, name)            
            # Логируем действие
            if email_sent:
                log_notification(user_id, 'welcome_email_sent', 
                               f'Приветственное письмо отправлено на {email}')
            else:
                log_notification(user_id, 'welcome_email_failed', 
                               f'Не удалось отправить письмо на {email}')           
            # Уведомляем подписчиков о новой регистрации
            try:
                notify_subscribers_about_new_user(name, email)
            except Exception as e:
                print(f"Ошибка при уведомлении подписчиков: {e}")
            return redirect('/login/')
        else:
            print('Такой пользователь уже есть')
    return render_template('register.html')

# Процесс входа
@app.route('/login/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'  # Проверяем, установлен ли флажок "Запомнить меня"
        user = get_user_by_email(email)
        if user is None:
            return render_template('login.html', message="Нет такой почты")
        if user[3] == password:
            print('Вход выполнен')
            # Сохраняем ID пользователя в сессии
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            update_last_login(user[0])  # Обновляем время последнего входа
            if remember: 
                token = create_auth_token(user[0], remember=True)
                response = redirect('/profile')
                response.set_cookie('auth_token', token, max_age=30*24*60*60)  # 30 дней
            else:
                response = redirect('/profile')
            log_notification(user[0], 'login', 'Пользователь вошел в систему')
            return response
        else:
            return render_template('login.html', message="Пароль неверный")
    return render_template('login.html')  

# Профиль текущего пользователя
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect('/login/')
    user_id = session['user_id']
    user = get_user_by_id(user_id)
    posts = get_posts_by_user(user_id)
    notifications = get_notifications_by_user(user_id)
    if user:
        return render_template('profile.html', user=user, posts=posts, notifications=notifications)
    return "Пользователь не найден", 404


# Маршрут для поиска
@app.route('/search')
def search():
    query = request.args.get('q', '').strip()

    if query:
        posts = search_posts(query)
        return render_template('main.html',
                               posts=posts,
                               users=get_all_users(),
                               user_name=session.get('user_name'),
                               search_query=query)

    return redirect('/')

# Маршрут для отображения постов по категории
@app.route('/category/<int:category_id>')
def category_posts(category_id):
    posts = get_posts_by_category(category_id)
    # Получаем информацию о категории
    cur.execute('SELECT * FROM categories WHERE id = ?', [category_id])
    category = cur.fetchone()
    if not category:
        return "Категория не найдена", 404
    return render_template('category.html',
                           posts=posts,
                           category=category,
                           user_name=session.get('user_name'))



# Страница пользователя
@app.route('/user/<int:user_id>')
def user_page(user_id):
    user = get_user_by_id(user_id)
    posts = get_posts_by_user(user_id)
    notifications = get_notifications_by_user(user_id)
    if user:
        return render_template('user_page.html', user=user, posts=posts, notifications=notifications)
    return "Пользователь не найден", 404

# Добавление поста
@app.route('/add_post', methods=['GET', 'POST'])
def add_post():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        category_id = request.form.get('category')
        if 'user_id' in session:
            user_id = session['user_id']
        else:
            return redirect('/login/')
        add_new_post(title, content, user_id, category_id)
        # Получаем название категории для лога
        cur.execute('SELECT name FROM categories WHERE id = ?', [category_id])
        category_name = cur.fetchone()
        category_name = category_name[0] if category_name else 'Неизвестно'

        log_notification(user_id, 'new_post', 
                         f'Создан пост "{title}" в категории "{category_name}"')
        return redirect('/')
    # При GET-запросе передаем категории в шаблон
    categories = get_all_categories()
    return render_template('new_post.html', categories=categories)

if __name__ == '__main__':
    app.run()