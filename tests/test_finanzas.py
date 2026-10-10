import json
import os
import tempfile
import unittest
from pathlib import Path

from flask import Flask
from app import finanzas


class FinanzasIsolationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.portfolio = self.root / "cartera.json"
        self.portfolio.write_bytes(b'{"portafolio":"NO MODIFICAR"}')
        self.server = Flask(__name__)
        finanzas.montar(self.server, str(self.root))
        self.client = self.server.test_client()
        self.original = self.portfolio.read_bytes()

    def data(self):
        return self.client.get("/api/finanzas").get_json()

    def test_isolated_and_manual(self):
        d = self.data()
        self.assertEqual(len(d["movimientos"]), 0)
        cat = next(c["id"] for c in d["categorias"] if c["tipo"] == "gasto")
        ingreso = next(c["id"] for c in d["categorias"] if c["tipo"] == "ingreso")
        gasto = {"fecha": "2026-10-10", "tipo": "gasto", "concepto": "Supermercado",
                 "importe": "100.00", "categoria": cat}
        ingreso_m = {"fecha": "2026-10-10", "tipo": "ingreso", "concepto": "Nómina",
                     "importe": "500", "categoria": ingreso}
        r = self.client.post("/api/finanzas/movimientos", json=[gasto, ingreso_m])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        r = self.client.post("/api/finanzas/movimientos", json={
            "fecha": "2026-10-11", "tipo": "devolucion", "concepto": "Reembolso",
            "importe": "20", "categoria": cat,
            "original": r.get_json()["movimientos"][0]["id"]})
        self.assertEqual(r.status_code, 200)
        totals = self.client.get("/api/finanzas/analisis").get_json()["total"]
        self.assertEqual(totals["ingresos"], 500)
        self.assertEqual(totals["gastos"], 80)
        self.assertEqual(totals["ahorro"], 420)
        self.assertEqual(self.portfolio.read_bytes(), self.original)
        self.assertFalse((self.root / "copias").exists())
        self.assertTrue((self.root / "finanzas" / "finanzas.json").exists())

    def test_default_category_ids_stable_before_first_save(self):
        first = self.data()
        second = self.data()
        self.assertEqual(first["categorias"], second["categorias"])
        categoria = next(c["id"] for c in first["categorias"] if c["tipo"] == "ingreso")
        response = self.client.post("/api/finanzas/movimientos", json={
            "fecha": "2026-10-05", "tipo": "ingreso", "concepto": "Saldo",
            "importe": "1109", "categoria": categoria})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self.portfolio.read_bytes(), self.original)

    def test_invalid_batch_is_atomic(self):
        cid = next(c["id"] for c in self.data()["categorias"] if c["tipo"] == "gasto")
        base = {"fecha": "2026-10-10", "tipo": "gasto", "concepto": "Test", "importe": 12, "categoria": cid}
        invalid = dict(base, importe=-20)
        self.assertEqual(self.client.post("/api/finanzas/movimientos", json=[base, invalid]).status_code, 400)
        self.assertFalse((self.root / "finanzas" / "finanzas.json").exists())
        self.assertEqual(self.portfolio.read_bytes(), self.original)

    def test_backup_and_restore(self):
        cid = next(c["id"] for c in self.data()["categorias"] if c["tipo"] == "gasto")
        row = {"fecha": "2026-10-10", "tipo": "gasto", "concepto": "Compra", "importe": 15, "categoria": cid}
        self.client.post("/api/finanzas/movimientos", json=row)
        self.client.post("/api/finanzas/movimientos", json=row)
        copies = self.client.get("/api/finanzas/copias").get_json()["copias"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(self.client.post("/api/finanzas/recuperar", json={"nombre": copies[0]}).status_code, 200)
        self.assertEqual(len(self.data()["movimientos"]), 1)
        self.assertEqual(self.portfolio.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
