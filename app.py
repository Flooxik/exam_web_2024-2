from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import current_user, LoginManager, UserMixin, login_user, logout_user, login_required
from mysql_db import MySQL
import mysql.connector
from functools import wraps
import hashlib
import os

app = Flask(__name__)
application = app
 
app.config.from_pyfile('config.py')

db = MySQL(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Для доступа необходимо пройти аутентификацию'
login_manager.login_message_category = 'warning'

class User(UserMixin):
    def __init__(self, user_id, user_login, role_id, first_name, last_name):
        self.id = user_id
        self.login = user_login
        self.role_id = role_id
        self.first_name = first_name
        self.last_name = last_name

def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_view(*args, **kwargs):
            if current_user.role_id not in roles:
                flash('У вас недостаточно привилегий!', 'warning')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_view
    return decorator

@login_manager.user_loader
def load_user(user_id):
    query = 'SELECT user_id, login, role_id, first_name, last_name FROM users WHERE user_id = %s'

    with db.connection().cursor(named_tuple=True) as cursor:
        cursor.execute(query, (user_id,))
        user = cursor.fetchone()

        return User(user.user_id, user.login, user.role_id, user.first_name, user.last_name) if user else None

@app.route('/')
def index():
    name_filter = request.args.get('name')
    genre_filter = request.args.getlist('genre')
    year_filter = request.args.getlist('year')
    volume_from = request.args.get('volume_from')
    volume_to = request.args.get('volume_to')
    author_filter = request.args.get('author')

    query = '''SELECT a.*, b.filename, g.genre
               FROM books a 
               JOIN book_img b ON a.fk_imgid = b.id
               LEFT JOIN genres g ON a.fk_genre = g.genre_id
               WHERE 1=1'''
    
    filters = []

    if name_filter:
        query += ' AND a.name LIKE %s'
        filters.append(f'%{name_filter}%')

    if genre_filter:
        query += ' AND a.fk_genre IN (%s)' % ','.join(['%s'] * len(genre_filter))
        filters.extend(genre_filter)

    if year_filter:
        query += ' AND a.year IN (%s)' % ','.join(['%s'] * len(year_filter))
        filters.extend(year_filter)

    if volume_from:
        query += ' AND a.length >= %s'
        filters.append(volume_from)

    if volume_to:
        query += ' AND a.length <= %s'
        filters.append(volume_to)

    if author_filter:
        query += ' AND a.author LIKE %s'
        filters.append(f'%{author_filter}%')

    query += ' ORDER BY a.year DESC'

    try:
        with db.connection().cursor(named_tuple=True) as cursor:
            cursor.execute(query, filters)
            books = cursor.fetchall()
            book_list = []
            for book in books:
                book_dict = {
                    'id': book.book_id,
                    'name': book.name,
                    'description': book.description,
                    'year': book.year,
                    'publisher': book.publisher,
                    'author': book.author,
                    'length': book.length,
                    'imgname': book.filename,
                    'genre': book.genre
                }
                book_list.append(book_dict)

    except mysql.connector.Error as err:
        flash(f'Ошибка БД: {err}', 'danger')

    genre_query = 'SELECT * FROM genres'
    with db.connection().cursor(named_tuple=True) as cursor:
        cursor.execute(genre_query)
        genres = cursor.fetchall()

    year_query = 'SELECT DISTINCT year FROM books ORDER BY year'
    with db.connection().cursor(named_tuple=True) as cursor:
        cursor.execute(year_query)
        years = [row.year for row in cursor.fetchall()]

    return render_template('index.html', 
                           book_list=book_list, 
                           genres=genres, 
                           years=years,
                           selected_genres=[int(g) for g in genre_filter],
                           selected_years=year_filter)


@app.route('/logout', methods=['GET'])
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':

        login = request.form['login']
        password = request.form['password_hash']
        check = request.form.get('remember') == 'on'

        query = 'SELECT user_id, login, role_id, first_name, last_name FROM users WHERE login=%s AND password_hash=SHA2(%s, 256)'
        
        try:
            with db.connection().cursor(named_tuple=True) as cursor:
                cursor.execute(query, (login, password))
                user = cursor.fetchone()
                
                if user:
                    login_user(User(user.user_id, user.login, user.role_id, user.first_name, user.last_name), remember=check)
                    flash('Вы успешно вошли!', 'success')
                    return redirect(url_for('index'))
                else:
                    flash('Неверные учетные данные.', 'danger')

        except mysql.connector.Error:
            flash('Ошибка БД! Обратитесь к администратору.', 'danger')
            
    return render_template('login.html')

@app.route('/book/<int:book_id>')
@login_required
def book_details(book_id):
    query = '''SELECT a.*, b.filename, g.genre 
    FROM books a 
    JOIN book_img b ON a.fk_imgid = b.id
    LEFT JOIN genres g ON a.fk_genre = g.genre_id
    WHERE a.book_id = %s'''
    try:
        with db.connection().cursor(named_tuple=True) as cursor:
            cursor.execute(query, (book_id,))
            book = cursor.fetchone()
            if book:
                book_dict = {
                    'book_id': book[0],
                    'name': book[1],
                    'description': book[2],
                    'year': book[3],
                    'publisher': book[4],
                    'author': book[5],
                    'length': book[6],
                    'imgname': str(book[7]) + '.webp',
                    'genre': book.genre
                }
                query = 'SELECT * FROM review WHERE book_id = %s'
                with db.connection().cursor(named_tuple=True) as cursor:
                    cursor.execute(query, (book_id,))
                    reviews = cursor.fetchall()
                return render_template('book/book_details.html', book=book_dict, reviews=reviews)
            else:
                flash('Книга не найдена', 'danger')
                return redirect(url_for('index'))
    except mysql.connector.Error:
        flash('Ошибка БД! Обратитесь к администратору.', 'danger')
        return redirect(url_for('index'))

@app.route('/book/add', methods=['POST', 'GET'])
@login_required
@roles_required(1)
def book_add():
    
    if request.method == 'POST':
        img = request.files['cover']
        book_name = request.form['book_name']
        description = request.form['description']
        year = request.form['year']
        publisher = request.form['publisher']
        author = request.form['author']
        length = request.form['length']
        genre_input = request.form['genre']  # Получаем введенный жанр
        
        if img:
            img_name = img.filename
            mime_type = img.mimetype
            img_hash = hashlib.md5(img.read()).hexdigest()
            img.seek(0) 
            
            img_query = 'INSERT INTO book_img (filename, mime_type, md5_hash) VALUES (%s, %s, %s)'
            book_query = 'INSERT INTO books (name, description, year, publisher, author, length, fk_imgid, fk_genre) VALUES (%s, %s, %s, %s, %s, %s, LAST_INSERT_ID(), %s)'
            genre_check_query = 'SELECT genre_id FROM genres WHERE genre = %s'
            genre_insert_query = 'INSERT INTO genres (genre) VALUES (%s)'
            
            try:
                with db.connection().cursor(named_tuple=True) as cursor:
                    cursor.execute(img_query, (img_name, mime_type, img_hash))
                    cursor.execute(genre_check_query, (genre_input,))
                    genre = cursor.fetchone()
                    
                    if genre:
                        genre_id = genre.genre_id
                    else:
                        cursor.execute(genre_insert_query, (genre_input,))
                        genre_id = cursor.lastrowid
                    cursor.execute(book_query, (book_name, description, year, publisher, author, length, genre_id))
                    
                    db.connection().commit()
                    
                    flash('Книга успешно добавлена!', 'success')
                    return redirect(url_for('index'))
            
            except mysql.connector.Error as err:
                flash(err, 'danger')
        else:
            flash('Обложка отсутствует!', 'danger')

    return render_template('book/book_add.html')

@app.route('/book/edit/<int:book_id>', methods=['POST', 'GET'])
@login_required
@roles_required(1, 2)
def book_edit(book_id):
    if request.method == 'POST':
        
        book_name = request.form['book_name']
        description = request.form['description']
        year = request.form['year']
        publisher = request.form['publisher']
        author = request.form['author']
        length = request.form['length']
        genre_input = request.form['genre']

        query = 'UPDATE `books` SET `name`= %s, `description`= %s, `year`=%s, `publisher`= %s, `author`= %s, `length`= %s, `fk_genre`= %s WHERE `book_id` = %s'
        genre_check_query = 'SELECT genre_id FROM genres WHERE genre = %s'
        genre_insert_query = 'INSERT INTO genres (genre) VALUES (%s)'
        
        try:
            with db.connection().cursor(named_tuple=True) as cursor:
                cursor.execute(genre_check_query, (genre_input,))
                genre = cursor.fetchone()
                
                if genre:
                    genre_id = genre.genre_id
                else:
                    cursor.execute(genre_insert_query, (genre_input,))
                    genre_id = cursor.lastrowid
                cursor.execute(query, (book_name, description, year, publisher, author, length, genre_id, book_id))
                db.connection().commit()
                
                flash('Данные о книге успешно обновлены!', 'success')
                return redirect(url_for('index'))
        
        except mysql.connector.Error as err:
            flash(err, 'danger')
    
    return render_template('book/book_edit.html')



@app.route('/book/delete/<int:book_id>', methods=['POST'])
@login_required
@roles_required(1)
def book_delete(book_id):
    if request.form['confirm'] == 'confirm':
        try:
            query = 'DELETE FROM books WHERE book_id = %s'
            with db.connection().cursor() as cursor:
                cursor.execute(query, (book_id,))
                db.connection().commit()
            
            query = 'SELECT MAX(book_id) FROM books'
            with db.connection().cursor() as cursor:
                cursor.execute(query)
                max_id = cursor.fetchone()[0]
                
            new_auto_increment = max_id + 1 if max_id else 1
            query = 'ALTER TABLE books AUTO_INCREMENT = %s'
            with db.connection().cursor() as cursor:
                cursor.execute(query, (new_auto_increment,))
                db.connection().commit()
            
            flash('Книга успешно удалена.', 'success')
        except mysql.connector.Error as err:
            flash(str(err), 'danger')

        return redirect(url_for('index'))


@app.route('/book/<int:book_id>/review', methods=['GET', 'POST'])
@login_required
def create_review(book_id):
    query = 'SELECT a.*, b.filename FROM books a JOIN book_img b ON a.fk_imgid = b.id WHERE a.book_id = %s'
    try:
        with db.connection().cursor(named_tuple=True) as cursor:
            cursor.execute(query, (book_id,))
            book = cursor.fetchone()
            if not book:
                flash('Книга не найдена', 'danger')
                return redirect(url_for('index'))
            
            book_dict = {
                'book_id': book[0],
                'name': book[1],
                'description': book[2],
                'year': book[3],
                'publisher': book[4],
                'author': book[5],
                'length': book[6],
                'imgname': str(book[7]) + '.webp'
            }
            
    except mysql.connector.Error as err:
        flash('Ошибка БД!', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        score = request.form['score']
        text = request.form['text']
        user_id = current_user.id

        query = 'SELECT * FROM review WHERE book_id = %s AND user_id = %s'
        with db.connection().cursor(named_tuple=True) as cursor:
            cursor.execute(query, (book_id, user_id))
            if cursor.fetchone():
                flash('Вы уже написали рецензию для этой книги.', 'warning')
                return redirect(url_for('book_details', book_id=book_id))

        query = 'INSERT INTO review (book_id, user_id, score, text) VALUES (%s, %s, %s, %s)'
        with db.connection().cursor(named_tuple=True) as cursor:
            cursor.execute(query, (book_id, user_id, score, text))
            db.connection().commit()
            flash('Рецензия успешно создана!', 'success')
            return redirect(url_for('book_details', book_id=book_id))

    return render_template('book/review_write.html', book=book_dict)

if __name__ == '__main__':
    app.run(debug=True)
