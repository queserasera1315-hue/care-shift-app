import streamlit as st
import pandas as pd
import datetime
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, LpStatus, value

# ---------------------------------------------------------
# 1. ページ基本設定
# ---------------------------------------------------------
st.set_page_config(page_title="介護シフト自動作成", layout="centered")
st.title("🏥 介護シフト自動作成アプリ")
st.caption("希望シフト・有休(公休分離)・夜勤均等配置・連勤上限・遅早防止対応。")

# ---------------------------------------------------------
# 2. 基本条件の設定
# ---------------------------------------------------------
st.subheader("⚙️ 1. 基本条件の設定")

staff_input = st.text_input(
    "スタッフ名（カンマ区切り）", 
    value="Aさん, Bさん, Cさん, Dさん, Eさん, Fさん, Gさん"
)
staffs = [s.strip() for s in staff_input.split(",") if s.strip()]

col_y, col_m = st.columns(2)
with col_y:
    year = st.number_input("年", min_value=2025, max_value=2030, value=2026)
with col_m:
    month = st.number_input("月", min_value=1, max_value=12, value=9)

# 該当月の日数を自動計算
if month in [1, 3, 5, 7, 8, 10, 12]:
    num_days = 31
elif month in [4, 6, 9, 11]:
    num_days = 30
else:
    num_days = 29 if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0) else 28

days = list(range(1, num_days + 1))

# 曜日ラベルの作成
weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
day_numbers = [str(d) for d in days]
day_weekdays = [weekdays_jp[datetime.date(year, month, d).weekday()] for d in days]

# 基本公休数の設定
monthly_holidays = st.number_input("1人あたりの毎月の「基本公休数」（日）", min_value=1, max_value=15, value=9)

# ---------------------------------------------------------
# 3. 1日あたりの必要人数
# ---------------------------------------------------------
st.subheader("👥 2. 1日あたりの必要人数")

col1, col2 = st.columns(2)
with col1:
    req_hayaban = st.number_input("早番 (7-16) 【固定人数】", min_value=0, value=1)
    req_osoban = st.number_input("遅番 (10-19) 【固定人数】", min_value=0, value=1)
    req_yakin = st.number_input("夜勤 (16-9) 【固定人数】", min_value=0, value=1)

with col2:
    st.write("▼ 日勤 (9-18) の人数範囲")
    col_nikkin_min, col_nikkin_max = st.columns(2)
    with col_nikkin_min:
        req_nikkin_min = st.number_input("最小", min_value=0, max_value=5, value=0)
    with col_nikkin_max:
        req_nikkin_max = st.number_input("最大", min_value=0, max_value=5, value=1)

shifts = ["早", "日", "遅", "夜", "明", "休", "有"]

# ---------------------------------------------------------
# 4. スタッフごとの個別条件設定
# ---------------------------------------------------------
st.subheader("👤 3. スタッフごとの個別条件設定")

staff_roles = {}
max_consecutive_days = {}
desire_holidays = {}
desire_paid_leaves = {}
desire_workdays = {}
night_shift_counts = {}

role_options = {
    "全シフト可（早/遅/日/夜）": ["早", "日", "遅", "夜", "明", "休", "有"],
    "日勤帯のみ（早/遅/日）": ["早", "日", "遅", "休", "有"],
    "夜勤専用（夜）": ["夜", "明", "休", "有"],
    "早・日のみ": ["早", "日", "休", "有"],
    "遅・日のみ": ["遅", "日", "休", "有"]
}

