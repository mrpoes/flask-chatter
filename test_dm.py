from server import app, socketio

def connect_client(username, uid):
    with app.test_client() as flask_client:
        with flask_client.session_transaction() as sess:
            sess["username"] = username
            sess["user_id"] = uid  # ID must exist in DB

        client = socketio.test_client(app, flask_test_client=flask_client)
    return client

# Create two test clients with usernames
c1 = connect_client("alice", 1)
c2 = connect_client("bob", 2)

# Bob sends to Alice
c1.emit("private_message", {"recipient": "bob", "message": "Hi Bob From Alice!"})
c2.emit("private_message", {"recipient": "alice", "message": "Hi Alice From Bob!"})

print("Alice received:", c2.get_received())
print("Bob received:", c1.get_received())