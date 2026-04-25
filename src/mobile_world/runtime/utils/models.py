# models.py
"""Pydantic models for FastAPI server requests and responses."""

from typing import Any, Literal

from pydantic import BaseModel, field_validator

# Action type constants
ANSWER = "answer"
CLICK = "click"
DOUBLE_TAP = "double_tap"
FINISHED = "finished"
INPUT_TEXT = "input_text"
KEYBOARD_ENTER = "keyboard_enter"
LONG_PRESS = "long_press"
NAVIGATE_BACK = "navigate_back"
NAVIGATE_HOME = "navigate_home"
OPEN_APP = "open_app"
SCROLL = "scroll"
STATUS = "status"
SWIPE = "swipe"
UNKNOWN = "unknown"
WAIT = "wait"
DRAG = "drag"
ASK_USER = "ask_user"
MCP = "mcp"
ENV_FAIL = "error_env"
DEFAULT_IMAGE = "ghcr.io/tongyi-mai/mobile_world:latest"
DEFAULT_NAME_PREFIX = "mobile_world_env"

# Coordinate scale factor — model emits pixel coords normalised to [0, 999].
SCALE_FACTOR = 999
_ACTION_TYPES = (
    CLICK,
    DOUBLE_TAP,
    SCROLL,
    SWIPE,
    INPUT_TEXT,
    NAVIGATE_HOME,
    NAVIGATE_BACK,
    KEYBOARD_ENTER,
    OPEN_APP,
    STATUS,
    WAIT,
    LONG_PRESS,
    ANSWER,
    FINISHED,
    UNKNOWN,
    DRAG,
    ASK_USER,
    MCP,
)

_SCROLL_DIRECTIONS = ("left", "right", "down", "up")

# Keys of JSON action
ACTION_TYPE = "action_type"
INDEX = "index"
X = "x"
Y = "y"
TEXT = "text"
DIRECTION = "direction"
APP_NAME = "app_name"
GOAL_STATUS = "goal_status"
START_X = "start_x"
START_Y = "start_y"
END_X = "end_x"
END_Y = "end_y"
ACTION_KEYS = [
    ACTION_TYPE,
    INDEX,
    X,
    Y,
    TEXT,
    DIRECTION,
    APP_NAME,
    GOAL_STATUS,
    START_X,
    START_Y,
    END_X,
    END_Y,
]


