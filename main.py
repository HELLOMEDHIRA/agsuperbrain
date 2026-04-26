"""Demo: sample module → ingest → query → `graph.html`."""
from pathlib import Path

from agsuperbrain.terminal import TEXT_ENCODING, console

SAMPLE = '''\
import json

def load_config(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def validate(cfg):
    return all(k in cfg for k in ["host","port"])

def connect(cfg):
    print(f"Connecting to {cfg['host']}")
    return cfg

def run_query(conn, q):
    print(f"Query: {q}")
    return []

class DataProcessor:
    def __init__(self, cfg_path):
        cfg = load_config(cfg_path)
        if not validate(cfg):
            raise ValueError("bad config")
        self.conn = connect(cfg)

    def process(self, q):
        results = run_query(self.conn, q)
        return self._transform(results)

    def _transform(self, data):
        return [str(x) for x in data]

def main():
    dp = DataProcessor("config.json")
    out = dp.process("SELECT * FROM users")
    print(len(out))

if __name__ == "__main__":
    main()
'''

if __name__ == "__main__":
    sample = Path("./sample_src/app.py")
    sample.parent.mkdir(exist_ok=True)
    sample.write_text(SAMPLE, encoding=TEXT_ENCODING)

    from agsuperbrain.memory.graph.graph_store import GraphStore
    store = GraphStore(Path("./.agsuperbrain/graph"))
    store.init_schema()

    from agsuperbrain.core.pipeline import CodeGraphPipeline
    CodeGraphPipeline(store).run([sample], verbose=True)

    console.rule("Call graph: DataProcessor methods")
    for row in store.query(
        "MATCH (cr:Function)-[:CALLS]->(ce:Function) "
        "WHERE cr.qualified_name CONTAINS 'DataProcessor' "
        "RETURN cr.qualified_name, ce.name"
    ):
        console.print(f"  [cyan]{row[0]}[/cyan] → [green]{row[1]}[/green]")

    from agsuperbrain.memory.graph.visualizer import visualize
    visualize(store, Path("./output/graph.html"))
    console.print("\n[bold green]Open:[/bold green] ./output/graph.html")