for s in staffs:
    with st.expander(f"【{s}】の設定", expanded=False):
        role_choice = st.selectbox(
            "勤務可能なシフト", 
            options=list(role_options.keys()), 
            key=f"role_{s}"
        )
        staff_roles[s] = role_options[role_choice]

        if role_choice == "夜勤専用（夜）":
            y_count = st.number_input(
                "1ヶ月の夜勤回数（回）", 
                min_value=1, 
                max_value=15, 
                value=8, 
                key=f"yakin_cnt_{s}"
            )
            night_shift_counts[s] = y_count
        else:
            night_shift_counts[s] = None

        max_work = st.number_input(
            "最大連勤数（日）", 
            min_value=2, 
            max_value=7, 
            value=5, 
            key=f"max_work_{s}"
        )
        max_consecutive_days[s] = max_work

        workday_str = st.text_input(
            "希望勤務日・シフト（例: 3:早, 15:夜）", 
            value="", 
            key=f"workday_{s}",
            help="「日付:シフト」で指定できます（例: 3:早）。"
        )
        
        col_kh, col_yukyu = st.columns(2)
        with col_kh:
            holiday_str = st.text_input(
                "希望「公休」日（例: 5, 12）", 
                value="", 
                key=f"holiday_{s}",
                help="公休として休みを取得する日付"
            )
        with col_yukyu:
            paid_leave_str = st.text_input(
                "希望「有休」日（例: 20）", 
                value="", 
                key=f"paid_leave_{s}",
                help="公休とは別枠の【有給休暇】として指定する日付"
            )

        # 希望勤務日解析
        parsed_workdays = {}
        for item in workday_str.split(","):
            item = item.strip()
            if ":" in item or "：" in item:
                parts = item.replace("：", ":").split(":")
                d_str, shift_req = parts[0].strip(), parts[1].strip()
                if d_str.isdigit():
                    d_num = int(d_str)
                    if 1 <= d_num <= num_days and shift_req in ["早", "日", "遅", "夜", "明"]:
                        parsed_workdays[d_num] = shift_req
            elif item.isdigit():
                d_num = int(item)
                if 1 <= d_num <= num_days:
                    parsed_workdays[d_num] = "出勤"
        desire_workdays[s] = parsed_workdays

        # 希望公休解析
        parsed_holidays = []
        for d_str in holiday_str.split(","):
            d_str = d_str.strip()
            if d_str.isdigit():
                d_num = int(d_str)
                if 1 <= d_num <= num_days:
                    parsed_holidays.append(d_num)
        desire_holidays[s] = parsed_holidays

        # 希望有休解析
        parsed_paid_leaves = []
        for d_str in paid_leave_str.split(","):
            d_str = d_str.strip()
            if d_str.isdigit():
                d_num = int(d_str)
                if 1 <= d_num <= num_days:
                    parsed_paid_leaves.append(d_num)
        desire_paid_leaves[s] = parsed_paid_leaves

# ---------------------------------------------------------
# 5. シフト計算ロジック
# ---------------------------------------------------------
st.markdown("---")

