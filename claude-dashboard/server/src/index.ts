import express from "express";
import { createServer } from "http";
import { WebSocketServer, WebSocket } from "ws";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import type { ClientMessage, ServerMessage } from "../../shared/src/types.js";
import { SessionManager } from "./session-manager.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const PORT = 3001;
const app = express();
const httpServer = createServer(app);
const wss = new WebSocketServer({ server: httpServer });

// Serve production build
app.use(express.static(join(__dirname, "../../client/dist")));

// Track connected clients
const clients = new Set<WebSocket>();

function broadcast(msg: ServerMessage) {
  const data = JSON.stringify(msg);
  for (const ws of clients) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(data);
    }
  }
}

// One session manager shared across connections
const defaultCwd = process.cwd();
const sessionManager = new SessionManager(defaultCwd, broadcast);

wss.on("connection", (ws) => {
  clients.add(ws);
  console.log(`Client connected (${clients.size} total)`);

  // Send current state
  ws.send(
    JSON.stringify({
      type: "status",
      state: "idle",
    } satisfies ServerMessage)
  );

  ws.on("message", (raw) => {
    try {
      const msg = JSON.parse(raw.toString()) as ClientMessage;

      switch (msg.type) {
        case "prompt":
          if (msg.workingDirectory) {
            sessionManager.setCwd(msg.workingDirectory);
          }
          sessionManager.runQuery(msg.text);
          break;

        case "cancel":
          sessionManager.cancel();
          break;

        case "set_cwd":
          sessionManager.setCwd(msg.path);
          break;
      }
    } catch (err) {
      console.error("Bad message:", err);
    }
  });

  ws.on("close", () => {
    clients.delete(ws);
    console.log(`Client disconnected (${clients.size} total)`);
  });
});

httpServer.listen(PORT, () => {
  console.log(`Dashboard server running on http://localhost:${PORT}`);
  console.log(`WebSocket on ws://localhost:${PORT}`);
  console.log(`Working directory: ${defaultCwd}`);
});
