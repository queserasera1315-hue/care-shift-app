import streamlit as st
import pandas as pd
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, LpStatus, value

# ---------------------------------------------------------
# 1. ページ基本設定
# ---------------------------------------------------------
st.set_page_config(page_title="介護シフト自動作成", layout="centered")
st.title("🏥 介護シフト自動作成アプリ")
st.caption("夜勤→明け→休みルール、公休数、希望休を考慮してシフトを作成します。")

# ---------------------------------------------------------
# 2. 基本条件の設定
# ---------------------------------------------------------
st.subheader("⚙️ 1. 基本条件の設定")

staff_input = st.text_input(
    "スタッフ名（カンマ区切り）", 
    value="Aさん, Bさん, Cさん, Dさん, Eさん, Fさん"
)
staffs = [s.strip() for s in staff_input.split(",") if s.strip()]

num_days = st.number_input("作成日数（日）", min_value=1, max_value=31, value=30)
days = list(range(1, num_days + 1))

# 公休数（純粋な休み）の設定
monthly_holidays = st.number_input("1人あたりの純粋な公休数（日）", min_value=1, max_value=15, value=9)

# ---------------------------------------------------------
# 3. 1日あたりの必要人数（出勤カウント）
# ---------------------------------------------------------
st.subheader("👥 2. 1日あたりの必要人数")
col1, col2 = st.columns(2)
with col1:
    req_hayaban = st.number_input("早番 (7-16)", min_value=0, value=1)
    req_nikkin = st.number_input("日勤 (9-18)", min_value=0, value=1)
with col2:
    req_osoban = st.number_input("遅番 (10-19)", min_value=0, value=1)
    req_yakin = st.number_input("夜勤 (16-9)", min_value=0, value=1)

# シフト定義（夜勤・明けは出勤扱い、休は純粋な公休）
shifts = ["早", "日", "遅", "夜", "明", "休"]

# ---------------------------------------------------------
# 4. 希望休の設定
# ---------------------------------------------------------
st.subheader("📅 3. スタッフごとの希望休設定")
st.caption("純粋な休み（公休）を希望する日付（半角数字）をカンマ区切りで入力してください（例: 5, 12, 20）")

desire_holidays = {}
for s in staffs:
    holiday_str = st.text_input(f"{s} の希望休", value="", key=f"holiday_{s}")
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
    with st.spinner("AIが条件を満たすシフトを計算中..."):
        
        prob = LpProblem("ShiftScheduling", LpMinimize)
        x = {}
        for s in staffs:
            for d in days:
                for shift in shifts:
                    x[s, d, shift] = LpVariable(f"x_{s}_{d}_{shift}", cat="Binary")

        # 制約1: 各スタッフは1日1シフト
        for s in staffs:
            for d in days:
                prob += lpSum([x[s, d, shift] for shift in shifts]) == 1

        # 制約2: 夜勤(16-9)の翌日は必ず「明（出勤扱い）」
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "明"] >= x[s, d, "夜"]

        # 制約3: 「明」の翌日は必ず「休（純粋な公休）」
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "休"] >= x[s, d, "明"]

        # 制約4: 公休数は「休」の回数のみでぴったりカウント（「明」は含めない）
        for s in staffs:
            prob += lpSum([x[s, d, "休"] for d in days]) == monthly_holidays

        # 制約5: 希望休の反映（指定日は必ず「休」）
        for s in staffs:
            for d in desire_holidays[s]:
                prob += x[s, d, "休"] == 1

        # 制約6: 各シフトの必要人数の確保
        for d in days:
            prob += lpSum([x[s, d, "早"] for s in staffs]) >= req_hayaban
            prob += lpSum([x[s, d, "日"] for s in staffs]) >= req_nikkin
            prob += lpSum([x[s, d, "遅"] for s in staffs]) >= req_osoban
            prob += lpSum([x[s, d, "夜"] for s in staffs]) >= req_yakin

        # 目的関数: 夜勤回数の平準化（特定の労働者に偏らないように分散）
        prob += lpSum([x[s, d, "夜"] for s in staffs for d in days])

        # 計算実行
        status = prob.solve()

        # ---------------------------------------------------------
        # 6. 結果の表示・ダウンロード
        # ---------------------------------------------------------
        if LpStatus[status] == "Optimal":
            st.success("✅ シフト表を作成しました！（「明」は出勤扱い、「休」のみ公休として9日カウント）")
            
            result_data = {}
            for s in staffs:
                s_shifts = []
                for d in days:
                    for shift in shifts:
                        if value(x[s, d, shift]) == 1:
                            s_shifts.append(shift)
                result_data[s] = s_shifts
            
            df = pd.DataFrame(result_data, index=[f"{d}日" for d in days]).T
            st.dataframe(df, use_container_width=True)
            
            csv = df.to_csv().encode('utf-8-sig')
            st.download_button(
                label="📥 CSVでダウンロード",
                data=csv,
                file_name="シフト表.csv",
                mime="text/csv"
            )
        else:
            st.error("❌ 条件を満たすシフトを作成できませんでした。スタッフ人数に対して必要人数が多いか、希望休が重なりすぎている可能性があります。")

