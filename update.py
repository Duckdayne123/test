import json
import os
import re
import threading
import time
import requests
import openai
from zlapi import ZaloAPI
from zlapi.models import Message, ThreadType

# Hằng số
SETTINGS_FILE = 'settings.json'
openai.api_key = "haha"  # Thay bằng khóa API OpenAI thực tế
THONG_TIN_TAC_GIA = (
    "👨‍💻 Tác giả: A Sìn\n"
    "🔄 Cập nhật: 09-10-24 v2\n"
    "🚀 Tính năng: Chào đón/tạm biệt thành viên nhóm, phát hiện và xóa tin nhắn buôn bán\n"
    "📌 Lưu ý:\n"
    "   1️⃣ [Bước 1] Thay imei và cookies\n"
    "   2️⃣ [Bước 2] Chọn nhóm để bật chào đón. Dùng '!wl on' để bật, '!wl off' để tắt"
)

# Hàm xử lý file
def read_settings():
    """Đọc cấu hình từ file JSON, tạo file mới nếu chưa tồn tại."""
    if not os.path.exists(SETTINGS_FILE):
        write_settings({})
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def write_settings(settings):
    """Ghi cấu hình vào file JSON với định dạng UTF-8."""
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as file:
        json.dump(settings, file, ensure_ascii=False, indent=4)

# Quản lý chế độ chào đón
def get_allowed_thread_ids():
    """Lấy danh sách ID nhóm có chế độ chào đón được bật."""
    settings = read_settings()
    welcome_settings = settings.get('welcome', {})
    return [thread_id for thread_id, is_enabled in welcome_settings.items() if is_enabled]

def enable_welcome(thread_id):
    """Bật chế độ chào đón cho nhóm."""
    settings = read_settings()
    settings.setdefault('welcome', {})
    settings['welcome'][thread_id] = True
    write_settings(settings)
    return "🚦 Chế độ chào đón 🟢 Đã bật 🎉"

def disable_welcome(thread_id):
    """Tắt chế độ chào đón cho nhóm."""
    settings = read_settings()
    if 'welcome' in settings and thread_id in settings['welcome']:
        settings['welcome'][thread_id] = False
        write_settings(settings)
        return "🚦 Chế độ chào đón 🔴 Đã tắt 🎉"
    return "🚦 Nhóm chưa có cấu hình chào đón để 🔴 Tắt 🤗"

def is_welcome_enabled(thread_id):
    """Kiểm tra xem nhóm có bật chế độ chào đón không."""
    settings = read_settings()
    return settings.get('welcome', {}).get(thread_id, False)

# Quản lý thông tin nhóm
def initialize_group_info(bot, allowed_thread_ids):
    """Khởi tạo thông tin nhóm từ danh sách ID nhóm."""
    for thread_id in allowed_thread_ids:
        group_info = bot.fetchGroupInfo(thread_id).gridInfoMap.get(thread_id)
        if group_info:
            bot.group_info_cache[thread_id] = {
                'name': group_info['name'],
                'member_list': group_info['memVerList'],
                'total_member': group_info['totalMember']
            }
        else:
            print(f"Bỏ qua nhóm {thread_id}")

def check_member_changes(bot, thread_id):
    """Kiểm tra sự thay đổi thành viên trong nhóm."""
    current_group_info = bot.fetchGroupInfo(thread_id).gridInfoMap.get(thread_id)
    cached_group_info = bot.group_info_cache.get(thread_id)

    if not cached_group_info or not current_group_info:
        return [], []

    old_members = {member.split('_')[0] for member in cached_group_info['member_list']}
    new_members = {member.split('_')[0] for member in current_group_info['memVerList']}

    joined_members = new_members - old_members
    left_members = old_members - new_members

    # Cập nhật cache
    bot.group_info_cache[thread_id] = {
        'name': current_group_info['name'],
        'member_list': current_group_info['memVerList'],
        'total_member': current_group_info['totalMember']
    }

    return joined_members, left_members

# Hàm tiện ích
def delete_file(file_path):
    """Xóa tệp tạm sau khi sử dụng."""
    try:
        os.remove(file_path)
        print(f"Đã xóa tệp: {file_path}")
    except Exception as e:
        print(f"Lỗi khi xóa tệp: {e}")

