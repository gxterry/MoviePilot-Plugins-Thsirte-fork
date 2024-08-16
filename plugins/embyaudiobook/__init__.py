import json
import threading
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.modules.emby import Emby
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.types import EventType
from app.utils.http import RequestUtils

lock = threading.Lock()


class EmbyAudioBook(_PluginBase):
    # 插件名称
    plugin_name = "Emby有声书整理"
    # 插件描述
    plugin_desc = "还在为Emby有声书整理烦恼吗？入库存在很多单集？"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/thsrite/MoviePilot-Plugins/main/icons/audiobook.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    plugin_config_prefix = "embyaudiobook_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _notify = False
    _rename = False
    _library_id = None
    _extend = None
    _msgtype = None

    _EMBY_HOST = settings.EMBY_HOST
    _EMBY_USER = Emby().get_user()
    _EMBY_APIKEY = settings.EMBY_API_KEY

    def init_plugin(self, config: dict = None):
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._library_id = config.get("library_id")
            self._notify = config.get("notify")
            self._rename = config.get("rename")
            self._msgtype = config.get("msgtype")

            if self._EMBY_HOST:
                if not self._EMBY_HOST.endswith("/"):
                    self._EMBY_HOST += "/"
                if not self._EMBY_HOST.startswith("http"):
                    self._EMBY_HOST = "http://" + self._EMBY_HOST

    @eventmanager.register(EventType.PluginAction)
    def audiobook(self, event: Event = None):
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "audiobook":
                return

            if not self._library_id:
                logger.error("请设置有声书文件夹ID！")
                self.post_message(channel=event.event_data.get("channel"),
                                  title="请设置有声书文件夹ID！",
                                  userid=event.event_data.get("user"))
                return

            args = event_data.get("args")
            if not args:
                logger.error(f"缺少参数：{event_data}")
                return

            args_list = args.split(" ")
            if len(args_list) != 2:
                logger.error(f"参数错误：{args_list}")
                self.post_message(channel=event.event_data.get("channel"),
                                  title=f"参数错误！ /ab 书名 正确信息集数",
                                  userid=event.event_data.get("user"))
                return

            book_name = args_list[0]
            book_idx = args_list[1]
            logger.info(f"有声书整理：{book_name} - 正确信息从集数 {book_idx} 获取")

            # 获取所有有声书
            items = self.__get_items(self._library_id)
            if not items:
                logger.error(f"获取 {self._library_id} 有声书失败！")
                self.post_message(channel=event.event_data.get("channel"),
                                  title=f"获取 {self._library_id} 有声书失败！",
                                  userid=event.event_data.get("user"))
                return

            # 获取指定有声书
            book_id = None
            for item in items:
                if book_name in item.get("Name"):
                    book_id = item.get("Id")
                    break

            if not book_id:
                logger.error(f"未找到 {book_name} 有声书！")
                self.post_message(channel=event.event_data.get("channel"),
                                  title=f"未找到 {book_name} 有声书！",
                                  userid=event.event_data.get("user"))
                return

            items = self.__get_items(book_id)
            if not items:
                logger.error(f"获取 {book_name} {book_id} 有声书失败！")
                self.post_message(channel=event.event_data.get("channel"),
                                  title=f"获取 {book_name} {book_id} 有声书失败！",
                                  userid=event.event_data.get("user"))
                return

            Album = items[book_idx - 1].get("Album")
            AlbumId = items[book_idx - 1].get("AlbumId")
            AlbumPrimaryImageTag = items[book_idx - 1].get("AlbumPrimaryImageTag")
            Artists = items[book_idx - 1].get("Artists")
            ArtistItems = items[book_idx - 1].get("ArtistItems")
            Composers = items[book_idx - 1].get("Composers")
            AlbumArtist = items[book_idx - 1].get("AlbumArtist")
            AlbumArtists = items[book_idx - 1].get("AlbumArtists")
            ParentIndexNumber = items[book_idx - 1].get("ParentIndexNumber")
            logger.info(
                f"从集数 {book_idx} 获取到有声书信息：{Album} - {Artists} - {Composers} - {AlbumArtist} - {AlbumArtists} - {ParentIndexNumber}")

            # 更新有声书信息
            for i, item in enumerate(items):
                # if len(items[0]) != len(item):
                if Album == item.get("Album") and \
                        AlbumId == item.get("AlbumId") and \
                        AlbumPrimaryImageTag == item.get("AlbumPrimaryImageTag") and \
                        Artists == item.get("Artists") and \
                        ArtistItems == item.get("ArtistItems") and \
                        Composers == item.get("Composers") and \
                        AlbumArtist == item.get("AlbumArtist") and \
                        AlbumArtists == item.get("AlbumArtists") and not self._rename:
                    logger.info(f"有声书 第{i + 1}集  {item.get('Name')} 信息完整，跳过！")
                    continue

                # 获取有声书信息
                item_info = self.__get_audiobook_item_info(item.get("Id"))

                # 重命名前判断名称是否一致
                if self._rename and item.get("Name") == Path(Path(item_info.get("Path")).name).stem:
                    logger.info(f"有声书 第{i + 1}集  {item.get('Name')} 名称相同，跳过！")
                    continue

                try:
                    item_info.update({
                        "Album": Album,
                        "AlbumId": AlbumId,
                        "AlbumPrimaryImageTag": AlbumPrimaryImageTag,
                        "Artists": Artists,
                        "ArtistItems": ArtistItems,
                        "Composers": Composers,
                        "AlbumArtist": AlbumArtist,
                        "AlbumArtists": AlbumArtists,
                        "ParentIndexNumber": ParentIndexNumber,
                        "IndexNumber": i + 1
                    })
                except Exception as e:
                    logger.error(f"更新有声书信息出错：{e} {item_info}")
                    continue

                if item_info.get("Name") == "filename" or self._rename:
                    item_info.update({
                        "Name": Path(Path(item_info.get("Path")).name).stem
                    })
                flag = self.__update_item_info(item.get("Id"), item_info)
                logger.info(f"{Album} 第{i + 1}集 {item_info.get('Name')} 更新{'成功' if flag else '失败'}")
                time.sleep(0.5)

    def get_state(self) -> bool:
        return self._enabled

    def __get_items(self, parent_id) -> list:
        """
        获取有声书剧集
        """
        if not self._EMBY_HOST or not self._EMBY_APIKEY:
            return []
        req_url = f"%semby/Users/%s/Items?ParentId=%s&api_key=%s" % (
            self._EMBY_HOST, self._EMBY_USER, parent_id, self._EMBY_APIKEY)
        try:
            with RequestUtils().get_res(req_url) as res:
                if res:
                    return res.json().get("Items")
                else:
                    logger.info(f"获取有声书剧集失败，无法连接Emby！")
                    return []
        except Exception as e:
            logger.error(f"连接有声书Items出错：" + str(e))
            return []

    def __get_audiobook_item_info(self, item_id) -> dict:
        """
        获取有声书剧集详情
        """
        if not self._EMBY_HOST or not self._EMBY_APIKEY:
            return {}
        req_url = f"%semby/Users/%s/Items/%s?fields=ShareLevel&ExcludeFields=Chapters,Overview,People,MediaStreams,Subviews&api_key=%s" % (
            self._EMBY_HOST, self._EMBY_USER, item_id, self._EMBY_APIKEY)
        try:
            with RequestUtils().get_res(req_url) as res:
                if res:
                    return res.json()
                else:
                    logger.info(f"获取有声书剧集详情失败，无法连接Emby！")
                    return {}
        except Exception as e:
            logger.error(f"连接有声书详情Items出错：" + str(e))
            return {}

    def __update_item_info(self, item_id, data):
        headers = {
            'accept': '*/*',
            'Content-Type': 'application/json'
        }
        res = RequestUtils(headers=headers).post(
            f"{self._EMBY_HOST}/emby/Items/{item_id}?api_key={self._EMBY_APIKEY}",
            data=json.dumps(data))
        if res and res.status_code == 204:
            return True
        return False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/ab",
                "event": EventType.PluginAction,
                "desc": "emby有声书整理",
                "category": "",
                "data": {
                    "action": "audiobook"
                }
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        MsgTypeOptions = []
        for item in NotificationType:
            MsgTypeOptions.append({
                "title": item.value,
                "value": item.name
            })
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '开启通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'rename',
                                            'label': '重命名有声书',
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': False,
                                            'chips': True,
                                            'model': 'msgtype',
                                            'label': '消息类型',
                                            'items': MsgTypeOptions
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'library_id',
                                            'label': '有声书文件夹ID',
                                            'placeholder': '媒体库有声书-->文件夹-->看URL里的ParentId'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '仅支持交互命令运行: /ab 书名 正确信息集数。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": False,
            "rename": False,
            "extend": "",
            "library_id": "",
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        pass