from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import oracledb
import datetime

app = Flask(__name__, static_url_path='/static', template_folder='.')
CORS(app)

# Oracle параметрлері
DB_USER = 'raim'
DB_PASSWORD = '2004'
DB_DSN = 'localhost:1521/XEPDB1'

def get_db_connection():
    try:
        return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)
    except Exception as e:
        print(f"DB Error: {e}")
        return None
# 2. БАСТЫ БЕТТІҢ (HOME) ЖОЛЫН КӨРСЕТУ
@app.route('/')
def home():
    # index.html файлы app.py-мен бір папкада жатуы керек!
    return render_template('index.html')
# --- LOGIN & REGISTER (Өзгеріссіз) ---
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "DB Error"}), 500
    
    cursor = conn.cursor()
    cursor.execute("SELECT fullname, role, email FROM users WHERE email = :1 AND password = :2", 
                   [data.get('email'), data.get('password')])
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if user:
        return jsonify({"success": True, "user": {"name": user[0], "role": user[1], "email": user[2]}})
    return jsonify({"success": False, "message": "Қате деректер"}), 401

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (fullname, email, password, role) VALUES (:1, :2, :3, :4)",
                       [data['name'], data['email'], data['password'], data['role']])
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        cursor.close()
        conn.close()

# --- ЖАҢА API-ЛАР ---

# 1. Барлық курстарды алу (Каталог үшін)
@app.route('/api/courses', methods=['GET'])
def get_courses():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, category, description, duration, instructor_name FROM courses")
    rows = cursor.fetchall()
    
    courses = []
    for row in rows:
        courses.append({
            "id": row[0], "title": row[1], "category": row[2], 
            "description": row[3], "duration": row[4], "instructor": row[5]
        })
    cursor.close()
    conn.close()
    return jsonify(courses)

# 2. Менің курстарым (Dashboard және My Courses үшін)
# app.py ішіндегі get_my_courses функциясын осыған ауыстырыңыз:
# app.py ішіндегі get_my_courses функциясының жаңа нұсқасы:
@app.route('/api/my-courses', methods=['GET'])
def get_my_courses():
    email = request.args.get('email')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # c.duration (ұзақтығы) қосылды [index 6 болады]
    sql = """
        SELECT c.id, c.title, c.category, c.instructor_name, e.progress, e.status, c.duration
        FROM enrollments e
        JOIN courses c ON e.course_id = c.id
        WHERE e.user_email = :1
    """
    cursor.execute(sql, [email])
    rows = cursor.fetchall()
    
    my_courses = []
    # Статистика айнымалылары
    stats = {
        "active": 0, 
        "completed": 0, 
        "total_progress": 0,
        "total_hours": 0  # Жаңа параметр: Жалпы сағат
    }
    
    for row in rows:
        progress = row[4]
        status = row[5]
        duration = row[6] if row[6] else 0 # Егер duration null болса, 0 деп аламыз

        if status == 'active': stats['active'] += 1
        if status == 'completed': stats['completed'] += 1
        
        stats['total_progress'] += progress
        stats['total_hours'] += duration # Сағаттарды қосамыз

        my_courses.append({
            "id": row[0],
            "title": row[1],
            "category": row[2],
            "instructor": row[3],
            "progress": progress,
            "status": status,
            "duration": duration
        })
    
    avg_progress = 0
    if len(rows) > 0:
        avg_progress = round(stats['total_progress'] / len(rows))
        
    cursor.close()
    conn.close()
    
    return jsonify({
        "courses": my_courses,
        "stats": {
            "total": len(rows),
            "active": stats['active'],
            "completed": stats['completed'],
            "avg_progress": avg_progress,
            "total_hours": stats['total_hours'] # Frontend-ке жібереміз
        }
    })
# app.py файлына қосыңыз:

