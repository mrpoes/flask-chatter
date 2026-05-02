from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
from flask_socketio import SocketIO, emit, join_room
from models import db, User, Message, Room, room_members
from helper import login_required
from dotenv import load_dotenv
import logging
import os

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder="templates", static_folder="static")

# Load credentials and secret key from .env
load_dotenv()
SECRET_KEY = os.getenv('SECRETKEY')
U1NAME = os.getenv('U1NAME')
U1PASS = os.getenv('U1PASS')
U2NAME = os.getenv('U2NAME')
U2PASS = os.getenv('U2PASS')

app.config.update(
    SECRET_KEY=SECRET_KEY,
    SQLALCHEMY_DATABASE_URI='sqlite:///chat.db',
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,   # prevents JS access to session cookie
    SESSION_COOKIE_SAMESITE='Strict'  # blocks cross-site request forgery
)

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", manage_session=True)

users = {}  # maps username -> socket session id (sid)

MAX_MESSAGE_LENGTH = 2000  # chars, enforced on send
MAX_HISTORY = 200          # messages returned per room/DM fetch


def init_db():
    """Create tables, seed the General room, and ensure demo users exist."""
    with app.app_context():
        db.create_all()

        general_room = Room.query.filter_by(name="General").first()
        if not general_room:
            general_room = Room(name="General", type='public')
            db.session.add(general_room)
            db.session.commit()

        if not User.query.filter_by(username=U1NAME).first():
            u = User(username=U1NAME)
            u.set_password(U1PASS)
            db.session.add(u)
        if not User.query.filter_by(username=U2NAME).first():
            u = User(username=U2NAME)
            u.set_password(U2PASS)
            db.session.add(u)

        db.session.commit()
        logging.info("DB initialized / demo users ensured")


# ---
# HTTP Routes
# ---

@app.route("/")
def root():
    # Send logged-in users straight to chat, others to login
    if "username" in session:
        return redirect(url_for("chat_home"))
    return redirect(url_for("login"))


