import os
import json
import logging
from celery import Celery
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from typing import Optional
import main

# Настройка логгера
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()])

app = Flask(__name__)
app.secret_key = os.urandom(16).hex()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

celery = Celery(__name__)
celery.config_from_object('celery_config')

@celery.task(bind=True)
def async_main_func(self):
    try:
        main.main_func()
    except Exception as e:
        logging.error(f"Error occurred in async task: {str(e)}")
        raise self.retry(exc=e, countdown=60, max_retries=3)



class User(UserMixin):
    pass


def load_config(key: Optional[str] = None) -> dict:
    current_directory = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_directory, "config.json")

    with open(file_path, "r") as file:
        config = json.load(file)

    if key:
        return config.get(key, None)
    else:
        return config


@login_manager.user_loader
def user_loader(username):
    if username != "admin":
        return
    user = User()
    user.id = username
    logging.info(f"User loaded: {user.id}") # Отладочный вывод
    return user


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username == load_config("login") and password == load_config("password"):
            user = User()
            user.id = username
            login_user(user)
            logging.info(f"User {username} logged in successfully.")
            logging.info(session)
            return redirect(url_for('index'))

        flash("Неверное имя пользователя или пароль", "danger")
        logging.warning(f"Failed login attempt by user {username}.")

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logging.info(f"User {session['user_id']} logged out.")
    logout_user()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('index.html')


@app.route('/run-main', methods=['POST'])
def run_main_function():
    task = async_main_func.apply_async()
    task_id = task.id
    return jsonify({"message": "Задача запущена, пожалуйста, подождите...", "task_id": task.id}), 202


@app.route('/task-status/<task_id>', methods=['GET'])
def task_status(task_id):
    task = async_main_func.AsyncResult(task_id)
    return jsonify({"status": task.status})


if __name__ == '__main__':
    # TODO: Не использовать режим отладки в продакшене!
    app.run(debug=True)
