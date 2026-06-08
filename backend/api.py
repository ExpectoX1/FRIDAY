import asyncio
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from neo4j import GraphDatabase
import os

logging.getLogger("neo4j").setLevel(logging.ERROR)

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "friday123"

POLL_INTERVAL = 2  # seconds between graph snapshot polls
PORT = 8766

# =========================================================
# Neo4j helpers
# =========================================================

def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def fetch_graph(driver) -> dict:
    with driver.session() as session:
        # All nodes that appear in at least one relationship
        node_res = session.run("""
            MATCH (n)
            WHERE (n)--()
            RETURN id(n) AS neo_id,
                   n.name AS name,
                   labels(n) AS labels
        """)
        nodes_raw = [r.data() for r in node_res]

        # All relationships (active and expired)
        rel_res = session.run("""
            MATCH (s)-[r]->(t)
            RETURN id(s) AS source_neo,
                   id(t) AS target_neo,
                   s.name AS source,
                   t.name AS target,
                   type(r) AS rel_type,
                   r.importance AS importance,
                   r.confidence AS confidence,
                   r.decay_rate AS decay_rate,
                   r.mention_count AS mention_count,
                   r.valid_to AS valid_to,
                   r.valid_from AS valid_from
        """)
        rels_raw = [r.data() for r in rel_res]

    # Build nodes dict keyed by neo_id → deduplicated name
    node_map = {}
    for n in nodes_raw:
        nid = n["neo_id"]
        label = n["labels"][0] if n["labels"] else "Entity"
        node_map[nid] = {"id": n["name"] or str(nid), "label": label, "neo_id": nid}

    # Ensure all relationship endpoints are represented
    name_to_node = {v["id"]: v for v in node_map.values()}

    links = []
    for r in rels_raw:
        src = r["source"] or str(r["source_neo"])
        tgt = r["target"] or str(r["target_neo"])
        if src not in name_to_node:
            name_to_node[src] = {"id": src, "label": "Entity", "neo_id": r["source_neo"]}
        if tgt not in name_to_node:
            name_to_node[tgt] = {"id": tgt, "label": "Entity", "neo_id": r["target_neo"]}
        links.append({
            "source": src,
            "target": tgt,
            "type": r["rel_type"],
            "importance": r["importance"],
            "confidence": r["confidence"],
            "decay_rate": r["decay_rate"],
            "mention_count": r["mention_count"],
            "valid_from": r["valid_from"],
            "active": r["valid_to"] is None,
        })

    return {"nodes": list(name_to_node.values()), "links": links}


def fetch_stats(driver) -> dict:
    with driver.session() as session:
        r = session.run("""
            MATCH (n) WHERE (n)--()
            WITH count(DISTINCT n) AS node_count
            MATCH ()-[r]->()
            WITH node_count,
                 sum(CASE WHEN coalesce(r.valid_to, null) IS NULL THEN 1 ELSE 0 END) AS active_rels,
                 sum(CASE WHEN coalesce(r.valid_to, null) IS NOT NULL THEN 1 ELSE 0 END) AS expired_rels
            RETURN node_count, active_rels, expired_rels
        """)
        row = r.single()
        if row:
            return {"nodes": row["node_count"], "active_rels": row["active_rels"], "expired_rels": row["expired_rels"]}
        return {"nodes": 0, "active_rels": 0, "expired_rels": 0}


# =========================================================
# WebSocket broadcast manager
# =========================================================

class GraphBroadcaster:
    def __init__(self):
        self.clients: list[WebSocket] = []
        self._last_snapshot: str = ""

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.append(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.remove(ws)

    async def broadcast(self, data: dict):
        payload = json.dumps(data)
        dead = []
        for ws in self.clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.remove(ws)

    async def poll_loop(self, driver):
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            if not self.clients:
                continue
            try:
                graph = fetch_graph(driver)
                snapshot = json.dumps(graph, sort_keys=True)
                if snapshot != self._last_snapshot:
                    self._last_snapshot = snapshot
                    await self.broadcast({"type": "graph", "data": graph})
            except Exception as e:
                await self.broadcast({"type": "error", "message": str(e)})


broadcaster = GraphBroadcaster()
_driver = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _driver
    _driver = get_driver()
    task = asyncio.create_task(broadcaster.poll_loop(_driver))
    yield
    task.cancel()
    _driver.close()


# =========================================================
# App
# =========================================================

app = FastAPI(title="FRIDAY Knowledge Graph", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/api/graph")
async def graph():
    return fetch_graph(_driver)


@app.get("/api/stats")
async def stats():
    return fetch_stats(_driver)


@app.websocket("/ws/graph")
async def ws_graph(websocket: WebSocket):
    await broadcaster.connect(websocket)
    # send current snapshot immediately on connect
    try:
        graph = fetch_graph(_driver)
        await websocket.send_text(json.dumps({"type": "graph", "data": graph}))
        while True:
            # keep alive — client just listens
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
    except Exception:
        broadcaster.disconnect(websocket)
