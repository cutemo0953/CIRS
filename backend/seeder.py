"""
CIRS Demo Data Seeder
植入展示用假資料
"""
from datetime import datetime, timedelta
import random
import hashlib

# 台灣常見姓氏和名字
SURNAMES = ["陳", "林", "黃", "張", "李", "王", "吳", "劉", "蔡", "楊",
            "許", "鄭", "謝", "郭", "洪", "邱", "曾", "廖", "賴", "周"]
NAMES_MALE = ["志明", "俊傑", "建宏", "宗翰", "家豪", "冠宇", "承恩", "柏翰", "宇軒", "彥廷"]
NAMES_FEMALE = ["淑芬", "美玲", "雅婷", "怡君", "佳穎", "雅雯", "詩涵", "欣怡", "宜蓁", "筱婷"]


def generate_taiwan_id(gender: str = None) -> str:
    """產生假身分證字號 (僅供 Demo 用)"""
    letters = "ABCDEFGHJKLMNPQRSTUVXYWZIO"
    first = random.choice(letters)
    if gender is None:
        gender_code = random.choice(["1", "2"])
    else:
        gender_code = "1" if gender == "M" else "2"
    numbers = "".join([str(random.randint(0, 9)) for _ in range(7)])
    return f"{first}{gender_code}{numbers}"


def hash_id(id_number: str) -> str:
    """Hash ID number for privacy"""
    return hashlib.sha256(id_number.encode()).hexdigest()[:16]


