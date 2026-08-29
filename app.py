import streamlit as st
import pandas as pd
import datetime
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, LpStatus, value

# ---------------------------------------------------------
# 1. ページ基本設定
# ---------------------------------------------------------
st.set_page_config(page_title="介護シフト自動作成", layout="centered")
st.title("🏥 介護シフト自動作成アプリ")
st.caption("個別スキル・連勤上限・遅早防止・夜勤専従回数・シフト均等化を考慮します。")

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
date_labels = []
for d in days:
    dt = datetime.date(year, month, d)
    w_str = weekdays_jp[dt.weekday()]
    date_labels.append(f"{month}/{d}({w_str})")

# 基本公休数の設定
monthly_holidays = st.number_input("1人あたりの基本公休数（日）", min_value=1, max_value=15, value=9)

# ---------------------------------------------------------
# 3. 1日あたりの必要人数
# ---------------------------------------------------------
st.subheader("👥 2. 1日あたりの必要人数")
col1, col2 = st.columns(2)
with col1:
    req_hayaban = st.number_input("早番 (7-16)", min_value=0, value=1)
    req_nikkin = st.number_input("日勤 (9-18)", min_value=0, value=1)
with col2:
    req_osoban = st.number_input("遅番 (10-19)", min_value=0, value=1)
    req_yakin = st.number_input("夜勤 (16-9)", min_value=0, value=1)

shifts = ["早", "日", "遅", "夜", "明", "休"]

# ---------------------------------------------------------
# 4. スタッフごとの個別条件設定
# ---------------------------------------------------------
st.subheader("👤 3. スタッフごとの個別条件設定")

staff_roles = {}
max_consecutive_days = {}
desire_holidays = {}
night_shift_counts = {}  # 夜勤専従用

role_options = {
    "全シフト可（早/遅/日/夜）": ["早", "日", "遅", "夜", "明", "休"],
    "日勤帯のみ（早/遅/日）": ["早", "日", "遅", "休"],
    "夜勤専用（夜）": ["夜", "明", "休"],
    "早・日のみ": ["早", "日", "休"],
    "遅・日のみ": ["遅", "日", "休"]
}

for s in staffs:
    with st.expander(f"【{s}】の設定", expanded=False):
        role_choice = st.selectbox(
            "勤務可能なシフト", 
            options=list(role_options.keys()), 
            key=f"role_{s}"
        )
        staff_roles[s] = role_options[role_choice]

        # 夜勤専従の場合のみ、月間夜勤回数を指定できる
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

        holiday_str = st.text_input(
            "希望休（日付をカンマ区切りで入力 例: 5, 12）", 
            value="", 
            key=f"holiday_{s}"
        )
        parsed_days = []
        for d_str in holiday_str.split(","):
            d_str = d_str.strip()
            if d_str.isdigit():
                d_num = int(d_str)
                if 1 <= d_num <= num_days:
                    parsed_days.append(d_num)
        desire_holidays[s] = parsed_days

# ---------------------------------------------------------
# 5. シフト計算ロジック
# ---------------------------------------------------------
st.markdown("---")

if st.button("🚀 シフトを作成する", type="primary"):
    with st.spinner("AIが夜勤専従回数・均等化を含めて計算中..."):
        
        prob = LpProblem("ShiftScheduling", LpMinimize)
        x = {}
        for s in staffs:
            for d in days:
                for shift in shifts:
                    x[s, d, shift] = LpVariable(f"x_{s}_{d}_{shift}", cat="Binary")

        # 平準化用の補助変数
        max_h = LpVariable("max_h", lowBound=0)
        max_o = LpVariable("max_o", lowBound=0)
        max_y = LpVariable("max_y", lowBound=0)

        # 制約1: 各スタッフは1日1シフト
        for s in staffs:
            for d in days:
                prob += lpSum([x[s, d, shift] for shift in shifts]) == 1

        # 制約2: 可能シフトのみ割り振る
        for s in staffs:
            allowed_shifts = staff_roles[s]
            for d in days:
                for shift in shifts:
                    if shift not in allowed_shifts:
                        prob += x[s, d, shift] == 0

        # 制約3: 夜勤 ➔ 翌日「明」
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "明"] >= x[s, d, "夜"]

        # 制約4: 「明」 ➔ 翌日「休」
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "休"] >= x[s, d, "明"]

        # 制約5: 遅番 ➔ 翌日「早番」の禁止（遅早禁止）
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "早"] + x[s, d, "遅"] <= 1

        # 制約6: 最大連勤数制限
        for s in staffs:
            k = max_consecutive_days[s]
            for d in range(1, num_days - k + 1):
                prob += lpSum([x[s, d + i, "休"] for i in range(k + 1)]) >= 1

        # 制約7: 公休数（夜勤専従以外は基本公休数を適用）
        for s in staffs:
            if night_shift_counts[s] is None:
                prob += lpSum([x[s, d, "休"] for d in days]) == monthly_holidays

        # 制約8: 夜勤専従の「月間夜勤回数」固定制約
        for s in staffs:
            if night_shift_counts[s] is not None:
                prob += lpSum([x[s, d, "夜"] for d in days]) == night_shift_counts[s]

        # 制約9: 希望休の反映
        for s in staffs:
            for d in desire_holidays[s]:
                prob += x[s, d, "休"] == 1

        # 制約10: 必要人数の確保
        for d in days:
            prob += lpSum([x[s, d, "早"] for s in staffs]) >= req_hayaban
            prob += lpSum([x[s, d, "日"] for s in staffs]) >= req_nikkin
            prob += lpSum([x[s, d, "遅"] for s in staffs]) >= req_osoban
            prob += lpSum([x[s, d, "夜"] for s in staffs]) >= req_yakin

        # 制約11: 通常スタッフの平準化（専従以外）
        for s in staffs:
            if night_shift_counts[s] is None:
                if "早" in staff_roles[s]:
                    prob += lpSum([x[s, d, "早"] for d in days]) <= max_h
                if "遅" in staff_roles[s]:
                    prob += lpSum([x[s, d, "遅"] for d in days]) <= max_o
                if "夜" in staff_roles[s]:
                    prob += lpSum([x[s, d, "夜"] for d in days]) <= max_y

        # 目的関数
        prob += max_h + max_o + max_y

        # 計算実行
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
                
                row_full = s_shifts + [f"早:{h_cnt} 日:{n_cnt} 遅:{o_cnt} 夜:{y_cnt} 明:{a_cnt} 公休:{k_cnt}"]
                result_data[s] = row_full
            
            headers = date_labels + ["【月間合計回数】"]
            df_main = pd.DataFrame(result_data, index=headers).T
            
            summary_data = {}
            for target_shift in ["早", "日", "遅", "夜", "明", "休"]:
                daily_sums = [sum(1 for s in staffs if value(x[s, d, target_shift]) == 1) for d in days]
                summary_data[f"【日別合計】{target_shift}"] = daily_sums + ["-"]
            
            df_summary = pd.DataFrame(summary_data, index=headers).T

            df_full = pd.concat([df_main, df_summary])

            st.write("📋 **シフト表（夜勤専従設定・月間集計付き）**")
            st.dataframe(df_full, use_container_width=True)
            
            csv = df_full.to_csv().encode('utf-8-sig')
            st.download_button(
                label="📥 CSVでダウンロード",
                data=csv,
                file_name=f"シフト表_{year}年{month}月.csv",
                mime="text/csv"
            )
        else:
            st.error("❌ 条件を満たすシフトを作成できませんでした。夜勤専従の回数指定や必要人数のバランスを確認してください。")