def is_selling_context(message: str) -> bool:
    """Dùng GPT để kiểm tra xem tin nhắn có nội dung buôn bán không."""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Bạn là AI kiểm duyệt. Trả lời 'yes' nếu nội dung liên quan đến buôn bán, còn lại trả lời 'no'."},
                {"role": "user", "content": f"Tin nhắn: \"{message}\""}
            ],
            temperature=0,
            max_tokens=5,
        )
        result = response.choices[0].message['content'].strip().lower()
        return 'yes' in result
    except Exception as e:
        print(f"❌ Lỗi khi gọi GPT: {e}")
        return False

def handle_group_member(bot, message_object, author_id, thread_id, thread_type):
    """Xử lý sự kiện thành viên vào/ra nhóm."""
    joined_members, left_members = check_member_changes(bot, thread_id)

    # Chào đón thành viên mới
    for member_id in joined_members:
        member_info = bot.fetchUserInfo(member_id).changed_profiles[member_id]
        total_member = bot.group_info_cache[thread_id]['total_member']
        cover = member_info.avatar

        try:
            cover_response = requests.get(cover)
            cover_filename = cover.rsplit('/', 1)[-1]
            with open(cover_filename, 'wb') as f:
                f.write(cover_response.content)
        except Exception:
            cover_filename = None

        messagesend = Message(text=f"🥳 Chào mừng {member_info.displayName} 🎉 đến với {bot.group_info_cache[thread_id]['name']}")
        if cover_filename and cover_response.status_code == 200:
            bot.sendLocalImage(cover_filename, thread_id, thread_type, message=messagesend, width=240, height=240)
            delete_file(cover_filename)
        else:
            bot.replyMessage(messagesend, message_object, thread_id, thread_type)

        response = f"Chào mừng {member_info.displayName} đến với {bot.group_info_cache[thread_id]['name']}! Bạn là thành viên thứ {total_member}."
        bot.send(Message(text=response), thread_id, thread_type)

    # Tạm biệt thành viên rời nhóm
    for member_id in left_members:
        member_info = bot.fetchUserInfo(member_id).changed_profiles[member_id]
        cover = member_info.avatar

        try:
            cover_response = requests.get(cover)
            cover_filename = cover.rsplit('/', 1)[-1]
            with open(cover_filename, 'wb') as f:
                f.write(cover_response.content)
        except Exception:
            cover_filename = None

        messagesend = Message(text=f"💔 Tạm biệt {member_info.displayName} 🤧")
        if cover_filename and cover_response.status_code == 200:
            bot.sendLocalImage(cover_filename, thread_id, thread_type, message=messagesend, width=240, height=240)
            delete_file(cover_filename)
        else:
            bot.replyMessage(messagesend, message_object, thread_id, thread_type)

        response = f"Tạm biệt {member_info.displayName}. Chúc bạn may mắn 🤑!"
        bot.send(Message(text=response), thread_id, thread_type)

