# -*- coding: utf-8 -*-

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
import models.avatar
import models.translate

logger = logging.getLogger(__name__)


class Command(enum.IntEnum):
    HEARTBEAT = 0
    JOIN_ROOM = 1
    ADD_TEXT = 2
    ADD_GIFT = 3
    ADD_MEMBER = 4
    ADD_SUPER_CHAT = 5
    DEL_SUPER_CHAT = 6
    UPDATE_TRANSLATION = 7


_http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

room_manager: Optional['RoomManager'] = None


def init():
    global room_manager
    room_manager = RoomManager()


class Room(blivedm.BLiveClient):
    HEARTBEAT_INTERVAL = 10

    # 重新定义parse_XXX是为了减少对字段名的依赖，防止B站改字段名
    def __parse_danmaku(self, command):
        info = command['info']
        if info[3]:
            room_id = info[3][3]
            medal_level = info[3][0]
        else:
            room_id = medal_level = 0
        return self._on_receive_danmaku(blivedm.DanmakuMessage(
            None, None, None, info[0][4], None, None, info[0][9], None,
            info[1],
            info[2][0], info[2][1], info[2][2], None, None, info[2][5], info[2][6], None,
            medal_level, None, None, room_id, None, None,
            info[4][0], None, None,
            None, None,
            info[7]
        ))

    def __parse_gift(self, command):
        data = command['data']
        return self._on_receive_gift(blivedm.GiftMessage(
            data['giftName'], data['num'], data['uname'], data['face'], None,
            data['uid'], data['timestamp'], None, None,
            None, None, None, data['coin_type'], data['total_coin']
        ))

    def __parse_buy_guard(self, command):
        data = command['data']
        return self._on_buy_guard(blivedm.GuardBuyMessage(
            data['uid'], data['username'], data['guard_level'], None, None,
            None, None, data['start_time'], None
        ))

    def __parse_super_chat(self, command):
        data = command['data']
        return self._on_super_chat(blivedm.SuperChatMessage(
            data['price'], data['message'], None, data['start_time'],
            None, None, data['id'], None,
            None, data['uid'], data['user_info']['uname'],
            data['user_info']['face'], None,
            None, None,
            None, None, None,
            None
        ))

    _COMMAND_HANDLERS = {
        **blivedm.BLiveClient._COMMAND_HANDLERS,
        'DANMU_MSG': __parse_danmaku,
        'SEND_GIFT': __parse_gift,
        'GUARD_BUY': __parse_buy_guard,
        'SUPER_CHAT_MESSAGE': __parse_super_chat
    }

    def __init__(self, room_id):
        super().__init__(room_id, session=_http_session, heartbeat_interval=self.HEARTBEAT_INTERVAL)
        self.clients: List['ChatHandler'] = []
        self.auto_translate_count = 0

    async def init_room(self):
        await super().init_room()
        return True

    def stop_and_close(self):
        if self.is_running:
            future = self.stop()
            future.add_done_callback(lambda _future: asyncio.ensure_future(self.close()))
        else:
            asyncio.ensure_future(self.close())

    def send_message(self, cmd, data):
        body = json.dumps({'cmd': cmd, 'data': data})
        for client in self.clients:
            try:
                client.write_message(body)
            except tornado.websocket.WebSocketClosedError:
                room_manager.del_client(self.room_id, client)

    def send_message_if(self, can_send_func: Callable[['ChatHandler'], bool], cmd, data):
        body = json.dumps({'cmd': cmd, 'data': data})
        for client in filter(can_send_func, self.clients):
            try:
                client.write_message(body)
            except tornado.websocket.WebSocketClosedError:
                room_manager.del_client(self.room_id, client)

    async def _on_receive_danmaku(self, danmaku: blivedm.DanmakuMessage):
        asyncio.ensure_future(self.__on_receive_danmaku(danmaku))

    async def __on_receive_danmaku(self, danmaku: blivedm.DanmakuMessage):
        if danmaku.uid == self.room_owner_uid:
            author_type = 3  # 主播
        elif danmaku.admin:
            author_type = 2  # 房管
        elif danmaku.privilege_type != 0:  # 1总督，2提督，3舰长
            author_type = 1  # 舰队
        else:
            author_type = 0

        need_translate = self._need_translate(danmaku.msg)
        if need_translate:
            translation = models.translate.get_translation_from_cache(danmaku.msg)
            if translation is None:
                # 没有缓存，需要后面异步翻译后通知
                translation = ''
            else:
                need_translate = False
        else:
            translation = ''

        id_ = uuid.uuid4().hex
        # 为了节省带宽用list而不是dict
        self.send_message(Command.ADD_TEXT, make_text_message(
            await models.avatar.get_avatar_url(danmaku.uid),
            int(danmaku.timestamp / 1000),
            danmaku.uname,
            author_type,
            danmaku.msg,
            danmaku.privilege_type,
            danmaku.msg_type,
            danmaku.user_level,
            danmaku.urank < 10000,
            danmaku.mobile_verify,
            0 if danmaku.room_id != self.room_id else danmaku.medal_level,
            id_,
            translation
        ))

        if need_translate:
            await self._translate_and_response(danmaku.msg, id_)

    async def _on_receive_gift(self, gift: blivedm.GiftMessage):
        avatar_url = models.avatar.process_avatar_url(gift.face)
        models.avatar.update_avatar_cache(gift.uid, avatar_url)
        if gift.coin_type != 'gold':  # 丢人
            return
        id_ = uuid.uuid4().hex
        self.send_message(Command.ADD_GIFT, {
            'id': id_,
            'avatarUrl': avatar_url,
            'timestamp': gift.timestamp,
            'authorName': gift.uname,
            'totalCoin': gift.total_coin,
            'giftName': gift.gift_name,
            'num': gift.num
        })

    async def _on_buy_guard(self, message: blivedm.GuardBuyMessage):
        asyncio.ensure_future(self.__on_buy_guard(message))

    async def __on_buy_guard(self, message: blivedm.GuardBuyMessage):
        id_ = uuid.uuid4().hex
        self.send_message(Command.ADD_MEMBER, {
            'id': id_,
            'avatarUrl': await models.avatar.get_avatar_url(message.uid),
            'timestamp': message.start_time,
            'authorName': message.username,
            'privilegeType': message.guard_level
        })

    async def _on_super_chat(self, message: blivedm.SuperChatMessage):
        avatar_url = models.avatar.process_avatar_url(message.face)
        models.avatar.update_avatar_cache(message.uid, avatar_url)

        need_translate = self._need_translate(message.message)
        if need_translate:
            translation = models.translate.get_translation_from_cache(message.message)
            if translation is None:
                # 没有缓存，需要后面异步翻译后通知
                translation = ''
            else:
                need_translate = False
        else:
            translation = ''

        id_ = str(message.id)
        self.send_message(Command.ADD_SUPER_CHAT, {
            'id': id_,
            'avatarUrl': avatar_url,
            'timestamp': message.start_time,
            'authorName': message.uname,
            'price': message.price,
            'content': message.message,
            'translation': translation
        })

        if need_translate:
            asyncio.ensure_future(self._translate_and_response(message.message, id_))

    async def _on_super_chat_delete(self, message: blivedm.SuperChatDeleteMessage):
        self.send_message(Command.ADD_SUPER_CHAT, {
            'ids': list(map(str, message.ids))
        })

    def _need_translate(self, text):
        cfg = config.get_config()
        return (
            cfg.enable_translate
            and (not cfg.allow_translate_rooms or self.room_id in cfg.allow_translate_rooms)
            and self.auto_translate_count > 0
            and models.translate.need_translate(text)
        )

    async def _translate_and_response(self, text, msg_id):
        translation = await models.translate.translate(text)
        if translation is None:
            return
        self.send_message_if(
            lambda client: client.auto_translate,
            Command.UPDATE_TRANSLATION, make_translation_message(
                msg_id,
                translation
            )
        )


