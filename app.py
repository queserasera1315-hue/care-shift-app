import streamlit as st
import pandas as pd
import datetime
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, LpStatus, value

# --------------------------------------------------
# 1. ページ基本設定
# --------------------------------------------------
st.set_page_config(page_title="介護シフト自動作成アプリ", layout="wide")
st.title("🏥 介護シフト自動作成アプリ")

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

# 勤務区分
shifts = ["早出", "日勤", "遅出", "夜勤", "明け", "公休", "有休"]

# --------------------------------------------------
# 3. スタッフごとの働き方区分（専従設定）
# --------------------------------------------------
st.header("1. スタッフの働き方（専従）設定")
st.caption("※ 夜勤専従や日勤のみなど、スタッフごとの勤務スタイルを選択してください。")

work_types = {}
cols_per_row = 4
for i in range(0, len(staff_list), cols_per_row):
    cols = st.columns(cols_per_row)
    for j, s in enumerate(staff_list[i:i+cols_per_row]):
        with cols[j]:
            work_types[s] = st.selectbox(
                f"{s} の勤務区分",
                ["通常", "夜勤専従", "日勤専従（夜勤不可）"],
                key=f"wt_{s}"
            )

# --------------------------------------------------
# 4. 1日の必要人数・月間回数ルール
# --------------------------------------------------
st.header("2. 1日の必要人数の設定")
col_req1, col_req2, col_req3, col_req4, col_req5 = st.columns(5)

with col_req1:
    req_early = st.number_input("早出 (人/日)", min_value=0, value=1)
with col_req2:
    min_day = st.number_input("日勤 最小(人/日)", min_value=0, max_value=10, value=0)
with col_req3:
    max_day = st.number_input("日勤 最大(人/日)", min_value=min_day, max_value=10, value=2)
with col_req4:
    req_late = st.number_input("遅出 (人/日・不足時0可)", min_value=0, value=1)
with col_req5:
    req_night = st.number_input("夜勤 (人/日)", min_value=0, value=1)

st.header("3. 1ヶ月の勤務上限・ルール設定")
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
with col_m1:
    target_off = st.number_input("月間公休数 (日/人)", min_value=0, value=9)
with col_m2:
    max_night = st.number_input("月間夜勤上限 (回/人・通常勤務用)", min_value=0, value=5)
with col_m3:
    max_early = st.number_input("月間早出上限 (回/人・0で無制限)", min_value=0, value=0)
with col_m4:
    max_late = st.number_input("月間遅出上限 (回/人・0で無制限)", min_value=0, value=0)

col_r1, col_r2 = st.columns(2)
with col_r1:
    max_work = st.number_input("最大連続勤務 (日)", min_value=1, value=5)
with col_r2:
    opt_night_off = st.checkbox("夜勤 → 明け → 公休（または有休）を必須にする", value=True)

# --------------------------------------------------
# 5. 希望休・個別シフト入力
# --------------------------------------------------
st.header("4. スタッフごとの勤務希望（希望休・指定シフト）入力")
st.caption("💡 入力方法: 固定したいマスに半角/全角で名称（例: `公休`, `有休`, `早出`, `日勤`, `遅出`, `夜勤`）を直接入力してください。空欄は自動調整されます。")

init_data = {f"{d}日": [""] * len(staff_list) for d in days}
df_requests = st.data_editor(pd.DataFrame(init_data, index=staff_list), key="req_table")

# --------------------------------------------------
# 6. シフト自動生成実行
# --------------------------------------------------
st.markdown("---")

