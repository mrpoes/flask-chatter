from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

room_members = db.Table(
    "room_members",
    db.Column("room_id", db.Integer, db.ForeignKey("rooms.id"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("role", db.String(20), default="member")  # owner/member
)
group_members = db.Table(
    "group_members",
    db.Column("room_id", db.Integer, db.ForeignKey("rooms.id"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("role", db.String(20), default="member")  # owner/member
)
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(
        db.String(80, collation="NOCASE"),
        unique=True,
        nullable=False
    )
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # messages sent by the user
    messages = db.relationship(
        "Message",
        back_populates="user",
        lazy="dynamic",
        foreign_keys="Message.user_id"   # <--- explicitly specify
    )

    # messages received by the user (optional convenience)
    received_messages = db.relationship(
        "Message",
        back_populates="recipient",
        lazy="dynamic",
        foreign_keys="Message.recipient_id"  # <--- explicitly specify
    )

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

@event.listens_for(User.username, "set", retval=True) 
def normalize_username(target, value, oldvalue, initiator): 
    return value.lower() if value else value

class Room(db.Model):
    __tablename__ = "rooms"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    type = db.Column(db.String(20), default="public")  # "public" or "dm"
    members = db.relationship(
        "User",
        secondary=room_members,
        backref=db.backref("groups", lazy="dynamic"),
        lazy="dynamic"
    )
    # one-to-many: room → messages
    messages = db.relationship("Message", back_populates="room", lazy="dynamic")


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # sender
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user = db.relationship("User", back_populates="messages", foreign_keys=[user_id])

    # optional recipient (for DMs)
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    recipient = db.relationship("User", back_populates="received_messages", foreign_keys=[recipient_id])

    # optional room
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=True)
    room = db.relationship("Room", back_populates="messages")
    def to_dict(self):
        return {
            "id": self.id,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "user": self.user.username if self.user else "Unknown",
            "room": self.room.name if self.room else "Unknown",
            "recipient": self.recipient.username if self.recipient else None
        }
    
