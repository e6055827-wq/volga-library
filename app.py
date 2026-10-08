import os
import uuid
from datetime import datetime, timedelta, date
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session, abort)
from flask_login import (LoginManager, UserMixin, login_user, login_required,
                         logout_user, current_user)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

# ==============================
# НАСТРОЙКА
# ==============================
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-me')

# База: SQLite локально, PostgreSQL через DATABASE_URL (pg8000)
uri = os.environ.get('DATABASE_URL', 'sqlite:///library.db')

if uri.startswith('postgres://'):
    uri = uri.replace('postgres://', 'postgresql://', 1)

if uri.startswith('postgresql://'):
    uri = uri.replace('postgresql://', 'postgresql+pg8000://', 1)

if uri.startswith('postgresql+pg8000://') and '?' in uri:
    base, params = uri.split('?', 1)
    keep = [p for p in params.split('&') if p.startswith('sslmode=')]
    uri = base + ('?' + '&'.join(keep) if keep else '')

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

COVERS_DIR = os.path.join('static', 'covers')
os.makedirs(COVERS_DIR, exist_ok=True)


# ==============================
# МОДЕЛИ
# ==============================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(200))


class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False)
    class_num = db.Column(db.Integer, nullable=False)
    class_letter = db.Column(db.String(2), nullable=False)

    @property
    def class_code(self):
        return f"{self.class_num}{self.class_letter}"


class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    author = db.Column(db.String(200))
    category = db.Column(db.String(50), nullable=False)
    publisher = db.Column(db.String(150))
    year = db.Column(db.Integer)
    isbn = db.Column(db.String(50))
    pages = db.Column(db.Integer)
    udc = db.Column(db.String(50))
    bbk = db.Column(db.String(50))
    annotation = db.Column(db.Text)
    total_copies = db.Column(db.Integer, default=1)
    available_copies = db.Column(db.Integer, default=1)
    cover_url = db.Column(db.String(500))
    cover_file = db.Column(db.String(300))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)


class Loan(db.Model):
    __tablename__ = 'loans'
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=False)
    returned_at = db.Column(db.DateTime)
    issued_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    book = db.relationship('Book')
    student = db.relationship('Student')


class Reservation(db.Model):
    __tablename__ = 'reservations'
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    reserved_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='active')

    book = db.relationship('Book')
    student = db.relationship('Student')


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    audience = db.Column(db.String(30), nullable=False)
    audience_value = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))


