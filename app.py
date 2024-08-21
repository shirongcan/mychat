from flask import Flask, render_template, request, flash, redirect, url_for, jsonify
from models import db, User, Message, MessageType
from flask_login import (
    current_user,
    LoginManager,
    login_user,
    login_required,
    logout_user,
)
from flask_socketio import SocketIO, emit, disconnect
from datetime import datetime
import os

from mytools import create_unique_filename


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "your_secret_key"
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///src_database.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")
    # 创建上传文件夹
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    return app


app = create_app()

login_manager = LoginManager(app)
login_manager.login_view = "login"

socketio = SocketIO(app)

# 用于存储在线用户的字典
online_users = {}


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            online_users[user.id] = datetime.now()

            return redirect(url_for("hello_world"))
        else:
            flash("登录失败。请检查用户名和密码。", "danger")
    return render_template("login.html")


@app.route("/")
@login_required
def hello_world():  # put application's code here
    all_users = User.query.all()
    return render_template(
        "微信聊天界面.html",
        all_users=all_users,
        online_users=online_users,
        current_user=current_user,
    )


@app.route("/logout")
@login_required
def logout():
    user_id = current_user.id
    logout_user()
    if user_id in online_users:
        del online_users[user_id]
    return redirect(url_for("login"))


@socketio.on("connect")
def handle_connect():
    if current_user.is_authenticated:
        online_users[current_user.id] = datetime.now()
        emit(
            "user_status_change",
            {
                "user_id": current_user.id,
                "username": current_user.username,
                "status": "online",
            },
            broadcast=True,
        )


@socketio.on("disconnect")
def handle_disconnect():
    if current_user.is_authenticated:
        online_users.pop(current_user.id, None)
        emit(
            "user_status_change",
            {
                "user_id": current_user.id,
                "username": current_user.username,
                "status": "offline",
            },
            broadcast=True,
        )


@socketio.on("send_message")
def send_message(data):
    if not current_user.is_authenticated:
        emit("authentication_error", {"message": "用户未认证"})
        return

    message_type = data.get("type", "text").upper()
    message_content = data.get("message", "")

    new_message = Message(
        user_id=current_user.id,
        message_type=MessageType[message_type],
        content=message_content,
    )

    try:
        db.session.add(new_message)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        emit("error", {"message": "保存消息失败"})
        return

    emit(
        "new_message",
        {
            "user_id": current_user.id,
            "username": current_user.nickname,
            "avatar": f"/static/images/{current_user.avatar}",
            "message": message_content,
            "type": message_type.value,
        },
        broadcast=True,
    )

    return {"status": "success", "message": "消息已广播"}


@app.route("/api/messages")
def get_messages():
    before_id = request.args.get("before_id", type=int)
    # after_id = request.args.get('after_id', type=int)
    limit = request.args.get("limit", 20, type=int)

    query = Message.query.order_by(Message.id.desc())

    if before_id:
        query = query.filter(Message.id < before_id)
    # elif after_id:
    #     query = query.filter(Message.id > after_id).order_by(Message.id.asc())

    messages = query.limit(limit).all()

    # if after_id:
    #     messages.reverse()  # Reverse to maintain descending order
    for msg in messages:
        print(msg.message_type.value)
    return jsonify(
        [
            {
                "id": msg.id,
                "user_id": msg.user_id,
                "username": msg.user.nickname,
                "message": msg.content,
                "avatar": "/static/images/" + msg.user.avatar,
                "timestamp": msg.timestamp.isoformat(),
                'type': msg.message_type.value,
                
            }
            for msg in messages[::-1]
        ]
    )


@app.route("/api/upload", methods=["POST"])
def upload_file():
    file = request.files["file"]
    if file:
        filename = create_unique_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        # 创建新的消息记录
        new_message = Message(
            user_id=current_user.id, content=filename, message_type=MessageType.FILE
        )

        db.session.add(new_message)
        db.session.commit()

        socketio.emit(
            "new_message",
            {
                "user_id": current_user.id,
                "username": current_user.nickname,
                "avatar": f"/static/images/{current_user.avatar}",
                "message": filename,
                "type": "file",
            },
        )

        return jsonify({"message": "文件上传成功"}), 200

    return jsonify({'error': '没有文件上传'}), 400


if __name__ == "__main__":
    app.debug = True
    app.run(host="0.0.0.0")