class JSONAction(BaseModel):
    """Represents a parsed JSON action.

    Example:
        result_json = {'action_type': 'click', 'x': 100, 'y': 200}
        action = JSONAction(**result_json)

    Attributes:
        action_type: The action type.
        index: The index to click, if action is a click. Either an index or a <x, y>
            should be provided. See x, y attributes below.
        x: The x position to click, if the action is a click.
        y: The y position to click, if the action is a click.
        text: The text to type, if action is type.
        direction: The direction to scroll, if action is scroll.
        goal_status: If the status is a 'status' type, indicates the status of the goal.
        app_name: The app name to launch, if the action type is 'open_app'.
        keycode: Keycode actions are necessary for an agent to interact with complex
            UI elements (like large textareas) that can't be accessed or controlled by
            simply taping, ensuring precise control over navigation and selection in
            the interface.
        clear_text: Whether to clear the text field before typing.
        start_x: The x position to start drag, if the action is a drag.
        start_y: The y position to start drag, if the action is a drag.
        end_x: The x position to end drag, if the action is a drag.
        end_y: The y position to end drag, if the action is a drag.
    """

    action_type: str | None = None
    index: str | int | None = None
    x: int | None = None
    y: int | None = None
    text: str | None = None
    direction: str | None = None
    goal_status: str | None = None
    app_name: str | None = None
    keycode: str | None = None
    clear_text: bool | None = None
    start_x: int | None = None
    start_y: int | None = None
    end_x: int | None = None
    end_y: int | None = None
    action_name: str | None = None
    action_json: dict | None = None

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, v: str | None) -> str | None:
        """Validate action type is valid."""
        if v is not None and v not in _ACTION_TYPES:
            raise ValueError(f"Invalid action type: {v}")
        return v

    @field_validator("index")
    @classmethod
    def validate_index(cls, v: str | int | None) -> int | None:
        """Convert index to int if needed."""
        if v is not None:
            return int(v)
        return v

    @field_validator("x", "y", mode="before")
    @classmethod
    def validate_coordinates(cls, v: int | float | None) -> int | None:
        """Convert float coordinates to int if needed."""
        if v is not None:
            return round(v)
        return v

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str | None) -> str | None:
        """Validate scroll direction is valid."""
        if v is not None and v not in _SCROLL_DIRECTIONS:
            raise ValueError(f"Invalid scroll direction: {v}")
        return v

    @field_validator("text", mode="before")
    @classmethod
    def validate_text(cls, v: Any) -> str | None:
        """Convert text to string if needed."""
        if v is not None and not isinstance(v, str):
            return str(v)
        return v

    @field_validator("keycode")
    @classmethod
    def validate_keycode(cls, v: str | None) -> str | None:
        """Validate keycode format."""
        if v is not None and not v.startswith("KEYCODE_"):
            raise ValueError(f"Invalid keycode: {v}")
        return v

    def model_post_init(self, __context: Any) -> None:
        """Additional validation after model initialization."""
        if self.index is not None:
            if self.x is not None or self.y is not None:
                raise ValueError("Either an index or a <x, y> should be provided.")

    def __eq__(self, other: object) -> bool:
        """Compare two JSONActions."""
        if not isinstance(other, JSONAction):
            return False
        return _compare_actions(self, other)

    def __ne__(self, other: object) -> bool:
        """Check if two JSONActions are not equal."""
        return not self.__eq__(other)


def _compare_actions(a: JSONAction, b: JSONAction) -> bool:
    """Compares two JSONActions.

    Args:
        a: The first action.
        b: The second action.

    Returns:
        If the actions are equal.
    """
    # Ignore cases for app_name and text.
    if a.app_name is not None and b.app_name is not None:
        app_name_match = a.app_name.lower() == b.app_name.lower()
    else:
        app_name_match = a.app_name == b.app_name

    if a.text is not None and b.text is not None:
        text_match = a.text.lower() == b.text.lower()
    else:
        text_match = a.text == b.text

    # Compare the non-metadata fields.
    return (
        app_name_match
        and text_match
        and a.action_type == b.action_type
        and a.index == b.index
        and a.x == b.x
        and a.y == b.y
        and a.keycode == b.keycode
        and a.direction == b.direction
        and a.goal_status == b.goal_status
        and a.start_x == b.start_x
        and a.start_y == b.start_y
        and a.end_x == b.end_x
        and a.end_y == b.end_y
    )


APP_DICT = {
    "桌面": "com.google.android.apps.nexuslauncher",
    "Contacts": "com.google.android.contacts",
    "Settings": "com.android.settings",
    "设置": "com.android.settings",
    "Clock": "com.google.android.deskclock",
    "Maps": "com.google.android.apps.maps",
    "Chrome": "com.android.chrome",
    "Calendar": "org.fossify.calendar",
    "files": "com.google.android.documentsui",
    "Gallery": "gallery.photomanager.picturegalleryapp.imagegallery",
    "淘店": "com.testmall.app",
    "Taodian": "com.testmall.app",
    "Mattermost": "com.mattermost.rnbeta",
    "Mastodon": "org.joinmastodon.android.mastodon",
    "Mail": "com.gmailclone",
    "SMS": "com.google.android.apps.messaging",
    "Camera": "com.android.camera2",
}

