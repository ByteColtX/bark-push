from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from bark_push import (
    BarkAPIError,
    BarkClient,
    BarkConnectionError,
    BarkHTTPError,
    PushParams,
    decrypt_payload,
)


class _Handler(BaseHTTPRequestHandler):
    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
                "body": body,
            }
        )
        status, payload, content_type = self.server.response  # type: ignore[attr-defined]
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def log_message(self, format: str, *args: object) -> None:
        pass


class BarkClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.requests = []  # type: ignore[attr-defined]
        self.httpd.response = (  # type: ignore[attr-defined]
            200,
            '{"code":200,"message":"success","timestamp":1,"data":{"id":"x"}}',
            "application/json",
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        self.client = BarkClient("KEY", server=f"http://{host}:{port}", timeout=5)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    @property
    def last(self) -> dict:
        return self.httpd.requests[-1]  # type: ignore[attr-defined]

    def test_get_uses_path_segments_and_query(self) -> None:
        response = self.client.send(
            PushParams(title="标题", body="a/b c", group="g", badge=2),
            method="get",
        )
        self.assertTrue(response.ok)
        self.assertEqual(response.code, 200)
        self.assertEqual(response.data, {"id": "x"})
        self.assertEqual(response.payload["timestamp"], 1)

        self.assertEqual(self.last["method"], "GET")
        url = urlsplit(self.last["path"])
        self.assertEqual(url.path, "/KEY/%E6%A0%87%E9%A2%98/a%2Fb%20c")
        self.assertEqual(parse_qs(url.query), {"group": ["g"], "badge": ["2"]})

    def test_get_without_body_puts_everything_in_query(self) -> None:
        self.client.send(PushParams(title="T", group="g"), method="get")
        url = urlsplit(self.last["path"])
        self.assertEqual(url.path, "/KEY")
        self.assertEqual(parse_qs(url.query), {"title": ["T"], "group": ["g"]})

    def test_get_with_subtitle(self) -> None:
        self.client.send(PushParams(title="T", subtitle="S", body="B"), method="get")
        self.assertEqual(urlsplit(self.last["path"]).path, "/KEY/T/S/B")

    def test_json_post(self) -> None:
        self.client.send(
            PushParams(
                title="t",
                body="b",
                badge=2,
                is_archive=False,
                level="timeSensitive",
            )
        )
        self.assertEqual(self.last["method"], "POST")
        self.assertEqual(urlsplit(self.last["path"]).path, "/KEY")
        self.assertEqual(
            self.last["headers"]["Content-Type"],
            "application/json; charset=utf-8",
        )
        self.assertEqual(
            json.loads(self.last["body"]),
            {
                "title": "t",
                "body": "b",
                "badge": 2,
                "level": "timeSensitive",
                "isArchive": "0",
            },
        )

    def test_keyword_fields(self) -> None:
        self.client.send(body="hello", title="hi")
        self.assertEqual(
            json.loads(self.last["body"]), {"title": "hi", "body": "hello"}
        )

    def test_form_post(self) -> None:
        self.client.send(PushParams(title="标题", body="a&b"), method="form")
        self.assertEqual(
            self.last["headers"]["Content-Type"],
            "application/x-www-form-urlencoded; charset=utf-8",
        )
        self.assertEqual(
            parse_qs(self.last["body"].decode()),
            {"title": ["标题"], "body": ["a&b"]},
        )

    def test_push_with_key_in_body(self) -> None:
        self.client.send(PushParams(device_key="OTHER", body="b"), body_key=True)
        self.assertEqual(urlsplit(self.last["path"]).path, "/push")
        self.assertEqual(
            json.loads(self.last["body"]), {"device_key": "OTHER", "body": "b"}
        )

    def test_batch_push(self) -> None:
        self.client.send_many(iter(["k1", "k2"]), PushParams(title="t", body="b"))
        self.assertEqual(urlsplit(self.last["path"]).path, "/push")
        self.assertEqual(
            json.loads(self.last["body"]),
            {"title": "t", "body": "b", "device_keys": ["k1", "k2"]},
        )

    def test_delete(self) -> None:
        self.client.delete("nid")
        self.assertEqual(json.loads(self.last["body"]), {"id": "nid", "delete": "1"})

    def test_api_error(self) -> None:
        self.httpd.response = (  # type: ignore[attr-defined]
            400,
            '{"code":400,"message":"invalid key"}',
            "application/json",
        )
        with self.assertRaises(BarkAPIError) as context:
            self.client.send(body="b")
        error = context.exception
        self.assertEqual(error.code, 400)
        self.assertEqual(error.status, 400)
        self.assertIn("invalid key", str(error))
        self.assertEqual(error.response.payload["code"], 400)

    def test_http_error_without_bark_payload(self) -> None:
        self.httpd.response = (  # type: ignore[attr-defined]
            502,
            "<html>bad gateway</html>",
            "text/html",
        )
        with self.assertRaises(BarkHTTPError) as context:
            self.client.send(body="b")
        self.assertEqual(context.exception.status, 502)
        self.assertIn("bad gateway", context.exception.body)

    def test_http_200_with_error_code(self) -> None:
        self.httpd.response = (  # type: ignore[attr-defined]
            200,
            '{"code":400,"message":"invalid key"}',
            "application/json",
        )
        with self.assertRaises(BarkAPIError):
            self.client.send(body="b")

    def test_http_error_with_success_code_is_http_error(self) -> None:
        self.httpd.response = (  # type: ignore[attr-defined]
            500,
            '{"code":200,"message":"proxy failed"}',
            "application/json",
        )
        with self.assertRaises(BarkHTTPError) as context:
            self.client.send(body="b")
        self.assertEqual(context.exception.status, 500)
        self.assertIn("proxy failed", str(context.exception))

    def test_connection_error(self) -> None:
        client = BarkClient("KEY", server="http://127.0.0.1:1", timeout=1)
        with self.assertRaises(BarkConnectionError):
            client.send(body="b")

    def test_send_encrypted(self) -> None:
        response = self.client.send_encrypted(
            PushParams(
                title="秘密",
                body="hello",
                group="g",
                is_archive=False,
                ttl=30,
                id="n1",
            ),
            "1234567890123456",
            iv="abcdefghijklmnop",
        )
        self.assertTrue(response.ok)
        raw = self.last["body"].decode()
        self.assertNotIn("hello", raw)
        self.assertNotIn("秘密", raw)

        payload = json.loads(raw)
        self.assertEqual(set(payload), {"ciphertext", "iv", "isArchive", "ttl", "id"})
        self.assertEqual(payload["iv"], "abcdefghijklmnop")
        self.assertEqual(payload["isArchive"], "0")
        self.assertEqual(payload["ttl"], 30)
        self.assertEqual(payload["id"], "n1")
        self.assertEqual(
            json.loads(
                decrypt_payload(
                    payload["ciphertext"], "1234567890123456", payload["iv"]
                )
            ),
            {"title": "秘密", "body": "hello", "group": "g"},
        )

    def test_send_encrypted_with_body_key(self) -> None:
        self.client.send_encrypted(
            PushParams(device_key="OTHER", body="b"),
            "1234567890123456",
            body_key=True,
        )
        self.assertEqual(urlsplit(self.last["path"]).path, "/push")
        payload = json.loads(self.last["body"])
        self.assertEqual(payload["device_key"], "OTHER")
        self.assertEqual(set(payload), {"device_key", "ciphertext", "iv"})

    def test_send_encrypted_rejects_unsupported_input(self) -> None:
        with self.assertRaises(ValueError):
            self.client.send_encrypted(
                PushParams(body="b", device_keys=["k1"]), "1234567890123456"
            )
        with self.assertRaises(ValueError):
            self.client.send_encrypted(
                PushParams(body="b", ciphertext="ct", iv="iv"), "1234567890123456"
            )

    def test_device_key_routing_guards(self) -> None:
        with self.assertRaises(ValueError):
            self.client.send(PushParams(device_key="OTHER", body="b"))
        with self.assertRaises(ValueError):
            self.client.send(PushParams(body="b", device_keys=["k1"]))
        with self.assertRaises(ValueError):
            self.client.send(
                PushParams(device_key="K", body="b"),
                body_key=True,
                method="get",
            )
        with self.assertRaises(ValueError):
            self.client.send(body="b", body_key=True)
        with self.assertRaises(ValueError):
            self.client.send(
                PushParams(device_key="OTHER", body="b"),
                key="KEY",
                body_key=True,
            )

    def test_argument_validation(self) -> None:
        with self.assertRaises(TypeError):
            self.client.send()
        with self.assertRaises(TypeError):
            self.client.send(PushParams(body="b"), body="c")
        with self.assertRaises(ValueError):
            self.client.send(body="b", method="put")
        with self.assertRaises(ValueError):
            BarkClient("KEY", timeout=0)

    def test_repr_hides_key(self) -> None:
        self.assertIn("key='<set>'", repr(self.client))
        self.assertNotIn("KEY", repr(self.client))
        self.assertIn("key=None", repr(BarkClient()))

    def test_constructor_validation(self) -> None:
        with self.assertRaises(ValueError):
            BarkClient(123)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            BarkClient("")
        with self.assertRaises(ValueError):
            BarkClient("KEY", server="")
        with self.assertRaises(ValueError):
            BarkClient("KEY", server=123)  # type: ignore[arg-type]

    def test_send_requires_key(self) -> None:
        client = BarkClient(server=self.client.server)
        with self.assertRaises(ValueError):
            client.send(body="b")

    def test_key_override(self) -> None:
        self.client.send(PushParams(body="b"), key="OTHER")
        self.assertEqual(urlsplit(self.last["path"]).path, "/OTHER")

    def test_get_body_without_title_has_no_query(self) -> None:
        self.client.send(PushParams(body="b"), method="get")
        url = urlsplit(self.last["path"])
        self.assertEqual(url.path, "/KEY/b")
        self.assertEqual(url.query, "")

    def test_send_many_rejects_string(self) -> None:
        with self.assertRaises(TypeError):
            self.client.send_many("key1", PushParams(body="b"))

    def test_send_many_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            self.client.send_many([], PushParams(body="b"))

    def test_send_many_rejects_empty_key(self) -> None:
        with self.assertRaises(ValueError):
            self.client.send_many([""], PushParams(body="b"))

    def test_send_many_rejects_non_string_key(self) -> None:
        with self.assertRaises(ValueError):
            self.client.send_many([1], PushParams(body="b"))  # type: ignore[list-item]

    def test_body_key_device_keys_requires_json(self) -> None:
        with self.assertRaises(ValueError):
            self.client.send(
                PushParams(device_keys=["k1"], body="b"),
                body_key=True,
                method="form",
            )

    def test_send_encrypted_requires_params(self) -> None:
        with self.assertRaises(TypeError):
            self.client.send_encrypted("not params", "1234567890123456")  # type: ignore[arg-type]

    def test_send_requires_params_instance(self) -> None:
        with self.assertRaises(TypeError):
            self.client.send("not params")  # type: ignore[arg-type]

    def test_method_must_be_string(self) -> None:
        with self.assertRaises(ValueError):
            self.client.send(body="b", method=1)  # type: ignore[arg-type]

    def test_parse_variants(self) -> None:
        response = BarkClient._parse(200, b'{"code":true}', "utf-8")
        self.assertIsNone(response.code)
        self.assertTrue(response.ok)

        response = BarkClient._parse(
            200, b'{"code":"400","message":123,"data":{"x":1}}', "utf-8"
        )
        self.assertEqual(response.code, 400)
        self.assertIsNone(response.message)
        self.assertEqual(response.data, {"x": 1})
        self.assertFalse(response.ok)

        response = BarkClient._parse(200, b'{"code":"abc"}', "utf-8")
        self.assertIsNone(response.code)
        self.assertTrue(response.ok)

        response = BarkClient._parse(200, b"[]", "utf-8")
        self.assertIsNone(response.code)
        self.assertIsNone(response.message)


if __name__ == "__main__":
    unittest.main()
