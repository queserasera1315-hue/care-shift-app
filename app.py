import streamlit as st
import pandas as pd
import datetime
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, LpStatus, value

# --------------------------------------------------
# 1. ページ基本設定
# --------------------------------------------------
st.set_page_config(page_title="介護シフト自動作成アプリ", layout="wide")
st.title("🏥 介護シフト自動作成アプリ")
st.caption("全条件統合版（夜勤バランス均等化・人手不足時の遅出調整機能付き）")

# --------------------------------------------------
# 2. 基本条件の設定 (サイドバー)
# --------------------------------------------------
st.sidebar.header("⚙️ 基本設定")

# 年月の選択
today = datetime.date.today()
year = st.sidebar.number_input("年", min_value=2024, max_value=2030, value=today.year)
month = st.sidebar.number_input("月", min_value=1, max_value=12, value=today.month)

# 日数の計算
if month in [1, 3, 5, 7, 8, 10, 12]:
    num_days = 31
elif month in [4, 6, 9, 11]:
    num_days = 30
else:
    num_days = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28

days = list(range(1, num_days + 1))

# スタッフリスト
st.sidebar.subheader("👥 スタッフ登録")
default_staff = "スタッフA, スタッフB, スタッフC, スタッフD, スタッフE, スタッフF, スタッフG, スタッフH"
staff_input = st.sidebar.text_area("カンマ区切りで入力", default_staff)
staff_list = [s.strip() for s in staff_input.split(",") if s.strip()]

# 勤務区分の定義
shifts = ["早出", "日勤", "遅出", "夜勤", "明け", "公休", "有休"]

# --------------------------------------------------
# 3. 条件詳細設定
# --------------------------------------------------
st.header("1. シフト条件・必要人数の設定")

col_req1, col_req2, col_req3, col_req4 = st.columns(4)
with col_req1:
    req_early = st.number_input("早出 (人/日)", min_value=0, value=1)
with col_req2:
    req_day = st.number_input("日勤 (人/日)", min_value=0, value=2)
with col_req3:
    req_late = st.number_input("遅出 (人/日・不足時0可)", min_value=0, value=1)
with col_req4:
    req_night = st.number_input("夜勤 (人/日)", min_value=0, value=1)

col_rule1, col_rule2, col_rule3 = st.columns(3)
with col_rule1:
    target_off_days = st.number_input("月間公休数 (日/人)", min_value=0, value=9)
with col_rule2:
    max_night_shifts = st.number_input("月間夜勤上限 (回/人)", min_value=0, value=5)
with col_rule3:
    max_consecutive_work = st.number_input("最大連勤数 (日)", min_value=1, value=5)

st.subheader("💡 組み合わせルール設定")
col_opt1, col_opt2 = st.columns(2)
with col_opt1:
    opt_night_off = st.checkbox("夜勤 → 明け → 公休（または有休）を必須にする", value=True)
with col_opt2:
    opt_night_prev = st.checkbox("夜勤の前日は「遅出」または「公休・有休」にする", value=True)

# --------------------------------------------------
# 4. 希望休の設定
# --------------------------------------------------
st.header("2. 希望休（公休・有休）の設定")
st.caption("※ 該当するセルに「公休」または「有休」を入力してください（空欄可）")

# 初期データの作成
init_data = {f"{d}日": [""] * len(staff_list) for d in days}
df_requests_init = pd.DataFrame(init_data, index=staff_list)

edited_requests = st.data_editor(df_requests_init, key="request_editor")

# --------------------------------------------------
# 5. シフト作成実行
# --------------------------------------------------
st.header("3. シフト自動生成")