COMMON_APP_MAPPER = {
    "com.quark.browser": "夸克",
    "com.mattermost.rn": "Mattermost",
    "com.google.android.apps.labs.language.tailwind": "NotebookLM",
    "com.tailscale.ipn": "Tailscale",
    "com.webank.wemoney": "微众银行",
    "com.unionpay.tsmservice": "银联可信服务安全组件",
    "com.google.android.googlequicksearchbox": "Google",
    "org.telegram.messenger": "Telegram",
    "com.sgcc.evs.echarge": "e充电",
    "com.finshell.wallet": "钱包",
    "com.tmri.app.main": "交管12123",
    "com.sankuai.meituan": "美团",
    "com.youku.phone": "优酷视频",
    "com.douban.frodo": "豆瓣",
    "com.tencent.qqmusic": "QQ音乐",
    "com.ncarzone.tmyc": "天猫养车",
    "au.com.commsec.android.CommSecPocket": "Pocket",
    "com.sohu.inputmethod.sogouoem": "搜狗输入法定制版",
    "com.hexin.plat.android": "同花顺",
    "com.whatsapp": "WhatsApp",
    "com.substack.app": "Substack",
    "com.tencent.androidqqmail": "QQ邮箱",
    "com.smzdm.client.android": "什么值得买",
    "com.jingyao.easybike": "哈啰",
    "com.transferwise.android": "Wise",
    "com.dianping.v1": "大众点评",
    "com.google.android.apps.authenticator2": "Authenticator",
    "com.petkit.android": "小佩宠物",
    "com.taou.maimai": "脉脉",
    "cmb.pb": "招商银行",
    "com.openai.chatgpt": "ChatGPT",
    "com.aliyun.tongyi": "千问",
    "com.MobileTicket": "铁路12306",
    "com.github.android": "GitHub",
    "com.molink.john.hummingbird": "bebird",
    "me.ele": "淘宝闪购",
    "com.bochk.app.aos": "BOCHK 中银香港",
    "com.xingin.xhs": "小红书",
    "com.tencent.mm": "微信",
    "com.sdu.didi.psnger": "滴滴出行",
    "com.chinamworld.bocmbci": "中国银行",
    "com.umetrip.android.msky.app": "航旅纵横",
    "com.brave.browser": "Brave",
    "com.oray.sunlogin": "向日葵远程控制",
    "com.mi.health": "小米运动健康",
    "com.android.mms": "信息",
    "com.icbc": "中国工商银行",
    "com.deepseek.chat": "DeepSeek",
    "app.podcast.cosmos": "小宇宙",
    "com.google.android.gm": "Gmail",
    "org.zotero.android": "Zotero",
    "au.com.amaysim.android": "amaysim",
    "com.hanweb.android.zhejiang.activity": "浙里办",
    "com.eastmoney.android.berlin": "东方财富",
    "com.teslamotors.tesla": "Tesla",
    "dji.go.v5": "DJI Fly",
    "com.mcdonalds.gma.cn": "麦当劳",
    "com.redteamobile.roaming": "逍遥游",
    "com.reqable.android": "Reqable",
    "com.xunmeng.pinduoduo": "拼多多",
    "com.tencent.wetype": "微信输入法",
    "com.twitter.android": "X",
    "com.haier.uhome.uplus": "海尔智家",
    "com.google.android.apps.bard": "Gemini",
    "com.google.android.apps.maps": "地图",
    "com.meituan.retail.v.android": "小象超市",
    "com.eusoft.eudic": "欧路词典",
    "com.cmi.jegotrip": "无忧行",
    "com.google.android.webview": "Android System WebView",
    "com.wudaokou.hippo": "盒马",
    "com.server.auditor.ssh.client": "Termius",
    "com.ft07.serverchan.app3.server_app3": "Server酱",
    "com.android.chrome": "Chrome",
    "cn.com.cmbc.newmbank": "民生银行",
    "com.xiaomi.mico": "小米音箱",
    "com.xiaomi.shop": "小米商城",
    "com.ss.android.ugc.aweme": "抖音",
    "com.tencent.mobileqq": "QQ",
    "com.ss.android.lark": "飞书",
    "com.getsurfboard": "Surfboard",
    "ai.x.grok": "Grok",
    "com.unionpay": "云闪付",
    "com.opos.ads": "智能推荐服务",
    "com.spotify.music": "Spotify",
    "com.x8bit.bitwarden": "Bitwarden",
    "com.ubercab": "Uber",
    "com.alibaba.wireless": "阿里巴巴",
    "ai.perplexity.app.android": "Perplexity",
    "com.zerotier.one": "ZeroTier One",
    "com.zhihu.android": "知乎",
    "com.coolapk.market": "酷安",
    "com.airbnb.android": "爱彼迎",
    "com.sinyee.babybus.story": "小布咕",
    "com.chinamworld.main": "中国建设银行",
    "com.smk": "杭州市民卡",
    "com.Slack": "Slack",
    "cn.damai": "大麦",
    "com.zhongan.ibank": "ZA Bank",
    "com.larus.nova": "豆包",
    "com.cainiao.wireless": "菜鸟",
    "com.rytong.ceair": "东方航空",
    "com.linkedin.android": "LinkedIn",
    "com.jingdong.app.mall": "京东",
    "com.autonavi.minimap": "高德地图",
    "com.citiccard.mobilebank": "动卡空间",
    "com.taobao.idlefish": "闲鱼",
    "ctrip.android.view": "携程旅行",
    "com.alibaba.android.rimet": "钉钉",
    "com.booking": "Booking.com缤客",
    "com.zuzuChe": "租租车",
    "com.tencent.wemeet.app": "腾讯会议",
    "com.nearme.instant.platform": "快应用服务框架",
    "com.android.email": "邮件",
    "ctrip.english": "Trip.com",
    "com.absinthe.libchecker": "LibChecker",
    "com.mybank.android.phone": "网商银行",
    "com.alibaba.aliyun": "阿里云",
    "com.videogo": "萤石云视频",
    "de.danoeh.antennapod": "AntennaPod",
    "com.baidu.netdisk": "百度网盘",
    "com.baidu.BaiduMap": "百度地图",
    "com.taobao.taobao": "淘宝",
    "com.sgcc.wsgw.cn": "网上国网",
    "com.xiaomi.smarthome": "米家",
    "cn.samsclub.app": "山姆会员商店",
    "com.lego.legobuildinginstructions": "LEGO® Builder",
    "com.google.android.apps.adm": "查找中心",
    "com.netease.cloudmusic": "网易云音乐",
    "com.ct.client": "中国电信",
    "tv.danmaku.bili": "哔哩哔哩",
    "com.eg.android.AlipayGphone": "支付宝",
    "cn.wps.moffice_eng": "WPS Office",
    "com.greenpoint.android.mc10086.activity": "中国移动",
    "com.google.android.inputmethod.latin": "Gboard",
    "com.thfund.client": "天弘基金",
    "com.taobao.trip": "飞猪旅行",
    "com.miHoYo.hkrpg": "崩坏：星穹铁道",
    "com.papegames.lysk.cn": "恋与深空",
    "com.android.settings": "Settings",
    "com.android.soundrecorder": "AudioRecorder",
    "com.android.deskclock": "Clock",
    "com.android.contacts": "Contacts",
    "com.android.fileexplorer": "Files",
    "com.google.android.apps.nbu.files": "Google Files",
    "com.google.android.calendar": "Google Calendar",
    "com.google.android.apps.dynamite": "Google Chat",
    "com.google.android.deskclock": "Google Clock",
    "com.google.android.contacts": "Google Contacts",
    "com.google.android.apps.docs.editors.docs": "Google Docs",
    "com.google.android.apps.docs": "Google Drive",
    "com.google.android.apps.fitness": "Google Fit",
    "com.google.android.keep": "Google Keep",
    "com.google.android.apps.books": "Google Play Books",
    "com.google.android.apps.docs.editors.slides": "Google Slides",
    "com.google.android.apps.tasks": "Google Tasks",
    "com.rammigsoftware.bluecoins": "Bluecoins",
    "com.flauschcode.broccoli": "Broccoli",
    "com.duolingo": "Duolingo",
    "com.expedia.bookings": "Expedia",
    "net.cozic.joplin": "Joplin",
    "com.mcdonalds.app": "McDonald's",
    "net.osmand": "OsmAnd",
    "com.Project100Pi.themusicplayer": "Pi Music Player",
    "com.quora.android": "Quora",
    "com.reddit.frontpage": "Reddit",
    "code.name.monkey.retromusic": "Retro Music",
    "com.einnovation.temu": "Temu",
    "com.zhiliaoapp.musically": "TikTok",
    "org.videolan.vlc": "VLC",
    "com.tencent.qqlive": "腾讯视频",
}


