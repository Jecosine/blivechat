import asyncio
import enum
import json
import logging
import random
import time
import uuid
from typing import *

import aiohttp
import tornado.websocket

import api.base
import blivedm.blivedm as blivedm
import config
import models.log
import models.translate


# noinspection PyAbstractClass
class LogHandler(api.base.ApiHandler):
    def get(self):
        lid = self.get_query_argument('lid', None)
        op = self.get_query_argument('op', None)
        if not lid:
            self.get_all_logs()
        elif op == 'view':
            self.get_content(lid)
        elif op == 'download':
            self.download(lid)

    def delete(self):
        lid = self.get_query_argument('lid', None)
        if not lid:
            self.set_status(400)
            return
        if models.log.delete_danmaku_by_file(lid):
            self.write('1')
        else:
            self.set_status(500)
            self.write('failed')

    def download(self, lid):
        data = models.log.get_danmakus_by_file(lid)
        if data is None:
            self.set_status(404, 'Log not found')
            self.write({
                'code': 404,
                'msg': 'Log not found',
                'data': None
            })
        else:
            filename = models.log.get_log_file_by_lid(lid).filename
            self.set_header('Content-Type', 'application/octet-stream')
            self.set_header(f'Content-Disposition', f'attachment; filename={filename}')
            data = '\n'.join(data).encode()
            self.write(data)

    def get_content(self, lid):
        data = models.log.get_danmakus_by_file(lid)
        if data is None:
            self.set_status(404, 'Log not found')
            self.write({
                'code': 404,
                'msg': 'Log not found',
                'data': None
            })
        else:
            self.write({
                'code': 0,
                'msg': 'success',
                'data': data
            })

    def get_all_logs(self):
        logs = models.log.get_all_logs()
        if logs is None:
            self.set_status(500, 'Failed to get log records')
            self.write({
                'code': '114514',
                'msg': 'Failed to get log records',
                'data': []
            })
        else:
            self.write({
                'code': '0',
                'msg': 'success',
                'data': json.dumps(logs, sort_keys=True, default=str)
            })

    def preview_log(self):
        lid = self.get_query_argument('lid', None)
        if lid is None:
            self.set_status(404, 'No such file')
            return
