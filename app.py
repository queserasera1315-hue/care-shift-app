import streamlit as st
import pandas as pd
import datetime
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, LpStatus, value
import io

# --------------------------------------------------
# 1. ページ基本設定
# --------------------------------------------------
st.set_page_config(page_title="介護シフト自動作成アプリ", layout="wide")
st.title("🏥 介護シフト自動作成アプリ（完全版）")

# --------------------------------------------------
# 2. 基本設定（人数・年月）
# --------------------------------------------------
st.header("⚙️ 1. 基本設定・スタッフ人数")

col_m, col_y, col_num = st.columns(3)
with col_m:
    today = datetime.date.today()
    year = st.number_input("年", min_value=2024, max_value=2030, value=today.year)
with col_y:
    month = st.number_input("月", min_value=1, max_value=12, value=today.month)
with col_num:
    num_staff = st.slider("スタッフ人数", min_value=6, max_value=8, value=7, key="main_staff_slider")

# 月の日数を計算
if month in [1, 3, 5, 7, 8, 10, 12]:
    num_days = 31
elif month in [4, 6, 9, 11]:
    num_days = 30
else:
    num_days = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28

days = list(range(1, num_days + 1))

all_staff_pool = ["スタッフA", "スタッフB", "スタッフC", "スタッフD", "スタッフE", "スタッフF", "スタッフG", "スタッフH"]
staff_list = all_staff_pool[:num_staff]

st.info(f"現在の対象スタッフ ({num_staff}人): **{', '.join(staff_list)}**")

shifts = ["早出", "日勤", "遅出", "夜勤", "明け", "公休"]
work_shifts = ["早出", "日勤", "遅出", "夜勤"]

# --------------------------------------------------
# 3. スタッフの個別設定（働き方 ＆ 連勤上限）
# --------------------------------------------------
st.header("2. スタッフの個別設定（働き方・連勤上限）")
st.caption("※ 夜勤専従1人、遅出パート1人、残りは通常スタッフとして設定してください。")

work_types = {}
staff_max_work = {}

for s in staff_list:
    st.markdown(f"**👤 {s}**")
    c1, c2 = st.columns(2)
    with c1:
        work_types[s] = st.selectbox(
            f"勤務区分 ({s})",
            ["通常", "夜勤専従", "遅出パート（月7回以内）", "日勤専従（夜勤不可）"],
            key=f"wt_{s}"
        )
    with c2:
        staff_max_work[s] = st.number_input(
            f"最大連勤数 ({s})",
            min_value=1, max_value=10, value=5,
            key=f"mw_{s}"
        )
    st.markdown("---")

# --------------------------------------------------
# 4. 1日の必要人数 ＆ 共通ルール
# --------------------------------------------------
st.header("3. 1日の必要人数 ＆ 共通ルール")
col_req1, col_req2, col_req3, col_req4 = st.columns(4)
with col_req1:
    req_early = st.number_input("早出 (人/日)", min_value=0, value=1)
with col_req2:
    req_day = st.number_input("日勤 (人/日)", min_value=0, value=0)
with col_req3:
    req_late = st.number_input("遅出 (人/日)", min_value=0, value=1)
with col_req4:
    req_night = st.number_input("夜勤 (人/日)", min_value=0, value=1)

col_r1, col_r2 = st.columns(2)
with col_r1:
    target_off = st.number_input("月間公休数 (通常・日勤専従)", min_value=0, value=9)
with col_r2:
    max_night_normal = st.number_input("月間夜勤上限 (通常スタッフ)", min_value=0, value=4)

# --------------------------------------------------
# 5. シフト別の組み合わせNGペアの設定（オプション）
# --------------------------------------------------
st.header("4. シフト別・同時勤務NGペアの設定（オプション）")
col_sp1, col_sp2, col_sp3, col_sp4 = st.columns(4)
with col_sp1:
    pair1_staff1 = st.selectbox("スタッフ1 (ペア1)", ["なし"] + staff_list, key="p1_s1")
with col_sp2:
    pair1_shift1 = st.selectbox("シフト1 (ペア1)", work_shifts, key="p1_sh1")
with col_sp3:
    pair1_staff2 = st.selectbox("スタッフ2 (ペア1)", ["なし"] + staff_list, key="p1_s2")
with col_sp4:
    pair1_shift2 = st.selectbox("シフト2 (ペア1)", work_shifts, key="p1_sh2")

col_tp1, col_tp2, col_tp3, col_tp4 = st.columns(4)
with col_tp1:
    pair2_staff1 = st.selectbox("スタッフ1 (ペア2)", ["なし"] + staff_list, key="p2_s1")