# FastAPI Server Models
class InstanceInfo(BaseModel):
    docker_port_local: int | None = None
    container_id: str | None = None


class InitRequest(BaseModel):
    device: str = "emulator-5554"
    type: Literal["cmd", "docker"] = "cmd"
    instance: InstanceInfo | None = None


class ScreenshotQuery(BaseModel):
    device: str
    prefix: str | None = None
    return_b64: bool = False


class XMLQuery(BaseModel):
    device: str
    prefix: str | None = None
    mode: Literal["uia", "ac"] = "uia"  # uia: get_xml; ac: get_ac_xml
    return_content: bool = False


class StepRequest(BaseModel):
    """Request for executing a step action."""

    device: str
    action: JSONAction


class TaskOperationRequest(BaseModel):
    task_name: str
    req_device: str


# Client Response Models
class Response(BaseModel):
    """Response model for client operations."""

    status: str
    message: str


class SmsRequest(BaseModel):
    device: str
    sender: str
    message: str


class TaskCallbackRequest(BaseModel):
    """Request for saving task callback data."""

    device: str
    callback_data: dict[str, Any]


class Observation(BaseModel):
    screenshot: Any
    accessibility_tree: Any = None
    ask_user_response: str | None = None
    tool_call: Any | None = None


# Environment/Docker Models
class ContainerInfo(BaseModel):
    """Information about a Docker container."""

    name: str
    status: str | None = None
    running: bool = False
    started_at: str | None = None
    image: str | None = None
    backend_port: int | None = None
    viewer_port: int | None = None
    vnc_port: int | None = None
    adb_port: int | None = None