@app.route('/api/certificates', methods=['GET'])
def get_certificates():
    email = request.args.get('email')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Тек аяқталған (completed) курстарды аламыз
    sql = """
        SELECT c.title, e.last_accessed, e.id, u.fullname
        FROM enrollments e
        JOIN courses c ON e.course_id = c.id
        JOIN users u ON e.user_email = u.email
        WHERE e.user_email = :1 AND e.status = 'completed'
    """
    cursor.execute(sql, [email])
    rows = cursor.fetchall()
    
    certificates = []
    for row in rows:
        # Күнді форматтау (Oracle-дан datetime келеді)
        date_str = row[1].strftime("%d.%m.%Y") if row[1] else "Белгісіз"
        
        certificates.append({
            "course_title": row[0],
            "date": date_str,
            "cert_id": f"CERT-2025-{row[2]}", # ID-ді генерациялаймыз
            "student_name": row[3]
        })
        
    cursor.close()
    conn.close()
    
    return jsonify(certificates)
# app.py ішіне қосыңыз:

@app.route('/api/complete-course', methods=['POST'])
def complete_course():
    data = request.json
    email = data.get('email')
    course_title = data.get('courseTitle') # Курстың аты арқылы табамыз
    print(f"DEBUG: Email: {email}, Course: '{course_title}'")
    
    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "DB Error"}), 500
    
    cursor = conn.cursor()
    
    try:
        # 1. Курстың аты арқылы оның ID-ін және Студенттің тіркелуін тауып, жаңартамыз
        # status = 'completed', progress = 100
        
        sql = """
            UPDATE enrollments 
            SET status = 'completed', progress = 100, last_accessed = SYSDATE
            WHERE user_email = :1 
            AND course_id = (SELECT id FROM courses WHERE title = :2)
        """
        
        cursor.execute(sql, [email, course_title])
        conn.commit()
        
        # Қанша жол өзгергенін тексереміз
        if cursor.rowcount > 0:
            return jsonify({"success": True, "message": "Курс аяқталды!"})
        else:
            return jsonify({"success": False, "message": "Курс табылмады немесе тіркелмегенсіз"}), 404
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
@app.route('/api/enroll', methods=['POST'])
def enroll_course():
    data = request.json
    email = data.get('email')
    course_title = data.get('courseTitle')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Курстың ID-ін табу
        cursor.execute("SELECT id FROM courses WHERE title = :1", [course_title])
        course = cursor.fetchone()
        
        if not course:
            return jsonify({"success": False, "message": "Курс табылмады"}), 404
            
        course_id = course[0]
        
        # 2. Студент бұл курсқа бұрын тіркелген бе?
        cursor.execute("SELECT 1 FROM enrollments WHERE user_email = :1 AND course_id = :2", [email, course_id])
        if cursor.fetchone():
            return jsonify({"success": False, "message": "Сіз бұл курсқа тіркеліп қойғансыз"}), 400
            
        # 3. Тіркеу
        cursor.execute("INSERT INTO enrollments (user_email, course_id, progress, status) VALUES (:1, :2, 0, 'active')",
                       [email, course_id])
        conn.commit()
        return jsonify({"success": True, "message": "Курсқа сәтті тіркелдіңіз!"})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close() 
# --- ФОРУМ (FORUM) API ---

# 1. Барлық сұрақтар мен жауаптарды алу
@app.route('/api/forum/posts', methods=['GET'])
def get_forum_posts():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Алдымен барлық сұрақтарды аламыз (ең соңғысы бірінші тұрады)
    cursor.execute("SELECT id, user_email, author_name, course_title, title, content, created_at FROM forum_posts ORDER BY created_at DESC")
    posts_rows = cursor.fetchall()
    
    all_posts = []
    
    for post in posts_rows:
        post_id = post[0]
        
        # Осы сұраққа жазылған жауаптарды аламыз
        cursor.execute("SELECT author_name, content, created_at, user_email FROM forum_replies WHERE post_id = :1 ORDER BY created_at ASC", [post_id])
        replies_rows = cursor.fetchall()
        
        replies = []
        for rep in replies_rows:
            replies.append({
                "authorName": rep[0],
                "content": rep[1],
                "timestamp": rep[2].strftime("%d.%m.%Y %H:%M") if rep[2] else "",
                "isInstructor": True if 'instructor' in rep[0].lower() else False # Инструктор екенін атынан немесе рөлінен анықтауға болады
            })

        all_posts.append({
            "id": post_id,
            "user_email": post[1],
            "authorName": post[2],
            "course": post[3],
            "title": post[4],
            "content": post[5],
            "timestamp": post[6].strftime("%d.%m.%Y %H:%M") if post[6] else "",
            "authorInitials": post[2][0].upper() if post[2] else "U",
            "replies": replies
        })
        
    cursor.close()
    conn.close()
    return jsonify(all_posts)

