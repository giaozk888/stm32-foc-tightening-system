import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import sqlite3
from network_server.schema import RANGES, validate
from network_server.store import Store, Conflict
from network_server.server import make_server

TOKEN = "test-only-token-not-for-real-device-0001"
def packet(seq=1, kind=0):
    s = dict.fromkeys(RANGES, 0)
    s.update(seq=seq, uptime_ms=1000, run=1, cycle=1, stage=9,
             outcome=1, flags=8, position_cdeg=-1234, vbus_quality=1, kind=kind)
    return {"v":1,"device":"AABBCCDDEEFF","session":"0123456789ABCDEF","sample":s}

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/"obs.sqlite3"
        self.store=Store(self.path)
    def tearDown(self): self.tmp.cleanup()
    def test_dedup_and_conflict(self):
        self.assertTrue(self.store.ingest(packet())["inserted"])
        self.assertFalse(self.store.ingest(packet())["inserted"])
        p=packet(); p["sample"]["iq_ma"]=42
        with self.assertRaises(Conflict): self.store.ingest(p)
        self.assertEqual(self.store.summary()["samples"],1)
    def test_survives_server_restart(self):
        self.store.ingest(packet()); other=Store(self.path)
        self.assertEqual(other.records()[0]["sample"]["seq"],1)
    def test_result_filter_csv_pagination(self):
        self.store.ingest(packet()); self.store.ingest(packet(2,1))
        self.assertEqual(self.store.summary()["results"],1)
        self.assertEqual(self.store.records(limit=1)[0]["id"],1)
        self.assertEqual(self.store.records(after=1)[0]["id"],2)
        self.assertEqual(self.store.records(kind=1)[0]["sample"]["kind"],1)
        self.assertIn("-1234",self.store.csv_bytes().decode("utf-8-sig"))
        self.assertFalse(self.store.summary()["control_enabled"])
    def test_schema_rejects_commands_types_and_ranges(self):
        for key in RANGES:
            p=packet(); p["sample"][key]=True
            with self.assertRaises(ValueError): validate(p)
            p=packet(); p["sample"][key]=RANGES[key][1]+1
            with self.assertRaises(ValueError): validate(p)
        for p in [[], {}, {**packet(), "command":"START"}]:
            with self.assertRaises(ValueError): validate(p)
        p=packet(1,1); p["sample"]["outcome"]=0
        with self.assertRaises(ValueError):validate(p)
    def test_reboot_session_does_not_collide(self):
        self.store.ingest(packet()); p=packet();p["session"]="FEDCBA9876543210"
        self.store.ingest(p); self.assertEqual(self.store.summary()["samples"],2)
    def test_concurrent_retry_single_record(self):
        errors=[]
        def submit():
            try:self.store.ingest(packet())
            except Exception as e:errors.append(e)
        workers=[threading.Thread(target=submit) for _ in range(10)]
        for w in workers:w.start()
        for w in workers:w.join()
        self.assertEqual(errors,[]);self.assertEqual(self.store.summary()["samples"],1)

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.server=make_server(("127.0.0.1",0),Path(self.tmp.name)/"data.sqlite3",TOKEN)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.worker.join();self.tmp.cleanup()
    def request(self, method, path, payload=None, auth=TOKEN, extra=None):
        c=http.client.HTTPConnection(*self.server.server_address,timeout=3)
        h={"Content-Type":"application/json"}
        if auth is not None:h["Authorization"]="Bearer "+auth
        h.update(extra or {})
        body=json.dumps(payload) if payload is not None else None
        c.request(method,path,body,h);r=c.getresponse()
        result=(r.status,dict(r.getheaders()),r.read());c.close();return result
    def test_roundtrip_exact_ack_duplicate_and_export(self):
        status,h,body=self.request("POST","/api/v1/observations",packet(10,1))
        self.assertEqual(status,201);self.assertEqual(h["X-Observation-Ack"],"0123456789ABCDEF:10")
        self.assertEqual(json.loads(body)["ack"]["seq"],10)
        self.assertEqual(self.request("POST","/api/v1/observations",packet(10,1))[0],200)
        status,_,body=self.request("GET","/api/v1/observations?kind=1")
        self.assertEqual(status,200);self.assertEqual(len(json.loads(body)["records"]),1)
        self.assertEqual(self.request("GET","/api/v1/export.csv")[0],200)
    def test_auth_and_no_control_endpoint(self):
        self.assertEqual(self.request("POST","/api/v1/observations",packet(),auth=None)[0],401)
        self.assertEqual(self.request("GET","/api/v1/summary",auth="wrong")[0],401)
        for action in ("start","stop","relay","iap","command"):
            self.assertEqual(self.request("POST","/api/"+action,{"command":"START"})[0],404)
        self.assertEqual(self.server.RequestHandlerClass.store.summary()["samples"],0)
    def test_bad_body_range_query_and_conflict(self):
        self.assertEqual(self.request("POST","/api/v1/observations",[])[0],400)
        p=packet();p["sample"]["seq"]=2**32
        self.assertEqual(self.request("POST","/api/v1/observations",p)[0],400)
        self.assertEqual(self.request("GET","/api/v1/observations?limit=999")[0],400)
        self.request("POST","/api/v1/observations",packet())
        p=packet();p["sample"]["vbus_mv"]=100
        self.assertEqual(self.request("POST","/api/v1/observations",p)[0],409)
    def test_storage_failure_has_no_ack(self):
        with patch.object(self.server.RequestHandlerClass.store,"ingest",side_effect=sqlite3.OperationalError("disk full")):
            status,h,_=self.request("POST","/api/v1/observations",packet())
        self.assertEqual(status,503);self.assertNotIn("X-Observation-Ack",h)
    def test_no_secrets_in_assets(self):
        status,_,body=self.request("GET","/",auth=None)
        self.assertEqual(status,200);self.assertNotIn(TOKEN.encode(),body)

if __name__=="__main__":unittest.main()