def make_text_message(avatar_url, timestamp, author_name, author_type, content, privilege_type,
                      is_gift_danmaku, author_level, is_newbie, is_mobile_verified, medal_level,
                      id_, translation):
    return [
        # 0: avatarUrl
        avatar_url,
        # 1: timestamp
        timestamp,
        # 2: authorName
        author_name,
        # 3: authorType
        author_type,
        # 4: content
        content,
        # 5: privilegeType
        privilege_type,
        # 6: isGiftDanmaku
        1 if is_gift_danmaku else 0,
        # 7: authorLevel
        author_level,
        # 8: isNewbie
        1 if is_newbie else 0,
        # 9: isMobileVerified
        1 if is_mobile_verified else 0,
        # 10: medalLevel
        medal_level,
        # 11: id
        id_,
        # 12: translation
        translation
    ]


def make_translation_message(msg_id, translation):
    return [
        # 0: id
        msg_id,
        # 1: translation
        translation
    ]


class RoomManager:
    def __init__(self):
        self._rooms: Dict[int, Room] = {}

    async def get_room(self, room_id):
        if room_id not in self._rooms:
            if not await self._add_room(room_id):
                return
        room = self._rooms.get(room_id, None)
        return room

    async def add_client(self, room_id, client: 'ChatHandler'):
        if room_id not in self._rooms:
            if not await self._add_room(room_id):
                client.close()
                return
        room = self._rooms.get(room_id, None)
        if room is None:
            return

        room.clients.append(client)
        logger.info('%d clients in room %s', len(room.clients), room_id)
        if client.auto_translate:
            room.auto_translate_count += 1

        await client.on_join_room()

    def del_client(self, room_id, client: 'ChatHandler'):
        room = self._rooms.get(room_id, None)
        if room is None:
            return

        try:
            room.clients.remove(client)
        except ValueError:
            # _add_room未完成，没有执行到room.clients.append
            pass
        else:
            logger.info('%d clients in room %s', len(room.clients), room_id)
            if client.auto_translate:
                room.auto_translate_count = max(0, room.auto_translate_count - 1)

        if not room.clients:
            self._del_room(room_id)

    async def _add_room(self, room_id):
        if room_id in self._rooms:
            return True
        logger.info('Creating room %d', room_id)
        self._rooms[room_id] = room = Room(room_id)
        if await room.init_room():
            room.start()
            logger.info('%d rooms', len(self._rooms))
            return True
        else:
            self._del_room(room_id)
            return False

    def _del_room(self, room_id):
        room = self._rooms.get(room_id, None)
        if room is None:
            return
        logger.info('Removing room %d', room_id)
        for client in room.clients:
            client.close()
        room.stop_and_close()
        self._rooms.pop(room_id, None)
        logger.info('%d rooms', len(self._rooms))