@app.route('/no')
def no():
    return render_template("no.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session["username"] = user.username
            session["user_id"] = user.id
            return redirect(url_for("chat_home"))
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not username or not password:
            return render_template("register.html", error="Username and password required")
        if password != confirm:
            return render_template("register.html", error="Passwords do not match")
        if User.query.filter_by(username=username).first():
            return render_template("register.html", error="Username already taken")
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.context_processor
def inject_user():
    # Makes `username` available in all templates without passing it manually
    return dict(username=session.get("username"))


@app.route("/chat")
@login_required
def chat_home():
    return redirect(url_for('chat_room', room_name='General'))


@app.route('/chat/room/<room_name>')
@login_required
def chat_room(room_name):
    room = Room.query.filter_by(name=room_name).first()
    if not room:
        # Room doesn't exist yet — client will create it on join
        return render_template("index.html", mode="room", target=room_name)

    if room.type == "group":
        # Private groups: only members can access
        user = User.query.get(session["user_id"])
        if user not in room.members:
            return abort(403, description="You are not a member of this group.")

    return render_template("index.html", mode="room", target=room_name)


@app.route('/chat/dm/<username>')
@login_required
def chat_dm(username):
    return render_template('index.html', mode='dm', target=username)


@app.route("/rooms")
@login_required
def rooms():
    public_rooms = Room.query.filter_by(type="public").all()
    return jsonify([{"id": r.id, "name": r.name, "type": r.type} for r in public_rooms])


@app.route("/whoami")
def whoami():
    """Returns the current session's username, or null if not logged in."""
    return jsonify({"username": session.get("username")})


@app.route("/users")
def get_users():
    if "username" not in session:
        return jsonify([])
    include_self = request.args.get('include_self') == 'true'
    q = User.query
    if not include_self:
        q = q.filter(User.username != session['username'])
    return jsonify([{"username": u.username} for u in q.all()])


@app.route("/active_users")
@login_required
def active_users():
    """Returns usernames of currently connected socket clients."""
    return jsonify(list(users.keys()))


@app.route("/messages")
@login_required
def messages():
    """
    Fetch message history.
    - ?recipient=<username>  →  DM conversation with that user
    - ?room=<room_name>      →  room message history
    Falls back to the session's current room if no params given.
    """
    recipient_name = request.args.get("recipient")
    room_name = request.args.get("room")
    me = session.get("username")

    if recipient_name:
        user_me = User.query.filter_by(username=me).first()
        user_rec = User.query.filter_by(username=recipient_name).first()
        if user_me and user_rec:
            dm_msgs = Message.query.filter(
                ((Message.user_id == user_me.id) & (Message.recipient_id == user_rec.id)) |
                ((Message.user_id == user_rec.id) & (Message.recipient_id == user_me.id))
            ).order_by(Message.timestamp.asc()).limit(MAX_HISTORY).all()
            return jsonify([{
                "id": m.id,
                "user": m.user.username,
                "content": m.content,
                "timestamp": m.timestamp.isoformat()
            } for m in dm_msgs])
        return jsonify([])

    if not room_name:
        room_name = session.get("room", "General")
    room = Room.query.filter_by(name=room_name).first()
    if not room:
        return jsonify([])

    msgs = Message.query.filter_by(room_id=room.id).order_by(Message.timestamp.asc()).limit(MAX_HISTORY).all()
    return jsonify([{
        "id": m.id,
        "user": m.user.username,
        "content": m.content,
        "timestamp": m.timestamp.isoformat()
    } for m in msgs])


@app.route("/groups")
@login_required
def get_groups():
    user = User.query.filter_by(username=session["username"]).first()
    if not user:
        return jsonify([])
    groups = user.groups.all()
    return jsonify([{"name": g.name, "members": [u.username for u in g.members]} for g in groups])


@app.route("/chat/group/create", methods=["POST"])
@login_required
def create_group():
    group_name = request.form.get("group_name", "").strip()
    if not group_name:
        return jsonify({"error": "Group name required"}), 400
    if Room.query.filter_by(name=group_name).first():
        return jsonify({"error": "Room already exists"}), 400

    group = Room(name=group_name, type="group")
    db.session.add(group)
    db.session.commit()

    # Add creator as a member and assign them the owner role
    user = User.query.get(session["user_id"])
    group.members.append(user)
    stmt = room_members.update().where(
        (room_members.c.room_id == group.id) &
        (room_members.c.user_id == user.id)
    ).values(role="owner")
    db.session.execute(stmt)
    db.session.commit()

    return jsonify({"success": True, "group": {"name": group.name, "id": group.id}})


@app.route("/chat/group/invite", methods=["POST"])
@login_required
def invite_to_group():
    group_name = request.form.get("group_name", "").strip()
    username = request.form.get("username", "").strip()
    if not group_name or not username:
        return jsonify({"error": "Missing parameters"}), 400

    group = Room.query.filter_by(name=group_name, type="group").first()
    if not group:
        return jsonify({"error": "Group not found"}), 404

    # Only the group owner can invite new members
    inviter = User.query.get(session["user_id"])
    assoc = db.session.query(room_members).filter_by(room_id=group.id, user_id=inviter.id).first()
    if not assoc or assoc.role != "owner":
        return jsonify({"error": "Only owners can invite"}), 403

    invitee = User.query.filter_by(username=username).first()
    if not invitee:
        return jsonify({"error": "User not found"}), 404
    if group.members.filter_by(id=invitee.id).first():
        return jsonify({"error": "User already a member"}), 400

    group.members.append(invitee)
    db.session.commit()
    return jsonify({"success": True})


# ---
# Socket Event Handlers
# ---

def get_or_create_dm_room(user1: str, user2: str):
    """Return existing DM room or create one. Room name is deterministic (sorted usernames)."""
    sorted_users = sorted([user1, user2])
    room_name = f"dm:{sorted_users[0]}:{sorted_users[1]}"
    room = Room.query.filter_by(name=room_name).first()
    if not room:
        room = Room(name=room_name, type="dm")
        db.session.add(room)
        db.session.commit()
    return room


@login_required
@socketio.on("start_dm")
def handle_start_dm(data):
    target_username = data.get("target")
    if not target_username:
        return

    target_user = User.query.filter_by(username=target_username).first()
    if not target_user:
        emit("system", {"text": f"User {target_username} does not exist."})
        return

    current_user = session["username"]
    room = get_or_create_dm_room(current_user, target_username)

    join_room(room.name)
    session["room"] = room.name
    emit("join_dm", {"room": room.name, "target": target_username})


@socketio.on("connect")
@login_required
def handle_connect(*args, **kwargs):
    # Prefer query string username (used in tests), fall back to session (web)
    username = request.args.get("username") or session.get("username")
    session["username"] = username
    users[username] = request.sid

    join_room(username)  # personal room for targeted emits
    logging.info(f"Socket connected: {username}")

    emit("user_online", {"username": username}, broadcast=True)
    emit("system", {"text": f"{username} connected."}, broadcast=True)

    # Send the new user a list of who's already online
    online_usernames = [u for u in users.keys() if u != username]
    if online_usernames:
        emit('initial_online_users', {'users': online_usernames})


@socketio.on("join")
def handle_join(data):
    room_name = (data.get("room") or "General").strip()
    room = Room.query.filter_by(name=room_name).first()

    if not room:
        # Auto-create public rooms on first join
        room = Room(name=room_name, type="public")
        db.session.add(room)
        db.session.commit()

    if room.type == "group":
        user = User.query.filter_by(username=session['username']).first()
        if not room.members.filter_by(id=user.id).first():
            emit("system", {"text": f"You are not a member of group '{room.name}'."})
            return

    join_room(room.name)
    session["room"] = room.name
    socketio.emit("system", {"text": f"{session['username']} joined {room.name}."}, to=room.name)


@socketio.on("send_message")
def handle_send_message(data):
    if "user_id" not in session:
        return

    content = data.get("content", "")[:MAX_MESSAGE_LENGTH]
    if not content:
        return

    room_name = session.get("room")
    if not room_name:
        logging.warning(f"No room in session for {session.get('username')}, defaulting to General")
        room_name = "General"

    room = Room.query.filter_by(name=room_name).first()
    if not room:
        # Safety fallback — should not happen under normal usage
        room = Room.query.filter_by(name="General").first()
        session["room"] = room.name

    msg = Message(user_id=session["user_id"], room_id=room.id, content=content)
    db.session.add(msg)
    db.session.commit()

    socketio.emit("receive_message", {
        "user": session["username"],
        "content": content,
        "timestamp": msg.timestamp.isoformat(),
        "room": room.name
    }, to=room.name)


@socketio.on("private_message")
def handle_private_message(data):
    """Save a DM to the DB and emit it to both sender and recipient."""
    me = session.get("username")
    if not me or "user_id" not in session:
        return

    recipient_username = data.get("recipient", "").strip()
    content = data.get("message", "")[:MAX_MESSAGE_LENGTH]
    if not recipient_username or not content:
        return

    recipient = User.query.filter_by(username=recipient_username).first()
    if not recipient:
        return

    msg = Message(user_id=session["user_id"], recipient_id=recipient.id, content=content)
    db.session.add(msg)
    db.session.commit()

    payload = {
        "sender": me,
        "message": content,
        "timestamp": msg.timestamp.isoformat()
    }

    # Deliver to recipient's personal room and echo back to sender
    socketio.emit("private_message", payload, room=recipient.username)
    socketio.emit("private_message", payload, room=me)


@socketio.on("disconnect")
def handle_disconnect(*args, **kwargs):
    username = session.get("username")
    if username:
        users.pop(username, None)
        emit("user_offline", {"username": username}, broadcast=True)
        emit("system", {"text": f"{username} disconnected."})


@socketio.on("typing")
def handle_typing():
    room_name = session.get("room", "General")
    socketio.emit("typing", {"user": session["username"]}, to=room_name)


if __name__ == "__main__":
    init_db()
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)