# 2. Жаңа сұрақ қосу (Студент үшін)
@app.route('/api/forum/create', methods=['POST'])
def create_forum_post():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO forum_posts (user_email, author_name, course_title, title, content) VALUES (:1, :2, :3, :4, :5)",
            [data['email'], data['authorName'], data['course'], data['title'], data['content']]
        )
        conn.commit()
        return jsonify({"success": True, "message": "Сұрақ жарияланды"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# 3. Жауап жазу (Инструктор үшін)
@app.route('/api/forum/reply', methods=['POST'])
def reply_forum_post():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO forum_replies (post_id, user_email, author_name, content) VALUES (:1, :2, :3, :4)",
            [data['postId'], data['email'], data['authorName'], data['content']]
        )
        conn.commit()
        return jsonify({"success": True, "message": "Жауап жіберілді"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close() 
# app.py соңына қосыңыз:
@app.route('/api/instructor/courses-list', methods=['GET'])
def get_instructor_courses_list():
    name = request.args.get('name')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Инструктордың курстарын және әр курста қанша студент бар екенін санаймыз
        # LEFT JOIN қолданамыз, себебі студенті жоқ курстар да тізімде шығуы керек
        sql = """
            SELECT c.title, c.category, COUNT(e.user_email) as student_count, c.description, c.duration
            FROM courses c
            LEFT JOIN enrollments e ON c.id = e.course_id
            WHERE c.instructor_name = :1
            GROUP BY c.id, c.title, c.category, c.description, c.duration
            ORDER BY student_count DESC
        """
        cursor.execute(sql, [name])
        rows = cursor.fetchall()
        
        courses = []
        for row in rows:
            courses.append({
                "title": row[0],
                "category": row[1],
                "students": row[2],
                "description": row[3], # Жаңа өріс
                "duration": row[4]
            })
            
        return jsonify({"success": True, "courses": courses})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()             
# app.py соңына қосыңыз:

@app.route('/api/instructor/course-students', methods=['GET'])
def get_course_students():
    title = request.args.get('title') # Курс аты
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Студент атын, үлгерімін, статусын аламыз
        sql = """
            SELECT u.fullname, e.progress, e.status, e.last_accessed
            FROM enrollments e
            JOIN users u ON e.user_email = u.email
            JOIN courses c ON e.course_id = c.id
            WHERE c.title = :1
        """
        cursor.execute(sql, [title])
        rows = cursor.fetchall()
        
        students = []
        for row in rows:
            # Күнді форматтау
            last_seen = row[3].strftime("%d.%m.%Y %H:%M") if row[3] else "Жақында"
            
            students.append({
                "name": row[0],
                "progress": row[1],
                "status": row[2],
                "last_seen": last_seen,
                "initials": row[0][0].upper() if row[0] else "U"
            })
            
        return jsonify({"success": True, "students": students})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
# app.py соңына қосыңыз:

@app.route('/api/instructor/all-students', methods=['GET'])
def get_all_instructor_students():
    name = request.args.get('name') # Инструктор аты
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Инструктордың БАРЛЫҚ курстарындағы студенттерді аламыз
        # Және нәтижеге курстың атын (c.title) да қосамыз
        sql = """
            SELECT u.fullname, e.progress, e.status, e.last_accessed, c.title
            FROM enrollments e
            JOIN users u ON e.user_email = u.email
            JOIN courses c ON e.course_id = c.id
            WHERE c.instructor_name = :1
            ORDER BY e.last_accessed DESC
        """
        cursor.execute(sql, [name])
        rows = cursor.fetchall()
        
        students = []
        for row in rows:
            last_seen = row[3].strftime("%d.%m.%Y %H:%M") if row[3] else "Жақында"
            
            students.append({
                "name": row[0],
                "progress": row[1],
                "status": row[2],
                "last_seen": last_seen,
                "course_title": row[4], # Курс аты
                "initials": row[0][0].upper() if row[0] else "U"
            })
            
        return jsonify({"success": True, "students": students})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
# app.py соңына қосыңыз:

@app.route('/api/instructor/create-course', methods=['POST'])
def create_course():
    data = request.json
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Курсты courses кестесіне қосамыз
        sql = """
            INSERT INTO courses (title, category, description, duration, instructor_name)
            VALUES (:1, :2, :3, :4, :5)
        """
        cursor.execute(sql, [
            data['title'],
            data['category'],
            data['description'],
            data['duration'],
            data['instructor_name'] # Инструктор атын автоматты түрде береміз
        ])
        
        conn.commit()
        return jsonify({"success": True, "message": "Курс сәтті құрылды!"})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
@app.route('/api/course-content', methods=['GET'])
def get_course_content():
    title = request.args.get('title') # Курс аты
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Курс ID-ін табамыз
        cursor.execute("SELECT id FROM courses WHERE title = :1", [title])
        course_row = cursor.fetchone()
        if not course_row:
            return jsonify({"success": False, "message": "Курс табылмады"})
        
        course_id = course_row[0]
        
        # 2. Осы курстың барлық сабақтарын аламыз
        cursor.execute("SELECT id, title, video_id, duration FROM lessons WHERE course_id = :1 ORDER BY order_num", [course_id])
        lessons_rows = cursor.fetchall()
        
        lessons_data = []
        
        for l_row in lessons_rows:
            lesson_id = l_row[0]
            
            # 3. Әр сабақтың сұрақтарын аламыз
            cursor.execute("SELECT question_text, option_1, option_2, option_3, option_4, correct_option FROM quiz_questions WHERE lesson_id = :1", [lesson_id])
            quiz_rows = cursor.fetchall()
            
            questions = []
            for q in quiz_rows:
                questions.append({
                    "q": q[0],
                    "options": [q[1], q[2], q[3], q[4]],
                    "correct": q[5]
                })
            
            lessons_data.append({
                "id": lesson_id,
                "title": l_row[1],
                "videoId": l_row[2],
                "duration": l_row[3],
                "quiz": questions
            })
            
        return jsonify({"success": True, "lessons": lessons_data})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
# app.py соңына қосыңыз:

@app.route('/api/update-progress', methods=['POST'])
def update_progress():
    data = request.json
    email = data.get('email')
    course_title = data.get('courseTitle')
    new_progress = data.get('progress')
    
    # --- DEBUG: Терминалға ақпарат шығару ---
    print(f"--------------------------------------------------")
    print(f"DEBUG START: Прогресс жаңарту")
    print(f"Email: {email}")
    print(f"Course: '{course_title}'") # Тырнақша ішінде көрейік (бос орындар бар ма?)
    print(f"Progress to save: {new_progress}")
    
    if not course_title:
        print("ERROR: Курс аты бос келді!")
        return jsonify({"success": False, "message": "Курс аты жоқ"}), 400
    # ----------------------------------------

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # SQL: GREATEST функциясын алып тастап, тікелей жаңартып көрейік (тексеру үшін)
        # NVL(..., 'active') бұл статус NULL болса active қылады
        sql = """
            UPDATE enrollments 
            SET progress = :1, 
                status = CASE WHEN :1 >= 100 THEN 'completed' ELSE 'active' END,
                last_accessed = SYSDATE
            WHERE user_email = :2
            AND course_id = (SELECT id FROM courses WHERE title = :3)
        """
        
        cursor.execute(sql, [new_progress, new_progress, email, course_title])
        conn.commit()
        
        # Қанша жол өзгергенін қараймыз
        rows = cursor.rowcount
        print(f"DEBUG: Oracle-да өзгерген жолдар саны: {rows}")
        
        if rows > 0:
            return jsonify({"success": True, "message": "Прогресс сақталды"})
        else:
            print("ERROR: Oracle жазбаны таппады! Email немесе Курс аты қате.")
            return jsonify({"success": False, "message": "Жазба табылмады"}), 404
        
    except Exception as e:
        print(f"Create error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
# app.py соңына қосыңыз:

@app.route('/api/user-profile', methods=['GET'])
def get_user_profile():
    email = request.args.get('email')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Аты, рөлі, поштасы және тіркелген күнін аламыз
        sql = "SELECT fullname, email, role, created_at FROM users WHERE email = :1"
        cursor.execute(sql, [email])
        row = cursor.fetchone()
        
        if row:
            # Күнді әдемі форматтау (Мысалы: 12 Қаңтар, 2025)
            # Python-да ай аттарын қазақшалау қиын болуы мүмкін, сондықтан сандық формат береміз
            reg_date = row[3].strftime("%d.%m.%Y") if row[3] else "Белгісіз"
            
            return jsonify({
                "success": True,
                "fullname": row[0],
                "email": row[1],
                "role": row[2],
                "joined": reg_date
            })
        else:
            return jsonify({"success": False, "message": "Қолданушы табылмады"}), 404
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
@app.route('/api/instructor/stats', methods=['GET'])
def get_instructor_stats_real():
    name = request.args.get('name')
    print(f"DEBUG: Статистика сұралды инструктор үшін: {name}")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Курстар санын алу
        cursor.execute("SELECT COUNT(*) FROM courses WHERE instructor_name = :1", [name])
        row_courses = cursor.fetchone()
        total_courses = row_courses[0] if row_courses else 0
        
        # 2. Студенттер санын және орташа прогрессті алу
        sql_students = """
            SELECT COUNT(DISTINCT e.user_email), AVG(e.progress)
            FROM enrollments e
            JOIN courses c ON e.course_id = c.id
            WHERE c.instructor_name = :1
        """
        cursor.execute(sql_students, [name])
        student_data = cursor.fetchone()
        
        total_students = student_data[0] if student_data and student_data[0] else 0
        avg_progress = round(student_data[1], 1) if student_data and student_data[1] else 0
        
        return jsonify({
            "success": True,
            "total_courses": total_courses,
            "total_students": total_students,
            "avg_progress": avg_progress,
            "rating": 4.9
        })
        
    except Exception as e:
        print(f"Stats error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
# app.py соңына қосыңыз немесе ауыстырыңыз:

@app.route('/api/instructor/students', methods=['GET'])
def get_instructor_students():
    instructor_name = request.args.get('name')
    course_filter = request.args.get('course') # Арнайы курс аты (опция)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Негізгі SQL сұраныс
        sql = """
            SELECT u.fullname, c.title, e.progress, e.status, e.last_accessed
            FROM enrollments e
            JOIN courses c ON e.course_id = c.id
            JOIN users u ON e.user_email = u.email
            WHERE c.instructor_name = :1
        """
        params = [instructor_name]

        # Егер нақты курс таңдалса, сүзгі қосамыз
        if course_filter and course_filter != 'null':
            sql += " AND c.title = :2"
            params.append(course_filter)
            
        sql += " ORDER BY e.last_accessed DESC"
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        students = []
        for row in rows:
            # Уақытты әдемілеу
            last_seen = row[4].strftime("%d.%m.%Y %H:%M") if row[4] else "Бұрын"
            
            students.append({
                "name": row[0],
                "course": row[1],
                "progress": row[2],
                "status": row[3],
                "last_seen": last_seen
            })
            
        return jsonify({"success": True, "students": students})
        
    except Exception as e:
        print(f"Students error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    app.run(debug=True, port=5000)