# noinspection PyAbstractClass
class ChatHandler(tornado.websocket.WebSocketHandler):
    HEARTBEAT_INTERVAL = 10
    RECEIVE_TIMEOUT = HEARTBEAT_INTERVAL + 5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._heartbeat_timer_handle = None
        self._receive_timeout_timer_handle = None

        self.room_id = None
        self.auto_translate = False

    def open(self):
        logger.info('Websocket connected %s', self.request.remote_ip)
        self._heartbeat_timer_handle = asyncio.get_event_loop().call_later(
            self.HEARTBEAT_INTERVAL, self._on_send_heartbeat
        )
        self._refresh_receive_timeout_timer()

    def _on_send_heartbeat(self):
        self.send_message(Command.HEARTBEAT, {})
        self._heartbeat_timer_handle = asyncio.get_event_loop().call_later(
            self.HEARTBEAT_INTERVAL, self._on_send_heartbeat
        )

    def _refresh_receive_timeout_timer(self):
        if self._receive_timeout_timer_handle is not None:
            self._receive_timeout_timer_handle.cancel()
        self._receive_timeout_timer_handle = asyncio.get_event_loop().call_later(
            self.RECEIVE_TIMEOUT, self._on_receive_timeout
        )

    def _on_receive_timeout(self):
        logger.warning('Client %s timed out', self.request.remote_ip)
        self._receive_timeout_timer_handle = None
        self.close()

    def on_close(self):
        logger.info('Websocket disconnected %s room: %s', self.request.remote_ip, str(self.room_id))
        if self.has_joined_room:
            room_manager.del_client(self.room_id, self)
        if self._heartbeat_timer_handle is not None:
            self._heartbeat_timer_handle.cancel()
            self._heartbeat_timer_handle = None
        if self._receive_timeout_timer_handle is not None:
            self._receive_timeout_timer_handle.cancel()
            self._receive_timeout_timer_handle = None

    def on_message(self, message):
        try:
            # 超时没有加入房间也断开
            if self.has_joined_room:
                self._refresh_receive_timeout_timer()

            body = json.loads(message)
            cmd = body['cmd']
            if cmd == Command.HEARTBEAT:
                pass
            elif cmd == Command.JOIN_ROOM:
                if self.has_joined_room:
                    return
                self._refresh_receive_timeout_timer()

                self.room_id = int(body['data']['roomId'])
                logger.info('Client %s is joining room %d', self.request.remote_ip, self.room_id)
                try:
                    cfg = body['data']['config']
                    self.auto_translate = cfg['autoTranslate']
                except KeyError:
                    pass

                asyncio.ensure_future(room_manager.add_client(self.room_id, self))
            else:
                logger.warning('Unknown cmd, client: %s, cmd: %d, body: %s', self.request.remote_ip, cmd, body)
        except Exception:
            logger.exception('on_message error, client: %s, message: %s', self.request.remote_ip, message)

    # 跨域测试用
    def check_origin(self, origin):
        if self.application.settings['debug']:
            return True
        return super().check_origin(origin)

    @property
    def has_joined_room(self):
        return self.room_id is not None

    def send_message(self, cmd, data):
        body = json.dumps({'cmd': cmd, 'data': data})
        try:
            self.write_message(body)
        except tornado.websocket.WebSocketClosedError:
            self.close()

    async def on_join_room(self):
        if self.application.settings['debug']:
            await self.send_test_message()

        # 不允许自动翻译的提示
        if self.auto_translate:
            cfg = config.get_config()
            if cfg.allow_translate_rooms and self.room_id not in cfg.allow_translate_rooms:
                self.send_message(Command.ADD_TEXT, make_text_message(
                    models.avatar.DEFAULT_AVATAR_URL,
                    int(time.time()),
                    'blivechat',
                    2,
                    'Translation is not allowed in this room. Please download to use translation',
                    0,
                    False,
                    60,
                    False,
                    True,
                    0,
                    uuid.uuid4().hex,
                    ''
                ))

    # 测试用
    async def send_test_message(self):
        base_data = {
            'avatarUrl': await models.avatar.get_avatar_url(300474),
            'timestamp': int(time.time()),
            'authorName': 'xfgryujk',
        }
        text_data = make_text_message(
            base_data['avatarUrl'],
            base_data['timestamp'],
            base_data['authorName'],
            0,
            '我能吞下玻璃而不伤身体',
            0,
            False,
            20,
            False,
            True,
            0,
            uuid.uuid4().hex,
            ''
        )
        member_data = {
            **base_data,
            'id': uuid.uuid4().hex,
            'privilegeType': 3
        }
        gift_data = {
            **base_data,
            'id': uuid.uuid4().hex,
            'totalCoin': 450000,
            'giftName': '摩天大楼',
            'num': 1
        }
        sc_data = {
            **base_data,
            'id': str(random.randint(1, 65535)),
            'price': 30,
            'content': 'The quick brown fox jumps over the lazy dog',
            'translation': ''
        }
        self.send_message(Command.ADD_TEXT, text_data)
        text_data[2] = '主播'
        text_data[3] = 3
        text_data[4] = "I can eat glass, it doesn't hurt me."
        text_data[11] = uuid.uuid4().hex
        self.send_message(Command.ADD_TEXT, text_data)
        self.send_message(Command.ADD_MEMBER, member_data)
        self.send_message(Command.ADD_SUPER_CHAT, sc_data)
        sc_data['id'] = str(random.randint(1, 65535))
        sc_data['price'] = 100
        sc_data['content'] = '敏捷的棕色狐狸跳过了懒狗'
        self.send_message(Command.ADD_SUPER_CHAT, sc_data)
        # self.send_message(Command.DEL_SUPER_CHAT, {'ids': [sc_data['id']]})
        self.send_message(Command.ADD_GIFT, gift_data)
        gift_data['id'] = uuid.uuid4().hex
        gift_data['totalCoin'] = 1245000
        gift_data['giftName'] = '小电视飞船'
        self.send_message(Command.ADD_GIFT, gift_data)