with col_tp2:
    pair2_shift1 = st.selectbox("シフト1 (ペア2)", work_shifts, key="p2_sh1")
with col_tp3:
    pair2_staff2 = st.selectbox("スタッフ2 (ペア2)", ["なし"] + staff_list, key="p2_s2")
with col_tp4:
    pair2_shift2 = st.selectbox("シフト2 (ペア2)", work_shifts, key="p2_sh2")

# --------------------------------------------------
# 6. 勤務希望・希望休の入力
# --------------------------------------------------
st.header("5. 勤務希望（希望休・指定シフト）")
st.caption("💡 有休は勝手につきません。希望がある場所だけ『有休』や『公休』を入力してください。空欄は自動で公平に埋まります。")

init_data = {f"{d}日": [""] * len(staff_list) for d in days}
df_requests = st.data_editor(pd.DataFrame(init_data, index=staff_list), key=f"req_table_{num_staff}")

# --------------------------------------------------
# 7. シフト自動生成実行
# --------------------------------------------------
st.markdown("---")

if st.button("🚀 シフトを作成する", type="primary"):
    model = LpProblem("Care_Shift_Scheduling", LpMinimize)
    
    all_shifts_with_paid = shifts + ["有休"]
    x = {(s, d, sh): LpVariable(f"x_{s}_{d}_{sh}", cat="Binary") 
         for s in staff_list for d in days for sh in all_shifts_with_paid}
    
    late_shortage = {d: LpVariable(f"late_shortage_{d}", lowBound=0, cat="Integer") for d in days}

    # ペナルティ設定：遅出不足の防止 ＋ シフト偏り防止（上旬・中旬・下旬の分散 ＆ 満遍なく回すペナルティ）
    model += lpSum([late_shortage[d] * 10000 for d in days])

    for s in staff_list:
        w_type = work_types[s]
        s_max_work = staff_max_work[s]

        # 1日につき必ず1つのシフトが入る
        for d in days:
            model += lpSum([x[s, d, sh] for sh in all_shifts_with_paid]) == 1

        # ユーザーが希望していない日に勝手に「有休」がつかないようにする（希望がある場合のみ1）
        for d in days:
            val = str(df_requests.loc[s, f"{d}日"]).strip()
            if val == "有休":
                model += x[s, d, "有休"] == 1
            else:
                model += x[s, d, "有休"] == 0

            # その他の希望（公休や指定シフト）の反映
            if val in shifts:
                model += x[s, d, val] == 1

        # 働き方別の個別ルール
        if w_type == "夜勤専従":
            for d in days:
                model += x[s, d, "早出"] == 0
                model += x[s, d, "日勤"] == 0
                model += x[s, d, "遅出"] == 0
            model += lpSum([x[s, d, "夜勤"] for d in days]) >= 7
            model += lpSum([x[s, d, "夜勤"] for d in days]) <= 9
            model += lpSum([x[s, d, "公休"] for d in days]) == num_days - (lpSum([x[s, d, "夜勤"] for d in days]) + lpSum([x[s, d, "明け"] for d in days]))

        elif w_type == "遅出パート（月7回以内）":
            for d in days:
                model += x[s, d, "早出"] == 0
                model += x[s, d, "日勤"] == 0
                model += x[s, d, "夜勤"] == 0
                model += x[s, d, "明け"] == 0
            model += lpSum([x[s, d, "遅出"] for d in days]) <= 7
            model += lpSum([x[s, d, "公休"] for d in days]) == num_days - lpSum([x[s, d, "遅出"] for d in days])

        elif w_type == "日勤専従（夜勤不可）":
            for d in days:
                model += x[s, d, "夜勤"] == 0
                model += x[s, d, "明け"] == 0
            model += lpSum([x[s, d, "公休"] for d in days]) == target_off

        else:  # 通常スタッフ
            model += lpSum([x[s, d, "公休"] for d in days]) == target_off
            model += lpSum([x[s, d, "夜勤"] for d in days]) <= max_night_normal
            
            # 通常スタッフは上旬(1〜10)、中旬(11〜20)、下旬(21〜末)で極端に夜勤や早出が偏らないように分散させる
            third_len = num_days // 3
            model += lpSum([x[s, d, "夜勤"] for d in range(1, third_len + 1)]) <= 2
            model += lpSum([x[s, d, "夜勤"] for d in range(third_len + 1, third_len * 2 + 1)]) <= 2

        # 最大連勤数の制限
        for d in range(1, num_days - s_max_work + 1):
            work_sum = lpSum([x[s, d + i, sh] 
                              for i in range(s_max_work + 1) 
                              for sh in work_shifts])
            model += work_sum <= s_max_work

        # 安全・健康管理ルール（夜勤セット ＆ 明け翌日の強制休み）
        for d in range(1, num_days):
            model += x[s, d, "夜勤"] <= x[s, d + 1, "明け"]
            model += x[s, d + 1, "明け"] <= x[s, d, "夜勤"]
            model += x[s, d, "明け"] <= x[s, d + 1, "公休"] + x[s, d + 1, "有休"]

        # 夜勤の連続を禁止
        for d in days[:-1]:
            model += x[s, d, "夜勤"] + x[s, d + 1, "夜勤"] <= 1

        # 遅出→早出の禁止
        for d in days[:-1]:
            model += x[s, d, "遅出"] + x[s, d + 1, "早出"] <= 1

    # NGペアの制約
    if pair1_staff1 != "なし" and pair1_staff2 != "なし" and pair1_staff1 != pair1_staff2:
        for d in days:
            model += x[pair1_staff1, d, pair1_shift1] + x[pair1_staff2, d, pair1_shift2] <= 1

    if pair2_staff1 != "なし" and pair2_staff2 != "なし" and pair2_staff1 != pair2_staff2:
        for d in days:
            model += x[pair2_staff1, d, pair2_shift1] + x[pair2_staff2, d, pair2_shift2] <= 1

    # 1日あたりの必要人数チェック
    for d in days:
        model += lpSum([x[s, d, "早出"] for s in staff_list]) >= req_early
        if req_day > 0:
            model += lpSum([x[s, d, "日勤"] for s in staff_list]) >= req_day
        model += lpSum([x[s, d, "夜勤"] for s in staff_list]) >= req_night
        model += lpSum([x[s, d, "遅出"] for s in staff_list]) + late_shortage[d] >= req_late

    status = model.solve()

    if LpStatus[status] == "Optimal":
        st.success("🎉 シフトが綺麗に作成できました！")
        
        result = {}
        for s in staff_list:
            row = []
            for d in days:
                for sh in all_shifts_with_paid:
                    if value(x[s, d, sh]) > 0.5:
                        row.append(sh)
                        break
            result[s] = row
        
        df_res = pd.DataFrame(result, index=[f"{d}日" for d in days]).T
        
        tab1, tab2 = st.tabs(["📅 シフト表 ＆ 日別人数", "📊 スタッフ別 月間回数集計サマリー"])
        
        with tab1:
            st.subheader("月間シフト一覧")
            st.dataframe(df_res, use_container_width=True)
            
            st.subheader("📅 日別の配置人数チェック（早出・日勤・遅出・夜勤）")
            daily_counts = {}
            for d in days:
                d_key = f"{d}日"
                daily_counts[d_key] = {
                    "早出": sum(1 for s in staff_list if result[s][d-1] == "早出"),
                    "日勤": sum(1 for s in staff_list if result[s][d-1] == "日勤"),
                    "遅出": sum(1 for s in staff_list if result[s][d-1] == "遅出"),
                    "夜勤": sum(1 for s in staff_list if result[s][d-1] == "夜勤"),
                }
            df_daily = pd.DataFrame(daily_counts)
            st.dataframe(df_daily, use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_res.to_excel(writer, sheet_name='シフト表')
                df_daily.to_excel(writer, sheet_name='日別人数')
            output.seek(0)
            
            st.download_button(
                label="📥 シフト表 ＆ 日別人数をExcelでダウンロード",
                data=output,
                file_name=f"{year}年{month}月_シフト表.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        with tab2:
            st.subheader("スタッフ別 月間回数集計サマリー")
            summary_data = []
            count_shifts = ["早出", "日勤", "遅出", "夜勤", "明け", "公休", "有休"]
            for s in staff_list:
                s_counts = {sh: list(result[s]).count(sh) for sh in count_shifts}
                s_counts["スタッフ名"] = s
                s_counts["実出勤日数"] = s_counts.get("早出", 0) + s_counts.get("日勤", 0) + s_counts.get("遅出", 0) + s_counts.get("夜勤", 0)
                summary_data.append(s_counts)
            
            df_summary = pd.DataFrame(summary_data)
            cols_order = ["スタッフ名", "実出勤日数", "早出", "日勤", "遅出", "夜勤", "明け", "公休", "有休"]
            df_summary = df_summary[[c for c in cols_order if c in df_summary.columns]]
            
            st.dataframe(df_summary.set_index("スタッフ名"), use_container_width=True)

        short_days = [d for d in days if value(late_shortage[d]) > 0]
        if short_days:
            st.warning(f"💡 一部の日程で人員調整のため「遅出」を0人に調整した日があります: {', '.join([f'{d}日' for d in short_days])}")
            
    else:
        st.error("この条件では作成できませんでした。スタッフの人数や希望休のバランスを確認してください。")
