"""Build a headless visual preview from clearly synthetic fixtures, not device data."""
from pathlib import Path
import os
import subprocess
import tempfile
import threading
from network_server.server import make_server
from network_server.schema import RANGES

root=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="network-ui-qa-") as directory:
    token="visual-test-token-only-not-for-devices"
    server=make_server(("127.0.0.1",0),Path(directory)/"fixture.sqlite3",token)
    store=server.RequestHandlerClass.store
    for seq in (1,2):
        sample=dict.fromkeys(RANGES,0)
        sample.update(seq=seq,uptime_ms=seq*1000,run=1,cycle=1,stage=9,outcome=1,
                      flags=8,position_cdeg=1234,speed_drpm=0,vbus_mv=12000,vbus_quality=1,kind=seq-1)
        store.ingest({"v":1,"device":"AABBCCDDEEFF","session":"0123456789ABCDEF","sample":sample})
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        subprocess.run(["node",str(root/"tools/network_dashboard_preview.cjs"),
                        f"http://127.0.0.1:{server.server_port}",token,
                        str(root/"network_server/test_artifacts")],check=True,env=os.environ.copy())
    finally:server.shutdown();server.server_close();worker.join()