class ContainerConfig(BaseModel):
    """Configuration for launching a container."""

    name: str
    backend_port: int
    viewer_port: int
    vnc_port: int
    adb_port: int = 5556
    image: str = DEFAULT_IMAGE
    dev_mode: bool = False
    enable_vnc: bool = False
    env_file_path: Any | None = None  # Path
    dev_src_path: Any | None = None  # Path


class LaunchResult(BaseModel):
    """Result of launching a container."""

    name: str
    backend_port: int
    viewer_port: int
    adb_port: int
    vnc_port: int
    success: bool = False
    ready: bool = False
    error_message: str | None = None


class PrerequisiteCheckResult(BaseModel):
    """Result of a single prerequisite check."""

    name: str
    passed: bool
    message: str
    details: str | None = None


class PrerequisiteCheckResults(BaseModel):
    """Results of all prerequisite checks."""

    checks: list[PrerequisiteCheckResult]

    @property
    def all_passed(self) -> bool:
        """Return True if all checks passed."""
        return all(c.passed for c in self.checks)

    @property
    def passed_count(self) -> int:
        """Return count of passed checks."""
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_count(self) -> int:
        """Return count of failed checks."""
        return sum(1 for c in self.checks if not c.passed)


class ImageStatus(BaseModel):
    """Status of a Docker image."""

    image: str
    exists_locally: bool
    local_digest: str | None = None
    remote_digest: str | None = None
    needs_update: bool = False
    error: str | None = None