def seed_cirs_demo(conn):
    """
    植入 CIRS 展示資料

    Args:
        conn: SQLite connection object
    """
    cursor = conn.cursor()

    # Check if already seeded
    cursor.execute("SELECT COUNT(*) FROM person")
    if cursor.fetchone()[0] > 0:
        print("[CIRS Seeder] Data already exists, skipping...")
        return

    print("[CIRS Seeder] Seeding demo data...")
    now = datetime.now()

    # =========================================
    # 1. 站點設定
    # =========================================
    config_data = [
        ('site_name', '[DEMO] 台北市信義區防災收容所'),
        ('site_address', '台北市信義區信義路五段 150 號'),
        ('demo_mode', 'true'),
        ('capacity', '200'),
        ('water_per_person_per_day', '3'),
        ('food_per_person_per_day', '2100'),
        ('admin_password_hash', hashlib.sha256('demo1234'.encode()).hexdigest()),
    ]
    cursor.executemany(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        config_data
    )

    # =========================================
    # 2. 人員資料 (50人)
    # =========================================
    triage_weights = {
        'GREEN': 60,    # 輕傷/無傷
        'YELLOW': 25,   # 中度傷勢
        'RED': 10,      # 重傷
        'BLACK': 5,     # 極重傷/死亡
    }

    for i in range(50):
        gender = random.choice(['M', 'F'])
        surname = random.choice(SURNAMES)
        name = surname + random.choice(NAMES_MALE if gender == 'M' else NAMES_FEMALE)
        id_number = generate_taiwan_id(gender)

        # 決定檢傷分類
        triage = random.choices(
            list(triage_weights.keys()),
            weights=list(triage_weights.values())
        )[0]

        # 報到時間 (過去 48 小時內)
        checkin_offset = random.randint(1, 48 * 60)  # minutes
        checkin_time = now - timedelta(minutes=checkin_offset)

        # 區域分配
        if triage == 'GREEN':
            zone = random.choice(['rest_area', 'dining_area', 'family_area'])
        elif triage == 'YELLOW':
            zone = 'yellow_area'
        elif triage == 'RED':
            zone = 'red_area'
        else:
            zone = 'observation_area'

        cursor.execute("""
            INSERT INTO person (
                name, national_id_hash, role, triage_status,
                current_zone, checked_in_at, notes, created_at
            ) VALUES (?, ?, 'public', ?, ?, ?, ?, ?)
        """, (
            name,
            hash_id(id_number),
            triage,
            zone,
            checkin_time.isoformat(),
            f"Demo 資料 #{i+1}",
            checkin_time.isoformat()
        ))

    # 加入工作人員
    staff_data = [
        ("王主任", "admin", "office"),
        ("李護理師", "staff", "triage_area"),
        ("張志工", "staff", "registration"),
        ("陳志工", "staff", "supply_station"),
    ]
    for name, role, zone in staff_data:
        cursor.execute("""
            INSERT INTO person (name, role, current_zone, checked_in_at, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (name, role, zone, now.isoformat(), now.isoformat()))

    # =========================================
    # 3. 物資庫存
    # =========================================
    inventory_data = [
        # 飲水類
        ("礦泉水 600ml", "water", "瓶", 500, 1000, 100, "統一", "2025-12-31"),
        ("桶裝水 20L", "water", "桶", 30, 50, 10, "悅氏", "2025-06-30"),

        # 食品類
        ("泡麵", "food", "碗", 200, 500, 50, "統一肉燥麵", "2025-03-31"),
        ("罐頭食品", "food", "罐", 150, 300, 30, "綜合口味", "2026-01-31"),
        ("餅乾", "food", "包", 100, 200, 20, "蘇打餅乾", "2025-09-30"),
        ("即食飯", "food", "盒", 80, 150, 15, "免煮白飯", "2025-08-31"),

        # 醫療用品
        ("急救包", "medical", "個", 25, 50, 10, "標準急救包", None),
        ("口罩", "medical", "盒", 50, 100, 20, "醫療級", "2026-06-30"),
        ("消毒酒精", "medical", "瓶", 30, 50, 10, "75%酒精", "2025-12-31"),
        ("繃帶", "medical", "捲", 100, 200, 30, "彈性繃帶", None),

        # 生活用品
        ("睡袋", "supplies", "個", 80, 120, 20, "三季型", None),
        ("毛毯", "supplies", "條", 100, 150, 25, "刷毛毛毯", None),
        ("睡墊", "supplies", "個", 60, 100, 15, "折疊睡墊", None),
        ("衛生紙", "supplies", "串", 40, 80, 10, "12入裝", None),

        # 設備
        ("發電機", "equipment", "台", 2, 3, 1, "5kW 汽油發電機", None),
        ("手電筒", "equipment", "支", 30, 50, 10, "LED 手電筒", None),
        ("對講機", "equipment", "組", 8, 10, 2, "無線對講機", None),
        ("摺疊桌", "equipment", "張", 15, 20, 5, "6尺折疊桌", None),
        ("摺疊椅", "equipment", "張", 80, 100, 20, "塑膠折疊椅", None),
    ]

    for item in inventory_data:
        name, category, unit, qty, max_qty, min_qty, spec, exp = item
        cursor.execute("""
            INSERT INTO inventory (
                name, category, unit, quantity, max_quantity, min_quantity,
                specification, expiry_date, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, category, unit, qty, max_qty, min_qty, spec, exp, now.isoformat()))

    # 設備狀態更新
    cursor.execute("""
        UPDATE inventory SET check_status = 'OK', last_check_date = ?
        WHERE category = 'equipment'
    """, (now.strftime("%Y-%m-%d"),))

    # =========================================
    # 4. 廣播訊息
    # =========================================
    messages = [
        ("【重要公告】晚餐時間為 18:00-19:00，請至一樓大廳領取便當", True),
        ("【醫療服務】血壓量測服務於二樓護理站，歡迎有需要的民眾前往", True),
        ("【提醒】夜間 22:00 後請降低音量，維護其他人休息品質", False),
        ("【物資發放】嬰兒用品請至服務台登記領取", False),
        ("【尋人】請張小明的家屬至服務台聯繫", False),
    ]

    for content, is_pinned in messages:
        msg_time = now - timedelta(hours=random.randint(1, 24))
        cursor.execute("""
            INSERT INTO message (
                content, message_type, is_pinned, sender_name, created_at
            ) VALUES (?, 'broadcast', ?, '系統管理員', ?)
        """, (content, 1 if is_pinned else 0, msg_time.isoformat()))

    # =========================================
    # 5. 事件記錄
    # =========================================
    events = [
        ("收容所開設", "info", "防災收容所正式開設，開始接收災民"),
        ("物資到達", "info", "第一批救援物資已送達"),
        ("醫療團隊進駐", "info", "衛生局醫療團隊已進駐"),
        ("用水量警示", "warning", "飲用水存量低於安全值"),
    ]

    for title, level, desc in events:
        event_time = now - timedelta(hours=random.randint(1, 48))
        cursor.execute("""
            INSERT INTO event (title, level, description, created_at)
            VALUES (?, ?, ?, ?)
        """, (title, level, desc, event_time.isoformat()))

    conn.commit()
    print(f"[CIRS Seeder] Demo data seeded successfully!")
    print(f"  - 54 persons (50 residents + 4 staff)")
    print(f"  - 19 inventory items")
    print(f"  - 5 broadcast messages")
    print(f"  - 4 events")


def clear_demo_data(conn):
    """清除所有資料 (用於 reset 功能)"""
    cursor = conn.cursor()

    # 清除資料表 (保留結構)
    tables = ['person', 'inventory', 'message', 'event', 'config']
    for table in tables:
        try:
            cursor.execute(f"DELETE FROM {table}")
        except Exception as e:
            print(f"[CIRS Seeder] Warning: Could not clear {table}: {e}")

    conn.commit()
    print("[CIRS Seeder] All demo data cleared")
