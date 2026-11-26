"""核对现场会话文件和 TCP 联调工具。"""

from hashlib import sha256
import json
from pathlib import Path
import socketserver
from threading import Thread
import unittest

from device_link import encode, exchange, load_scene


class LoopbackHandler(socketserver.StreamRequestHandler):
    def handle(self):
        for message in self.rfile:
            event = json.loads(message)
            self.wfile.write(encode({'event': event, 'session_port': self.client_address[1]}))


class LocalLinkTests(unittest.TestCase):
    def test_published_scene(self):
        events = load_scene(Path(__file__).resolve().parents[1] / 'field-session.jsonl')
        self.assertGreater(len(events), 10)
        disconnected = next(e for e in events if e['kind'] == 'disconnect')
        actor = disconnected['actor']
        self.assertTrue(any(e['actor'] == actor and e['at'] > disconnected['at'] for e in events))
        for event in events:
            body = event['body']
            if 'digest' in body:
                fragments = json.dumps(body['values'], separators=(',', ':')).encode('utf-8')
                self.assertEqual(body['digest'], sha256(fragments).hexdigest())
                first, after_last = body['ticks']
                self.assertEqual(len(body['values']), len(range(first, after_last, body['stride'])))
        receipts = self.receipts(events)
        self.assertEqual([reply['event'] for reply in receipts],
                         [event for event in events if event['kind'] != 'disconnect'])

    def test_loopback_and_connection_reset(self):
        def record(at, actor, kind):
            return {'at': at, 'actor': actor, 'kind': kind, 'body': {}}

        messages = [record(0, '站点', 'wake'), record(1, '站点', 'report'),
                    record(2, '控制台', 'query'), record(3, '站点', 'disconnect'),
                    record(4, '站点', 'report')]
        receipts = self.receipts(messages)
        ports = [reply['session_port'] for reply in receipts]
        self.assertEqual([reply['event']['kind'] for reply in receipts], ['wake', 'report', 'query', 'report'])
        self.assertEqual(ports[0], ports[1])
        self.assertEqual(len(set(ports)), 3)

    def receipts(self, messages):
        with socketserver.ThreadingTCPServer(('127.0.0.1', 0), LoopbackHandler) as server:
            thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
            thread.start()
            try:
                return [reply for _, reply in exchange(messages, server.server_address, 2)]
            finally:
                server.shutdown()
                thread.join()


if __name__ == '__main__':
    unittest.main()