if st.button("🚀 シフトを作成する", type="primary"):
    if not staff_list:
        st.error("スタッフを入力してください。")
    else:
        model = LpProblem("Care_Shift_Scheduling", LpMinimize)
        
        # 割り当て変数
        x = {(s, d, sh): LpVariable(f"x_{s}_{d}_{sh}", cat="Binary") 
             for s in staff_list for d in days for sh in shifts}
        
        # 人手不足調整用変数（遅出を自動で削るための優先設定）
        late_shortage = {d: LpVariable(f"late_shortage_{d}", lowBound=0, cat="Integer") for d in days}

        # 目的関数: 遅出の不足を極力抑える
        model += lpSum([late_shortage[d] * 1000 for d in days])

        # --- スタッフごとの制約条件 ---
        for s in staff_list:
            w_type = work_types[s]

            # 1日1シフト
            for d in days:
                model += lpSum([x[s, d, sh] for sh in shifts]) == 1

            # 月間公休数
            model += lpSum([x[s, d, "公休"] for d in days]) == target_off

            # 働き方区分（専従）の制御
            if w_type == "夜勤専従":
                for d in days:
                    model += x[s, d, "早出"] == 0
                    model += x[s, d, "日勤"] == 0
                    model += x[s, d, "遅出"] == 0
            elif w_type == "日勤専従（夜勤不可）":
                for d in days:
                    model += x[s, d, "夜勤"] == 0
                    model += x[s, d, "明け"] == 0
            else: # 通常勤務
                model += lpSum([x[s, d, "夜勤"] for d in days]) <= max_night

            # 月間早出上限
            if max_early > 0:
                model += lpSum([x[s, d, "早出"] for d in days]) <= max_early

            # 月間遅出上限
            if max_late > 0:
                model += lpSum([x[s, d, "遅出"] for d in days]) <= max_late

            # 個別希望（入力された文字をそのまま反映）
            for d in days:
                val = str(df_requests.loc[s, f"{d}日"]).strip()
                if val in shifts:
                    model += x[s, d, val] == 1

            # 連勤上限
            for d in range(1, num_days - max_work + 1):
                work_sum = lpSum([x[s, d + i, sh] 
                                  for i in range(max_work + 1) 
                                  for sh in ["早出", "日勤", "遅出", "夜勤"]])
                model += work_sum <= max_work

            # 夜勤のルール（翌日は明け、連続夜勤は不可）
            for d in days[:-1]:
                model += x[s, d, "夜勤"] <= x[s, d + 1, "明け"]
                model += x[s, d, "夜勤"] + x[s, d + 1, "夜勤"] <= 1

            # 夜勤 → 明け → 休日ルール
            if opt_night_off:
                for d in range(1, num_days - 1):
                    model += x[s, d, "夜勤"] <= x[s, d + 2, "公休"] + x[s, d + 2, "有休"]

            # 夜勤の前後半バランス
            if w_type != "日勤専従（夜勤不可）":
                mid = num_days // 2
                fh = lpSum([x[s, d, "夜勤"] for d in range(1, mid + 1)])
                sh = lpSum([x[s, d, "夜勤"] for d in range(mid + 1, num_days + 1)])
                model += fh - sh <= 2
                model += sh - fh <= 2

        # --- 日ごとの必要人数制約 ---
        for d in days:
            model += lpSum([x[s, d, "早出"] for s in staff_list]) >= req_early
            
            # 日勤人数の範囲（最小〜最大）
            model += lpSum([x[s, d, "日勤"] for s in staff_list]) >= min_day
            model += lpSum([x[s, d, "日勤"] for s in staff_list]) <= max_day
            
            model += lpSum([x[s, d, "夜勤"] for s in staff_list]) >= req_night
            
            # 人手不足の時は遅出を0人にして自動調整
            model += lpSum([x[s, d, "遅出"] for s in staff_list]) + late_shortage[d] >= req_late

        # 計算実行
        status = model.solve()

        if LpStatus[status] == "Optimal":
            st.success("🎉 シフトを作成しました！")
            
            # 結果出力
            result = {}
            for s in staff_list:
                row = []
                for d in days:
                    for sh in shifts:
                        if value(x[s, d, sh]) == 1:
                            row.append(sh)
                            break
                result[s] = row
            
            df_res = pd.DataFrame(result, index=[f"{d}日" for d in days]).T
            st.dataframe(df_res, use_container_width=True)
            
            # 遅出調整の通知
            short_days = [d for d in days if value(late_shortage[d]) > 0]
            if short_days:
                st.info(f"💡 以下の日は人員調整のため「遅出」を0人（または減員）に調整しました: {', '.join([f'{d}日' for d in short_days])}")
        else:
            st.error("この条件では作成できませんでした。希望休や日勤・遅出の人数設定を緩めてお試しください。")