# noinspection PyAbstractClass
class RoomInfoHandler(api.base.ApiHandler):
    _host_server_list_cache = blivedm.DEFAULT_DANMAKU_SERVER_LIST

    async def get(self):
        room_id = int(self.get_query_argument('roomId'))
        logger.info('Client %s is getting room info %d', self.request.remote_ip, room_id)
        room_id, owner_uid = await self._get_room_info(room_id)
        host_server_list = await self._get_server_host_list(room_id)
        if owner_uid == 0:
            # 缓存3分钟
            self.set_header('Cache-Control', 'private, max-age=180')
        else:
            # 缓存1天
            self.set_header('Cache-Control', 'private, max-age=86400')
        self.write({
            'roomId': room_id,
            'ownerUid': owner_uid,
            'hostServerList': host_server_list
        })

    @staticmethod
    async def _get_room_info(room_id):
        try:
            async with _http_session.get(blivedm.ROOM_INIT_URL, params={'room_id': room_id}
                                         ) as res:
                if res.status != 200:
                    logger.warning('room %d _get_room_info failed: %d %s', room_id,
                                   res.status, res.reason)
                    return room_id, 0
                data = await res.json()
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            logger.exception('room %d _get_room_info failed', room_id)
            return room_id, 0

        if data['code'] != 0:
            logger.warning('room %d _get_room_info failed: %s', room_id, data['message'])
            return room_id, 0

        room_info = data['data']['room_info']
        return room_info['room_id'], room_info['uid']

    @classmethod
    async def _get_server_host_list(cls, _room_id):
        return cls._host_server_list_cache

        # 连接其他host必须要key
        # try:
        #     async with _http_session.get(blivedm.DANMAKU_SERVER_CONF_URL, params={'id': room_id, 'type': 0}
        #                                  ) as res:
        #         if res.status != 200:
        #             logger.warning('room %d _get_server_host_list failed: %d %s', room_id,
        #                            res.status, res.reason)
        #             return cls._host_server_list_cache
        #         data = await res.json()
        # except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
        #     logger.exception('room %d _get_server_host_list failed', room_id)
        #     return cls._host_server_list_cache
        #
        # if data['code'] != 0:
        #     logger.warning('room %d _get_server_host_list failed: %s', room_id, data['message'])
        #     return cls._host_server_list_cache
        #
        # host_server_list = data['data']['host_list']
        # if not host_server_list:
        #     logger.warning('room %d _get_server_host_list failed: host_server_list is empty')
        #     return cls._host_server_list_cache
        #
        # cls._host_server_list_cache = host_server_list
        # return host_server_list