# Lớp Bot
class Bot(ZaloAPI):
    def __init__(self, api_key, secret_key, imei=None, session_cookies=None):
        super().__init__(api_key, secret_key, imei, session_cookies)
        self.group_info_cache = {}
        all_group = self.fetchAllGroups()
        allowed_thread_ids = list(all_group.gridVerMap.keys())
        initialize_group_info(self, allowed_thread_ids)
        self.start_member_check_thread(allowed_thread_ids)

    def start_member_check_thread(self, allowed_thread_ids):
        """Bắt đầu luồng kiểm tra thay đổi thành viên."""
        def check_members_loop():
            while True:
                for thread_id in allowed_thread_ids:
                    if is_welcome_enabled(thread_id):
                        handle_group_member(self, None, None, thread_id, ThreadType.GROUP)
                time.sleep(2)

        thread = threading.Thread(target=check_members_loop, daemon=True)
        thread.start()

    def onMessage(self, mid, author_id, message, message_object, thread_id, thread_type):
        """Xử lý tin nhắn đến, phát hiện liên kết và lệnh."""
        print(f"🎏 {thread_type.name} {'🙂' if thread_type.name == 'USER' else '🐞'} {author_id} {thread_id}")
        print(f"Nội dung tin nhắn: {message}")
        print(f"Đối tượng tin nhắn: {message_object}")
        print(f"cliMsgId: {getattr(message_object, 'cliMsgId', 'Không tìm thấy')}")

        link_pattern = r'(https?:\/\/[^\s]+|www\.[^\s]+|(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})'

        # Xóa nếu content['title'] chứa liên kết
        if hasattr(message_object, 'content') and isinstance(message_object.content, dict):
            title = message_object.content.get('title', '')
            if isinstance(title, str) and re.search(link_pattern, title.strip().lower()):
                try:
                    self.deleteGroupMsg(mid, author_id, message_object.cliMsgId, thread_id)
                    print(f"🚫 Đã xóa tin nhắn chứa liên kết trong content['title']: {title}")
                    return
                except Exception as e:
                    print(f"❌ Lỗi khi xóa tin nhắn đối tượng: {e}")
                    return

        # Xóa nếu tin nhắn văn bản chứa liên kết
        if isinstance(message, str) and re.search(link_pattern, message.strip().lower()):
            try:
                self.deleteGroupMsg(mid, author_id, message_object.cliMsgId, thread_id)
                print(f"🚫 Đã xóa tin nhắn chứa liên kết từ {author_id}: {message}")
                return
            except Exception as e:
                print(f"❌ Lỗi khi xóa liên kết: {e}")
                return

        # Phân tích AI: Xóa nếu tin nhắn liên quan đến buôn bán
        if isinstance(message, str):
            ban_keywords = [
                "bán", "shop", "giá", "đặt hàng", "giao hàng", "order", "sale", "ship",
                "khuyến mãi", "mua", "sỉ lẻ", "bao giá", "chốt đơn", "thanh toán",
                "săn sale", "combo", "freeship", "deal", "đơn hàng", "tuyển sỉ", "tuyển ctv"
            ]
            lowered = message.lower()
            if any(kw in lowered for kw in ban_keywords):
                print("🤖 Phát hiện từ khóa nghi ngờ buôn bán, gọi GPT để kiểm tra...")
                if is_selling_context(message):
                    try:
                        self.deleteGroupMsg(mid, author_id, message_object.cliMsgId, thread_id)
                        print(f"🛒 Đã xóa tin nhắn buôn bán: {message}")
                        return
                    except Exception as e:
                        print(f"❌ Lỗi khi xóa tin nhắn buôn bán: {e}")
                        return
                else:
                    print("✅ GPT xác nhận không phải tin nhắn buôn bán, giữ lại.")

        # Xử lý lệnh !wl
        if isinstance(message, str) and message.startswith('!wl'):
            parts = message.split()
            if len(parts) < 2:
                response = "➜ Vui lòng chỉ định [on/off] sau !wl 🤗\n➜ Ví dụ: !wl on hoặc !wl off ✅"
            else:
                sub_action = parts[1].lower()
                if author_id not in [self.uid, '2049100404891878006']:
                    response = "➜ Lệnh này chỉ dành cho chủ sở hữu 🤗"
                elif thread_type != ThreadType.GROUP:
                    response = "➜ Lệnh này chỉ hoạt động trong nhóm 🤗"
                else:
                    response = (
                        enable_welcome(thread_id) if sub_action == 'on' else
                        disable_welcome(thread_id) if sub_action == 'off' else
                        f"➜ Lệnh !wl {sub_action} không được hỗ trợ 🤗"
                    )
            if response:
                self.send(Message(text=response), thread_id, thread_type)

# Cấu hình
imei = 'df654c2f-a935-410b-b9b4-c111cf98cbce-7ddeda88d0c599cc494da0dece6554d5'
session_cookies = {
    '_ga': 'GA1.2.1522948663.1727945417',
    '_ga_RYD7END4JE': 'GS1.2.1727945417.1.1.1727945418.59.0.0',
    '__zi': '3000.SSZzejyD3yaynFwzpKGIpZ37_hRBJXo4FCRqkeG30SeothVcbWbFXZRUyg-M04U1C9lpgfPBGuyodlAYD3Os.1',
    '__zi-legacy': '3000.SSZzejyD3yaynFwzpKGIpZ37_hRBJXo4FCRqkeG30SeothVcbWbFXZRUyg-M04U1C9lpgfPBGuyodlAYD3Os.1',
    '_zlang': 'vn',
    '_gid': 'GA1.2.540760167.1752876683',
    'zpsid': '1sSR.408549022.4.XPG3LhB7xuqiCRQLliVlZSUqdRc2_zgvY_VTlxnvg2_qrclHipaTyDh7xuq',
    'zpw_sek': '_xYX.408549022.a0.qyiFJoALVyEyOoRR0vL_mrct6gW0hrsrSS4DgaUcBf5JqIUIUl89ingW5ejZg4BXNvl1X83JRaT-b80nN_r_mm',
    'app.event.zalo.me': '2451148194835893133'
}

# Chạy bot
client = Bot('api_key', 'secret_key', imei=imei, session_cookies=session_cookies)
client.listen(run_forever=True, delay=0, thread=True, type='requests')