class NotificationRead(db.Model):
    __tablename__ = 'notification_reads'
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey('notifications.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow)


class ReadingList(db.Model):
    __tablename__ = 'reading_lists'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    target_class = db.Column(db.String(10))
    deadline = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    teacher = db.relationship('User')
    items = db.relationship('ReadingListItem', backref='reading_list',
                            cascade='all, delete-orphan')


class ReadingListItem(db.Model):
    __tablename__ = 'reading_list_items'
    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey('reading_lists.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    note = db.Column(db.String(500))

    book = db.relationship('Book')


class StudentReadingProgress(db.Model):
    __tablename__ = 'student_reading_progress'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('reading_list_items.id'), nullable=False)
    read_at = db.Column(db.DateTime)
    teacher_grade = db.Column(db.Integer)
    comment = db.Column(db.Text)


class History(db.Model):
    __tablename__ = 'history'
    id = db.Column(db.Integer, primary_key=True)
    actor_type = db.Column(db.String(20))
    actor_id = db.Column(db.Integer)
    action = db.Column(db.String(50))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ==============================
# АВТОРИЗАЦИЯ
# ==============================
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def role_required(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('Недостаточно прав', 'error')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return wrapper
    return deco


def student_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'student_id' not in session:
            flash('Сначала войдите как ученик', 'error')
            return redirect(url_for('student_entry'))
        return f(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    classes = db.session.query(Student.class_num, Student.class_letter).distinct().all()
    all_classes = sorted([f"{c[0]}{c[1]}" for c in classes])
    return dict(all_classes=all_classes)


@app.template_filter('cover_src')
def cover_src(book):
    if book.cover_file:
        return url_for('static', filename=f'covers/{book.cover_file}')
    if book.cover_url:
        return book.cover_url
    return url_for('static', filename='img/no-cover.svg')


def log_action(actor_type, actor_id, action, details):
    db.session.add(History(actor_type=actor_type, actor_id=actor_id,
                           action=action, details=details))
    db.session.commit()


# ==============================
# ГЛАВНАЯ
# ==============================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password_hash, request.form['password']):
            login_user(u)
            flash(f'Добро пожаловать, {u.full_name or u.username}', 'ok')
            if u.role == 'admin':
                return redirect(url_for('admin_panel'))
            if u.role == 'librarian':
                return redirect(url_for('librarian_panel'))
            return redirect(url_for('teacher_panel'))
        flash('Неверный логин или пароль', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/student-entry', methods=['GET', 'POST'])
def student_entry():
    if request.method == 'POST':
        s = Student.query.filter(
            db.func.lower(Student.full_name) == request.form['full_name'].strip().lower(),
            Student.class_num == int(request.form['class_num']),
            db.func.upper(Student.class_letter) == request.form['class_letter'].strip().upper()
        ).first()
        if s:
            session['student_id'] = s.id
            session['student_name'] = s.full_name
            session['student_class'] = s.class_code
            return redirect(url_for('student_cabinet'))
        flash('Ученик не найден', 'error')
    return render_template('student_entry.html')


@app.route('/student-logout')
def student_logout():
    session.clear()
    return redirect(url_for('index'))


# ==============================
# КАТАЛОГ
# ==============================
@app.route('/catalog')
def catalog():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '')
    sort = request.args.get('sort', 'title')
    query = Book.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Book.title.ilike(like), Book.author.ilike(like),
                                    Book.annotation.ilike(like)))
    if category:
        query = query.filter(Book.category == category)
    if sort == 'author':
        query = query.order_by(Book.author, Book.title)
    elif sort == 'year':
        query = query.order_by(Book.year.desc(), Book.title)
    else:
        query = query.order_by(Book.title)
    return render_template('catalog.html', books=query.all(), q=q,
                           category=category, sort=sort)


@app.route('/book/<int:book_id>')
def book_card(book_id):
    book = db.session.get(Book, book_id) or abort(404)
    return render_template('book_card.html', book=book)


@app.route('/reserve/<int:book_id>', methods=['POST'])
@student_required
def reserve(book_id):
    book = db.session.get(Book, book_id) or abort(404)
    if book.available_copies <= 0:
        flash('Нет доступных экземпляров', 'error')
        return redirect(url_for('book_card', book_id=book_id))
    now = datetime.utcnow()
    expires = (now + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    db.session.add(Reservation(book_id=book_id, student_id=session['student_id'],
                               expires_at=expires))
    book.available_copies -= 1
    db.session.commit()
    log_action('student', session['student_id'], 'reserve', f'Забронировал: {book.title}')
    flash(f'Забронировано до {expires.strftime("%d.%m.%Y %H:%M")}', 'ok')
    return redirect(url_for('book_card', book_id=book_id))


# ==============================
# КАБИНЕТ УЧЕНИКА
# ==============================
@app.route('/student/cabinet')
def student_cabinet():
    sid = session.get('student_id')
    if not sid:
        return redirect(url_for('student_entry'))
    student = db.session.get(Student, sid) or abort(404)
    active_loans = Loan.query.filter_by(student_id=sid, returned_at=None).all()
    active_reservations = Reservation.query.filter_by(student_id=sid, status='active').all()
    total_read = Loan.query.filter_by(student_id=sid).filter(Loan.returned_at.isnot(None)).count()

    cls = student.class_code
    lists = ReadingList.query.filter(db.or_(ReadingList.target_class == cls,
                                            ReadingList.target_class == 'ALL')).all()
    reading_lists = []
    for rl in lists:
        total = len(rl.items)
        if total == 0:
            continue
        item_ids = [i.id for i in rl.items]
        read = StudentReadingProgress.query.filter(
            StudentReadingProgress.student_id == student.id,
            StudentReadingProgress.item_id.in_(item_ids),
            StudentReadingProgress.read_at.isnot(None)).count()
        reading_lists.append({'list': rl, 'total': total, 'read': read,
                              'percent': round(read / total * 100)})
    return render_template('student_cabinet.html', student=student,
                           active_loans=active_loans,
                           active_reservations=active_reservations,
                           reading_lists=reading_lists, total_read=total_read)


# ==============================
# УВЕДОМЛЕНИЯ
# ==============================
@app.route('/notifications')
def notifications():
    rows = []
    if 'student_id' in session:
        sid = session['student_id']
        cls = session['student_class']
        read_ids = [r.notification_id for r in NotificationRead.query.filter_by(student_id=sid).all()]
        query = Notification.query
        if read_ids:
            query = query.filter(~Notification.id.in_(read_ids))
        query = query.filter(db.or_(Notification.audience == 'all',
                                    db.and_(Notification.audience == 'class',
                                            Notification.audience_value == cls),
                                    db.and_(Notification.audience == 'student',
                                            Notification.audience_value == str(sid)),
                                    db.and_(Notification.audience == 'class_teacher',
                                            Notification.audience_value == cls)))
        rows = query.order_by(Notification.created_at.desc()).all()
    return render_template('notifications.html', notifications=rows)


@app.route('/notifications/read/<int:nid>', methods=['POST'])
def mark_notification_read(nid):
    if 'student_id' not in session:
        return redirect(url_for('student_entry'))
    if not NotificationRead.query.filter_by(notification_id=nid,
                                             student_id=session['student_id']).first():
        db.session.add(NotificationRead(notification_id=nid, student_id=session['student_id']))
        db.session.commit()
    return redirect(url_for('notifications'))


# ==============================
# ИСТОРИЯ
# ==============================
@app.route('/history')
def history():
    if 'student_id' in session:
        sid = session['student_id']
        loans = Loan.query.filter_by(student_id=sid).order_by(Loan.issued_at.desc()).all()
        reservations = Reservation.query.filter_by(student_id=sid).order_by(
            Reservation.reserved_at.desc()).all()
        actions = History.query.filter_by(actor_type='student', actor_id=sid).order_by(
            History.created_at.desc()).all()
        return render_template('history.html', loans=loans, reservations=reservations,
                               history=actions)
    elif current_user.is_authenticated:
        actions = History.query.filter_by(actor_type='user', actor_id=current_user.id).order_by(
            History.created_at.desc()).all()
        return render_template('history.html', loans=[], reservations=[], history=actions)
    return redirect(url_for('index'))


# ==============================
# АДМИН
# ==============================
@app.route('/admin')
@login_required
@role_required('admin')
def admin_panel():
    return render_template('admin_panel.html',
                           users=User.query.all(),
                           students=Student.query.order_by(Student.class_num,
                                                           Student.class_letter,
                                                           Student.full_name).all(),
                           books_count=Book.query.count())


@app.route('/admin/add-user', methods=['POST'])
@login_required
@role_required('admin')
def add_user():
    if User.query.filter_by(username=request.form['username']).first():
        flash('Логин занят', 'error')
        return redirect(url_for('admin_panel'))
    db.session.add(User(role=request.form['role'], username=request.form['username'],
                        password_hash=generate_password_hash(request.form['password']),
                        full_name=request.form.get('full_name', '')))
    db.session.commit()
    flash('Пользователь добавлен', 'ok')
    return redirect(url_for('admin_panel'))


@app.route('/admin/add-student', methods=['POST'])
@login_required
@role_required('admin', 'librarian')
def add_student():
    db.session.add(Student(full_name=request.form['full_name'],
                           class_num=int(request.form['class_num']),
                           class_letter=request.form['class_letter'].upper()))
    db.session.commit()
    flash('Ученик добавлен', 'ok')
    return redirect(request.referrer or url_for('admin_panel'))


# ==============================
# БИБЛИОТЕКАРЬ
# ==============================
@app.route('/librarian')
@login_required
@role_required('librarian', 'admin')
def librarian_panel():
    return render_template('librarian_panel.html',
                           books=Book.query.order_by(Book.title).all(),
                           students=Student.query.order_by(Student.class_num,
                                                           Student.class_letter,
                                                           Student.full_name).all(),
                           active_loans=Loan.query.filter_by(returned_at=None).order_by(
                               Loan.due_date).all(),
                           reservations=Reservation.query.filter_by(status='active').order_by(
                               Reservation.expires_at).all())


@app.route('/librarian/add-book', methods=['POST'])
@login_required
@role_required('librarian', 'admin')
def add_book():
    f = request.form
    copies = int(f.get('total_copies', 1))
    book = Book(title=f['title'], author=f.get('author', ''), category=f['category'],
                publisher=f.get('publisher', ''),
                year=int(f['year']) if f.get('year') else None,
                isbn=f.get('isbn', ''),
                pages=int(f['pages']) if f.get('pages') else None,
                udc=f.get('udc', ''), bbk=f.get('bbk', ''),
                annotation=f.get('annotation', ''),
                total_copies=copies, available_copies=copies,
                cover_url=f.get('cover_url', '').strip() or None)
    cover = request.files.get('cover_file')
    if cover and cover.filename:
        ext = cover.filename.rsplit('.', 1)[-1].lower()
        if ext in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
            filename = f"{uuid.uuid4().hex}.{ext}"
            cover.save(os.path.join(COVERS_DIR, filename))
            book.cover_file = filename
    db.session.add(book)
    db.session.commit()
    flash('Книга добавлена', 'ok')
    return redirect(url_for('librarian_panel'))


@app.route('/librarian/edit-cover/<int:book_id>', methods=['POST'])
@login_required
@role_required('librarian', 'admin')
def edit_cover(book_id):
    book = db.session.get(Book, book_id) or abort(404)
    cover_url = request.form.get('cover_url', '').strip()
    cover = request.files.get('cover_file')
    if cover and cover.filename:
        ext = cover.filename.rsplit('.', 1)[-1].lower()
        if ext in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
            filename = f"{uuid.uuid4().hex}.{ext}"
            cover.save(os.path.join(COVERS_DIR, filename))
            book.cover_file = filename
            book.cover_url = None
            flash('Обложка загружена', 'ok')
    elif cover_url:
        book.cover_url = cover_url
        book.cover_file = None
        flash('Ссылка сохранена', 'ok')
    db.session.commit()
    return redirect(url_for('book_card', book_id=book_id))


@app.route('/librarian/delete-book/<int:book_id>', methods=['POST'])
@login_required
@role_required('librarian', 'admin')
def delete_book(book_id):
    book = db.session.get(Book, book_id)
    if book:
        db.session.delete(book)
        db.session.commit()
        flash('Книга удалена', 'ok')
    return redirect(url_for('librarian_panel'))


@app.route('/librarian/issue', methods=['POST'])
@login_required
@role_required('librarian', 'admin')
def issue_book():
    book = db.session.get(Book, int(request.form['book_id']))
    if not book or book.available_copies <= 0:
        flash('Нет экземпляров', 'error')
        return redirect(url_for('librarian_panel'))
    days = int(request.form.get('days', 14))
    db.session.add(Loan(book_id=book.id, student_id=int(request.form['student_id']),
                        issued_at=datetime.utcnow(),
                        due_date=datetime.utcnow() + timedelta(days=days),
                        issued_by=current_user.id))
    book.available_copies -= 1
    db.session.commit()
    log_action('user', current_user.id, 'issue', f'Выдал: {book.title}')
    flash('Книга выдана', 'ok')
    return redirect(url_for('librarian_panel'))


@app.route('/librarian/return/<int:loan_id>', methods=['POST'])
@login_required
@role_required('librarian', 'admin')
def return_book(loan_id):
    loan = db.session.get(Loan, loan_id)
    if loan and not loan.returned_at:
        loan.returned_at = datetime.utcnow()
        book = db.session.get(Book, loan.book_id)
        book.available_copies += 1
        db.session.commit()
        log_action('user', current_user.id, 'return', f'Принял: {book.title}')
        flash('Книга принята', 'ok')
    return redirect(url_for('librarian_panel'))


@app.route('/librarian/confirm-reservation/<int:rid>', methods=['POST'])
@login_required
@role_required('librarian', 'admin')
def confirm_reservation(rid):
    r = db.session.get(Reservation, rid)
    if r and r.status == 'active':
        r.status = 'taken'
        db.session.add(Loan(book_id=r.book_id, student_id=r.student_id,
                            issued_at=datetime.utcnow(),
                            due_date=datetime.utcnow() + timedelta(days=14),
                            issued_by=current_user.id))
        db.session.commit()
        flash('Книга выдана по брони', 'ok')
    return redirect(url_for('librarian_panel'))


# ==============================
# УЧИТЕЛЬ
# ==============================
@app.route('/teacher')
@login_required
@role_required('teacher', 'admin')
def teacher_panel():
    return render_template('teacher_panel.html',
                           books=Book.query.order_by(Book.title).all(),
                           assignments=ReadingList.query.filter_by(
                               teacher_id=current_user.id).order_by(
                               ReadingList.created_at.desc()).all())


@app.route('/teacher/create-list', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def create_reading_list():
    title = request.form['title']
    target_class = request.form.get('target_class', 'ALL').upper()
    deadline_str = request.form.get('deadline')
    deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date() if deadline_str else None
    rl = ReadingList(teacher_id=current_user.id, title=title,
                     target_class=target_class, deadline=deadline)
    db.session.add(rl)
    db.session.flush()
    for bid in request.form.getlist('book_ids'):
        db.session.add(ReadingListItem(list_id=rl.id, book_id=int(bid)))
    if target_class != 'ALL':
        db.session.add(Notification(title=f'📚 Список литературы: {title}',
                                    body=f'Учитель {current_user.full_name} добавил книги для чтения.',
                                    audience='class', audience_value=target_class,
                                    created_by=current_user.id))
    else:
        db.session.add(Notification(title=f'📚 Список литературы: {title}',
                                    body=f'Учитель {current_user.full_name} добавил книги для всех.',
                                    audience='all', created_by=current_user.id))
    db.session.commit()
    flash('Список создан', 'ok')
    return redirect(url_for('teacher_panel'))


@app.route('/teacher/notify', methods=['POST'])
@login_required
@role_required('teacher', 'admin', 'librarian')
def send_notification():
    db.session.add(Notification(title=request.form['title'], body=request.form.get('body', ''),
                                audience=request.form['audience'],
                                audience_value=request.form.get('audience_value', '') or None,
                                created_by=current_user.id))
    db.session.commit()
    flash('Уведомление отправлено', 'ok')
    return redirect(request.referrer or url_for('index'))


# ==============================
# PWA
# ==============================
@app.route('/service-worker.js')
def service_worker():
    from flask import send_file
    return send_file('static/service-worker.js', mimetype='application/javascript')


@app.route('/offline')
def offline():
    return render_template('offline.html')


@app.route('/manifest.json')
def manifest():
    from flask import send_file
    return send_file('static/manifest.json', mimetype='application/manifest+json')


# ==============================
# ИНИЦИАЛИЗАЦИЯ
# ==============================
with app.app_context():
    db.create_all()

    if not User.query.filter_by(username='admin').first():
        for u, p, r, n in [
            ('admin', 'admin123', 'admin', 'Администратор'),
            ('librarian', 'lib123', 'librarian', 'Библиотекарь Иванова И.И.'),
            ('teacher', 'teacher123', 'teacher', 'Учитель Петров П.П.'),
        ]:
            db.session.add(User(username=u, password_hash=generate_password_hash(p),
                                role=r, full_name=n))
        db.session.commit()
        print('✅ Демо-аккаунты созданы')

    if Student.query.count() == 0:
        for n, cn, cl in [('Иванов Иван Иванович', 5, 'А'),
                          ('Петрова Мария Сергеевна', 5, 'А'),
                          ('Сидоров Пётр Алексеевич', 5, 'Б'),
                          ('Кузнецова Анна Дмитриевна', 7, 'А')]:
            db.session.add(Student(full_name=n, class_num=cn, class_letter=cl))
        db.session.commit()
        print('✅ Демо-ученики добавлены')

    if Book.query.count() == 0:
        for t, a, c, p, y, i, pg, u, b, an, tc in [
            ('Война и мир', 'Л.Н. Толстой', 'fiction', 'Просвещение', 2018,
             '978-5-09-000001', 1274, '821.161.1', '84(2Рос)1', 'Роман-эпопея', 5),
            ('Большая российская энциклопедия', 'Коллектив авторов', 'encyclopedia',
             'БРЭ', 2020, '978-5-85-270-001', 800, '030', '92', 'Универсальная энциклопедия', 3),
            ('Сборник рассказов', 'А.П. Чехов', 'collection', 'Дрофа', 2019,
             '978-5-35-800001', 400, '821.161.1', '84(2Рос)1', 'Избранные рассказы', 4),
            ('Математика 5 класс', 'Виленкин Н.Я.', 'textbook', 'Мнемозина', 2021,
             '978-5-34-600001', 280, '51', '22.1', 'Учебник для 5 класса', 30),
            ('Физика 7 класс', 'Перyшкин А.В.', 'textbook', 'Дрофа', 2022,
             '978-5-35-800123', 224, '53', '22.3', 'Учебник для 7 класса', 25),
        ]:
            db.session.add(Book(title=t, author=a, category=c, publisher=p, year=y,
                                isbn=i, pages=pg, udc=u, bbk=b, annotation=an,
                                total_copies=tc, available_copies=tc))
        db.session.commit()
        print('✅ Демо-книги добавлены')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)