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

# スタッフ人数の選択（6人、7人、8人を確実に切り替え）
st.sidebar.subheader("👥 スタッフ人数・登録")
num_staff = st.sidebar.slider("スタッフ人数", min_value=6, max_value=8, value=8)

# 人数に応じて自動でスタッフリストを生成（A, B, C, D, E, F, G, H）
all_possible_staff = ["スタッフA", "スタッフB", "スタッフC", "スタッフD", "スタッフE", "スタッフF", "スタッフG", "スタッフH"]
staff_list = all_possible_staff[:num_staff]

st.sidebar.write(f"現在のメンバー: {', '.join(staff_list)}")

# 勤務区分
shifts = ["早出", "日勤", "遅出", "夜勤", "明け", "公休", "有休"]

# --------------------------------------------------
# 3. スタッフごとの個別設定（働き方 ＆ 連勤上限）
# --------------------------------------------------
st.header("1. スタッフの個別設定（働き方・連勤上限）")
st.caption("※ スタッフごとの勤務スタイルと、人ごとの最大連勤数（何連勤まで許容するか）を設定できます。")

work_types = {}
staff_max_work = {}

for s in staff_list:
    st.markdown(f"**👤 {s}**")
    c1, c2 = st.columns(2)
    with c1:
        work_types[s] = st.selectbox(
            f"勤務区分",
            ["通常", "夜勤専従", "日勤専従（夜勤不可）"],
            key=f"wt_{s}"
        )
    with c2:
        staff_max_work[s] = st.number_input(
            f"最大連勤数 (日)",
            min_value=1, max_value=10, value=5,
            key=f"mw_{s}"
        )
    st.markdown("---")

# --------------------------------------------------
# 4. 1日の必要人数・月間共通ルール
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

st.header("3. 1ヶ月の共通ルール設定")
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
with col_m1:
    target_off = st.number_input("月間公休数 (日/人)", min_value=0, value=9)
with col_m2:
    max_night = st.number_input("月間夜勤上限 (回/人・通常勤務用)", min_value=0, value=5)
with col_m3:
    max_early = st.number_input("月間早出上限 (回/人・0で無制限)", min_value=0, value=0)
with col_m4:
    max_late = st.number_input("月間遅出上限 (回/人・0で無制限)", min_value=0, value=0)

opt_night_off = st.checkbox("夜勤 → 明け → 公休（または有休）を必須にする", value=True)

# --------------------------------------------------
# 5. 同時勤務NG（重なってほしくない）ペアの設定
# --------------------------------------------------
st.header("4. 同時出勤NGペアの設定（オプション）")
st.caption("💡 同じ日に一緒に働かせたくない（または同じシフトに入ってほしくない）スタッフの組み合わせがあれば設定できます。")

col_p1, col_p2 = st.columns(2)
with col_p1:
    exclude_staff1 = st.selectbox("スタッフ1 (ペアA)", ["なし"] + staff_list, key="ex1")
with col_p2:
    exclude_staff2 = st.selectbox("スタッフ2 (ペアB)", ["なし"] + staff_list, key="ex2")

# --------------------------------------------------
# 6. 希望休・個別シフト入力
# --------------------------------------------------
st.header("5. スタッフごとの勤務希望（希望休・指定シフト）入力")
st.caption("💡 入力方法: 固定したいマスに半角/全角で名称（例: `公休`, `有休`, `早出`, `日勤`, `遅出`, `夜勤`）を直接入力してください。空欄は自動調整されます。")

init_data = {f"{d}日": [""] * len(staff_list) for d in days}
df_requests = st.data_editor(pd.DataFrame(init_data, index=staff_list), key="req_table")

# --------------------------------------------------
# 7. シフト自動生成実行
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
            s_max_work = staff_max_work[s] # スタッフごとの最大連勤数

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

            # スタッフごとの個別連勤上限
            for d in range(1, num_days - s_max_work + 1):
                work_sum = lpSum([x[s, d + i, sh] 
                                  for i in range(s_max_work + 1) 
                                  for sh in ["早出", "日勤", "遅出", "夜勤"]])
                model += work_sum <= s_max_work

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

        # --- 同時出勤NGペアの制約 ---
        if exclude_staff1 != "なし" and exclude_staff2 != "なし" and exclude_staff1 != exclude_staff2:
            for d in days:
                work_sh = ["早出", "日勤", "遅出", "夜勤"]
                s1_working = lpSum([x[exclude_staff1, d, sh] for sh in work_sh])
                s2_working = lpSum([x[exclude_staff2, d, sh] for sh in work_sh])
                model += s1_working + s2_working <= 1

        # --- 日ごとの必要人数制約 ---
        for d in days:
            model += lpSum([x[s, d, "早出"] for s in staff_list]) >= req_early
            model += lpSum([x[s, d, "日勤"] for s in staff_list]) >= min_day
            model += lpSum([x[s, d, "日勤"] for s in staff_list]) <= max_day
            model += lpSum([x[s, d, "夜勤"] for s in staff_list]) >= req_night
            model += lpSum([x[s, d, "遅出"] for s in staff_list]) + late_shortage[d] >= req_late

        # 計算実行
        status = model.solve()

        if LpStatus[status] == "Optimal":
            st.success("🎉 シフトを作成しました！")
            
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
            
            short_days = [d for d in days if value(late_shortage[d]) > 0]
            if short_days:
                st.info(f"💡 以下の日は人員調整のため「遅出」を0人（または減員）に調整しました: {', '.join([f'{d}日' for d in short_days])}")
        else:
            st.error("この条件では作成できませんでした。スタッフ人数、希望休、または同時出勤NGの組み合わせが厳しすぎないか見直してください。")