if st.button("🚀 シフトを作成する", type="primary"):
    if not staff_list:
        st.error("スタッフを1人以上登録してください。")
    else:
        # --- 数理モデルの構築 ---
        model = LpProblem("Care_Shift_Scheduling", LpMinimize)
        
        # 変数: x[s, d, shift] = 1 (スタッフsがd日にshift勤務)
        x = {(s, d, sh): LpVariable(f"x_{s}_{d}_{sh}", cat="Binary") 
             for s in staff_list for d in days for sh in shifts}
        
        # 遅出不足を許容するためのスラック変数（ペナルティ用）
        late_shortage = {d: LpVariable(f"late_shortage_{d}", lowBound=0, cat="Integer") for d in days}

        # 目的関数: 遅出の不足をできるだけ最小化する
        model += lpSum([late_shortage[d] * 1000 for d in days])

        # --- 制約条件 ---
        for s in staff_list:
            # A. 1人1日1シフト
            for d in days:
                model += lpSum([x[s, d, sh] for sh in shifts]) == 1

            # B. 月間公休数の確保
            model += lpSum([x[s, d, "公休"] for d in days]) == target_off_days

            # C. 月間夜勤回数の上限
            model += lpSum([x[s, d, "夜勤"] for d in days]) <= max_night_shifts

            # D. 希望休（公休・有休）の反映
            for d in days:
                req = edited_requests.loc[s, f"{d}日"]
                if req in ["公休", "有休"]:
                    model += x[s, d, req] == 1

            # E. 連勤上限（指定日数以上の連続勤務を禁止）
            for d in range(1, num_days - max_consecutive_work + 1):
                work_days = lpSum([x[s, d + i, sh] 
                                  for i in range(max_consecutive_work + 1) 
                                  for sh in ["早出", "日勤", "遅出", "夜勤"]])
                model += work_days <= max_consecutive_work

            # F. 夜勤関連の連続制約
            for d in days[:-1]:
                # 夜勤の翌日は必ず「明け」
                model += x[s, d, "夜勤"] <= x[s, d + 1, "明け"]
                # 夜勤の連続禁止
                model += x[s, d, "夜勤"] + x[s, d + 1, "夜勤"] <= 1

            # G. オプション：夜勤 → 明け → 休日
            if opt_night_off:
                for d in range(1, num_days - 1):
                    model += x[s, d, "夜勤"] <= x[s, d + 2, "公休"] + x[s, d + 2, "有休"]

            # H. オプション：夜勤前日は「遅出」または「休日」
            if opt_night_prev:
                for d in range(2, num_days + 1):
                    model += x[s, d, "夜勤"] <= x[s, d - 1, "遅出"] + x[s, d - 1, "公休"] + x[s, d - 1, "有休"]

            # I. 【新条件】夜勤の月間バランス（前半・後半での平準化）
            mid_day = num_days // 2
            first_half_nights = lpSum([x[s, d, "夜勤"] for d in range(1, mid_day + 1)])
            second_half_nights = lpSum([x[s, d, "夜勤"] for d in range(mid_day + 1, num_days + 1)])
            model += first_half_nights - second_half_nights <= 2
            model += second_half_nights - first_half_nights <= 2

        # --- 日ごとの必要人数制約 ---
        for d in days:
            model += lpSum([x[s, d, "早出"] for s in staff_list]) >= req_early
            model += lpSum([x[s, d, "日勤"] for s in staff_list]) >= req_day
            model += lpSum([x[s, d, "夜勤"] for s in staff_list]) >= req_night
            
            # 【新条件】遅出は人手不足時に0人への自動調整（削減）を許可
            model += lpSum([x[s, d, "遅出"] for s in staff_list]) + late_shortage[d] >= req_late

        # --- 最適化の実行 ---
        status = model.solve()

        if LpStatus[status] == "Optimal":
            st.success("🎉 条件をすべて満たしたシフト表を作成しました！")
            
            # 結果のデータフレーム作成
            shift_data = {}
            for s in staff_list:
                person_shifts = []
                for d in days:
                    for sh in shifts:
                        if value(x[s, d, sh]) == 1:
                            person_shifts.append(sh)
                            break
                shift_data[s] = person_shifts
            
            df_result = pd.DataFrame(shift_data, index=[f"{d}日" for d in days]).T
            
            # 表示
            st.dataframe(df_result, use_container_width=True)
            
            # 遅出が削減された日の通知
            shortage_days = [d for d in days if value(late_shortage[d]) > 0]
            if shortage_days:
                st.warning(f"⚠️ 人員調整のため、以下の日は「遅出」を0人（または減員）にして調整しました: {', '.join([f'{d}日' for d in shortage_days])}")
        else:
            st.error("条件を満たすシフトを作成できませんでした。希望休が集中しすぎているか、スタッフ人数に対して必要人数が多すぎる可能性があります。設定を見直してください。")
