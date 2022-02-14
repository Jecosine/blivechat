import asyncio
import datetime
import json
import logging
import re
import time
from typing import *

import aiohttp
import sqlalchemy.orm
import sqlalchemy
import sqlalchemy.exc
from sqlalchemy.sql import func
import config
import models.database

logger = logging.getLogger(__name__)

_room_log_mapper = {}


class LogItem(models.database.OrmBase):
    __tablename__ = 'danmaku'
    did = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    lid = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey('log_records.lid'))
    content = sqlalchemy.Column(sqlalchemy.Text)
    logfile = sqlalchemy.orm.relationship("LogFile", back_populates="danmakus")


class LogFile(models.database.OrmBase):
    __tablename__ = 'log_records'
    lid = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    filename = sqlalchemy.Column(sqlalchemy.String(64))
    room_id = sqlalchemy.Column(sqlalchemy.Integer)
    create_time = sqlalchemy.Column(sqlalchemy.DateTime, server_default=func.now())
    danmakus = sqlalchemy.orm.relationship('LogItem', back_populates="logfile", cascade="all, delete, delete-orphan")


# https://stackoverflow.com/a/37350445
def object_as_dict(obj):
    return {c.key: getattr(obj, c.key) for c in sqlalchemy.inspect(obj).mapper.column_attrs}


def log_file_name():
    return time.strftime('%Y-%m-%d-%H-%M-%S.log')


def get_danmakus_by_file(lid):
    try:
        with models.database.get_session() as session:
            logfile = session.query(LogFile).filter(LogFile.lid == lid).first()
            return [json.dumps(object_as_dict(dm)) for dm in logfile.danmakus]
    except sqlalchemy.exc.OperationalError:
        return
    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.exception(f'get_danmakus_by_file failed: {e}')
        return


def delete_danmaku_by_file(lid):
    try:
        with models.database.get_session() as session:
            logfile = session.query(LogFile).filter(LogFile.lid == lid).first()
            session.delete(logfile)
            session.commit()
        return True
    except sqlalchemy.exc.OperationalError:
        return False
    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.exception(f'delete_danmaku_by_file failed: {e}')
        return False


def get_log_file(room_id):
    global _room_log_mapper
    if _room_log_mapper.get(room_id):
        return _room_log_mapper[room_id]
    try:
        with models.database.get_session() as session:
            logfile = LogFile(filename=log_file_name(), room_id=room_id)
            session.add(logfile)
            session.commit()
            _room_log_mapper[room_id] = LogFile(lid=logfile.lid, filename=logfile.filename)
    except sqlalchemy.exc.OperationalError:
        return
    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.exception(f'get_log_file failed: {e}')
        return
    return _room_log_mapper[room_id]


def get_log_file_id(room_id):
    return get_log_file(room_id).lid


def get_log_file_by_lid(lid):
    if _room_log_mapper.get(lid):
        return _room_log_mapper[lid]
    try:
        with models.database.get_session() as session:
            logfile = session.query(LogFile.lid, LogFile.filename).filter(LogFile.lid == lid).first()
            return logfile
    except sqlalchemy.exc.OperationalError:
        return
    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.exception(f'get_log_file failed: {e}')
        return


def add_danmaku(room_id, body):
    lid = get_log_file_id(room_id)
    try:
        with models.database.get_session() as session:
            danmaku = LogItem(lid=lid, content=str(body))
            session.add(danmaku)
            session.commit()
    except sqlalchemy.exc.OperationalError:
        return False
    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.exception(f'add_danmaku failed: {e}')
        return False
    return True


def get_all_logs():
    try:
        with models.database.get_session() as session:
            logs = session.query(LogFile.lid, LogFile.filename, LogFile.room_id, LogFile.create_time).all()
    except sqlalchemy.exc.OperationalError:
        return
    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.exception(f'get_all_logs failed: {e}')
        return
    return [{
        'lid': i[0],
        'filename': i[1],
        'room_id': i[2],
        'create_time': i[3],
    } for i in logs]