# noinspection PyAbstractClass
class AvatarHandler(api.base.ApiHandler):
    async def get(self):
        uid = int(self.get_query_argument('uid'))
        avatar_url = await models.avatar.get_avatar_url_or_none(uid)
        if avatar_url is None:
            avatar_url = models.avatar.DEFAULT_AVATAR_URL
            # 缓存3分钟
            self.set_header('Cache-Control', 'private, max-age=180')
        else:
            # 缓存1天
            self.set_header('Cache-Control', 'private, max-age=86400')
        self.write({
            'avatarUrl': avatar_url
        })


# noinspection PyAbstractClass
# handle reply message
class ReplyHandler(api.base.ApiHandler):
    async def post(self):
        logger.info(self.json_args)
        uid = None if self.json_args['uid'] == -1 else self.json_args['uid']
        avatar_url = await models.avatar.get_avatar_url(uid)
        text_message = make_text_message(
            avatar_url=avatar_url,
            timestamp=int(time.time()),
            author_name=self.json_args['name'],
            author_type=3,
            content=self.json_args['content'],
            author_level=0,
            id_=uuid.uuid4().hex,
            privilege_type=0,
            is_newbie=0,
            is_gift_danmaku=0,
            is_mobile_verified=True,
            medal_level=0,
            translation=0
        )
        # get room
        room: Room = await room_manager.get_room(room_id=self.json_args['room_id'])
        room.send_message(Command.ADD_TEXT, text_message)

