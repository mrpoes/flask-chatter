window.addEventListener("DOMContentLoaded", () => {
  const socket = io();
  const messagesDiv = document.getElementById("messages");
  const input = document.getElementById("messageInput");
  const sendBtn = document.getElementById("sendBtn");

  // --- Browser history support ---
  window.onpopstate = () => {
      location.reload();
  };

  // --- Determine initial state from URL/template ---
  let currentRoom = null;
  let currentRecipient = null;

  if (window.CHAT_MODE === "room") {
      currentRoom = window.CHAT_TARGET;
  } else if (window.CHAT_MODE === "dm") {
      currentRecipient = window.CHAT_TARGET;
  }

  let sessionUsername = null;
  let displayedMessageIds = new Set(); // prevent duplicates
  let onlineUsers = new Set();         // track who is online
  let currentRoomIsGroup = false;

  const header = document.getElementById('locationDisplay');
  if (currentRoom) header.textContent = `Room: ${currentRoom}`;
  else if (currentRecipient) header.textContent = `DM: ${currentRecipient}`;

  // HERE
  const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp"];
  const urlRegex = /(https?:\/\/[^\s]+)/g;

  function isImageUrl(url) {
    try {
      const u = new URL(url);
      const ext = u.pathname.split(".").pop().toLowerCase();
      return IMAGE_EXTENSIONS.includes(ext);
    } catch {
      return false;
    }
  }

  function escapeHtml(str) {
    return str
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function renderMessageContent(text) {
    let embedUsed = false;
    let embedHtml = "";

    const renderedText = text.split(urlRegex).map(part => {
      if (!urlRegex.test(part)) {
        return escapeHtml(part);
      }

      const safeLink = `<a href="${part}" target="_blank" rel="noopener noreferrer">${part}</a>`;

      if (embedUsed) return safeLink;

      let embedUrl = null;

      if (isImageUrl(part)) {
        embedUrl = part;
      }

      if (embedUrl) {
        embedUsed = true;
        embedHtml = `
          <div class="embed-image">
            <img src="${embedUrl}" loading="lazy" onerror="this.remove()">
          </div>
        `;
      }

      return safeLink;
    }).join("");

    return renderedText + embedHtml;
  }
  // END

  // --- Message rendering ---
  function addMessage(user, content, isoTimestamp = null, id = null) {
    if (id && displayedMessageIds.has(id)) return;
    if (id) displayedMessageIds.add(id);

    const el = document.createElement("div");
    el.className = "msg";
    if (user === sessionUsername) el.classList.add("owned");

    let formatted = "";
    if (isoTimestamp) {
      const ts = new Date(isoTimestamp);
      const now = new Date();
      formatted = ts.toDateString() === now.toDateString()
        ? ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : ts.toLocaleString([], { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' });
    }

    el.innerHTML = `
      <div class="msg-author">${user}</div>
      <div class="msg-content">${renderMessageContent(content)}</div>
      <div class="msg-timestamp">${formatted || ''}</div>
    `;
    messagesDiv.appendChild(el);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }

  function addSystem(text) {
    const el = document.createElement("div");
    el.className = "sys";
    el.textContent = `[System] ${text}`;
    messagesDiv.appendChild(el);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }

  // --- Fetch session username & initialize links/messages ---
  fetch("/whoami")
    .then(r => r.json())
    .then(d => {
      sessionUsername = d.username;
      console.log(sessionUsername);

      fetch("/rooms").then(r => r.json()).then(renderRoomLinks);
      fetch("/groups").then(r => r.json()).then(renderGroupLinks);
      fetch("/users").then(r => r.json()).then(renderDMLinks);

      if (currentRoom) {
        fetchRoomMessages(currentRoom);
        socket.emit("join", { room: currentRoom });
      }
      if (currentRecipient) fetchDMMessages(currentRecipient);

      // initialize member list
      updateMemberList(currentRoom);

      // --- CREATE GROUP BUTTON ---
      const createBtn = document.getElementById("createGroupBtn");
      if (createBtn) {
        createBtn.addEventListener("click", () => {
          const name = document.getElementById("groupNameInput").value.trim();
          if (!name) return;

          fetch("/chat/group/create", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: `group_name=${encodeURIComponent(name)}`
          })
          .then(r => r.json())
          .then(res => {
            if (res.success) {
              addSystem(`Group '${name}' created.`);
              fetch("/groups").then(r => r.json()).then(renderGroupLinks);
            } else {
              addSystem(res.error || "Failed to create group.");
            }
          })
          .catch(() => addSystem("Network error while creating group."));
        });
      }

      // --- INVITE USER BUTTON ---
      const inviteBtn = document.getElementById("inviteBtn");
      if (inviteBtn) {
        inviteBtn.addEventListener("click", () => {
          const username = document.getElementById("inviteInput").value.trim();
          if (!username || !currentRoom) return;

          fetch("/chat/group/invite", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: `group_name=${encodeURIComponent(currentRoom)}&username=${encodeURIComponent(username)}`
          })
          .then(r => r.json())
          .then(res => {
            if (res.success) {
              addSystem(`${username} added to ${currentRoom}`);
              fetch("/groups").then(r => r.json()).then(renderGroupLinks);
              updateMemberList(currentRoom);
            } else {
              addSystem(res.error || "Failed to invite user.");
            }
          })
          .catch(() => addSystem("Network error while inviting user."));
        });
      }
    })
    .catch(() => addSystem("Failed to fetch session username."));

  // --- Dynamic Room/DM/Group links ---
  function renderRoomLinks(rooms) {
    const container = document.getElementById("roomLinks");
    if (!container) return;
    container.innerHTML = "";
    rooms.forEach(rm => {
      const a = document.createElement("a");
      a.href = `/chat/room/${rm.name}`;
      a.textContent = rm.name;
      if (rm.name === currentRoom) a.style.fontWeight = "bold";
      a.style.marginRight = "8px";
      container.appendChild(a);
    });
  }

  function renderDMLinks(users) {
    const container = document.getElementById("dmLinks");
    if (!container) return;
    container.innerHTML = "";
    users.forEach(u => {
      if (u.username === sessionUsername) return;
      const a = document.createElement("a");
      a.href = `/chat/dm/${u.username}`;
      a.textContent = u.username;
      if (u.username === currentRecipient) a.style.fontWeight = "bold";
      a.style.marginRight = "8px";
      container.appendChild(a);
    });
  }

  function renderGroupLinks(groups) {
    const container = document.getElementById("groupLinks");
    if (!container) return;
    container.innerHTML = "";
    groups.forEach(g => {
      if (!g.members.includes(sessionUsername)) return;
      const a = document.createElement("a");
      a.href = `/chat/room/${g.name}`;
      a.textContent = g.name;
      if (g.name === currentRoom) a.style.fontWeight = "bold";
      a.style.marginRight = "8px";
      container.appendChild(a);
    });
  }

  // --- MEMBER LIST FUNCTIONS ---
  function renderMemberList(members) {
    const container = document.getElementById("memberlist");
    if (!container) return;
    container.innerHTML = "";

    members.forEach(u => {
      const div = document.createElement("div");
      div.style.display = "block";
      div.textContent = u;

      if (onlineUsers.has(u)) {
        console.log(`from renderMemberList: onlineUsers.has(${u})`)
        const circle = document.createElement("span");
        circle.className = "online-circle";
        circle.style.marginLeft = "6px";
        div.appendChild(circle);
      }

      container.appendChild(div);
    });
  }

  function updateMemberList(roomName) {
    const container = document.getElementById("memberlist");
    if (!container || !roomName) return;

    fetch("/groups")
      .then(r => r.json())
      .then(groups => {
        const group = groups.find(g => g.name === roomName);
        currentRoomIsGroup = !!group;

        if (group) {
          // group → only show members
          renderMemberList(group.members);
        } else {
          // public → show all users including self
          fetch("/users?include_self=true")
            .then(r => r.json())
            .then(users => {
              console.log(`from updateMemberList: users = ${users}`)
              const allMembers = users.map(u => u.username);
              if (!allMembers.includes(sessionUsername)) allMembers.unshift(sessionUsername);
              renderMemberList(allMembers);
            });
        }
      });
  }

  function refreshMemberList() {
    if (window.CHAT_MODE === "room" && currentRoom) {
      updateMemberList(currentRoom);
    }
  }

  // --- Socket events for online/offline ---
  socket.on("initial_online_users", data => {
  data.users.forEach(u => onlineUsers.add(u));
  refreshMemberList();
  });

  socket.on("user_online", data => {
    onlineUsers.add(data.username);
    refreshMemberList();
  });

  socket.on("user_offline", data => {
    onlineUsers.delete(data.username);
    console.log(`username ${data.username} deleted from onlineUsers`)
    refreshMemberList();
  });

  // --- Fetch messages ---
  function fetchRoomMessages(room) {
    messagesDiv.innerHTML = "";
    displayedMessageIds.clear();
    fetch(`/messages?room=${encodeURIComponent(room)}`)
      .then(r => r.json())
      .then(list => list.forEach(m => addMessage(m.user, m.content, m.timestamp, m.id)))
      .catch(err => console.error("Failed loading messages:", err));
  }

  function fetchDMMessages(recipient) {
    messagesDiv.innerHTML = "";
    displayedMessageIds.clear();
    fetch(`/messages?recipient=${encodeURIComponent(recipient)}`)
      .then(r => r.json())
      .then(list => list.forEach(m => addMessage(m.user, m.content, m.timestamp, m.id)))
      .catch(err => console.error("Failed loading DM messages:", err));
  }

  // --- Sending messages ---
  function send() {
    const content = input.value.trim();
    if (!content) return;

    if (currentRecipient) {
      socket.emit("private_message", { recipient: currentRecipient, message: content });
      addMessage(sessionUsername, content, new Date().toISOString());
    } else if (currentRoom) {
      socket.emit("send_message", { content });
    }

    input.value = "";
  }

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", e => { if (e.key === "Enter") send(); });

  // --- Receiving messages ---
  socket.on("receive_message", data => {
    if (!currentRecipient && data.room === currentRoom) {
      addMessage(data.user, data.content, data.timestamp, data.id);
    }
  });

  socket.on("private_message", data => {
    if (currentRecipient === data.sender || currentRecipient === data.recipient) {
      addMessage(data.sender, data.message, data.timestamp, data.id);
    }
  });
});
