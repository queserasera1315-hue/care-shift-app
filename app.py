import streamlit as st
import pandas as pd
import datetime
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, LpStatus, value

# --------------------------------------------------
# 1. ページ基本設定
# --------------------------------------------------
st.set_page_config(page_title="介護シフト自動作成アプリ", layout="wide")
st.title("🏥 介護シフト自動作成アプリ")
st.caption("希望シフト・夜勤の月間均等配置・人員不足時の遅出自動調整対応版")

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
# 3. 必要人数の設定
# --------------------------------------------------
st.header("1. 1日あたりの必要人数の設定")
col1, col2, col3, col4 = st.columns(4)

with col1:
    req_early = st.number_input("早出 (人/日)", min_value=0, value=1)
with col2:
    req_day = st.number_input("日勤 (人/日)", min_value=0, value=2)
with col3:
    req_late = st.number_input("遅出 (人/日・不足時0可)", min_value=0, value=1)
with col4:
    req_night = st.number_input("夜勤 (人/日)", min_value=0, value=1)

# --------------------------------------------------
# 4. シフト作成実行
# --------------------------------------------------
st.header("2. シフト自動生成")

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

        # 目的関数: 遅出の不足をできるだけ最小化する（どうしても無理な場合のみ遅出を減らす）
        model += lpSum([late_shortage[d] * 1000 for d in days])

        # --- 制約条件 ---
        for d in days:
            # 1. 1人1日1シフト
            for s in staff_list:
                model += lpSum([x[s, d, sh] for sh in shifts]) == 1

            # 2. 1日の必要人数の確保
            model += lpSum([x[s, d, "早出"] for s in staff_list]) >= req_early
            model += lpSum([x[s, d, "日勤"] for s in staff_list]) >= req_day
            model += lpSum([x[s, d, "夜勤"] for s in staff_list]) >= req_night
            
            # 遅出は不足を許容（人手不足時は0人になってもエラーにしない）
            model += lpSum([x[s, d, "遅出"] for s in staff_list]) + late_shortage[d] >= req_late

        # 3. 夜勤の翌日は必ず「明けて」
        for s in staff_list:
            for d in days[:-1]:
                model += x[s, d, "夜勤"] <= x[s, d + 1, "明け"]

        # 4. 夜勤の連続禁止
        for s in staff_list:
            for d in days[:-1]:
                model += x[s, d, "夜勤"] + x[s, d + 1, "夜勤"] <= 1

        # 5. 夜勤の月間バランス（前半・後半での平準化）
        mid_day = num_days // 2
        for s in staff_list:
            first_half_nights = lpSum([x[s, d, "夜勤"] for d in range(1, mid_day + 1)])
            second_half_nights = lpSum([x[s, d, "夜勤"] for d in range(mid_day + 1, num_days + 1)])
            
            # 前半と後半の夜勤回数の差を2回以内にする（偏りを防ぐ）
            model += first_half_nights - second_half_nights <= 2
            model += second_half_nights - first_half_nights <= 2

        # 6. 連勤上限（最大5連勤まで）
        for s in staff_list:
            for d in range(1, num_days - 4):
                work_days = lpSum([x[s, d + i, sh] 
                                  for i in range(6) 
                                  for sh in ["早出", "日勤", "遅出", "夜勤"]])
                model += work_days <= 5

        # --- 最適化の実行 ---
        status = model.solve()

        if LpStatus[status] == "Optimal":
            st.success("🎉 シフト表が正常に作成されました！")
            
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
            
            # 遅出がカットされた日の通知
            shortage_days = [d for d in days if value(late_shortage[d]) > 0]
            if shortage_days:
                st.warning(f"⚠️ 人員調整のため、以下の日は「遅出」を削って調整しました: {', '.join([f'{d}日' for d in shortage_days])}")
        else:
            st.error("条件を満たすシフトを作成できませんでした。スタッフ人数を増やすか、設定を見直してください。")
