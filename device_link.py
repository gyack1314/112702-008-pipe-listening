"""通过 TCP 转交合成现场会话。"""

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import socket


def load_scene(path):
    events = []
    with path.open(encoding='utf-8') as source:
        for line_no, line in enumerate(source, 1):
            message = json.loads(line)
            if (set(message) != {'at', 'actor', 'kind', 'body'}
                    or type(message['at']) is not int or message['at'] < 0
                    or not isinstance(message['actor'], str) or not message['actor']
                    or not isinstance(message['kind'], str) or not message['kind']
                    or not isinstance(message['body'], dict)):
                raise ValueError(f'第 {line_no} 行的消息外壳不合法')
            if events and message['at'] < events[-1]['at']:
                raise ValueError(f'第 {line_no} 行的接收时间倒序')
            events.append(message)
    if not events:
        raise ValueError('会话文件为空')
    return events


def encode(message):
    return (json.dumps(message, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


def exchange(events, address, timeout):
    sessions = {}
    with ExitStack() as resources:
        for event in events:
            actor = event['actor']
            if event['kind'] == 'disconnect':
                if actor in sessions:
                    session, _ = sessions.pop(actor)
                    session.close()
                continue
            if actor not in sessions:
                session = resources.enter_context(ExitStack())
                link = session.enter_context(socket.create_connection(address, timeout))
                stream = session.enter_context(link.makefile('rwb'))
                sessions[actor] = session, stream
            _, stream = sessions[actor]
            stream.write(encode(event))
            stream.flush()
            data = stream.readline(1024 * 1024 + 1)
            if not data.endswith(b'\n') or len(data) > 1024 * 1024:
                raise ValueError(f'{actor} 未收到完整的单行响应')
            yield event, json.loads(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scene', type=Path, help='UTF-8 JSON Lines 会话')
    parser.add_argument('--check', action='store_true', help='读取会话格式，不发起连接')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--timeout', type=float, default=4)
    options = parser.parse_args()
    events = load_scene(options.scene)
    if options.check:
        print(f'读取 {len(events)} 条记录，涉及 {len({event["actor"] for event in events})} 个发送方')
        return
    for event, reply in exchange(events, (options.host, options.port), options.timeout):
        print(encode({'request': event, 'reply': reply}).decode('utf-8'), end='')


if __name__ == '__main__':
    main()