if st.button("🚀 シフトを作成する", type="primary"):
    with st.spinner("AIが希望シフト・有休・夜勤間隔最適化を計算中..."):
        
        prob = LpProblem("ShiftScheduling", LpMinimize)
        x = {}
        for s in staffs:
            for d in days:
                for shift in shifts:
                    x[s, d, shift] = LpVariable(f"x_{s}_{d}_{shift}", cat="Binary")

        max_h = LpVariable("max_h", lowBound=0)
        max_o = LpVariable("max_o", lowBound=0)
        max_y = LpVariable("max_y", lowBound=0)

        # 1. 各スタッフ1日1シフト
        for s in staffs:
            for d in days:
                prob += lpSum([x[s, d, shift] for shift in shifts]) == 1

        # 2. 権限シフトのみ
        for s in staffs:
            allowed = staff_roles[s]
            for d in days:
                for shift in shifts:
                    if shift not in allowed:
                        prob += x[s, d, shift] == 0

        # 3. 夜 ➔ 明
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "明"] == x[s, d, "夜"]

        # 4. 明 ➔ 休み（公休または有休）
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "休"] + x[s, d + 1, "有"] >= x[s, d, "明"]

        # 5. 遅 ➔ 早 の禁止
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "早"] + x[s, d, "遅"] <= 1

        # 6. 連勤数制限（公休・有休どちらも休みカウント）
        for s in staffs:
            k = max_consecutive_days[s]
            for d in range(1, num_days - k + 1):
                prob += lpSum([x[s, d + i, "休"] + x[s, d + i, "有"] for i in range(k + 1)]) >= 1

        # 7. 公休数と有休数の固定
        for s in staffs:
            paid_cnt = len(desire_paid_leaves[s])
            prob += lpSum([x[s, d, "有"] for d in days]) == paid_cnt
            if night_shift_counts[s] is None:
                prob += lpSum([x[s, d, "休"] for d in days]) == monthly_holidays

        # 8. 夜勤専従回数
        for s in staffs:
            if night_shift_counts[s] is not None:
                prob += lpSum([x[s, d, "夜"] for d in days]) == night_shift_counts[s]

        # 9. 希望公休・有休の固定
        for s in staffs:
            for d in desire_holidays[s]:
                prob += x[s, d, "休"] == 1
            for d in desire_paid_leaves[s]:
                prob += x[s, d, "有"] == 1

        # 10. 希望勤務日・シフト
        for s in staffs:
            for d, req in desire_workdays[s].items():
                if req == "出勤":
                    prob += x[s, d, "休"] == 0
                    prob += x[s, d, "有"] == 0
                else:
                    prob += x[s, d, req] == 1

        # 11. 必要人数制約
        for d in days:
            prob += lpSum([x[s, d, "早"] for s in staffs]) == req_hayaban
            prob += lpSum([x[s, d, "遅"] for s in staffs]) == req_osoban
            prob += lpSum([x[s, d, "夜"] for s in staffs]) == req_yakin
            prob += lpSum([x[s, d, "日"] for s in staffs]) >= req_nikkin_min
            prob += lpSum([x[s, d, "日"] for s in staffs]) <= req_nikkin_max

        # 12. 平準化
        for s in staffs:
            if night_shift_counts[s] is None:
                if "早" in staff_roles[s]:
                    prob += lpSum([x[s, d, "早"] for d in days]) <= max_h
                if "遅" in staff_roles[s]:
                    prob += lpSum([x[s, d, "遅"] for d in days]) <= max_o
                if "夜" in staff_roles[s]:
                    prob += lpSum([x[s, d, "夜"] for d in days]) <= max_y

        # 【追加機能】13. 夜勤の間隔平準化（近すぎる夜勤にペナルティ）
        night_penalty = []
        for s in staffs:
            if "夜" in staff_roles[s]:
                # 夜勤間隔が2日以内（例: 1日夜勤 ➔ 2日明 ➔ 3日夜勤）に近い場合ペナルティ加算
                for d in range(1, num_days - 2):
                    p_var = LpVariable(f"p_night_{s}_{d}", cat="Binary")
                    prob += x[s, d, "夜"] + x[s, d + 2, "夜"] - 1 <= p_var
                    night_penalty.append(p_var)

        # 目的関数
        prob += max_h + max_o + max_y + 5 * lpSum(night_penalty)

        status = prob.solve()

        # ---------------------------------------------------------
        # 6. 結果表示・集計
        # ---------------------------------------------------------
        if LpStatus[status] == "Optimal":
            st.success(f"✅ {year}年{month}月のシフト表を作成しました！")
            
            result_data = {}
            for s in staffs:
                s_shifts = []
                for d in days:
                    for shift in shifts:
                        if value(x[s, d, shift]) == 1:
                            s_shifts.append(shift)
                
                h_cnt = s_shifts.count("早")
                n_cnt = s_shifts.count("日")
                o_cnt = s_shifts.count("遅")
                y_cnt = s_shifts.count("夜")
                a_cnt = s_shifts.count("明")
                k_cnt = s_shifts.count("休")
                u_cnt = s_shifts.count("有")
                
                row_full = s_shifts + [f"早:{h_cnt} 日:{n_cnt} 遅:{o_cnt} 夜:{y_cnt} 明:{a_cnt} 公休:{k_cnt} 有休:{u_cnt}"]
                result_data[s] = row_full
            
            columns_multi = pd.MultiIndex.from_tuples(
                [(d, w) for d, w in zip(day_numbers, day_weekdays)] + [("【月間合計回数】", "")]
            )
            
            df_main = pd.DataFrame(result_data, index=columns_multi).T
            
            summary_data = {}
            for target_shift in ["早", "日", "遅", "夜", "明", "休", "有"]:
                daily_sums = [sum(1 for s in staffs if value(x[s, d, target_shift]) == 1) for d in days]
                summary_data[f"【日別合計】{target_shift}"] = daily_sums + ["-"]
            
            df_summary = pd.DataFrame(summary_data, index=columns_multi).T

            df_full = pd.concat([df_main, df_summary])

            st.write(f"📋 **{year}年{month}月 シフト表**")
            st.dataframe(df_full, use_container_width=True)
            
            csv = df_full.to_csv().encode('utf-8-sig')
            st.download_button(
                label="📥 CSVでダウンロード",
                data=csv,
                file_name=f"シフト表_{year}年{month}月.csv",
                mime="text/csv"
            )
        else:
            st.error("❌ 条件を満たすシフトを作成できませんでした。希望条件が重複しすぎているか、必要人数の制約と衝突している可能性があります。")
